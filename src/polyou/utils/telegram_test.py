from dotenv import load_dotenv
load_dotenv()
from polyou.utils.telegram_notifier import send_telegram_message

send_telegram_message(
    "✅ Polyou Telegram test successful.\nIf you see this, alerts are wired correctly."
)
