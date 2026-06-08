import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
resp = c.client.get_order("38438147258954153838398053844164240828786167822502850200902530144246798646345")
print(json.dumps(resp, indent=2))

