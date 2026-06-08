
from dotenv import load_dotenv
load_dotenv()
import os
print('DEBUG: GMAIL_APP_PASSWORD =', os.environ.get('GMAIL_APP_PASSWORD'))
from src.polyou.utils.decision_email import send_decision_email

if __name__ == "__main__":
    # Example test values
    send_decision_email(
        symbol="BTCUSD",
        side="UP",
        contract_slug="btc-updown-4h-1770483600",
        window_start_ts=1770480000,
        window_end_ts=1770483600,
        decision_ts=1770481800,
        metrics={
            "price": 69350.44,
            "anchor_price": 69200.00,
            "fair": 69300.00,
            "edge_z": 1.25,
            "slope_z": 0.35,
            "percent_move": 0.0217,
            "distance_z": 1.15,
            "sigma_score": 0.72,
            "volatility": 0.00015,
            "slope_ok": True,
            "percent_ok": True,
            "distance_ok": True,
            "stability_ok": True,
        },
    )
    print("Test decision email sent.")
