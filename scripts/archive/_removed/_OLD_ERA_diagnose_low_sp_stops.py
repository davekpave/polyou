"""Diagnose the 14 low-sp (0.50-0.70 entry) STOP_LOSS closures.

For each token:
- Find ALL exit_log rows for that token (the re-logged duplicates) — first/last ts, count.
- Look up the corresponding entry context from execution_log.csv if present.
- Compute time-to-stop = first exit ts - entry ts (when entry available).
- Show entry_price, exit_price, count, span, and whether stop fired well before
  expiry (15-min window) or at the edge.

Also:
- Compare against the 12 winning low-sp TAKE_PROFITs the same way.

Read-only.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXIT_LOG = ROOT / "logs" / "exit_log.csv"
EXEC_LOGS = [
    ROOT / "logs" / "execution_log.csv",
    ROOT / "logs" / "execution_log.v2_partial.csv",
    ROOT / "logs" / "execution_log.combined.csv",
    ROOT / "logs" / "execution_log.archive.csv",
]


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_exits():
    """Group exit rows by token_id; sort each group by timestamp."""
    groups = defaultdict(list)
    with EXIT_LOG.open("r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts = to_float(r.get("timestamp"))
            if ts is None:
                continue
            groups[r["token_id"]].append({
                "ts": ts,
                "type": r.get("type"),
                "entry": to_float(r.get("entry_price")),
                "exit": to_float(r.get("exit_price")),
                "profit_cents": to_float(r.get("profit_cents")),
            })
    for k in groups:
        groups[k].sort(key=lambda x: x["ts"])
    return groups


def load_entries():
    """token_id -> first entry context across all execution log files."""
    entries = {}
    for path in EXEC_LOGS:
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "token_id" not in (reader.fieldnames or []):
                continue
            for r in reader:
                tid = r.get("token_id")
                if not tid or tid in entries:
                    continue
                ts = to_float(r.get("timestamp"))
                entries[tid] = {
                    "ts": ts,
                    "symbol": r.get("symbol"),
                    "side": r.get("side"),
                    "slug": r.get("contract_slug"),
                    "snapshot_price": to_float(r.get("snapshot_price")),
                    "signal_priority": to_float(r.get("signal_priority")),
                    "signal_quality": to_float(r.get("signal_quality")),
                    "signal_age_minutes": to_float(r.get("signal_age_minutes")),
                    "vol_ratio": to_float(r.get("vol_ratio")),
                    "anchor_distance_percent": to_float(r.get("anchor_distance_percent")),
                }
    return entries


def main():
    exits = load_exits()
    entries = load_entries()

    # canonical: take first row per token
    canon = []
    for tid, rows in exits.items():
        first = rows[0]
        canon.append({
            "token_id": tid,
            "type": first["type"],
            "entry": first["entry"],
            "exit": first["exit"],
            "first_exit_ts": first["ts"],
            "last_exit_ts": rows[-1]["ts"],
            "exit_row_count": len(rows),
            "exit_span_seconds": rows[-1]["ts"] - first["ts"],
        })

    def in_band(c, lo, hi):
        return c["entry"] is not None and lo <= c["entry"] < hi

    sl_low = sorted(
        [c for c in canon if c["type"] == "STOP_LOSS" and in_band(c, 0.50, 0.70)],
        key=lambda c: c["first_exit_ts"],
    )
    tp_low = sorted(
        [c for c in canon if c["type"] == "TAKE_PROFIT" and in_band(c, 0.50, 0.70)],
        key=lambda c: c["first_exit_ts"],
    )

    def report(label, items):
        print(f"\n{'='*100}")
        print(f"{label}  (n={len(items)})")
        print(f"{'='*100}")
        print(f"{'#':>2} {'date':<19} {'entry':>5} {'exit':>5} "
              f"{'rows':>4} {'span_s':>7} {'sym':>6} {'side':>4} "
              f"{'tt_stop_min':>11} {'spr':>4} {'spq':>4} {'volr':>5} {'anchΔ%':>7}")
        time_to_stops = []
        had_entry = 0
        for i, c in enumerate(items, 1):
            ent = entries.get(c["token_id"]) or {}
            t_entry = ent.get("ts")
            if t_entry:
                tt_min = (c["first_exit_ts"] - t_entry) / 60
                time_to_stops.append(tt_min)
                had_entry += 1
            else:
                tt_min = None
            d = datetime.fromtimestamp(c["first_exit_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

            def fmt(v, spec, dash):
                return format(v, spec) if v is not None else dash

            tt_s = fmt(tt_min, ">11.1f", "          -")
            spr_s = fmt(ent.get("signal_priority"), ">4.1f", "   -")
            spq_s = fmt(ent.get("signal_quality"), ">4.1f", "   -")
            volr_s = fmt(ent.get("vol_ratio"), ">5.2f", "    -")
            anch_s = fmt(ent.get("anchor_distance_percent"), ">+7.2f", "      -")
            sym_s = (ent.get("symbol") or "-")
            side_s = (ent.get("side") or "-")
            print(f"{i:>2} {d:<19} "
                  f"{c['entry']:>5.2f} {c['exit']:>5.2f} "
                  f"{c['exit_row_count']:>4d} {c['exit_span_seconds']:>7.0f} "
                  f"{sym_s:>6} {side_s:>4} "
                  f"{tt_s} {spr_s} {spq_s} {volr_s} {anch_s}")
        print(f"\n  with execution_log entry: {had_entry}/{len(items)}")
        if time_to_stops:
            avg = sum(time_to_stops) / len(time_to_stops)
            mn = min(time_to_stops)
            mx = max(time_to_stops)
            print(f"  time-to-{('stop' if 'STOP' in label else 'TP')}  avg={avg:.1f}m  min={mn:.1f}m  max={mx:.1f}m")
            # Bucket
            early = sum(1 for t in time_to_stops if t <= 5)
            mid = sum(1 for t in time_to_stops if 5 < t <= 12)
            late = sum(1 for t in time_to_stops if t > 12)
            print(f"  buckets: early(≤5m)={early}  mid(5-12m)={mid}  late(>12m)={late}")
        # exit_row_count statistics
        counts = [c["exit_row_count"] for c in items]
        if counts:
            print(f"  exit_row_count  avg={sum(counts)/len(counts):.1f}  "
                  f"min={min(counts)}  max={max(counts)}")
        spans = [c["exit_span_seconds"] for c in items if c["exit_span_seconds"] > 0]
        if spans:
            print(f"  re-log span (s) avg={sum(spans)/len(spans):.0f}  "
                  f"min={min(spans):.0f}  max={max(spans):.0f}")

    report("STOP_LOSS  entry sp 0.50-0.70  (deduped)", sl_low)
    report("TAKE_PROFIT entry sp 0.50-0.70  (deduped)", tp_low)

    # Also show overall comparison
    print(f"\n{'='*100}")
    print("Aggregate exit_price stats per type+band")
    print(f"{'='*100}")
    for label, items in [("SL low", sl_low), ("TP low", tp_low)]:
        if not items:
            continue
        exits_p = [c["exit"] for c in items]
        entries_p = [c["entry"] for c in items]
        print(f"  {label:7s}  n={len(items):2d}  "
              f"mean_entry={sum(entries_p)/len(entries_p):.3f}  "
              f"mean_exit={sum(exits_p)/len(exits_p):.3f}  "
              f"min_exit={min(exits_p):.3f}  max_exit={max(exits_p):.3f}")


if __name__ == "__main__":
    main()