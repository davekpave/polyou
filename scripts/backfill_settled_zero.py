"""Backfill SETTLED_ZERO rows into logs/exit_log.csv from bot.log history.

Scans bot.log for "Position <token_id> dropped from local tracking" events
(date >= 2026-04-24, the hold-to-expiry era), looks back to find the most
recent BUY EXECUTED line for the same token to recover entry_price, and
appends a SETTLED_ZERO row to exit_log.csv if one isn't already there.

Idempotent: skips token_ids that already have a SETTLED_ZERO row.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_LOG = ROOT / "logs" / "bot.log"
EXIT_LOG = ROOT / "logs" / "exit_log.csv"

CUTOVER_TS = dt.datetime(2026, 4, 24, 0, 0, 0).timestamp()

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
EXEC_RE = re.compile(
    r"EXECUTED \| (\d+) \| side=(\w+) price=([\d.]+) size=([\d.]+) "
    r"notional=([\d.]+) status=(\w+)"
)
DROP_RE = re.compile(r"Position (\d+) dropped from local tracking")


def parse_ts(line: str) -> float | None:
    m = TS_RE.match(line)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return None


def main():
    # 1. Load existing exit_log to know which tokens are already covered.
    existing_settled = set()
    existing_rows = []
    if EXIT_LOG.exists():
        with EXIT_LOG.open(encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                existing_rows.append(r)
                if r.get("type") == "SETTLED_ZERO":
                    existing_settled.add(r["token_id"])

    # 2. Single pass over bot.log: track the latest BUY EXECUTED entry_price
    #    per token, and emit a SETTLED_ZERO whenever we see a "dropped" event.
    last_buy: dict[str, tuple[float, float]] = {}  # token_id -> (entry_price, ts)
    new_rows = []  # rows to append
    seen_drops = set()  # token_ids we've already backfilled in this run

    with BOT_LOG.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_ts(line)
            if ts is None:
                continue

            em = EXEC_RE.search(line)
            if em:
                tid, side, price, *_ = em.groups()
                if side == "BUY":
                    last_buy[tid] = (float(price), ts)
                continue

            dm = DROP_RE.search(line)
            if dm:
                tid = dm.group(1)
                if ts < CUTOVER_TS:
                    continue
                if tid in existing_settled or tid in seen_drops:
                    continue
                if tid not in last_buy:
                    print(f"  SKIP {tid[:14]}.. no prior BUY found")
                    continue
                entry_price, _ = last_buy[tid]
                seen_drops.add(tid)
                new_rows.append({
                    "timestamp": ts,
                    "token_id": tid,
                    "type": "SETTLED_ZERO",
                    "entry_price": entry_price,
                    "exit_price": 0.0,
                    "profit_cents": -entry_price,
                })

    print(f"existing SETTLED_ZERO rows: {len(existing_settled)}")
    print(f"new SETTLED_ZERO rows to append: {len(new_rows)}")
    if not new_rows:
        return

    # 3. Append (preserve existing schema).
    fieldnames = ["timestamp", "token_id", "type", "entry_price",
                  "exit_price", "profit_cents"]
    with EXIT_LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        for r in new_rows:
            w.writerow(r)

    print()
    print("appended:")
    for r in new_rows:
        when = dt.datetime.utcfromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {when}  {r['token_id'][:14]}..  entry={r['entry_price']:.3f}  loss=${r['profit_cents']:+.3f}/share")


if __name__ == "__main__":
    main()
