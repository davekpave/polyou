"""
Replay harness — strategy backtester + live-model calibration gate.

Two responsibilities, one file:

  1. STRATEGY HARNESS (`run_replay`): given a `Strategy` and a daily book
     snapshot file, simulate fills and report P&L. Strategies see a small
     three-callback interface; the fill model is pluggable.

  2. CALIBRATE (`calibrate`): given a date, replay every live shadow exit
     against the recorded book snapshots using the *bit-for-bit live model*
     (`ShadowFillModel`) and assert the harness reproduces what the live bot
     wrote to `shadow_exits.csv`. This is the gate that earns the right to
     trust new-strategy P&L from the harness.

DESIGN NOTES
------------
* Two `FillModel` implementations:
    - `ShadowFillModel`: matches `src/polyou/execution/shadow_book.py` exactly.
      Entry at snapshot_price (no size check, 100% fill). Exit at expiry uses
      `bid >= 0.01 -> max(0, round(bid - 0.01, 4))`, else SETTLED_ZERO after
      a 15-min grace period. This is the ONLY model used by `--calibrate`.
    - `RealisticFillModel`: cross-ask with size check on entry, configurable
      slippage and exit spread. This is the model new strategies should be
      scored under once the shadow model is calibrated.
* The live bot's `settle_expired()` runs on its own loop, reading whatever
  snapshot the tracker last polled. Calibrate therefore locates the tick
  *closest to and ≤ the recorded exit_ts* and applies settle logic to that
  tick — that mirrors what live actually saw at the moment it decided to
  close.

USAGE
-----
    python scripts/replay.py --date 2026-05-07 --calibrate
    python scripts/replay.py --date 2026-05-07 --strategy fade
    python scripts/replay.py --date 2026-05-07 --strategy fade --model shadow
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple


# --------------------------------------------------
# Paths
# --------------------------------------------------

LOG_DIR = "logs"
SHADOW_EXITS_PATH = os.path.join(LOG_DIR, "shadow_exits.csv")


# --------------------------------------------------
# Data model
# --------------------------------------------------

@dataclass(frozen=True)
class BookTick:
    """One row from book_snapshots_YYYYMMDD.csv, one token."""
    ts_epoch: float
    ts_iso: str
    symbol: str
    side: str                 # "YES" or "NO"
    window_start_ts: int
    token_id: str
    best_ask: Optional[float]
    best_bid: Optional[float]
    best_ask_size: Optional[float]
    best_bid_size: Optional[float]
    top_asks: List[Tuple[float, float]] = field(default_factory=list)
    top_bids: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class MarketSnapshot:
    """Both legs of a single 15-min market at a single instant."""
    ts_epoch: float
    symbol: str
    window_start_ts: int
    yes: Optional[BookTick]
    no: Optional[BookTick]


@dataclass
class Position:
    position_id: str
    symbol: str
    side: str                 # "YES" or "NO"
    token_id: str
    window_start_ts: int
    entry_ts: float
    entry_price: float
    size: float


@dataclass
class ClosedTrade:
    position: Position
    exit_ts: float
    exit_price: float
    exit_type: str            # "EXPIRY_BID", "SETTLED_ZERO", "STRATEGY_EXIT"
    pnl: float


# --------------------------------------------------
# Fill models
# --------------------------------------------------

WINDOW_SECONDS = 15 * 60


class FillModel:
    """Abstract base. Strategies see one interface; harness picks impl."""

    grace_seconds: int = 0  # how long past window_end to wait before SETTLED_ZERO

    def entry_price(self, leg: BookTick, requested_size: float) -> Optional[float]:
        raise NotImplementedError

    def exit_price_strategy(self, leg: BookTick) -> Optional[float]:
        """Mid-window discretionary exit. None if not supported / no liquidity."""
        raise NotImplementedError

    def exit_at_window(self, last_leg: Optional[BookTick],
                       seconds_past_window_end: float
                       ) -> Optional[Tuple[float, str]]:
        """
        Return (exit_price, exit_type) when the position should settle, or
        None to keep waiting (still inside grace period with no bid).
        """
        raise NotImplementedError


class ShadowFillModel(FillModel):
    """
    Bit-for-bit reproduction of src/polyou/execution/shadow_book.py.

    Live behavior we mirror:
      * Entry: entry_price = snapshot_price (= leg.best_ask at decision).
        No size check, no rejection. 100% fill assumed.
      * No mid-window exits (live shadow book has none in READ_ONLY mode).
      * Window-end (settle_expired):
          if best_bid is not None and best_bid >= 0.01:
              exit_price = max(0.0, round(best_bid - 0.01, 4))
              exit_type  = EXPIRY_BID
          elif (now - window_end_ts) > 15min:
              exit_price = 0.0
              exit_type  = SETTLED_ZERO
          else:
              keep waiting.
    """
    grace_seconds = 15 * 60

    def entry_price(self, leg: BookTick, requested_size: float) -> Optional[float]:
        if leg is None or leg.best_ask is None:
            return None
        return leg.best_ask

    def exit_price_strategy(self, leg: BookTick) -> Optional[float]:
        # Live shadow book has no mid-window exits.
        return None

    def exit_at_window(self, last_leg: Optional[BookTick],
                       seconds_past_window_end: float
                       ) -> Optional[Tuple[float, str]]:
        bid = last_leg.best_bid if last_leg is not None else None
        if bid is not None and bid >= 0.01:
            return (max(0.0, round(bid - 0.01, 4)), "EXPIRY_BID")
        if seconds_past_window_end > self.grace_seconds:
            return (0.0, "SETTLED_ZERO")
        return None


class RealisticFillModel(FillModel):
    """
    Conservative model for new-strategy research.

      * Entry: cross ask. Refuse if best_ask_size < requested or ask >= 1.0.
        Optional fill_slippage added to the ask.
      * Strategy exits: cross bid minus exit_spread.
      * Window-end: cross bid (any positive value) minus exit_spread; else $0
        immediately. No grace.
    """
    grace_seconds = 0

    def __init__(self, *, fill_slippage: float = 0.0,
                 exit_spread: float = 0.0):
        self.fill_slippage = fill_slippage
        self.exit_spread = exit_spread

    def entry_price(self, leg: BookTick, requested_size: float) -> Optional[float]:
        if leg is None or leg.best_ask is None:
            return None
        if leg.best_ask_size is not None and leg.best_ask_size < requested_size:
            return None
        price = leg.best_ask + self.fill_slippage
        if price >= 1.0:
            return None
        return price

    def exit_price_strategy(self, leg: BookTick) -> Optional[float]:
        if leg is None or leg.best_bid is None:
            return None
        return leg.best_bid - self.exit_spread

    def exit_at_window(self, last_leg: Optional[BookTick],
                       seconds_past_window_end: float
                       ) -> Optional[Tuple[float, str]]:
        bid = last_leg.best_bid if last_leg is not None else None
        if bid is not None and bid > 0:
            return (max(0.0, bid - self.exit_spread), "EXPIRY_BID")
        return (0.0, "SETTLED_ZERO")


# --------------------------------------------------
# Strategy interface
# --------------------------------------------------

class Strategy:
    """
    Subclass and override callbacks.

    Harness guarantees:
      - on_tick called in strict ts_epoch order.
      - on_market_close called once per (symbol, window_start_ts), after
        positions in that window have been settled.
      - submit_entry / submit_exit return immediately (synchronous fills).
    """

    name: str = "base"

    def on_tick(self, snap: MarketSnapshot, ctx: "ReplayContext") -> None:
        pass

    def on_market_close(self, symbol: str, window_start_ts: int,
                        ctx: "ReplayContext") -> None:
        pass


# --------------------------------------------------
# Replay context
# --------------------------------------------------

class ReplayContext:
    """Strategies call submit_entry/submit_exit; harness handles fills + P&L."""

    def __init__(self, fill_model: FillModel):
        self.fill_model = fill_model
        self._next_id = 0
        self.open: Dict[str, Position] = {}
        self.closed: List[ClosedTrade] = []

    def _new_id(self) -> str:
        self._next_id += 1
        return f"replay-{self._next_id}"

    # ---------- strategy-facing API ----------

    def submit_entry(self, leg: BookTick, *, size: float = 1.0,
                     ts_epoch: Optional[float] = None) -> Optional[Position]:
        price = self.fill_model.entry_price(leg, size)
        if price is None or leg is None:
            return None
        pos = Position(
            position_id=self._new_id(),
            symbol=leg.symbol,
            side=leg.side,
            token_id=leg.token_id,
            window_start_ts=leg.window_start_ts,
            entry_ts=ts_epoch if ts_epoch is not None else leg.ts_epoch,
            entry_price=price,
            size=size,
        )
        self.open[pos.position_id] = pos
        return pos

    def submit_exit(self, position: Position, leg: BookTick,
                    *, ts_epoch: Optional[float] = None
                    ) -> Optional[ClosedTrade]:
        if position.position_id not in self.open:
            return None
        price = self.fill_model.exit_price_strategy(leg)
        if price is None:
            return None
        return self._record_close(
            position, exit_price=price, exit_type="STRATEGY_EXIT",
            exit_ts=ts_epoch if ts_epoch is not None else leg.ts_epoch,
        )

    # ---------- harness-facing helpers ----------

    def _record_close(self, position: Position, *, exit_price: float,
                      exit_type: str, exit_ts: float) -> ClosedTrade:
        del self.open[position.position_id]
        trade = ClosedTrade(
            position=position,
            exit_ts=exit_ts,
            exit_price=exit_price,
            exit_type=exit_type,
            pnl=(exit_price - position.entry_price) * position.size,
        )
        self.closed.append(trade)
        return trade

    def try_settle(self, position: Position, leg: Optional[BookTick],
                   ts_epoch: float) -> Optional[ClosedTrade]:
        """Called per-tick by run_replay; respects the model's grace logic."""
        seconds_past = ts_epoch - (position.window_start_ts + WINDOW_SECONDS)
        if seconds_past < 0:
            return None
        result = self.fill_model.exit_at_window(leg, seconds_past)
        if result is None:
            return None
        exit_price, exit_type = result
        return self._record_close(
            position, exit_price=exit_price, exit_type=exit_type,
            exit_ts=ts_epoch,
        )


# --------------------------------------------------
# Loaders
# --------------------------------------------------

def _market_key(symbol: str, window_start_ts: int) -> str:
    return f"{symbol}:{window_start_ts}"


def _parse_levels(raw: str) -> List[Tuple[float, float]]:
    if not raw:
        return []
    try:
        levels = json.loads(raw)
        return [(float(p), float(s)) for p, s in levels]
    except Exception:
        return []


def _parse_float(raw: str) -> Optional[float]:
    if raw == "" or raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_book_snapshots(path: str) -> Iterable[BookTick]:
    """Stream BookTick rows from a single daily snapshot file."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield BookTick(
                ts_epoch=float(row["ts_epoch"]),
                ts_iso=row["ts_iso"],
                symbol=row["symbol"],
                side=row["side"],
                window_start_ts=int(row["window_start_ts"]),
                token_id=row["token_id"],
                best_ask=_parse_float(row["best_ask"]),
                best_bid=_parse_float(row["best_bid"]),
                best_ask_size=_parse_float(row["best_ask_size"]),
                best_bid_size=_parse_float(row["best_bid_size"]),
                top_asks=_parse_levels(row.get("top5_asks", "")),
                top_bids=_parse_levels(row.get("top5_bids", "")),
            )


def assemble_market_snapshots(ticks: Iterable[BookTick]
                              ) -> Iterable[MarketSnapshot]:
    """
    Pair YES/NO ticks into MarketSnapshots. Each incoming tick yields one
    snapshot using the most recent YES + NO seen for that
    (symbol, window_start_ts). Mirrors the staleness the live bot saw.
    """
    latest: Dict[Tuple[str, int, str], BookTick] = {}
    for tick in ticks:
        latest[(tick.symbol, tick.window_start_ts, tick.side)] = tick
        yield MarketSnapshot(
            ts_epoch=tick.ts_epoch,
            symbol=tick.symbol,
            window_start_ts=tick.window_start_ts,
            yes=latest.get((tick.symbol, tick.window_start_ts, "YES")),
            no=latest.get((tick.symbol, tick.window_start_ts, "NO")),
        )


# --------------------------------------------------
# Replay loop
# --------------------------------------------------

def run_replay(snapshot_path: str, strategy: Strategy,
               *, fill_model: Optional[FillModel] = None
               ) -> Tuple[ReplayContext, Dict[str, MarketSnapshot]]:
    if fill_model is None:
        fill_model = RealisticFillModel()
    ctx = ReplayContext(fill_model)
    last_seen: Dict[str, MarketSnapshot] = {}
    closed_markets: set = set()

    for snap in assemble_market_snapshots(load_book_snapshots(snapshot_path)):
        key = _market_key(snap.symbol, snap.window_start_ts)
        last_seen[key] = snap

        # 1) Try to settle any open positions in this market past window_end.
        for pid in list(ctx.open.keys()):
            pos = ctx.open[pid]
            if pos.symbol != snap.symbol or pos.window_start_ts != snap.window_start_ts:
                continue
            leg = snap.yes if pos.side == "YES" else snap.no
            ctx.try_settle(pos, leg, snap.ts_epoch)

        # 2) Notify strategy of market close exactly once.
        if (key not in closed_markets
                and snap.ts_epoch >= snap.window_start_ts + WINDOW_SECONDS):
            strategy.on_market_close(snap.symbol, snap.window_start_ts, ctx)
            closed_markets.add(key)

        # 3) Always give strategy a chance to act on the tick.
        strategy.on_tick(snap, ctx)

    # End-of-file flush: force-close anything still open with infinite past-grace.
    for pid in list(ctx.open.keys()):
        pos = ctx.open[pid]
        snap = last_seen.get(_market_key(pos.symbol, pos.window_start_ts))
        leg = (snap.yes if pos.side == "YES" else snap.no) if snap else None
        result = fill_model.exit_at_window(leg, fill_model.grace_seconds + 1)
        if result is None:
            result = (0.0, "SETTLED_ZERO")
        exit_price, exit_type = result
        ctx._record_close(
            pos, exit_price=exit_price, exit_type=exit_type,
            exit_ts=snap.ts_epoch if snap else pos.entry_ts,
        )

    return ctx, last_seen


# --------------------------------------------------
# Sample strategies
# --------------------------------------------------

class NoopStrategy(Strategy):
    name = "noop"


class FadeStrategy(Strategy):
    """
    Placeholder. Buys NO whenever YES_ask is in [enter_lo, enter_hi] and we
    have no open position in this window. Real fade research will replace
    this once `--calibrate` passes.
    """
    name = "fade"

    def __init__(self, enter_lo: float = 0.70, enter_hi: float = 0.95):
        self.enter_lo = enter_lo
        self.enter_hi = enter_hi
        self._opened: set = set()

    def on_tick(self, snap: MarketSnapshot, ctx: ReplayContext) -> None:
        key = _market_key(snap.symbol, snap.window_start_ts)
        if key in self._opened:
            return
        if snap.yes is None or snap.yes.best_ask is None:
            return
        if not (self.enter_lo <= snap.yes.best_ask <= self.enter_hi):
            return
        if snap.no is None:
            return
        pos = ctx.submit_entry(snap.no, size=1.0, ts_epoch=snap.ts_epoch)
        if pos is not None:
            self._opened.add(key)


STRATEGIES: Dict[str, Callable[[], Strategy]] = {
    "noop": NoopStrategy,
    "fade": FadeStrategy,
}

FILL_MODELS: Dict[str, Callable[[], FillModel]] = {
    "shadow": ShadowFillModel,
    "realistic": RealisticFillModel,
}


# --------------------------------------------------
# Reporting (strategy mode)
# --------------------------------------------------

def summarize(ctx: ReplayContext) -> str:
    n = len(ctx.closed)
    if n == 0:
        return "no closed trades"
    wins = sum(1 for t in ctx.closed if t.pnl > 0)
    total = sum(t.pnl for t in ctx.closed)
    return (f"n={n}  WR={wins / n:.1%}  total_pnl={total:+.2f}  "
            f"avg={total / n:+.4f}")


# --------------------------------------------------
# Calibrate
# --------------------------------------------------

CALIBRATE_TICK_TOLERANCE_S = 30.0
CALIBRATE_PRICE_TOLERANCE = 0.0001


def calibrate(date_str: str) -> int:
    """
    Verify the replay harness reproduces live shadow exits exactly.

    For each row in shadow_exits.csv whose exit fell on `date_str` (UTC):
      1. Try to locate a fresh book tick for the token (within
         CALIBRATE_TICK_TOLERANCE_S seconds of the recorded exit_ts AND
         ≤ exit_ts).
            - If found: apply ShadowFillModel.exit_at_window(tick, ...).
            - If not found: simulate with last_leg=None — this mirrors what
              live saw, because clob_book_tracker drops tokens from cache
              after their market closes, so the live _book() returned
              bid=None and SETTLED_ZERO fired.
      2. Compare simulated (exit_price, exit_type) to recorded values.
         Match must be exact: identical exit_type AND
         |Δ price| < CALIBRATE_PRICE_TOLERANCE.

    A trade is only "unreplayable" if we have no book data for the token at
    all on this date (full instrumentation gap, distinct from "stale").

    Prints a per-trade summary; lists worst mismatches; returns 0 on full
    pass, 1 on any mismatch.
    """
    book_path = _date_to_path(date_str)
    if not os.path.isfile(book_path):
        raise SystemExit(f"book snapshots not found: {book_path}")
    if not os.path.isfile(SHADOW_EXITS_PATH):
        raise SystemExit(f"shadow exits not found: {SHADOW_EXITS_PATH}")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Load shadow exits whose exit happened on the target UTC date.
    exits: List[dict] = []
    with open(SHADOW_EXITS_PATH, newline="") as f:
        for row in csv.DictReader(f):
            ts_iso = row.get("ts_iso", "")
            try:
                exit_dt = datetime.fromisoformat(
                    ts_iso.replace("Z", "+00:00"))
            except Exception:
                continue
            if exit_dt.astimezone(timezone.utc).date() == target_date:
                exits.append(row)

    if not exits:
        print(f"calibrate {date_str}: no shadow_exits rows on this date")
        return 0

    # Index book ticks by token, sorted by ts_epoch.
    by_token: Dict[str, List[BookTick]] = {}
    for tick in load_book_snapshots(book_path):
        by_token.setdefault(tick.token_id, []).append(tick)
    for ticks in by_token.values():
        ticks.sort(key=lambda t: t.ts_epoch)

    model = ShadowFillModel()

    n_total = len(exits)
    n_unreplayable_no_book = 0
    n_match = 0
    n_match_stale_to_none = 0
    n_mismatch_type = 0
    n_mismatch_price = 0
    n_mismatch_keep_waiting = 0
    mismatches: List[dict] = []

    for row in exits:
        token_id = row.get("token_id", "")
        try:
            window_end = int(float(row["window_end_ts"]))
            exit_ts = float(row["exit_ts"])
            recorded_price = float(row["exit_price"])
            recorded_type = row["exit_type"]
        except (KeyError, ValueError):
            n_unreplayable_no_book += 1
            continue

        ticks = by_token.get(token_id, [])
        if not ticks:
            n_unreplayable_no_book += 1
            continue

        # Find the latest tick at or before exit_ts.
        candidates = [t for t in ticks if t.ts_epoch <= exit_ts]
        closest: Optional[BookTick] = None
        staleness = float("inf")
        used_stale_as_none = False
        if candidates:
            picked = max(candidates, key=lambda t: t.ts_epoch)
            staleness = exit_ts - picked.ts_epoch
            if staleness <= CALIBRATE_TICK_TOLERANCE_S:
                closest = picked

        # If we have no fresh tick, simulate as the live tracker did:
        # bid=None (cached snapshot was dropped after market close).
        if closest is None:
            used_stale_as_none = True

        # shadow_exits.csv stores exit_ts rounded to the second (f"{now:.0f}"),
        # so the recorded value is on average 0.5s earlier than the actual
        # live `now`. Compensate so boundary cases like seconds_past==900
        # behave the way live did.
        seconds_past = (exit_ts - window_end) + 0.5
        result = model.exit_at_window(closest, seconds_past)

        if result is None:
            n_mismatch_keep_waiting += 1
            mismatches.append({
                "token_id": token_id,
                "symbol": row.get("symbol", ""),
                "side": row.get("side", ""),
                "window_end_ts": window_end,
                "exit_ts": exit_ts,
                "staleness_s": staleness,
                "tick_bid": closest.best_bid if closest else None,
                "seconds_past": seconds_past,
                "recorded_type": recorded_type,
                "recorded_price": recorded_price,
                "sim_type": "WAIT",
                "sim_price": None,
                "delta": None,
                "fresh_tick": not used_stale_as_none,
            })
            continue

        sim_price, sim_type = result
        type_match = sim_type == recorded_type
        price_match = abs(sim_price - recorded_price) < CALIBRATE_PRICE_TOLERANCE
        if type_match and price_match:
            n_match += 1
            if used_stale_as_none:
                n_match_stale_to_none += 1
            continue

        if not type_match:
            n_mismatch_type += 1
        else:
            n_mismatch_price += 1
        mismatches.append({
            "token_id": token_id,
            "symbol": row.get("symbol", ""),
            "side": row.get("side", ""),
            "window_end_ts": window_end,
            "exit_ts": exit_ts,
            "staleness_s": staleness,
            "tick_bid": closest.best_bid if closest else None,
            "seconds_past": seconds_past,
            "recorded_type": recorded_type,
            "recorded_price": recorded_price,
            "sim_type": sim_type,
            "sim_price": sim_price,
            "delta": sim_price - recorded_price,
            "fresh_tick": not used_stale_as_none,
        })

    replayable = n_total - n_unreplayable_no_book
    n_mismatch = n_mismatch_type + n_mismatch_price + n_mismatch_keep_waiting

    print(f"\ncalibrate {date_str}")
    print(f"  shadow exits on date:           {n_total}")
    print(f"  unreplayable (no book for tok): {n_unreplayable_no_book}")
    print(f"  replayable:                     {replayable}")
    if replayable:
        rate = n_match / replayable
        n_match_fresh = n_match - n_match_stale_to_none
        print(f"    exact match:                  {n_match}  ({rate:.1%})")
        print(f"      from fresh tick:            {n_match_fresh}")
        print(f"      from stale->None (live had "
              f"bid=None too):  {n_match_stale_to_none}")
        if n_mismatch_type:
            print(f"    mismatch (exit_type):         {n_mismatch_type}")
        if n_mismatch_price:
            print(f"    mismatch (price only):        {n_mismatch_price}")
        if n_mismatch_keep_waiting:
            print(f"    mismatch (model said WAIT):   "
                  f"{n_mismatch_keep_waiting}")

    if mismatches:
        print(f"\n  worst mismatches (up to 10):")

        def _mag(m: dict) -> float:
            return abs(m["delta"]) if m["delta"] is not None else float("inf")

        for m in sorted(mismatches, key=_mag, reverse=True)[:10]:
            delta_s = (f"Δ=${m['delta']:+.4f}"
                       if m["delta"] is not None else "Δ=N/A")
            sim_price_s = (f"${m['sim_price']:.4f}"
                           if m["sim_price"] is not None else "—")
            print(
                f"    {m['symbol']:8s} {m['side']:3s} "
                f"we={m['window_end_ts']} "
                f"recorded={m['recorded_type']:12s} "
                f"${m['recorded_price']:.4f}  "
                f"sim={m['sim_type']:12s} {sim_price_s}  "
                f"{delta_s}  "
                f"tick_bid={m['tick_bid']}  "
                f"stale={m['staleness_s']:.1f}s  "
                f"past={m['seconds_past']:.0f}s")

    if n_mismatch > 0:
        print(f"\nFAIL — {n_mismatch} mismatch(es). "
              f"Harness does not reproduce live exits.")
        return 1
    if replayable == 0:
        print(f"\nINCONCLUSIVE — 0 replayable trades. Need book + exit data "
              f"on the same date.")
        return 1
    print(f"\nPASS — all {replayable} replayable exits matched live within "
          f"${CALIBRATE_PRICE_TOLERANCE:.4f}.")
    return 0


# --------------------------------------------------
# Inverse-fade comparison (Option C)
# --------------------------------------------------

# How close the entry-side opposite-leg tick must be to the bot's recorded
# entry_ts (in seconds). Wider than the calibrate exit tolerance because
# entries fire on the bot's own decision loop and the opposite leg may not
# refresh on the same tick.
INVERSE_ENTRY_TICK_TOLERANCE_S = 10.0


def compare_inverse_fade(date_str: str, *, fill_slippage: float = 0.0) -> int:
    """
    Option C: replay the bot's actual trades through a realistic fill model
    on the OPPOSITE side and compare to the `inverse_pnl_naive` column in
    shadow_exits.csv.

    Per shadow_exits row on `date_str`:
      1. Identify the opposite leg (side != bot side, same symbol +
         window_end_ts → window_start_ts).
      2. Find the opposite-leg tick within INVERSE_ENTRY_TICK_TOLERANCE_S
         of entry_ts. Apply RealisticFillModel.entry_price(size=1.0).
         No fill (insufficient size, no ask, ask>=1.0) → unfillable.
      3. Find the opposite-leg tick at or before recorded exit_ts; if
         staleness > CALIBRATE_TICK_TOLERANCE_S use last_leg=None (mirrors
         live cache drop, identical convention to calibrate()). Apply
         ShadowFillModel.exit_at_window with the bot's actual past-grace
         delta (seconds_past = exit_ts - window_end + 0.5).
      4. realistic_fade_pnl = exit_price - entry_price. Compare to the
         row's inverse_pnl_naive.

    Outputs: fill rate, mean Δ entry vs (1 - YES_ask), total realistic
    P&L vs total naive P&L, per-symbol breakdown.

    Returns 0 always (this is research, not a gate).
    """
    book_path = _date_to_path(date_str)
    if not os.path.isfile(book_path):
        raise SystemExit(f"book snapshots not found: {book_path}")
    if not os.path.isfile(SHADOW_EXITS_PATH):
        raise SystemExit(f"shadow exits not found: {SHADOW_EXITS_PATH}")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    rows: List[dict] = []
    with open(SHADOW_EXITS_PATH, newline="") as f:
        for row in csv.DictReader(f):
            ts_iso = row.get("ts_iso", "")
            try:
                exit_dt = datetime.fromisoformat(
                    ts_iso.replace("Z", "+00:00"))
            except Exception:
                continue
            if exit_dt.astimezone(timezone.utc).date() == target_date:
                rows.append(row)

    if not rows:
        print(f"compare-inverse-fade {date_str}: no shadow_exits on this date")
        return 0

    # Index ticks by (symbol, window_start_ts, side), sorted by ts_epoch.
    by_leg: Dict[Tuple[str, int, str], List[BookTick]] = {}
    for tick in load_book_snapshots(book_path):
        by_leg.setdefault(
            (tick.symbol, tick.window_start_ts, tick.side), []
        ).append(tick)
    for ticks in by_leg.values():
        ticks.sort(key=lambda t: t.ts_epoch)

    entry_model = RealisticFillModel(fill_slippage=fill_slippage)
    exit_model = ShadowFillModel()

    @dataclass
    class _Result:
        symbol: str
        side_traded: str
        opp_side: str
        entry_ts: float
        bot_entry: float        # original snapshot_price (YES_ask if bot bought YES)
        opp_entry: Optional[float]   # opposite-leg ask at entry_ts (None=unfillable)
        opp_exit: Optional[float]    # exit price for opposite leg (None=skipped)
        opp_exit_type: Optional[str]
        realistic_pnl: Optional[float]
        naive_pnl: float        # inverse_pnl_naive from shadow_exits
        unfillable_reason: str = ""

    results: List[_Result] = []

    for row in rows:
        try:
            symbol = row["symbol"]
            side = row["side"]
            entry_ts = float(row["entry_ts"])
            exit_ts = float(row["exit_ts"])
            window_end = int(float(row["window_end_ts"]))
            bot_entry = float(row["entry_price"])
            naive = float(row["inverse_pnl_naive"])
        except (KeyError, ValueError):
            continue

        opp_side = "NO" if side in ("UP", "YES") else "YES"
        # Bot side strings vary: shadow_exits uses UP/DOWN (the market label),
        # but tracker tags ticks "YES" / "NO". UP corresponds to YES of the
        # up-side market; DOWN corresponds to YES of the down-side market.
        # In practice both legs are stored under YES/NO of the same token
        # pair, so the opposite of whatever the bot bought is the other
        # YES/NO label. Handle the canonical case:
        #   bot bought UP/YES → we'd buy NO of same window
        #   bot bought DOWN/NO → we'd buy YES
        if side in ("UP", "YES"):
            opp_side = "NO"
        elif side in ("DOWN", "NO"):
            opp_side = "YES"
        else:
            opp_side = "NO"

        window_start = window_end - WINDOW_SECONDS
        opp_ticks = by_leg.get((symbol, window_start, opp_side), [])

        # ---- Entry: realistic fill on opposite leg ----
        opp_entry: Optional[float] = None
        unfillable_reason = ""
        if not opp_ticks:
            unfillable_reason = "no_opposite_book"
        else:
            # Closest tick within tolerance of entry_ts (either side).
            best = min(opp_ticks, key=lambda t: abs(t.ts_epoch - entry_ts))
            if abs(best.ts_epoch - entry_ts) > INVERSE_ENTRY_TICK_TOLERANCE_S:
                unfillable_reason = "stale_entry_book"
            else:
                price = entry_model.entry_price(best, requested_size=1.0)
                if price is None:
                    if best.best_ask is None:
                        unfillable_reason = "no_ask"
                    elif best.best_ask >= 1.0:
                        unfillable_reason = "ask_at_one"
                    else:
                        unfillable_reason = "size_too_small"
                else:
                    opp_entry = price

        # ---- Exit: shadow model on opposite leg, evaluated on the
        # OPPOSITE leg's own timing (NOT the bot's exit_ts). The bot's
        # exit_ts is determined by when *its* leg triggered EXPIRY_BID or
        # SETTLED_ZERO; the opposite leg fires independently. We scan its
        # ticks from window_end forward and apply ShadowFillModel rules:
        # first tick with bid >= 0.01 → EXPIRY_BID; else after 15-min grace
        # → SETTLED_ZERO. ----
        opp_exit: Optional[float] = None
        opp_exit_type: Optional[str] = None
        if opp_entry is not None:
            # Ticks at or after window_end, in chronological order.
            post_close = [t for t in opp_ticks
                          if t.ts_epoch >= window_end]
            picked_exit_ts = exit_ts  # fallback for reporting only
            for t in post_close:
                seconds_past = (t.ts_epoch - window_end) + 0.5
                res = exit_model.exit_at_window(t, seconds_past)
                if res is not None:
                    opp_exit, opp_exit_type = res
                    picked_exit_ts = t.ts_epoch
                    break
            if opp_exit is None:
                # Cache drop / no tick after window_end. Mirror live: bid=None
                # past grace → SETTLED_ZERO.
                res = exit_model.exit_at_window(
                    None, exit_model.grace_seconds + 1.0
                )
                opp_exit, opp_exit_type = (
                    res if res is not None else (0.0, "SETTLED_ZERO")
                )
                picked_exit_ts = window_end + exit_model.grace_seconds

        realistic_pnl = (
            (opp_exit - opp_entry)
            if (opp_entry is not None and opp_exit is not None)
            else None
        )
        results.append(_Result(
            symbol=symbol,
            side_traded=side,
            opp_side=opp_side,
            entry_ts=entry_ts,
            bot_entry=bot_entry,
            opp_entry=opp_entry,
            opp_exit=opp_exit,
            opp_exit_type=opp_exit_type,
            realistic_pnl=realistic_pnl,
            naive_pnl=naive,
            unfillable_reason=unfillable_reason,
        ))

    n_total = len(results)
    n_filled = sum(1 for r in results if r.realistic_pnl is not None)
    fill_rate = n_filled / n_total if n_total else 0.0

    # Mean Δ entry: realistic_no_ask − (1 − bot_entry) = opp_entry − (1 − bot_entry)
    # Positive = realistic entry costs more than the naive (1 − YES_ask)
    # assumption ⇒ inverse_pnl_naive overstates edge.
    deltas = [
        r.opp_entry - (1.0 - r.bot_entry)
        for r in results
        if r.opp_entry is not None
    ]
    mean_delta_entry = sum(deltas) / len(deltas) if deltas else 0.0

    total_realistic = sum(r.realistic_pnl for r in results
                          if r.realistic_pnl is not None)
    # For apples-to-apples, restrict naive sum to the SAME filled rows.
    total_naive_filled = sum(r.naive_pnl for r in results
                             if r.realistic_pnl is not None)
    total_naive_all = sum(r.naive_pnl for r in results)

    wr_realistic = (
        sum(1 for r in results if r.realistic_pnl is not None
            and r.realistic_pnl > 0) / n_filled
        if n_filled else 0.0
    )
    wr_naive_filled = (
        sum(1 for r in results if r.realistic_pnl is not None
            and r.naive_pnl > 0) / n_filled
        if n_filled else 0.0
    )

    print(f"\ncompare-inverse-fade  date={date_str}  "
          f"slippage={fill_slippage:+.4f}")
    print(f"  shadow_exits rows on date:    {n_total}")
    print(f"  filled (opposite leg):        {n_filled}  "
          f"({fill_rate:.1%})")

    # Unfillable breakdown
    reasons: Dict[str, int] = {}
    for r in results:
        if r.realistic_pnl is None:
            reasons[r.unfillable_reason or "unknown"] = (
                reasons.get(r.unfillable_reason or "unknown", 0) + 1
            )
    if reasons:
        print(f"  unfillable reasons:")
        for reason, count in sorted(reasons.items(),
                                    key=lambda kv: -kv[1]):
            print(f"    {reason:24s} {count}")

    print(f"\n  mean Δ entry  (realistic − (1 − YES_ask)):  "
          f"{mean_delta_entry:+.4f}")
    print(f"\n  TOTAL P&L  (filled rows only, n={n_filled}):")
    print(f"    realistic fade:             {total_realistic:+8.2f}")
    print(f"    naive (inverse_pnl_naive):  {total_naive_filled:+8.2f}")
    print(f"    Δ (realistic − naive):      "
          f"{total_realistic - total_naive_filled:+8.2f}")
    print(f"  WR realistic = {wr_realistic:.1%}   "
          f"WR naive (same rows) = {wr_naive_filled:.1%}")
    print(f"\n  (reference) total naive on ALL rows incl. unfilled: "
          f"{total_naive_all:+.2f}")

    # Per-symbol breakdown
    print(f"\n  per-symbol (filled rows):")
    sym_keys = sorted({r.symbol for r in results
                       if r.realistic_pnl is not None})
    print(f"    {'symbol':10s} {'n':>4s}  {'real':>8s}  {'naive':>8s}  "
          f"{'Δ':>8s}  {'mean Δentry':>12s}")
    for sym in sym_keys:
        sym_rows = [r for r in results
                    if r.symbol == sym and r.realistic_pnl is not None]
        n_s = len(sym_rows)
        r_s = sum(r.realistic_pnl for r in sym_rows)
        n_s_naive = sum(r.naive_pnl for r in sym_rows)
        d_entry = sum(
            r.opp_entry - (1.0 - r.bot_entry) for r in sym_rows
        ) / n_s
        print(f"    {sym:10s} {n_s:>4d}  {r_s:+8.2f}  {n_s_naive:+8.2f}  "
              f"{r_s - n_s_naive:+8.2f}  {d_entry:+12.4f}")

    return 0


# --------------------------------------------------
# CLI
# --------------------------------------------------

def _date_to_path(date_str: str) -> str:
    """YYYY-MM-DD -> logs/book_snapshots_YYYYMMDD.csv"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return os.path.join(LOG_DIR, f"book_snapshots_{dt.strftime('%Y%m%d')}.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay harness")
    parser.add_argument("--date", required=True,
                        help="YYYY-MM-DD (UTC) of the snapshot file")
    parser.add_argument("--strategy", default="noop",
                        choices=sorted(STRATEGIES.keys()))
    parser.add_argument("--model", default="realistic",
                        choices=sorted(FILL_MODELS.keys()),
                        help="fill model for strategy mode (ignored by "
                             "--calibrate, which always uses shadow)")
    parser.add_argument("--fill-slippage", type=float, default=0.0,
                        help="extra cents added to ask on entry "
                             "(realistic model only)")
    parser.add_argument("--exit-spread", type=float, default=0.0,
                        help="cents subtracted from bid on exit "
                             "(realistic model only)")
    parser.add_argument("--calibrate", action="store_true",
                        help="verify harness reproduces live shadow exits")
    parser.add_argument("--compare-inverse-fade", action="store_true",
                        help="replay bot trades through realistic fill on "
                             "the opposite leg; compare to inverse_pnl_naive")
    args = parser.parse_args()

    if args.calibrate:
        raise SystemExit(calibrate(args.date))

    if args.compare_inverse_fade:
        raise SystemExit(compare_inverse_fade(
            args.date, fill_slippage=args.fill_slippage))

    path = _date_to_path(args.date)
    if not os.path.isfile(path):
        raise SystemExit(f"snapshot file not found: {path}")

    if args.model == "realistic":
        model: FillModel = RealisticFillModel(
            fill_slippage=args.fill_slippage,
            exit_spread=args.exit_spread,
        )
    else:
        model = ShadowFillModel()

    strategy = STRATEGIES[args.strategy]()
    print(f"replay  date={args.date}  strategy={strategy.name}  "
          f"model={args.model}  file={path}")
    ctx, _ = run_replay(path, strategy, fill_model=model)
    print(summarize(ctx))


if __name__ == "__main__":
    main()
