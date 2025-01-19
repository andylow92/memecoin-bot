import os
import time
import json
import requests
import smtplib
import logging
import platform
import subprocess
import signal
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional, Dict, Union, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("crypto_alert.log")  # Also log to file
    ]
)

class PriceCondition:
    def __init__(self, target_price: float, condition_type: str = "above"):
        """
        Initialize a price condition
        :param target_price: The target price to compare against
        :param condition_type: "above" or "below"
        """
        self.target_price = float(target_price)
        if condition_type not in ["above", "below"]:
            raise ValueError("condition_type must be either 'above' or 'below'")
        self.condition_type = condition_type

    def is_met(self, current_price: float) -> bool:
        """Check if the price condition is met."""
        if self.condition_type == "above":
            return current_price >= self.target_price
        else:  # condition_type == "below"
            return current_price <= self.target_price

    def __str__(self) -> str:
        return f"Price {self.condition_type} ${self.target_price}"

class CryptoAlertBot:
    def __init__(
        self, 
        coin_id: str,
        conditions: Union[PriceCondition, List[PriceCondition]],
        alert_types: Union[str, List[str]] = "sound",
        cooldown_period: int = 300,
        check_interval: int = 60,
        sound_file: str = "/System/Library/Sounds/Ping.aiff",
        config_file: str = "crypto_config.json"
    ):
        """
        Enhanced initialization with multiple conditions and alert types.

        :param coin_id:           The CoinGecko ID of your coin (e.g. "bitcoin", "pepe", "trump-token")
        :param conditions:        One or more PriceCondition objects
        :param alert_types:       "sound", "email", or a list like ["sound", "email"]
        :param cooldown_period:   Time in seconds to wait before sending another alert (default=300)
        :param check_interval:    Time in seconds between each price check (default=60)
        :param sound_file:        Path to a sound file on macOS for playing alerts
        :param config_file:       JSON config file for email credentials & preferences
        """
        self.coin_id = coin_id.lower()
        # Ensure we have a list of conditions
        self.conditions = conditions if isinstance(conditions, list) else [conditions]
        # Ensure we have a list of alert types
        self.alert_types = alert_types if isinstance(alert_types, list) else [alert_types]

        self.last_alert_time = None
        self.cooldown_period = cooldown_period
        self.check_interval = check_interval
        self.sound_file = sound_file
        self.config_file = config_file
        self.running = True

        # Load or create configuration file
        self.config = self.load_config()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown on SIGINT or SIGTERM."""
        logging.info("Shutting down gracefully...")
        self.running = False

    def load_config(self) -> Dict:
        """Load configuration from file or create a default config."""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Create a default config if none found
            config = {
                "email": {
                    "sender_email": os.getenv("SENDER_EMAIL", ""),
                    "sender_password": os.getenv("SENDER_PASSWORD", ""),
                    "receiver_email": os.getenv("RECEIVER_EMAIL", "")
                },
                "notification_preferences": {
                    "price_history": True,
                    "volume_alert": True
                }
            }
            self.save_config(config)
            return config

    def save_config(self, config: Dict):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)

    def get_current_price(self) -> Optional[Dict[str, float]]:
        """
        Enhanced price fetch with additional market data.
        Returns a dictionary with at least:
          - "price": float
          - "volume": float (24h volume)
          - "change": float (% change in last 24h)
        """
        try:
            url = (
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={self.coin_id}"
                "&vs_currencies=usd"
                "&include_24hr_vol=true"
                "&include_24hr_change=true"
            )
            headers = {
                "Accept": "application/json",
                "User-Agent": "CryptoAlertBot/1.0",
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if self.coin_id not in data:
                logging.error(f"Coin ID '{self.coin_id}' not found in API response.")
                return None
            
            return {
                "price": data[self.coin_id]["usd"],
                "volume": data[self.coin_id].get("usd_24h_vol"),
                "change": data[self.coin_id].get("usd_24h_change")
            }
        except requests.exceptions.RequestException as e:
            logging.error(f"Network/HTTP error while fetching price: {e}")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
        return None

    def send_email_alert(self, market_data: Dict[str, float], triggered_condition: PriceCondition):
        """Send an email alert (if credentials exist) with additional market data."""
        if not all(self.config["email"].values()):
            logging.error("Email credentials are not properly configured in the JSON config.")
            return

        subject = f"🚨 Price Alert: {self.coin_id.upper()} {triggered_condition}"
        body = (
            f"Price Alert for {self.coin_id.upper()}!\n\n"
            f"Current Price: ${market_data['price']:.8f}\n"
            f"Condition Met: {triggered_condition}\n"
            f"24h Change: {market_data.get('change', 'N/A')}%\n"
            f"24h Volume: ${market_data.get('volume', 'N/A'):,.2f}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        sender_email = self.config["email"]["sender_email"]
        sender_password = self.config["email"]["sender_password"]
        receiver_email = self.config["email"]["receiver_email"]

        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = sender_email
            msg["To"] = receiver_email

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)

            logging.info("Email alert sent successfully!")
        except Exception as e:
            logging.error(f"Error sending email: {e}")

    def play_sound_alert(self):
        """Play system sound alert on macOS."""
        if platform.system() != "Darwin":
            logging.warning("Sound alert is only configured for macOS in this script.")
            return
        try:
            if not os.path.exists(self.sound_file):
                logging.error(f"Sound file not found: {self.sound_file}")
                return
            subprocess.run(["afplay", self.sound_file], check=True)
            logging.info("Sound alert played successfully!")
        except subprocess.SubprocessError as e:
            logging.error(f"Error playing sound: {e}")

    def should_send_alert(self) -> bool:
        """Check if we're past the cooldown period before sending another alert."""
        if self.last_alert_time is None:
            return True
        return (time.time() - self.last_alert_time) >= self.cooldown_period

    def start_monitoring(self):
        """Main loop to monitor the coin price at intervals."""
        logging.info(f"Starting price monitoring for {self.coin_id.upper()}...")
        logging.info(f"Alert types enabled: {', '.join(self.alert_types)}")
        for condition in self.conditions:
            logging.info(f"Monitoring condition: {condition}")

        while self.running:
            market_data = self.get_current_price()

            if market_data is not None:
                price = market_data["price"]
                logging.info(
                    f"Current {self.coin_id.upper()} price: ${price:.8f} "
                    f"| 24h Change: {market_data.get('change', 'N/A')}%"
                )

                # Check each condition (below 64, above 80, above 100, etc.)
                for condition in self.conditions:
                    if condition.is_met(price) and self.should_send_alert():
                        logging.info(f"Alert condition met: {condition}")
                        
                        # Trigger each alert type
                        for alert_type in self.alert_types:
                            if alert_type == "email":
                                self.send_email_alert(market_data, condition)
                            elif alert_type == "sound":
                                self.play_sound_alert()

                        self.last_alert_time = time.time()
            
            time.sleep(self.check_interval)

        logging.info("Monitoring stopped.")

# ----------------------------
# Example usage
# ----------------------------
if __name__ == "__main__":
    # We want three conditions:
    # 1) Price goes below 64
    # 2) Price goes above 80
    # 3) Price goes above 100
    conditions_list = [
        PriceCondition(64, "below"),
        PriceCondition(80, "above"),
        PriceCondition(100, "above"),
    ]

    # Choose your alert types: "sound", "email", or both.
    # For example, ["sound", "email"] will play sound AND send an email.
    alerts = ["sound", "email"]  # or ["sound","email"] if you want both

    bot = CryptoAlertBot(
        coin_id="official-trump",   # Replace with actual CoinGecko ID for your coin
        conditions=conditions_list,
        alert_types=alerts,
        cooldown_period=300,     # Wait 5 minutes before sending another alert
        check_interval=60        # Check the price every 60 seconds
    )

    bot.start_monitoring()

'''
export SENDER_EMAIL="memebotandres@gmail.com"
export SENDER_PASSWORD="aqfd vmad ztnm qefv"
export RECEIVER_EMAIL="aalc928@gmail.com"

memebot: aqfd vmad ztnm qefv



3. Use the Script
a. Basic Example

If you want to set a single price condition, use the following code:

from crypto_alert_bot import CryptoAlertBot, PriceCondition

bot = CryptoAlertBot(
    coin_id="pepe",  # The ID of the cryptocurrency (from CoinGecko)
    conditions=PriceCondition(0.000001, "above"),  # Alert when price goes above 0.000001
    alert_types="sound"  # Alert type: "sound", "email", or both
)
bot.start_monitoring()

b. Advanced Example with Multiple Conditions

For more advanced setups, you can monitor multiple price conditions and use both sound and email alerts:

from crypto_alert_bot import CryptoAlertBot, PriceCondition

conditions = [
    PriceCondition(0.000001, "above"),  # Alert if price goes above this
    PriceCondition(0.0000005, "below")  # Alert if price goes below this
]

bot = CryptoAlertBot(
    coin_id="pepe",  # The ID of the cryptocurrency (from CoinGecko)
    conditions=conditions,
    alert_types=["sound", "email"],  # Use both sound and email alerts
    cooldown_period=300,  # Minimum time between alerts (in seconds)
    check_interval=60  # Check the price every 60 seconds
)
bot.start_monitoring()

Save this in a .py file (e.g., run_bot.py) and run it:

python run_bot.py

4. Stop the Script

To stop monitoring, press CTRL+C. The bot will shut down gracefully and log the event.

'''