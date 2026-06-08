import requests, warnings
warnings.filterwarnings('ignore')

print("=== Kraken (all pairs) ===")
pairs = [('BTCUSD', 'XBTUSD'), ('ETHUSD', 'ETHUSD'), ('SOLUSD', 'SOLUSD'), ('XRPUSD', 'XRPUSD')]
for display, pair in pairs:
    try:
        r = requests.get('https://api.kraken.com/0/public/Ticker', params={'pair': pair}, timeout=5, verify=False)
        j = r.json()
        err = j.get('error') or []
        if err:
            print(f'  {display}: ERROR {err}')
        else:
            data = next(iter(j['result'].values()))
            print(f'  {display}: OK last={data["c"][0]}')
    except Exception as e:
        print(f'  {display}: EXCEPTION {e}')
