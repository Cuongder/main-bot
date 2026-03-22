"""
Logging utility with structured output and file rotation
"""
import logging
import os
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler


def setup_logger(name='trading_bot', log_file='data/bot.log', level=logging.INFO):
    """Setup logger with console and file handlers"""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console handler with colors
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        '%(asctime)s │ %(levelname)-8s │ %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)

    # File handler with rotation (10MB max, keep 5 files)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_format = logging.Formatter(
        '%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


class TradeLogger:
    """Log trades to JSON file for analysis"""

    def __init__(self, log_file='data/trades.json'):
        self.log_file = log_file
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        if not os.path.exists(log_file):
            with open(log_file, 'w') as f:
                json.dump([], f)

    def log_trade(self, trade_data: dict):
        """Append a trade record to the JSON log"""
        trade_data['timestamp'] = datetime.utcnow().isoformat()
        try:
            with open(self.log_file, 'r') as f:
                trades = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            trades = []

        trades.append(trade_data)

        with open(self.log_file, 'w') as f:
            json.dump(trades, f, indent=2)

    def get_trades(self, limit=None) -> list:
        """Get trade history"""
        try:
            with open(self.log_file, 'r') as f:
                trades = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

        if limit:
            return trades[-limit:]
        return trades

    def get_daily_trades(self, date=None) -> list:
        """Get trades for a specific date"""
        if date is None:
            date = datetime.utcnow().strftime('%Y-%m-%d')

        trades = self.get_trades()
        return [t for t in trades if t.get('timestamp', '').startswith(date)]

    def get_daily_pnl(self, date=None) -> float:
        """Calculate daily PnL"""
        daily_trades = self.get_daily_trades(date)
        return sum(t.get('pnl', 0) for t in daily_trades if t.get('status') == 'closed')


# Global logger instance
logger = setup_logger()
trade_logger = TradeLogger()
