"""
PolyouBot — minimal real-time leader copy trader (paper-only).

Replaces the prior 2k-line signal-generation bot. This version does one thing:
poll the top-N OOS-validated leader wallets from
``logs/oos_top_traders.csv`` and mirror any new BTC/ETH/SOL/XRP up-down
trade into the local ``ShadowPositionBook`` for paper P&L tracking.

Constructor + ``run()`` + ``_build_no_trade_metrics`` are preserved so
``src/run_polyou_bot.py`` continues to work unchanged.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import httpx

from polyou.execution.shadow_book import ShadowPositionBook
from polyou.utils.telegram_notifier import send_telegram_message

logger = logging.getLogger("polyou_bot")

# --------------------------------------------------
# Public surface re-used by the runner
# --------------------------------------------------
SAFE_MARKETS: Tuple[str, ...] = ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD")

# --------------------------------------------------
# Config
# --------------------------------------------------
DATA_API = "https://data-api.polymarket.com/trades"
LEADERS_FILE = Path("logs/oos_top_traders.csv")

# Blacklist: EMPTY until June 8, 2026 (30-day checkpoint)
# Running clean baseline with pure top-50 copying to establish true performance
# Lesson learned: early data too noisy, blocked 0xf3a71007 who became top 5 performer
# Will do comprehensive review at 30 days with 3x more data
BLACKLIST = set()

# Whitelist: if non-empty, only copy these leaders (overrides top_n selection).
# Set via COPY_WHITELIST env var as comma-separated addresses, or leave empty for all.
# June 8 analysis: best leaders by 30-day P&L and $/trade
WHITELIST: set[str] = set()

# Previously blocked (removed May 20 for clean baseline):
# 0x04849ea1c5dca8f6cae51a163734e5bec43cbe3f  # -$3.36, 70 trades, 2 losing days
# 0x460563d4d4f01f2ac5fb20da1b12af6f9321b773  # -$2.06, 6 trades, 1 day only
# 0xac6df77395095fd6a6f16e836ad845dd8cb0919a  # -$1.26, 5 trades, 2 losing days
# 0x5d3cc45e538130b02c8f3c821638ec9cd350c298  # -$1.16, 87 trades, 4-day decline
# 0xb4b5c838eee748bc8873d7065235d2802bb6879a  # -$0.69, 12 trades, had winning day
# 0xeebde7a0 UNBLOCKED: +$7.86 (was -$2.74 with stop-loss bug)
# 0xf3a71007 UNBLOCKED: +$3.74 (recovered after 1 bad day, now top 5)
# 0x43d20d9b UNBLOCKED: -$1.52 (only 1 day, insufficient data)

SLUG_RE = re.compile(r"^(btc|eth|sol|xrp)-updown-(5m|15m)-(\d+)$")
WINDOW_SECONDS = {"5m": 5 * 60, "15m": 15 * 60}
SYMBOL_FROM_SLUG = {
    "btc": "BTCUSD",
    "eth": "ETHUSD",
    "sol": "SOLUSD",
    "xrp": "XRPUSD",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class PolyouBot:
    """Minimal copy-trader. Paper-only via ``ShadowPositionBook``."""

    def __init__(
        self,
        *,
        market_data,
        read_only: bool = True,
        execution_client=None,
        clob_book_tracker=None,
    ):
        self.market_data = market_data
        self.read_only = read_only
        self.execution_client = execution_client  # currently unused (paper-only)
        self.clob_book_tracker = clob_book_tracker

        self.shadow_book = ShadowPositionBook(
            clob_book_tracker=clob_book_tracker,
            market_data=market_data,
        )

        # Tunables (env-overridable)
        self.top_n: int = _env_int("COPY_TOP_N_LEADERS", 40)
        self.poll_interval: float = _env_float("COPY_POLL_INTERVAL_SEC", 3.0)
        self.min_tte_sec: int = _env_int("COPY_MIN_TTE_SEC", 30)
        self.max_entry_price: float = _env_float("COPY_MAX_ENTRY_PRICE", 0.95)
        self.copy_only_buys: bool = os.getenv(
            "COPY_ONLY_BUYS", "true"
        ).lower() == "true"
        # 5m markets are not currently in the CLOB book tracker's discovery
        # set (it only probes 15m windows). Copying them yields
        # SETTLED_ZERO at expiry regardless of true outcome, polluting
        # paper P&L. Default-off until tracker is extended.
        self.include_5m: bool = os.getenv(
            "COPY_INCLUDE_5M", "false"
        ).lower() == "true"
        # Stop-loss threshold in P&L per share (e.g., -0.25 = cut losses at -25¢)
        # Set to None to disable (leaders use hold-to-expiry strategy)
        stop_loss_env = os.getenv("COPY_STOP_LOSS")
        self.stop_loss_threshold: Optional[float] = (
            float(stop_loss_env) if stop_loss_env else None
        )
        self.per_leader_limit: int = _env_int("COPY_LEADER_TRADE_LIMIT", 20)
        # Only copy DOWN trades (validated edge from 30-day analysis)
        # DOWN avg +$0.074/trade vs UP avg -$0.052/trade across all 4 weeks
        self.copy_only_down: bool = os.getenv(
            "COPY_ONLY_DOWN", "false"
        ).lower() == "true"
        # Minimum entry price filter: signals below this lose money (~19% win rate)
        self.min_entry_price: float = _env_float("COPY_MIN_PRICE", 0.0)
        # UTC hours to skip: validated dead zones (00=8pmET, 10=6amET, 17=1pmET)
        _skip_hours_env = os.getenv("COPY_SKIP_UTC_HOURS", "")
        self.skip_utc_hours: set[int] = {
            int(h.strip()) for h in _skip_hours_env.split(",") if h.strip().isdigit()
        }
        # Runtime whitelist override (comma-separated addresses)
        env_whitelist = os.getenv("COPY_WHITELIST", "")
        self._runtime_whitelist: set[str] = {
            a.strip().lower() for a in env_whitelist.split(",") if a.strip()
        } or {a.lower() for a in WHITELIST}

        self.leaders: list[str] = self._load_leaders()
        # Per-leader high-water-mark timestamp; only act on trades newer than this.
        self.last_seen_ts: Dict[str, int] = {}
        # Dedupe by (leader, txhash) across restarts is best-effort only.
        self.copied: Set[Tuple[str, str]] = set()

        # Stats
        self.n_polls = 0
        self.n_trades_seen = 0
        self.n_copied = 0
        self.n_skipped = 0

        logger.info(
            "PolyouBot (copy mode) ready | leaders=%d top_n=%d poll=%.1fs "
            "min_tte=%ds max_entry=%.2f stop_loss=%s read_only=%s "
            "copy_only_down=%s whitelist=%s",
            len(self.leaders), self.top_n, self.poll_interval,
            self.min_tte_sec, self.max_entry_price,
            "disabled" if self.stop_loss_threshold is None else f"{self.stop_loss_threshold:+.2f}",
            self.read_only,
            self.copy_only_down,
            len(self._runtime_whitelist) if self._runtime_whitelist else "all",
        )

    # ------------------------------------------------------------------
    # Leader list
    # ------------------------------------------------------------------
    def _load_leaders(self) -> list[str]:
        if not LEADERS_FILE.exists():
            logger.error("Leader file missing: %s", LEADERS_FILE)
            return []
        out: list[str] = []
        filtered = 0
        with LEADERS_FILE.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                addr = (row.get("address") or "").strip().lower()
                if addr.startswith("0x") and len(addr) == 42:
                    if addr in BLACKLIST:
                        filtered += 1
                        continue
                    if self._runtime_whitelist and addr not in self._runtime_whitelist:
                        continue
                    out.append(addr)
                if len(out) >= self.top_n:
                    break
        if filtered:
            logger.info("Filtered %d blacklisted addresses", filtered)
        if self._runtime_whitelist:
            logger.info("Whitelist active: copying %d leaders", len(out))
        return out

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    async def run(self) -> None:
        if not self.leaders:
            logger.error("No leaders to follow; idling.")
            while True:
                await asyncio.sleep(60)

        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "Mozilla/5.0 polyou-copy"},
        ) as client:
            while True:
                try:
                    await self._poll_once(client)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("copy loop iteration failed")

                # Always advance shadow-book bookkeeping.
                try:
                    self.shadow_book.tick()
                    # Check stop-loss before expiry to exit losing positions early
                    if self.stop_loss_threshold is not None:
                        self.shadow_book.settle_stop_loss(self.stop_loss_threshold)
                    self.shadow_book.settle_expired()
                except Exception:
                    logger.exception("shadow book maintenance failed")

                if self.n_polls % 100 == 0:
                    logger.info(
                        "copy stats | polls=%d seen=%d copied=%d skipped=%d open=%d",
                        self.n_polls, self.n_trades_seen, self.n_copied,
                        self.n_skipped, len(self.shadow_book.positions),
                    )

                await asyncio.sleep(self.poll_interval)

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        self.n_polls += 1
        # Poll all leaders in parallel; ignore individual failures.
        results = await asyncio.gather(
            *(self._fetch_leader(client, addr) for addr in self.leaders),
            return_exceptions=True,
        )
        for addr, res in zip(self.leaders, results):
            if isinstance(res, Exception) or not res:
                continue
            for trade in res:
                self._maybe_copy(addr, trade)

    async def _fetch_leader(
        self, client: httpx.AsyncClient, addr: str
    ) -> Optional[list[dict]]:
        try:
            r = await client.get(
                DATA_API,
                params={"user": addr, "limit": self.per_leader_limit},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, list) else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Copy decision
    # ------------------------------------------------------------------
    def _maybe_copy(self, leader: str, trade: dict) -> None:
        self.n_trades_seen += 1

        try:
            ts = int(trade.get("timestamp") or 0)
        except (TypeError, ValueError):
            return
        if ts <= 0:
            return

        # Skip anything we already saw (per-leader high-water-mark).
        hwm = self.last_seen_ts.get(leader, 0)
        if ts <= hwm:
            return
        # Always advance the HWM, even if we skip the trade for other reasons,
        # so we don't re-evaluate it forever.
        self.last_seen_ts[leader] = ts

        tx = str(trade.get("transactionHash") or "")
        key = (leader, tx)
        if tx and key in self.copied:
            return

        slug = str(trade.get("slug") or trade.get("eventSlug") or "")
        m = SLUG_RE.match(slug)
        if not m:
            self.n_skipped += 1
            return
        sym_short, window_label, ws_str = m.group(1), m.group(2), m.group(3)
        if window_label == "5m" and not self.include_5m:
            self.n_skipped += 1
            return
        symbol = SYMBOL_FROM_SLUG[sym_short]
        window_start = int(ws_str)
        window_end = window_start + WINDOW_SECONDS[window_label]

        # Time-to-expiry gate: too late to copy.
        now = int(time.time())
        tte = window_end - now
        if tte < self.min_tte_sec:
            self.n_skipped += 1
            return

        side_raw = str(trade.get("side") or "").upper()

        # Mirror leader early exits: if the leader is selling a token we hold,
        # close our shadow position (and live position if execution enabled).
        if side_raw == "SELL":
            token_id = str(trade.get("asset") or "")
            if token_id:
                try:
                    exit_price = float(trade.get("price") or 0.0)
                except (TypeError, ValueError):
                    exit_price = 0.0
                if exit_price > 0.0:
                    closed_id = self.shadow_book.settle_leader_exit(
                        leader_address=leader,
                        token_id=token_id,
                        exit_price=exit_price,
                    )
                    if closed_id is not None:
                        logger.info(
                            "LEADER_EXIT | leader=%s token=%s exit_px=%.4f tx=%s",
                            leader[:10], token_id[:10], exit_price, tx[:10],
                        )
                        if not self.read_only and self.execution_client is not None:
                            asyncio.create_task(
                                self.execution_client.sell_position(
                                    token_id=token_id,
                                    price=exit_price,
                                ),
                                name=f"sell_{token_id[:10]}",
                            )
                        if not self.read_only:
                            try:
                                send_telegram_message(
                                    f"🚪 LEADER EXIT | token={token_id[:10]}\n"
                                    f"exit_price={exit_price:.3f}\n"
                                    f"leader={leader[:10]}"
                                )
                            except Exception:
                                pass
            return  # Never treat a SELL as a new entry

        if self.copy_only_buys and side_raw != "BUY":
            self.n_skipped += 1
            return

        try:
            price = float(trade.get("price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0.0 or price > self.max_entry_price:
            self.n_skipped += 1
            return

        if self.min_entry_price > 0.0 and price < self.min_entry_price:
            self.n_skipped += 1
            return

        if self.skip_utc_hours:
            import datetime
            current_utc_hour = datetime.datetime.utcnow().hour
            if current_utc_hour in self.skip_utc_hours:
                self.n_skipped += 1
                return

        outcome = str(trade.get("outcome") or "").upper()
        # Polymarket up-down markets: outcome is "Up"/"Down" → side label.
        if outcome in ("UP", "YES"):
            side_label = "UP"
        elif outcome in ("DOWN", "NO"):
            side_label = "DOWN"
        else:
            self.n_skipped += 1
            return

        # DOWN-only filter: validated 30-day edge (DOWN +$0.074/trade, UP -$0.052/trade)
        if self.copy_only_down and side_label != "DOWN":
            self.n_skipped += 1
            return

        token_id = str(trade.get("asset") or "")
        if not token_id:
            self.n_skipped += 1
            return

        # For live orders, record the actual fill price (snapshot + entry buffer)
        # so shadow EV accurately reflects real cost. Paper mode uses snapshot as-is.
        _ENTRY_BUFFER = 0.02  # must match execution_client.py guaranteed_buy_price
        live_entry_price = (
            min(0.85, round(price + _ENTRY_BUFFER, 2))
            if not self.read_only else None
        )
        position_id = self.shadow_book.open(
            token_id=token_id,
            symbol=symbol,
            side=side_label,
            snapshot_price=price,
            entry_price=live_entry_price,
            window_end_ts=window_end,
            leader_address=leader,
            contract_slug=slug,
            window_seconds=WINDOW_SECONDS[window_label],
        )
        if position_id is None:
            # Already shadowing this token (another leader got here first).
            return

        self.copied.add(key)
        self.n_copied += 1
        logger.info(
            "COPY | leader=%s sym=%s side=%s slug=%s px=%.4f tte=%ds tx=%s",
            leader[:10], symbol, side_label, slug, price, tte, tx[:10],
        )
        if not self.read_only:
            try:
                send_telegram_message(
                    f"📋 COPY | {symbol} {side_label}\n"
                    f"price={price:.3f} tte={tte}s\n"
                    f"leader={leader[:10]}\n"
                    f"slug={slug}"
                )
            except Exception:
                logger.exception("Telegram COPY notification failed")

        # Live execution: place real order if execution client is available.
        # Position size set to minimum ($1 USDC notional) via COPY_TRADE_SIZE env var.
        if not self.read_only and self.execution_client is not None:
            trade_size = _env_float("COPY_TRADE_SIZE", 1.0)
            asyncio.create_task(
                self.execution_client.execute_trade(
                    symbol=symbol,
                    contract_slug=slug,
                    token_id=token_id,
                    side=side_label,
                    price=price,
                    size=trade_size,
                    window_end_ts=window_end,
                ),
                name=f"execute_{position_id}",
            )

    # ------------------------------------------------------------------
    # Compatibility shim (referenced by run_polyou_bot._repair_*)
    # ------------------------------------------------------------------
    def _build_no_trade_metrics(self, *_args, **_kwargs) -> Dict[str, Any]:
        return {}
