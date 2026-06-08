"""
Passive-bid replay simulator (Phase 1).

For each market in cache/trades/, simulate posting a passive BID on BOTH outcomes
at price `bid_px` for size `bid_size_usdc`, live from t=t_start_frac to t=t_end_frac
(fractions of the 15m window).

FILL RULE (queue-naive, optimistic):
- Walk trades in time order. Only consider trades where side=='SELL' (someone is
  hitting a bid). If trade.price <= bid_px AND trade is within our active window
  AND we still have remaining size on that outcome, we get filled at OUR bid_px
  (better than trade.price for us) for min(remaining_size_shares, trade.size).
- We post on BOTH outcomes simultaneously. Both can fill independently.
- After window_end, resolve: winning shares pay $1; losing shares pay $0.

NOTE: queue-naive => UPPER BOUND on fills. Real fills will be lower because we'd
be behind other resting bids at the same price.

Fees: Polymarket maker fee is 0% (taker pays). So gross P&L == net P&L for makers.

Output: per (bid_px, t_start, t_end) summary across all markets.
"""
import csv, json, glob, os, collections

META = "cache/trades/_meta.csv"
TRADES_DIR = "cache/trades"

# Load market metadata
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
        # Two outcome tokens
        toks = []
        for k in ("token_yes", "token_no", "token0", "token1", "tokens"):
            v = row.get(k, "")
            if v:
                if "," in v:
                    toks = [x.strip() for x in v.split(",") if x.strip()]
                else:
                    toks.append(v.strip())
        meta[slug] = {
            "winner_token": winner,
            "tokens": toks,
            "window_start": ws,
            "window_end": ws + 900,
        }

# Inspect one row to see what columns _meta.csv has
with open(META, newline="", encoding="utf-8") as f:
    rdr = csv.DictReader(f)
    print("meta cols:", rdr.fieldnames)


def load_trades(slug):
    p = os.path.join(TRADES_DIR, f"{slug}.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def simulate(bid_px: float, t_start_frac: float, t_end_frac: float, bid_size_usdc: float):
    """Return aggregate stats across all markets."""
    n_markets_with_fill = 0
    n_markets = 0
    total_cost = 0.0
    total_payout = 0.0
    total_filled_shares = 0.0
    fills_by_market = []

    for slug, m in meta.items():
        trades = load_trades(slug)
        if not trades:
            continue
        n_markets += 1

        ws = m["window_start"]
        we = m["window_end"]
        winner = m["winner_token"]

        active_start = ws + int(900 * t_start_frac)
        active_end = ws + int(900 * t_end_frac)

        # Discover the two tokens from the trade tape
        tokens_seen = set()
        for t in trades:
            a = str(t.get("asset", ""))
            if a:
                tokens_seen.add(a)
        # Resting bid on EACH token; remaining size in shares.
        remaining_shares = {tok: bid_size_usdc / bid_px for tok in tokens_seen}
        cost_per_token = {tok: 0.0 for tok in tokens_seen}
        filled_shares_per_token = {tok: 0.0 for tok in tokens_seen}

        # Sort trades by time
        trades_sorted = sorted(trades, key=lambda t: int(t.get("timestamp", 0)))

        for t in trades_sorted:
            try:
                ts = int(t["timestamp"])
                price = float(t["price"])
                size = float(t["size"])  # shares
                side = t.get("side")
                tok = str(t.get("asset", ""))
            except Exception:
                continue
            if ts < active_start or ts >= active_end:
                continue
            if side != "SELL":
                continue
            if price > bid_px:
                continue
            # We can fill at our bid price
            rem = remaining_shares.get(tok, 0.0)
            if rem <= 0:
                continue
            fill_shares = min(rem, size)
            remaining_shares[tok] = rem - fill_shares
            cost_per_token[tok] += fill_shares * bid_px
            filled_shares_per_token[tok] += fill_shares

        market_cost = sum(cost_per_token.values())
        market_payout = filled_shares_per_token.get(winner, 0.0)  # $1 per winning share
        if market_cost > 0:
            n_markets_with_fill += 1
            total_cost += market_cost
            total_payout += market_payout
            total_filled_shares += sum(filled_shares_per_token.values())
            fills_by_market.append((slug, market_cost, market_payout))

    pnl = total_payout - total_cost
    ev_per_dollar = (pnl / total_cost) if total_cost else 0.0
    return {
        "bid_px": bid_px,
        "t_window": f"{t_start_frac:.2f}-{t_end_frac:.2f}",
        "size_per_side": bid_size_usdc,
        "n_markets": n_markets,
        "n_filled_markets": n_markets_with_fill,
        "fill_rate": n_markets_with_fill / n_markets if n_markets else 0,
        "total_cost": total_cost,
        "total_payout": total_payout,
        "pnl": pnl,
        "ev_per_dollar": ev_per_dollar,
    }


print(f"\nMarkets in meta: {len(meta)}")
print(f"\n{'bid_px':>7} {'t_window':>10} {'sz/side':>8} {'n_filled':>9} {'fill%':>6} {'cost':>10} {'pnl':>10} {'EV/$':>7}")
print("-" * 85)

# Sweep
configs = []
for bid_px in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45]:
    for tw in [(0.0, 0.25), (0.0, 0.50), (0.25, 0.50), (0.0, 0.75)]:
        configs.append((bid_px, tw[0], tw[1]))

results = []
for bid_px, t0, t1 in configs:
    r = simulate(bid_px, t0, t1, bid_size_usdc=100.0)
    results.append(r)
    print(f"{r['bid_px']:>7.2f} {r['t_window']:>10} {r['size_per_side']:>8.0f} "
          f"{r['n_filled_markets']:>9d} {r['fill_rate']*100:>5.1f}% "
          f"${r['total_cost']:>9,.0f} ${r['pnl']:>+9,.0f} {r['ev_per_dollar']*100:>+6.1f}%")

# Sort top configs by absolute pnl
print("\n=== Top 10 configs by P&L ===")
for r in sorted(results, key=lambda x: -x["pnl"])[:10]:
    print(f"bid={r['bid_px']:.2f} t={r['t_window']} pnl=${r['pnl']:+,.0f} ev/$={r['ev_per_dollar']*100:+.1f}% filled_markets={r['n_filled_markets']}/{r['n_markets']}")
