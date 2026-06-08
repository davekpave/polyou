"""Test two filters/discriminators for the UP-side WR failure:
   1. signal_age_minutes distribution (W vs L, by side)
   2. ask-drift filter: best_ask >= snapshot_price - 0.02 (live market hasn't
      walked away from us in the latency gap between signal-fire and decision-log).
"""
import csv
import statistics


def f(x):
    try:
        return float(x)
    except Exception:
        return None


# Build map: token_id -> outcome (win/loss + pnl)
exits = {}
for row in csv.DictReader(open("logs/shadow_exits.csv")):
    pps = f(row["profit_per_share"]) or 0.0
    exits[row["token_id"]] = {
        "side": row["side"],
        "symbol": row["symbol"],
        "pps": pps,
        "win": pps > 0,
        "exit_type": row["exit_type"],
    }

# signal_age_minutes lives in execution_log.csv; book data in decision_log.csv.
# Join both onto each token_id.
exec_age = {}
for row in csv.DictReader(open("logs/execution_log.csv")):
    exec_age[row["token_id"]] = f(row.get("signal_age_minutes"))

# Join decision_log entries with their outcome
joined = []
for row in csv.DictReader(open("logs/decision_log.csv")):
    tid = row["token_id"]
    if tid not in exits:
        continue
    snap = f(row["snapshot_price"])
    ask = f(row["best_ask"])
    age_min = exec_age.get(tid)
    # snapshot was clob_ask + 0.02 at signal-fire. So implied signal-time ask = snap - 0.02.
    # ask_drift = (current ask) - (signal-time ask) = ask - (snap - 0.02) = ask - snap + 0.02
    drift = (ask - snap + 0.02) if (ask is not None and snap is not None) else None
    joined.append(
        {
            "tid": tid,
            "sym": row["symbol"],
            "side": row["side"],
            "snap": snap,
            "ask": ask,
            "drift": drift,
            "age_min": age_min,
            **exits[tid],
        }
    )

print(f"Joined {len(joined)} of {len(exits)} exit rows with decision_log entries\n")

# ---------- Part 1: signal_age_minutes by side x outcome ----------
print("=" * 70)
print("PART 1: signal_age_minutes (where in 15-min window the signal fires)")
print("=" * 70)
for side in ("UP", "DOWN"):
    for label, pred in (("WIN ", lambda r: r["win"]), ("LOSS", lambda r: not r["win"])):
        sub = [r for r in joined if r["side"] == side and pred(r) and r["age_min"] is not None]
        if not sub:
            print(f"  {side} {label}: n=0")
            continue
        ages = [r["age_min"] for r in sub]
        print(
            f"  {side} {label}: n={len(sub):2d}  mean={statistics.mean(ages):5.2f}min "
            f"median={statistics.median(ages):5.2f}min  "
            f"range=[{min(ages):.2f},{max(ages):.2f}]"
        )

# ---------- Part 2: ask-drift filter ----------
print()
print("=" * 70)
print("PART 2: ask-drift filter test (drift = best_ask_at_decision - signal_ask)")
print("=" * 70)
print("Signal-time ask = snapshot_price - 0.02")
print("Filter rule: keep trade only if drift >= THRESHOLD\n")


def evaluate_filter(rows, threshold):
    survivors = [r for r in rows if r["drift"] is not None and r["drift"] >= threshold]
    if not survivors:
        return None
    wins = sum(1 for r in survivors if r["win"])
    pnl = sum(r["pps"] for r in survivors)
    return {
        "n": len(survivors),
        "wins": wins,
        "wr": wins / len(survivors),
        "pnl": pnl,
        "mean_pps": pnl / len(survivors),
    }


for side in ("UP", "DOWN", "ALL"):
    rows = [r for r in joined if (side == "ALL" or r["side"] == side) and r["drift"] is not None]
    if not rows:
        continue
    base_wins = sum(1 for r in rows if r["win"])
    base_pnl = sum(r["pps"] for r in rows)
    print(
        f"\n--- {side} (baseline n={len(rows)}, "
        f"WR={base_wins/len(rows):.1%}, total_pnl=${base_pnl:+.2f}, "
        f"mean_pps=${base_pnl/len(rows):+.4f}) ---"
    )
    print(f"  {'threshold':>10s}  {'kept':>4s}  {'wins':>4s}  {'WR':>6s}  {'tot_pnl':>10s}  {'mean_pps':>10s}")
    for thr in (-0.10, -0.06, -0.04, -0.02, -0.01, 0.00, 0.01, 0.02):
        res = evaluate_filter(rows, thr)
        if res is None:
            print(f"  {thr:>+10.3f}  (none survive)")
            continue
        print(
            f"  {thr:>+10.3f}  {res['n']:>4d}  {res['wins']:>4d}  {res['wr']:>5.1%}  "
            f"${res['pnl']:>+9.2f}  ${res['mean_pps']:>+9.4f}"
        )

# ---------- Part 3: per-trade detail to see if drift correlates with outcome on UP ----------
print()
print("=" * 70)
print("PART 3: UP trades sorted by drift (most-against-us first)")
print("=" * 70)
print(f"  {'sym':7s}  {'snap':>5s}  {'ask':>5s}  {'drift':>6s}  {'age_min':>7s}  {'pps':>7s}  result")
ups = sorted([r for r in joined if r["side"] == "UP" and r["drift"] is not None], key=lambda r: r["drift"])
for r in ups:
    result = "WIN " if r["win"] else "LOSS"
    print(
        f"  {r['sym']:7s}  {r['snap']:>5.3f}  {r['ask']:>5.3f}  {r['drift']:>+6.3f}  "
        f"{r['age_min']:>7.2f}  {r['pps']:>+7.3f}  {result}  ({r['exit_type']})"
    )
