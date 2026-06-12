"""
Leader auto-rebalancer.

Runs once daily (via systemd timer at 04:00 UTC).  Reads the paper bot's
shadow exits, scores every leader on their last-30 filtered DOWN trades, and
rewrites COPY_WHITELIST in /root/polyou/.env, then restarts polyou-bot.

Rules
-----
Scoring window  : last-30 filtered DOWN trades (price>=0.30, not in skip hours)
Eligibility     : >=20 filtered trades total AND last exit within 5 days
Whitelist size  : top 3 eligible; run with fewer if fewer qualify (EV > 0)
Demotion        : rolling-30 EV < 0.0  → drop from whitelist
Promotion       : rolling-30 EV >= 0.05 AND meets eligibility
Rebalance time  : called externally at 04:00 UTC by systemd timer
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# ------------------------------------------------------------------
# Config (all overridable via env)
# ------------------------------------------------------------------
SHADOW_FILE     = os.getenv("REBAL_SHADOW_FILE",  "/root/polyou/logs/paper_shadow_exits.csv")
SHADOW_FILE_AUX = os.getenv("REBAL_SHADOW_FILE_AUX", "/root/polyou/logs/live_shadow_exits.csv")
ENV_FILE        = os.getenv("REBAL_ENV_FILE",      "/root/polyou/.env")
OOS_FILE        = os.getenv("REBAL_OOS_FILE",      "/root/polyou/logs/oos_top_traders.csv")
SERVICE_NAME    = os.getenv("REBAL_SERVICE",       "polyou-bot")
REBAL_LOG       = os.getenv("REBAL_LOG",           "/root/polyou/logs/rebalancer.log")

ROLLING_N       = int(os.getenv("REBAL_ROLLING_N",       "30"))
MIN_TRADES      = int(os.getenv("REBAL_MIN_TRADES",       "20"))
MAX_INACTIVE_D  = int(os.getenv("REBAL_MAX_INACTIVE_DAYS", "5"))
MAX_WHITELIST   = int(os.getenv("REBAL_MAX_WHITELIST",     "3"))
DEMOTION_EV     = float(os.getenv("REBAL_DEMOTION_EV",   "0.0"))
PROMOTION_EV    = float(os.getenv("REBAL_PROMOTION_EV",  "0.05"))

# Per-leader skip hours: hours where a leader has >=N trades with EV below threshold
LEADER_SKIP_HOURS_FILE  = os.getenv("REBAL_SKIP_HOURS_FILE", "/root/polyou/logs/leader_skip_hours.json")
SKIP_HOUR_MIN_N         = int(os.getenv("REBAL_SKIP_HOUR_MIN_N", "3"))
SKIP_HOUR_EV_THRESHOLD  = float(os.getenv("REBAL_SKIP_HOUR_EV_THRESHOLD", "-0.05"))
MIN_PRICE: float = 0.30


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _log(msg: str) -> None:
    import datetime as _dt
    ts = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(REBAL_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _read_shadow(path: str) -> dict[str, list[dict]]:
    """Return {address: [filtered trade dicts]} from shadow CSV."""
    by_leader: dict[str, list[dict]] = defaultdict(list)
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("side", "").strip() != "DOWN":
                    continue
                try:
                    ep = float(row["entry_price"])
                    h = int(row["ts_iso"][11:13])
                    if ep < MIN_PRICE or h in SKIP_HOURS:
                        continue
                    addr = row["leader_address"].strip().lower()
                    trade_date = row["ts_iso"][:10]
                    pnl = float(row["true_pnl"])
                    by_leader[addr].append({"date": trade_date, "pnl": pnl, "hour": h})
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        _log(f"WARNING: shadow file not found: {path}")
    return by_leader


def _score(trades: list[dict]) -> float:
    """Mean PnL of the last ROLLING_N trades."""
    window = trades[-ROLLING_N:]
    return sum(t["pnl"] for t in window) / len(window)


def _compute_leader_skip_hours(
    by_leader: dict[str, list[dict]],
) -> dict[str, list[int]]:
    """Return {addr: [bad_utc_hours]} derived from unfiltered paper trades.

    A UTC hour is marked bad for a leader when they have >= SKIP_HOUR_MIN_N
    settled trades in that hour and the mean PnL is below SKIP_HOUR_EV_THRESHOLD.
    """
    result: dict[str, list[int]] = {}
    for addr, trades in by_leader.items():
        hour_pnls: dict[int, list[float]] = defaultdict(list)
        for t in trades:
            h = t.get("hour")
            if h is not None:
                hour_pnls[h].append(t["pnl"])
        bad = [
            h for h, pnls in hour_pnls.items()
            if len(pnls) >= SKIP_HOUR_MIN_N
            and sum(pnls) / len(pnls) < SKIP_HOUR_EV_THRESHOLD
        ]
        result[addr] = sorted(bad)
    return result


def _write_skip_hours(skip_hours: dict[str, list[int]], path: str) -> None:
    import json as _json
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(skip_hours, f, indent=2)


def _read_current_whitelist(env_path: str) -> list[str]:
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^COPY_WHITELIST\s*=\s*(.*)$", line.strip())
                if m:
                    val = m.group(1).strip()
                    return [a.strip().lower() for a in val.split(",") if a.strip()]
    except FileNotFoundError:
        pass
    return []


def _write_whitelist(env_path: str, new_wl: list[str]) -> None:
    with open(env_path, encoding="utf-8") as f:
        lines = f.readlines()

    new_val = ",".join(new_wl)
    found = False
    out = []
    for line in lines:
        if re.match(r"^COPY_WHITELIST\s*=", line):
            out.append(f"COPY_WHITELIST={new_val}\n")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"COPY_WHITELIST={new_val}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(out)


def _restart_service(name: str) -> None:
    try:
        result = subprocess.run(
            ["systemctl", "restart", name],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            _log(f"Restarted {name}")
        else:
            _log(f"ERROR restarting {name}: {result.stderr.strip()}")
    except Exception as e:
        _log(f"ERROR restarting {name}: {e}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    _log("=== Rebalancer starting ===")

    today = date.today()
    cutoff = (today - timedelta(days=MAX_INACTIVE_D)).isoformat()

    by_leader = _read_shadow(SHADOW_FILE)
    # Merge auxiliary shadow file (e.g. live_shadow_exits.csv) so historical
    # data from before the paper bot started is included in scoring.
    if SHADOW_FILE_AUX and SHADOW_FILE_AUX != SHADOW_FILE:
        aux = _read_shadow(SHADOW_FILE_AUX)
        for addr, trades in aux.items():
            by_leader[addr].extend(trades)
        # Re-sort each leader's trades by date after merging
        for addr in by_leader:
            by_leader[addr].sort(key=lambda t: t["date"])
    _log(f"Shadow file: {len(by_leader)} leaders tracked")

    # Compute per-leader skip hours from raw data and write JSON for the live bot
    leader_skip = _compute_leader_skip_hours(by_leader)
    _write_skip_hours(leader_skip, LEADER_SKIP_HOURS_FILE)
    total_bad = sum(len(v) for v in leader_skip.values())
    _log(f"Wrote per-leader skip hours: {total_bad} bad hours across {len(leader_skip)} leaders → {LEADER_SKIP_HOURS_FILE}")

    # Filter each leader's trades using their own skip hours before scoring
    for addr in list(by_leader.keys()):
        skip = set(leader_skip.get(addr, []))
        if skip:
            by_leader[addr] = [t for t in by_leader[addr] if t.get("hour") not in skip]

    current_wl = _read_current_whitelist(ENV_FILE)
    _log(f"Current whitelist: {current_wl}")

    # Score every leader that has enough trades
    candidates: list[tuple[float, str]] = []
    for addr, trades in by_leader.items():
        if len(trades) < MIN_TRADES:
            continue
        last_date = max(t["date"] for t in trades)
        if last_date < cutoff:
            continue  # inactive
        ev = _score(trades)
        candidates.append((ev, addr))
        _log(f"  {addr[:12]}  rolling_ev={ev:+.4f}  n={len(trades)}  last={last_date}")

    candidates.sort(reverse=True)

    # Promote top leaders with EV >= PROMOTION_EV, up to MAX_WHITELIST
    new_wl: list[str] = []
    for ev, addr in candidates:
        if len(new_wl) >= MAX_WHITELIST:
            break
        if ev >= PROMOTION_EV:
            new_wl.append(addr)

    _log(f"New whitelist ({len(new_wl)}): {new_wl}")

    if not new_wl:
        _log("WARNING: No leaders qualified — keeping current whitelist unchanged")
        return

    if sorted(new_wl) == sorted(current_wl):
        _log("No change needed — skipping restart")
        return

    _write_whitelist(ENV_FILE, new_wl)
    _log(f"Wrote COPY_WHITELIST to {ENV_FILE}")

    _restart_service(SERVICE_NAME)
    _log("=== Rebalancer done ===")


if __name__ == "__main__":
    main()
