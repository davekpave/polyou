import asyncio
import websockets

async def test(url):
    try:
        async with websockets.connect(
            url,
            additional_headers={
                "Origin": "https://polymarket.com",
                "User-Agent": "Mozilla/5.0",
            },
            subprotocols=["json"],   # <-- CRITICAL
        ):
            print("SUCCESS:", url)
    except Exception as e:
        print("FAIL:", url, "|", e)

async def main():
    urls = [
        "wss://ws-subscriptions-clob.polymarket.com/ws/",
    ]

    for u in urls:
        await test(u)

asyncio.run(main())