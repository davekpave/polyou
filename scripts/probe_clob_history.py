import requests, csv, time
rows = list(csv.DictReader(open('logs/shadow_exits.csv', newline='')))
r = rows[-1]
token = r['token_id']
slug = r['contract_slug']
window_end = int(r['window_end_ts'])
print('slug:', slug)
print('window_end:', window_end, '(', time.strftime('%Y-%m-%d %H:%M', time.gmtime(window_end)), ')')
for fid in [1, 60, 600]:
    resp = requests.get('https://clob.polymarket.com/prices-history', params={
        'market': token,
        'startTs': window_end - 3600,
        'endTs': window_end + 60,
        'fidelity': fid,
    }, timeout=15)
    j = resp.json()
    n = len(j.get('history', []))
    print(f'fidelity={fid}: status={resp.status_code} n={n}')
    if n:
        print('  first:', j['history'][0])
        print('  last:', j['history'][-1])
