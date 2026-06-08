"""
Fetch all trades for each resolved market in logs/shadow_exits.csv.

For each contract_slug:
  - look up conditionId + clobTokenIds via gamma
  - figure out winning token_id from shadow_exits (predicted_side_won + bot's token_id)
  - pull all trades from data-api.polymarket.com/trades?market=<conditionId>
  - cache to cache/trades/<slug>.json

Output:
  - cache/trades/<slug>.json    raw trades
  - cache/trades/_meta.csv      slug, conditionId, token_yes, token_no, winner_token_id, n_trades
"""
from __future__ import annotations
import csv
import json
import os
import time
from pathlib import Path
import requests

GAMMA = "https://gamma-api.polymarket.com/markets"
DATA_API = "https://data-api.polymarket.com/trades"
CACHE = Path("cache/trades")
CACHE.mkdir(parents=True, exist_ok=True)
META = CACHE / "_meta.csv"


def load_shadow():
    return list(csv.DictReader(open("logs/shadow_exits.csv")))


def gamma_lookup(slug: str):
    r = requests.get(GAMMA, params={"slug": slug, "closed": "true"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if not j:
        return None
    m = j[0]
    tokens = json.loads(m.get("clobTokenIds") or "[]")
    return {
        "conditionId": m.get("conditionId"),
        "tokens": tokens,
    }


def fetch_trades(condition_id: str):
    out = []
    offset = 0
    limit = 500
    while True:
        r = requests.get(
            DATA_API,
            params={"market": condition_id, "limit": limit, "offset": offset},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.05)
    return out


def main():
    rows = load_shadow()
    print(f"Markets to process: {len(rows)}")
    meta_rows = []
    for i, row in enumerate(rows, 1):
        slug = row["contract_slug"]
        bot_token = row["token_id"]
        won = row["predicted_side_won"]
        cache_file = CACHE / f"{slug}.json"
        if cache_file.exists():
            try:
                trades = json.loads(cache_file.read_text())
                cached = True
            except Exception:
                trades = None
        else:
            trades = None
            cached = False

        info = None
        if trades is None:
            try:
                info = gamma_lookup(slug)
            except Exception as e:
                print(f"[{i}] gamma fail {slug}: {e}")
                continue
            if not info or not info["conditionId"]:
                print(f"[{i}] no gamma {slug}")
                continue
            try:
                trades = fetch_trades(info["conditionId"])
            except Exception as e:
                print(f"[{i}] trades fail {slug}: {e}")
                continue
            cache_file.write_text(json.dumps(trades))
        else:
            # need conditionId + tokens for meta; reconstruct cheaply
            try:
                info = gamma_lookup(slug)
            except Exception:
                info = None

        tokens = info["tokens"] if info else []
        cond = info["conditionId"] if info else ""
        # winner token: if predicted_side_won == "1", bot_token is winner
        if won == "1":
            winner = bot_token
        elif won == "0":
            winner = next((t for t in tokens if t != bot_token), "")
        else:
            winner = ""

        meta_rows.append(
            {
                "slug": slug,
                "conditionId": cond,
                "tokens": ",".join(tokens),
                "bot_token": bot_token,
                "predicted_side_won": won,
                "winner_token": winner,
                "n_trades": len(trades) if trades else 0,
                "cached": cached,
            }
        )
        if i % 10 == 0 or not cached:
            print(f"[{i}/{len(rows)}] {slug} trades={len(trades) if trades else 0} cached={cached}")

    with META.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "slug",
                "conditionId",
                "tokens",
                "bot_token",
                "predicted_side_won",
                "winner_token",
                "n_trades",
                "cached",
            ],
        )
        w.writeheader()
        w.writerows(meta_rows)
    total = sum(r["n_trades"] for r in meta_rows)
    print(f"Wrote {META} | markets={len(meta_rows)} total_trades={total}")


if __name__ == "__main__":
    main()
