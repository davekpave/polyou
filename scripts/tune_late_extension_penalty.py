"""Late-extension trades: quality distribution by outcome.

For each settled trade in exit_log.csv that had a 'Late extension penalty'
log line within ~12 lines before its EXECUTED line, extract quality from
the FINAL TRADE line (which is post-multiply by 0.65) and reverse it to
raw quality. Then test what multiplier threshold (with MIN_QUALITY_SCORE=1000)
would have blocked which trades.
"""
import csv
import re

EXIT_LOG = "logs/exit_log.csv"
BOT_LOG = "logs/bot.log"
MIN_QUALITY = 1000

# Outcomes from exit log
outcomes = {}
with open(EXIT_LOG, "r") as f:
    for row in csv.DictReader(f):
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

EXEC_RE = re.compile(r"EXECUTED \| (\d+) \| side=BUY price=([\d.]+)")
LATE_RE = re.compile(r"Late extension penalty \| symbol=(\w+)")
FINAL_RE = re.compile(r"FINAL TRADE \| symbol=(\w+) side=(\w+) priority=([\d.]+) quality=([\d.]+)")

# Sliding window of recent lines so we can look back from EXECUTED.
buf = []
BUF_N = 25
results = []  # (token, price, raw_quality, outcome)

with open(BOT_LOG, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        buf.append(line)
        if len(buf) > BUF_N:
            buf.pop(0)
        m_exec = EXEC_RE.search(line)
        if not m_exec:
            continue
        tok = m_exec.group(1)
        if tok not in outcomes:
            continue
        price = float(m_exec.group(2))
        # Look back through buf for FINAL TRADE and Late extension penalty
        late_flag = False
        post_quality = None
        for prev in reversed(buf[:-1]):
            if not late_flag and LATE_RE.search(prev):
                late_flag = True
            if post_quality is None:
                m_fin = FINAL_RE.search(prev)
                if m_fin:
                    post_quality = float(m_fin.group(4))
            if late_flag and post_quality is not None:
                break
        if late_flag and post_quality is not None:
            raw_quality = post_quality / 0.65
            results.append((tok, price, raw_quality, outcomes[tok]))

print(f"Late-extension settled trades found: {len(results)}")
print(f"  Wins:   {sum(1 for r in results if r[3][0]=='win')}")
print(f"  Losses: {sum(1 for r in results if r[3][0]=='loss')}\n")

print(f"{'tok[:8]':<10} {'price':>6} {'rawQ':>8} {'outcome':>8} {'pnl¢':>8}")
for r in sorted(results, key=lambda x: x[2]):
    tok, price, q, (oc, pc) = r
    print(f"{tok[:8]:<10} {price:>6.2f} {q:>8.0f} {oc:>8} {pc:>+8.2f}")

print("\n--- What multiplier blocks how many? (after MIN_QUALITY=1000) ---")
print(f"{'mult':>5} {'blocked_W':>10} {'blocked_L':>10} {'kept_W':>8} {'kept_L':>8} {'net_per_share':>14}")
for mult in [0.65, 0.55, 0.45, 0.40, 0.37, 0.35, 0.30]:
    blocked = [r for r in results if r[2] * mult < MIN_QUALITY]
    bw = [r for r in blocked if r[3][0] == "win"]
    bl = [r for r in blocked if r[3][0] == "loss"]
    kw = [r for r in results if r[3][0] == "win" and r not in blocked]
    kl = [r for r in results if r[3][0] == "loss" and r not in blocked]
    # Net = avoided losses - lost wins (per share, in cents)
    net = -(sum(r[3][1] for r in bw) + sum(r[3][1] for r in bl))
    print(f"{mult:>5.2f} {len(bw):>10} {len(bl):>10} {len(kw):>8} {len(kl):>8} {net/100:>+14.2f}")
