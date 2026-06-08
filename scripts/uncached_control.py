"""
Final selection-bias test: fetch a random sample of crypto Up/Down markets from
the same time window (May 5-8 2026) that are NOT in our cache, then re-run the
queue-aware sim on them.

If those un-flagged markets show similar +EV at bid=0.20, the edge is real.
If they show ~0 EV, our cache is biased and the strategy is fake.
"""
import csv, json, urllib.request, time, os, ast, glob
from collections import defaultdict
from bisect import bisect_left

CACHED_SLUGS = set()
CACHED_WS = set()
for r in csv.DictReader(open("cache/trades/_meta.csv")):
    CACHED_SLUGS.add(r["slug"])
    try:
        CACHED_WS.add(int(r["slug"].rsplit("-", 1)[1]))
    except Exception:
        pass

# Build candidate windows: every 15-min anchor in May 5-8, for BTC/ETH/SOL/XRP
candidates = []
import datetime as dt
start = int(dt.datetime(2026, 5, 5, tzinfo=dt.timezone.utc).timestamp())
end = int(dt.datetime(2026, 5, 9, tzinfo=dt.timezone.utc).timestamp())
for sym in ("btc", "eth", "sol", "xrp"):
    for ws in range(start, end, 900):
        slug = f"{sym}-updown-15m-{ws}"
        if slug not in CACHED_SLUGS:
            candidates.append((slug, ws, sym))

print(f"Candidate uncached windows: {len(candidates)}")
import random
random.seed(42)
random.shuffle(candidates)
sample = candidates[:60]  # ~60 markets to fetch
print(f"Sampling: {len(sample)}")


def gamma_lookup(slug):
    try:
        url = f"https://gamma-api.polymarket.com/events/slug/{slug}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        markets = data.get("markets", [])
        if not markets:
            return None
        m = markets[0]
        cid = m.get("conditionId")
        toks_raw = m.get("clobTokenIds")
        if isinstance(toks_raw, str):
            toks = json.loads(toks_raw)
        else:
            toks = toks_raw
        # Outcomes: tokens[0]=Up=Yes, tokens[1]=Down=No (per existing resolver)
        outcomes_raw = m.get("outcomePrices") or m.get("outcomes") or []
        # Determine winner via UMA-resolved outcome: closed market has resolvedOutcomeIndex or outcomePrices=[1,0] or [0,1]
        op = m.get("outcomePrices")
        if isinstance(op, str):
            op = json.loads(op)
        winner_token = None
        if op and len(op) == 2 and len(toks) == 2:
            try:
                yes_p, no_p = float(op[0]), float(op[1])
                if yes_p > no_p:
                    winner_token = toks[0]
                elif no_p > yes_p:
                    winner_token = toks[1]
            except Exception:
                pass
        return {"slug": slug, "conditionId": cid, "tokens": toks, "winner": winner_token,
                "closed": m.get("closed")}
    except Exception:
        return None


def fetch_trades(condition_id):
    out = []
    for offset in range(0, 5000, 500):
        try:
            url = f"https://data-api.polymarket.com/trades?market={condition_id}&limit=500&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = json.loads(urllib.request.urlopen(req, timeout=15).read())
            if not data:
                break
            out.extend(data)
            if len(data) < 500:
                break
        except Exception:
            break
    return out


# Fetch
print("\nFetching uncached markets...")
fetched = []
for i, (slug, ws, sym) in enumerate(sample):
    info = gamma_lookup(slug)
    if not info or not info["closed"] or not info["winner"]:
        continue
    trades = fetch_trades(info["conditionId"])
    if not trades:
        continue
    fetched.append({
        "slug": slug, "ws": ws, "we": ws + 900,
        "winner": info["winner"], "trades": trades,
    })
    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(sample)} processed, {len(fetched)} usable")
    time.sleep(0.1)

print(f"\nUsable uncached markets: {len(fetched)}")

# Load book index
print("\nLoading book snapshots...")
book_index = defaultdict(list)
for path in sorted(glob.glob("logs/book_snapshots_2026*.csv")):
    for row in csv.DictReader(open(path, encoding="utf-8")):
        try:
            ts = float(row["ts_epoch"])
        except Exception:
            continue
        try:
            bids = ast.literal_eval(row.get("top5_bids", "")) if row.get("top5_bids") else []
        except Exception:
            bids = []
        book_index[row["token_id"]].append((ts, bids))
for tok in book_index:
    book_index[tok].sort(key=lambda x: x[0])
print(f"  {len(book_index)} tokens")


def nearest_bids(tok, target_ts, max_lookback_s=120):
    arr = book_index.get(tok)
    if not arr:
        return None
    times = [x[0] for x in arr]
    i = bisect_left(times, target_ts)
    candidates = []
    if i < len(arr): candidates.append(arr[i])
    if i > 0: candidates.append(arr[i - 1])
    best, best_dt = None, None
    for ts, bids in candidates:
        dt = abs(ts - target_ts)
        if dt > max_lookback_s: continue
        if best is None or dt < best_dt:
            best, best_dt = bids, dt
    return best


def simulate(market_subset, bid_px=0.20, size_usdc=100.0, post_delay=30):
    win_cost = lose_cost = win_shares = 0.0
    n_filled = n_with_book = 0
    for m in market_subset:
        trades = m["trades"]
        if not trades: continue
        ws, we, winner = m["ws"], m["we"], m["winner"]
        tokens = list({str(t.get("asset", "")) for t in trades if t.get("asset")})
        if len(tokens) != 2: continue
        t_post = ws + post_delay
        had_book = had_fill = False
        for tok in tokens:
            bids = nearest_bids(tok, t_post)
            if bids is None: continue
            had_book = True
            bids_above = sum(sz for px, sz in bids if px > bid_px + 1e-9)
            queue_at = sum(sz for px, sz in bids if abs(px - bid_px) <= 1e-9)
            our_remaining = size_usdc / bid_px
            cost = filled = 0.0
            sells = sorted(
                (t for t in trades
                 if t.get("side") == "SELL"
                 and str(t.get("asset","")) == tok
                 and t_post <= int(t.get("timestamp",0)) < we
                 and float(t.get("price",1)) <= bid_px + 1e-9),
                key=lambda x: int(x["timestamp"]),
            )
            for s in sells:
                avail = float(s["size"])
                eat = min(avail, bids_above); bids_above -= eat; avail -= eat
                if avail <= 0: continue
                eat = min(avail, queue_at); queue_at -= eat; avail -= eat
                if avail <= 0: continue
                ours = min(avail, our_remaining)
                our_remaining -= ours
                filled += ours
                cost += ours * bid_px
                if our_remaining <= 0: break
            if filled > 0:
                had_fill = True
                if tok == winner:
                    win_shares += filled; win_cost += cost
                else:
                    lose_cost += cost
        if had_book: n_with_book += 1
        if had_fill: n_filled += 1
    cost = win_cost + lose_cost
    pnl = win_shares - cost
    return {
        "n": len(market_subset), "n_with_book": n_with_book, "n_filled": n_filled,
        "cost": cost, "pnl": pnl,
        "ev": pnl/cost if cost else 0,
        "winshare": win_cost/cost if cost else 0,
    }


print(f"\n=== UNCACHED markets at bid=0.20 ===")
r = simulate(fetched, bid_px=0.20)
print(f"  n={r['n']}  with_book={r['n_with_book']}  filled={r['n_filled']}")
print(f"  cost=${r['cost']:,.0f}  pnl=${r['pnl']:+,.0f}  EV/$={r['ev']*100:+.1f}%  win$={r['winshare']*100:.1f}%")

print(f"\n=== UNCACHED markets at bid=0.30 ===")
r = simulate(fetched, bid_px=0.30)
print(f"  n={r['n']}  with_book={r['n_with_book']}  filled={r['n_filled']}")
print(f"  cost=${r['cost']:,.0f}  pnl=${r['pnl']:+,.0f}  EV/$={r['ev']*100:+.1f}%  win$={r['winshare']*100:.1f}%")

print(f"\n  Compare to CACHED 151 at bid=0.20: EV/$=+126.9%, win$=45.4%")
print(f"  Compare to CACHED 151 at bid=0.30: EV/$=+48.9%,  win$=44.7%")
