"""Step 1: Backfill window outcomes from clob_ticks.csv.

For each (symbol, window_start_ts) pair seen in clob_ticks.csv, find the
latest YES-side tick at or before window close + 5s grace, and classify.

Two confidence tiers:
  STRICT  (gold standard, label_conf="strict"):
    YES_ask >= 0.99 -> winner=UP   (YES resolved to ~1.0)
    YES_ask <= 0.01 -> winner=DOWN (YES resolved to ~0.0)

  NEAR_CLOSE FALLBACK (label_conf="near_close"):
    Used only when STRICT cannot label AND the terminal tick is within
    NEAR_CLOSE_SECS (60s) of window close.
    YES_ask >= 0.85 -> winner=UP
    YES_ask <= 0.15 -> winner=DOWN

  Otherwise label_conf="stale_terminal"/"near_close_indeterminate",
  winner="UNRESOLVED".

Cross-check using matching NO-side terminal tick when present:
  YES_ask + NO_ask should be ~1.0 on a healthy market.
  If abs(YES+NO-1.0) > SUM_OFFSET_STALE we tag label_conf with
  "_yes_no_disagree" (except for STRICT, which we trust).

Output: logs/derived/window_outcomes_backfilled.csv
Read-only; no production state modified.
"""
import csv
import os
from datetime import datetime
from collections import defaultdict

CLOB_TICKS = "logs/clob_ticks.csv"
OUT_DIR = "logs/derived"
OUT_PATH = os.path.join(OUT_DIR, "window_outcomes_backfilled.csv")

WINDOW_SECONDS = 900
STRICT_WIN = 0.99
STRICT_LOSS = 0.01
NEAR_CLOSE_SECS = 60
FALLBACK_WIN = 0.85
FALLBACK_LOSS = 0.15
SUM_OFFSET_STALE = 0.10


def parse_iso(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp())


# Pass 1: collect last YES-tick AND last NO-tick per (symbol, window_start_ts)
last_tick = {"YES": {}, "NO": {}}

with open(CLOB_TICKS, "r", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        side = row.get("side")
        if side not in ("YES", "NO"):
            continue
        try:
            epoch = parse_iso(row["ts_iso"])
            ws = int(row["window_start_ts"])
            ask = float(row["best_ask"])
            bid = float(row["best_bid"])
        except (ValueError, KeyError):
            continue
        if epoch < ws or epoch > ws + WINDOW_SECONDS + 5:
            continue
        key = (row["symbol"], ws)
        prev = last_tick[side].get(key)
        if prev is None or epoch > prev[0]:
            last_tick[side][key] = (epoch, ask, bid, row["ts_iso"])

# Pass 2: classify per window
os.makedirs(OUT_DIR, exist_ok=True)
rows_out = []
all_keys = set(last_tick["YES"].keys()) | set(last_tick["NO"].keys())

for key in all_keys:
    symbol, ws = key
    yes = last_tick["YES"].get(key)
    no = last_tick["NO"].get(key)

    if yes is None:
        rows_out.append({
            "symbol": symbol, "window_start_ts": ws,
            "terminal_yes_ask": "", "terminal_yes_bid": "",
            "terminal_ts_iso": no[3] if no else "",
            "seconds_before_close": "",
            "yes_no_sum_offset": "",
            "winner": "UNRESOLVED", "label_conf": "no_yes_data",
        })
        continue

    epoch, ask, bid, ts_iso = yes
    seconds_before_close = (ws + WINDOW_SECONDS) - epoch

    if no is not None:
        sum_offset = abs(ask + no[1] - 1.0)
        sum_offset_str = f"{sum_offset:.4f}"
        stale_flag = sum_offset > SUM_OFFSET_STALE
    else:
        sum_offset_str = ""
        stale_flag = False

    if ask >= STRICT_WIN:
        winner, label_conf = "UP", "strict"
    elif ask <= STRICT_LOSS:
        winner, label_conf = "DOWN", "strict"
    elif seconds_before_close <= NEAR_CLOSE_SECS:
        if ask >= FALLBACK_WIN:
            winner, label_conf = "UP", "near_close"
        elif ask <= FALLBACK_LOSS:
            winner, label_conf = "DOWN", "near_close"
        else:
            winner, label_conf = "UNRESOLVED", "near_close_indeterminate"
    else:
        winner, label_conf = "UNRESOLVED", "stale_terminal"

    if stale_flag and label_conf != "strict":
        label_conf = label_conf + "_yes_no_disagree"

    rows_out.append({
        "symbol": symbol, "window_start_ts": ws,
        "terminal_yes_ask": f"{ask:.4f}",
        "terminal_yes_bid": f"{bid:.4f}",
        "terminal_ts_iso": ts_iso,
        "seconds_before_close": seconds_before_close,
        "yes_no_sum_offset": sum_offset_str,
        "winner": winner, "label_conf": label_conf,
    })

rows_out.sort(key=lambda r: (r["symbol"], r["window_start_ts"]))

with open(OUT_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "symbol", "window_start_ts",
        "terminal_yes_ask", "terminal_yes_bid", "terminal_ts_iso",
        "seconds_before_close", "yes_no_sum_offset",
        "winner", "label_conf",
    ])
    writer.writeheader()
    writer.writerows(rows_out)

# ---- summary
total = len(rows_out)
print(f"Wrote {total} window rows to {OUT_PATH}\n")

def pct(n): return f"({100 * n / total:.1f}%)" if total else "(-)"

strict = sum(1 for r in rows_out if r["label_conf"] == "strict")
near = sum(1 for r in rows_out
           if r["label_conf"].startswith("near_close") and r["winner"] != "UNRESOLVED")
unres = sum(1 for r in rows_out if r["winner"] == "UNRESOLVED")
print(f"Resolved STRICT     : {strict:4d} {pct(strict)}")
print(f"Resolved NEAR_CLOSE : {near:4d} {pct(near)}")
print(f"Unresolved          : {unres:4d} {pct(unres)}")
print(f"Total resolved      : {strict + near:4d} {pct(strict + near)}\n")

res_rows = [r for r in rows_out if r["winner"] in ("UP", "DOWN")]
if res_rows:
    ups = sum(1 for r in res_rows if r["winner"] == "UP")
    downs = sum(1 for r in res_rows if r["winner"] == "DOWN")
    print(f"Resolved UP/DOWN balance: UP={ups}  DOWN={downs}  "
          f"UP_rate={(ups / len(res_rows)) * 100:.1f}%")

print("\nBy symbol:")
by_sym = defaultdict(lambda: {"UP": 0, "DOWN": 0, "UNRESOLVED": 0,
                              "strict": 0, "near": 0})
for r in rows_out:
    s = by_sym[r["symbol"]]
    s[r["winner"]] += 1
    if r["label_conf"] == "strict":
        s["strict"] += 1
    elif r["label_conf"].startswith("near_close") and r["winner"] != "UNRESOLVED":
        s["near"] += 1
for sym in sorted(by_sym):
    s = by_sym[sym]
    tot = s["UP"] + s["DOWN"] + s["UNRESOLVED"]
    res = s["UP"] + s["DOWN"]
    print(f"  {sym:<8} total={tot:3d}  resolved={res:3d}  "
          f"(strict={s['strict']:3d} near={s['near']:3d})  "
          f"UP={s['UP']:3d}  DOWN={s['DOWN']:3d}  UNRES={s['UNRESOLVED']:3d}")

offsets = [float(r["yes_no_sum_offset"]) for r in rows_out
           if r["yes_no_sum_offset"] not in ("", None)]
if offsets:
    offsets.sort()
    n = len(offsets)
    def at(p): return offsets[min(int(n * p), n - 1)]
    print(f"\nYES+NO sum offset (lower=healthier):  n={n}")
    print(f"  min={offsets[0]:.4f}  p25={at(.25):.4f}  p50={at(.5):.4f}  "
          f"p75={at(.75):.4f}  p95={at(.95):.4f}  max={offsets[-1]:.4f}")
    stale = sum(1 for o in offsets if o > SUM_OFFSET_STALE)
    print(f"  Windows with sum_offset > {SUM_OFFSET_STALE}: {stale} "
          f"({100 * stale / n:.1f}%)")
