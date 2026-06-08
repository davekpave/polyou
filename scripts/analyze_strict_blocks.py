"""Step 3: Strict-only deep dive + UP/DOWN asymmetry investigation.

Filters block_outcomes.csv to label_conf == 'strict' (gold standard,
~3000 blocks, verified clean), then drills:

A. Decision matrix: side x symbol x snapshot_price bucket
B. UP/DOWN asymmetry probes:
   B1. Within snapshot_price buckets — does UP still beat DOWN at the
       SAME entry price? If yes, the asymmetry is real.
   B2. Per-symbol UP vs DOWN at matched price buckets.
   B3. clob_age_ms distribution UP vs DOWN — is DOWN getting staler quotes?
   B4. tracker_ask vs snapshot_price gap UP vs DOWN — overshoot test.
   B5. signal_rr distribution UP vs DOWN.

Read-only.
"""
import csv
from collections import defaultdict
from statistics import mean, median

PATH = "logs/derived/block_outcomes.csv"

rows_all = []
with open(PATH, newline="") as f:
    for r in csv.DictReader(f):
        if r.get("block_won") not in ("0", "1"):
            continue
        rows_all.append(r)

rows = [r for r in rows_all if r["outcome_label_conf"] == "strict"]

print(f"Total resolved blocks: {len(rows_all)}")
print(f"Strict-only subset   : {len(rows)}\n")

def fmt_stats(rows, label, indent=2):
    n = len(rows)
    if n == 0:
        return f"{' ' * indent}{label:<32} n=    0"
    wins = sum(1 for r in rows if r["block_won"] == "1")
    wr = wins / n
    sps = [float(r["snapshot_price"]) for r in rows]
    mean_sp = mean(sps)
    payoffs = [float(r["payoff_per_dollar"]) for r in rows]
    ev = mean(payoffs)
    edge = (wr - mean_sp) * 100
    return (f"{' ' * indent}{label:<32} n={n:5d}  "
            f"win={wr*100:5.1f}%  sp={mean_sp:.3f}  "
            f"edge={edge:+5.1f}pp  EV/$={ev:+.4f}")

def bucket(sp):
    for lo in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        if sp < lo + 0.05:
            return f"[{lo:.2f},{lo+0.05:.2f})"
    return "[1.00]"

# ---------- A. Decision matrix
print("=" * 78)
print("A. DECISION MATRIX (strict-only): symbol x side x snapshot_price")
print("=" * 78)
buckets = defaultdict(list)
for r in rows:
    buckets[(r["symbol"], r["side"], bucket(float(r["snapshot_price"])))].append(r)

for sym in sorted(set(r["symbol"] for r in rows)):
    print(f"\n{sym}:")
    for side in ("UP", "DOWN"):
        print(f"  side={side}")
        keys = sorted(k for k in buckets if k[0] == sym and k[1] == side)
        for k in keys:
            print(fmt_stats(buckets[k], k[2], indent=4))

# ---------- B1. Within-bucket UP vs DOWN (the key asymmetry test)
print("\n" + "=" * 78)
print("B1. UP vs DOWN at MATCHED snapshot_price buckets (strict-only, all symbols)")
print("=" * 78)
print("    If asymmetry persists at the same price, UP signals are genuinely better.")
sp_keys = sorted(set(bucket(float(r["snapshot_price"])) for r in rows))
for b in sp_keys:
    in_b = [r for r in rows if bucket(float(r["snapshot_price"])) == b]
    if len(in_b) < 10:
        continue
    print(f"\n  bucket {b}:")
    for side in ("UP", "DOWN"):
        sub = [r for r in in_b if r["side"] == side]
        print(fmt_stats(sub, f"side={side}", indent=4))

# ---------- B2. Per-symbol UP vs DOWN
print("\n" + "=" * 78)
print("B2. UP vs DOWN per symbol (strict-only)")
print("=" * 78)
for sym in sorted(set(r["symbol"] for r in rows)):
    print(f"\n  {sym}:")
    sym_rows = [r for r in rows if r["symbol"] == sym]
    for side in ("UP", "DOWN"):
        sub = [r for r in sym_rows if r["side"] == side]
        print(fmt_stats(sub, f"side={side}", indent=4))

# ---------- B3. Latency distribution UP vs DOWN
print("\n" + "=" * 78)
print("B3. CLOB latency (clob_age_ms) UP vs DOWN")
print("=" * 78)
def lat_summary(rs, label):
    ages = []
    for r in rs:
        try:
            ages.append(float(r["clob_age_ms"]))
        except (ValueError, KeyError):
            pass
    if not ages:
        print(f"  {label} n=0"); return
    ages.sort()
    n = len(ages)
    def at(p): return ages[min(int(n * p), n - 1)]
    print(f"  {label:<10} n={n:5d}  "
          f"min={ages[0]:7.0f}  p50={at(.5):7.0f}  p75={at(.75):7.0f}  "
          f"p95={at(.95):7.0f}  max={ages[-1]:8.0f}  mean={mean(ages):7.0f}")

for side in ("UP", "DOWN"):
    sub = [r for r in rows if r["side"] == side]
    lat_summary(sub, f"side={side}")
print("  (Same after splitting by win/loss:)")
for side in ("UP", "DOWN"):
    for outcome in ("1", "0"):
        sub = [r for r in rows if r["side"] == side and r["block_won"] == outcome]
        lat_summary(sub, f"{side}/{'win' if outcome=='1' else 'loss'}")

# ---------- B4. tracker_ask vs snapshot_price gap
print("\n" + "=" * 78)
print("B4. snapshot_price - tracker_ask  (positive = bot would overpay vs CLOB)")
print("=" * 78)
def gap_summary(rs, label):
    gaps = []
    for r in rs:
        try:
            sp = float(r["snapshot_price"]); ta = float(r["tracker_ask"])
            gaps.append(sp - ta)
        except (ValueError, KeyError, TypeError):
            pass
    if not gaps:
        print(f"  {label} n=0"); return
    gaps.sort()
    n = len(gaps)
    def at(p): return gaps[min(int(n * p), n - 1)]
    print(f"  {label:<14} n={n:5d}  "
          f"min={gaps[0]:+.4f}  p25={at(.25):+.4f}  p50={at(.5):+.4f}  "
          f"p75={at(.75):+.4f}  max={gaps[-1]:+.4f}  mean={mean(gaps):+.4f}")
for side in ("UP", "DOWN"):
    sub = [r for r in rows if r["side"] == side]
    gap_summary(sub, f"side={side}")
for side in ("UP", "DOWN"):
    for outcome in ("1", "0"):
        sub = [r for r in rows if r["side"] == side and r["block_won"] == outcome]
        gap_summary(sub, f"{side}/{'win' if outcome=='1' else 'loss'}")

# ---------- B5. signal_rr UP vs DOWN
print("\n" + "=" * 78)
print("B5. signal_rr distribution UP vs DOWN")
print("=" * 78)
def rr_summary(rs, label):
    vals = []
    for r in rs:
        try:
            vals.append(float(r["signal_rr"]))
        except (ValueError, KeyError):
            pass
    if not vals:
        print(f"  {label} n=0"); return
    vals.sort()
    n = len(vals)
    def at(p): return vals[min(int(n * p), n - 1)]
    print(f"  {label:<14} n={n:5d}  "
          f"min={vals[0]:.4f}  p25={at(.25):.4f}  p50={at(.5):.4f}  "
          f"p75={at(.75):.4f}  max={vals[-1]:.4f}  mean={mean(vals):.4f}")
for side in ("UP", "DOWN"):
    sub = [r for r in rows if r["side"] == side]
    rr_summary(sub, f"side={side}")

# ---------- C. Best-of-the-best filter preview (no changes, just simulation)
print("\n" + "=" * 78)
print("C. SIMULATED FILTER PREVIEWS (strict-only, what would survive each rule)")
print("=" * 78)

filters = [
    ("baseline (all strict)", lambda r: True),
    ("UP only", lambda r: r["side"] == "UP"),
    ("DOWN only", lambda r: r["side"] == "DOWN"),
    ("SOL only", lambda r: r["symbol"] == "SOLUSD"),
    ("SOL + UP", lambda r: r["symbol"] == "SOLUSD" and r["side"] == "UP"),
    ("SOL + DOWN", lambda r: r["symbol"] == "SOLUSD" and r["side"] == "DOWN"),
    ("BTC + UP", lambda r: r["symbol"] == "BTCUSD" and r["side"] == "UP"),
    ("BTC + DOWN", lambda r: r["symbol"] == "BTCUSD" and r["side"] == "DOWN"),
    ("XRP + UP", lambda r: r["symbol"] == "XRPUSD" and r["side"] == "UP"),
    ("UP + sp<=0.90", lambda r: r["side"] == "UP" and float(r["snapshot_price"]) <= 0.90),
    ("UP + sp<=0.85", lambda r: r["side"] == "UP" and float(r["snapshot_price"]) <= 0.85),
    ("DOWN + sp<=0.85", lambda r: r["side"] == "DOWN" and float(r["snapshot_price"]) <= 0.85),
    ("SOL+UP + sp<=0.90", lambda r: r["symbol"]=="SOLUSD" and r["side"]=="UP" and float(r["snapshot_price"]) <= 0.90),
]
for name, fn in filters:
    sub = [r for r in rows if fn(r)]
    print(fmt_stats(sub, name, indent=2))
