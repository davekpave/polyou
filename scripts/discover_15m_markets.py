"""
discover_15m_markets.py

Discover all resolved BTC/ETH/SOL 15m Up/Down markets in a date window via gamma API,
write/extend cache/trades/_meta.csv and cache/trades/_meta_gamma_winners.csv.

Usage:
    python scripts/discover_15m_markets.py --days 90
    python scripts/discover_15m_markets.py --start 2026-02-01 --end 2026-05-01
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

GAMMA = "https://gamma-api.polymarket.com/markets"
EVENTS = "https://gamma-api.polymarket.com/events"
CACHE = Path("cache/trades")
CACHE.mkdir(parents=True, exist_ok=True)
META = CACHE / "_meta.csv"
GAMMA_WIN = CACHE / "_meta_gamma_winners.csv"

SLUG_15M_RE = re.compile(r"^(btc|eth|sol)-updown-15m-\d+$")
SLUG_5M_RE = re.compile(r"^(btc|eth|sol)-updown-5m-\d+$")

META_COLS = [
    "slug", "conditionId", "tokens", "bot_token",
    "predicted_side_won", "winner_token", "n_trades", "cached",
]


def load_existing():
    rows = {}
    if META.exists():
        for r in csv.DictReader(open(META, encoding="utf-8")):
            rows[r["slug"]] = r
    winners = {}
    if GAMMA_WIN.exists():
        for r in csv.DictReader(open(GAMMA_WIN, encoding="utf-8")):
            winners[r["slug"]] = r["gamma_winner"]
    return rows, winners


def write_meta(rows: dict[str, dict]):
    tmp = META.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=META_COLS)
        w.writeheader()
        for slug in sorted(rows):
            r = rows[slug]
            w.writerow({k: r.get(k, "") for k in META_COLS})
    tmp.replace(META)


def write_winners(winners: dict[str, str]):
    tmp = GAMMA_WIN.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slug", "gamma_winner"])
        for slug in sorted(winners):
            w.writerow([slug, winners[slug]])
    tmp.replace(GAMMA_WIN)


def fetch_day(client: httpx.Client, day_start: datetime):
    """Yield gamma market rows whose endDate is in [day_start, day_start+1d)."""
    day_end = day_start + timedelta(days=1)
    params_base = {
        "closed": "true",
        "limit": 500,
        "end_date_min": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date_max": day_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    offset = 0
    while True:
        params = dict(params_base, offset=offset)
        for attempt in range(5):
            try:
                r = client.get(GAMMA, params=params, timeout=30)
                r.raise_for_status()
                batch = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(1.0 * (attempt + 1))
        if not batch:
            return
        for m in batch:
            yield m
        if len(batch) < 500:
            return
        offset += 500



def parse_market(m: dict, is_5m=False):
    slug = m.get("slug", "")
    if is_5m:
        if not SLUG_5M_RE.match(slug):
            return None
    else:
        if not SLUG_15M_RE.match(slug):
            return None
    cond = m.get("conditionId") or ""
    try:
        tokens = json.loads(m.get("clobTokenIds") or "[]")
    except Exception:
        tokens = []
    if len(tokens) != 2 or not cond:
        return None
    try:
        op = json.loads(m.get("outcomePrices") or "[]")
        op = [float(x) for x in op]
    except Exception:
        op = []
    winner = ""
    if len(op) == 2 and tokens:
        if op[0] >= 0.99 and op[1] <= 0.01:
            winner = tokens[0]
        elif op[1] >= 0.99 and op[0] <= 0.01:
            winner = tokens[1]
    return slug, cond, tokens, winner

def fetch_5m_markets(client: httpx.Client, day_start: datetime):
    """Yield resolved 5m crypto updown markets ending in [day_start, day_start+1d) via /events."""
    day_end = day_start + timedelta(days=1)
    params = {
        "closed": "true",
        "limit": 500,
        "end_date_min": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date_max": day_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    offset = 0
    while True:
        p = dict(params, offset=offset)
        for attempt in range(5):
            try:
                r = client.get(EVENTS, params=p, timeout=30)
                r.raise_for_status()
                batch = r.json()
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(1.0 * (attempt + 1))
        if not batch:
            return
        for event in batch:
            slug = event.get("slug", "")
            if not SLUG_5M_RE.match(slug):
                continue
            # Each event may have multiple markets, but for updown it's usually one
            for m in event.get("markets", []):
                m["slug"] = slug  # propagate slug
                yield m
        if len(batch) < 500:
            return
        offset += 500


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="lookback days from --end")
    ap.add_argument("--start", type=str, default=None, help="UTC YYYY-MM-DD inclusive")
    ap.add_argument("--end", type=str, default=None, help="UTC YYYY-MM-DD exclusive (default: today)")
    args = ap.parse_args()

    end = (
        datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.end
        else datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    start = (
        datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.start
        else end - timedelta(days=args.days)
    )

    print(f"Window: {start.date()} -> {end.date()} ({(end - start).days} days)")
    rows, winners = load_existing()
    print(f"Existing meta rows: {len(rows)}; winners: {len(winners)}")

    discovered = 0
    new = 0
    no_winner = 0

    with httpx.Client(http2=False) as client:
        day = start
        while day < end:
            day_count_15m = 0
            day_count_5m = 0
            # 15m markets
            for m in fetch_day(client, day):
                parsed = parse_market(m, is_5m=False)
                if not parsed:
                    continue
                slug, cond, tokens, winner = parsed
                day_count_15m += 1
                if slug not in rows:
                    new += 1
                rows[slug] = {
                    "slug": slug,
                    "conditionId": cond,
                    "tokens": ",".join(tokens),
                    "bot_token": rows.get(slug, {}).get("bot_token", ""),
                    "predicted_side_won": rows.get(slug, {}).get("predicted_side_won", ""),
                    "winner_token": winner or rows.get(slug, {}).get("winner_token", ""),
                    "n_trades": rows.get(slug, {}).get("n_trades", ""),
                    "cached": rows.get(slug, {}).get("cached", "False"),
                }
                if winner:
                    winners[slug] = winner
                else:
                    no_winner += 1
            # 5m markets
            for m in fetch_5m_markets(client, day):
                parsed = parse_market(m, is_5m=True)
                if not parsed:
                    continue
                slug, cond, tokens, winner = parsed
                day_count_5m += 1
                if slug not in rows:
                    new += 1
                rows[slug] = {
                    "slug": slug,
                    "conditionId": cond,
                    "tokens": ",".join(tokens),
                    "bot_token": rows.get(slug, {}).get("bot_token", ""),
                    "predicted_side_won": rows.get(slug, {}).get("predicted_side_won", ""),
                    "winner_token": winner or rows.get(slug, {}).get("winner_token", ""),
                    "n_trades": rows.get(slug, {}).get("n_trades", ""),
                    "cached": rows.get(slug, {}).get("cached", "False"),
                }
                if winner:
                    winners[slug] = winner
                else:
                    no_winner += 1
            discovered += (day_count_15m + day_count_5m)
            print(f"  {day.date()}: +{day_count_15m} 15m, +{day_count_5m} 5m crypto markets (total disc {discovered}, new {new})")
            day += timedelta(days=1)

    write_meta(rows)
    write_winners(winners)
    print(f"\nDone. meta={len(rows)} winners={len(winners)} discovered_in_window={discovered} new={new} no_winner_markets={no_winner}")


if __name__ == "__main__":
    main()
