"""
Skepticism checks for the lag-backtest.

(a) Validate CEX-derived outcomes against the actual Polymarket resolution by
    cross-referencing shadow_exits: if predicted_side_won=1 and side=UP, then
    UP won. Compare to up_won computed from chainlink.

(b) Per-day P&L breakdown at K=5 bps to see if the edge is uniform.

(c) For each backtest trade, did the existing bot also take a trade in the
    same market and same direction? Compare entry prices and outcomes.
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
    ts = [p[0] for p in pm_sorted]
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return pm_sorted[i]


def main():
    LOOKBACK_S = 60
    HOLD_LATEST_S = 30
    MARKUP = 0.02
    K = 5

    cex_by_sym = load_chainlink_all()

    rows = list(csv.DictReader(open("logs/lag_dataset.csv")))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["slug"], r["token_id"])].append(r)

    bot_trades = list(csv.DictReader(open("logs/shadow_exits.csv")))
    bot_by_token = {t["token_id"]: t for t in bot_trades}

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
            "token_id": first["token_id"],
        }
        pm_by_market[key] = sorted(
            [(float(r["pm_t"]), float(r["pm_px"])) for r in gr]
        )

    # ---------- (a) outcome validation ----------
    print("=== (a) Outcome validation: chainlink-derived vs bot's own resolution ===")
    n_check = 0
    n_match = 0
    mismatches = []
    for key, meta in market_meta.items():
        bot = bot_by_token.get(meta["token_id"])
        if bot is None:
            continue
        side_bet = bot["side"]
        won_bet = bot["predicted_side_won"]  # "1" if bet side won, "0" otherwise
        if won_bet not in ("0", "1"):
            continue
        bet_won_flag = int(won_bet)
        # derived: did side_bet win per chainlink?
        if side_bet == "UP":
            cl_bet_won = meta["up_won"]
        else:
            cl_bet_won = 1 - meta["up_won"]
        n_check += 1
        if cl_bet_won == bet_won_flag:
            n_match += 1
        else:
            mismatches.append((key[0], side_bet, bet_won_flag, cl_bet_won,
                               meta["px_start"], meta["px_end"]))
    print(f"  checked: {n_check}  matches: {n_match}  mismatches: {n_check - n_match}")
    for m in mismatches[:10]:
        print(f"    {m}")

    # ---------- (b) per-day breakdown ----------
    print()
    print(f"=== (b) Per-day P&L at K={K} bps ===")
    by_day = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
    trades = []
    for key, meta in market_meta.items():
        sym = meta["sym"]
        cex = cex_by_sym[sym]
        pm = pm_by_market[key]
        cex_ts, cex_px = cex
        i_lo = bisect.bisect_left(cex_ts, meta["win_start"] + LOOKBACK_S)
        i_hi = bisect.bisect_right(cex_ts, meta["win_end"] - HOLD_LATEST_S)
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
                px_our = pm_px_bet_side
            else:
                px_our = 1.0 - pm_px_bet_side
            ask = min(0.99, px_our + MARKUP)
            we_won = 1 if (
                (our_side == "UP" and meta["up_won"] == 1)
                or (our_side == "DOWN" and meta["up_won"] == 0)
            ) else 0
            pnl = (1.0 if we_won else 0.0) - ask
            day_key = int(meta["win_end"]) // 86400
            by_day[day_key]["n"] += 1
            by_day[day_key]["wins"] += we_won
            by_day[day_key]["pnl"] += pnl
            trades.append({
                "slug": key[0],
                "token_id": meta["token_id"],
                "sym": sym,
                "our_side": our_side,
                "ask": ask,
                "we_won": we_won,
                "pnl": pnl,
                "trigger_t": t,
                "win_end": meta["win_end"],
                "d_bps": d_bps,
            })
            break  # one trade per market

    print(f"{'day_key':>10s}  {'n':>4s}  {'win%':>6s}  {'pnl':>9s}")
    for d in sorted(by_day):
        s = by_day[d]
        print(f"{d:>10d}  {s['n']:>4d}  {100*s['wins']/max(1,s['n']):>6.2f}  {s['pnl']:>9.3f}")

    # ---------- (c) cross-check vs bot ----------
    print()
    print("=== (c) Cross-check vs bot's actual trades (same K=5) ===")
    n_overlap = 0
    n_bot_won = 0
    n_back_won = 0
    bot_pnl_sum = 0.0
    back_pnl_sum = 0.0
    for tr in trades:
        bot = bot_by_token.get(tr["token_id"])
        if bot is None:
            continue
        n_overlap += 1
        bot_won = int(bot["predicted_side_won"]) if bot["predicted_side_won"] in ("0", "1") else 0
        bot_entry = float(bot["entry_price"])
        bot_pnl = (1.0 if bot_won else 0.0) - bot_entry
        n_bot_won += bot_won
        n_back_won += tr["we_won"]
        bot_pnl_sum += bot_pnl
        back_pnl_sum += tr["pnl"]
    print(f"  overlap markets       : {n_overlap}")
    print(f"  bot win rate         : {100*n_bot_won/max(1,n_overlap):.2f}%   total pnl={bot_pnl_sum:+.2f}")
    print(f"  backtest win rate    : {100*n_back_won/max(1,n_overlap):.2f}%   total pnl={back_pnl_sum:+.2f}")

    # quick same-side breakdown
    same_side = sum(1 for tr in trades if (b := bot_by_token.get(tr["token_id"])) and b["side"] == tr["our_side"])
    print(f"  same side as bot     : {same_side}/{n_overlap}")


if __name__ == "__main__":
    main()
