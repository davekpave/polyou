import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient
import py_clob_client.clob_types as ctypes
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
print(json.dumps(c.client.get_trades(ctypes.TradeParams()), indent=2)[:1000])

