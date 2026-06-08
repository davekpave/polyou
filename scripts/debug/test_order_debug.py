import os
import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from eth_account import Account

# We can reuse the Polymarket proxy wallet
private_key = os.getenv("POLY_PRIVATE_KEY")
proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")

account = Account.from_key(private_key)
address = account.address
funder = proxy_address if proxy_address else address
signature_type = 2 if proxy_address else 0

client = ClobClient(
    host="https://clob.polymarket.com",
    key=private_key,
    chain_id=137,
    funder=funder,
    signature_type=signature_type,
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

print("Address", address)
print("Funder", funder)

# test market: let's get the active 15m btc market token
try:
    with open("src/polyou/execution/active_positions.json") as f:
        print("Positions", f.read())
except Exception:
    pass

