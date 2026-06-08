"""All FINAL TRADEs in the past 68 hours, with features and Gamma settlement.

Windows we already know: 1777307400 (BTC W), 1777320000 (BTC W), 1777321800 (BTC L),
1777330800 (XRP L), 1777341600 (BTC W), 1777363200 (BTC W).
Gather any others, plus features per trade, and report whether proposed filters
A (30-min same sym+side cooldown) or B (recent exhaustion_ok fail) would have blocked them.
"""
import re, time, json, requests
from datetime import datetime, timedelta

PATH = "logs/bot.log"
CUTOFF_HOURS = 68
NOW = datetime(2026, 4, 28, 4, 37, 0)  # approx current time per context
START = NOW - timedelta(hours=CUTOFF_HOURS)

SYM_PREFIX = {"BTCUSD":"btc","ETHUSD":"eth","SOLUSD":"sol","XRPUSD":"xrp"}
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"

FINAL_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ET \[INFO\] polyou_bot: FINAL TRADE \| symbol=(\w+) side=(\w+) priority=([\d.]+) quality=([\d.]+)")
DECISION_RE = re.compile(r"\[DECISION EMAIL SENT\]\s+(\w+)\s+\|\s+(\w+)\s+\|\s+window_end_ts=(\d+)")
LATE_RE = re.compile(r"Late extension penalty \| symbol=(\w+) phase=([\d.]+) distance_z=([\d.]+)")
EXHAUST_RE = re.compile(r"Blocked: Failed exhaustion_ok hard gate \| symbol=(\w+) side=(\w+)")

with open(PATH, encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()
print(f"Loaded {len(lines)} lines")

trades = []  # list of dicts
for i, ln in enumerate(lines):
    m = FINAL_RE.search(ln)
    if not m:
        continue
    ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    if ts < START:
        continue
    sym, side = m.group(2), m.group(3)
    priority, quality = float(m.group(4)), float(m.group(5))
    # find DECISION EMAIL ahead within 60s
    slug = None
    for j in range(i+1, min(i+200, len(lines))):
        dm = DECISION_RE.search(lines[j])
        if dm and dm.group(1) == sym and dm.group(2) == side:
            we = int(dm.group(3))
            slug = f"{SYM_PREFIX.get(sym,sym.lower()[:3])}-updown-15m-{we-900}"
            break
        if FINAL_RE.search(lines[j]):
            break
    # find Late extension within prior 5 lines (same second)
    phase = dz = None
    for j in range(max(0,i-5), i+1):
        lm = LATE_RE.search(lines[j])
        if lm and lm.group(1) == sym:
            phase = float(lm.group(2)); dz = float(lm.group(3))
    # find exhaustion fail within last 30s same sym+side (look back ~150 lines)
    exhaust_fail = False
    for j in range(max(0,i-150), i):
        em = EXHAUST_RE.search(lines[j])
        if em and em.group(1) == sym and em.group(2) == side:
            # also confirm time diff <= 30s
            tm = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", lines[j])
            if tm:
                t2 = datetime.strptime(tm.group(1), "%Y-%m-%d %H:%M:%S")
                if (ts - t2).total_seconds() <= 30:
                    exhaust_fail = True
                    break
    trades.append({"ts":ts,"sym":sym,"side":side,"priority":priority,
                   "quality":quality,"slug":slug,"phase":phase,"dz":dz,
                   "exhaust_fail":exhaust_fail})

trades.sort(key=lambda t: t["ts"])
print(f"FINAL TRADEs since {START}: {len(trades)}\n")

# Settle via Gamma
def resolve(slug):
    try:
        m = requests.get(GAMMA.format(slug), timeout=10).json()[0]["markets"][0]
    except Exception:
        return None
    if not m.get("closed", False):
        return "OPEN"
    outs, pr = m.get("outcomes",[]), m.get("outcomePrices",[])
    if isinstance(outs, str): outs = json.loads(outs)
    if isinstance(pr, str): pr = json.loads(pr)
    for k,p in enumerate(pr):
        if str(p)=="1": return outs[k].upper()
    return None

for t in trades:
    if t["slug"]:
        winner = resolve(t["slug"])
        time.sleep(0.10)
        if winner == "OPEN":
            t["result"] = "OPEN"
        elif winner is None:
            t["result"] = "?"
        else:
            t["result"] = "WIN" if winner == t["side"] else "LOSS"
    else:
        t["result"] = "NO_SLUG"

# Mark filter A: same sym+side within 30 min before this trade (in our list)
for idx, t in enumerate(trades):
    blockedA = False
    for prev in trades[:idx]:
        if prev["sym"] == t["sym"] and prev["side"] == t["side"]:
            dt = (t["ts"] - prev["ts"]).total_seconds()
            if 0 < dt <= 30*60:
                blockedA = True; break
    t["filterA"] = blockedA
    t["filterB"] = t["exhaust_fail"]

print(f"{'when':19}  {'sym':6} {'side':4} {'pri':>7} {'qual':>7} {'phase':>5} {'dz':>5} {'exh':>3} {'result':>5}  {'A':>1} {'B':>1}  slug")
for t in trades:
    print(f"{t['ts']!s:19}  {t['sym']:6} {t['side']:4} {t['priority']:>7.0f} {t['quality']:>7.0f} "
          f"{(t['phase'] if t['phase'] is not None else 0):>5.2f} "
          f"{(t['dz'] if t['dz'] is not None else 0):>5.1f} "
          f"{('Y' if t['exhaust_fail'] else '.'):>3} "
          f"{t['result']:>5}  "
          f"{'Y' if t['filterA'] else '.'} {'Y' if t['filterB'] else '.'}  {t['slug']}")

# Summary: how many winners blocked vs losers blocked
wins = [t for t in trades if t["result"] == "WIN"]
losses = [t for t in trades if t["result"] == "LOSS"]
print(f"\nWinners: {len(wins)}, Losses: {len(losses)}, Open/?/no_slug: {len(trades)-len(wins)-len(losses)}")
def cnt(coll, key): return sum(1 for x in coll if x[key])
print(f"Filter A blocks: winners={cnt(wins,'filterA')} / {len(wins)}, losses={cnt(losses,'filterA')} / {len(losses)}")
print(f"Filter B blocks: winners={cnt(wins,'filterB')} / {len(wins)}, losses={cnt(losses,'filterB')} / {len(losses)}")
print(f"Either: winners={sum(1 for x in wins if x['filterA'] or x['filterB'])}, losses={sum(1 for x in losses if x['filterA'] or x['filterB'])}")
