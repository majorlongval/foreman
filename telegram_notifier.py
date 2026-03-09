import os
import logging
import requests

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    A class to handle sending notifications to a Telegram chat.
    Reads configuration from environment variables.
    """
    def __init__(self):
        """
        Initializes the TelegramNotifier by reading credentials from environment variables.
        """
        try:
            self.token = os.getenv("TELEGRAM_BOT_TOKEN")
            self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
            self.enabled = bool(self.token and self.chat_id)

            if self.enabled:
                logger.info("Telegram notifier is enabled.")
            else:
                logger.debug("Telegram notifier is disabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable.")
            
            if bool(self.token) ^ bool(self.chat_id):
                logger.warning("Partial Telegram configuration found. Both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set for notifications to work.")
                self.enabled = False

        except Exception as e:
            logger.error(f"Failed to initialize TelegramNotifier: {e}", exc_info=True)
            self.enabled = False
            self.token = None
            self.chat_id = None

    def send_message(self, message: str):
        """
        Sends a message to the configured Telegram chat if the notifier is enabled.

        Args:
            message (str): The message to send. Assumed to be formatted with MarkdownV2.
        """
        if not self.enabled:
            logger.debug(f"Telegram notifications disabled, not sending message: {message[:80]}...")
            return

        api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'MarkdownV2'
        }

        try:
            response = requests.post(api_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Successfully sent Telegram notification.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram notification due to a network error or API issue: {e}")
            if e.response is not None:
                logger.error(f"Telegram API response: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending Telegram notification: {e}", exc_info=True)

    def _escape_markdown(self, text: str) -> str:
        """
        Escapes characters for Telegram's MarkdownV2 parser.
        """
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        return "".join(f"\\{char}" if char in escape_chars else char for char in text)

    def notify_issue_refined(self, issue_id: str, issue_title: str):
        """
        Sends a notification for a successfully refined issue.
        """
        title_safe = self._escape_markdown(issue_title)
        message = f"✅ *Issue Refined*\n\n*ID:* `{issue_id}`\n*Title:* _{title_safe}_"
        self.send_message(message)

    def notify_cost_ceiling_reached(self, limit: float, current_cost: float):
        """
        Sends a notification that the API cost ceiling has been reached.
        """
        message = (
            f"🚨 *API Cost Ceiling Reached*\n\n"
            f"*Limit:* `${limit:.2f}`\n"
            f"*Current Cost:* `${current_cost:.2f}`\n\n"
            f"Agent has been stopped to prevent further costs\\."
        )
        self.send_message(message)

    def notify_brainstorming_complete(self, issue_id: str, task_count: int):
        """
        Sends a notification after brainstorming new tasks for an issue.
        """
        message = (
            f"🧠 *Brainstorming Complete*\n\n"
            f"*Issue ID:* `{issue_id}`\n"
            f"*New Tasks Created:* `{task_count}`"
        )
        self.send_message(message)


# Singleton instance for easy import and use across the application.
# If env vars are not set, it will safely do nothing when its methods are called.
notifier = TelegramNotifier()