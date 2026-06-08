import os
from py_clob_client.client import ClobClient
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
c = ClobClient('https://clob.polymarket.com', 137, key=pk, funder=Account.from_key(pk).address)
c.set_api_creds(c.create_or_derive_api_creds())

trades = c.get_trades()
print(f'Found {len(trades)} trades via CLOB API.')
for i,t in enumerate(trades[:10]):
    print(f"{i+1}. Side: {t.get('side')} | Asset: {t.get('asset_id')} | Price: {t.get('price')} | Size: {t.get('size')} | Maker: {t.get('maker_address')} | Taker: {t.get('taker_address')}")

