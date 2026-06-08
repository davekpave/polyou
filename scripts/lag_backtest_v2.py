"""
Lag backtest v2 — fix look-ahead.

Trigger off chainlink (CEX) ticks, not PM ticks.
At each chainlink tick t with CEX move > K bps over last LOOKBACK_S seconds,
take the LAST PM tick with timestamp <= t (i.e., the stalest visible book).
Trade direction = sign(cex_delta).
Entry ask  = min(0.99, pm_px_for_our_side + 0.02), where:
  - if our_side == side_bet (the side this market's row was originally for),
    pm_px in dataset is already that side's price.
  - else pm_px in dataset is the OTHER side, so price for our side ≈ 1 - pm_px.

Outcome from chainlink: UP wins iff cex(win_end) > cex(win_start).

Also reports timing: fraction of triggers where the most-recent PM tick is
BEFORE the CEX move started (true lag) vs after (no edge).
"""
import bisect
import csv
import glob
from collections import defaultdict


def load_chainlink_all():
    by_sym = defaultdict(list)
    for f in sorted(glob.glob("logs/chainlink_prices_*.csv")):
        with open(f, "r") as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    by_sym[row["symbol"]].append((float(row["ts_epoch"]), float(row["price"])))
                except Exception:
                    continue
    out = {}
    for sym, pairs in by_sym.items():
        pairs.sort()
        out[sym] = ([p[0] for p in pairs], [p[1] for p in pairs])
    return out


def cex_at(cex, t):
    ts, px = cex
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return (ts[i], px[i])


def pm_last_at_or_before(pm_sorted, t):
    """pm_sorted is list of (t, px). Return last with t <= cutoff."""
    ts = [p[0] for p in pm_sorted]
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return pm_sorted[i]


def main():
    LOOKBACK_S = 60
    MARKUP = 0.02
    HOLD_LATEST_S = 30  # don't enter in last 30s of window
    cex_by_sym = load_chainlink_all()

    rows = list(csv.DictReader(open("logs/lag_dataset.csv")))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["slug"], r["token_id"])].append(r)

    market_meta = {}
    pm_by_market = {}
    for key, gr in groups.items():
        first = gr[0]
        sym = first["symbol"]
        win_start = int(first["win_start"])
        win_end = int(first["win_end"])
        if sym not in cex_by_sym:
            continue
        pa = cex_at(cex_by_sym[sym], win_start)
        pb = cex_at(cex_by_sym[sym], win_end)
        if pa is None or pb is None:
            continue
        market_meta[key] = {
            "sym": sym,
            "win_start": win_start,
            "win_end": win_end,
            "side_bet": first["side"],
            "up_won": 1 if pb[1] > pa[1] else 0,
            "px_start": pa[1],
            "px_end": pb[1],
        }
        pm_by_market[key] = sorted(
            [(float(r["pm_t"]), float(r["pm_px"])) for r in gr]
        )

    print(f"markets: {len(market_meta)}")

    print()
    print("=== Q2 v2: CEX-trigger backtest, trade at LAST PM tick (no look-ahead) ===")
    print(
        f"{'K_bps':>6s}  {'n':>4s}  {'win%':>6s}  {'avg_ask':>8s}  "
        f"{'avg_pnl':>8s}  {'total':>9s}  {'pm_age_med_s':>13s}"
    )
    for K in [3, 5, 8, 10, 15, 20, 30]:
        n = 0
        wins = 0
        sum_ask = 0.0
        sum_pnl = 0.0
        pm_ages = []
        for key, meta in market_meta.items():
            sym = meta["sym"]
            cex = cex_by_sym[sym]
            pm = pm_by_market[key]
            cex_ts, cex_px = cex
            i_lo = bisect.bisect_left(cex_ts, meta["win_start"] + LOOKBACK_S)
            i_hi = bisect.bisect_right(cex_ts, meta["win_end"] - HOLD_LATEST_S)
            taken = False
            for i in range(i_lo, i_hi):
                t = cex_ts[i]
                back = cex_at(cex, t - LOOKBACK_S)
                if back is None:
                    continue
                d_bps = (cex_px[i] - back[1]) / back[1] * 1e4
                if abs(d_bps) < K:
                    continue
                pm_last = pm_last_at_or_before(pm, t)
                if pm_last is None:
                    continue
                pm_t, pm_px_bet_side = pm_last
                our_side = "UP" if d_bps > 0 else "DOWN"
                if our_side == meta["side_bet"]:
                    px_our_side = pm_px_bet_side
                else:
                    px_our_side = 1.0 - pm_px_bet_side
                ask = min(0.99, px_our_side + MARKUP)
                we_won = 1 if (
                    (our_side == "UP" and meta["up_won"] == 1)
                    or (our_side == "DOWN" and meta["up_won"] == 0)
                ) else 0
                pnl = (1.0 if we_won else 0.0) - ask
                n += 1
                wins += we_won
                sum_ask += ask
                sum_pnl += pnl
                pm_ages.append(t - pm_t)
                taken = True
                break
            # one trade per market per K
        if n == 0:
            continue
        pm_ages.sort()
        med = pm_ages[len(pm_ages) // 2]
        print(
            f"{K:6d}  {n:4d}  {100*wins/n:6.2f}  {sum_ask/n:8.4f}  "
            f"{sum_pnl/n:8.4f}  {sum_pnl:9.2f}  {med:13.1f}"
        )

    # Diagnostic: distribution of CEX moves at PM-tick timestamps vs chainlink-tick timestamps
    print()
    print("=== Diagnostic: PM-tick freshness ===")
    age_pm_after_cex = []
    for key, meta in market_meta.items():
        cex = cex_by_sym[meta["sym"]]
        pm = pm_by_market[key]
        for (pm_t, _) in pm:
            cex_now = cex_at(cex, pm_t)
            if cex_now is None:
                continue
            age_pm_after_cex.append(pm_t - cex_now[0])
    age_pm_after_cex.sort()
    if age_pm_after_cex:
        n = len(age_pm_after_cex)
        print(f"PM ticks observed after most-recent CEX tick (sec):")
        print(f"  n      = {n}")
        print(f"  median = {age_pm_after_cex[n//2]:.2f}")
        print(f"  p25    = {age_pm_after_cex[n//4]:.2f}")
        print(f"  p75    = {age_pm_after_cex[3*n//4]:.2f}")
        print(f"  p95    = {age_pm_after_cex[int(0.95*n)]:.2f}")


if __name__ == "__main__":
    main()
