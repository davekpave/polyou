import csv
from collections import defaultdict
from datetime import datetime

rows = list(csv.DictReader(open('logs/rr_blocks.csv')))
windows_passing = defaultdict(set)
windows_total = defaultdict(set)
for r in rows:
    sym = r['symbol']
    w = r.get('window_start_ts','')
    if not w: continue
    windows_total[sym].add(w)
    try:
        if float(r['signal_rr']) >= 0.275:
            windows_passing[sym].add(w)
    except Exception:
        pass

ts = sorted(datetime.fromisoformat(r['ts_iso']) for r in rows if r.get('ts_iso'))
hrs = (ts[-1]-ts[0]).total_seconds()/3600

print(f'Span: {hrs:.1f}h ({hrs/24:.2f} days)')
print(f'{"sym":>8}{"windows_total":>16}{"win_pass_0.275":>18}')
for s in ['BTCUSD','ETHUSD','SOLUSD','XRPUSD']:
    print(f'{s:>8}{len(windows_total[s]):>16}{len(windows_passing[s]):>18}')

enabled = {'SOLUSD','XRPUSD'}
n_tradeable = sum(len(windows_passing[s]) for s in enabled)
print()
print(f'With SAFE_MARKETS=(SOL,XRP) and rr_min=0.275:')
print(f'  Tradeable windows: {n_tradeable} over {hrs:.1f}h')
print(f'  Per 48h: {n_tradeable*48/hrs:.1f}')
print(f'  Per 7 days: {n_tradeable*24*7/hrs:.1f}')

enabled2 = {'SOLUSD','XRPUSD','ETHUSD'}
n2 = sum(len(windows_passing[s]) for s in enabled2)
print()
print(f'If ETH were re-enabled: per 48h = {n2*48/hrs:.1f}')

enabled3 = {'SOLUSD','XRPUSD','ETHUSD','BTCUSD'}
n3 = sum(len(windows_passing[s]) for s in enabled3)
print(f'If ALL re-enabled: per 48h = {n3*48/hrs:.1f}')
