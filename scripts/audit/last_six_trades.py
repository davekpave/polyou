"""Extract FINAL TRADE + DECISION EMAIL context for given slugs from bot.log."""
import re, sys

TARGETS = [
    ("BTC", 1777307400, "WIN"),
    ("BTC", 1777320000, "WIN"),
    ("BTC", 1777321800, "LOSS"),
    ("XRP", 1777330800, "LOSS"),
    ("BTC", 1777341600, "WIN"),
    ("BTC", 1777363200, "WIN"),
]
# window_end = window_start + 900
TARGETS_WE = [(s, ws + 900, r) for s, ws, r in TARGETS]

PATH = "logs/bot.log"
DECISION_RE = re.compile(r"\[DECISION EMAIL SENT\]\s+(\w+)\s+\|\s+(\w+)\s+\|\s+window_end_ts=(\d+)")
FINAL_RE    = re.compile(r"FINAL TRADE \| symbol=(\w+) side=(\w+)")

# Read all lines once (130MB but ok)
with open(PATH, encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()
print(f"Loaded {len(lines)} lines")

# Map window_end_ts -> list of (line_idx, sym, side) from DECISION EMAILs
decisions = []
for i, ln in enumerate(lines):
    m = DECISION_RE.search(ln)
    if m:
        decisions.append((i, m.group(1), m.group(2), int(m.group(3))))

for sym, we, result in TARGETS_WE:
    print("\n" + "="*80)
    print(f"=== {sym} window_end={we}  RESULT={result} ===")
    print("="*80)
    matches = [d for d in decisions if d[1].upper().startswith(sym) and d[3] == we]
    if not matches:
        print(" (no DECISION EMAIL found)")
        continue
    for idx, s, side, _we in matches:
        # Print 60 lines around the decision and look for the FINAL TRADE
        start = max(0, idx - 5)
        end = min(len(lines), idx + 80)
        chunk = lines[start:end]
        # Filter to interesting lines
        keep_re = re.compile(
            r"DECISION EMAIL|FINAL TRADE|priority=|quality=|percent_move|distance_z|"
            r"signal_rr|snapshot|live_ask|acceleration|EARLY|signal_strength|"
            r"momentum|composite|edge|symbol=" + sym
        )
        for ln in chunk:
            if keep_re.search(ln):
                print(ln.rstrip())
