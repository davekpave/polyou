import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient, OpenOrderParams
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
print(json.dumps(c.client.get_orders(OpenOrderParams(client_order_id="xrp-updown-15m-1776691800:DOWN:1776692700")), indent=2))

