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
        Initializes the TelegramNotifier by fetching the bot token and chat ID
        from environment variables.
        """
        try:
            self.token = os.getenv("TELEGRAM_BOT_TOKEN")
            self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
            self.enabled = bool(self.token and self.chat_id)

            if self.enabled:
                logger.info("Telegram notifier is enabled.")
            else:
                logger.info("Telegram notifier is disabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable.")
        except Exception as e:
            logger.error(f"Error initializing TelegramNotifier: {e}")
            self.enabled = False


    def send_message(self, text: str):
        """
        Sends a message to the configured Telegram chat.

        If the notifier is not enabled (i.e., env vars are not set or there was an init error),
        this method will do nothing and not raise an error.

        Args:
            text (str): The message text to send. Supports Markdown.
        """
        if not self.enabled:
            logger.debug("Skipping Telegram notification because it is disabled.")
            return

        api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }

        try:
            response = requests.post(api_url, json=payload, timeout=10)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            logger.info(f"Successfully sent Telegram notification to chat ID {self.chat_id[:4]}...")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram notification: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while sending Telegram notification: {e}", exc_info=True)

# Create a singleton instance to be used across the application
# This allows the configuration to be read once at startup.
telegram_notifier = TelegramNotifier()