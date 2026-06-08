#!/usr/bin/env python3
"""
Check Token Allowance Status for Polymarket CLOB

This script checks your current token allowances for the CLOB Exchange.

Usage:
    python scripts/check_allowances.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType


def check_allowances():
    print("=" * 60)
    print("Polymarket Token Allowance Status")
    print("=" * 60)
    
    # Load credentials
    private_key = os.getenv("POLY_PRIVATE_KEY")
    if not private_key:
        print("❌ ERROR: POLY_PRIVATE_KEY environment variable not set")
        sys.exit(1)
    
    # Get wallet address
    account = Account.from_key(private_key)
    address = account.address
    
    # Check for proxy wallet
    proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")
    funder = proxy_address if proxy_address else address
    signature_type = 2 if proxy_address else 0
    
    print(f"Signer Address: {address}")
    if proxy_address:
        print(f"Proxy Wallet: {proxy_address}")
    print(f"Funder Address: {funder}")
    print()
    
    # Initialize client
    print("Initializing CLOB client...")
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=137,
        funder=funder,
        signature_type=signature_type,
    )
    
    # Create API creds
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    print("✅ Client initialized\n")
    
    # Check allowances
    try:
        print("Checking token allowances...")
        
        conditional_params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL)
        conditional_allowance = client.get_balance_allowance(params=conditional_params)
        
        collateral_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        collateral_allowance = client.get_balance_allowance(params=collateral_params)
        
        print()
        print(f"Conditional Tokens (Outcome Shares) Allowance: {conditional_allowance}")
        print(f"Collateral (USDC) Allowance: {collateral_allowance}")
        print()
        
        if conditional_allowance > 10**60:
            print("✅ Conditional allowance is set (unlimited)")
            print("   Your bot should be able to close positions.")
        elif conditional_allowance > 0:
            print(f"⚠️  Conditional allowance is limited: {conditional_allowance}")
            print("   You may encounter errors when closing positions.")
            print("   Run scripts/fix_allowances.py to fix this.")
        else:
            print("❌ No conditional allowance set!")
            print("   Your bot CANNOT close positions.")
            print("   Run scripts/fix_allowances.py to fix this.")
        
    except Exception as e:
        print(f"❌ ERROR checking allowances: {e}")
        print()
        print("This may indicate:")
        print("  1. Network connection issues")
        print("  2. Incorrect wallet configuration")
        print("  3. Missing py_clob_client method (old SDK version)")


if __name__ == "__main__":
    check_allowances()
