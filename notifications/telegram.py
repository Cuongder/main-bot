"""
Telegram Notification Module
Sends trade alerts and accepts lightweight bot commands via Telegram.
"""
import threading
import time

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED
from utils.logger import logger


class TelegramNotifier:
    """
    Sends notifications via Telegram bot.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
    """

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = TELEGRAM_ENABLED
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._rate_limit = 1
        self._last_send_time = 0
        self._last_update_id = 0
        self._command_handler = None
        self._command_running = False
        self._command_thread = None

        if not self.enabled:
            logger.warning("Telegram notifications disabled (no token/chat_id)")

    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send a message via Telegram."""
        if not self.enabled:
            return

        now = time.time()
        if now - self._last_send_time < self._rate_limit:
            time.sleep(self._rate_limit - (now - self._last_send_time))

        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            self._last_send_time = time.time()

            if response.status_code != 200:
                logger.error(f"Telegram send failed: {response.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def start_command_loop(self, command_handler):
        """Start background polling for Telegram commands."""
        if not self.enabled or self._command_running:
            return

        self._command_handler = command_handler
        self._command_running = True
        self._command_thread = threading.Thread(target=self._poll_commands, daemon=True)
        self._command_thread.start()

    def stop_command_loop(self):
        """Stop background command polling."""
        self._command_running = False

    def _poll_commands(self):
        """Continuously fetch Telegram updates."""
        while self._command_running:
            try:
                updates = self._fetch_updates()
                if updates:
                    self._handle_updates(updates)
            except Exception as e:
                logger.error(f"Telegram command loop error: {e}")
            time.sleep(2)

    def _fetch_updates(self):
        """Fetch pending Telegram bot updates."""
        response = requests.get(
            f"{self.base_url}/getUpdates",
            params={"timeout": 10, "offset": self._last_update_id},
            timeout=15,
        )

        if response.status_code != 200:
            logger.error(f"Telegram getUpdates failed: {response.text}")
            return []

        payload = response.json()
        if not payload.get("ok"):
            logger.error(f"Telegram getUpdates invalid payload: {payload}")
            return []

        return payload.get("result", [])

    def _handle_updates(self, updates):
        """Handle Telegram commands from the configured chat."""
        for update in updates:
            update_id = int(update.get("update_id", 0))
            if update_id >= self._last_update_id:
                self._last_update_id = update_id + 1

            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = (message.get("text") or "").strip()

            if not text.startswith("/"):
                continue
            if chat_id != str(self.chat_id):
                logger.warning(f"Ignoring Telegram command from unauthorized chat: {chat_id}")
                continue
            if not self._command_handler:
                continue

            try:
                response_text = self._command_handler(text)
                if response_text:
                    self.send_message(response_text)
            except Exception as e:
                logger.error(f"Telegram command handler failed: {e}")
                self.send_message(f"🔴 <b>COMMAND ERROR</b>\n\n{e}")

    def notify_trade_open(self, trade: dict):
        """Send notification when a trade is opened."""
        direction = trade.get("direction", trade.get("side", ""))
        emoji = "🟢" if direction in ("LONG", "buy") else "🔴"

        text = (
            f"{emoji} <b>NEW TRADE OPENED</b>\n\n"
            f"📊 <b>{trade.get('symbol', 'ETH/USDT')}</b>\n"
            f"📈 Direction: <b>{direction}</b>\n"
            f"💰 Entry: <b>${trade.get('entry_price', 0):.2f}</b>\n"
            f"📏 Size: <b>{trade.get('amount', 0):.4f} ETH</b>\n"
            f"🛡️ Stop Loss: ${trade.get('stop_loss', 0):.2f}\n"
            f"🎯 Take Profit: ${trade.get('take_profit', 0):.2f}\n"
            f"⚡ Leverage: 5x\n"
            f"💵 Risk: ${trade.get('risk_amount', 0):.2f}\n"
            f"🏦 Balance: ${trade.get('balance_after', 0):.2f}"
        )
        self.send_message(text)

    def notify_trade_close(self, trade: dict):
        """Send notification when a trade is closed."""
        pnl = trade.get("pnl", 0)
        pnl_pct = trade.get("pnl_pct")
        emoji = "✅" if pnl >= 0 else "❌"
        pnl_emoji = "💰" if pnl >= 0 else "💸"
        pnl_pct_text = f" ({pnl_pct:+.2f}%)" if pnl_pct is not None else ""

        text = (
            f"{emoji} <b>TRADE CLOSED</b>\n\n"
            f"📊 <b>{trade.get('symbol', 'ETH/USDT')}</b>\n"
            f"{pnl_emoji} PnL: <b>${pnl:+.2f}</b>{pnl_pct_text}\n"
            f"📈 Exit Price: ${trade.get('exit_price', 0):.2f}\n"
            f"📝 Reason: {self._format_exit_reason(trade.get('exit_reason', 'unknown'))}\n"
            f"💵 Balance: ${trade.get('balance_after', 0):.2f}"
        )
        self.send_message(text)

    def notify_daily_summary(self, summary: dict):
        """Send daily performance summary."""
        pnl = summary.get("daily_pnl", 0)
        emoji = "📈" if pnl >= 0 else "📉"

        text = (
            f"📊 <b>DAILY SUMMARY</b>\n\n"
            f"{emoji} Daily PnL: <b>${pnl:+.2f}</b>\n"
            f"📈 Trades: {summary.get('trade_count', 0)}\n"
            f"✅ Win Rate: {summary.get('win_rate', 0):.0f}%\n"
            f"💵 Balance: ${summary.get('balance', 0):.2f}\n"
            f"📉 Drawdown: {summary.get('drawdown_pct', 0):.1f}%"
        )
        self.send_message(text)

    def notify_circuit_breaker(self, reason: str):
        """Send alert when circuit breaker activates."""
        text = (
            f"🚨 <b>CIRCUIT BREAKER ACTIVATED</b>\n\n"
            f"⚠️ {reason}\n"
            f"⏸️ Trading paused for safety"
        )
        self.send_message(text)

    def notify_error(self, error: str):
        """Send error notification."""
        self.send_message(f"🔴 <b>BOT ERROR</b>\n\n{error}")

    def notify_startup(self, balance: float):
        """Send bot startup notification."""
        text = (
            f"🤖 <b>TRADING BOT STARTED</b>\n\n"
            f"📊 Pair: ETH/USDT\n"
            f"⚡ Leverage: 5x\n"
            f"💵 Balance: ${balance:.2f}\n"
            f"🕐 Mode: 24/7 Automated"
        )
        self.send_message(text)

    def _format_exit_reason(self, reason: str) -> str:
        """Convert machine-readable exit reasons into readable labels."""
        labels = {
            "take_profit": "Take Profit",
            "stop_loss": "Stop Loss",
            "trailing_stop": "Trailing Stop",
            "manual_close": "Manual Close",
            "unknown": "Unknown",
        }
        return labels.get(reason, reason.replace("_", " ").title())
