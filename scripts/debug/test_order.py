import os
from dotenv import load_dotenv
load_dotenv()
from py_clob_client.client import ClobClient
import json
from polyou.execution.execution_client import ExecutionClient
c=ExecutionClient(base_url="https://clob.polymarket.com")
print(json.dumps(c.client.get_order("0x5ca9c68ea8af4a03abf4684949a2ee6f4e15baee7dbbaadc84bfa6caecb7f6fa"), indent=2))

