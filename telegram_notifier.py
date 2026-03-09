"""
FOREMAN Telegram Notifier
Sends notifications to a Telegram chat. Optional — fails silently if not configured.

Usage:
    from telegram_notifier import notify
    notify("Issue #5 refined successfully")
"""

import os
import logging
import urllib.request
import urllib.parse
import json

log = logging.getLogger("foreman.telegram")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def notify(message: str) -> bool:
    """Send a Telegram message. Returns True on success, False if not configured or failed."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log.info(f"  📱 Telegram: sent")
                return True
    except Exception as e:
        log.warning(f"  📱 Telegram send failed (non-critical): {e}")

    return False
