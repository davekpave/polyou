"""Investigate the 5 NO_SLUG FINAL TRADE entries.

Show full context (DECISION EMAIL or absence, EXECUTED, exit) so we can attribute
them to a real trade outcome or a logging gap.
"""
import re
from datetime import datetime

PATH = "logs/bot.log"
TARGETS = [
    ("2026-04-27 02:05:08", "ETHUSD", "DOWN"),
    ("2026-04-27 03:38:03", "BTCUSD", "DOWN"),
    ("2026-04-27 16:23:05", "BTCUSD", "UP"),
    ("2026-04-27 20:53:39", "BTCUSD", "DOWN"),
    ("2026-04-27 21:09:21", "BTCUSD", "DOWN"),
]
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

with open(PATH, encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

for ts_str, sym, side in TARGETS:
    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    # Find the line index
    idx = None
    for i, ln in enumerate(lines):
        if ts_str in ln and "FINAL TRADE" in ln and sym in ln:
            idx = i; break
    if idx is None:
        print(f"\n### {ts_str} {sym} {side}: NOT FOUND")
        continue
    print("\n" + "="*80)
    print(f"### {ts_str} {sym} {side}  (line {idx})")
    print("="*80)
    # 5 lines before, 200 lines after; filter to events
    keep = re.compile(
        r"FINAL TRADE|DECISION EMAIL|EXECUTED|PARTIAL|EXPIRY|exit_log|"
        r"order_id|Execution|Could not|did not cross|symbol=" + sym
    )
    end = min(len(lines), idx + 250)
    for j in range(max(0, idx-2), end):
        ln = lines[j]
        if keep.search(ln) and (sym in ln or "DECISION EMAIL" in ln or "EXECUTED" in ln or "Execution" in ln):
            tm = TS_RE.match(ln)
            if tm:
                t2 = datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S")
                # Only show within 20 minutes after FINAL TRADE
                if (t2 - ts).total_seconds() > 20*60:
                    break
            print(ln.rstrip())
