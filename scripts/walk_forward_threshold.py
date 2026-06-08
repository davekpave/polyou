"""Walk-forward harness for the rr_single_threshold knob.

Splits logs/rr_blocks_resolved.csv chronologically into K folds. For each
fold k>=1, picks the threshold T that maximises mean EV/$ on folds [0..k-1]
and reports the OOS EV/$, win-rate, and trade count on fold k.

This is a SANITY tool, not a tuning recommendation. Do NOT lower the live
threshold based on a single run. Pre-commit your decision rule before
looking at the OOS numbers, per the discipline plan.

Usage:
    .venv/Scripts/python.exe scripts/walk_forward_threshold.py
    .venv/Scripts/python.exe scripts/walk_forward_threshold.py --folds 8
    .venv/Scripts/python.exe scripts/walk_forward_threshold.py --by symbol_side
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

RR_PATH = Path("logs/rr_blocks_resolved.csv")
DEFAULT_FOLDS = 6
# Candidate thresholds to scan (signal_rr cutoff: take if signal_rr >= T).
CANDIDATES = [round(0.05 * i, 2) for i in range(1, 16)]  # 0.05 .. 0.75
MIN_FOLD_TRADES = 30  # below this, treat fold result as "n/a"


def _load(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("would_have_won") not in ("0", "1"):
                continue
            try:
                ev = float(r["payoff_per_dollar"])
                rr = float(r.get("signal_rr") or "nan")
            except ValueError:
                continue
            if math.isnan(ev) or math.isnan(rr):
                continue
            rows.append({
                "ts": r.get("ts_iso", ""),
                "symbol": r.get("symbol", ""),
                "side": r.get("side", ""),
                "rr": rr,
                "ev": ev,
                "won": int(r["would_have_won"] == "1"),
            })
    rows.sort(key=lambda x: x["ts"])
    return rows


def _score(rows, threshold: float):
    taken = [r for r in rows if r["rr"] >= threshold]
    n = len(taken)
    if n == 0:
        return 0, 0.0, 0.0
    ev = sum(r["ev"] for r in taken) / n
    wr = sum(r["won"] for r in taken) / n
    return n, ev, wr


def _best_threshold(rows, min_n: int) -> tuple[float, float]:
    best_t, best_ev = CANDIDATES[0], -1e9
    for t in CANDIDATES:
        n, ev, _ = _score(rows, t)
        if n < min_n:
            continue
        if ev > best_ev:
            best_t, best_ev = t, ev
    return best_t, best_ev


def _walk_forward(rows, folds: int, label: str) -> None:
    if len(rows) < folds * 2:
        print(f"[{label}] not enough rows ({len(rows)}) for {folds} folds")
        return
    fold_size = len(rows) // folds
    print(f"\n=== walk-forward ({label}, n={len(rows)}, folds={folds}, fold_size~{fold_size}) ===")
    print(f"{'fold':<5} {'fit_T':>6} {'fit_EV':>9} {'oos_n':>7} {'oos_win%':>9} {'oos_EV':>9}")
    oos_evs = []
    for k in range(1, folds):
        train = rows[: k * fold_size]
        test = rows[k * fold_size : (k + 1) * fold_size]
        # Require at least 1% of train hit rate (or 30) so we don't pick
        # extreme thresholds on tiny samples.
        min_n_train = max(MIN_FOLD_TRADES, len(train) // 100)
        t, fit_ev = _best_threshold(train, min_n_train)
        n_test, ev_test, wr_test = _score(test, t)
        if n_test < MIN_FOLD_TRADES:
            print(f"{k:<5} {t:>6.2f} {fit_ev:>+9.4f} {n_test:>7} {'n/a':>9} {'n/a':>9}")
            continue
        oos_evs.append(ev_test)
        print(f"{k:<5} {t:>6.2f} {fit_ev:>+9.4f} {n_test:>7} {wr_test*100:>8.1f}% {ev_test:>+9.4f}")
    if oos_evs:
        avg = sum(oos_evs) / len(oos_evs)
        worst = min(oos_evs)
        print(f"avg OOS EV/$ = {avg:+.4f}   worst fold = {worst:+.4f}   (positive => threshold drop survived OOS on average)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--by", choices=["overall", "symbol_side"], default="overall")
    args = parser.parse_args()

    if not RR_PATH.exists():
        print(f"missing {RR_PATH}; run scripts/resolve_decision_outcomes.py first")
        return

    rows = _load(RR_PATH)
    print(f"loaded {len(rows)} resolved rr_blocks rows")

    if args.by == "overall":
        _walk_forward(rows, args.folds, "overall")
    else:
        groups: dict = {}
        for r in rows:
            groups.setdefault((r["symbol"], r["side"]), []).append(r)
        for key in sorted(groups.keys()):
            _walk_forward(groups[key], args.folds, f"{key[0]}/{key[1]}")

    print("\nReminder: pre-commit your decision rule (e.g. 'lower threshold only if avg OOS EV/$ > +0.01 AND no fold worse than -0.02') BEFORE acting on this output.")


if __name__ == "__main__":
    main()
