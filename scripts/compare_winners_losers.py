"""Compare signal features for the user-provided 15-trade list (W/L).

The CSV file mixes two row schemas because DictWriter writes whatever keys are
in the dict and the header is fixed once on first write:

  OLD (26 cols, the file's actual header):
    timestamp, token_id, symbol, side, contract_slug, snapshot_price,
    signal_rr, signal_age_minutes, signal_phase, anchor_distance_percent,
    signal_priority, signal_quality, slope_z_24h, structure_vol,
    dynamic_percent_threshold, vol_ratio, percent_vol_ratio,
    extension_pressure, adaptive_drift_cap, drift_ok, exhaustion_ok,
    continuation_override, acceleration_ok, pvr_ideal, pvr_terminal,
    pvr_terminal_cap

  NEW (28 cols, after partial-fill fix added execution_outcome+order_id):
    ...signal_quality, execution_outcome, order_id, slope_z_24h, ...
"""
import csv
import statistics
from pathlib import Path

OUTCOMES = {
    "btc-updown-15m-1777120200": "W",
    "btc-updown-15m-1777143600": "L",
    "btc-updown-15m-1777156200": "W",
    "btc-updown-15m-1777159800": "W",
    "btc-updown-15m-1777215600": "W",
    "btc-updown-15m-1777230000": "L",
    "eth-updown-15m-1777239900": "L",
    "btc-updown-15m-1777241700": "L",
    "eth-updown-15m-1777243500": "W",
    "btc-updown-15m-1777247100": "W",
    "btc-updown-15m-1777251600": "L",
    "eth-updown-15m-1777252500": "W",
    "btc-updown-15m-1777264200": "W",
    "eth-updown-15m-1777269600": "W*",  # partial fill
    "btc-updown-15m-1777275900": "L",
}

OLD_COLS = (
    "timestamp,token_id,symbol,side,contract_slug,snapshot_price,signal_rr,"
    "signal_age_minutes,signal_phase,anchor_distance_percent,signal_priority,"
    "signal_quality,slope_z_24h,structure_vol,dynamic_percent_threshold,"
    "vol_ratio,percent_vol_ratio,extension_pressure,adaptive_drift_cap,"
    "drift_ok,exhaustion_ok,continuation_override,acceleration_ok,"
    "pvr_ideal,pvr_terminal,pvr_terminal_cap"
).split(",")

NEW_COLS = OLD_COLS[:12] + ["execution_outcome", "order_id"] + OLD_COLS[12:]


def parse_row(raw):
    if len(raw) >= len(NEW_COLS):
        return dict(zip(NEW_COLS, raw))
    if len(raw) >= len(OLD_COLS):
        return dict(zip(OLD_COLS, raw))
    return None


rows = {}
for path in [Path("logs/execution_log.archive.csv"), Path("logs/execution_log.csv")]:
    if not path.exists():
        continue
    with path.open() as f:
        reader = csv.reader(f)
        next(reader, None)  # skip stale header
        for raw in reader:
            r = parse_row(raw)
            if r is None:
                continue
            slug = r.get("contract_slug")
            if slug in OUTCOMES and slug not in rows:
                rows[slug] = r

cols = [
    "side", "signal_phase", "signal_age_minutes", "signal_priority",
    "signal_quality", "structure_vol", "dynamic_percent_threshold",
    "anchor_distance_percent", "slope_z_24h", "vol_ratio",
    "percent_vol_ratio", "extension_pressure", "adaptive_drift_cap",
    "continuation_override", "acceleration_ok", "pvr_ideal",
    "pvr_terminal", "pvr_terminal_cap",
]
short = {
    "side": "side", "signal_phase": "phase", "signal_age_minutes": "age",
    "signal_priority": "prio", "signal_quality": "qual",
    "structure_vol": "svol", "dynamic_percent_threshold": "dyn%",
    "anchor_distance_percent": "anch%", "slope_z_24h": "slope",
    "vol_ratio": "vol_r", "percent_vol_ratio": "pvr",
    "extension_pressure": "ext", "adaptive_drift_cap": "drift_c",
    "continuation_override": "cont", "acceleration_ok": "acc",
    "pvr_ideal": "pvi", "pvr_terminal": "pvt",
    "pvr_terminal_cap": "pvtc",
}


def fmt(v):
    if v in ("True", "False", "", None):
        return v or "-"
    try:
        f = float(v)
        if abs(f) >= 100:
            return f"{f:.0f}"
        if abs(f) >= 10:
            return f"{f:.2f}"
        if abs(f) < 0.001 and f != 0:
            return f"{f:.2e}"
        return f"{f:.3f}"
    except Exception:
        return str(v)[:8]


print(f"{'slug':<32} {'W/L':<3} ", end="")
print(" ".join(f"{short[c]:>9}" for c in cols))
for slug, wl in OUTCOMES.items():
    r = rows.get(slug)
    if not r:
        print(f"{slug:<32} {wl:<3} (NOT FOUND)")
        continue
    print(f"{slug:<32} {wl:<3} ", end="")
    print(" ".join(f"{fmt(r.get(c, '-')):>9}" for c in cols))

# Aggregate stats by W vs L (excluding W* partial)
print("\n--- AVG by class (excluding W*) ---")
numeric = [
    "signal_phase", "signal_age_minutes", "signal_priority",
    "signal_quality", "structure_vol", "dynamic_percent_threshold",
    "anchor_distance_percent", "slope_z_24h", "vol_ratio",
    "percent_vol_ratio", "extension_pressure", "adaptive_drift_cap",
]
for cls in ("W", "L"):
    print(f"\nClass {cls}:")
    for col in numeric:
        vals = []
        for slug, wl in OUTCOMES.items():
            if wl != cls:
                continue
            r = rows.get(slug)
            if not r:
                continue
            try:
                vals.append(float(r[col]))
            except (TypeError, ValueError):
                pass
        if vals:
            print(f"  {col:<28} mean={statistics.mean(vals):.4g} "
                  f"min={min(vals):.4g} max={max(vals):.4g} n={len(vals)}")

# Focused side-by-side for the 2 surviving losers vs nearest winners.
PAIRS = [
    ("btc-updown-15m-1777143600", "btc-updown-15m-1777120200"),  # both BTC DOWN
    ("btc-updown-15m-1777275900", "btc-updown-15m-1777159800"),  # both BTC UP
]
print("\n--- Surviving-loser vs nearest-winner pairs ---")
for loser, winner in PAIRS:
    print(f"\nL {loser}  vs  W {winner}")
    rL, rW = rows.get(loser), rows.get(winner)
    if not rL or not rW:
        print("  (one row missing)")
        continue
    for col in cols:
        vL = rL.get(col, "-")
        vW = rW.get(col, "-")
        marker = "  " if str(vL) == str(vW) else "* "
        print(f"  {marker}{col:<28} L={fmt(vL):>10}   W={fmt(vW):>10}")
