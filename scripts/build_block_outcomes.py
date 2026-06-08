"""Step 2: Join rr_blocks with backfilled window outcomes.

For each block in logs/rr_blocks.csv:
  - Find the matching window outcome by (symbol, window_start_ts).
  - Determine if the bot's intended side matches the winner.
       block_won = (block.side == outcome.winner)
  - Compute would-have-been P&L per $1 staked at snapshot_price:
       if block_won:   payoff = (1 - snapshot_price)
       else:           payoff = -snapshot_price
       (UNRESOLVED -> drop from analysis)

Output: logs/derived/block_outcomes.csv
Plus a summary: per-tier and per-symbol empirical win rate, mean payoff,
break-even win rate (= snapshot_price), and edge.

Read-only.
"""
import csv
import os
from collections import defaultdict
from statistics import mean

BLOCKS_PATH = "logs/rr_blocks.csv"
OUTCOMES_PATH = "logs/derived/window_outcomes_backfilled.csv"
OUT_PATH = "logs/derived/block_outcomes.csv"

# Load outcomes index: (symbol, window_start_ts) -> dict
outcomes = {}
with open(OUTCOMES_PATH, newline="") as f:
    for r in csv.DictReader(f):
        key = (r["symbol"], int(r["window_start_ts"]))
        outcomes[key] = r

joined = []
unmatched = 0
with open(BLOCKS_PATH, newline="") as f:
    for r in csv.DictReader(f):
        try:
            ws = int(r["window_start_ts"])
            sp = float(r["snapshot_price"])
        except (ValueError, KeyError):
            continue
        key = (r["symbol"], ws)
        oc = outcomes.get(key)
        if oc is None:
            unmatched += 1
            continue
        winner = oc["winner"]
        if winner not in ("UP", "DOWN"):
            joined.append({**r,
                "outcome_winner": winner,
                "outcome_label_conf": oc["label_conf"],
                "block_won": "",
                "payoff_per_dollar": "",
            })
            continue
        won = (r["side"] == winner)
        payoff = (1 - sp) if won else (-sp)
        joined.append({**r,
            "outcome_winner": winner,
            "outcome_label_conf": oc["label_conf"],
            "block_won": "1" if won else "0",
            "payoff_per_dollar": f"{payoff:.4f}",
        })

# write
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
fieldnames = list(joined[0].keys()) if joined else []
with open(OUT_PATH, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(joined)

# summary
total = len(joined)
resolved = [r for r in joined if r["block_won"] in ("0", "1")]
print(f"Total blocks read     : {total + unmatched}")
print(f"  unmatched (no window outcome): {unmatched}")
print(f"  matched                       : {total}")
print(f"  resolved (UP/DOWN winner)     : {len(resolved)}")
print(f"  ambiguous (UNRESOLVED window) : {total - len(resolved)}\n")

if not resolved:
    print("No resolved blocks; cannot calibrate yet.")
    raise SystemExit(0)

def stats(rows, label):
    n = len(rows)
    if not n:
        return f"  {label:<28} n=  0"
    wins = sum(1 for r in rows if r["block_won"] == "1")
    win_rate = wins / n
    mean_payoff = mean(float(r["payoff_per_dollar"]) for r in rows)
    mean_sp = mean(float(r["snapshot_price"]) for r in rows)
    breakeven = mean_sp
    edge_pp = (win_rate - breakeven) * 100
    return (f"  {label:<28} n={n:5d}  win={win_rate*100:5.1f}%  "
            f"mean_sp={mean_sp:.3f}  break_even={breakeven*100:5.1f}%  "
            f"edge={edge_pp:+5.1f}pp  EV/$={mean_payoff:+.4f}")

print("OVERALL")
print(stats(resolved, "all_resolved"))

print("\nBY TIER")
by_tier = defaultdict(list)
for r in resolved:
    by_tier[r["tier"]].append(r)
for tier in sorted(by_tier):
    print(stats(by_tier[tier], tier))

print("\nBY SYMBOL")
by_sym = defaultdict(list)
for r in resolved:
    by_sym[r["symbol"]].append(r)
for sym in sorted(by_sym):
    print(stats(by_sym[sym], sym))

print("\nBY SYMBOL x TIER")
by_st = defaultdict(list)
for r in resolved:
    by_st[(r["symbol"], r["tier"])].append(r)
for k in sorted(by_st):
    print(stats(by_st[k], f"{k[0]}/{k[1]}"))

print("\nBY SNAPSHOT_PRICE BUCKET")
def bucket(sp):
    # 5-cent buckets from 0.50 to 0.85
    for lo in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        if sp < lo + 0.05:
            return f"[{lo:.2f},{lo+0.05:.2f})"
    return "[0.85+]"
by_b = defaultdict(list)
for r in resolved:
    by_b[bucket(float(r["snapshot_price"]))].append(r)
for b in sorted(by_b):
    print(stats(by_b[b], b))

print("\nBY SIDE")
by_side = defaultdict(list)
for r in resolved:
    by_side[r["side"]].append(r)
for s in sorted(by_side):
    print(stats(by_side[s], s))

# Per label_conf -> sanity (does NEAR_CLOSE labeling skew win-rate?)
print("\nBY LABEL_CONF (data-quality sanity check)")
by_lc = defaultdict(list)
for r in resolved:
    by_lc[r["outcome_label_conf"]].append(r)
for lc in sorted(by_lc):
    print(stats(by_lc[lc], lc))
