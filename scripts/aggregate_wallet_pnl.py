"""
Aggregate trades from cache/trades/*.json into per-wallet P&L using
mark-to-resolution accounting.

Per trade on token T at price p, size s, side S:
  contribution to wallet P&L (in USDC):
    BUY :  (winner==T ?  1-p : -p) * s
    SELL:  (winner==T ?  p-1 :  p) * s

Output:
  logs/wallet_pnl.csv : per-wallet, all 151 markets combined
    wallet, n_trades, n_markets, total_size, gross_volume_usdc,
    pnl_usdc, n_buy, n_sell, avg_price_buy, avg_price_sell,
    first_ts, last_ts
"""
from __future__ import annotations
import csv
import json
from collections import defaultdict
from pathlib import Path

CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
OUT = Path("logs/wallet_pnl.csv")


def main():
    meta = {r["slug"]: r for r in csv.DictReader(open(META))}

    # wallet -> aggregate dict
    wallets = defaultdict(
        lambda: {
            "n_trades": 0,
            "markets": set(),
            "size_total": 0.0,
            "gross_usdc": 0.0,
            "pnl": 0.0,
            "n_buy": 0,
            "n_sell": 0,
            "buy_size_x_price": 0.0,
            "buy_size": 0.0,
            "sell_size_x_price": 0.0,
            "sell_size": 0.0,
            "first_ts": 10**12,
            "last_ts": 0,
        }
    )

    for slug, m in meta.items():
        winner = m["winner_token"]
        if not winner:
            continue
        f = CACHE / f"{slug}.json"
        if not f.exists():
            continue
        trades = json.loads(f.read_text())
        for t in trades:
            wallet = t.get("proxyWallet")
            if not wallet:
                continue
            asset = str(t.get("asset"))
            side = t.get("side")
            try:
                p = float(t.get("price"))
                s = float(t.get("size"))
                ts = int(t.get("timestamp"))
            except (TypeError, ValueError):
                continue
            is_winner = asset == winner
            if side == "BUY":
                pnl = (1 - p) * s if is_winner else -p * s
            elif side == "SELL":
                pnl = (p - 1) * s if is_winner else p * s
            else:
                continue
            w = wallets[wallet]
            w["n_trades"] += 1
            w["markets"].add(slug)
            w["size_total"] += s
            w["gross_usdc"] += p * s
            w["pnl"] += pnl
            if side == "BUY":
                w["n_buy"] += 1
                w["buy_size_x_price"] += p * s
                w["buy_size"] += s
            else:
                w["n_sell"] += 1
                w["sell_size_x_price"] += p * s
                w["sell_size"] += s
            if ts < w["first_ts"]:
                w["first_ts"] = ts
            if ts > w["last_ts"]:
                w["last_ts"] = ts

    rows = []
    for wallet, w in wallets.items():
        rows.append(
            {
                "wallet": wallet,
                "n_trades": w["n_trades"],
                "n_markets": len(w["markets"]),
                "size_total": round(w["size_total"], 4),
                "gross_usdc": round(w["gross_usdc"], 4),
                "pnl_usdc": round(w["pnl"], 4),
                "n_buy": w["n_buy"],
                "n_sell": w["n_sell"],
                "avg_price_buy": round(w["buy_size_x_price"] / w["buy_size"], 4)
                if w["buy_size"]
                else "",
                "avg_price_sell": round(w["sell_size_x_price"] / w["sell_size"], 4)
                if w["sell_size"]
                else "",
                "first_ts": w["first_ts"],
                "last_ts": w["last_ts"],
            }
        )
    rows.sort(key=lambda r: r["pnl_usdc"], reverse=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total_pnl = sum(r["pnl_usdc"] for r in rows)
    total_vol = sum(r["gross_usdc"] for r in rows)
    print(f"Wrote {OUT}: {len(rows)} wallets")
    print(f"Sum PnL across all wallets (should ≈ 0 minus fees): {total_pnl:.2f}")
    print(f"Sum gross volume (USDC): {total_vol:,.2f}")
    print()
    print("Top 15 winners:")
    for r in rows[:15]:
        print(
            f"  {r['wallet']}  pnl={r['pnl_usdc']:>10.2f}  trades={r['n_trades']:>5}  "
            f"markets={r['n_markets']:>3}  vol={r['gross_usdc']:>10.0f}  "
            f"avg_buy={r['avg_price_buy']}  avg_sell={r['avg_price_sell']}"
        )
    print()
    print("Top 15 losers:")
    for r in rows[-15:][::-1]:
        print(
            f"  {r['wallet']}  pnl={r['pnl_usdc']:>10.2f}  trades={r['n_trades']:>5}  "
            f"markets={r['n_markets']:>3}  vol={r['gross_usdc']:>10.0f}  "
            f"avg_buy={r['avg_price_buy']}  avg_sell={r['avg_price_sell']}"
        )


if __name__ == "__main__":
    main()
