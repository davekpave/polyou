"""
Bulk pull merged PM+CEX ticks for every market in logs/shadow_exits.csv.

Output: logs/lag_dataset.csv with columns
  slug, token_id, symbol, side, win_start, win_end,
  entry_ts, exit_ts, entry_price, exit_type, exit_price,
  pm_t, pm_px, cex_t, cex_px, cex_age_s, rel_s

Behaviour:
- Caches each CLOB history response in cache/clob_hist/<token>.json so re-runs
  are free.
- Loads chainlink CSVs once into memory keyed by symbol (sorted).
- Pads window by 60s on each side.
- Skips markets with no chainlink coverage.
"""
import bisect
import csv
import glob
import json
import os
import sys
import time
from collections import defaultdict
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

CLOB_HIST = "https://clob.polymarket.com/prices-history"
CACHE_DIR = "cache/clob_hist"
OUT_PATH = "logs/lag_dataset.csv"
PAD_S = 60
SLEEP_BETWEEN_HTTP_S = 0.10


def http_get_json(url: str, timeout: float = 20.0):
    req = Request(url, headers={"User-Agent": "polyou-research/0.1"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_clob_history_cached(token_id: str, ts_lo: int, ts_hi: int):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = f"{token_id}_{ts_lo}_{ts_hi}.json"
    path = os.path.join(CACHE_DIR, key)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    url = (
        f"{CLOB_HIST}?market={token_id}"
        f"&startTs={int(ts_lo)}&endTs={int(ts_hi)}&fidelity=1"
    )
    for attempt in range(4):
        try:
            j = http_get_json(url)
            with open(path, "w") as f:
                json.dump(j, f)
            time.sleep(SLEEP_BETWEEN_HTTP_S)
            return j
        except (URLError, HTTPError) as e:
            wait = 1.0 * (2 ** attempt)
            print(f"  http err ({e}); sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url}")


def parse_clob_points(j):
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


def load_chainlink_all():
    """Return dict[symbol] -> (sorted_ts_list, sorted_price_list)."""
    by_sym_ts = defaultdict(list)
    by_sym_px = defaultdict(list)
    for f in sorted(glob.glob("logs/chainlink_prices_*.csv")):
        with open(f, "r") as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    ts = float(row["ts_epoch"])
                    p = float(row["price"])
                except Exception:
                    continue
                sym = row["symbol"]
                by_sym_ts[sym].append(ts)
                by_sym_px[sym].append(p)
    # sort each
    out = {}
    for sym in by_sym_ts:
        pairs = sorted(zip(by_sym_ts[sym], by_sym_px[sym]))
        ts = [p[0] for p in pairs]
        px = [p[1] for p in pairs]
        out[sym] = (ts, px)
    return out


def cex_at(cex, t):
    """Return (cex_t, cex_px, age_s) for last CEX point with ts <= t. None if before first."""
    ts, px = cex
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return (ts[i], px[i], t - ts[i])


def main():
    rows = list(csv.DictReader(open("logs/shadow_exits.csv")))
    print(f"shadow_exits rows: {len(rows)}")

    print("loading chainlink ...")
    cex_by_sym = load_chainlink_all()
    for sym, (ts, _) in cex_by_sym.items():
        print(f"  {sym:6s} n={len(ts)} ts=[{ts[0]:.0f},{ts[-1]:.0f}]")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out_f = open(OUT_PATH, "w", newline="")
    w = csv.writer(out_f)
    w.writerow([
        "slug", "token_id", "symbol", "side", "win_start", "win_end",
        "entry_ts", "exit_ts", "entry_price", "exit_type", "exit_price",
        "pm_t", "pm_px", "cex_t", "cex_px", "cex_age_s", "rel_s",
    ])

    n_total = 0
    n_with_data = 0
    n_skipped_no_cex = 0
    n_skipped_no_pm = 0
    pm_pts_total = 0

    for i, r in enumerate(rows):
        sym = r["symbol"]
        tok = r["token_id"]
        side = r["side"]
        slug = r["contract_slug"]
        try:
            entry_ts = int(float(r["entry_ts"]))
            exit_ts = int(float(r["exit_ts"]))
            win_end = int(float(r["window_end_ts"]))
        except Exception:
            continue
        win_start = win_end - 900
        ts_lo = win_start - PAD_S
        ts_hi = win_end + PAD_S

        n_total += 1
        if sym not in cex_by_sym:
            n_skipped_no_cex += 1
            continue
        cex = cex_by_sym[sym]
        # Need overlapping CEX coverage
        if cex[0][0] > ts_hi or cex[0][-1] < ts_lo:
            n_skipped_no_cex += 1
            continue

        try:
            j = fetch_clob_history_cached(tok, ts_lo, ts_hi)
        except Exception as e:
            print(f"  [{i}] {slug} fetch failed: {e}", file=sys.stderr)
            continue
        pm = parse_clob_points(j)
        if not pm:
            n_skipped_no_pm += 1
            continue

        n_with_data += 1
        for (t, p) in pm:
            res = cex_at(cex, t)
            if res is None:
                continue
            ct, cp, age = res
            rel = t - win_start
            w.writerow([
                slug, tok, sym, side, win_start, win_end,
                entry_ts, exit_ts, r["entry_price"], r["exit_type"], r["exit_price"],
                f"{t:.0f}", f"{p:.6f}", f"{ct:.3f}", f"{cp:.6f}", f"{age:.2f}", f"{rel:.0f}",
            ])
            pm_pts_total += 1

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(rows)}] with_data={n_with_data} no_cex={n_skipped_no_cex} no_pm={n_skipped_no_pm} pm_pts={pm_pts_total}")

    out_f.close()
    print()
    print(f"DONE")
    print(f"  total markets         : {n_total}")
    print(f"  with merged data      : {n_with_data}")
    print(f"  skipped (no cex cov.) : {n_skipped_no_cex}")
    print(f"  skipped (no pm hist.) : {n_skipped_no_pm}")
    print(f"  total PM ticks emitted: {pm_pts_total}")
    print(f"  output                : {OUT_PATH}")


if __name__ == "__main__":
    main()
