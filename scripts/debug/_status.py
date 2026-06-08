import csv, time
from datetime import datetime

# Bot was restarted ~April 22, 2026 around 11AM ET
# Unix timestamp for April 22, 2026 00:00 UTC ~ 1776268800
RESTART_TS = 1776268800  # use all of April 22+ to be safe

rows = list(csv.DictReader(open('logs/exit_log.csv')))

# Deduplicate by token_id (keep first per token_id)
seen = set()
unique_all = []
for r in rows:
    tid = r['token_id']
    if tid not in seen:
        seen.add(tid)
        unique_all.append(r)

new_rows = [r for r in unique_all if float(r['timestamp']) >= RESTART_TS]
old_rows = [r for r in unique_all if float(r['timestamp']) < RESTART_TS]

def summarize(label, data):
    if not data:
        print(f"{label}: no data")
        return
    wins = [r for r in data if r['type'] == 'TAKE_PROFIT']
    losses = [r for r in data if r['type'] in ('STOP_LOSS', 'TIME_DECAY', 'EXPIRY_SELL')]
    wr = len(wins)/len(data)*100
    
    def shares(entry, notional=5.0):
        buy_price = min(0.70, entry + 0.01)
        return int((notional * 0.98 / buy_price) * 100) / 100.0

    total_pnl = 0
    for r in data:
        e = float(r['entry_price'])
        s = shares(e)
        total_pnl += float(r['profit_cents']) * s

    print(f"\n=== {label} ===")
    print(f"  Positions: {len(data)}")
    print(f"  Wins: {len(wins)}  Losses: {len(losses)}")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Est. total P&L: ${total_pnl:.2f}")
    if wins:
        avg_w = sum(float(r['profit_cents']) for r in wins)/len(wins)
        print(f"  Avg win/share: +{avg_w:.3f}")
    if losses:
        avg_l = sum(float(r['profit_cents']) for r in losses)/len(losses)
        print(f"  Avg loss/share: {avg_l:.3f}")
    
    # Show last 10 exits
    recent = sorted(data, key=lambda r: float(r['timestamp']))[-10:]
    print(f"\n  Last {len(recent)} exits:")
    for r in recent:
        ts = datetime.fromtimestamp(float(r['timestamp'])).strftime('%m/%d %H:%M')
        print(f"    {ts}  {r['type']:<12}  entry={r['entry_price']}  exit={r['exit_price']}  pnl={float(r['profit_cents']):+.3f}/sh")

summarize("BEFORE restart (old settings)", old_rows)
summarize("AFTER restart (new settings)", new_rows)

# Also check execution log for recent entries
try:
    exec_rows = list(csv.DictReader(open('logs/execution_log.csv')))
    new_entries = [r for r in exec_rows if float(r['timestamp']) >= RESTART_TS]
    print(f"\n=== New entries since restart ===")
    print(f"  Total: {len(new_entries)}")
    if new_entries:
        recent_e = sorted(new_entries, key=lambda r: float(r['timestamp']))[-5:]
        for r in recent_e:
            ts = datetime.fromtimestamp(float(r['timestamp'])).strftime('%m/%d %H:%M')
            print(f"    {ts}  {r.get('symbol','?')}  {r.get('side','?')}  price={r.get('snapshot_price','?')}")
except Exception as e:
    print(f"\nCould not read execution_log: {e}")
