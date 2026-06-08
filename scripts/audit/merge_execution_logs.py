"""Safely merge execution_log.csv + execution_log.archive.csv into a canonical
narrow-schema combined log.

Approach:
- Reads both source files without modifying them.
- Detects per-row schema by inspecting which column holds a known symbol
  (BTCUSD/ETHUSD/SOLUSD/XRPUSD) and which holds a *-updown-15m-* slug.
- Skips rows where neither can be located (e.g. a header row that survived,
  or a corrupted row with a token_id where 'symbol' should be).
- Emits canonical columns:
    timestamp, symbol, side, contract_slug, snapshot_price, signal_rr, source
- Dedupes on (symbol, contract_slug); when both files have the same key,
  prefers the row with the earliest valid timestamp (the original entry).
- Sorts by timestamp ascending.
- Writes to logs/execution_log.combined.csv (NEW FILE; originals untouched).
"""
from __future__ import annotations

import csv
import os
import sys

KNOWN_SYMBOLS = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"}
SIDES = {"UP", "DOWN"}

SOURCES = [
    ("logs/execution_log.csv", "current"),
    ("logs/execution_log.archive.csv", "archive"),
]
OUT_PATH = "logs/execution_log.combined.csv"


def find_field(row, predicate):
    for i, v in enumerate(row):
        if predicate(v):
            return i, v
    return -1, None


def parse_row(row):
    """Return canonical dict or None if row is unusable."""
    sym_idx, sym = find_field(row, lambda v: v in KNOWN_SYMBOLS)
    slug_idx, slug = find_field(row, lambda v: isinstance(v, str) and "-updown-15m-" in v)
    if sym is None or slug is None:
        return None
    # side: usually one column adjacent to symbol
    side = None
    for j in (sym_idx + 1, sym_idx + 2, sym_idx - 1):
        if 0 <= j < len(row) and row[j] in SIDES:
            side = row[j]
            break
    # timestamp: first column that parses as float > 1e9
    ts = None
    for v in row[:3]:
        try:
            t = float(v)
            if t > 1_000_000_000:
                ts = t
                break
        except (ValueError, TypeError):
            continue
    if ts is None or side is None:
        return None
    # snapshot_price: usually right after slug
    snap = None
    for j in (slug_idx + 1, slug_idx + 2):
        if 0 <= j < len(row):
            try:
                p = float(row[j])
                if 0.0 < p < 1.0:
                    snap = p
                    break
            except (ValueError, TypeError):
                continue
    # signal_rr: first 0..1 float after snapshot
    rr = None
    start = (slug_idx + 2) if snap is not None else (slug_idx + 1)
    for j in range(start, min(start + 3, len(row))):
        try:
            x = float(row[j])
            if 0.0 <= x <= 1.0:
                rr = x
                break
        except (ValueError, TypeError):
            continue
    return {
        "timestamp": ts,
        "symbol": sym,
        "side": side,
        "contract_slug": slug,
        "snapshot_price": snap if snap is not None else "",
        "signal_rr": rr if rr is not None else "",
    }


def main():
    merged = {}  # key=(symbol, slug) -> (canonical_dict, source)
    stats = {}
    for path, src_name in SOURCES:
        if not os.path.exists(path):
            print(f"[skip] {path} not found")
            continue
        kept = skipped = 0
        with open(path, newline="") as f:
            for raw in csv.reader(f):
                row = list(raw)
                if not row:
                    skipped += 1
                    continue
                rec = parse_row(row)
                if rec is None:
                    skipped += 1
                    continue
                key = (rec["symbol"], rec["contract_slug"])
                existing = merged.get(key)
                if existing is None:
                    merged[key] = (rec, src_name)
                    kept += 1
                else:
                    # prefer earliest timestamp (original entry write)
                    if rec["timestamp"] < existing[0]["timestamp"]:
                        merged[key] = (rec, src_name)
        stats[path] = (kept, skipped)
        print(f"[read] {path}: kept={kept} skipped={skipped}")

    rows = sorted(merged.values(), key=lambda x: x[0]["timestamp"])
    fieldnames = ["timestamp", "symbol", "side", "contract_slug",
                  "snapshot_price", "signal_rr", "source"]

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rec, src in rows:
            out = dict(rec)
            out["source"] = src
            w.writerow(out)

    print(f"\n[wrote] {OUT_PATH}")
    print(f"  total unique trades: {len(rows)}")
    by_sym = {}
    for rec, _src in rows:
        by_sym[rec["symbol"]] = by_sym.get(rec["symbol"], 0) + 1
    for s in sorted(by_sym):
        print(f"  {s}: {by_sym[s]}")


if __name__ == "__main__":
    sys.exit(main())
