import os, json
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient
import py_clob_client.clob_types as ctypes
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
print(c.client.get_balance_allowance(ctypes.BalanceAllowanceParams(asset_type=ctypes.AssetType.CONDITIONAL, signature_type=2, token_id="38438147258954153838398053844164240828786167822502850200902530144246798646345")))

