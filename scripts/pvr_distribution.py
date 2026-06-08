"""One-off: compute percent_vol_ratio distribution per symbol from bot.log."""
import re
from collections import defaultdict

pat_sym = re.compile(r"symbol=(\w+)")
pat_pvr = re.compile(r"percent_vol_ratio=([\d.eE+-]+)")
pat_rv = re.compile(r"raw_vol=([\d.eE+-]+)")

vals = defaultdict(list)
raw_vols = defaultdict(list)
n_lines = 0
with open("logs/bot.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "percent_vol_ratio=" not in line:
            continue
        n_lines += 1
        ms = pat_sym.search(line)
        mp = pat_pvr.search(line)
        if not (ms and mp):
            continue
        try:
            v = float(mp.group(1))
        except ValueError:
            continue
        vals[ms.group(1)].append(v)
        mr = pat_rv.search(line)
        if mr:
            try:
                raw_vols[ms.group(1)].append(float(mr.group(1)))
            except ValueError:
                pass

print(f"Scanned {n_lines} lines containing percent_vol_ratio=")
print()
print(f"{'sym':7s} {'n':>7s}  {'p50':>8s} {'p90':>8s} {'p95':>8s} {'p99':>8s} {'max':>10s}   {'%>28':>6s}  {'%>100':>6s}  {'%>200':>6s}")
for sym in sorted(vals):
    xs = sorted(vals[sym])
    n = len(xs)
    def pct(p):
        return xs[min(n - 1, int(n * p))]
    over28 = sum(1 for x in xs if x > 28) / n * 100
    over100 = sum(1 for x in xs if x > 100) / n * 100
    over200 = sum(1 for x in xs if x > 200) / n * 100
    print(f"{sym:7s} {n:7d}  {pct(0.50):8.2f} {pct(0.90):8.2f} {pct(0.95):8.2f} {pct(0.99):8.2f} {max(xs):10.2f}   {over28:6.1f}  {over100:6.1f}  {over200:6.1f}")

print()
print("raw_vol stats per symbol:")
for sym in sorted(raw_vols):
    xs = sorted(raw_vols[sym])
    if not xs:
        continue
    n = len(xs)
    def pct(p):
        return xs[min(n - 1, int(n * p))]
    zeros = sum(1 for x in xs if x == 0) / n * 100
    print(f"  {sym:7s} n={n:6d}  raw_vol p50={pct(0.50):.6f}  p10={pct(0.10):.6f}  pct_zero={zeros:.1f}%")
