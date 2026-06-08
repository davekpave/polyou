"""One-pass analysis: how many historical winners would the new gates block?

Gates (added 2026-04-30):
  1. MAX_SNAPSHOT_PRICE 0.72 -> 0.70  (blocks any EXECUTED price > 0.70)
  2. Late-extension converted from soft penalty to hard block
     (trigger: phase >= 0.40 AND distance_z >= 8.5; same condition as before)
"""
import csv
import re
from collections import defaultdict

EXIT_LOG = "logs/exit_log.csv"
BOT_LOG = "logs/bot.log"

# 1) Read exit_log: classify each token_id by outcome.
outcomes = {}  # token_id -> ("win"/"loss", profit_cents)
with open(EXIT_LOG, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        tok = row["token_id"]
        typ = row["type"]
        try:
            pc = float(row["profit_cents"])
        except (ValueError, KeyError):
            pc = 0.0
        if typ in ("TAKE_PROFIT", "EXPIRY_SELL"):
            outcomes[tok] = ("win", pc)
        elif typ in ("STOP_LOSS", "SETTLED_ZERO"):
            outcomes[tok] = ("loss", pc)

print(f"Outcomes: {sum(1 for v in outcomes.values() if v[0]=='win')} wins, "
      f"{sum(1 for v in outcomes.values() if v[0]=='loss')} losses")

# 2) Single pass through bot.log:
#    - track most-recent "Late extension penalty" line (timestamp + symbol)
#    - on EXECUTED, look up token_id, capture price + whether the
#      preceding ~10 lines contained a Late extension flag for the same symbol.
EXEC_RE = re.compile(r"EXECUTED \| (\d+) \| side=BUY price=([\d.]+)")
LATE_RE = re.compile(r"Late extension penalty \| symbol=(\w+)")

# Recent late-extension flags: symbol -> last seen line index
recent_late = {}
results = []  # list of (token_id, price, late_flag_within_10_lines, outcome)

line_idx = 0
with open(BOT_LOG, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        line_idx += 1
        m_late = LATE_RE.search(line)
        if m_late:
            recent_late[m_late.group(1)] = line_idx
            continue
        m_exec = EXEC_RE.search(line)
        if not m_exec:
            continue
        tok = m_exec.group(1)
        price = float(m_exec.group(2))
        if tok not in outcomes:
            continue
        # Determine symbol from the surrounding context not available cheaply;
        # instead, check if ANY late-extension flag fired in the last ~12 lines.
        late_within_window = any(
            (line_idx - ln) <= 12 for ln in recent_late.values()
        )
        results.append((tok, price, late_within_window, outcomes[tok]))

print(f"Matched EXECUTED lines for {len(results)} settled trades in bot.log")

# 3) Tally
def tally(label, predicate):
    blocked = [r for r in results if predicate(r)]
    wins = [r for r in blocked if r[3][0] == "win"]
    losses = [r for r in blocked if r[3][0] == "loss"]
    win_pnl = sum(r[3][1] for r in wins)
    loss_pnl = sum(r[3][1] for r in losses)
    net = win_pnl + loss_pnl
    print(f"\n{label}")
    print(f"  Total blocked: {len(blocked)} ({len(wins)} wins, {len(losses)} losses)")
    print(f"  Win  PnL forgone:  ${win_pnl:+.2f} per share")
    print(f"  Loss PnL avoided:  ${loss_pnl:+.2f} per share")
    print(f"  NET impact (bigger=better avoided): ${-net:+.2f} per share")

tally("Gate 1: price > 0.70", lambda r: r[1] > 0.70)
tally("Gate 2: late-extension flag (within 12 lines pre-EXEC)", lambda r: r[2])
tally("EITHER gate (combined)", lambda r: r[1] > 0.70 or r[2])
