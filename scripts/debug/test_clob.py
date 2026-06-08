import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from eth_account import Account

load_dotenv()
pk = os.getenv("POLY_PRIVATE_KEY")
address = Account.from_key(pk).address

c = ClobClient(
    host="https://clob.polymarket.com",
    key=pk,
    chain_id=137,
    funder=address,
)
c.set_api_creds(c.create_or_derive_api_creds())

# get open orders
try:
    orders = c.get_orders()
    print("Open Orders using ClobClient:")
    print(orders)
except Exception as e:
    print("Error getting open orders:", e)

# get history? We can use the execution_client maybe?
