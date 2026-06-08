"""Tiny inventory of the local chainlink price CSVs."""
import csv
import glob
import os
from collections import defaultdict

files = sorted(glob.glob("logs/chainlink_prices_*.csv"))
print(f"files: {len(files)}")
for f in files:
    size = os.path.getsize(f)
    print(f"\n=== {f}  ({size/1e6:.2f} MB) ===")
    with open(f, "r") as fh:
        rdr = csv.reader(fh)
        header = next(rdr)
        print(f"  header: {header}")
        n = 0
        per_sym = defaultdict(int)
        first_ts = {}
        last_ts = {}
        last_row = None
        first_row = None
        for row in rdr:
            n += 1
            if first_row is None:
                first_row = row
            last_row = row
            try:
                ts = float(row[0])
                sym = row[1]
            except Exception:
                continue
            per_sym[sym] += 1
            first_ts.setdefault(sym, ts)
            last_ts[sym] = ts
        print(f"  rows: {n}")
        print(f"  first row: {first_row}")
        print(f"  last  row: {last_row}")
        for sym in sorted(per_sym):
            ft = first_ts[sym]
            lt = last_ts[sym]
            dur_h = (lt - ft) / 3600.0
            rate = per_sym[sym] / max(1.0, (lt - ft))
            print(f"  {sym:6s}  n={per_sym[sym]:7d}  span={dur_h:6.2f}h  rate={rate:.2f} rows/s  ts=[{ft:.0f},{lt:.0f}]")
