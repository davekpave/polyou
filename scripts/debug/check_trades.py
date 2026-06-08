import os
import dotenv
from py_clob_client.client import ClobClient

dotenv.load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')

try:
    client = ClobClient(
        host='https://clob.polymarket.com',
        key=pk,
        chain_id=137
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    print("Recent Trades:")
    trades = client.get_trades()
    print(trades)
    
except Exception as e:
    print("Error:", e)
