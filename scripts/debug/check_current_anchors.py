#!/usr/bin/env python3
"""
Quick script to check current Chainlink anchor prices
"""
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, 'src')

from polyou.data.chainlink_streams_poller import ChainlinkStreamsPoller
from polyou.core.data import MarketData


async def main():
    symbols = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'XRPUSD']
    bus = MarketData()
    poller = ChainlinkStreamsPoller(market_data=bus)
    
    print("Fetching current Chainlink oracle prices...")
    print("-" * 60)
    
    now = datetime.now(tz=timezone.utc)
    # Determine current 15-minute window
    minute = (now.minute // 15) * 15
    window_time = now.replace(minute=minute, second=0, microsecond=0)
    
    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"Current 15-min window: {window_time.strftime('%Y-%m-%d %H:%M')} UTC")
    print("-" * 60)
    print("\nCurrent Chainlink Oracle Prices (Anchor Reference):")
    print("-" * 60)
    
    for sym in symbols:
        try:
            price, ts = await poller._fetch_chainlink_onchain(sym)
            print(f"{sym:8s}: ${price:,.8f}")
        except Exception as e:
            print(f"{sym:8s}: ERROR - {e}")
    
    print("-" * 60)
    print("\nThese are the prices from Chainlink Classic Price Feeds on Arbitrum.")
    print("Compare these to Polymarket's displayed anchor prices.")


if __name__ == '__main__':
    asyncio.run(main())
