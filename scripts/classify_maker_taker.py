"""Classify top-leader fills as MAKER vs TAKER by reading on-chain logs.

For each tx involving a top-N leader:
  - fetch eth_getTransactionReceipt from a public Polygon RPC
  - find OrdersMatched events (topic0 = 0x63bf4d16...)
    * topic2 = takerOrderMaker (the AGGRESSOR who submitted the taker order)
  - if leader's wallet is listed as takerOrderMaker -> TAKER for this tx
  - else                                              -> MAKER

This is the decisive test for whether the leaders' edge is copyable:
- TAKER-dominated leaders: edge from speed/signal -> copyable in principle
- MAKER-dominated leaders: edge from quoting -> NOT copyable
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LEADERS_CSV = ROOT / "logs" / "oos_top_traders.csv"
TRADES_DIR = ROOT / "cache" / "trades"
OUT_CSV = ROOT / "logs" / "maker_taker_classification.csv"

# event OrdersMatched(bytes32 indexed takerOrderHash, address indexed takerOrderMaker, ...)
TOPIC_ORDERS_MATCHED = "0x63bf4d16b7fa898ef4c4b2b6d90fd201e9c56313b65638af6088d149d2ce956c"

RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://1rpc.io/matic",
    "https://polygon.gateway.tenderly.co",
]


def topic_to_addr(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def load_leaders(top: int) -> list[str]:
    out: list[str] = []
    with LEADERS_CSV.open() as f:
        for r in csv.DictReader(f):
            out.append(r["address"].lower())
            if len(out) >= top:
                break
    return out


def sample_fills(leaders: set[str], target_per_leader: int, file_budget: int = 5000) -> list[dict]:
    """Walk random trade-cache files, collect fills involving any leader,
    return up to target_per_leader per leader."""
    files = list(TRADES_DIR.glob("*.json"))
    random.shuffle(files)
    files = files[:file_budget]

    by_leader: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        try:
            trades = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in trades:
            w = (t.get("proxyWallet") or "").lower()
            if w not in leaders:
                continue
            if len(by_leader[w]) >= target_per_leader:
                continue
            by_leader[w].append(t)
        if all(len(v) >= target_per_leader for v in by_leader.values()) and len(by_leader) >= len(leaders):
            break

    flat: list[dict] = []
    for w, lst in by_leader.items():
        flat.extend(lst[:target_per_leader])
    return flat


async def fetch_receipt(client: httpx.AsyncClient, tx: str, rpc_idx: int) -> dict | None:
    rpc = RPCS[rpc_idx % len(RPCS)]
    try:
        r = await client.post(
            rpc,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx]},
            timeout=15.0,
        )
        j = r.json()
        return j.get("result")
    except Exception:
        return None


def classify_receipt(receipt: dict, leader: str) -> str:
    leader = leader.lower()
    aggressors: set[str] = set()
    found_event = False
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if not topics or topics[0].lower() != TOPIC_ORDERS_MATCHED:
            continue
        if len(topics) < 3:
            continue
        found_event = True
        aggressors.add(topic_to_addr(topics[2]))
    if not found_event:
        return "no_match_event"
    return "TAKER" if leader in aggressors else "MAKER"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--per-leader", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    leaders = load_leaders(args.top)
    leader_set = set(leaders)
    print(f"Sampling up to {args.per_leader} fills each for {len(leaders)} leaders...")
    fills = sample_fills(leader_set, args.per_leader)
    print(f"Got {len(fills)} fills across {len({f['proxyWallet'].lower() for f in fills})} leaders.")

    # Group by tx -> set of (leader, fill) needing classification
    by_tx: dict[str, list[dict]] = defaultdict(list)
    for f in fills:
        tx = f.get("transactionHash")
        if tx:
            by_tx[tx].append(f)
    print(f"Unique txs to fetch: {len(by_tx)}")

    sem = asyncio.Semaphore(args.concurrency)
    results: list[tuple[dict, str]] = []
    n_done = 0
    n_err = 0
    t0 = time.time()

    async with httpx.AsyncClient() as client:

        async def process(tx: str, fills_for_tx: list[dict], idx: int) -> None:
            nonlocal n_done, n_err
            async with sem:
                rec = await fetch_receipt(client, tx, idx)
            if not rec:
                n_err += 1
                for ff in fills_for_tx:
                    results.append((ff, "rpc_err"))
                return
            for ff in fills_for_tx:
                cls = classify_receipt(rec, ff["proxyWallet"])
                results.append((ff, cls))
            n_done += 1
            if n_done % 25 == 0:
                rate = n_done / (time.time() - t0)
                print(f"  ... {n_done}/{len(by_tx)} ({rate:.1f} tx/s, {n_err} err)")

        await asyncio.gather(*[
            process(tx, fls, i) for i, (tx, fls) in enumerate(by_tx.items())
        ])

    # Tally per leader
    per_leader: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f, cls in results:
        w = f["proxyWallet"].lower()
        per_leader[w][cls] += 1
        per_leader[w]["_n"] += 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["wallet", "n", "n_TAKER", "n_MAKER", "n_no_event", "n_rpc_err", "pct_taker"])
        rows = []
        for addr, c in per_leader.items():
            n = c["_n"]
            taker = c["TAKER"]
            maker = c["MAKER"]
            noev = c["no_match_event"]
            err = c["rpc_err"]
            denom = taker + maker
            pct = (taker / denom * 100.0) if denom else float("nan")
            rows.append((addr, n, taker, maker, noev, err, pct))
            w.writerow([addr, n, taker, maker, noev, err, f"{pct:.1f}" if pct == pct else ""])

    rows.sort(key=lambda r: -r[6] if r[6] == r[6] else 0)
    print()
    print("=== per-leader classification (top 20 by % taker) ===")
    print(f"{'wallet':44s} {'n':>4s} {'TAKER':>6s} {'MAKER':>6s} {'NOEV':>5s} {'ERR':>4s}  pct_taker")
    for addr, n, t, m, noev, err, pct in rows[:20]:
        pct_s = f"{pct:5.1f}%" if pct == pct else "  n/a"
        print(f"{addr} {n:>4d} {t:>6d} {m:>6d} {noev:>5d} {err:>4d}  {pct_s}")

    # Aggregate
    tot_t = sum(r[2] for r in rows)
    tot_m = sum(r[3] for r in rows)
    tot_n = sum(r[1] for r in rows)
    tot_err = sum(r[5] for r in rows)
    tot_noev = sum(r[4] for r in rows)
    print()
    print("=== aggregate ===")
    print(f"total fills examined: {tot_n}")
    print(f"  TAKER: {tot_t} ({tot_t / max(tot_t + tot_m, 1) * 100:.1f}% of classified)")
    print(f"  MAKER: {tot_m} ({tot_m / max(tot_t + tot_m, 1) * 100:.1f}%)")
    print(f"  no OrdersMatched event: {tot_noev}")
    print(f"  rpc errors: {tot_err}")
    print(f"  output: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
