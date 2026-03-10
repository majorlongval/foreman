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
    consecutive_failures = 0
    max_failures = 10

    while consecutive_failures < max_failures:
        if not TELEGRAM_BOT_TOKEN:
            log.error("  📱 Telegram bot token missing in polling loop. Exiting thread.")
            break
            
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=30"
            with urllib.request.urlopen(url, timeout=40) as resp:
                if resp.status != 200:
                    log.warning(f"  📱 Telegram getUpdates failed with status: {resp.status}")
                    consecutive_failures += 1
                    time.sleep(10) # Wait before retrying on server errors
                    continue

                data = json.load(resp)

            if data.get("ok"):
                consecutive_failures = 0
                for update in data.get("result", []):
                    last_update_id = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        command = text.split(" ")[0]
                        if command in COMMANDS:
                            log.info(f"  📱 Received command: {command}")
                            COMMANDS[command](update)
                # Global rate limit to prevent spamming in case of instant responses
                time.sleep(1)
            else:
                consecutive_failures += 1
                log.warning(f"  📱 Telegram API returned ok: False. Failures: {consecutive_failures}")
                time.sleep(10)
            
        except urllib.error.HTTPError as e:
            consecutive_failures += 1
            log.warning(f"  📱 Telegram HTTP error {e.code} (failure {consecutive_failures}/{max_failures})")
            if e.code in [401, 404]:
                log.error("  📱 Critical Telegram token error. Shutting down polling.")
                break
            time.sleep(15)
        except urllib.error.URLError as e:
            consecutive_failures += 1
            log.warning(f"  📱 Telegram polling network error (failure {consecutive_failures}/{max_failures}): {e}")
            time.sleep(15)
        except Exception as e:
            consecutive_failures += 1
            log.error(f"  📱 Unhandled error in Telegram polling (failure {consecutive_failures}/{max_failures}): {e}", exc_info=True)
            time.sleep(15)

    if consecutive_failures >= max_failures:
        log.error("  📱 Too many consecutive Telegram polling failures. Command listener stopped.")

_polling_thread = None

def start_telegram_bot_polling():
    """Starts the Telegram bot command listener in a separate thread."""
    global _polling_thread
    if not TELEGRAM_BOT_TOKEN:
        log.info("  📱 Telegram bot token not configured, command polling disabled.")
        return
    if not TELEGRAM_AUTHORIZED_USERS:
        log.warning("  📱 AUTHORIZED_TELEGRAM_USER_IDS not set. No one can issue commands.")
        return

    log.info("  📱 Starting Telegram bot command listener...")
    _polling_thread = threading.Thread(target=_poll_updates, daemon=True)
    _polling_thread.start()
    log.info("  📱 Telegram bot command listener started.")

def is_polling_alive() -> bool:
    """Check if the Telegram polling thread is still running."""
    return _polling_thread is not None and _polling_thread.is_alive()