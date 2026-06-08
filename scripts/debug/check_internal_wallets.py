import os, sys, requests, web3
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
addr = Account.from_key(pk).address if pk else None
if not addr: sys.exit('No key found.')

w3 = web3.Web3(web3.Web3.HTTPProvider('https://polygon.drpc.org'))

# Query proxy wallet via Relayer API (standard procedure for PM)
r = requests.get(f"https://relayer.polymarket.com/proxy-wallet?owner={addr}")
if r.status_code == 200 and r.json().get('address'):
    proxy = r.json().get('address')
    print(f"PROXY FOUND: {proxy}")
else:
    print("NO PROXY API RETURN")

