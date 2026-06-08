"""Parse logs/bot.log for enriched exhaustion_ok block lines and report
per-symbol distributions of vol_ratio and percent_vol_ratio."""
import re
from collections import defaultdict

PAT = re.compile(
    r"symbol=(\w+)\s+side=(\w+)\s+"
    r"raw_vol=([\d.eE+-]+)\s+"
    r"percent_move=([\d.eE+-]+)\s+"
    r"vol_ratio=([\d.eE+-]+)\s+"
    r"percent_vol_ratio=([\d.eE+-]+)\s+"
    r"vrcap=([\d.eE+-]+)\s+"
    r"pvrcap=([\d.eE+-]+)"
)


def pct(xs, q):
    if not xs:
        return float("nan")
    xs2 = sorted(xs)
    i = min(len(xs2) - 1, int(len(xs2) * q))
    return xs2[i]


def report(label, xs, cap):
    n = len(xs)
    if n == 0:
        print(f"  {label:20s} n=0")
        return
    p50 = pct(xs, 0.50)
    p90 = pct(xs, 0.90)
    p95 = pct(xs, 0.95)
    p99 = pct(xs, 0.99)
    mx = max(xs)
    pct_above = 100.0 * sum(1 for x in xs if x > cap) / n
    print(
        f"  {label:20s} n={n:5d}  p50={p50:8.3f}  p90={p90:8.3f}  "
        f"p95={p95:8.3f}  p99={p99:8.3f}  max={mx:8.3f}  "
        f"%>cap({cap:g})={pct_above:5.1f}%"
    )


def main():
    by_sym_vr = defaultdict(list)
    by_sym_pvr = defaultdict(list)
    by_sym_rv = defaultdict(list)
    n_lines = 0
    with open("logs/bot.log", "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "Failed exhaustion_ok hard gate" not in line:
                continue
            if "raw_vol=" not in line:
                continue
            m = PAT.search(line)
            if not m:
                continue
            n_lines += 1
            sym, side, rv, pm, vr, pvr, vrcap, pvrcap = m.groups()
            by_sym_vr[sym].append(float(vr))
            by_sym_pvr[sym].append(float(pvr))
            by_sym_rv[sym].append(float(rv))
    print(f"Parsed {n_lines} enriched exhaustion_ok blocks\n")
    for sym in sorted(by_sym_vr):
        print(f"== {sym} ==")
        report("vol_ratio", by_sym_vr[sym], 1.75)
        report("percent_vol_ratio", by_sym_pvr[sym], 28.0)
        report("raw_vol", by_sym_rv[sym], 1e9)  # cap N/A
        print()


if __name__ == "__main__":
    main()
