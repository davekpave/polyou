"""
PolyouBot
"""
from typing import Dict, Any, Iterable, Tuple
import asyncio
import logging
import time
import math
import statistics
import os
import csv
import json
import random
import httpx
from collections import deque
from datetime import datetime, timezone
from polyou.core.data import MarketData, SpotPriceEvent
from polyou.utils.alerts import emit_alert
from polyou.markets.polymarket_crypto_resolver import resolve_crypto_contract
from polyou.markets.gamma_outcome import fetch_resolved_outcome
from polyou.utils.decision_email import send_decision_email
from polyou.execution.shadow_book import ShadowPositionBook
from polyou.utils import aux_logs

logger = logging.getLogger("polyou_bot")

# --------------------------------------------------
# Configuration
# --------------------------------------------------
# Data-driven symbol filter.
# Per combined audit (archive + bot.log, Apr 14-27 2026, n=166 settled trades via Gamma):
#   XRP: 14W/2L  (87.5% WR, EV +$0.148/trade)  -> ENABLED (best performer)
#   BTC: 48W/16L (75.0% WR, EV +$0.025/trade)  -> DISABLED 2026-04-30: rr_blocks
#                EV analysis (n=2218 candidates, Apr 29-30) shows BTC is -EV at
#                every R:R threshold tested (0.15-0.40). Re-enable only with a
#                BTC-specific gate that screens out the losing population.
#   SOL: 15W/5L  (75.0% WR, EV +$0.025/trade)  -> ENABLED (reinstated; old comment
#                claiming 4.4% WR was contradicted by the archive)
#   ETH: 46W/20L (69.7% WR, EV -$0.027/trade)  -> DISABLED (only -EV symbol;
#                largest sample so unlikely to be noise. Re-evaluate after
#                threshold tuning.)
# Break-even WR ~72.4% (entry ~0.70, win pays ~1.00).
SAFE_MARKETS = (
    # All symbols enabled for paper-trading / data collection (not live).
    # Re-narrow this list before re-enabling live execution per EV audit.
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "XRPUSD",
)

SYMBOL_MAP = {
    "BTCUSD": "BTC",
    "ETHUSD": "ETH",
    "SOLUSD": "SOL",
    "XRPUSD": "XRP",
}


# --- Window durations for 5m/15m support ---
WINDOW_DURATIONS_SEC = {
    "5m": 5 * 60,
    "15m": 15 * 60,
}

# Helper to get window duration from slug
def get_window_duration_from_slug(slug: str) -> int:
    if "-updown-5m-" in slug:
        return WINDOW_DURATIONS_SEC["5m"]
    if "-updown-15m-" in slug:
        return WINDOW_DURATIONS_SEC["15m"]
    # Default to 15m for safety
    return WINDOW_DURATIONS_SEC["15m"]

# --------------------------------------------------
# Re-entry micro movement guard
# --------------------------------------------------
MIN_REENTRY_MOVE_PCT = 0.0004 # 0.04%

# --------------------------------------------------
# Dynamic Position Sizing
# --------------------------------------------------
POSITION_SIZE_STANDARD = 5.0
POSITION_SIZE_STRONG = 7.5
POSITION_SIZE_EXCEPTIONAL = 10.0

# --------------------------------------------------
# Data-Driven Trade Filters (from deep-dive analysis)
# --------------------------------------------------
# Entry price filter.
# Original (0.70): set from analysis based on `predicted_side_won`, which we
# later found was derived from exit-type (sold vs settled-zero), not from
# real chainlink outcome. That flag misclassified ~40% of true winners that
# expired with no bid -> the original "8.3% WR in $0.50-$0.65" was wrong.
# Lowered to 0.55 on 2026-05-07 after backtest predicted +$0.17/trade EV at
# lower bands (calibration_curve.py + side_stability.py).
# REVERTED to 0.70 on 2026-05-08 after live shadow contradicted the backtest:
# n=34 trades since restart -> WR 53%, avg P&L -$0.33/trade.
# Slicing by entry_price bucket made the cause clear:
#   0.85+      n=21  WR 71%  avg -$0.20  (legacy regime)
#   0.70-0.85  n=10  WR 30%  avg -$0.50  (newly-enabled, lossy)
#   <0.70      n=3   WR  0%  avg -$0.67  (newly-enabled, lossy)
# Hypothesis: at the moment the bot first generates a signal that survives all
# other gates at a lower price, the market has already priced in the move and
# subsequently reverts. Backtest assumed an early-entry edge that does not
# exist in production. See chat transcript 2026-05-08 for full diagnosis.
MIN_ENTRY_PRICE = 0.70
# Side preference: None = both sides, False = UP-only, True = DOWN-only
PREFER_DOWN_SIDE = None  # None = trade both UP and DOWN since data is inconclusive
# Historical data: Waiting for clean token_id-based analysis to determine directional edge
# Quality score minimum: 1000+ chosen from 48h W/L analysis (2026-04-25..27).
# At qual>=1000 the 6 weakest trades (3 weakest winners + 1 loser) drop out;
# remaining 8 trades are 6W+2L = 75% WR. The 3 dropped winners all sat in qual<950.
MIN_QUALITY_SCORE = 1000
# Minimum signal age before a trade may execute. Same 48h analysis showed every
# winner had age >= 5.1 min; two losers had age 1.4 and 2.1 min. Fresh signals
# haven't had time to confirm direction.
MIN_SIGNAL_AGE_MIN = 5.0


# Post-loss cooldown: after a confirmed losing exit, skip entries in the next N windows (window size depends on market)
POST_LOSS_SKIP_WINDOWS = 1

def calculate_position_size(quality_score: float) -> float:
    """
    Calculate position size based on signal quality score.
    
    Tiered approach:
    - Standard: $5.00 (quality < 2500)
    - Strong: $7.50 (quality 2500-3500)
    - Exceptional: $10.00 (quality > 3500)
    
    Returns:
        Position size in USD
    """
    if quality_score >= 3500:
        return POSITION_SIZE_EXCEPTIONAL
    elif quality_score >= 2500:
        return POSITION_SIZE_STRONG
    else:
        return POSITION_SIZE_STANDARD


LOG_DIR = "logs"
EXECUTION_LOG_PATH = os.path.join(LOG_DIR, "execution_log.csv")
EXIT_LOG_PATH = os.path.join(LOG_DIR, "exit_log.csv")
RR_BLOCKS_LOG_PATH = os.path.join(LOG_DIR, "rr_blocks.csv")
RR_BLOCKS_FIELDS = (
    "ts_iso",
    "symbol",
    "side",
    "tier",
    "snapshot_price",
    "signal_rr",
    "req_rr",
    "stable",
    "clob_age_ms",
    "tracker_ask",
    "window_start_ts",
    "token_id",
    # Gate-history context (auto-filled by writer from self._recent_gate_results
    # and self._current_regime). Captures bot-internal state that cannot be
    # reconstructed later from clob_ticks.csv alone.
    "regime",
    "prev_regime",
    "pvr_block_ratio_20",
    "dominant_recent_gate",
    "recent_gate_diversity",
    # Book-depth context (auto-filled by writer from clob_book_tracker).
    # Required for fillable-EV / spread-aware analysis.
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "spread_bps",
    "top5_asks",
    "top5_bids",
)

# Unified decision log (all trades and skips)
DECISION_LOG_PATH = os.path.join(LOG_DIR, "decision_log.csv")
DECISION_LOG_FIELDS = [
    "ts_iso",
    "decision_type",  # TRADE or NO_TRADE
    "reason",
    "symbol",
    "side",
    "token_id",
    "contract_slug",
    "window_start_ts",
    "window_end_ts",
    "snapshot_price",
    "signal_rr",
    "signal_quality",
    "signal_priority",
    "execution_outcome",
    "order_id",
    "config_snapshot",
    "extra",
    # Auto-filled by writer.
    "regime",
    "prev_regime",
    "pvr_block_ratio_20",
    "dominant_recent_gate",
    "recent_gate_diversity",
    "best_ask",
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "spread_bps",
    "clob_age_ms",
    "top5_asks",
    "top5_bids",
]

# Phase 1 — Option B: unified gate-block CSV. One row per blocked entry, any
# gate, so we can `value_counts()` the `gate_name` column and rank which gate
# is the dominant filter. OBSERVER ONLY — never feeds any decision.
GATE_BLOCKS_LOG_PATH = os.path.join(LOG_DIR, "gate_blocks.csv")
GATE_BLOCKS_FIELDS = (
    "ts_iso",
    "symbol",
    "side",
    "gate_name",
    "snapshot_price",
    "signal_rr",
    "req_rr",
    "distance_z",
    "slope_z",
    "percent_move",
    "stability_ok",
    "tier",
    "window_start_ts",
    "token_id",
    "extra",
    # Gate-history context (auto-filled by writer from self._recent_gate_results
    # and self._current_regime). Captures bot-internal state that cannot be
    # reconstructed later from clob_ticks.csv alone.
    "regime",
    "prev_regime",
    "pvr_block_ratio_20",
    "dominant_recent_gate",
    "recent_gate_diversity",
    # Book-depth context (auto-filled by writer from clob_book_tracker).
    "best_ask",
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "spread_bps",
    "clob_age_ms",
    "top5_asks",
    "top5_bids",
)


class PolyouBot:


    def __init__(
        self,
        *,
        market_data: MarketData,
        read_only: bool = True,
        execution_client=None,
        clob_book_tracker=None,
    ):
        self.market_data = market_data
        self.read_only = read_only
        self.execution_client = execution_client
        self.clob_book_tracker = clob_book_tracker
        # --- Minimal state for copy trading and market management ---
        self._cooldown_until_window_ts: int = 0
        self._last_trade_meta: Dict[str, Dict[str, Any]] = {}
        logger.info(
            "PolyouBot initialized | Copy trading mode | read_only=%s",
            self.read_only,
        )


    # Legacy window cleanup and market iteration removed.


    # --- Legacy analytics removed: _get_price_window, _compute_vol, thresholds, etc. ---

    async def _fetch_clob_ask_price(self, token_id: str) -> float | None:
        if not token_id:
            logger.warning("CLOB Book Fetch Skipped: token_id is missing or None")
            return None
        
        for attempt in range(3):
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.get(
                        "https://clob.polymarket.com/book",
                        params={"token_id": token_id}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        asks = data.get("asks", [])
                        if asks:
                            best_ask = min(float(a["price"]) for a in asks if float(a["price"]) > 0)
                            return best_ask
                        else:
                            logger.debug(f"CLOB Book empty (no asks) | attempt={attempt+1} token_id={token_id}")
                    else:
                        logger.warning(f"CLOB Book status {resp.status_code} | attempt={attempt+1} token_id={token_id}")
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                logger.warning("CLOB Book Fetch attempt %d failed: %s", attempt + 1, str(e))
            await asyncio.sleep(0.5)
        
        logger.warning(f"CLOB Book Fetch completely failed after 3 attempts | token_id={token_id}")
        return None


    async def _fetch_clob_bid_price(self, token_id: str) -> float | None:
        """Fetch best bid price from CLOB order book using httpx."""
        if not token_id:
            logger.warning("CLOB Book Fetch Skipped: token_id is missing or None")
            return None
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    resp = await client.get(
                        "https://clob.polymarket.com/book",
                        params={"token_id": token_id}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        bids = data.get("bids", [])
                        if bids:
                            best_bid = max(float(b["price"]) for b in bids if float(b["price"]) > 0)
                            return best_bid
                        else:
                            logger.debug(f"CLOB Book empty (no bids) | attempt={attempt+1} token_id={token_id}")
                    else:
                        logger.warning(f"CLOB Book status {resp.status_code} | attempt={attempt+1} token_id={token_id}")
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                logger.warning("CLOB Book Fetch attempt %d failed: %s", attempt + 1, str(e))
            await asyncio.sleep(0.5)
        
        logger.warning(f"CLOB Book Fetch completely failed after 3 attempts | token_id={token_id}")
        return None


    def _compute_rr(self, price: float) -> float:
        if price is None or price <= 0 or price >= 1:
            return 0.0
        return (1 - price) / price

    def _log_execution_row(self, row: Dict[str, Any]) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_exists = os.path.isfile(EXECUTION_LOG_PATH)

        with open(EXECUTION_LOG_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

    def _log_exit_row(self, row: Dict[str, Any]) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_exists = os.path.isfile(EXIT_LOG_PATH)
        with open(EXIT_LOG_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

    def _book_context(self, token_id: Any) -> Dict[str, Any]:
        """Snapshot best bid/ask + sizes + spread_bps + clob_age_ms for token_id.

        Pure observability. Defensive: any failure returns empty strings so
        log writes are never broken.
        """
        empty = {
            "best_ask": "",
            "best_bid": "",
            "best_ask_size": "",
            "best_bid_size": "",
            "spread_bps": "",
            "clob_age_ms": "",
            "top5_asks": "",
            "top5_bids": "",
        }
        try:
            if not token_id or self.clob_book_tracker is None:
                return empty
            tok = str(token_id)
            snap = self.clob_book_tracker.get_book(tok)
            age_ms = self.clob_book_tracker.get_age_ms(tok)
            if snap is None:
                return {**empty, "clob_age_ms": age_ms if age_ms is not None else ""}
            ba = snap.best_ask
            bb = snap.best_bid
            spread_bps = ""
            if ba is not None and bb is not None and ba > 0:
                mid = (ba + bb) / 2.0
                if mid > 0:
                    spread_bps = f"{((ba - bb) / mid) * 10000.0:.2f}"
            return {
                "best_ask": f"{ba:.4f}" if ba is not None else "",
                "best_bid": f"{bb:.4f}" if bb is not None else "",
                "best_ask_size": f"{snap.best_ask_size:.2f}" if snap.best_ask_size is not None else "",
                "best_bid_size": f"{snap.best_bid_size:.2f}" if snap.best_bid_size is not None else "",
                "spread_bps": spread_bps,
                "clob_age_ms": age_ms if age_ms is not None else "",
                "top5_asks": json.dumps(snap.top_asks) if getattr(snap, "top_asks", None) else "",
                "top5_bids": json.dumps(snap.top_bids) if getattr(snap, "top_bids", None) else "",
            }
        except Exception:
            return empty

    def _gate_history_context(self) -> Dict[str, Any]:
        """Snapshot of bot-internal gate-history state at write time.

        Defensive: any failure returns empty strings rather than raising, so
        block-row writes are never broken by enrichment errors.
        """
        try:
            recent = list(self._recent_gate_results)
            n = len(recent)
            if n == 0:
                return {
                    "regime": getattr(self, "_current_regime", "") or "",
                    "prev_regime": getattr(self, "_last_regime", "") or "",
                    "pvr_block_ratio_20": "",
                    "dominant_recent_gate": "",
                    "recent_gate_diversity": 0,
                }
            counts: Dict[str, int] = {}
            for g in recent:
                counts[g] = counts.get(g, 0) + 1
            pvr_blocks = counts.get("pvr_limit", 0)
            dominant = max(counts.items(), key=lambda kv: kv[1])[0]
            return {
                "regime": getattr(self, "_current_regime", "") or "",
                "prev_regime": getattr(self, "_last_regime", "") or "",
                "pvr_block_ratio_20": f"{pvr_blocks / n:.3f}",
                "dominant_recent_gate": dominant,
                "recent_gate_diversity": len(counts),
            }
        except Exception:
            return {
                "regime": "",
                "prev_regime": "",
                "pvr_block_ratio_20": "",
                "dominant_recent_gate": "",
                "recent_gate_diversity": "",
            }

    def _log_rr_block_row(self, row: Dict[str, Any]) -> None:
        try:
            book = self._book_context(row.get("token_id"))
            # Don't overwrite explicit clob_age_ms / tracker_ask already on the row.
            book.pop("best_ask", None)
            if row.get("clob_age_ms") not in (None, ""):
                book.pop("clob_age_ms", None)
            row = {**row, **self._gate_history_context(), **book}
            os.makedirs(LOG_DIR, exist_ok=True)
            new_file = not os.path.isfile(RR_BLOCKS_LOG_PATH)
            with open(RR_BLOCKS_LOG_PATH, mode="a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=RR_BLOCKS_FIELDS)
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            logger.exception("rr_blocks.csv write failed")

    def _log_gate_block_row(self, row: Dict[str, Any]) -> None:
        try:
            row = {**row, **self._gate_history_context(), **self._book_context(row.get("token_id"))}
            os.makedirs(LOG_DIR, exist_ok=True)
            new_file = not os.path.isfile(GATE_BLOCKS_LOG_PATH)
            with open(GATE_BLOCKS_LOG_PATH, mode="a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=GATE_BLOCKS_FIELDS)
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            logger.exception("gate_blocks.csv write failed")

    def _log_decision_row(self, row: Dict[str, Any]) -> None:
        try:
            row = {**row, **self._gate_history_context(), **self._book_context(row.get("token_id"))}
            os.makedirs(LOG_DIR, exist_ok=True)
            file_exists = os.path.isfile(DECISION_LOG_PATH)
            with open(DECISION_LOG_PATH, mode="a", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=DECISION_LOG_FIELDS,
                    extrasaction="ignore",
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            logger.exception("decision_log.csv write failed")

    def _get_config_snapshot(self) -> dict:
        # Minimal config snapshot for reproducibility
        return {
            "SAFE_MARKETS": list(SAFE_MARKETS),
            "MIN_DISTANCE_Z": MIN_DISTANCE_Z,
            "MIN_PERCENT_MOVE": MIN_PERCENT_MOVE,
            "MIN_ENTRY_PRICE": MIN_ENTRY_PRICE,
            "MAX_SNAPSHOT_PRICE": 0.70,
            "MIN_QUALITY_SCORE": MIN_QUALITY_SCORE,
            "MIN_SIGNAL_AGE_MIN": MIN_SIGNAL_AGE_MIN,
            "RR_MIN": RR_MIN,
        }

    def _record_gate_block(
        self,
        gate_name: str,
        *,
        symbol: str,
        side: str,
        snapshot_price: float | None = None,
        signal_rr: float | None = None,
        req_rr: float | None = None,
        distance_z: float | None = None,
        slope_z: float | None = None,
        percent_move: float | None = None,
        stability_ok: bool | None = None,
        tier: str = "",
        window_start_ts: int | None = None,
        token_id: str = "",
        extra: Dict[str, Any] | None = None,
    ) -> None:
        """Append a unified gate-block row. Observer only; swallows all errors."""
        try:
            row = {
                "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "symbol": symbol,
                "side": side,
                "gate_name": gate_name,
                "snapshot_price": f"{snapshot_price:.4f}" if snapshot_price is not None else "",
                "signal_rr": f"{signal_rr:.4f}" if signal_rr is not None else "",
                "req_rr": f"{req_rr:.4f}" if req_rr is not None else "",
                "distance_z": f"{distance_z:.3f}" if distance_z is not None else "",
                "slope_z": f"{slope_z:.3f}" if slope_z is not None else "",
                "percent_move": f"{percent_move:.5f}" if percent_move is not None else "",
                "stability_ok": "" if stability_ok is None else bool(stability_ok),
                "tier": tier,
                "window_start_ts": window_start_ts if window_start_ts is not None else "",
                "token_id": token_id,
                "extra": json.dumps(extra, default=str) if extra else "",
            }
            self._log_gate_block_row(row)
        except Exception:
            logger.exception("_record_gate_block failed")

    def _compute_structure_metrics(self, prices):
        raw_vol = self._compute_vol(prices)
        vol = max(raw_vol, ABSOLUTE_MIN_FLOOR)

        slope = (
            math.log(prices[-1]) - math.log(prices[0])
        ) / (STRUCTURE_WINDOW_SECONDS / 86400)

        slope_z = slope / vol

        return slope_z, vol

    def _compute_decision_metrics(
        self,
        *,
        anchor_price: float,
        decision_prices,
        structure_vol,
        window_seconds: int,
    ) -> Dict[str, Any]:

        mean_price = sum(decision_prices) / len(decision_prices)
        raw_vol = self._compute_vol(decision_prices)

        adaptive_floor = max(
            ABSOLUTE_MIN_FLOOR,
            structure_vol * STRUCTURE_VOL_RATIO,
        )

        vol = max(raw_vol, adaptive_floor)

        distance_z = abs(math.log(decision_prices[-1]) - math.log(anchor_price)) / vol
        percent_move = abs(decision_prices[-1] / anchor_price - 1.0)
        edge_z = (math.log(decision_prices[-1]) - math.log(mean_price)) / vol

        slope = (
            math.log(decision_prices[-1]) - math.log(decision_prices[0])
        ) / (window_seconds / 86400)

        slope_z = slope / vol

        return {
            "price": decision_prices[-1],
            "mean": mean_price,
            "raw_vol": raw_vol,
            "adaptive_floor": adaptive_floor,
            "volatility": vol,
            "edge_z": edge_z,
            "slope_z": slope_z,
            "distance_z": distance_z,
            "percent_move": percent_move,
        }

    def _compute_signal_strength(self, distance_z, slope_z):
        speed = abs(slope_z) ** 0.75
        structure = distance_z ** 0.85
        base = speed * structure
        return base

    def _get_price_window_since(self, symbol: str, start_ts: int):
        replay = self.market_data.get_replay(symbol)

        prices = [
            ev.price
            for ev in replay
            if isinstance(ev, SpotPriceEvent)
            and ev.ts >= start_ts
        ]

        if len(prices) < 4:  # Decoupled from the 24-point structure window
            return None

        return prices

    def _compute_phase_and_gates(
        self,
        symbol: str,
        anchor_price: float,
        decision_prices,
        structure_prices,
    ):
        slope_z_24h, structure_vol = self._compute_structure_metrics(structure_prices)

        m = self._compute_decision_metrics(
            anchor_price=anchor_price,
            decision_prices=decision_prices,
            structure_vol=structure_vol,
            window_seconds=DECISION_WINDOW_SECONDS,
        )

        window_return = math.log(decision_prices[-1]) - math.log(decision_prices[0])

        vol_scaled_percent = PERCENT_VOL_MULTIPLIER[symbol] * m["volatility"]
        dynamic_percent = max(MIN_PERCENT_MOVE[symbol], vol_scaled_percent)

        slope_ok = abs(m["slope_z"]) >= MIN_TREND_Z
        acceleration_ok = abs(m["slope_z"]) >= ACCELERATION_FLOOR[symbol]
        percent_ok = m["percent_move"] >= dynamic_percent
        distance_ok = m["distance_z"] >= MIN_DISTANCE_Z[symbol]

        vol_ratio = m["raw_vol"] / structure_vol if structure_vol > 0 else 0.0
        percent_vol_ratio = (
            m["percent_move"] / m["raw_vol"]
            if m["raw_vol"] > 0 else 0.0
        )

        pvr_terminal = percent_vol_ratio >= PVR_TERMINAL_CAP
        pvr_ideal = PVR_IDEAL_MIN <= percent_vol_ratio <= PVR_IDEAL_MAX

        exhaustion_ok = (
            vol_ratio <= VOL_RATIO_CAP and
            percent_vol_ratio <= PERCENT_VOL_RATIO_CAP
        )

        extension_pressure = (
            m["distance_z"] / abs(m["slope_z"])
            if abs(m["slope_z"]) > 0 else float("inf")
        )

        adaptive_drift_cap = BASE_DRIFT_CAP * (
            1 + DRIFT_TREND_SENSITIVITY * abs(slope_z_24h)
        )

        drift_ok = extension_pressure <= adaptive_drift_cap

        continuation_override = (
            abs(slope_z_24h) >= OVERRIDE_STRUCTURE_Z
            and abs(m["slope_z"]) >= 2.0 * MIN_TREND_Z
            and m["percent_move"] >= dynamic_percent * OVERRIDE_PERCENT_MULTIPLIER
            and percent_vol_ratio < 21.5
        )

        side = None
        if decision_prices[-1] > anchor_price:
            side = "UP"
        elif decision_prices[-1] < anchor_price:
            side = "DOWN"

        candle_ok = True
        if side == "UP" and window_return <= 0:
            candle_ok = False
        if side == "DOWN" and window_return >= 0:
            candle_ok = False

        structure_alignment_ok = True
        if side == "UP" and slope_z_24h <= 0:
            structure_alignment_ok = False
        if side == "DOWN" and slope_z_24h >= 0:
            structure_alignment_ok = False

        gates = {
            "slope_ok": slope_ok,
            "acceleration_ok": acceleration_ok,
            "percent_ok": percent_ok,
            "distance_ok": distance_ok,
            "exhaustion_ok": exhaustion_ok,
            "drift_ok": drift_ok,
            "candle_ok": candle_ok,
            "structure_alignment_ok": structure_alignment_ok,
            "continuation_override": continuation_override,
            "pvr_terminal_block": pvr_terminal,
            "direction_ok": side is not None,
            "stability_ok": True,  # Will be updated downstream in run_once
        }

        phase = {
            "slope_z_24h": slope_z_24h,
            "structure_vol": structure_vol,
            "dynamic_percent_threshold": dynamic_percent,
            "vol_ratio": vol_ratio,
            "percent_vol_ratio": percent_vol_ratio,
            "extension_pressure": extension_pressure,
            "adaptive_drift_cap": adaptive_drift_cap,
            "drift_ok": drift_ok,
            "exhaustion_ok": exhaustion_ok,
            "continuation_override": continuation_override,
            "acceleration_ok": acceleration_ok,
            "pvr_ideal": pvr_ideal,
            "pvr_terminal": pvr_terminal,
            "pvr_terminal_cap": PVR_TERMINAL_CAP,
        }

        return m, phase, gates, side


    async def _run_once_for_symbol(self, symbol: str) -> None:

        now_ts = time.time()
        
        # Periodic memory cleanup (every 100 calls)
        self._cleanup_counter += 1
        if self._cleanup_counter >= 100:
            self._cleanup_old_windows()
            self._cleanup_counter = 0

        contract = await resolve_crypto_contract(
            symbol=SYMBOL_MAP[symbol],
            now_ts=now_ts,
        )
        if not contract:
            return

        window_start_ts = int(contract.get("window_start_ts", 0))
        window_end_ts = int(contract.get("window_end_ts", 0))
        contract_slug = contract.get('slug', '')
        
        if not window_start_ts or not window_end_ts or not contract_slug:
            logger.warning("Invalid contract data | symbol=%s", symbol)
            return

        if self._window_signaled.get(window_end_ts):
            return

        store = self._window_signals.setdefault(window_end_ts, {})

        if window_end_ts not in self._symbols_traded_this_window:
            self._symbols_traded_this_window[window_end_ts] = set()

        anchor_price = self.market_data.get_anchor(
            symbol=symbol,
            window_start_ts=window_start_ts,
        )

        if anchor_price is None:
            store[symbol] = None
            return

        scan_start = window_start_ts + SCAN_START_OFFSET_SECONDS
        scan_end = window_end_ts - SCAN_END_OFFSET_SECONDS

        if now_ts < scan_start or now_ts > scan_end:
            store[symbol] = None
            return

        decision_prices = self._get_price_window_since(symbol, window_start_ts)
        structure_prices = self._get_price_window(symbol, STRUCTURE_WINDOW_SECONDS)

        if not decision_prices or not structure_prices:
            store[symbol] = None
            return

        m, phase, gates, side = self._compute_phase_and_gates(
            symbol,
            anchor_price,
            decision_prices,
            structure_prices,
        )

        if side is None:
            store[symbol] = None
            return

        if symbol in self._symbols_traded_this_window[window_end_ts]:
            # One trade per directional window per symbol
            store[symbol] = None
            return

        vol_ratio = phase["vol_ratio"]
        base_threshold = 0.95 if symbol in MAJOR_ASSETS else 1.0
        factor = EARLY_EXPANSION_FACTOR[symbol]
        effective_threshold = base_threshold * factor

        expansion_penalty = 1.0
        if vol_ratio <= effective_threshold:
            expansion_penalty = 0.75
            logger.debug(
                "Expansion weak | symbol=%s vol_ratio=%.3f threshold=%.3f",
                symbol,
                vol_ratio,
                effective_threshold,
            )

        strong_impulse = (
            gates["acceleration_ok"]
            and gates["structure_alignment_ok"]
            and gates["drift_ok"]
            and gates["exhaustion_ok"]
        )

        early_trend_build = (
            abs(m["slope_z"]) >= 6.0
            and m["distance_z"] >= 5.0
            and 5.5 <= phase["percent_vol_ratio"] <= 13.0
        )

        high_accel_early = (
            abs(m["slope_z"]) >= 22.0
            and m["distance_z"] >= 7.0
            and phase["percent_vol_ratio"] < 15.0
        )

        early_expansion = (
            9.0 <= phase["percent_vol_ratio"] <= 14.0
            and abs(m["slope_z"]) >= 10.0
            and m["distance_z"] >= 2.0
        )

        early_momentum = (
            abs(m["slope_z"]) >= 18.0
            and m["distance_z"] >= 4.0
            and phase["percent_vol_ratio"] >= 7.0
        )

        nascent_breakout = (
            abs(m["slope_z"]) >= 4.0
            and m["distance_z"] >= 1.2
            and abs(m["percent_move"]) >= 0.0003
        )

        flash_breakout = (
            abs(m["slope_z"]) >= 3.0
            and abs(m["percent_move"]) >= 0.0003
        )

        core_signal = (
            abs(m["slope_z"]) >= 10
            and m["distance_z"] >= 3
            and 8.0 <= phase["percent_vol_ratio"] <= 23
        )

        pvr = phase["percent_vol_ratio"]
        if not (8.0 <= pvr < 22 or (22 <= pvr < 24 and m["distance_z"] >= 20)):
            self._recent_gate_results.append("pvr_limit")

        any_valid_signal = core_signal or high_accel_early or early_momentum or early_expansion or early_trend_build or nascent_breakout or flash_breakout
        if not any_valid_signal:
            store[symbol] = None
            return

        # Lowered to 0.03% to beat the Polymarket 99c market makers!
        if abs(m["percent_move"]) < 0.0003:
            store[symbol] = None
            return

        failed_gates = []

        if not gates["acceleration_ok"] and not gates["continuation_override"]:
            failed_gates.append("acceleration_or_override")

        if not gates["distance_ok"]:
            failed_gates.append("distance_ok")

        if not gates["structure_alignment_ok"]:
            failed_gates.append("structure_alignment_ok")

        if not gates["drift_ok"]:
            failed_gates.append("drift_ok")

        if not gates["exhaustion_ok"]:
            failed_gates.append("exhaustion_ok")

        if not gates["candle_ok"]:
            failed_gates.append("candle_ok")

        for gate_name in failed_gates:
            self._recent_gate_results.append(gate_name)

        if len(self._recent_gate_results) >= 20:
            pvr_blocks = sum(1 for g in self._recent_gate_results if g == "pvr_limit")
            ratio = pvr_blocks / len(self._recent_gate_results)

            if ratio > 0.7:
                regime = "COMPRESSION"
            elif ratio > 0.4:
                regime = "MIXED"
            else:
                regime = "EXPANSION"

            self._last_regime = self._current_regime
            self._current_regime = regime

            logger.info(
                "Regime | type=%s pvr_ratio=%.2f sample=%d",
                regime,
                ratio,
                len(self._recent_gate_results),
            )

            if self._last_regime == "COMPRESSION" and self._current_regime == "EXPANSION":
                logger.info(
                    "Regime Transition | COMPRESSION → EXPANSION | pvr_ratio=%.2f",
                    ratio,
                )

        # Safe token_id extraction for CLOB price check
        try:
            token_id = contract["yes_token_id"] if side == "UP" else contract["no_token_id"]
            if not token_id:
                logger.warning("Empty token_id for %s %s, cannot fetch CLOB price", symbol, side)
                store[symbol] = None
                return
        except KeyError as e:
            logger.error("Missing token_id key in contract | symbol=%s side=%s error=%s", symbol, side, e)
            store[symbol] = None
            return
        
        clob_ask = await self._fetch_clob_ask_price(token_id)
        
        if clob_ask is None:
            # Fallback: The book is completely empty. We cannot safely trade.
            logger.warning("CLOB completely empty for %s, cannot calculate entry.", symbol)
            store[symbol] = None
            return

        logger.debug("Polymarket Top-of-Book Ask | symbol=%s side=%s price=%.3f", symbol, side, clob_ask)

        # Add 2 cents of slippage to cross the spread on fast breakouts
        snapshot_price = min(0.99, clob_ask + 0.02)

        signal_rr = self._compute_rr(snapshot_price)

        stability_ok = self.market_data.is_stable(
            symbol,
            side=side,
            since_ts=window_start_ts,
        )

        # Dynamic R:R based on signal strength
        vip_pass = strong_impulse and (high_accel_early or early_momentum) and stability_ok
        standard_pass = (strong_impulse or core_signal) and (stability_ok or not vip_pass) 
        
        # If the market is violently unstable, instantly drop it to STRICT tier
        if not stability_ok:
            vip_pass = False
            standard_pass = False

        # Single R:R threshold (retired tier system 2026-04-30).
        # 2026-05-04: relaxed from 0.275 -> 0.0 for shadow-trade data collection.
        # Selectivity sweep (logs/rr_blocks_resolved.csv, 532 deduped trades over
        # 4 days) showed signal_rr is anti-predictive across all symbols:
        # tighter rr -> lower WR and worse EV. Original 0.275 was based on
        # pre-rotation data where enriched columns were silently corrupted.
        # READ_ONLY_MODE remains true; this only affects ShadowPositionBook.
        rr_min = 0.0
        if signal_rr < rr_min:
            tracker_age_ms = None
            tracker_ask = None
            if self.clob_book_tracker is not None:
                try:
                    tracker_age_ms = self.clob_book_tracker.get_age_ms(token_id)
                    tracker_snap = self.clob_book_tracker.get_book(token_id)
                    if tracker_snap is not None:
                        tracker_ask = tracker_snap.best_ask
                except Exception:
                    pass
            logger.info(
                "R:R blocked | symbol=%s price=%.2f rr=%.3f req=%.3f (stable=%s) clob_age_ms=%s tracker_ask=%s",
                symbol, snapshot_price, signal_rr, rr_min, stability_ok,
                tracker_age_ms if tracker_age_ms is not None else "n/a",
                f"{tracker_ask:.3f}" if tracker_ask is not None else "n/a",
            )
            self._log_rr_block_row({
                "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "symbol": symbol,
                "side": side,
                "tier": "SINGLE",  # For legacy log compatibility
                "snapshot_price": f"{snapshot_price:.4f}",
                "signal_rr": f"{signal_rr:.4f}",
                "req_rr": f"{rr_min:.4f}",
                "stable": stability_ok,
                "clob_age_ms": tracker_age_ms if tracker_age_ms is not None else "",
                "tracker_ask": f"{tracker_ask:.4f}" if tracker_ask is not None else "",
                "window_start_ts": window_start_ts,
                "token_id": token_id,
            })
            self._record_gate_block(
                "rr_single_threshold",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                req_rr=rr_min,
                distance_z=m.get("distance_z"),
                slope_z=m.get("slope_z"),
                percent_move=m.get("percent_move"),
                stability_ok=stability_ok,
                tier="SINGLE",
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "clob_age_ms": tracker_age_ms,
                    "tracker_ask": tracker_ask,
                },
            )
            store[symbol] = None
            return

        gates["stability_ok"] = stability_ok

        impulse_strength = self._compute_signal_strength(
            m["distance_z"],
            m["slope_z"],
        )

        modifier = expansion_penalty
        if strong_impulse:
            modifier *= 1.2
        if high_accel_early:
            modifier *= 1.15
        if early_trend_build:
            modifier *= 1.1
        if early_expansion:
            modifier *= 1.1

        # ---------------------------------------------------------
        # HARD STOPS - Do not trade if these core gates are failed
        # IMPORTANT: Only check on FIRST confirmation loop to prevent
        # re-check failures during confirmation period
        # ---------------------------------------------------------
        confirm_key = (symbol, contract_slug)
        current_confirmation_count = self._signal_confirmations.get(confirm_key, 0)
        
        # Only apply hard gates on first loop (before confirmation tracking starts)
        if current_confirmation_count == 0:
            if not gates["percent_ok"]:
                logger.info(
                    "Blocked: Failed percent_ok hard gate | symbol=%s side=%s "
                    "percent_move=%.6g dynamic_percent=%.6g ratio=%.3f",
                    symbol, side,
                    m.get("percent_move", float("nan")),
                    phase.get("dynamic_percent_threshold", float("nan")),
                    (m.get("percent_move", 0.0) / phase.get("dynamic_percent_threshold", 1.0))
                    if phase.get("dynamic_percent_threshold") else float("nan"),
                )
                self._record_gate_block(
                    "percent_ok",
                    symbol=symbol,
                    side=side,
                    snapshot_price=snapshot_price,
                    signal_rr=signal_rr,
                    distance_z=m.get("distance_z"),
                    slope_z=m.get("slope_z"),
                    percent_move=m.get("percent_move"),
                    stability_ok=stability_ok,
                    tier="SINGLE",
                    window_start_ts=window_start_ts,
                    token_id=token_id,
                )
                store[symbol] = None
                return

            if not gates["exhaustion_ok"]:
                logger.info(
                    "Blocked: Failed exhaustion_ok hard gate | symbol=%s side=%s "
                    "raw_vol=%.6g percent_move=%.6g vol_ratio=%.3f percent_vol_ratio=%.3f "
                    "vrcap=%.2f pvrcap=%.2f",
                    symbol, side,
                    m.get("raw_vol", float("nan")),
                    m.get("percent_move", float("nan")),
                    phase.get("vol_ratio", float("nan")),
                    phase.get("percent_vol_ratio", float("nan")),
                    VOL_RATIO_CAP,
                    PERCENT_VOL_RATIO_CAP,
                )
                self._record_gate_block(
                    "exhaustion_ok",
                    symbol=symbol,
                    side=side,
                    snapshot_price=snapshot_price,
                    signal_rr=signal_rr,
                    distance_z=m.get("distance_z"),
                    slope_z=m.get("slope_z"),
                    percent_move=m.get("percent_move"),
                    stability_ok=stability_ok,
                    tier="SINGLE",
                    window_start_ts=window_start_ts,
                    token_id=token_id,
                )
                store[symbol] = None
                return
        else:
            # During confirmation: signal already passed gates, don't re-check
            logger.debug("Confirmation loop %d: skipping hard gate re-check | symbol=%s", current_confirmation_count + 1, symbol)

        if not gates["structure_alignment_ok"]:
            modifier *= 0.7
        if not gates["drift_ok"]:
            modifier *= 0.9

        if not stability_ok:
            modifier *= 0.70
            logger.info(
                "Stability soft penalty | symbol=%s side=%s",
                symbol,
                side,
            )

        signal_quality = impulse_strength * modifier
        
        # Race condition guard: Check if window already traded before polluting state
        if self._window_signaled.get(window_end_ts):
            logger.info("Race condition avoided | window already signaled | symbol=%s", symbol)
            store[symbol] = None
            return

        signal_phase = (now_ts - window_start_ts) / (window_end_ts - window_start_ts)

        # DATA-DRIVEN FILTERS (from 316-trade winner/loser analysis)
        
        # Filter 1: Entry price - REQUIRE >= $0.65 (80% WR vs 7.5% in $0.50-$0.65 death zone)
        if snapshot_price < MIN_ENTRY_PRICE:
            logger.info("Blocked: Entry price too low | symbol=%s side=%s price=%.2f (min=%.2f) | Data shows %.1f%% WR below threshold", 
                       symbol, side, snapshot_price, MIN_ENTRY_PRICE, 7.5)
            self._record_gate_block(
                "entry_price_too_low",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                distance_z=m.get("distance_z"),
                slope_z=m.get("slope_z"),
                percent_move=m.get("percent_move"),
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={"min_entry_price": MIN_ENTRY_PRICE},
            )
            store[symbol] = None
            return

        # Filter 1b: Entry price ceiling.
        # 2026-05-04: raised from 0.70 -> 0.95 for shadow-trade data collection.
        # Selectivity sweep showed BTC price <= 0.95 is the only positive-EV
        # slice (n=168, WR 82.1%, mean EV/$ +$0.0042 over 4 days).
        # READ_ONLY_MODE remains true — the 0.70 execution cap is moot for
        # shadow trades. Re-tighten to 0.70 BEFORE re-enabling live execution.
        MAX_SNAPSHOT_PRICE = 0.95
        if snapshot_price > MAX_SNAPSHOT_PRICE:
            logger.info(
                "Blocked: Entry price above execution cap | symbol=%s side=%s snapshot=%.2f clob_ask=%.2f (max_snapshot=%.2f, exec_cap=0.70)",
                symbol, side, snapshot_price, clob_ask, MAX_SNAPSHOT_PRICE,
            )
            self._record_gate_block(
                "entry_price_above_cap",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "clob_ask": clob_ask,
                    "max_snapshot": MAX_SNAPSHOT_PRICE,
                    "exec_cap": 0.70,
                },
            )
            store[symbol] = None
            return

        # Filter 2: Side preference (only active if PREFER_DOWN_SIDE is not None)
        if PREFER_DOWN_SIDE is not None:
            if not PREFER_DOWN_SIDE and side == "DOWN":
                logger.info("Blocked: DOWN side (UP-only mode) | symbol=%s side=%s", 
                           symbol, side)
                self._record_gate_block(
                    "side_preference_up_only",
                    symbol=symbol,
                    side=side,
                    snapshot_price=snapshot_price,
                    window_start_ts=window_start_ts,
                    token_id=token_id,
                )
                store[symbol] = None
                return
            elif PREFER_DOWN_SIDE and side == "UP":
                logger.info("Blocked: UP side (DOWN-only mode) | symbol=%s side=%s", 
                           symbol, side)
                self._record_gate_block(
                    "side_preference_down_only",
                    symbol=symbol,
                    side=side,
                    snapshot_price=snapshot_price,
                    window_start_ts=window_start_ts,
                    token_id=token_id,
                )
                store[symbol] = None
                return

        # Prevent paying high premiums for tiny absolute moves early in the window
        # The dynamic R:R tiers above will already handle absolute caps between 85c - 90c depending on signal strength + trend direction
        premium_cap_trap = (
            (snapshot_price > 0.54 and signal_phase < 0.50 and m["percent_move"] < 0.0018)
        )

        if premium_cap_trap:
            logger.info("Blocked expensive premium (bad Risk:Reward) | symbol=%s price=%.2f move_pct=%.5f phase=%.2f", symbol, snapshot_price, m["percent_move"], signal_phase)
            self._record_gate_block(
                "premium_cap_trap",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                distance_z=m.get("distance_z"),
                slope_z=m.get("slope_z"),
                percent_move=m.get("percent_move"),
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={"signal_phase": signal_phase},
            )
            store[symbol] = None
            return

        late_extension = (
            signal_phase >= 0.40
            and m["distance_z"] >= 8.5
        )

        if late_extension:
            # Reverted 2026-04-30 to soft penalty: blocking-winners analysis
            # over last 38 settled trades showed hard block would forgo 13
            # winners to avoid 7 losses (net only +$0.89/share). Price gate
            # (MAX_SNAPSHOT_PRICE 0.70) catches 6/9 SETTLED_ZERO losers with
            # better PnL trade-off (+$3.00/share), so let this stay soft.
            logger.info(
                "Late extension penalty | symbol=%s phase=%.2f distance_z=%.2f",
                symbol,
                signal_phase,
                m["distance_z"],
            )
            signal_quality *= 0.65

        if pvr < 8.0:
            probability_factor = 0.6
        elif 8.0 <= pvr < 12:
            probability_factor = 0.9
        elif 12 <= pvr <= 16:
            probability_factor = 1.2
        elif 16 < pvr <= 22:
            probability_factor = 1.0
        else:
            probability_factor = 0.7

        ev_component = (probability_factor * (signal_rr + 1)) - 1
        ev_component = max(0.1, ev_component + 1)

        time_weight = max(0.5, 1.2 - signal_phase)

        signal_priority = signal_quality * ev_component * time_weight

        # Signal age gate: 48h W/L analysis showed every winner had age >= 5.1 min;
        # losers at age 1.4 and 2.1 min. Block until the signal matures.
        signal_age_minutes = (now_ts - window_start_ts) / 60
        if signal_age_minutes < MIN_SIGNAL_AGE_MIN:
            logger.info("Blocked: Signal too fresh | symbol=%s side=%s age=%.2fmin (min=%.1f)",
                       symbol, side, signal_age_minutes, MIN_SIGNAL_AGE_MIN)
            self._record_gate_block(
                "signal_too_fresh",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                distance_z=m.get("distance_z"),
                slope_z=m.get("slope_z"),
                percent_move=m.get("percent_move"),
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "age_min": signal_age_minutes,
                    "min_age_min": MIN_SIGNAL_AGE_MIN,
                },
            )
            store[symbol] = None
            return

        # Quality filter: Require signal_quality >= 1000 (48h W/L analysis 2026-04-27)
        # At this threshold: 3 weakest winners + 1 loser drop; remaining 8 trades = 75% WR.
        if signal_quality < MIN_QUALITY_SCORE:
            logger.info("Blocked: Signal quality too low | symbol=%s side=%s quality=%.1f (min=%d)", 
                       symbol, side, signal_quality, MIN_QUALITY_SCORE)
            self._record_gate_block(
                "signal_quality_too_low",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                distance_z=m.get("distance_z"),
                slope_z=m.get("slope_z"),
                percent_move=m.get("percent_move"),
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "signal_quality": signal_quality,
                    "min_quality": MIN_QUALITY_SCORE,
                },
            )
            store[symbol] = None
            return

        # Post-loss cooldown gate: block any entry in a window <= cooldown horizon.
        if window_end_ts <= self._cooldown_until_window_ts:
            logger.info(
                "Blocked: Post-loss cooldown | symbol=%s side=%s window_end=%d cooldown_until=%d",
                symbol, side, window_end_ts, self._cooldown_until_window_ts,
            )
            try:
                aux_logs.log_cooldown_event(
                    event="OBSERVED_BLOCK",
                    reason="entry_blocked",
                    cooldown_until_window_ts=int(self._cooldown_until_window_ts),
                    current_window_end_ts=int(window_end_ts),
                )
            except Exception:
                pass
            self._record_gate_block(
                "post_loss_cooldown",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "window_end_ts": window_end_ts,
                    "cooldown_until_window_ts": self._cooldown_until_window_ts,
                },
            )
            store[symbol] = None
            return

        # Note: confirm_key already defined above for hard gate check
        count = current_confirmation_count + 1
        self._signal_confirmations[confirm_key] = count
        try:
            aux_logs.log_confirmation_event(
                event="INCREMENT",
                symbol=symbol,
                side=side,
                count=count,
                required=CONFIRMATION_LOOPS_REQUIRED,
                trigger="signal_repeat",
            )
        except Exception:
            pass

        strong_signal = strong_impulse or high_accel_early or early_momentum
        semi_strong_signal = early_trend_build
        
        # If the move is somewhat small, demand full confirmation regardless of 'strong_signal'
        if m["percent_move"] < MIN_PERCENT_MOVE.get(symbol, 0.0010) * 1.5:
            required_confirmations = CONFIRMATION_LOOPS_REQUIRED
        else:
            required_confirmations = 2 if (strong_signal or semi_strong_signal) else CONFIRMATION_LOOPS_REQUIRED

        if count < required_confirmations:
            store[symbol] = None
            return

        if symbol not in MAJOR_ASSETS:
            for s in self._candidate_signals.values():
                if (
                    s["symbol"] in MAJOR_ASSETS
                    and signal_priority < s["strength"] * ALT_REPLACEMENT_STRENGTH
                ):
                    store[symbol] = None
                    return

        if self._candidate_signals:
            existing_window = next(iter(self._candidate_signals.values()))["window_end_ts"]
            if window_end_ts != existing_window:
                self._candidate_signals.clear()
                self._signal_confirmations.clear()
                self._comparison_start_ts = None
                self._current_best_signal = None

        if self._current_best_signal:
            if signal_quality <= self._current_best_signal["quality"]:
                store[symbol] = None
                return

        self._candidate_signals[symbol] = {
            "symbol": symbol,
            "side": side,
            "strength": signal_priority,
            "quality": signal_quality,
            "metrics": m,
            "context": {
                "anchor_price": anchor_price,
                "snapshot_price": snapshot_price,
                "signal_rr": signal_rr,
                "signal_age_minutes": (now_ts - window_start_ts) / 60,
                "signal_phase": signal_phase,
            },
            "phase": phase,
            "gates": {
                **gates,
                "stability_ok": stability_ok,
            },
            "contract": contract,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "contract_slug": contract_slug,
            "ts": now_ts,
        }

        self._current_best_signal = self._candidate_signals[symbol]

        if self._comparison_start_ts is None:
            self._comparison_start_ts = now_ts

        # Comparison logic: For single-symbol strategy, this is effectively bypassed
        # since len(self._candidate_signals) is always 1 (ETHUSD only)
        if (
            (now_ts - self._comparison_start_ts) < SIGNAL_COMPARISON_SECONDS
            and len(self._candidate_signals) < 2
        ):
            # This branch always executes for single-symbol strategy
            pass

        store[symbol] = self._candidate_signals.get(symbol)

        if len(store) < len(SAFE_MARKETS):
            logger.info(
                "STORE INCOMPLETE | proceeding anyway | %d/%d symbols",
                len(store),
                len(SAFE_MARKETS),
            )

        if self._window_signaled.get(window_end_ts):
            return

        candidates = [s for s in store.values() if s is not None]

        MIN_ACTIVE_CANDIDATES = 1

        if len(candidates) < MIN_ACTIVE_CANDIDATES:


            decision_ts = time.time()
            leader = max(candidates, key=lambda x: x["quality"]) if candidates else None
            # Log NO_TRADE decision
            self._log_decision_row({
                "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "decision_type": "NO_TRADE",
                "reason": f"quorum_{self._current_regime}",
                "symbol": leader["symbol"] if leader else "",
                "side": leader["side"] if leader else "",
                "token_id": leader["contract"].get("yes_token_id") if leader and leader["side"] == "UP" else (leader["contract"].get("no_token_id") if leader else ""),
                "contract_slug": leader["contract_slug"] if leader else "",
                "window_start_ts": leader["window_start_ts"] if leader else "",
                "window_end_ts": leader["window_end_ts"] if leader else window_end_ts,
                "snapshot_price": leader["context"]["snapshot_price"] if leader else "",
                "signal_rr": leader["context"].get("signal_rr") if leader else "",
                "signal_quality": leader["quality"] if leader else "",
                "signal_priority": leader["strength"] if leader else "",
                "execution_outcome": "no_trade",
                "order_id": "",
                "config_snapshot": json.dumps(self._get_config_snapshot()),
                "extra": json.dumps({"candidates": [c["symbol"] for c in candidates]}),
            })

            logger.info(
                "FINAL DECISION | NO TRADE (%s quorum) | window_end=%s candidates=%d required=%d",
                self._current_regime,
                window_end_ts,
                len(candidates),
                MIN_ACTIVE_CANDIDATES,
            )

            self._window_signals[window_end_ts] = {}
            self._candidate_signals.clear()
            self._signal_confirmations.clear()
            self._comparison_start_ts = None
            self._current_best_signal = None

            return

        leader = max(candidates, key=lambda x: x["quality"])

        # Log signal competition outcome
        if len(candidates) > 1:
            logger.info(
                "Signal competition | WINNER: %s (quality=%.2f) | candidates=%s",
                leader["symbol"],
                leader["quality"],
                [(c["symbol"], c["side"], round(c["quality"], 2)) for c in candidates]
            )
        
        # Detect correlation: both symbols agree on direction (high confidence)
        correlation_detected = False
        if len(candidates) >= 2:
            sides = [c["side"] for c in candidates]
            if len(set(sides)) == 1:  # All same direction
                correlation_detected = True
                logger.info(
                    "🔥 CORRELATION DETECTED | Both symbols agree: %s | Increasing position size by 30%%",
                    sides[0]
                )

        window_start_ts = leader["window_start_ts"]
        window_end_ts = leader["window_end_ts"]

        decision_ts = time.time()

        late_window = decision_ts > (window_end_ts - SCAN_END_OFFSET_SECONDS)

        all_unstable = all(not s["gates"]["stability_ok"] for s in candidates)
        early_phase = leader["context"]["signal_phase"] < 0.20

        if late_window:
            logger.info("FINAL DECISION | NO TRADE (late) | window_end=%s", window_end_ts)

            self._window_signals[window_end_ts] = {}
            self._candidate_signals.clear()
            self._signal_confirmations.clear()
            self._comparison_start_ts = None
            self._current_best_signal = None

            return

        if all_unstable and early_phase:
            logger.info("FINAL DECISION | NO TRADE (unstable) | window_end=%s", window_end_ts)

            self._window_signals[window_end_ts] = {}
            self._candidate_signals.clear()
            self._signal_confirmations.clear()
            self._comparison_start_ts = None
            self._current_best_signal = None

            return

        symbol = leader["symbol"]
        side = leader["side"]
        m = leader["metrics"]
        ctx = leader["context"]
        phase = leader["phase"]
        gates = leader["gates"]
        contract = leader["contract"]
        snapshot_price = ctx["snapshot_price"]
        signal_rr = ctx["signal_rr"]
        anchor_price = ctx["anchor_price"]
        contract_slug = leader["contract_slug"]
        
        # Safe token_id extraction with validation
        try:
            token_id = contract["yes_token_id"] if side == "UP" else contract["no_token_id"]
            if not token_id:
                raise ValueError("token_id is empty")
        except (KeyError, ValueError) as e:
            logger.error("Missing or invalid token_id | symbol=%s side=%s error=%s", symbol, side, e)
            self._window_signaled[window_end_ts] = True
            self._candidate_signals.clear()
            self._signal_confirmations.clear()
            self._comparison_start_ts = None
            self._current_best_signal = None
            return

        # Filter A: same-symbol, same-side cooldown (30 min).
        # Audit (2026-04-25..28, n=24 settled): blocks 1 of 8 losses, 0 of 16 winners,
        # plus suppresses 2 wasted execution-failed re-fires. Net +EV in-sample.
        SAME_SIDE_COOLDOWN_S = 30 * 60
        last_ts = self._last_final_trade_ts.get((symbol, side))
        now_ts = time.time()
        if last_ts is not None and (now_ts - last_ts) < SAME_SIDE_COOLDOWN_S:
            wait_s = int(SAME_SIDE_COOLDOWN_S - (now_ts - last_ts))
            logger.info(
                "Blocked: same-side cooldown | symbol=%s side=%s remaining=%ds (last FINAL TRADE %ds ago)",
                symbol,
                side,
                wait_s,
                int(now_ts - last_ts),
            )
            self._record_gate_block(
                "same_side_cooldown",
                symbol=symbol,
                side=side,
                snapshot_price=snapshot_price,
                signal_rr=signal_rr,
                window_start_ts=window_start_ts,
                token_id=token_id,
                extra={
                    "remaining_s": wait_s,
                    "since_last_final_s": int(now_ts - last_ts),
                    "cooldown_s": SAME_SIDE_COOLDOWN_S,
                },
            )
            self._window_signaled[window_end_ts] = True
            self._candidate_signals.clear()
            self._signal_confirmations.clear()
            self._comparison_start_ts = None
            self._current_best_signal = None
            return

        logger.info(
            "FINAL TRADE | symbol=%s side=%s priority=%.2f quality=%.2f",
            symbol,
            side,
            leader["strength"],
            leader["quality"],
        )

        # Instrumentation: emit a single feature-snapshot line adjacent to FINAL
        # TRADE so post-hoc audits can recover the decision context without
        # scraping 60 lines of upstream log noise. Wrapped in try/except so a
        # missing key never blocks a trade.
        try:
            _m = leader.get("metrics", {}) or {}
            _phase = leader.get("phase", {}) or {}
            _ctx = leader.get("context", {}) or {}
            logger.info(
                "FINAL TRADE FEATURES | symbol=%s side=%s slug=%s "
                "percent_move=%.5f dynamic_percent_threshold=%.5f volatility=%.6f "
                "slope_z=%.3f distance_z=%.3f vol_ratio=%.3f percent_vol_ratio=%.3f "
                "age_min=%.2f phase=%.3f snapshot_price=%.4f signal_rr=%.4f",
                symbol,
                side,
                contract_slug,
                float(_m.get("percent_move", 0.0) or 0.0),
                float(_phase.get("dynamic_percent_threshold", 0.0) or 0.0),
                float(_m.get("volatility", 0.0) or 0.0),
                float(_m.get("slope_z", 0.0) or 0.0),
                float(_m.get("distance_z", 0.0) or 0.0),
                float(_phase.get("vol_ratio", 0.0) or 0.0),
                float(_phase.get("percent_vol_ratio", 0.0) or 0.0),
                float(_ctx.get("signal_age_minutes", 0.0) or 0.0),
                float(_ctx.get("signal_phase", 0.0) or 0.0),
                float(_ctx.get("snapshot_price", 0.0) or 0.0),
                float(_ctx.get("signal_rr", 0.0) or 0.0),
            )
        except Exception:
            logger.exception("FINAL TRADE FEATURES emit failed")

        import asyncio

        # Mark the window as signaled immediately to prevent double-trades from race conditions.
        self._window_signaled[window_end_ts] = True
        self._last_final_trade_ts[(symbol, side)] = now_ts

        # Track background tasks with proper cleanup
        def _task_done_callback(task):
            self._background_tasks.discard(task)
            if task.exception():
                logger.error("Background task failed: %s", task.exception())

        try:
            # Build the decision-email kwargs now (while all locals are in scope),
            # but defer the actual send until after execution confirms a fill.
            # This prevents email noise for signals that get skipped by the
            # execution-side live-ask cap.
            _email_kwargs = dict(
                symbol=symbol,
                side=side,
                contract_slug=contract_slug,
                window_start_ts=window_start_ts,
                window_end_ts=window_end_ts,
                decision_ts=decision_ts,
                metrics={
                    **m,
                    **ctx,
                    **phase,
                    **gates,
                    "signal_priority": leader["strength"],
                    "signal_quality": leader["quality"],
                    "all_candidates": [
                        {
                            "symbol": s["symbol"],
                            "quality": s["quality"],
                            "priority": s["strength"],
                            "pvr": s["phase"]["percent_vol_ratio"],
                            "stability_ok": s["gates"]["stability_ok"],
                        }
                        for s in candidates
                    ],
                },
            )
        except Exception:
            logger.exception("Failed to build decision email payload")
            _email_kwargs = None

        # Build the Telegram alert payload now (while all locals are in scope),
        # but defer the actual send until after execution confirms a fill.
        _telegram_payload = {
            "symbol": symbol,
            "side": side,
            "price": m["price"],
            "anchor_price": anchor_price,
            "contract": contract,
            "timestamp": decision_ts,
            "snapshot_price": snapshot_price,
            "signal_rr": signal_rr,
            "signal_quality": leader["quality"],
            "stability_ok": gates["stability_ok"],
            **phase,
        }

        # Update local tracking variables before awaiting execution to prevent race conditions
        self._last_trade_meta[symbol] = {
            "symbol": symbol,
            "side": side,
            "entry_price": m["price"],
            "entry_ts": decision_ts,
        }
        if window_end_ts not in self._symbols_traded_this_window:
            self._symbols_traded_this_window[window_end_ts] = set()
        self._symbols_traded_this_window[window_end_ts].add(symbol)

        # ---------------- EXECUTION ----------------
        # Track outcome so the CSV row at the end of this method records whether
        # the signal actually filled. Values: "filled", "skipped", "error",
        # "read_only", "no_client".
        execution_outcome = "no_client"
        execution_order_id = ""
        if not self.read_only and self.execution_client:
            try:
                # Dynamic position sizing based on signal quality
                # Standard: $5 (< 2500), Strong: $7.50 (2500-3500), Exceptional: $10 (> 3500)
                # NOTE: Analysis showed quality_score may be backwards (low quality = high WR)
                # but keeping tiered sizing for now - may want to invert or use flat $5 later
                quality_score = leader["quality"]
                trade_size = calculate_position_size(quality_score)
                
                # Apply correlation bonus: when both BTC and ETH agree on direction,
                # it's strong confirmation - increase position size by 30%
                if correlation_detected:
                    trade_size *= 1.3
                    logger.info(
                        "Position sizing | quality=%.2f base=$%.2f correlation_bonus=30%% final=$%.2f",
                        quality_score,
                        trade_size / 1.3,
                        trade_size,
                    )
                else:
                    logger.info(
                        "Position sizing | quality=%.2f size=$%.2f",
                        quality_score,
                        trade_size,
                    )
                
                execution_result = await self.execution_client.execute_trade(
                    symbol=symbol,
                    contract_slug=contract_slug,
                    token_id=token_id,
                    side=side,
                    price=snapshot_price,
                    size=trade_size,
                    window_end_ts=window_end_ts,
                )
                if execution_result is None:
                    execution_outcome = "skipped"
                    logger.error(
                        "Execution failed or skipped | symbol=%s side=%s",
                        symbol,
                        side,
                    )
                else:
                    execution_outcome = "filled"
                    execution_order_id = str(execution_result.get("id") or "")
                    logger.info(
                        "Execution confirmed | order_id=%s",
                        execution_result.get("id"),
                    )
                    # Fire user-facing notifications only on confirmed fill.
                    if _email_kwargs is not None:
                        try:
                            email_task = asyncio.create_task(
                                asyncio.to_thread(send_decision_email, **_email_kwargs)
                            )
                            email_task.add_done_callback(_task_done_callback)
                            self._background_tasks.add(email_task)
                        except Exception:
                            logger.exception("Email alert failed")
                    try:
                        telegram_task = asyncio.create_task(
                            asyncio.to_thread(emit_alert, _telegram_payload)
                        )
                        telegram_task.add_done_callback(_task_done_callback)
                        self._background_tasks.add(telegram_task)
                    except Exception:
                        logger.exception("Telegram alert failed")
            except Exception:
                execution_outcome = "error"
                logger.exception("Execution layer failure")
        else:
            execution_outcome = "read_only"
            # Open a shadow (paper-fill) position so we collect the same
            # lifecycle telemetry we would get under live execution. Pure
            # observer; no orders are sent.
            try:
                self.shadow_book.open(
                    token_id=token_id,
                    symbol=symbol,
                    side=side,
                    snapshot_price=snapshot_price,
                    window_end_ts=window_end_ts,
                    signal_rr=signal_rr,
                    signal_quality=leader["quality"],
                    signal_priority=leader["strength"],
                    contract_slug=contract_slug,
                )
            except Exception:
                logger.exception("Shadow open failed")
            # Read-only / no-execution mode: fire notifications directly so dry
            # runs and observation modes still produce email + Telegram output.
            if _email_kwargs is not None:
                try:
                    email_task = asyncio.create_task(
                        asyncio.to_thread(send_decision_email, **_email_kwargs)
                    )
                    email_task.add_done_callback(_task_done_callback)
                    self._background_tasks.add(email_task)
                except Exception:
                    logger.exception("Email alert failed")
            try:
                telegram_task = asyncio.create_task(
                    asyncio.to_thread(emit_alert, _telegram_payload)
                )
                telegram_task.add_done_callback(_task_done_callback)
                self._background_tasks.add(telegram_task)
            except Exception:
                logger.exception("Telegram alert failed")


        # Per-gate detail for the WINNING signal (one row per gate). Lets us
        # measure per-gate contribution post-hoc instead of digging through the
        # decision_log.extra JSON. Observer only.
        try:
            aux_logs.log_trade_gates(
                decision_type="TRADE" if execution_outcome == "filled" else execution_outcome.upper(),
                symbol=symbol,
                side=side,
                token_id=token_id,
                window_start_ts=window_start_ts,
                gates=gates if isinstance(gates, dict) else {},
            )
        except Exception:
            pass

        # YES vs NO book snapshot at decision time. Imbalance + mid_sum are
        # the headline diagnostics for adverse selection / arb mispricing.
        try:
            _contract_dict = leader.get("contract") if isinstance(leader, dict) else None
            if _contract_dict:
                aux_logs.log_side_imbalance(
                    symbol=symbol,
                    contract_slug=contract_slug,
                    window_start_ts=window_start_ts,
                    decided_side=side,
                    yes_token_id=str(_contract_dict.get("yes_token_id") or ""),
                    no_token_id=str(_contract_dict.get("no_token_id") or ""),
                    clob_book_tracker=self.clob_book_tracker,
                )
        except Exception:
            pass

        # Log unified decision row (TRADE or SKIPPED/READ_ONLY)
        self._log_decision_row({
            "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "decision_type": "TRADE" if execution_outcome == "filled" else "NO_TRADE",
            "reason": execution_outcome,
            "symbol": symbol,
            "side": side,
            "token_id": token_id,
            "contract_slug": contract_slug,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "snapshot_price": snapshot_price,
            "signal_rr": signal_rr,
            "signal_quality": leader["quality"],
            "signal_priority": leader["strength"],
            "execution_outcome": execution_outcome,
            "order_id": execution_order_id,
            "config_snapshot": json.dumps(self._get_config_snapshot()),
            "extra": json.dumps({"phase": phase, "metrics": m, "context": ctx, "gates": gates}),
        })

        self._log_execution_row({
            "timestamp": decision_ts,
            "token_id": token_id,
            "symbol": symbol,
            "side": side,
            "contract_slug": contract_slug,
            "snapshot_price": snapshot_price,
            "signal_rr": signal_rr,
            "signal_age_minutes": ctx["signal_age_minutes"],
            "signal_phase": ctx["signal_phase"],
            "anchor_distance_percent": (m["price"] - anchor_price) / anchor_price * 100,
            "signal_priority": leader["strength"],
            "signal_quality": leader["quality"],
            "execution_outcome": execution_outcome,
            "order_id": execution_order_id,
            **phase,
        })

        self._window_signals[window_end_ts] = {}
        self._candidate_signals.clear()
        self._signal_confirmations.clear()
        self._comparison_start_ts = None
        self._current_best_signal = None


    def _build_no_trade_metrics(
        self,
        *,
        reason: str,
        regime: str | None,
        candidates: list,
        leader: dict | None,
    ) -> dict:

        def safe(v):
            return v if v is not None else "na"

        base = {
            "decision_type": "NO_TRADE",
            "reason": reason,
            "regime": regime,
            "active_candidates": len(candidates),
        }

        if leader:
            m = leader.get("metrics", {})
            ctx = leader.get("context", {})
            phase = leader.get("phase", {})
            gates = leader.get("gates", {})

            price = m.get("price")
            anchor = ctx.get("anchor_price")

            anchor_distance = None
            if (
                isinstance(price, (int, float)) and
                isinstance(anchor, (int, float)) and
                anchor != 0
            ):
                anchor_distance = (price - anchor) / anchor * 100

            enriched = {
                "price": safe(price),
                "anchor_price": safe(anchor),
                "anchor_distance_percent": safe(anchor_distance),
                "snapshot_price": safe(ctx.get("snapshot_price")),
                "signal_rr": safe(ctx.get("signal_rr")),
                "signal_age_minutes": safe(ctx.get("signal_age_minutes")),
                "signal_phase": safe(ctx.get("signal_phase")),
                "signal_quality": safe(leader.get("quality")),
                "signal_priority": safe(leader.get("strength")),
                "edge_z": safe(m.get("edge_z")),
                "slope_z": safe(m.get("slope_z")),
                "slope_z_24h": safe(phase.get("slope_z_24h")),
                "percent_move": safe(m.get("percent_move")),
                "distance_z": safe(m.get("distance_z")),
                "raw_vol": safe(m.get("raw_vol")),
                "adaptive_floor": safe(m.get("adaptive_floor")),
                "volatility": safe(m.get("volatility")),
                "structure_vol": safe(phase.get("structure_vol")),
                "vol_ratio": safe(phase.get("vol_ratio")),
                "percent_vol_ratio": safe(phase.get("percent_vol_ratio")),
                "extension_pressure": safe(phase.get("extension_pressure")),
                "adaptive_drift_cap": safe(phase.get("adaptive_drift_cap")),
                "pvr_ideal": safe(phase.get("pvr_ideal")),
                "pvr_terminal": safe(phase.get("pvr_terminal")),
                "continuation_override": safe(phase.get("continuation_override")),
                "slope_ok": safe(gates.get("slope_ok")),
                "acceleration_ok": safe(gates.get("acceleration_ok")),
                "percent_ok": safe(gates.get("percent_ok")),
                "distance_ok": safe(gates.get("distance_ok")),
                "exhaustion_ok": safe(gates.get("exhaustion_ok")),
                "drift_ok": safe(gates.get("drift_ok")),
                "candle_ok": safe(gates.get("candle_ok")),
                "structure_alignment_ok": safe(gates.get("structure_alignment_ok")),
                "stability_ok": safe(gates.get("stability_ok")),
            }
        else:
            enriched = {
                "signal_quality": "na",
                "signal_priority": "na",
                "signal_phase": "na",
            }

        candidates_block = [
            {
                "symbol": s.get("symbol"),
                "quality": s.get("quality"),
                "priority": s.get("strength"),
                "pvr": s.get("phase", {}).get("percent_vol_ratio"),
                "stability_ok": s.get("gates", {}).get("stability_ok"),
            }
            for s in candidates
        ]

        return {
            **base,
            **enriched,
            "all_candidates": candidates_block,
        }


    def _trigger_post_loss_cooldown(self, loss_window_end_ts: int, *, reason: str) -> None:
        """Extend the post-loss cooldown horizon by POST_LOSS_SKIP_WINDOWS windows.

        Idempotent: never shrinks the existing horizon; if multiple losses
        resolve close together the horizon is the latest of them.
        """
        new_horizon = int(loss_window_end_ts) + POST_LOSS_SKIP_WINDOWS * WINDOW_DURATION_SEC
        if new_horizon > self._cooldown_until_window_ts:
            self._cooldown_until_window_ts = new_horizon
            logger.info(
                "Post-loss cooldown engaged | reason=%s loss_window_end=%d skip_windows=%d cooldown_until=%d",
                reason, loss_window_end_ts, POST_LOSS_SKIP_WINDOWS, new_horizon,
            )
            try:
                aux_logs.log_cooldown_event(
                    event="SET",
                    reason=reason,
                    loss_window_end_ts=int(loss_window_end_ts),
                    cooldown_until_window_ts=int(new_horizon),
                    skip_windows=POST_LOSS_SKIP_WINDOWS,
                )
            except Exception:
                pass

    async def _manage_positions(self) -> None:
        if not self.execution_client:
            return
            
        now_ts = time.time()
        for token_id, pos in list(self.execution_client.active_positions.items()):
            # 1. Age Out / Expiry Sell
            window_end_ts = pos["window_end_ts"]

            if now_ts >= window_end_ts:
                # Window has closed — attempt to sell whatever the current bid is before
                # the contract settles. Polymarket does NOT auto-redeem; leaving shares
                # unsold means we must manually claim via the UI.
                bid_price = await self._fetch_clob_bid_price(token_id)
                if bid_price and bid_price >= 0.01:
                    entry_price = pos["entry_price"]
                    actual_exit = round(bid_price - 0.01, 2)
                    profit_cents = actual_exit - entry_price
                    logger.info("Expiry Sell | token=%s entry=%.3f bid=%.3f actual_exit=%.3f profit=$%.2f", token_id, entry_price, bid_price, actual_exit, profit_cents)
                    success = await self.execution_client.close_position(token_id, sell_price=bid_price)
                    if success:
                        # Fetch resolved outcome and compare to side
                        predicted_side = pos.get("side", "")
                        resolved_outcome = await fetch_resolved_outcome(token_id)
                        predicted_side_won = None
                        if resolved_outcome is not None and predicted_side:
                            # Normalize to uppercase for comparison
                            if predicted_side.upper() == resolved_outcome.upper():
                                predicted_side_won = 1
                            else:
                                predicted_side_won = 0
                        self._log_exit_row({
                            "timestamp": now_ts,
                            "token_id": token_id,
                            "type": "EXPIRY_SELL",
                            "entry_price": entry_price,
                            "exit_price": actual_exit,
                            "profit_cents": profit_cents,
                            "predicted_side": predicted_side,
                            "resolved_outcome": resolved_outcome,
                            "predicted_side_won": predicted_side_won
                        })
                        if profit_cents <= 0:
                            self._trigger_post_loss_cooldown(window_end_ts, reason="expiry_sell_loss")
                    else:
                        logger.warning("Expiry sell did not fill for %s. Will retry next cycle.", token_id)
                else:
                    # No bid — contract likely already settled at $0. Drop tracking.
                    if now_ts > window_end_ts + 60 * 15:
                        entry_price = pos["entry_price"]
                        profit_cents = -entry_price  # full loss of premium per share
                        logger.info(
                            "Position %s dropped from local tracking (no bid after expiry, likely settled $0) | entry=%.3f loss=$%.3f/share",
                            token_id, entry_price, entry_price,
                        )
                        # Fetch resolved outcome and compare to side
                        predicted_side = pos.get("side", "")
                        resolved_outcome = await fetch_resolved_outcome(token_id)
                        predicted_side_won = None
                        if resolved_outcome is not None and predicted_side:
                            if predicted_side.upper() == resolved_outcome.upper():
                                predicted_side_won = 1
                            else:
                                predicted_side_won = 0
                        self._log_exit_row({
                            "timestamp": now_ts,
                            "token_id": token_id,
                            "type": "SETTLED_ZERO",
                            "entry_price": entry_price,
                            "exit_price": 0.0,
                            "profit_cents": profit_cents,
                            "predicted_side": predicted_side,
                            "resolved_outcome": resolved_outcome,
                            "predicted_side_won": predicted_side_won
                        })
                        del self.execution_client.active_positions[token_id]
                        self.execution_client._persist_state()
                        # Settled-at-$0 path is a confirmed loss.
                        self._trigger_post_loss_cooldown(window_end_ts, reason="settled_zero")
                continue

            # 2. Hold-to-Expiry Strategy (No Stop-Loss)
            # With 76% prediction accuracy, we trust the signals and hold all positions
            # to resolution. Binary outcome markets resolve to $1.00 (win) or $0.00 (loss).
            # Interim price swings are noise - exiting early converts winners into losers.
            # Strategy: Only exit at expiry, let oracle resolution determine profit/loss.

    async def _on_price_event(self, symbol: str, event) -> None:
        """
        Callback invoked by MarketData on each new price update.
        Queues the event for processing by the main loop.
        Filters out non-tradable symbols at ingress.
        """
        # Skip non-tradable symbols early to keep queue clean
        if symbol not in SAFE_MARKETS:
            return
        try:
            # Non-blocking put with size limit to prevent memory issues
            if self._price_event_queue.qsize() < 900:
                await self._price_event_queue.put((symbol, event))
        except Exception as e:
            logger.error("Error queueing price event | symbol=%s | %s", symbol, e)

    async def run(self) -> None:
        logger.info("PolyouBot started (event-driven mode)")
        
        # Start background task for periodic position management
        position_mgmt_task = asyncio.create_task(self._position_management_loop())
        
        try:
            while True:
                try:
                    # Wait for price event (blocks until new price arrives)
                    # Timeout ensures position management runs even without prices
                    try:
                        symbol, event = await asyncio.wait_for(
                            self._price_event_queue.get(),
                            timeout=5.0
                        )
                        
                        # CRITICAL: Filter to safe markets only.
                        # Price listener receives ALL symbols (BTC/ETH/SOL/XRP),
                        # but SAFE_MARKETS restricts which we trade.
                        if symbol not in SAFE_MARKETS:
                            continue
                        
                        # Throttle evaluations per symbol to avoid excessive processing
                        now = time.time()
                        last_eval = self._last_eval_ts.get(symbol, 0)
                        
                        if now - last_eval < self._min_eval_interval:
                            # Skip this update, too soon since last eval
                            continue
                        
                        self._last_eval_ts[symbol] = now
                        
                        # Process this symbol immediately
                        await self._run_once_for_symbol(symbol)
                        
                    except asyncio.TimeoutError:
                        # No new prices for 5s, process all symbols once
                        for symbol in self._iter_markets():
                            await self._run_once_for_symbol(symbol)
                    
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("[FATAL]")
                    await asyncio.sleep(60)
        finally:
            position_mgmt_task.cancel()
            await asyncio.gather(position_mgmt_task, return_exceptions=True)
    
    async def _position_management_loop(self) -> None:
        """
        Separate loop for managing positions, runs every 30 seconds.
        """
        while True:
            try:
                await asyncio.sleep(30)
                await self._manage_positions()
                # Shadow paper-book: tick all open synthetic positions, then
                # settle any whose window expired. Defensive — never raise.
                try:
                    self.shadow_book.tick()
                    self.shadow_book.settle_expired()
                except Exception:
                    logger.exception("Shadow book tick/settle failed")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Position management error")
