"""Live latency probe for top Polymarket leaders.

For ~run-duration seconds, polls data-api/trades for each top-N leader on a
fixed interval and records:
  - detection_lag_s   = (now - trade.timestamp) seconds when we first see a fill
  - For each new fill, fetches CLOB orderbook for that token and records
    best_bid, best_ask, mid, top-3 depth, and the implied taker fill price for
    the leader's side & size.
  - leader_price (from trade record) vs live_book_taker_price -> adverse slippage.

Output: logs/latency_probe.csv (append mode), stdout running summary.

Usage:
    .\.venv\Scripts\python.exe scripts/latency_probe.py --top 50 --poll-secs 2 --duration-mins 60
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
LEADERS_CSV = ROOT / "logs" / "oos_top_traders.csv"
OUT_CSV = ROOT / "logs" / "latency_probe.csv"

DATA_API = "https://data-api.polymarket.com/trades"
CLOB_BOOK = "https://clob.polymarket.com/book"

UA = {"User-Agent": "polyou-latency-probe/1.0"}


def load_leaders(path: Path, top: int) -> list[str]:
    addrs: list[str] = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            addrs.append(row["address"].lower())
            if len(addrs) >= top:
                break
    return addrs


async def fetch_recent_trades(
    client: httpx.AsyncClient, wallet: str, limit: int = 20
) -> list[dict[str, Any]]:
    try:
        r = await client.get(
            DATA_API,
            params={"user": wallet, "limit": limit},
            headers=UA,
            timeout=8.0,
        )
        if r.status_code != 200:
            return []
        return r.json() or []
    except Exception:
        return []


async def fetch_book(client: httpx.AsyncClient, token_id: str) -> dict[str, Any] | None:
    try:
        r = await client.get(
            CLOB_BOOK, params={"token_id": token_id}, headers=UA, timeout=5.0
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def book_taker_price(book: dict[str, Any], side: str, size: float) -> tuple[float, float, float, float, float]:
    """Walk the book on the side a taker would hit. Returns
    (taker_avg_price, best_bid, best_ask, depth_top3_bids, depth_top3_asks)."""
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    # Polymarket CLOB returns bids/asks as [{"price": "0.42", "size": "100"}, ...]
    bids_p = [(float(x["price"]), float(x["size"])) for x in bids]
    asks_p = [(float(x["price"]), float(x["size"])) for x in asks]
    bids_p.sort(key=lambda x: -x[0])
    asks_p.sort(key=lambda x: x[0])

    best_bid = bids_p[0][0] if bids_p else 0.0
    best_ask = asks_p[0][0] if asks_p else 1.0
    depth_bids = sum(s for _, s in bids_p[:3])
    depth_asks = sum(s for _, s in asks_p[:3])

    levels = asks_p if side == "BUY" else bids_p
    remaining = size
    cost = 0.0
    filled = 0.0
    for px, sz in levels:
        take = min(remaining, sz)
        cost += take * px
        filled += take
        remaining -= take
        if remaining <= 0:
            break
    avg = cost / filled if filled > 0 else float("nan")
    return avg, best_bid, best_ask, depth_bids, depth_asks


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--poll-secs", type=float, default=2.0)
    ap.add_argument("--duration-mins", type=float, default=60.0)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()

    leaders = load_leaders(LEADERS_CSV, args.top)
    print(f"Tracking {len(leaders)} leaders, poll every {args.poll_secs}s, "
          f"for {args.duration_mins} min.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    new_file = not OUT_CSV.exists()
    out_f = OUT_CSV.open("a", newline="")
    writer = csv.writer(out_f)
    if new_file:
        writer.writerow([
            "now_ts", "wallet", "tx", "trade_ts", "detection_lag_s",
            "asset", "slug", "side", "size", "leader_price",
            "best_bid", "best_ask", "depth_bids_top3", "depth_asks_top3",
            "live_taker_price", "adverse_slippage",
        ])

    seen_tx: set[str] = set()
    sem = asyncio.Semaphore(args.concurrency)
    deadline = time.time() + args.duration_mins * 60.0
    n_fills = 0
    n_priced = 0
    lag_sum = 0.0
    slip_sum = 0.0

    async with httpx.AsyncClient(http2=False) as client:

        async def poll_one(w: str) -> list[dict[str, Any]]:
            async with sem:
                return await fetch_recent_trades(client, w, 20)

        # warmup: load existing tx hashes so we only react to truly NEW fills
        warm = await asyncio.gather(*[poll_one(w) for w in leaders])
        for trades in warm:
            for t in trades:
                tx = t.get("transactionHash")
                if tx:
                    seen_tx.add(tx)
        print(f"Warmup: {len(seen_tx)} pre-existing tx hashes ignored.")

        while time.time() < deadline:
            t0 = time.time()
            polls = await asyncio.gather(*[poll_one(w) for w in leaders])
            new_fills: list[dict[str, Any]] = []
            for w, trades in zip(leaders, polls):
                for t in trades:
                    tx = t.get("transactionHash")
                    if not tx or tx in seen_tx:
                        continue
                    seen_tx.add(tx)
                    t["_wallet"] = w
                    t["_detected_at"] = time.time()
                    new_fills.append(t)

            # price each new fill against live book
            async def price_one(t: dict[str, Any]) -> None:
                nonlocal n_priced, slip_sum
                token_id = t.get("asset")
                if not token_id:
                    return
                async with sem:
                    book = await fetch_book(client, str(token_id))
                if not book:
                    return
                side = str(t.get("side", "BUY")).upper()
                size = float(t.get("size", 0.0))
                leader_px = float(t.get("price", 0.0))
                avg, bb, ba, db, da = book_taker_price(book, side, size)
                # Adverse slippage in prob units (positive = worse for copier).
                if side == "BUY":
                    slip = avg - leader_px  # paying more is worse
                else:
                    slip = leader_px - avg  # receiving less is worse
                t["_book"] = (avg, bb, ba, db, da, slip)
                n_priced += 1
                if avg == avg:  # not nan
                    slip_sum += slip

            await asyncio.gather(*[price_one(t) for t in new_fills])

            # write rows
            for t in new_fills:
                lag = t["_detected_at"] - float(t["timestamp"])
                lag_sum += lag
                n_fills += 1
                book = t.get("_book")
                if book:
                    avg, bb, ba, db, da, slip = book
                else:
                    avg = bb = ba = db = da = slip = float("nan")
                writer.writerow([
                    f"{t['_detected_at']:.3f}", t["_wallet"], t.get("transactionHash"),
                    t.get("timestamp"), f"{lag:.3f}",
                    t.get("asset"), t.get("slug"), t.get("side"),
                    t.get("size"), t.get("price"),
                    f"{bb:.4f}", f"{ba:.4f}", f"{db:.2f}", f"{da:.2f}",
                    f"{avg:.4f}", f"{slip:.4f}",
                ])
            out_f.flush()

            elapsed_loop = time.time() - t0
            if new_fills:
                lag_mean = lag_sum / max(n_fills, 1)
                slip_mean = slip_sum / max(n_priced, 1)
                print(f"[{time.strftime('%H:%M:%S')}] +{len(new_fills)} fills "
                      f"({elapsed_loop:.2f}s loop) | total {n_fills} | "
                      f"mean lag {lag_mean:.2f}s | priced {n_priced} | "
                      f"mean adverse slip {slip_mean:+.4f}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] (no new) {elapsed_loop:.2f}s loop")

            sleep_for = max(0.0, args.poll_secs - elapsed_loop)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    out_f.close()
    print("\n=== summary ===")
    print(f"total new fills:    {n_fills}")
    print(f"priced vs live book:{n_priced}")
    if n_fills:
        print(f"mean detection lag: {lag_sum / n_fills:.2f}s")
    if n_priced:
        print(f"mean adverse slip:  {slip_sum / n_priced:+.4f} (prob units)")
    print(f"output: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
