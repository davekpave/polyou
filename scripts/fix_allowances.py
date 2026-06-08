#!/usr/bin/env python3
"""
Fix Token Allowances for Polymarket CLOB Trading

This script sets unlimited token allowances for the CLOB Exchange contract
to spend your outcome tokens (shares). This is required to sell positions.

Usage:
    python scripts/fix_allowances.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType


def fix_allowances():
    print("=" * 60)
    print("Polymarket Token Allowance Fix")
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
    
    # Set token allowances
    try:
        print("Setting token allowances...")
        print("(This will submit a blockchain transaction)")
        print()
        
        # Set allowance for outcome tokens (CONDITIONAL) and USDC (COLLATERAL)
        conditional_params = BalanceAllowanceParams(asset_type=AssetType.CONDITIONAL)
        client.update_balance_allowance(params=conditional_params)
        
        collateral_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.update_balance_allowance(params=collateral_params)
        
        print("✅ Token allowances set successfully!")
        print()
        print("Details:")
        print(f"  Transaction: {result}")
        print()
        print("You can now close positions on Polymarket CLOB.")
        print("Restart your trading bot for the changes to take effect.")
        
    except Exception as e:
        error_str = str(e).lower()
        
        # Check if already approved
        if "already" in error_str or "sufficient" in error_str:
            print("✅ Token allowances already set (no action needed)")
        else:
            print(f"❌ ERROR setting allowances: {e}")
            print()
            print("Possible reasons:")
            print("  1. Insufficient gas (MATIC) in your wallet")
            print("  2. Network connection issues")
            print("  3. Proxy wallet configuration problem")
            print()
            print("Try again or check Polymarket UI to manually approve.")
            sys.exit(1)


if __name__ == "__main__":
    fix_allowances()
