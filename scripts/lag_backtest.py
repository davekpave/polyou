"""
Lag-detection analysis on logs/lag_dataset.csv.

Question 1 (information): at each PM tick t, does the CEX move over the prior
N seconds predict the NEXT PM tick's direction? (sanity / micro-edge)

Question 2 (P&L): if we'd entered the side of the CEX move whenever
|cex_delta_bps_60s| > K (and PM hadn't yet moved that direction by Y bps),
buying at pm_ask = pm_px + 0.02, exiting at win_end at outcome (1 or 0),
what's the per-trade P&L?

We compute the *true* market outcome from chainlink (price at win_start vs
win_end), independent of what the bot actually did.
"""
import bisect
import csv
import glob
from collections import defaultdict


CL_FILES = sorted(glob.glob("logs/chainlink_prices_*.csv"))


def load_chainlink_all():
    by_sym = defaultdict(list)
    for f in CL_FILES:
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


def main():
    print("loading chainlink ...")
    cex_by_sym = load_chainlink_all()

    # group merged ticks by (slug, token_id)
    rows = list(csv.DictReader(open("logs/lag_dataset.csv")))
    print(f"merged ticks: {len(rows)}")
    groups = defaultdict(list)
    for r in rows:
        groups[(r["slug"], r["token_id"])].append(r)
    print(f"markets: {len(groups)}")

    # determine true outcome for each market from chainlink
    market_meta = {}
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
        up_won = 1 if pb[1] > pa[1] else 0
        market_meta[key] = {
            "sym": sym,
            "win_start": win_start,
            "win_end": win_end,
            "side_bet": first["side"],
            "px_start": pa[1],
            "px_end": pb[1],
            "up_won": up_won,
        }
    print(f"markets with outcome: {len(market_meta)}")

    # ---------- Question 1 ---------- direction prediction tick-to-tick
    # For each consecutive pair of PM ticks within a market, compute
    # CEX delta over the prior N=60s ending at the FIRST tick.
    # Check sign(cex_delta) vs sign(pm_delta_to_next).
    LOOKBACK_S = 60
    buckets = [(0, 5), (5, 10), (10, 20), (20, 50), (50, 1e9)]  # bps
    bucket_stats = {b: {"n": 0, "agree": 0} for b in buckets}

    for key, gr in groups.items():
        if key not in market_meta:
            continue
        sym = market_meta[key]["sym"]
        cex = cex_by_sym[sym]
        gr_sorted = sorted(gr, key=lambda r: float(r["pm_t"]))
        for i in range(len(gr_sorted) - 1):
            cur = gr_sorted[i]
            nxt = gr_sorted[i + 1]
            t_cur = float(cur["pm_t"])
            pm_cur = float(cur["pm_px"])
            pm_nxt = float(nxt["pm_px"])
            cex_now = cex_at(cex, t_cur)
            cex_back = cex_at(cex, t_cur - LOOKBACK_S)
            if cex_now is None or cex_back is None:
                continue
            cex_delta_bps = (cex_now[1] - cex_back[1]) / cex_back[1] * 1e4
            pm_delta = pm_nxt - pm_cur
            if pm_delta == 0:
                continue  # ignore no-move
            agree = 1 if (cex_delta_bps * pm_delta) > 0 else 0
            adb = abs(cex_delta_bps)
            for lo, hi in buckets:
                if lo <= adb < hi:
                    bucket_stats[(lo, hi)]["n"] += 1
                    bucket_stats[(lo, hi)]["agree"] += agree
                    break

    print()
    print("=== Q1: does CEX 60s lookback predict next PM tick direction? ===")
    print(f"{'cex_move_bps':>14s}  {'n':>6s}  {'agree_rate':>10s}")
    for b in buckets:
        s = bucket_stats[b]
        rate = s["agree"] / s["n"] if s["n"] else 0
        lo, hi = b
        label = f"[{lo:.0f},{hi:.0f})" if hi < 1e8 else f"[{lo:.0f},inf)"
        print(f"{label:>14s}  {s['n']:>6d}  {rate:>10.3f}")

    # ---------- Question 2 ---------- backtest P&L
    # Strategy: at each PM tick t (after enough lookback), if
    #   |cex_delta_bps_60s| > K
    # AND we haven't already taken a position in this market,
    # buy YES on the side of the CEX move (UP if cex_delta>0, DOWN<0)
    # at pm_ask = pm_px + 0.02 capped at 0.99.
    # Outcome: 1.0 if our side wins, 0.0 otherwise.
    # P&L per trade = outcome - pm_ask.
    print()
    print("=== Q2: lag-entry backtest P&L ===")
    print(f"{'K_bps':>6s}  {'n':>4s}  {'win%':>6s}  {'avg_ask':>8s}  {'avg_pnl':>8s}  {'total':>9s}")
    for K in [3, 5, 8, 10, 15, 20, 30, 50]:
        n = 0
        wins = 0
        sum_ask = 0.0
        sum_pnl = 0.0
        for key, gr in groups.items():
            if key not in market_meta:
                continue
            meta = market_meta[key]
            sym = meta["sym"]
            cex = cex_by_sym[sym]
            up_won = meta["up_won"]
            gr_sorted = sorted(gr, key=lambda r: float(r["pm_t"]))
            taken = False
            for cur in gr_sorted:
                if taken:
                    break
                t = float(cur["pm_t"])
                if t < meta["win_start"] + LOOKBACK_S:
                    continue
                if t > meta["win_end"] - 30:
                    # don't enter in last 30s; not enough time
                    continue
                pm_px = float(cur["pm_px"])
                cex_now = cex_at(cex, t)
                cex_back = cex_at(cex, t - LOOKBACK_S)
                if cex_now is None or cex_back is None:
                    continue
                d_bps = (cex_now[1] - cex_back[1]) / cex_back[1] * 1e4
                if abs(d_bps) < K:
                    continue
                # take side of CEX move
                our_side = "UP" if d_bps > 0 else "DOWN"
                # buy that side at ask
                ask = min(0.99, pm_px + 0.02) if our_side == meta["side_bet"] else min(0.99, (1.0 - pm_px) + 0.02)
                # NOTE: pm_px is the price of the side that was originally bet on.
                # If our_side == side_bet, the ask for our side is pm_px + 0.02.
                # Else, the ask for the OPPOSITE side is approximately (1 - pm_px) + 0.02.
                # outcome
                we_won = 1 if (our_side == "UP" and up_won == 1) or (our_side == "DOWN" and up_won == 0) else 0
                payoff = 1.0 if we_won else 0.0
                pnl = payoff - ask
                n += 1
                wins += we_won
                sum_ask += ask
                sum_pnl += pnl
                taken = True
        if n == 0:
            print(f"{K:6d}  {0:4d}  {0.0:6.2f}  {0.0:8.4f}  {0.0:8.4f}  {0.0:9.2f}")
            continue
        print(f"{K:6d}  {n:4d}  {100*wins/n:6.2f}  {sum_ask/n:8.4f}  {sum_pnl/n:8.4f}  {sum_pnl:9.2f}")


if __name__ == "__main__":
    main()
