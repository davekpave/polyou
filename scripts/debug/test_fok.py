import os, json, requests
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient, OrderArgs
from py_clob_client.clob_types import OrderType
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
for tk in requests.get("https://clob.polymarket.com/markets?limit=25&active=true").json()['data']:
  if tk.get('accepting_orders') and len(tk.get('tokens', [])) > 1:
    args = OrderArgs(token_id=tk['tokens'][1]['token_id'], side="SELL", price=0.99, size=5)
    try:
        o = c.client.create_order(args)
        r = c.client.post_order(o, orderType=OrderType.FOK)
        print(json.dumps(r, indent=2))
        break
    except Exception as e:
        print(e)

