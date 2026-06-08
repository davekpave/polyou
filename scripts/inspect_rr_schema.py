"""Inspect rr_blocks.csv rows by column count to map schema evolution."""

from collections import defaultdict
from pathlib import Path

p = Path("logs/rr_blocks.csv")
counts: dict[int, int] = defaultdict(int)
first_ts: dict[int, str] = {}
last_ts: dict[int, str] = {}

with p.open("r", encoding="utf-8") as f:
    header = f.readline().rstrip("\n").split(",")
    print(f"header has {len(header)} cols:")
    print(header)
    print()

    for line in f:
        # naive — but first field is always ts_iso ISO8601, no embedded commas
        fields = line.rstrip("\n").split(",")
        n = len(fields)
        counts[n] += 1
        ts = fields[0]
        if n not in first_ts:
            first_ts[n] = ts
        last_ts[n] = ts

print("rows by column count:")
for n in sorted(counts):
    print(f"  {n:3d} cols : {counts[n]:>6,d}   first {first_ts[n]}   last {last_ts[n]}")
