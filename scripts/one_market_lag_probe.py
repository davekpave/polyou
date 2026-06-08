"""
Sanity-check: for ONE shadow_exits market, pull
  - Polymarket CLOB price history (fidelity=1, ~1m candles) for the token
  - Chainlink CEX prices for the symbol over the same window
and print a merged time series so we can see if a lag-detection backtest is feasible.
"""
import csv
import glob
import json
import os
import sys
from urllib.request import Request, urlopen

CLOB_HIST = "https://clob.polymarket.com/prices-history"


def http_get_json(url: str, timeout: float = 15.0):
    req = Request(url, headers={"User-Agent": "polyou-research/0.1"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_shadow_exits(path: str = "logs/shadow_exits.csv"):
    with open(path, "r") as f:
        r = csv.DictReader(f)
        return list(r)


def load_chainlink_for_symbol(symbol: str, ts_lo: int, ts_hi: int):
    """Return list of (ts_epoch, price) for symbol within [ts_lo, ts_hi]."""
    out = []
    for f in sorted(glob.glob("logs/chainlink_prices_*.csv")):
        with open(f, "r") as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    ts = float(row["ts_epoch"])
                except Exception:
                    continue
                if ts < ts_lo or ts > ts_hi:
                    continue
                if row["symbol"] != symbol:
                    continue
                try:
                    p = float(row["price"])
                except Exception:
                    continue
                out.append((ts, p))
    out.sort()
    return out


def fetch_clob_history(token_id: str, ts_lo: int, ts_hi: int, fidelity: int = 1):
    url = (
        f"{CLOB_HIST}?market={token_id}"
        f"&startTs={int(ts_lo)}&endTs={int(ts_hi)}&fidelity={int(fidelity)}"
    )
    j = http_get_json(url)
    pts = j.get("history") or j.get("data") or []
    out = []
    for p in pts:
        t = p.get("t") or p.get("timestamp") or p.get("ts")
        v = p.get("p") or p.get("price")
        if t is None or v is None:
            continue
        out.append((float(t), float(v)))
    out.sort()
    return out


def main():
    rows = load_shadow_exits()
    # pick a recent ETH UP market (chainlink covers >May 5 18:00)
    target = None
    for r in rows:
        if r["symbol"] == "ETHUSD" and float(r["entry_ts"]) > 1778100000:
            target = r
            break
    if target is None:
        print("no candidate market found")
        sys.exit(1)

    sym = target["symbol"]
    tok = target["token_id"]
    side = target["side"]
    entry_ts = int(float(target["entry_ts"]))
    exit_ts = int(float(target["exit_ts"]))
    win_end = int(float(target["window_end_ts"]))
    win_start = win_end - 900
    slug = target["contract_slug"]

    print(f"=== market sanity check ===")
    print(f"slug          : {slug}")
    print(f"token_id      : {tok}")
    print(f"symbol/side   : {sym} / {side}")
    print(f"window        : [{win_start}, {win_end}]  (15m)")
    print(f"entry_ts      : {entry_ts}  (offset {entry_ts - win_start}s into window)")
    print(f"exit_ts       : {exit_ts}   (offset {exit_ts - win_start}s into window)")
    print(f"entry_price   : {target['entry_price']}")
    print(f"exit_type     : {target['exit_type']}  exit_price={target['exit_price']}")
    print(f"predicted_won : {target['predicted_side_won']}")
    print()

    # pull both feeds over the full window with a small pad
    pad = 60
    ts_lo = win_start - pad
    ts_hi = win_end + pad

    print(f"fetching CLOB history fidelity=1 over [{ts_lo}, {ts_hi}] ...")
    pm = fetch_clob_history(tok, ts_lo, ts_hi, fidelity=1)
    print(f"  CLOB points: {len(pm)}")
    if pm:
        print(f"  first: ts={pm[0][0]:.0f} p={pm[0][1]:.4f}")
        print(f"  last : ts={pm[-1][0]:.0f} p={pm[-1][1]:.4f}")

    print(f"loading chainlink {sym} over same window ...")
    cl = load_chainlink_for_symbol(sym, ts_lo, ts_hi)
    print(f"  chainlink points: {len(cl)}")
    if cl:
        print(f"  first: ts={cl[0][0]:.0f} p={cl[0][1]:.4f}")
        print(f"  last : ts={cl[-1][0]:.0f} p={cl[-1][1]:.4f}")

    if not pm or not cl:
        print("missing one feed; aborting merge preview")
        return

    # Build a per-second CEX index for fast lookup, then sample at each PM tick.
    # Use last-known CEX price <= t.
    cex_idx = 0
    print()
    print(f"=== merged ticks (PM polymarket price + nearest prior CEX price) ===")
    print(f"{'rel_s':>7s}  {'pm_t':>10s}  {'pm_px':>7s}  {'cex_t':>10s}  {'cex_px':>10s}  {'cex_age_s':>9s}")
    for (t, p) in pm:
        # advance cex_idx to last CEX point with ts <= t
        while cex_idx + 1 < len(cl) and cl[cex_idx + 1][0] <= t:
            cex_idx += 1
        ct, cp = cl[cex_idx]
        rel = t - win_start
        age = t - ct
        print(f"{rel:7.0f}  {t:10.0f}  {p:7.4f}  {ct:10.0f}  {cp:10.4f}  {age:9.1f}")

    # Quick directional check: did CEX move from window_start to entry_ts in the
    # direction the bot bet on?
    win_start_cex = None
    entry_cex = None
    end_cex = None
    for (t, p) in cl:
        if t <= win_start:
            win_start_cex = p
        if t <= entry_ts:
            entry_cex = p
        if t <= win_end:
            end_cex = p
    print()
    print(f"CEX @ window_start: {win_start_cex}")
    print(f"CEX @ entry_ts   : {entry_cex}")
    print(f"CEX @ window_end : {end_cex}")
    if win_start_cex and end_cex:
        actual_dir = "UP" if end_cex > win_start_cex else ("DOWN" if end_cex < win_start_cex else "FLAT")
        print(f"actual market resolution direction (CEX): {actual_dir}  bet={side}  match={actual_dir == side}")


if __name__ == "__main__":
    main()
