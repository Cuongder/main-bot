"""
Preflight checks for demo deployment readiness.
Run this before copying the bot to a VPS for 24/7 demo trading.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, Tuple

from core.exchange import ExchangeManager
from core.order_manager import OrderManager
from notifications.telegram import TelegramNotifier


class PreflightChecker:
    """Collects local and live readiness checks for the demo bot."""

    def __init__(self, exchange_mgr=None, order_mgr=None, telegram=None):
        self.exchange_mgr = exchange_mgr or ExchangeManager()
        self.order_mgr = order_mgr or OrderManager(self.exchange_mgr)
        self.telegram = telegram or TelegramNotifier()

    def check_environment(self, env: Dict[str, str] | None = None) -> Dict[str, bool]:
        """Check whether required environment fields are present."""
        env = env or os.environ
        return {
            "binance_api_demo": bool(env.get("BINANCE_API_DEMO")),
            "binance_secret_demo": bool(env.get("BINANCE_SECRET_DEMO")),
            "telegram_bot_token": bool(env.get("TELEGRAM_BOT_TOKEN")),
            "telegram_chat_id": bool(env.get("TELEGRAM_CHAT_ID")),
        }

    def check_binance(self) -> Dict[str, object]:
        """Fetch a small live snapshot from Binance demo."""
        balance = self.exchange_mgr.get_balance()
        positions = self.exchange_mgr.get_positions()
        price = self.exchange_mgr.get_current_price()
        ok = balance["total"] > 0 and price > 0
        return {
            "ok": ok,
            "balance": balance,
            "positions": positions,
            "price": price,
        }

    def check_telegram(self) -> Dict[str, object]:
        """Attempt a lightweight Telegram reachability check."""
        try:
            updates = self.telegram._fetch_updates()
            return {"ok": True, "updates_count": len(updates)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def smoke_test_order(self, symbol: str = "ETH/USDT", amount: float = 0.01) -> Dict[str, object]:
        """Place and close a tiny demo order, but only if the symbol is clean."""
        positions = self.exchange_mgr.get_positions()
        normalized = symbol.replace("/", "")
        existing = [p for p in positions if p.get("symbol") == normalized]
        if existing:
            return {
                "ok": False,
                "reason": f"Abort: existing {symbol.split('/')[0]} position found",
                "positions": existing,
            }

        return {
            "ok": True,
            "reason": "ready_for_live_smoke_test",
            "symbol": symbol,
            "amount": amount,
        }

    def run_live_order_smoke(self, symbol: str = "ETH/USDT", amount: float = 0.01) -> Dict[str, object]:
        """Run a real tiny open/close smoke test on Binance demo."""
        guard = self.smoke_test_order(symbol=symbol, amount=amount)
        if not guard["ok"]:
            return guard

        price = self.exchange_mgr.get_current_price(symbol)
        stop_loss = round(price * 0.99, 2)
        take_profit = round(price * 1.01, 2)

        opened = self.order_mgr.place_market_order(
            side="buy",
            amount=amount,
            symbol=symbol,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        if opened.get("status") == "failed" or not opened.get("order_id"):
            return {"ok": False, "reason": "open_failed", "open": opened}

        time.sleep(1)
        mid_positions = self.exchange_mgr.get_positions()
        matching = [p for p in mid_positions if p.get("symbol") == symbol.replace("/", "")]
        if not matching:
            return {"ok": False, "reason": "position_not_found_after_open", "open": opened}

        closed = self.order_mgr.close_position(symbol)
        if closed.get("status") != "closed":
            return {"ok": False, "reason": "close_failed", "open": opened, "close": closed}

        return {
            "ok": True,
            "open": opened,
            "close": closed,
        }

    def evaluate_readiness(self, report: Dict[str, Dict[str, object]]) -> Tuple[bool, str]:
        """Summarize whether the current environment is VPS-ready."""
        failing = [
            name
            for name, payload in report.items()
            if isinstance(payload, dict) and payload.get("ok") is False
        ]
        ready = not failing
        summary = "ready" if ready else f"not ready: failed checks -> {', '.join(failing)}"
        return ready, summary

    def run(self, include_order_smoke: bool = False, live_order_smoke: bool = False,
            symbol: str = "ETH/USDT", amount: float = 0.01):
        """Run the preflight suite."""
        report = {
            "environment": {"ok": all(self.check_environment().values()), "details": self.check_environment()},
            "binance": self.check_binance(),
            "telegram": self.check_telegram(),
        }
        if include_order_smoke:
            report["order_smoke_test"] = self.smoke_test_order(symbol=symbol, amount=amount)
        if live_order_smoke:
            report["live_order_smoke"] = self.run_live_order_smoke(symbol=symbol, amount=amount)
        ready, summary = self.evaluate_readiness(report)
        report["ready"] = ready
        report["summary"] = summary
        return report


def main():
    parser = argparse.ArgumentParser(description="Run preflight checks before VPS demo deployment.")
    parser.add_argument("--smoke-order", action="store_true", help="Include order smoke-test guard/report.")
    parser.add_argument("--live-order-smoke", action="store_true", help="Place and close a tiny real demo order.")
    parser.add_argument("--symbol", default="ETH/USDT", help="Symbol for smoke-order guard.")
    parser.add_argument("--amount", type=float, default=0.01, help="Order size for smoke-order guard.")
    args = parser.parse_args()

    checker = PreflightChecker()
    report = checker.run(
        include_order_smoke=args.smoke_order,
        live_order_smoke=args.live_order_smoke,
        symbol=args.symbol,
        amount=args.amount,
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
