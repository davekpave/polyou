"""
Debug script to inspect order response fields from Polymarket CLOB API.
Run this after a trade executes to see what fields are available.
"""
import os
import sys
import json
from py_clob_client.client import ClobClient
from eth_account import Account

def main():
    if len(sys.argv) < 2:
        print("Usage: python inspect_order_response.py <order_id>")
        print("\nGet order_id from bot logs or recent trade")
        return
    
    order_id = sys.argv[1]
    
    private_key = os.getenv("POLY_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLY_PRIVATE_KEY environment variable not set")
        return
    
    proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")
    account = Account.from_key(private_key)
    funder = proxy_address if proxy_address else account.address
    signature_type = 2 if proxy_address else 0
    
    print(f"Initializing client for funder: {funder}")
    
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=137,
        funder=funder,
        signature_type=signature_type,
    )
    
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    
    print(f"\nFetching order: {order_id}")
    
    try:
        response = client.get_order(order_id)
        print("\n" + "="*80)
        print("ORDER RESPONSE:")
        print("="*80)
        print(json.dumps(response, indent=2))
        print("="*80)
        
        # Highlight key fields
        print("\n🔍 KEY FIELDS:")
        print(f"  status: {response.get('status')}")
        print(f"  state: {response.get('state')}")
        print(f"  size: {response.get('size')}")
        print(f"  original_size: {response.get('original_size')}")
        print(f"  size_matched: {response.get('size_matched')}")
        print(f"  filled_size: {response.get('filled_size')}")
        print(f"  sizeMached: {response.get('sizeMached')}")
        print(f"  price: {response.get('price')}")
        print(f"  created_at: {response.get('created_at')}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
