import asyncio
from dotenv import load_dotenv
import logging
import os
import signal
import sys
from datetime import datetime, timezone
import httpx
import json as _json

# --------------------------------------------------
# ENV
# --------------------------------------------------

load_dotenv()

# --------------------------------------------------
# Imports
# --------------------------------------------------

from polyou.bots.polyou_bot import PolyouBot
import polyou.bots.polyou_bot as polyou_bot_module
from polyou.core.data import MarketData
from polyou.data.chainlink_streams_poller import ChainlinkStreamsPoller
from polyou.data.clob_book_tracker import ClobBookTracker
from polyou.bots.polyou_bot import SAFE_MARKETS as _SAFE_MARKETS
from polyou.utils.telegram_notifier import send_telegram_message

ExecutionClient = None

# --------------------------------------------------
# TOKEN RESOLVER (FULL + FALLBACK RESTORED)
# --------------------------------------------------

_token_cache = {}

async def resolve_token_id(slug: str, direction: str):
    cache_key = f"{slug}:{direction}"
    if cache_key in _token_cache:
        return _token_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            # -----------------------------
            # Primary: Gamma events API
            # -----------------------------
            r = await client.get(
                f"https://gamma-api.polymarket.com/events?slug={slug}"
            )

            if r.status_code != 200:
                logger.error("Events API failed | %s | %s", slug, r.status_code)
                return None

            data = r.json()
            events = data.get("events") if isinstance(data, dict) else data

            if not events:
                logger.error("No events found | %s", slug)
                return None

            event = events[0]
            markets = event.get("markets") or []

            if not markets:
                logger.error("No markets in event | %s", slug)
                return None

            market = markets[0]
            
            # --- FIX: ALWAYS use the specific 'tokens' array first because Polymarket Gamma API ---
            # --- has a bug where clobTokenIds on crypto 15m markets returns a Mavericks NBA game ---
            for token in market.get("tokens", []):
                outcome = str(token.get("outcome", "")).upper()
                if outcome == direction or (outcome == "YES" and direction == "UP") or (outcome == "NO" and direction == "DOWN"):
                    token_id = token.get("tokenId")
                    if token_id:
                        _token_cache[cache_key] = token_id
                        return token_id

            # Fallback if tokens array is absent
            token_ids = market.get("clobTokenIds")

            if token_ids:
                if isinstance(token_ids, str):
                    token_ids = _json.loads(token_ids)

                if len(token_ids) >= 2:
                    token_id = token_ids[0] if direction == "UP" else token_ids[1]
                    _token_cache[cache_key] = token_id
                    return token_id

            # -----------------------------
            # Fallback: conditionId → CLOB
            # -----------------------------
            condition_id = market.get("conditionId")

            if not condition_id:
                logger.error("Missing conditionId | %s", slug)
                return None

            r2 = await client.get(
                f"https://clob.polymarket.com/rewards/markets/{condition_id}?sponsored=true"
            )

            if r2.status_code != 200:
                logger.error("CLOB market fetch failed | %s", condition_id)
                return None

            clob_data = r2.json()
            tokens = clob_data.get("tokens") or clob_data.get("outcomes")

            if not tokens or len(tokens) < 2:
                logger.error("Invalid tokens from CLOB | %s", condition_id)
                return None

            token_ids = [t["id"] for t in tokens]
            token_id = token_ids[0] if direction == "UP" else token_ids[1]

            _token_cache[cache_key] = token_id
            return token_id

    except Exception as e:
        logger.error("Resolver error | %s | %s", slug, str(e))
        return None

# --------------------------------------------------
# ET-aware logging
# --------------------------------------------------

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None


class ETFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(
            record.created,
            tz=ET or timezone.utc,
        )
        return dt.strftime("%Y-%m-%d %H:%M:%S ET")


handler = logging.StreamHandler()
handler.setFormatter(
    ETFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

os.makedirs("logs", exist_ok=True)
file_handler = logging.FileHandler("logs/bot.log", encoding="utf-8")
file_handler.setFormatter(
    ETFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

root = logging.getLogger()
root.setLevel(logging.INFO)
root.handlers.clear()
root.addHandler(handler)
root.addHandler(file_handler)

# Keep external transport logs quiet in normal runs; warnings/errors still surface.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("run_polyou_bot")

# --------------------------------------------------
# SAFETY: Repair missing methods
# --------------------------------------------------

def _repair_polyoubot_class_scope() -> None:
    repaired = []

    if not callable(getattr(PolyouBot, "run", None)):
        module_run = getattr(polyou_bot_module, "run", None)
        if callable(module_run):
            setattr(PolyouBot, "run", module_run)
            repaired.append("run")

    if not callable(getattr(PolyouBot, "_build_no_trade_metrics", None)):
        module_metrics = getattr(polyou_bot_module, "_build_no_trade_metrics", None)
        if callable(module_metrics):
            setattr(PolyouBot, "_build_no_trade_metrics", module_metrics)
            repaired.append("_build_no_trade_metrics")

    if repaired:
        logger.warning(
            "Recovered PolyouBot class methods from module scope: %s",
            ", ".join(repaired),
        )

# --------------------------------------------------
# Async runner
# --------------------------------------------------

async def main_async():
    _repair_polyoubot_class_scope()

    read_only = os.getenv("READ_ONLY_MODE", "true").lower() == "true"
    telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    execution_enabled = os.getenv("EXECUTION_ENABLED", "false").lower() == "true"
    has_env_api_creds = all(
        bool(os.getenv(name))
        for name in ("POLY_API_KEY", "POLY_API_SECRET", "POLY_API_PASSPHRASE")
    )
    has_private_key = bool(os.getenv("POLY_PRIVATE_KEY"))

    logger.info("==============================================")
    logger.info("Starting PolyouBot runner (ORACLE-NATIVE, SAFE)")
    logger.info("Resolver mode: events + clob (15m)")
    logger.info("READ_ONLY_MODE=%s", read_only)
    logger.info("TELEGRAM_ENABLED=%s", telegram_enabled)
    logger.info("EXECUTION_ENABLED=%s", execution_enabled)
    logger.info(
        "Auth mode hint: %s",
        "env-api-creds" if has_env_api_creds else "wallet-derive-fallback",
    )
    logger.info("POLY_PRIVATE_KEY present=%s", has_private_key)
    logger.info("==============================================")

    if telegram_enabled:
        try:
            send_telegram_message(
                "🚀 PolyouBot started successfully.\n"
                f"READ_ONLY_MODE={read_only}"
            )
        except Exception:
            logger.exception("Telegram startup ping failed")

    market_data = MarketData()

    chainlink = ChainlinkStreamsPoller(market_data=market_data)
    chainlink_task = asyncio.create_task(chainlink.run(), name="chainlink_streams_poller")

    # Phase 1: read-only CLOB book tracker. Diagnostic only — does not feed
    # any trading decision. Used to log Polymarket reprice latency next to
    # our own R:R block events.
    clob_tracker = ClobBookTracker(symbols=_SAFE_MARKETS)
    clob_tracker_task = asyncio.create_task(
        clob_tracker.run(), name="clob_book_tracker"
    )

    execution_client = None

    # --------------------------------------------------
    # EXECUTION CLIENT (FIXED)
    # --------------------------------------------------

    if execution_enabled:
        from polyou.execution.execution_client import ExecutionClient
        from eth_account import Account

        private_key = os.getenv("POLY_PRIVATE_KEY")

        acct = Account.from_key(private_key)
        logger.info("Execution signer address: %s", acct.address)

        # ✅ FIX: remove unused api_key argument
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

    # --------------------------------------------------

    bot = PolyouBot(
        market_data=market_data,
        read_only=read_only,
        execution_client=execution_client,
        clob_book_tracker=clob_tracker,
    )

    if not callable(getattr(bot, "run", None)):
        raise RuntimeError("PolyouBot.run is missing.")

    bot_task = asyncio.create_task(bot.run(), name="polyou_bot")

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


_SINGLE_INSTANCE_LOCK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "polyou_bot.lock"
)
# Module-level reference keeps the OS lock alive for the process lifetime.
_single_instance_handle = None


def _acquire_single_instance_lock():
    """
    Ensure only one PolyouBot process can run at a time.
    Uses an exclusive, non-blocking OS file lock. Releases automatically
    when the process exits (handle closed by the OS).
    """
    global _single_instance_handle

    lock_path = os.path.abspath(_SINGLE_INSTANCE_LOCK_PATH)

    try:
        # Open (create if needed) without truncating, so we can write our PID
        # while another process still holds the lock.
        handle = open(lock_path, "a+")
    except OSError as e:
        print(f"[FATAL] Could not open lock file {lock_path}: {e}")
        sys.exit(1)

    try:
        if os.name == "nt":
            import msvcrt
            # Always lock the SAME byte (offset 0) so concurrent processes
            # actually contend. msvcrt.locking() locks at the current file
            # position, and "a+" leaves the position at end-of-file.
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
        msg = (
            f"[FATAL] Another PolyouBot instance is already running"
            f"{f' (pid {existing_pid})' if existing_pid else ''}. "
            f"Lock file: {lock_path}"
        )
        print(msg)
        sys.exit(1)

    # Record our PID for diagnostics.
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except Exception:
        pass

    _single_instance_handle = handle


def main():
    _acquire_single_instance_lock()
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()