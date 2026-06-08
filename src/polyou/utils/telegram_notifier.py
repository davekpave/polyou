"""
Telegram notifier utility.

FAIL-LOUD by design:
- Logs exactly why Telegram does not send
- Raises on API/network errors
"""

import os
import logging
import requests

logger = logging.getLogger("telegram")


def send_telegram_message(message: str) -> None:
    enabled = os.environ.get("TELEGRAM_ENABLED", "false").lower()

    if enabled != "true":
        logger.info("Telegram disabled (TELEGRAM_ENABLED != true)")
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram API error: {data}"
            )

        logger.info("Telegram message sent successfully")

    except requests.RequestException as e:
        logger.exception("Telegram API call failed")
        if hasattr(e, "response") and e.response is not None:
            logger.error(
                "Telegram API error response: %s",
                e.response.text,
            )
        raise