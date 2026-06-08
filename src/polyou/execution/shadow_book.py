"""
Shadow Position Book — paper-fill simulator for data collection.

Pure observer. Never sends an order. When the bot reaches a "would-trade"
decision in READ_ONLY mode, we open a synthetic position at snapshot_price,
record per-tick mark prices to logs/position_ticks.csv, and settle at the
expiry bid (or oracle 0/1) writing logs/shadow_exits.csv.

Produces the data we'd otherwise only get after flipping execution on:
  - per-position lifecycle (entry/exit timestamps, slippage_vs_snapshot,
    fill assumption, fees=0)
  - per-tick unrealized PnL with live mid/best_ask/best_bid/spread_bps
  - exit-time book context

State persisted to logs/shadow_positions.json so a restart resumes
in-flight synthetic positions.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("shadow_book")

LOG_DIR = "logs"
STATE_PATH = os.path.join(LOG_DIR, "shadow_positions.json")
POSITION_TICKS_PATH = os.path.join(LOG_DIR, "position_ticks.csv")
# Allow override via env var so a second bot instance can write to a separate file
SHADOW_EXITS_PATH = os.environ.get(
    "SHADOW_EXITS_FILE", os.path.join(LOG_DIR, "shadow_exits.csv")
)

POSITION_TICKS_FIELDS = (
    "ts_iso",
    "position_id",
    "token_id",
    "symbol",
    "side",
    "entry_price",
    "entry_ts",
    "age_in_position_s",
    "best_ask",
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "mid",
    "spread_bps",
    "mark_price",          # mid if both sides present, else best_bid, else best_ask
    "unrealized_pnl",      # mark_price - entry_price (per share)
    "clob_age_ms",
)

SHADOW_EXITS_FIELDS = (
    "ts_iso",
    "position_id",
    "leader_address",
    "token_id",
    "symbol",
    "side",
    "entry_price",
    "entry_ts",
    "exit_ts",
    "exit_type",           # EXPIRY_BID | SETTLED_ZERO | SETTLED_ONE | STOP_LOSS
    "exit_price",          # realized per-share proceeds
    "profit_per_share",
    "best_ask_at_exit",
    "best_bid_at_exit",
    "spread_bps_at_exit",
    "clob_age_ms_at_exit",
    "window_end_ts",
    "hold_seconds",
    "snapshot_price",      # what bot saw at decision
    "slippage_vs_snapshot",  # entry_price - snapshot_price (we assume immediate fill at snapshot)
    "signal_rr",
    "signal_quality",
    "signal_priority",
    "contract_slug",
    # --- Inverse / fade-the-signal shadow accounting (no behavior change) ---
    # predicted_side_won: 1 if exit_type == EXPIRY_BID (the predicted side was
    # trading near $1 at expiry => about to settle TRUE); 0 if SETTLED_ZERO;
    # blank for ambiguous types.
    # NOTE: this is exit-type based, not actual outcome. It misclassifies
    # winners that couldn't sell (no bid past grace) as losses. Use the
    # `actual_won` / `true_pnl` columns below for ground-truth analysis.
    "predicted_side_won",
    # inverse_pnl_naive: per-share P&L of the OPPOSITE bet, assuming we could
    # have sold our predicted side at exactly entry_price (no slippage).
    # = entry_price            if predicted side LOST  (we keep the premium)
    # = entry_price - 1.0      if predicted side WON   (we owe $1 at settle)
    # Same caveat as above: derived from exit_type, not actual outcome.
    "inverse_pnl_naive",
    # inverse_pnl_3c_spread: same as above but charging 3¢ for crossing the
    # opposite-side ask at entry. Conservative spread approximation.
    "inverse_pnl_3c_spread",
    # --- Ground-truth (chainlink) outcome columns ---
    # window_start_price / window_end_price: chainlink spot at the moment
    # the window opened / closed. Blank if unavailable from the price
    # replay buffer. Polymarket Up/Down settles by comparing these.
    "window_start_price",
    "window_end_price",
    # actual_won: 1 if bot's predicted side actually won per chainlink
    # (UP and end>start, or DOWN and end<=start). 0 if it lost. Blank if
    # we couldn't determine outcome from replay buffer.
    "actual_won",
    # true_pnl: on-chain redemption P&L of the bot's actual position.
    # = (1 - entry_price)  if actual_won  else  -entry_price
    # This is what the bot would have earned if it held to redemption
    # instead of accepting a $0 mark on SETTLED_ZERO.
    "true_pnl",
    # true_inverse_pnl: on-chain redemption P&L of the OPPOSITE bet,
    # assuming entry at (1 - entry_price) on the inverse side.
    # = entry_price        if actual_won == 0  (inverse won)
    # = entry_price - 1.0  if actual_won == 1  (inverse lost)
    "true_inverse_pnl",
)

# Time after window_end_ts before we declare unsold position settled at $0.
SETTLE_GRACE_SECONDS = 15 * 60


def _append_csv(path: str, fields, row: dict) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        new_file = not os.path.isfile(path)
        with open(path, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        logger.exception("CSV write failed | path=%s", path)


class ShadowPositionBook:
    """Tracks would-be positions in paper mode."""

    def __init__(self, *, clob_book_tracker=None, market_data=None):
        self.tracker = clob_book_tracker
        # Optional: MarketData for chainlink replay lookup. Used to compute
        # ground-truth outcome (`actual_won`) at close, instead of relying
        # on exit_type which silently misclassifies winners with no bid.
        self.market_data = market_data
        self.positions: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    # ------------------------------------------------------------------
    # Chainlink price lookup (oracle outcome)
    # ------------------------------------------------------------------
    def _price_at(self, symbol: str, target_ts: float) -> Optional[float]:
        """Latest chainlink price at-or-before target_ts from replay buffer.

        Returns None if MarketData isn't wired in or no sample qualifies.
        Buffer is bounded (~500 events) so a far-past lookup may return None;
        we accept that and leave the column blank.
        """
        if self.market_data is None:
            return None
        try:
            replay = self.market_data.get_replay(symbol)
        except Exception:
            return None
        best = None
        for ev in replay:
            ev_ts = getattr(ev, "ts", None)
            if ev_ts is None or ev_ts > target_ts:
                continue
            if best is None or ev_ts > getattr(best, "ts", 0.0):
                best = ev
        return float(best.price) if best is not None else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        try:
            if os.path.isfile(STATE_PATH):
                with open(STATE_PATH, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.positions = data
                    logger.info("Shadow book restored | n_positions=%d", len(self.positions))
        except Exception:
            logger.exception("Failed to load shadow positions; starting empty")
            self.positions = {}

    def _persist_state(self) -> None:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            tmp = STATE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.positions, f)
            os.replace(tmp, STATE_PATH)
        except Exception:
            logger.exception("Failed to persist shadow positions")

    # ------------------------------------------------------------------
    # Book context lookup
    # ------------------------------------------------------------------
    def _book(self, token_id: str) -> Dict[str, Any]:
        empty = {
            "best_ask": None, "best_bid": None,
            "best_ask_size": None, "best_bid_size": None,
            "mid": None, "spread_bps": None, "clob_age_ms": None,
        }
        if not token_id or self.tracker is None:
            return empty
        try:
            snap = self.tracker.get_book(token_id)
            age = self.tracker.get_age_ms(token_id)
            if snap is None:
                return {**empty, "clob_age_ms": age}
            ba, bb = snap.best_ask, snap.best_bid
            mid = ((ba + bb) / 2.0) if (ba is not None and bb is not None) else None
            spread_bps = None
            if mid is not None and mid > 0 and ba is not None and bb is not None:
                spread_bps = ((ba - bb) / mid) * 10000.0
            return {
                "best_ask": ba, "best_bid": bb,
                "best_ask_size": snap.best_ask_size,
                "best_bid_size": snap.best_bid_size,
                "mid": mid, "spread_bps": spread_bps,
                "clob_age_ms": age,
            }
        except Exception:
            return empty

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def open(
        self,
        *,
        token_id: str,
        symbol: str,
        side: str,
        snapshot_price: float,
        window_end_ts: int,
        leader_address: str = "",
        signal_rr: float | None = None,
        signal_quality: float | None = None,
        signal_priority: float | None = None,
        contract_slug: str = "",
        window_seconds: int = 15 * 60,
    ) -> Optional[str]:
        """Open a synthetic position. Returns position_id, or None if duplicate."""
        if not token_id or snapshot_price is None:
            return None
        token_id = str(token_id)
        if token_id in self.positions:
            return None  # already shadowing this token
        now = time.time()
        # Entry assumed = snapshot_price (the bot's stated intent). If the live
        # ask drifted higher, we still record snapshot to compare slippage at exit.
        position_id = f"{token_id}-{int(now)}"
        # Snapshot chainlink price at window_start so we have the correct
        # reference even if the replay buffer rotates it out before close.
        window_end_int = int(window_end_ts) if window_end_ts else 0
        window_start_ts = (window_end_int - int(window_seconds)) if window_end_int else 0
        window_start_price = (
            self._price_at(symbol, window_start_ts + 5)
            if window_start_ts else None
        )
        self.positions[token_id] = {
            "position_id": position_id,
            "token_id": token_id,
            "symbol": symbol,
            "side": side,
            "entry_price": float(snapshot_price),
            "snapshot_price": float(snapshot_price),
            "entry_ts": now,
            "window_end_ts": window_end_int,
            "window_start_price": window_start_price,
            "leader_address": leader_address,
            "signal_rr": signal_rr,
            "signal_quality": signal_quality,
            "signal_priority": signal_priority,
            "contract_slug": contract_slug,
        }
        self._persist_state()
        logger.info(
            "Shadow open | sym=%s side=%s token=%s entry=%.4f window_end=%s",
            symbol, side, token_id, snapshot_price, window_end_ts,
        )
        return position_id

    def tick(self) -> None:
        """Write a position_ticks.csv row for every open shadow position."""
        if not self.positions:
            return
        now = time.time()
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for token_id, pos in list(self.positions.items()):
            book = self._book(token_id)
            mark = book["mid"] or book["best_bid"] or book["best_ask"]
            unreal = (mark - pos["entry_price"]) if mark is not None else None
            _append_csv(POSITION_TICKS_PATH, POSITION_TICKS_FIELDS, {
                "ts_iso": ts_iso,
                "position_id": pos["position_id"],
                "token_id": token_id,
                "symbol": pos["symbol"],
                "side": pos["side"],
                "entry_price": f"{pos['entry_price']:.4f}",
                "entry_ts": f"{pos['entry_ts']:.0f}",
                "age_in_position_s": f"{now - pos['entry_ts']:.0f}",
                "best_ask": f"{book['best_ask']:.4f}" if book["best_ask"] is not None else "",
                "best_bid": f"{book['best_bid']:.4f}" if book["best_bid"] is not None else "",
                "best_ask_size": f"{book['best_ask_size']:.2f}" if book["best_ask_size"] is not None else "",
                "best_bid_size": f"{book['best_bid_size']:.2f}" if book["best_bid_size"] is not None else "",
                "mid": f"{book['mid']:.4f}" if book["mid"] is not None else "",
                "spread_bps": f"{book['spread_bps']:.2f}" if book["spread_bps"] is not None else "",
                "mark_price": f"{mark:.4f}" if mark is not None else "",
                "unrealized_pnl": f"{unreal:.4f}" if unreal is not None else "",
                "clob_age_ms": book["clob_age_ms"] if book["clob_age_ms"] is not None else "",
            })

    def settle_stop_loss(self, threshold: float = -0.25) -> None:
        """Close positions that have fallen below the stop-loss threshold.

        Args:
            threshold: P&L threshold (e.g., -0.25 for -25 cents per share)
        """
        if not self.positions:
            return
        now = time.time()
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for token_id, pos in list(self.positions.items()):
            book = self._book(token_id)
            # Calculate current P&L using mark price
            mark = book["mid"] or book["best_bid"] or book["best_ask"]
            if mark is None:
                continue  # Can't evaluate P&L without a mark price
            
            entry = pos["entry_price"]
            pnl = mark - entry
            
            # Check if we've hit the stop-loss
            if pnl <= threshold:
                # Exit at current bid if available, else at mark
                bid = book["best_bid"]
                exit_price = bid if bid is not None else mark
                exit_price = max(0.0, exit_price)  # Can't be negative
                self._close(pos, exit_price=exit_price, exit_type="STOP_LOSS",
                            book=book, now=now, ts_iso=ts_iso)
                logger.info(
                    "Stop-loss triggered | sym=%s side=%s token=%s entry=%.4f mark=%.4f pnl=%+.4f",
                    pos["symbol"], pos["side"], token_id, entry, mark, pnl
                )

    def settle_expired(self) -> None:
        """Close any positions whose window_end_ts has passed.

        Mirrors _manage_positions logic: try expiry-bid sell; if no bid past
        grace period, declare settled at $0.
        """
        if not self.positions:
            return
        now = time.time()
        ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for token_id, pos in list(self.positions.items()):
            wet = pos.get("window_end_ts") or 0
            if wet <= 0 or now < wet:
                continue
            book = self._book(token_id)
            bid = book["best_bid"]
            ask = book["best_ask"]
            if bid is not None and bid >= 0.01:
                exit_price = max(0.0, round(bid - 0.01, 4))
                self._close(pos, exit_price=exit_price, exit_type="EXPIRY_BID",
                            book=book, now=now, ts_iso=ts_iso)
            elif now > wet + SETTLE_GRACE_SECONDS:
                # No live bid past grace — assume settled at $0.
                self._close(pos, exit_price=0.0, exit_type="SETTLED_ZERO",
                            book=book, now=now, ts_iso=ts_iso)
            # else: keep waiting for a bid to appear.

    def _close(self, pos, *, exit_price, exit_type, book, now, ts_iso):
        token_id = pos["token_id"]
        entry = pos["entry_price"]
        snap = pos.get("snapshot_price", entry)
        # Inverse-fade accounting (paper-only; never affects live behavior).
        if exit_type == "EXPIRY_BID":
            predicted_side_won = 1
            inverse_pnl_naive = entry - 1.0
        elif exit_type == "SETTLED_ZERO":
            predicted_side_won = 0
            inverse_pnl_naive = entry
        elif exit_type == "STOP_LOSS":
            # Stop-loss exits before expiry; can't determine predicted outcome
            predicted_side_won = ""
            inverse_pnl_naive = None
        else:
            predicted_side_won = ""
            inverse_pnl_naive = None
        inverse_pnl_3c = (inverse_pnl_naive - 0.03) if inverse_pnl_naive is not None else None

        # --- Ground-truth outcome from chainlink replay buffer ---
        window_end_int = pos.get("window_end_ts") or 0
        window_start_price = pos.get("window_start_price")
        window_end_price = (
            self._price_at(pos["symbol"], window_end_int)
            if window_end_int else None
        )
        actual_won: Any = ""
        true_pnl: Any = ""
        true_inv_pnl: Any = ""
        if window_start_price is not None and window_end_price is not None:
            up_won = window_end_price > window_start_price
            side = pos["side"]
            won = (side == "UP" and up_won) or (side == "DOWN" and not up_won)
            actual_won = 1 if won else 0
            true_pnl = (1.0 - entry) if won else -entry
            true_inv_pnl = entry if not won else (entry - 1.0)
        _append_csv(SHADOW_EXITS_PATH, SHADOW_EXITS_FIELDS, {
            "ts_iso": ts_iso,
            "position_id": pos["position_id"],
            "leader_address": pos.get("leader_address", ""),
            "token_id": token_id,
            "symbol": pos["symbol"],
            "side": pos["side"],
            "entry_price": f"{entry:.4f}",
            "entry_ts": f"{pos['entry_ts']:.0f}",
            "exit_ts": f"{now:.0f}",
            "exit_type": exit_type,
            "exit_price": f"{exit_price:.4f}",
            "profit_per_share": f"{exit_price - entry:.4f}",
            "best_ask_at_exit": f"{book['best_ask']:.4f}" if book["best_ask"] is not None else "",
            "best_bid_at_exit": f"{book['best_bid']:.4f}" if book["best_bid"] is not None else "",
            "spread_bps_at_exit": f"{book['spread_bps']:.2f}" if book["spread_bps"] is not None else "",
            "clob_age_ms_at_exit": book["clob_age_ms"] if book["clob_age_ms"] is not None else "",
            "window_end_ts": pos.get("window_end_ts", ""),
            "hold_seconds": f"{now - pos['entry_ts']:.0f}",
            "snapshot_price": f"{snap:.4f}",
            "slippage_vs_snapshot": f"{entry - snap:.4f}",
            "signal_rr": pos.get("signal_rr") or "",
            "signal_quality": pos.get("signal_quality") or "",
            "signal_priority": pos.get("signal_priority") or "",
            "contract_slug": pos.get("contract_slug") or "",
            "predicted_side_won": predicted_side_won,
            "inverse_pnl_naive": f"{inverse_pnl_naive:+.4f}" if inverse_pnl_naive is not None else "",
            "inverse_pnl_3c_spread": f"{inverse_pnl_3c:+.4f}" if inverse_pnl_3c is not None else "",
            "window_start_price": f"{window_start_price:.6f}" if window_start_price is not None else "",
            "window_end_price": f"{window_end_price:.6f}" if window_end_price is not None else "",
            "actual_won": actual_won,
            "true_pnl": f"{true_pnl:+.4f}" if true_pnl != "" else "",
            "true_inverse_pnl": f"{true_inv_pnl:+.4f}" if true_inv_pnl != "" else "",
        })
        logger.info(
            "Shadow close | sym=%s side=%s token=%s entry=%.3f exit=%.3f pnl=%+.3f type=%s",
            pos["symbol"], pos["side"], token_id, entry, exit_price,
            exit_price - entry, exit_type,
        )
        self.positions.pop(token_id, None)
        self._persist_state()
