"""
Test: in the last 30s of the window, is the side trading > 0.5 the eventual winner?
If yes (≥80%), there's a buy-the-favorite-late edge.
Uses book snapshots near window_end - 30s, gamma-resolved winners.
"""
import csv, json, ast, glob, os
from collections import defaultdict
from bisect import bisect_left

# Load gamma winners
gw_map = {r["slug"]: r["gamma_winner"]
          for r in csv.DictReader(open("cache/trades/_meta_gamma_winners.csv"))}

# Load meta
META = list(csv.DictReader(open("cache/trades/_meta.csv")))

# Load book snapshots: store top-of-book mid per token timeline
print("Loading snapshots...")
book = defaultdict(list)  # token -> [(ts, best_bid, best_ask)]
for path in sorted(glob.glob("logs/book_snapshots_2026*.csv")):
    for row in csv.DictReader(open(path, encoding="utf-8")):
        try:
            ts = float(row["ts_epoch"])
            bb = float(row["best_bid"]) if row["best_bid"] else None
            ba = float(row["best_ask"]) if row["best_ask"] else None
        except Exception:
            continue
        book[row["token_id"]].append((ts, bb, ba))
for tok in book: book[tok].sort(key=lambda x: x[0])
print(f"  {len(book)} tokens")


def nearest(tok, target_ts, max_lookback=60):
    arr = book.get(tok)
    if not arr: return None
    times = [x[0] for x in arr]
    i = bisect_left(times, target_ts)
    cands = []
    if i < len(arr): cands.append(arr[i])
    if i > 0: cands.append(arr[i-1])
    best, bdt = None, None
    for ts, bb, ba in cands:
        dt = abs(ts - target_ts)
        if dt > max_lookback: continue
        if best is None or dt < bdt:
            best, bdt = (bb, ba, ts), dt
    return best


# Test at multiple lead times before window end
for lead_s in (60, 30, 15, 5):
    print(f"\n=== At window_end - {lead_s}s ===")
    n = favs = fav_won = clear_fav = clear_fav_won = 0
    margins_when_correct = []
    margins_when_wrong = []
    for r in META:
        slug = r["slug"]
        winner = gw_map.get(slug)
        if not winner: continue
        try:
            toks = r["tokens"].split(",")
            if len(toks) != 2: continue
            ws = int(slug.rsplit("-", 1)[1])
        except Exception:
            continue
        we = ws + 900
        target = we - lead_s

        # Get mid for both tokens
        mids = {}
        for tok in toks:
            snap = nearest(tok, target)
            if snap is None or snap[0] is None or snap[1] is None:
                mids = None; break
            mids[tok] = (snap[0] + snap[1]) / 2.0
        if not mids: continue

        n += 1
        # Favorite = token with higher mid
        fav_tok = max(mids, key=mids.get)
        fav_mid = mids[fav_tok]
        other_mid = min(mids.values())
        margin = fav_mid - other_mid

        favs += 1
        won = (fav_tok == winner)
        if won: fav_won += 1
        if won: margins_when_correct.append(margin)
        else: margins_when_wrong.append(margin)

        # "Clear" favorite: mid >= 0.70
        if fav_mid >= 0.70:
            clear_fav += 1
            if won: clear_fav_won += 1

    if favs:
        print(f"  n={n}  favorite_wins={fav_won}/{favs} = {100*fav_won/favs:.1f}%")
    if clear_fav:
        print(f"  clear-fav (mid>=0.70):  wins={clear_fav_won}/{clear_fav} = {100*clear_fav_won/clear_fav:.1f}%")
    if margins_when_correct:
        avg_c = sum(margins_when_correct)/len(margins_when_correct)
        print(f"  avg margin when fav wins:  {avg_c:.3f}")
    if margins_when_wrong:
        avg_w = sum(margins_when_wrong)/len(margins_when_wrong)
        print(f"  avg margin when fav loses: {avg_w:.3f}")
