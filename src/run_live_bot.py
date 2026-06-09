"""
Live trading bot runner.

Runs alongside run_polyou_bot.py (paper) with separate lock file and log files.
Uses COPY_WHITELIST, COPY_ONLY_DOWN, and EXECUTION_ENABLED=true.

Launch example:
    $env:COPY_WHITELIST="0xa3d043b2da27b9b20d27d71f0f3d05bd1c070d5e,0x01b739b360d3c2f6cc8ec84cda900d48650e2eca,0x08ec01051d8fe6c4ff5f9e1d18ab61d23454f46f,0xeebde7a0e019a63e6b476eb425505b7b3e6eba30,0x14774b671287348daa324e8404e5f608e3acbe50,0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82"
    $env:COPY_ONLY_DOWN="true"
    $env:EXECUTION_ENABLED="true"
    $env:READ_ONLY_MODE="false"
    $env:SHADOW_EXITS_FILE="logs/live_shadow_exits.csv"
    $env:PYTHONPATH="src"
    .\.venv\Scripts\python.exe src\run_live_bot.py
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
import httpx
import json as _json

from dotenv import load_dotenv
load_dotenv()

import sys
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Force separate log files before any imports that read env
os.environ.setdefault("SHADOW_EXITS_FILE", "logs/live_shadow_exits.csv")

from polyou.bots.polyou_bot import PolyouBot
import polyou.bots.polyou_bot as polyou_bot_module
from polyou.core.data import MarketData
from polyou.data.chainlink_streams_poller import ChainlinkStreamsPoller
from polyou.data.clob_book_tracker import ClobBookTracker
from polyou.bots.polyou_bot import SAFE_MARKETS as _SAFE_MARKETS

ExecutionClient = None

# --------------------------------------------------
# TOKEN RESOLVER (copied from run_polyou_bot.py)
# --------------------------------------------------

_token_cache = {}

async def resolve_token_id(slug: str, direction: str):
    cache_key = f"{slug}:{direction}"
    if cache_key in _token_cache:
        return _token_cache[cache_key]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://gamma-api.polymarket.com/events?slug={slug}"
            )
            if r.status_code != 200:
                return None
            data = r.json()
            events = data.get("events") if isinstance(data, dict) else data
            if not events:
                return None
            event = events[0]
            markets = event.get("markets") or []
            if not markets:
                return None
            market = markets[0]
            for token in market.get("tokens", []):
                outcome = str(token.get("outcome", "")).upper()
                if outcome == direction or (outcome == "YES" and direction == "UP") or (outcome == "NO" and direction == "DOWN"):
                    token_id = token.get("tokenId")
                    if token_id:
                        _token_cache[cache_key] = token_id
                        return token_id
            token_ids = market.get("clobTokenIds")
            if token_ids:
                if isinstance(token_ids, str):
                    token_ids = _json.loads(token_ids)
                if len(token_ids) >= 2:
                    token_id = token_ids[0] if direction == "UP" else token_ids[1]
                    _token_cache[cache_key] = token_id
                    return token_id
    except Exception as e:
        logger.error("Resolver error | %s | %s", slug, str(e))
    return None

# --------------------------------------------------
# ET-aware logging → separate live log files
# --------------------------------------------------

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None


class ETFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=ET or timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S ET")


os.makedirs("logs", exist_ok=True)

handler = logging.StreamHandler()
handler.setFormatter(ETFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

file_handler = logging.FileHandler("logs/live_bot.log", encoding="utf-8")
file_handler.setFormatter(ETFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

root = logging.getLogger()
root.setLevel(logging.INFO)
root.handlers.clear()
root.addHandler(handler)
root.addHandler(file_handler)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("run_live_bot")


# --------------------------------------------------
# Async runner
# --------------------------------------------------

async def main_async():
    read_only = os.getenv("READ_ONLY_MODE", "false").lower() == "true"
    execution_enabled = os.getenv("EXECUTION_ENABLED", "true").lower() == "true"
    copy_only_down = os.getenv("COPY_ONLY_DOWN", "true").lower() == "true"
    whitelist = os.getenv("COPY_WHITELIST", "")

    logger.info("==============================================")
    logger.info("Starting LIVE PolyouBot runner")
    logger.info("READ_ONLY_MODE=%s", read_only)
    logger.info("EXECUTION_ENABLED=%s", execution_enabled)
    logger.info("COPY_ONLY_DOWN=%s", copy_only_down)
    logger.info("COPY_WHITELIST=%s", whitelist or "(not set - copying all leaders)")
    logger.info("SHADOW_EXITS_FILE=%s", os.environ.get("SHADOW_EXITS_FILE"))
    logger.info("==============================================")

    if not execution_enabled:
        logger.warning("EXECUTION_ENABLED is false — live bot will not place real orders")

    market_data = MarketData()
    chainlink = ChainlinkStreamsPoller(market_data=market_data)
    chainlink_task = asyncio.create_task(chainlink.run(), name="chainlink_streams_poller")

    clob_tracker = ClobBookTracker(symbols=_SAFE_MARKETS)
    clob_tracker_task = asyncio.create_task(clob_tracker.run(), name="clob_book_tracker")

    execution_client = None
    if execution_enabled:
        from polyou.execution.execution_client import ExecutionClient
        execution_client = ExecutionClient(
            base_url=os.getenv("POLYMARKET_BASE_URL"),
        )
        logger.info("Execution enabled — testing connectivity")
        ok = await execution_client.test_order_capability()
        if not ok:
            logger.error("Execution test failed — aborting startup")
            return
    else:
        logger.info("Execution disabled — running in signal-only mode")

    bot = PolyouBot(
        market_data=market_data,
        read_only=read_only,
        execution_client=execution_client,
        clob_book_tracker=clob_tracker,
    )

    bot_task = asyncio.create_task(bot.run(), name="live_bot")

    stop_event = asyncio.Event()

    def _shutdown():
        logger.warning("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("Cancelling tasks...")
        for task in (chainlink_task, clob_tracker_task, bot_task):
            task.cancel()
        await asyncio.gather(
            chainlink_task, clob_tracker_task, bot_task, return_exceptions=True
        )
        logger.info("Shutdown complete")


# --------------------------------------------------
# Separate lock file from paper bot
# --------------------------------------------------

_LIVE_LOCK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "polyou_live_bot.lock"
)
_live_lock_handle = None


def _acquire_live_lock():
    global _live_lock_handle
    lock_path = os.path.abspath(_LIVE_LOCK_PATH)
    try:
        handle = open(lock_path, "a+")
    except OSError as e:
        print(f"[FATAL] Could not open lock file {lock_path}: {e}")
        sys.exit(1)
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        existing_pid = ""
        try:
            handle.seek(0)
            existing_pid = handle.read().strip()
        except Exception:
            pass
        handle.close()
        print(
            f"[FATAL] Another live bot instance is already running"
            f"{f' (pid {existing_pid})' if existing_pid else ''}."
        )
        sys.exit(1)
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except Exception:
        pass
    _live_lock_handle = handle


def main():
    _acquire_live_lock()
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
