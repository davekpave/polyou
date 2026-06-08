"""
Decision email sender.

This module emits the FINAL decision email (system-of-record).
"""

import os
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

logger = logging.getLogger("decision_email")


# --------------------------------------------------
# Configuration
# --------------------------------------------------

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

SENDER_EMAIL = "davekpave@gmail.com"
RECIPIENT_EMAIL = "davekpave@gmail.com"

SMTP_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

if not SMTP_APP_PASSWORD:
    logger.warning(
        "GMAIL_APP_PASSWORD not set — Decision emails will NOT be sent"
    )


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _safe(v):
    return "na" if v is None else v


def _fmt_ts(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=ET) if ET else datetime.utcfromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S ET")


def _send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.set_content(body.strip())

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls()
        server.login(SENDER_EMAIL, SMTP_APP_PASSWORD)
        server.send_message(msg)


# --------------------------------------------------
# DECISION EMAIL
# --------------------------------------------------

def send_decision_email(
    *,
    symbol: str,
    side: str,
    contract_slug: str,
    window_start_ts: int,
    window_end_ts: int,
    decision_ts: float,
    metrics: dict,
) -> None:

    if not SMTP_APP_PASSWORD:
        return

    try:
        decision_type = metrics.get("decision_type")

        # Subject
        if decision_type == "NO_TRADE":
            subject = "[DECISION] NO TRADE"
        else:
            subject = f"[DECISION] {symbol} — BUY {side}"

        # Header fields
        if decision_type == "NO_TRADE":
            symbol_line = "MULTI-ASSET"
            decision_line = "NO TRADE"
        else:
            symbol_line = symbol
            decision_line = f"BUY {side}"

        decision_time = _fmt_ts(decision_ts)
        window_start = _fmt_ts(window_start_ts)
        window_end = _fmt_ts(window_end_ts)

        contract_slug = contract_slug or "N/A"

        # Candidates block
        candidates_block = ""
        if metrics.get("all_candidates"):
            lines = []
            for c in metrics["all_candidates"]:
                try:
                    lines.append(
                        f"{c['symbol']:6} | q={c['quality']:.2f} | p={c['priority']:.2f} | "
                        f"pvr={c['pvr']:.2f} | stable={c['stability_ok']}"
                    )
                except (KeyError, TypeError, ValueError):
                    lines.append(str(c))
            candidates_block = "\n\nCandidates\n----------\n" + "\n".join(lines)

        body = f"""
DECISION SNAPSHOT

Symbol : {symbol_line}
Decision : {decision_line}
Decision time : {decision_time}

Market
------
Contract slug : {contract_slug}
Resolution : End price vs Start price (Chainlink, 15m)
Window start : {window_start}
Window end : {window_end}

Prices at decision
------------------
Oracle price : {_safe(metrics.get('price'))}
Anchor price : {_safe(metrics.get('anchor_price'))}
Distance from anchor (%) : {_safe(metrics.get('anchor_distance_percent'))}
Snapshot price : {_safe(metrics.get('snapshot_price'))}
Signal R:R : {_safe(metrics.get('signal_rr'))}
Signal age (minutes) : {_safe(metrics.get('signal_age_minutes'))}
Signal phase (0–1) : {_safe(metrics.get('signal_phase'))}

Signal scoring
--------------
signal_quality : {_safe(metrics.get('signal_quality'))}
signal_priority : {_safe(metrics.get('signal_priority'))}

Computed metrics
----------------
edge_z : {_safe(metrics.get('edge_z'))}
slope_z : {_safe(metrics.get('slope_z'))}
slope_z_24h : {_safe(metrics.get('slope_z_24h'))}
percent_move : {_safe(metrics.get('percent_move'))}
distance_z : {_safe(metrics.get('distance_z'))}

Volatility diagnostics
----------------------
raw_vol (4H) : {_safe(metrics.get('raw_vol'))}
adaptive_floor (4H) : {_safe(metrics.get('adaptive_floor'))}
volatility_used (4H) : {_safe(metrics.get('volatility'))}
structure_vol (24H) : {_safe(metrics.get('structure_vol'))}

Exhaustion diagnostics
----------------------
vol_ratio : {_safe(metrics.get('vol_ratio'))}
percent_vol_ratio : {_safe(metrics.get('percent_vol_ratio'))}

Drift diagnostics
-----------------
extension_pressure : {_safe(metrics.get('extension_pressure'))}
adaptive_drift_cap : {_safe(metrics.get('adaptive_drift_cap'))}

Phase diagnostics
-----------------
pvr_ideal : {_safe(metrics.get('pvr_ideal'))}
pvr_terminal : {_safe(metrics.get('pvr_terminal'))}

Hybrid override
---------------
continuation_override : {_safe(metrics.get('continuation_override'))}

Gates passed
------------
slope_ok : {_safe(metrics.get('slope_ok'))}
acceleration_ok : {_safe(metrics.get('acceleration_ok'))}
percent_ok : {_safe(metrics.get('percent_ok'))}
distance_ok : {_safe(metrics.get('distance_ok'))}
exhaustion_ok : {_safe(metrics.get('exhaustion_ok'))}
drift_ok : {_safe(metrics.get('drift_ok'))}
candle_ok : {_safe(metrics.get('candle_ok'))}
structure_alignment_ok : {_safe(metrics.get('structure_alignment_ok'))}
stability_ok : {_safe(metrics.get('stability_ok'))}
""" + candidates_block + """

NOTE:
This email records a system decision event.
The system evaluates all assets and makes exactly one decision per window.
"""

        _send_email(subject, body)

        if decision_type == "NO_TRADE":
            logger.info(
                "[DECISION EMAIL SENT] NO_TRADE | window_end_ts=%s",
                window_end_ts,
            )
        else:
            logger.info(
                "[DECISION EMAIL SENT] %s | %s | window_end_ts=%s",
                symbol,
                side,
                window_end_ts,
            )

    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        logger.exception("[DECISION EMAIL FAILED - Network/SMTP error]: %s", e)
    except (KeyError, TypeError, ValueError) as e:
        logger.exception("[DECISION EMAIL FAILED - Data formatting error]: %s", e)
