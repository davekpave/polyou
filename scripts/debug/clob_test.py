import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')

client = ClobClient(
    host='https://clob.polymarket.com',
    key=pk,
    chain_id=137
)

creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
print('Funder address:', creds.address if hasattr(creds, 'address') else 'unknown')
print('Client Funder Method:', client.get_funder_address() if hasattr(client, 'get_funder_address') else getattr(client, 'funder', None))

