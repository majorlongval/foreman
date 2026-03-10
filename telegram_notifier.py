"""
FOREMAN Telegram Notifier
Sends notifications to a Telegram chat. Optional — fails silently if not configured.
Also listens for commands (/status, /pause, /resume) to control the agent loop.

Usage:
    from telegram_notifier import notify, start_telegram_bot_polling
    notify("Issue #5 refined successfully")
    start_telegram_bot_polling() # Run this in the main thread startup
"""

import os
import logging
import urllib.request
import urllib.parse
import json
import threading
import time
from functools import wraps

from agent_state import agent_state_manager, AgentState

log = logging.getLogger("foreman.telegram")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") # Used for general notifications
TELEGRAM_AUTHORIZED_USERS = [user.strip() for user in os.environ.get("AUTHORIZED_TELEGRAM_USER_IDS", "").split(",") if user.strip()]

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

# --- Bot Command Handling ---

def _send_reply(chat_id: int, message: str) -> bool:
    """Send a reply to a specific chat ID."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log.info(f"  📱 Telegram: replied to {chat_id}")
                return True
    except Exception as e:
        log.warning(f"  📱 Telegram reply failed: {e}")
    return False

def authorized(f):
    """Decorator to check if the user is authorized."""
    @wraps(f)
    def decorated(update, *args, **kwargs):
        try:
            chat_id = str(update.get("message", {}).get("chat", {}).get("id"))
            if not chat_id:
                log.warning("  📱 Could not get chat_id from Telegram update")
                return
            
            if chat_id in TELEGRAM_AUTHORIZED_USERS:
                return f(update, *args, **kwargs)
            else:
                log.warning(f"  📱 Unauthorized access attempt from chat_id: {chat_id}")
                _send_reply(int(chat_id), "You are not authorized to use this command.")
        except Exception as e:
            log.error(f"  📱 Error in authorization decorator: {e}")
    return decorated

@authorized
def _handle_start(update):
    chat_id = update["message"]["chat"]["id"]
    _send_reply(chat_id, "FOREMAN agent bot is active.")

@authorized
def _handle_status(update):
    chat_id = update["message"]["chat"]["id"]
    state = agent_state_manager.get_state()
    _send_reply(chat_id, f"Agent status: {state.name}")

@authorized
def _handle_pause(update):
    chat_id = update["message"]["chat"]["id"]
    log.info("  ⏸️ Pause command received via Telegram.")
    agent_state_manager.set_state(AgentState.PAUSED)
    _send_reply(chat_id, "Agent loop paused.")

@authorized
def _handle_resume(update):
    chat_id = update["message"]["chat"]["id"]
    log.info("  ▶️ Resume command received via Telegram.")
    agent_state_manager.set_state(AgentState.RUNNING)
    _send_reply(chat_id, "Agent loop resumed.")

COMMANDS = {
    "/start": _handle_start,
    "/status": _handle_status,
    "/pause": _handle_pause,
    "/resume": _handle_resume,
}

def _poll_updates():
    """Polls Telegram for new messages and handles commands."""
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            with urllib.request.urlopen(url, timeout=40) as resp:
                if resp.status != 200:
                    log.warning(f"  📱 Telegram getUpdates failed with status: {resp.status}")
                    time.sleep(10) # Wait before retrying on server errors
                    continue

                data = json.load(resp)

            if data.get("ok"):
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        command = text.split(" ")[0]
                        if command in COMMANDS:
                            log.info(f"  📱 Received command: {command}")
                            COMMANDS[command](update)
            
        except urllib.error.URLError as e:
            log.warning(f"  📱 Telegram polling network error (will retry): {e}")
            time.sleep(15) # Wait longer on network errors
        except Exception as e:
            log.error(f"  📱 Unhandled error in Telegram polling loop: {e}", exc_info=True)
            time.sleep(5) # Brief pause before retrying

def start_telegram_bot_polling():
    """Starts the Telegram bot command listener in a separate thread."""
    if not TELEGRAM_BOT_TOKEN:
        log.info("  📱 Telegram bot token not configured, command polling disabled.")
        return
    if not TELEGRAM_AUTHORIZED_USERS:
        log.warning("  📱 AUTHORIZED_TELEGRAM_USER_IDS not set. No one can issue commands.")
        return

    log.info("  📱 Starting Telegram bot command listener...")
    thread = threading.Thread(target=_poll_updates, daemon=True)
    thread.start()
    log.info("  📱 Telegram bot command listener started.")