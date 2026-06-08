"""Detailed look at UP-side trades to find the failure pattern."""
import csv
from collections import defaultdict


with open("logs/shadow_exits.csv", "r", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))


def f(r, k, default=None):
    try:
        return float(r[k])
    except (ValueError, KeyError, TypeError):
        return default


up = [r for r in rows if r["side"] == "UP"]
dn = [r for r in rows if r["side"] == "DOWN"]

print(f"UP n={len(up)}  W={sum(1 for r in up if f(r,'profit_per_share')>0)}")
print(f"DOWN n={len(dn)}  W={sum(1 for r in dn if f(r,'profit_per_share')>0)}")
print()

# 1. all UP trades, ordered by time
print("== ALL UP TRADES (chronological) ==")
print(
    f"{'ts_iso':27s} {'sym':7s} {'entry':>5s} {'exit':>5s} "
    f"{'pnl':>6s} {'rr':>5s} {'qual':>6s} {'hold_s':>6s} {'exit_type':15s}"
)
for r in sorted(up, key=lambda r: r["ts_iso"]):
    print(
        f"{r['ts_iso']:27s} {r['symbol']:7s} "
        f"{f(r,'entry_price'):5.2f} {f(r,'exit_price'):5.2f} "
        f"{f(r,'profit_per_share'):+6.2f} {f(r,'signal_rr'):5.2f} "
        f"{f(r,'signal_quality'):6.0f} {f(r,'hold_seconds'):6.0f} "
        f"{r['exit_type']:15s}"
    )

# 2. by symbol+side
print("\n== UP by symbol ==")
g = defaultdict(list)
for r in up:
    g[r["symbol"]].append(r)
for sym in sorted(g):
    rs = g[sym]
    w = sum(1 for r in rs if f(r, "profit_per_share") > 0)
    net = sum(f(r, "profit_per_share") for r in rs)
    print(f"  {sym:8s} n={len(rs):2d}  W={w}  net=${net:+.2f}")

# 3. UP exit types
print("\n== UP exit types ==")
g = defaultdict(list)
for r in up:
    g[r["exit_type"]].append(r)
for k in sorted(g):
    rs = g[k]
    w = sum(1 for r in rs if f(r, "profit_per_share") > 0)
    net = sum(f(r, "profit_per_share") for r in rs)
    print(f"  {k:18s} n={len(rs):2d}  W={w}  net=${net:+.2f}")

# 4. The one UP winner
print("\n== UP winners ==")
for r in [r for r in up if f(r, "profit_per_share") > 0]:
    print(f"  {r}")

# 5. DOWN winners stats vs losers
print("\n== DOWN side detail ==")
print(
    f"{'ts_iso':27s} {'sym':7s} {'entry':>5s} {'exit':>5s} "
    f"{'pnl':>6s} {'hold_s':>6s} {'exit_type':15s}"
)
for r in sorted(dn, key=lambda r: r["ts_iso"]):
    print(
        f"{r['ts_iso']:27s} {r['symbol']:7s} "
        f"{f(r,'entry_price'):5.2f} {f(r,'exit_price'):5.2f} "
        f"{f(r,'profit_per_share'):+6.2f} {f(r,'hold_seconds'):6.0f} "
        f"{r['exit_type']:15s}"
    )
