"""Calibration report — does signal quality / RR / regime actually predict win rate?

Consumes:
  logs/decision_log_resolved.csv  (produced by resolve_decision_outcomes.py)
  logs/gate_blocks_resolved.csv   (ditto)
  logs/shadow_exits.csv           (paper-fill realized P&L, optional)

Produces (stdout + logs/derived/calibration_report.txt):
  1. Win rate by signal_quality bucket (quintiles)
  2. Win rate by signal_rr bucket
  3. Win rate by regime
  4. Per-gate counterfactual: of signals BLOCKED by each gate, what % would
     have won? (gate "saved-loss" estimate)
  5. Shadow paper P&L summary if shadow_exits.csv is present.

Read-only; safe to run while the bot is up.

Usage:
    .venv\\Scripts\\python.exe scripts\\calibration_report.py
"""

from __future__ import annotations

import csv
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

LOGS_DIR = "logs"
DERIVED_DIR = os.path.join(LOGS_DIR, "derived")
DECISION_RESOLVED = os.path.join(LOGS_DIR, "decision_log_resolved.csv")
GATE_RESOLVED = os.path.join(LOGS_DIR, "gate_blocks_resolved.csv")
SHADOW_EXITS = os.path.join(LOGS_DIR, "shadow_exits.csv")
OUT_PATH = os.path.join(DERIVED_DIR, "calibration_report.txt")


def _f(s: str) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _read(path: str) -> List[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _quantile_buckets(values: List[float], n: int = 5) -> List[Tuple[float, float]]:
    """Return n consecutive (lo, hi) bins covering quantiles of `values`."""
    if not values:
        return []
    vs = sorted(values)
    edges = [vs[int(i * len(vs) / n)] for i in range(n)] + [vs[-1]]
    bins: List[Tuple[float, float]] = []
    for i in range(n):
        bins.append((edges[i], edges[i + 1]))
    return bins


def _bucket_idx(value: float, bins: List[Tuple[float, float]]) -> Optional[int]:
    if value is None or not bins:
        return None
    for i, (lo, hi) in enumerate(bins):
        if value <= hi:
            return i
    return len(bins) - 1


def _winrate(rows: List[dict]) -> Tuple[int, int, float, float]:
    n = 0
    wins = 0
    payoff_sum = 0.0
    for r in rows:
        won = r.get("would_have_won", "")
        payoff = _f(r.get("payoff_per_dollar", ""))
        if won not in ("0", "1"):
            continue
        n += 1
        if won == "1":
            wins += 1
        if payoff is not None:
            payoff_sum += payoff
    wr = wins / n if n else 0.0
    avg_payoff = payoff_sum / n if n else 0.0
    return n, wins, wr, avg_payoff


def report_overall(decisions: List[dict], lines: List[str]) -> None:
    n, wins, wr, ev = _winrate(decisions)
    lines.append(f"=== OVERALL (decision_log_resolved) ===")
    lines.append(f"resolved rows: {n}  wins: {wins}  win_rate: {wr:.3f}  EV/$: {ev:+.4f}")
    lines.append("")


def report_bucketed(
    rows: List[dict],
    *,
    field: str,
    label: str,
    n_buckets: int,
    lines: List[str],
) -> None:
    vals: List[Tuple[float, dict]] = []
    for r in rows:
        v = _f(r.get(field, ""))
        if v is None:
            continue
        if r.get("would_have_won", "") not in ("0", "1"):
            continue
        vals.append((v, r))
    if not vals:
        lines.append(f"=== WR by {label} ===  (no data)\n")
        return
    just_v = [v for v, _ in vals]
    bins = _quantile_buckets(just_v, n=n_buckets)
    grouped: Dict[int, List[dict]] = defaultdict(list)
    for v, r in vals:
        idx = _bucket_idx(v, bins)
        if idx is not None:
            grouped[idx].append(r)
    lines.append(f"=== WR by {label} ({n_buckets} quantile buckets) ===")
    lines.append(f"{'bucket':<10} {'range':<25} {'n':>6} {'wins':>6} {'wr':>8} {'EV/$':>10}")
    for i in range(n_buckets):
        rs = grouped.get(i, [])
        n, wins, wr, ev = _winrate(rs)
        lo, hi = bins[i]
        lines.append(f"{i:<10} {f'[{lo:.4f}, {hi:.4f}]':<25} {n:>6} {wins:>6} {wr:>8.3f} {ev:>+10.4f}")
    lines.append("")


def report_categorical(
    rows: List[dict],
    *,
    field: str,
    label: str,
    lines: List[str],
) -> None:
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("would_have_won", "") not in ("0", "1"):
            continue
        key = r.get(field, "") or "(empty)"
        grouped[key].append(r)
    if not grouped:
        lines.append(f"=== WR by {label} ===  (no data)\n")
        return
    lines.append(f"=== WR by {label} ===")
    lines.append(f"{label:<25} {'n':>6} {'wins':>6} {'wr':>8} {'EV/$':>10}")
    for key in sorted(grouped.keys(), key=lambda k: -len(grouped[k])):
        rs = grouped[key]
        n, wins, wr, ev = _winrate(rs)
        lines.append(f"{str(key)[:25]:<25} {n:>6} {wins:>6} {wr:>8.3f} {ev:>+10.4f}")
    lines.append("")


def report_gate_efficacy(blocks: List[dict], lines: List[str]) -> None:
    """For each gate that fired a block, show would_have_won rate of those
    blocks. A gate is 'saving losses' when its blocked-rows WR is well below
    overall traded WR."""
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for r in blocks:
        if r.get("would_have_won", "") not in ("0", "1"):
            continue
        gate = r.get("gate_name", "") or "(unknown)"
        grouped[gate].append(r)
    if not grouped:
        lines.append("=== Gate efficacy ===  (no resolved blocks)\n")
        return
    lines.append("=== Gate efficacy: of signals BLOCKED by each gate, what fraction would have won? ===")
    lines.append("(Lower wr_if_passed => gate is correctly suppressing losers.)")
    lines.append(f"{'gate':<30} {'n':>7} {'would_win':>10} {'wr_if_passed':>14} {'avg_EV/$':>10}")
    for gate, rs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        n, wins, wr, ev = _winrate(rs)
        lines.append(f"{gate[:30]:<30} {n:>7} {wins:>10} {wr:>14.3f} {ev:>+10.4f}")
    lines.append("")


def report_shadow(lines: List[str]) -> None:
    rows = _read(SHADOW_EXITS)
    if not rows:
        lines.append("=== Shadow paper P&L ===  (no shadow_exits.csv)\n")
        return
    n = len(rows)
    profits = [v for v in (_f(r.get("profit_per_share", "")) for r in rows) if v is not None]
    if not profits:
        lines.append("=== Shadow paper P&L ===  (no profit data)\n")
        return
    wins = sum(1 for p in profits if p > 0)
    total = sum(profits)
    avg = total / len(profits)
    lines.append("=== Shadow paper P&L (assumes fill at snapshot, fees=0) ===")
    lines.append(f"closed positions: {n}  wins: {wins}  wr: {wins/n:.3f}")
    lines.append(f"total profit/share (sum): {total:+.4f}")
    lines.append(f"avg profit/share        : {avg:+.4f}")
    if len(profits) >= 2:
        lines.append(f"stdev profit/share      : {statistics.stdev(profits):.4f}")
    # Bucket by signal_quality if present
    qual_rows = [(_f(r.get("signal_quality", "")), _f(r.get("profit_per_share", ""))) for r in rows]
    qual_rows = [(q, p) for q, p in qual_rows if q is not None and p is not None]
    if qual_rows:
        qs = sorted(q for q, _ in qual_rows)
        edges = [qs[int(i * len(qs) / 5)] for i in range(5)] + [qs[-1]]
        lines.append("")
        lines.append("Shadow P&L by signal_quality quintile:")
        lines.append(f"{'bucket':<8} {'range':<25} {'n':>6} {'wr':>8} {'avg/$':>10}")
        for i in range(5):
            lo, hi = edges[i], edges[i + 1]
            sub = [(q, p) for q, p in qual_rows if lo <= q <= hi]
            if not sub:
                continue
            sub_wins = sum(1 for _, p in sub if p > 0)
            sub_avg = sum(p for _, p in sub) / len(sub)
            sub_wr = sub_wins / len(sub)
            lines.append(f"{i:<8} {f'[{lo:.0f}, {hi:.0f}]':<25} {len(sub):>6} {sub_wr:>8.3f} {sub_avg:>+10.4f}")
    lines.append("")


def main() -> int:
    decisions = _read(DECISION_RESOLVED)
    blocks = _read(GATE_RESOLVED)

    lines: List[str] = []
    lines.append("CALIBRATION REPORT")
    lines.append("=" * 60)
    lines.append("")

    if decisions:
        report_overall(decisions, lines)
        report_bucketed(decisions, field="signal_quality", label="signal_quality", n_buckets=5, lines=lines)
        report_bucketed(decisions, field="signal_rr", label="signal_rr", n_buckets=5, lines=lines)
        report_categorical(decisions, field="regime", label="regime", lines=lines)
        report_categorical(decisions, field="symbol", label="symbol", lines=lines)
        report_categorical(decisions, field="side", label="side", lines=lines)
    else:
        lines.append(f"(no {DECISION_RESOLVED} found — run resolve_decision_outcomes.py first)\n")

    if blocks:
        report_gate_efficacy(blocks, lines)
    else:
        lines.append(f"(no {GATE_RESOLVED} found — run resolve_decision_outcomes.py first)\n")

    report_shadow(lines)

    text = "\n".join(lines)
    print(text)

    try:
        os.makedirs(DERIVED_DIR, exist_ok=True)
        with open(OUT_PATH, "w") as f:
            f.write(text)
        print(f"\nReport saved to {OUT_PATH}")
    except Exception as exc:
        print(f"WARN: could not save report: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
