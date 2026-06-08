import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient, OrderArgs
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
# Try a tiny FOK buy to see what the API returns! 
args = OrderArgs(token_id="38438147258954153838398053844164240828786167822502850200902530144246798646345", side="BUY", price=0.01, size=0)
try:
    o = c.client.create_order(args)
    r = c.client.post_order(o, orderType="FOK")
    print(json.dumps(r, indent=2))
except Exception as e:
    print(e)

