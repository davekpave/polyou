"""
Resolves the central question: when shadow_book.py marks a position
SETTLED_ZERO (couldn't sell at expiry, recorded as total loss), does
the on-chain market actually pay out $1 to the bot's predicted side?

Method: for each SETTLED_ZERO row in logs/shadow_exits.csv, query
the Polymarket Gamma API for that contract's resolved outcomePrices.
A winning outcome has price "1". If the bot's `side` matches the
winning outcome, the on-chain truth is a WIN ($1) regardless of what
shadow_book recorded.

No assumptions — just reads the file, queries the live API, prints
the disagreement count and dollar impact.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter

import requests

GAMMA = "https://gamma-api.polymarket.com/events?slug={}"
SHADOW = "logs/shadow_exits.csv"


def fetch_outcome(slug: str) -> tuple[str, list[str], list[str]]:
    """Returns (status, outcomes, prices) where status in
    {"closed","open","missing","error"}."""
    try:
        r = requests.get(GAMMA.format(slug), timeout=15)
        data = r.json()
        if not data or not data[0].get("markets"):
            return "missing", [], []
        m = data[0]["markets"][0]
        outcomes = m.get("outcomes", [])
        prices = m.get("outcomePrices", [])
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            prices = json.loads(prices)
        status = "closed" if m.get("closed") else "open"
        return status, outcomes, [str(p) for p in prices]
    except Exception as e:
        return f"error:{e}", [], []


def main() -> None:
    rows = list(csv.DictReader(open(SHADOW, newline="")))
    settled_zero = [r for r in rows if r["exit_type"] == "SETTLED_ZERO"]
    print(f"shadow_exits total rows : {len(rows)}")
    print(f"  SETTLED_ZERO rows     : {len(settled_zero)}")
    print(f"  Querying Gamma for each (1 req/300ms)...")
    print()

    counts: Counter[str] = Counter()
    bot_won_dollars = 0.0
    bot_lost_dollars = 0.0
    open_dollars = 0.0
    err_dollars = 0.0
    detail_winners: list[dict] = []

    for i, r in enumerate(settled_zero, 1):
        slug = r["contract_slug"]
        bot_side = r["side"].upper()  # "UP" or "DOWN"
        entry = float(r["entry_price"])
        status, outcomes, prices = fetch_outcome(slug)

        if status == "open":
            counts["open"] += 1
            open_dollars += entry  # would still be -entry recorded
            print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> still OPEN")
        elif status == "missing":
            counts["missing"] += 1
            err_dollars += entry
            print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> NOT FOUND on gamma")
        elif status.startswith("error"):
            counts["error"] += 1
            err_dollars += entry
            print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> {status}")
        else:  # closed
            winning_side = None
            for j, p in enumerate(prices):
                if p in ("1", "1.0"):
                    winning_side = outcomes[j].upper()
                    break
            if winning_side is None:
                counts["closed_no_winner"] += 1
                err_dollars += entry
                print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> closed but no $1 outcome (prices={prices})")
            elif winning_side == bot_side:
                counts["bot_won_onchain"] += 1
                bot_won_dollars += (1.0 - entry)
                detail_winners.append({"slug": slug, "side": bot_side, "entry": entry})
                print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> ON-CHAIN WIN  (recorded -{entry:.2f}, true +{1-entry:.2f})")
            else:
                counts["bot_lost_onchain"] += 1
                bot_lost_dollars += entry  # confirms the -entry loss
                print(f"[{i:3d}] {slug:38s} {bot_side:4s} -> on-chain LOSS (won={winning_side})")

        time.sleep(0.3)  # be polite to gamma API

    print()
    print("=" * 72)
    print("Summary across SETTLED_ZERO rows:")
    for k in ("bot_won_onchain", "bot_lost_onchain", "open",
              "missing", "error", "closed_no_winner"):
        if counts[k]:
            print(f"  {k:24s} {counts[k]}")
    print()
    print(f"Recorded loss (shadow_book) on these rows: -${sum(float(r['entry_price']) for r in settled_zero):.2f}")
    print(f"True on-chain redeem P&L on these rows   :")
    print(f"  bot_won_onchain  : +${bot_won_dollars:.2f}  ({counts['bot_won_onchain']} positions, would redeem $1 each)")
    print(f"  bot_lost_onchain : -${bot_lost_dollars:.2f}  ({counts['bot_lost_onchain']} positions, true $0)")
    print(f"  unresolved/error : recorded -${open_dollars + err_dollars:.2f} ({counts['open']+counts['missing']+counts['error']+counts['closed_no_winner']} positions)")
    print()
    if counts["bot_won_onchain"]:
        diff = bot_won_dollars + sum(float(d["entry"]) for d in detail_winners)
        print(f"Net correction vs shadow-recorded loss on resolved rows: +${diff:.2f}")
        print(f"  ({counts['bot_won_onchain']} 'losses' that were actually wins worth $1 on-chain)")


if __name__ == "__main__":
    main()
