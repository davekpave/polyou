"""
Profile wallets with statistical significance (>= MIN_TRADES, >= MIN_MARKETS).

Reveal:
  - Win-rate distribution (P&L > 0 share)
  - Avg buy price by P&L bucket
  - Maker vs taker proxy: distance from 0/1 at trade time
  - Concentration vs spread across markets
"""
from __future__ import annotations
import csv
from statistics import mean, median

MIN_TRADES = 30
MIN_MARKETS = 5
PATH = "logs/wallet_pnl.csv"


def main():
    rows = list(csv.DictReader(open(PATH)))
    for r in rows:
        for k in (
            "n_trades",
            "n_markets",
            "size_total",
            "gross_usdc",
            "pnl_usdc",
            "n_buy",
            "n_sell",
            "first_ts",
            "last_ts",
        ):
            r[k] = float(r[k]) if "." in r[k] or k in ("pnl_usdc", "gross_usdc", "size_total") else int(r[k])
        r["avg_price_buy"] = float(r["avg_price_buy"]) if r["avg_price_buy"] else None
        r["avg_price_sell"] = float(r["avg_price_sell"]) if r["avg_price_sell"] else None

    print(f"Total wallets: {len(rows)}")
    sig = [r for r in rows if r["n_trades"] >= MIN_TRADES and r["n_markets"] >= MIN_MARKETS]
    print(f"With >= {MIN_TRADES} trades and >= {MIN_MARKETS} markets: {len(sig)}")

    if not sig:
        return

    pnls = [r["pnl_usdc"] for r in sig]
    print()
    print("--- P&L distribution among 'significant' wallets ---")
    print(f"  net positive: {sum(1 for p in pnls if p > 0)} / {len(sig)} = "
          f"{100*sum(1 for p in pnls if p > 0)/len(sig):.1f}%")
    print(f"  median pnl: ${median(pnls):.2f}")
    print(f"  mean pnl:   ${mean(pnls):.2f}")
    print(f"  total pnl:  ${sum(pnls):.2f}")
    print(f"  total vol:  ${sum(r['gross_usdc'] for r in sig):,.0f}")

    # Bucket by P&L sign
    winners = [r for r in sig if r["pnl_usdc"] > 0]
    losers = [r for r in sig if r["pnl_usdc"] < 0]

    def avg(field, group):
        vals = [r[field] for r in group if r[field] is not None]
        return sum(vals) / len(vals) if vals else None

    print()
    print(f"--- Winners (n={len(winners)}) avg behavior ---")
    print(f"  avg_buy_price (mean of wallet means):  {avg('avg_price_buy', winners):.4f}")
    aps = [r['avg_price_sell'] for r in winners if r['avg_price_sell'] is not None]
    print(f"  avg_sell_price (mean):                  {sum(aps)/len(aps):.4f}" if aps else "  avg_sell_price: n/a")
    print(f"  median trades:                          {median([r['n_trades'] for r in winners]):.0f}")
    print(f"  median markets:                         {median([r['n_markets'] for r in winners]):.0f}")
    print(f"  median size_total:                      {median([r['size_total'] for r in winners]):.0f}")
    print(f"  median gross_usdc:                      {median([r['gross_usdc'] for r in winners]):.0f}")
    sells_pct = [100*r['n_sell']/r['n_trades'] for r in winners]
    print(f"  median %sell of trades:                 {median(sells_pct):.1f}%")

    print()
    print(f"--- Losers (n={len(losers)}) avg behavior ---")
    print(f"  avg_buy_price (mean of wallet means):  {avg('avg_price_buy', losers):.4f}")
    aps = [r['avg_price_sell'] for r in losers if r['avg_price_sell'] is not None]
    print(f"  avg_sell_price (mean):                  {sum(aps)/len(aps):.4f}" if aps else "  avg_sell_price: n/a")
    print(f"  median trades:                          {median([r['n_trades'] for r in losers]):.0f}")
    print(f"  median markets:                         {median([r['n_markets'] for r in losers]):.0f}")
    print(f"  median size_total:                      {median([r['size_total'] for r in losers]):.0f}")
    print(f"  median gross_usdc:                      {median([r['gross_usdc'] for r in losers]):.0f}")
    sells_pct = [100*r['n_sell']/r['n_trades'] for r in losers]
    print(f"  median %sell of trades:                 {median(sells_pct):.1f}%")

    print()
    print("--- Top 20 winners (significant) ---")
    sig_sorted = sorted(sig, key=lambda r: r["pnl_usdc"], reverse=True)
    for r in sig_sorted[:20]:
        print(
            f"  {r['wallet']}  pnl=${r['pnl_usdc']:>9.2f}  "
            f"trades={r['n_trades']:>4}  mkts={r['n_markets']:>3}  "
            f"vol=${r['gross_usdc']:>8.0f}  "
            f"avg_buy={r['avg_price_buy']}  avg_sell={r['avg_price_sell']}  "
            f"%sell={100*r['n_sell']/r['n_trades']:.0f}"
        )


if __name__ == "__main__":
    main()
