"""
Selection-bias check: does the +127% EV cell hold up in markets the BOT did NOT
participate in?

If the bot's losing trades create the cheap-buy opportunity, then markets without
the bot should show a much weaker edge. If the edge is ~the same, it's a real
property of 15m crypto Up/Down markets, not bot-induced.

Also check: time distribution of cached markets, to see if data is concentrated
in any single period.
"""
import csv, json, glob, os, ast
from collections import defaultdict, Counter
from datetime import datetime, timezone
from bisect import bisect_left

META = "cache/trades/_meta.csv"
TRADES_DIR = "cache/trades"
SNAP_GLOB = "logs/book_snapshots_2026*.csv"
BOT_WALLET = "0x1b78f77e168f24835f97a380198592a4e1210c1a"

# 1) Time distribution
print("=== Time distribution of cached markets ===")
date_counter = Counter()
markets = []
for row in csv.DictReader(open(META, newline="", encoding="utf-8")):
    slug = row["slug"]
    try:
        ws = int(slug.rsplit("-", 1)[1])
    except Exception:
        continue
    winner = row.get("winner_token", "").strip()
    if not winner:
        continue
    d = datetime.fromtimestamp(ws, tz=timezone.utc).strftime("%Y-%m-%d")
    date_counter[d] += 1
    markets.append({"slug": slug, "ws": ws, "we": ws + 900, "winner": winner})

for d in sorted(date_counter):
    print(f"  {d}: {date_counter[d]} markets")
print(f"  Total: {len(markets)}")

# 2) Split markets by whether bot participated
print("\n=== Splitting by bot participation ===")
bot_markets = []
no_bot_markets = []
for m in markets:
    path = os.path.join(TRADES_DIR, f"{m['slug']}.json")
    try:
        trades = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    bot_present = any(t.get("proxyWallet", "").lower() == BOT_WALLET for t in trades)
    if bot_present:
        bot_markets.append(m)
    else:
        no_bot_markets.append(m)

print(f"  With bot:    {len(bot_markets)} markets")
print(f"  Without bot: {len(no_bot_markets)} markets")

# 3) Run the queue-aware sim on each subset
print("\n=== Loading book snapshots ===")
book_index = defaultdict(list)
n_rows = 0
for path in sorted(glob.glob(SNAP_GLOB)):
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = float(row["ts_epoch"])
            except Exception:
                continue
            tok = row["token_id"]
            try:
                bids = ast.literal_eval(row.get("top5_bids", "")) if row.get("top5_bids") else []
            except Exception:
                bids = []
            book_index[tok].append((ts, bids))
            n_rows += 1
for tok in book_index:
    book_index[tok].sort(key=lambda x: x[0])
print(f"  {n_rows:,} snapshots, {len(book_index):,} tokens")


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
    n_filled = 0
    n_with_book = 0
    for m in market_subset:
        path = os.path.join(TRADES_DIR, f"{m['slug']}.json")
        try:
            trades = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not trades: continue
        ws, we, winner = m["ws"], m["we"], m["winner"]
        tokens = list({str(t.get("asset", "")) for t in trades if t.get("asset")})
        if len(tokens) != 2: continue
        t_post = ws + post_delay
        had_book = False
        had_fill = False
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
        "n": len(market_subset),
        "n_with_book": n_with_book,
        "n_filled": n_filled,
        "cost": cost,
        "pnl": pnl,
        "ev": pnl / cost if cost else 0,
        "winshare": win_cost / cost if cost else 0,
    }


print(f"\n=== Side-by-side at bid=0.20, t=+30s, $100/side ===")
print(f"{'group':>14} {'n':>4} {'w/book':>6} {'filled':>6} {'cost':>10} {'pnl':>10} {'EV/$':>7} {'win$':>5}")
for label, sub in [("ALL", markets), ("with bot", bot_markets), ("without bot", no_bot_markets)]:
    r = simulate(sub)
    print(f"{label:>14} {r['n']:>4d} {r['n_with_book']:>6d} {r['n_filled']:>6d} "
          f"${r['cost']:>8,.0f} ${r['pnl']:>+8,.0f} {r['ev']*100:>+6.1f}% {r['winshare']*100:>4.1f}%")

# Also at bid=0.30 to see if the pattern is consistent
print(f"\n=== Same at bid=0.30 ===")
print(f"{'group':>14} {'n':>4} {'w/book':>6} {'filled':>6} {'cost':>10} {'pnl':>10} {'EV/$':>7} {'win$':>5}")
for label, sub in [("ALL", markets), ("with bot", bot_markets), ("without bot", no_bot_markets)]:
    r = simulate(sub, bid_px=0.30)
    print(f"{label:>14} {r['n']:>4d} {r['n_with_book']:>6d} {r['n_filled']:>6d} "
          f"${r['cost']:>8,.0f} ${r['pnl']:>+8,.0f} {r['ev']*100:>+6.1f}% {r['winshare']*100:>4.1f}%")
