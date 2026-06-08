import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient, OpenOrderParams
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
print(json.dumps(c.client.get_orders(OpenOrderParams(market="38438147258954153838398053844164240828786167822502850200902530144246798646345")), indent=2))

