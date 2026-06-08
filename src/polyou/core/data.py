"""
polyou.core.data

MarketData event pipeline and oracle event types.
"""

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass
from collections import deque
from typing import Dict, List, Optional, Tuple, Any, Deque, Callable


# --------------------------------------------------
# Events
# --------------------------------------------------

class SpotPriceEvent:
    """
    Oracle spot price event (e.g. Chainlink).
    """
    def __init__(self, *, symbol: str, price: float, ts: Optional[float] = None):
        self.symbol = symbol
        self.price = price
        self.ts = ts if ts is not None else time.time()


# --------------------------------------------------
# Internal structs
# --------------------------------------------------

@dataclass(frozen=True)
class PriceSample:
    ts: float
    price: float


# --------------------------------------------------
# MarketData
# --------------------------------------------------

class MarketData:
    """
    Central in-memory market data store.

    Responsibilities:
    - store spot price replay buffers
    - store oracle anchor prices (time-bucketed windows, e.g. 15m)
    - track price extremes and stability
    - notify listeners on new price events (event-driven architecture)
    """

    def __init__(self, *, replay_size: int = 500):
        self._replay_size = replay_size

        # symbol -> list[SpotPriceEvent]
        self._replay: Dict[str, List[SpotPriceEvent]] = {}

        # (symbol, window_start_ts) -> anchor_price
        self._anchors: Dict[Tuple[str, int], float] = {}

        # --- Stability tracking ---
        self._price_history: Dict[str, Deque[PriceSample]] = {}
        self._last_high: Dict[str, PriceSample] = {}
        self._last_low: Dict[str, PriceSample] = {}
        self._latest_ts: Dict[str, float] = {}
        
        # --- Event-driven architecture ---
        # List of async callbacks to invoke on new price events
        # Each callback receives (symbol: str, event: SpotPriceEvent)
        self._price_listeners: List[Any] = []

    # --------------------------------------------------
    # Event ingestion
    # --------------------------------------------------

    def on_message(self, event: Any) -> None:
        """
        Unified entrypoint for incoming events.
        """

        # --- Spot price events ---
        if isinstance(event, SpotPriceEvent):
            replay = self._replay.setdefault(event.symbol, [])
            replay.append(event)

            if len(replay) > self._replay_size:
                replay.pop(0)

            # --- Stability tracking ---
            history = self._price_history.setdefault(
                event.symbol,
                deque(maxlen=300),
            )

            sample = PriceSample(ts=event.ts, price=event.price)
            history.append(sample)
            self._latest_ts[event.symbol] = event.ts

            last_high = self._last_high.get(event.symbol)
            last_low = self._last_low.get(event.symbol)

            if last_high is None or event.price > last_high.price:
                self._last_high[event.symbol] = sample
            
            # --- Notify listeners (event-driven architecture) ---
            self._notify_price_listeners(event.symbol, event)

            if last_low is None or event.price < last_low.price:
                self._last_low[event.symbol] = sample

            return

        # --- Anchor price events (dict-based, by design) ---
        if isinstance(event, dict) and event.get("type") == "ANCHOR_PRICE":
            symbol = event["symbol"]
            window_start_ts = int(event["window_start_ts"])
            price = float(event["price"])

            self.set_anchor(
                symbol=symbol,
                window_start_ts=window_start_ts,
                price=price,
            )
            return

        # Unknown events are intentionally ignored (fail-safe)
    
    def add_price_listener(self, callback: Callable) -> None:
        """
        Register a callback to be invoked on each new price event.
        Callback signature: async def callback(symbol: str, event: SpotPriceEvent)
        """
        if callback not in self._price_listeners:
            self._price_listeners.append(callback)
    
    def remove_price_listener(self, callback: Callable) -> None:
        """Remove a previously registered price listener."""
        if callback in self._price_listeners:
            self._price_listeners.remove(callback)
    
    def _notify_price_listeners(self, symbol: str, event: SpotPriceEvent) -> None:
        """
        Notify all registered listeners about a new price event.
        Listeners are called synchronously to avoid race conditions.
        """
        for listener in self._price_listeners:
            try:
                # Schedule the callback without waiting (fire-and-forget)
                # This ensures price ingestion doesn't block on slow listeners
                if asyncio.iscoroutinefunction(listener):
                    asyncio.create_task(listener(symbol, event))
                else:
                    listener(symbol, event)
            except Exception as e:
                # Log but don't crash on listener errors
                import logging
                logger = logging.getLogger(__name__)
                logger.exception("Price listener error: %s", e)

    # --------------------------------------------------
    # Replay access
    # --------------------------------------------------

    def get_replay(self, symbol: str) -> List[SpotPriceEvent]:
        """
        Return a defensive copy of spot price history for a symbol.
        """
        return list(self._replay.get(symbol, []))

    def get_latest_spot(self, symbol: str) -> Optional[SpotPriceEvent]:
        """
        Return the most recent spot price event for a symbol.
        """
        replay = self._replay.get(symbol)
        if not replay:
            return None
        return replay[-1]

    def get_replay_size(self, symbol: str) -> int:
        """
        Return number of spot price events stored for a symbol.
        """
        return len(self._replay.get(symbol, []))

    def has_min_replay(self, symbol: str, n: int) -> bool:
        """
        Check whether at least n spot price events exist for a symbol.
        """
        return self.get_replay_size(symbol) >= n

    # --------------------------------------------------
    # Stability gate
    # --------------------------------------------------

    def is_stable(
        self,
        symbol: str,
        *,
        seconds: Optional[int] = 180,
        side: Optional[str] = None,
        since_ts: Optional[float] = None,
    ) -> bool:
        """
        Stability semantics (conservative, layered):

        1) Directional mode (decision-aware):
           - After `since_ts`, price must NOT make a new extreme
             AGAINST the intended settlement direction.

        2) Legacy mode (seconds-based):
           - No new high OR low in the last `seconds`
        """

        # -----------------------------
        # Direction-aware stability
        # -----------------------------
        if side is not None and since_ts is not None:
            replay = self._replay.get(symbol, [])
            if not replay:
                return False

            prices = [
                ev.price
                for ev in replay
                if ev.ts >= since_ts
            ]

            if len(prices) < 3:
                return True # insufficient data to disqualify

            first = prices[0]

            if side == "UP":
                return min(prices) >= first

            if side == "DOWN":
                return max(prices) <= first

            return False # unknown side → fail safe

        # -----------------------------
        # Legacy volatility stability
        # -----------------------------
        if seconds is None:
            return True

        latest_ts = self._latest_ts.get(symbol)
        last_high = self._last_high.get(symbol)
        last_low = self._last_low.get(symbol)

        if latest_ts is None or last_high is None or last_low is None:
            return False

        most_recent_extreme_ts = max(last_high.ts, last_low.ts)
        return (latest_ts - most_recent_extreme_ts) >= seconds

    # --------------------------------------------------
    # Anchor management
    # --------------------------------------------------

    def set_anchor(
        self,
        *,
        symbol: str,
        window_start_ts: int,
        price: float,
    ) -> None:
        """
        Store oracle anchor price for a time-bucketed window (e.g. 15m).
        """
        self._anchors[(symbol, window_start_ts)] = price

    def get_anchor(
        self,
        *,
        symbol: str,
        window_start_ts: int,
    ) -> Optional[float]:
        """
        Retrieve oracle anchor price for a time-bucketed window.
        """
        price = self._anchors.get((symbol, window_start_ts))

        if price is None:
            # Visibility for silent failures (important for 15m systems)
            import logging
            logging.getLogger("polyou.core.data").warning(
                "Missing anchor | symbol=%s window=%s",
                symbol,
                window_start_ts,
            )

        return price

    def get_anchor_windows(self, symbol: str) -> List[int]:
        """
        Return sorted list of window_start_ts values for which anchors exist.
        """
        return sorted(
            ws for (sym, ws) in self._anchors.keys() if sym == symbol
        )
