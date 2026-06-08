"""
Queue-aware passive-bid backtest using real top-5 book snapshots.

For each market in cache/trades/_meta.csv (winning side known):
  At t_post = window_start + POST_DELAY_S, find the nearest book snapshot per
  token. Place a hypothetical $BID_SIZE_USDC bid at $BID_PX on each side.
  - bids_above_us = sum(size at price > BID_PX in top5 bids)
  - queue_at_my_level = size at price == BID_PX (we go behind it)
  Walk SELL trades from cache/trades for that market in [t_post, window_end].
  For each SELL with price <= BID_PX, consume bids_above_us, then queue,
  then us. Compute realized fills, cost, payout per side.

Compare to optimistic (queue-blind) sim.
"""
import csv, json, glob, os, ast
from collections import defaultdict
from bisect import bisect_left

META = "cache/trades/_meta.csv"
TRADES_DIR = "cache/trades"
SNAP_GLOB = "logs/book_snapshots_2026*.csv"

POST_DELAY_S = 30          # we post at window_start + 30s
BID_PX_LIST = [0.20, 0.25, 0.30, 0.35]
BID_SIZE_USDC = 100.0      # per side


def parse_levels(s):
    if not s or s.strip() == "":
        return []
    try:
        return ast.literal_eval(s)
    except Exception:
        return []


# 1) Index book snapshots by token_id -> sorted list of (ts, top5_bids)
print("Loading book snapshots...")
book_index = defaultdict(list)  # token_id -> list of (ts_epoch, top5_bids_list)
n_rows = 0
for path in sorted(glob.glob(SNAP_GLOB)):
    with open(path, encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            try:
                ts = float(row["ts_epoch"])
            except Exception:
                continue
            tok = row["token_id"]
            bids = parse_levels(row.get("top5_bids", ""))
            book_index[tok].append((ts, bids))
            n_rows += 1
# Sort per-token by ts
for tok in book_index:
    book_index[tok].sort(key=lambda x: x[0])
print(f"  Loaded {n_rows:,} snapshots across {len(book_index):,} tokens")


def nearest_snapshot(tok, target_ts, max_lookback_s=120):
    """Return top5_bids list from the snapshot closest to (and >=) target_ts, or
    the most recent one within max_lookback_s before."""
    arr = book_index.get(tok)
    if not arr:
        return None
    # Use binary search by ts
    times = [x[0] for x in arr]
    i = bisect_left(times, target_ts)
    # Prefer first snapshot at or after target
    candidates = []
    if i < len(arr):
        candidates.append(arr[i])
    if i > 0:
        candidates.append(arr[i - 1])
    best = None
    best_dt = None
    for ts, bids in candidates:
        dt = abs(ts - target_ts)
        if dt > max_lookback_s:
            continue
        if best is None or dt < best_dt:
            best = bids
            best_dt = dt
    return best


# 2) Load market meta
markets = []
with open(META, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        slug = row["slug"]
        try:
            ws = int(slug.rsplit("-", 1)[1])
        except Exception:
            continue
        winner = row.get("winner_token", "").strip()
        if not winner:
            continue
        markets.append({"slug": slug, "ws": ws, "we": ws + 900, "winner": winner})


def simulate_queue_aware(bid_px, size_usdc):
    stats = {
        "n_markets": 0,
        "n_with_book": 0,
        "n_top_of_book": 0,         # markets where our bid was best
        "n_filled_any": 0,
        "win_shares": 0.0, "lose_shares": 0.0,
        "win_cost": 0.0, "lose_cost": 0.0,
    }
    for m in markets:
        slug, ws, we, winner = m["slug"], m["ws"], m["we"], m["winner"]
        path = os.path.join(TRADES_DIR, f"{slug}.json")
        try:
            trades = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not trades:
            continue
        stats["n_markets"] += 1

        # Discover the two tokens from the trade tape
        tokens = list({str(t.get("asset", "")) for t in trades if t.get("asset")})
        if len(tokens) != 2:
            continue

        t_post = ws + POST_DELAY_S
        any_book = False
        any_fill = False

        for tok in tokens:
            bids = nearest_snapshot(tok, t_post)
            if bids is None:
                continue
            any_book = True
            # bids is list of [price, size] sorted desc by price (top5)
            bids_above = sum(sz for px, sz in bids if px > bid_px + 1e-9)
            queue_at_level = sum(sz for px, sz in bids if abs(px - bid_px) <= 1e-9)
            # If our bid is strictly above all snapshot bids, we're top-of-book
            top_of_book = (not bids) or (max((px for px, _ in bids), default=0) < bid_px)
            if top_of_book:
                stats["n_top_of_book"] += 1

            our_remaining = size_usdc / bid_px
            cost = 0.0
            filled = 0.0

            # SELLs in [t_post, we) with price <= bid_px on this token, in time order
            sells = sorted(
                (t for t in trades
                 if t.get("side") == "SELL"
                 and str(t.get("asset", "")) == tok
                 and ws <= int(t.get("timestamp", 0)) < we
                 and float(t.get("price", 1)) <= bid_px + 1e-9),
                key=lambda x: int(x["timestamp"]),
            )

            for s in sells:
                if int(s["timestamp"]) < t_post:
                    continue
                avail = float(s["size"])
                # Eat bids above first
                eat = min(avail, bids_above)
                bids_above -= eat
                avail -= eat
                if avail <= 0:
                    continue
                # Eat queue at our level
                eat = min(avail, queue_at_level)
                queue_at_level -= eat
                avail -= eat
                if avail <= 0:
                    continue
                # Now us
                our_fill = min(avail, our_remaining)
                our_remaining -= our_fill
                filled += our_fill
                cost += our_fill * bid_px
                if our_remaining <= 0:
                    break

            if filled > 0:
                any_fill = True
                if tok == winner:
                    stats["win_shares"] += filled
                    stats["win_cost"] += cost
                else:
                    stats["lose_shares"] += filled
                    stats["lose_cost"] += cost

        if any_book:
            stats["n_with_book"] += 1
        if any_fill:
            stats["n_filled_any"] += 1
    return stats


print(f"\nMarkets with winner: {len(markets)}")
print(f"\n{'bid_px':>7} {'mkts':>5} {'w/book':>6} {'TOB':>5} {'filled':>7} "
      f"{'cost':>10} {'pnl':>10} {'EV/$':>7} {'win%$':>6}")
print("-" * 80)
for bid_px in BID_PX_LIST:
    s = simulate_queue_aware(bid_px, BID_SIZE_USDC)
    cost = s["win_cost"] + s["lose_cost"]
    payout = s["win_shares"]
    pnl = payout - cost
    ev = pnl / cost if cost else 0
    winshare = s["win_cost"] / cost if cost else 0
    print(f"{bid_px:>7.2f} {s['n_markets']:>5d} {s['n_with_book']:>6d} "
          f"{s['n_top_of_book']:>5d} {s['n_filled_any']:>7d} "
          f"${cost:>8,.0f} ${pnl:>+8,.0f} {ev*100:>+6.1f}% {winshare*100:>5.1f}%")

print("\nLegend: mkts=#markets ; w/book=had snapshot near post time ;")
print("  TOB=#token-sides where our bid was top-of-book ;")
print("  filled=#markets with at least one of our bids partially filled ;")
print("  win%$=fraction of cost on the winning side")
