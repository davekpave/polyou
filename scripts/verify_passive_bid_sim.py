"""
Verify passive_bid_sim.py before trusting it.

Check 1: Side semantics. Cross-reference a known bot trade from data-api with the
side recorded. Bot trades are BUYs (it crosses asks). If data-api shows them as
'BUY', it's taker-side. If 'SELL', maker-side. We need taker-side for our SELL
filter to mean 'a bid was hit'.

Check 2: For bid=0.20, t=0-50%, compute the per-side fill stats:
- shares filled on winner vs loser
- $ spent per side
- implied win-share-of-dollars
The +135% EV claim implies win-share ~= 47%. Verify.

Check 3: Random-baseline. Run sim with a 'noop' rule (post bid at e.g. 0.50,
midpoint) — should net to ~0 EV. If it shows +100%, sim is broken.

Check 4: Spot-check one market end-to-end.
"""
import csv, json, glob, os, urllib.request

# --- CHECK 1: bot-trade side semantics ---
print("=== CHECK 1: data-api side semantics ===")
W = "0x1b78f77e168f24835f97a380198592a4e1210c1a"
url = f"https://data-api.polymarket.com/trades?user={W}&limit=20"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
data = json.loads(urllib.request.urlopen(req, timeout=15).read())
sides = [t["side"] for t in data]
prices = [float(t["price"]) for t in data]
print(f"  Bot's last 20 trades: BUY={sides.count('BUY')}, SELL={sides.count('SELL')}")
print(f"  BUY prices (bot crosses ASK, so should be HIGH if at-money): "
      f"min={min((p for s,p in zip(sides,prices) if s=='BUY'), default=0):.3f} "
      f"max={max((p for s,p in zip(sides,prices) if s=='BUY'), default=0):.3f}")
print(f"  SELL prices (bot exits to BID, should be HIGH if winning): "
      f"min={min((p for s,p in zip(sides,prices) if s=='SELL'), default=0):.3f} "
      f"max={max((p for s,p in zip(sides,prices) if s=='SELL'), default=0):.3f}")
print("  Bot is known taker. If we see BUY=majority and prices ~0.5-0.8,")
print("  then data-api side IS taker-side, and our SELL filter is correct.")

# --- Load meta + sim helpers ---
META = "cache/trades/_meta.csv"
TRADES_DIR = "cache/trades"
meta = {}
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
        meta[slug] = {"winner": winner, "ws": ws, "we": ws + 900}


def sim_with_breakdown(bid_px, t0_frac, t1_frac, size_usdc=100.0):
    """Returns per-side breakdown for verification."""
    win_shares = 0.0
    lose_shares = 0.0
    win_cost = 0.0
    lose_cost = 0.0
    n_filled = 0
    n_markets = 0

    for slug, m in meta.items():
        path = os.path.join(TRADES_DIR, f"{slug}.json")
        try:
            trades = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not trades:
            continue
        n_markets += 1
        ws, we = m["ws"], m["we"]
        winner = m["winner"]
        active_start = ws + int(900 * t0_frac)
        active_end = ws + int(900 * t1_frac)

        tokens = set(str(t.get("asset", "")) for t in trades if t.get("asset"))
        remaining = {tok: size_usdc / bid_px for tok in tokens}
        market_filled = False

        for t in sorted(trades, key=lambda x: int(x.get("timestamp", 0))):
            try:
                ts = int(t["timestamp"])
                price = float(t["price"])
                size = float(t["size"])
                side = t.get("side")
                tok = str(t.get("asset", ""))
            except Exception:
                continue
            if ts < active_start or ts >= active_end:
                continue
            if side != "SELL" or price > bid_px:
                continue
            rem = remaining.get(tok, 0)
            if rem <= 0:
                continue
            fill = min(rem, size)
            remaining[tok] = rem - fill
            cost = fill * bid_px
            if tok == winner:
                win_shares += fill
                win_cost += cost
            else:
                lose_shares += fill
                lose_cost += cost
            market_filled = True
        if market_filled:
            n_filled += 1

    total_cost = win_cost + lose_cost
    total_payout = win_shares  # $1/winning share
    pnl = total_payout - total_cost
    win_share_pct = win_cost / total_cost if total_cost else 0
    return {
        "win_shares": win_shares, "lose_shares": lose_shares,
        "win_cost": win_cost, "lose_cost": lose_cost,
        "total_cost": total_cost, "pnl": pnl,
        "ev": pnl / total_cost if total_cost else 0,
        "win_share_pct": win_share_pct,
        "n_filled": n_filled, "n_markets": n_markets,
    }


print("\n=== CHECK 2: Per-side breakdown at bid=0.20, t=0-50% ===")
r = sim_with_breakdown(0.20, 0.0, 0.50)
print(f"  Markets: {r['n_filled']}/{r['n_markets']} got at least one fill")
print(f"  Filled on WINNER:  {r['win_shares']:>10,.0f} shares  cost ${r['win_cost']:>8,.2f}")
print(f"  Filled on LOSER:   {r['lose_shares']:>10,.0f} shares  cost ${r['lose_cost']:>8,.2f}")
print(f"  Total cost: ${r['total_cost']:,.2f}   payout: ${r['win_shares']:,.2f}   pnl: ${r['pnl']:+,.2f}")
print(f"  Win-share-of-dollars: {r['win_share_pct']*100:.1f}%  (break-even at bid=0.20: 20.0%)")
print(f"  EV/$: {r['ev']*100:+.1f}%")
print("  If win-share-of-dollars >> 20%, the edge is real.")

print("\n=== CHECK 3: Random baseline at bid=0.50, t=0-50% ===")
r = sim_with_breakdown(0.50, 0.0, 0.50)
print(f"  Markets filled: {r['n_filled']}/{r['n_markets']}")
print(f"  Win-share-of-dollars: {r['win_share_pct']*100:.1f}%  (break-even at bid=0.50: 50.0%)")
print(f"  EV/$: {r['ev']*100:+.1f}%")
print("  At bid=0.50, posting on BOTH sides is symmetric. EV should be small (near 0)")
print("  minus adverse-selection. If it's +50%+, sim has a bug.")

print("\n=== CHECK 4: Spot-check one market ===")
slug = next(iter(meta))
m = meta[slug]
trades = sorted(json.load(open(f"{TRADES_DIR}/{slug}.json", encoding="utf-8")),
                key=lambda x: int(x.get("timestamp", 0)))
ws = m["ws"]
print(f"  Slug: {slug}")
print(f"  Window start: {ws}, end: {ws+900}")
print(f"  Winner token: {m['winner'][:30]}...")
print(f"  N trades: {len(trades)}")
print(f"  First 5 trades:")
for t in trades[:5]:
    rel = int(t["timestamp"]) - ws
    print(f"    t+{rel:+5d}s side={t['side']:4s} px={float(t['price']):.3f} "
          f"sz={float(t['size']):>8.1f} winner={'Y' if str(t['asset'])==m['winner'] else 'N'}")
print(f"  SELLs in 0-450s with px<=0.20:")
hits = [t for t in trades
        if t.get("side") == "SELL"
        and ws <= int(t["timestamp"]) < ws+450
        and float(t["price"]) <= 0.20]
for t in hits[:10]:
    rel = int(t["timestamp"]) - ws
    print(f"    t+{rel:+5d}s px={float(t['price']):.3f} sz={float(t['size']):>8.1f} "
          f"winner={'Y' if str(t['asset'])==m['winner'] else 'N'}")
if not hits:
    print("    (none)")
