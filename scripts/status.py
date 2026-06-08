import csv
from collections import defaultdict

rows = []
with open("logs/shadow_exits.csv", "r", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))


def pnl(r):
    return float(r["profit_per_share"])


total = sum(pnl(r) for r in rows)
wins = [r for r in rows if pnl(r) > 0]
losses = [r for r in rows if pnl(r) <= 0]
print(
    f"TOTAL n={len(rows)}  W={len(wins)}  L={len(losses)}  "
    f"WR={len(wins)/len(rows):.1%}  net=${total:+.2f}  "
    f"mean=${total/len(rows):+.3f}"
)
print()

for keyfn, label in [(lambda r: r["symbol"], "symbol"), (lambda r: r["side"], "side")]:
    g = defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(r)
    print(f"-- by {label} --")
    for k in sorted(g):
        gs = g[k]
        w = sum(1 for r in gs if pnl(r) > 0)
        n = len(gs)
        net = sum(pnl(r) for r in gs)
        print(f"  {k:8s} n={n:3d}  W={w:2d}  L={n-w:2d}  WR={w/n:.0%}  net=${net:+.2f}")
    print()

print("-- last 5 trades (ts_iso is UTC; ET = -4h) --")
for r in rows[-5:]:
    print(
        f"  {r['ts_iso']}  {r['symbol']:7s} {r['side']:4s}  "
        f"entry={float(r['entry_price']):.3f} exit={float(r['exit_price']):.3f} "
        f"pnl={pnl(r):+.3f}  {r['exit_type']}"
    )
