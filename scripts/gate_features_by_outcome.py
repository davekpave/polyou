"""Compare exhaustion-gate features (structure_vol, vol_ratio, percent_vol_ratio,
slope_z_24h, dynamic_percent_threshold, anchor_distance_percent) across:
  UP wins   vs  UP losses   vs  DOWN wins  vs  DOWN losses
Looking for whether UP losers cluster against the gate caps in a way DOWN doesn't.
"""
import csv
import statistics

VOL_RATIO_CAP = 1.75
PERCENT_VOL_RATIO_CAP = 28


def f(x):
    try:
        return float(x)
    except Exception:
        return None


exits = {}
for row in csv.DictReader(open("logs/shadow_exits.csv")):
    pps = f(row["profit_per_share"]) or 0.0
    exits[row["token_id"]] = {"win": pps > 0, "pps": pps, "side": row["side"], "symbol": row["symbol"]}

joined = []
for row in csv.DictReader(open("logs/execution_log.csv")):
    tid = row["token_id"]
    if tid not in exits:
        continue
    joined.append(
        {
            **exits[tid],
            "structure_vol": f(row.get("structure_vol")),
            "vol_ratio": f(row.get("vol_ratio")),
            "percent_vol_ratio": f(row.get("percent_vol_ratio")),
            "slope_z_24h": f(row.get("slope_z_24h")),
            "dynamic_percent_threshold": f(row.get("dynamic_percent_threshold")),
            "anchor_distance_percent": f(row.get("anchor_distance_percent")),
            "extension_pressure": f(row.get("extension_pressure")),
            "adaptive_drift_cap": f(row.get("adaptive_drift_cap")),
            "signal_age_minutes": f(row.get("signal_age_minutes")),
        }
    )


def summarize(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    if not vals:
        return "n=0"
    if len(vals) == 1:
        return f"n=1 val={vals[0]:.4f}"
    return (
        f"n={len(vals):2d} mean={statistics.mean(vals):+8.4f} "
        f"median={statistics.median(vals):+8.4f} "
        f"min={min(vals):+8.4f} max={max(vals):+8.4f}"
    )


groups = {
    "UP-WIN":   [r for r in joined if r["side"] == "UP"   and r["win"]],
    "UP-LOSS":  [r for r in joined if r["side"] == "UP"   and not r["win"]],
    "DN-WIN":   [r for r in joined if r["side"] == "DOWN" and r["win"]],
    "DN-LOSS":  [r for r in joined if r["side"] == "DOWN" and not r["win"]],
}

keys = [
    "vol_ratio",
    "percent_vol_ratio",
    "structure_vol",
    "slope_z_24h",
    "dynamic_percent_threshold",
    "anchor_distance_percent",
    "extension_pressure",
    "adaptive_drift_cap",
    "signal_age_minutes",
]

for k in keys:
    print(f"\n--- {k} (caps: vol_ratio<={VOL_RATIO_CAP}, pvr<={PERCENT_VOL_RATIO_CAP}) ---" if k in ("vol_ratio","percent_vol_ratio") else f"\n--- {k} ---")
    for gname, rows in groups.items():
        print(f"  {gname:8s}: {summarize(rows, k)}")

# Per-trade UP listing
print("\n=== Per-trade UP detail (sorted by vol_ratio) ===")
print(f"  {'sym':7s}  {'vr':>5s}  {'pvr':>5s}  {'struct_vol':>10s}  {'slope_z':>7s}  {'anchor%':>8s}  {'pps':>6s}")
ups = sorted([r for r in joined if r["side"] == "UP"], key=lambda r: (r["vol_ratio"] or 0))
for r in ups:
    res = "WIN" if r["win"] else "LOSS"
    print(
        f"  {r['symbol']:7s}  {r['vol_ratio']:>5.2f}  {r['percent_vol_ratio']:>5.2f}  "
        f"{r['structure_vol']:>10.6f}  {r['slope_z_24h']:>+7.2f}  "
        f"{r['anchor_distance_percent']:>+8.4f}  {r['pps']:>+6.2f}  {res}"
    )

# Slope direction match: does sign(slope_z_24h) match side?
print("\n=== Slope-direction vs side match ===")
for gname, rows in groups.items():
    matched = 0
    total = 0
    for r in rows:
        sz = r["slope_z_24h"]
        if sz is None:
            continue
        total += 1
        if (r["side"] == "UP" and sz > 0) or (r["side"] == "DOWN" and sz < 0):
            matched += 1
    pct = (matched / total * 100) if total else 0
    print(f"  {gname:8s}: {matched}/{total} signal direction matches 24h slope ({pct:.0f}%)")
