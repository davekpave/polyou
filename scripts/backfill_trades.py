"""
backfill_trades.py

For every slug in cache/trades/_meta.csv with a known conditionId, fetch all trades
from data-api.polymarket.com/trades?market=<conditionId> and cache to
cache/trades/<slug>.json. Skips files that already exist and are non-empty.

Usage:
    python scripts/backfill_trades.py [--concurrency 8] [--limit 5000]
"""
from __future__ import annotations
import argparse
import asyncio
import csv
import json
import time
from pathlib import Path

import httpx

DATA_API = "https://data-api.polymarket.com/trades"
CACHE = Path("cache/trades")
META = CACHE / "_meta.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 polyou-research"}


def load_meta():
    rows = list(csv.DictReader(open(META, encoding="utf-8")))
    return rows


async def fetch_trades(client: httpx.AsyncClient, condition_id: str):
    """Paginate; data-api may 400 on offset>~3500 — treat as end-of-stream."""
    out = []
    offset = 0
    limit = 500
    truncated = False
    while True:
        batch = None
        for attempt in range(8):
            try:
                r = await client.get(
                    DATA_API,
                    params={"market": condition_id, "limit": limit, "offset": offset},
                    timeout=30,
                    headers=HEADERS,
                )
                if r.status_code == 400:
                    truncated = True
                    return out, truncated
                if r.status_code == 429:
                    # rate limited; back off and retry
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                r.raise_for_status()
                batch = r.json()
                break
            except httpx.HTTPStatusError:
                if attempt == 7:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))
            except Exception:
                if attempt == 7:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        if batch is None:
            raise RuntimeError(f"failed after retries at offset={offset}")
        if not batch:
            break
        out.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return out, truncated


async def worker(name: int, queue: asyncio.Queue, client: httpx.AsyncClient, stats: dict):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        slug, cond = item
        f = CACHE / f"{slug}.json"
        try:
            trades, truncated = await fetch_trades(client, cond)
            f.write_text(json.dumps(trades), encoding="utf-8")
            stats["ok"] += 1
            stats["trades"] += len(trades)
            if truncated:
                stats["truncated"] += 1
            if stats["ok"] % 25 == 0:
                print(f"  [{stats['ok']}/{stats['total']}] {slug}: {len(trades)} trades"
                      f"{' (TRUNC)' if truncated else ''}  cum={stats['trades']} trunc={stats['truncated']} err={stats['err']}")
        except Exception as e:
            stats["err"] += 1
            print(f"  ! fail {slug}: {e}")
        finally:
            queue.task_done()


async def amain(concurrency: int, max_markets: int | None):
    rows = load_meta()
    todo = []
    for r in rows:
        slug = r["slug"]
        cond = r.get("conditionId", "")
        if not cond:
            continue
        f = CACHE / f"{slug}.json"
        if f.exists() and f.stat().st_size > 2:
            continue
        todo.append((slug, cond))
    if max_markets:
        todo = todo[:max_markets]

    print(f"Markets to fetch: {len(todo)}  (concurrency={concurrency})")
    if not todo:
        return

    stats = {"ok": 0, "err": 0, "trades": 0, "truncated": 0, "total": len(todo)}
    queue: asyncio.Queue = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)
    for _ in range(concurrency):
        queue.put_nowait(None)

    t0 = time.time()
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        await asyncio.gather(*[worker(i, queue, client, stats) for i in range(concurrency)])

    dt = time.time() - t0
    print(f"\nDone in {dt:.1f}s. ok={stats['ok']} err={stats['err']} truncated={stats['truncated']} total_trades={stats['trades']}")

    # Update n_trades in meta
    for r in rows:
        f = CACHE / f"{r['slug']}.json"
        if f.exists() and f.stat().st_size > 2:
            try:
                n = len(json.loads(f.read_text(encoding="utf-8")))
                r["n_trades"] = n
                r["cached"] = "True"
            except Exception:
                pass
    tmp = META.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(META)
    print("Updated n_trades in _meta.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="cap markets fetched (debug)")
    args = ap.parse_args()
    asyncio.run(amain(args.concurrency, args.limit))


if __name__ == "__main__":
    main()
