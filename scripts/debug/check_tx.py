import requests

addr = '0x415C6EA0F432fE64477d83355595f36Ca385E68f'
url = f'https://api.polygonscan.com/api?module=account&action=tokentx&address={addr}&startblock=0&endblock=99999999&page=1&offset=20&sort=desc'
r = requests.get(url).json()

if r.get('status') == '1':
    for tx in r.get('result', []):
        sym = tx.get('tokenSymbol')
        dec = int(tx.get('tokenDecimal', 18))
        val = int(tx.get('value', 0)) / (10 ** dec)
        print(f"{sym:<10} | {val:,.4f} | To: {tx.get('to')} | From: {tx.get('from')}")
else:
    print('No results or error')
