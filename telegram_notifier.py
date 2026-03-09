import os
import logging
import requests

class TelegramNotifier:
    """
    A class to handle sending notifications to a Telegram chat.
    It reads the bot token and chat ID from environment variables.
    If the environment variables are not set, it will not send notifications.
    """
    def __init__(self):
        """
        Initializes the TelegramNotifier, loading configuration from environment variables.
        """
        try:
            self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
            self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
            self.is_configured = self.bot_token and self.chat_id

            if self.is_configured:
                logging.info("Telegram notifier is configured.")
            else:
                logging.info("Telegram notifier is not configured. Notifications will be skipped.")
        except Exception as e:
            logging.error(f"Error initializing TelegramNotifier: {e}")
            self.is_configured = False

    def send_message(self, message: str):
        """
        Sends a message to the configured Telegram chat.
        If the notifier is not configured, this method does nothing.

        Args:
            message (str): The message text to send.
        """
        if not self.is_configured:
            return

        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }

        try:
            logging.info(f"Sending Telegram notification to chat ID {self.chat_id[:4]}...")
            response = requests.post(api_url, json=payload, timeout=10)
            response.raise_for_status()
            logging.info("Telegram notification sent successfully.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to send Telegram notification due to a network error: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while sending Telegram notification: {e}")