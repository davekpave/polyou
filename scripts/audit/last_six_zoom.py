"""Wider context around the two losing trades."""
import re

PATH = "logs/bot.log"
TARGETS = [
    ("BTCUSD", 1777322700, "BTC LOSS"),
    ("XRPUSD", 1777331700, "XRP LOSS"),
    # also pull a winner for side-by-side
    ("BTCUSD", 1777320900, "BTC WIN (just before BTC loss)"),
    ("BTCUSD", 1777342500, "BTC WIN"),
]
DECISION_RE = re.compile(r"\[DECISION EMAIL SENT\]\s+(\w+)\s+\|\s+(\w+)\s+\|\s+window_end_ts=(\d+)")

with open(PATH, encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

decisions = []
for i, ln in enumerate(lines):
    m = DECISION_RE.search(ln)
    if m:
        decisions.append((i, m.group(1), m.group(2), int(m.group(3))))

for sym, we, label in TARGETS:
    print("\n" + "#"*80)
    print(f"### {label}  symbol={sym} window_end={we}")
    print("#"*80)
    for idx, s, side, _we in decisions:
        if s == sym and _we == we:
            start = max(0, idx - 60)
            end = min(len(lines), idx + 30)
            for ln in lines[start:end]:
                # Filter: match symbol or relevant features
                if (sym in ln or sym[:3].lower() in ln.lower()) and any(k in ln for k in [
                    "FINAL TRADE","DECISION EMAIL","ALERT_FORENSIC","priority=","quality=",
                    "percent_move","distance_z","signal_rr","snapshot","live_ask",
                    "acceleration","EARLY","continuation","Position sizing","[ENTRY","[OPEN",
                    "skip","SKIP","Block","BLOCK","No trade","NO TRADE","Cooldown","cooldown"
                ]):
                    print(ln.rstrip())
            break
