import logging
from typing import Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo

from polyou.utils.telegram_notifier import send_telegram_message

logger = logging.getLogger("alerts")

ET = ZoneInfo("America/New_York")


def emit_alert(payload: Dict[str, Any]) -> None:

    try:
        ts = payload["timestamp"]
    except KeyError as e:
        raise RuntimeError(f"Missing required alert field: {e}")

    decision_type = payload.get("decision_type")

    ts_str = datetime.fromtimestamp(ts, tz=ET).strftime("%Y-%m-%d %H:%M:%S ET")

    # --------------------------------------------------
    # NO TRADE branch (no side required)
    # --------------------------------------------------
    if decision_type == "NO_TRADE":

        reason = payload.get("reason", "unknown")

        lines = [
            "⚪ NO TRADE",
            f"Time : {ts_str}",
            "Symbol : MULTI-ASSET",
            f"Reason : {reason}",
            f"Quality : {payload.get('signal_quality')}",
            f"Phase : {payload.get('signal_phase')}",
        ]

        message = "\n".join(lines)

        print(message)
        send_telegram_message(message)

        logger.info(
            "ALERT_NO_TRADE | "
            f"time={ts_str} | "
            f"reason={reason} | "
            f"signal_quality={payload.get('signal_quality')} | "
            f"signal_phase={payload.get('signal_phase')}"
        )

        return

    # --------------------------------------------------
    # TRADE branch (side required)
    # --------------------------------------------------
    try:
        symbol = payload["symbol"]
        side = payload["side"]
        contract = payload.get("contract")
    except KeyError as e:
        raise RuntimeError(f"Missing required alert field: {e}")

    if side not in {"UP", "DOWN"}:
        raise RuntimeError(f"Invalid side value: {side}")

    price = payload.get("price")
    anchor_price = payload.get("anchor_price")
    reason = payload.get("reason", "polyou_signal")

    side_label = "BUY UP" if side == "UP" else "BUY DOWN"
    emoji = "🟡"

    if isinstance(price, (int, float)):
        price_line = f"Oracle px : {price:.6f}"
    else:
        price_line = "Oracle px : na"

    quality = payload.get("signal_quality")
    pvr = payload.get("percent_vol_ratio")
    stability = payload.get("stability_ok")
    phase_val = payload.get("signal_phase")

    slug = contract.get("slug") if isinstance(contract, dict) else None

    lines = [
        f"{emoji} TRADE — {side_label}",
        f"Time : {ts_str}",
        f"Symbol : {symbol}",
        f"Market : {slug or 'N/A'}",
        price_line,
        f"Quality : {quality}",
        f"PVR : {pvr}",
        f"Phase : {phase_val}",
        f"Stable : {stability}",
        f"Resolution : end vs start (Chainlink, 15m ET)",
        f"Reason : {reason}",
    ]

    message = "\n".join(lines)

    print(message)
    send_telegram_message(message)

    def safe_delta(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a - b
        return "na"

    logger.info(
        "ALERT_FORENSIC | "
        f"symbol={symbol} | "
        f"side={side} | "
        f"price={price} | "
        f"anchor_price={anchor_price} | "
        f"delta_vs_anchor={safe_delta(price, anchor_price)} | "
        f"fair={payload.get('fair')} | "
        f"percent_move={payload.get('percent_move')} | "
        f"distance_z={payload.get('distance_z')} | "
        f"edge_z={payload.get('edge_z')} | "
        f"slope_z={payload.get('slope_z')} | "
        f"slope_z_24h={payload.get('slope_z_24h')} | "
        f"raw_vol_4h={payload.get('raw_vol')} | "
        f"adaptive_floor_4h={payload.get('adaptive_floor')} | "
        f"volatility_used_4h={payload.get('volatility')} | "
        f"structure_vol_24h={payload.get('structure_vol')} | "
        f"vol_ratio={payload.get('vol_ratio')} | "
        f"percent_vol_ratio={payload.get('percent_vol_ratio')} | "
        f"extension_pressure={payload.get('extension_pressure')} | "
        f"adaptive_drift_cap={payload.get('adaptive_drift_cap')} | "
        f"continuation_override={payload.get('continuation_override')} | "
        f"acceleration_ok={payload.get('acceleration_ok')} | "
        f"time={ts_str}"
    )

