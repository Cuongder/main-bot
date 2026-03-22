import unittest
from unittest.mock import MagicMock

from preflight_check import PreflightChecker


class PreflightCheckerTests(unittest.TestCase):
    def test_check_environment_reports_required_fields(self):
        checker = PreflightChecker()

        result = checker.check_environment(
            {
                "BINANCE_API_DEMO": "demo-key",
                "BINANCE_SECRET_DEMO": "demo-secret",
                "TELEGRAM_BOT_TOKEN": "",
                "TELEGRAM_CHAT_ID": "123",
            }
        )

        self.assertTrue(result["binance_api_demo"])
        self.assertTrue(result["binance_secret_demo"])
        self.assertFalse(result["telegram_bot_token"])
        self.assertTrue(result["telegram_chat_id"])

    def test_smoke_test_order_aborts_if_symbol_position_already_exists(self):
        exchange = MagicMock()
        exchange.get_positions.return_value = [{"symbol": "ETHUSDT"}]
        checker = PreflightChecker(exchange_mgr=exchange)

        result = checker.smoke_test_order(symbol="ETH/USDT", amount=0.01)

        self.assertFalse(result["ok"])
        self.assertIn("existing ETH position", result["reason"])

    def test_evaluate_readiness_requires_binance_and_telegram_checks(self):
        checker = PreflightChecker()

        ready, summary = checker.evaluate_readiness(
            {
                "environment": {"ok": True},
                "binance": {"ok": True},
                "telegram": {"ok": False},
                "order_smoke_test": {"ok": True},
            }
        )

        self.assertFalse(ready)
        self.assertIn("telegram", summary.lower())

    def test_run_live_order_smoke_places_and_closes_tiny_order(self):
        exchange = MagicMock()
        exchange.get_positions.side_effect = [
            [],
            [{"symbol": "ETHUSDT", "side": "long", "size": 0.01, "entry_price": 2000.0, "unrealized_pnl": 0.5}],
            [],
        ]
        exchange.get_current_price.side_effect = [2000.0, 2001.0]
        exchange.get_balance.return_value = {"total": 500.0, "free": 500.0, "used": 0.0}
        exchange._private_request.return_value = []

        order_mgr = MagicMock()
        order_mgr.place_market_order.return_value = {
            "status": "open",
            "order_id": "123",
            "sl_order_id": "a1",
            "tp_order_id": "a2",
        }
        order_mgr.close_position.return_value = {
            "status": "closed",
            "exit_price": 2001.0,
            "pnl": 0.5,
        }

        checker = PreflightChecker(exchange_mgr=exchange, order_mgr=order_mgr)

        result = checker.run_live_order_smoke(symbol="ETH/USDT", amount=0.01)

        self.assertTrue(result["ok"])
        order_mgr.place_market_order.assert_called_once()
        order_mgr.close_position.assert_called_once_with("ETH/USDT")


if __name__ == "__main__":
    unittest.main()
