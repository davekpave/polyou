import time
import logging

from polyou.utils.decision_email import send_decision_email

logging.basicConfig(level=logging.INFO)

print("Sending DECISION test email...")

now_ts = time.time()

send_decision_email(
    symbol="TEST",
    side="DOWN",
    contract_slug="test-updown-4h-0000000000",
    window_start_ts=int(now_ts) - 4 * 3600,
    window_end_ts=int(now_ts) + 1800,
    decision_ts=now_ts,
    metrics={
        "price": 123.45,
        "anchor_price": 130.00,
        "fair": 125.00,
        "edge_z": 1.42,
        "slope_z": -0.55,
        "percent_move": 0.028,
        "distance_z": 1.31,
        "sigma_score": 0.71,
        "volatility": 0.012,
        "slope_ok": True,
        "percent_ok": True,
        "distance_ok": True,
        "stability_ok": True,
    },
)

print("Done.")