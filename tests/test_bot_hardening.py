import unittest
from unittest.mock import MagicMock, patch

import config
import main
from analysis.ai_analyzer import AIAnalyzer
from core.order_manager import OrderManager
from dashboard.server import create_app
from core.exchange import ExchangeManager
from notifications.telegram import TelegramNotifier
from risk.position_sizer import PositionSizer


class DashboardWiringTests(unittest.TestCase):
    def test_create_app_keeps_reference_for_empty_bot_data(self):
        bot_data = {}
        app = create_app(bot_data)

        bot_data["status"] = "running"

        with app.test_client() as client:
            response = client.get("/api/status")

        self.assertEqual(response.get_json()["status"], "running")

    @patch("main.threading.Thread")
    @patch("main.TradingBot")
    def test_start_trade_mode_passes_dashboard_data_to_background_thread(self, bot_cls, thread_cls):
        bot = MagicMock()
        bot.dashboard_data = {"status": "initializing"}
        bot_cls.return_value = bot

        main.start_trade_mode()

        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        self.assertEqual(kwargs["target"], main.run_dashboard)
        self.assertEqual(kwargs["args"], (bot.dashboard_data,))
        bot.start.assert_called_once_with()


class RiskAndVolatilityTests(unittest.TestCase):
    def test_position_sizer_uses_supplied_dynamic_risk_pct(self):
        sizer = PositionSizer()

        result = sizer.calculate_position(
            balance=500,
            entry_price=2000,
            stop_loss_price=1980,
            side="LONG",
            risk_pct=0.005,
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["risk_pct"], 0.5)
        self.assertAlmostEqual(result["risk_amount"], 2.5)

    def test_evaluate_trade_passes_high_volatility_flag_to_risk_manager(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot.risk_mgr = MagicMock()
        bot.risk_mgr.can_trade.return_value = {"allowed": False, "reasons": ["high volatility"]}
        bot.telegram = MagicMock()
        bot.ai_analyzer = MagicMock()
        bot.position_sizer = MagicMock()
        bot.order_mgr = MagicMock()
        bot._current_news_sentiment = None
        bot._last_ai_analysis = 0

        signal = {"action": "LONG", "confidence": 0.9, "atr": 10, "high_volatility": True}
        balance = {"total": 500, "free": 500}

        bot._evaluate_trade(signal, balance, [], 2000)

        kwargs = bot.risk_mgr.can_trade.call_args.kwargs
        self.assertTrue(kwargs["volatility_high"])
        bot.order_mgr.place_market_order.assert_not_called()

    def test_evaluate_trade_does_not_block_entry_when_ai_rejects_in_advisory_mode(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot.risk_mgr = MagicMock()
        bot.risk_mgr.can_trade.return_value = {"allowed": True, "reasons": []}
        bot.risk_mgr.get_adjusted_risk.return_value = 0.01
        bot.telegram = MagicMock()
        bot.ai_analyzer = MagicMock()
        bot.ai_analyzer.analyze_market.return_value = {
            "confirmed": False,
            "confidence": 0.2,
            "reasoning": "wait",
            "risk_level": "HIGH",
        }
        bot.position_sizer = MagicMock()
        bot.position_sizer.calculate_sl_tp.return_value = {
            "stop_loss": 1980,
            "take_profit": 2040,
            "rr_ratio": 2.0,
        }
        bot.position_sizer.calculate_position.return_value = {
            "valid": True,
            "contracts": 0.01,
            "risk_amount": 2.5,
        }
        bot.order_mgr = MagicMock()
        bot.order_mgr.place_market_order.return_value = {"status": "open", "order_id": "1"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_balance.return_value = {"total": 500}
        bot._current_news_sentiment = None
        bot._last_ai_analysis = 0
        bot._current_ai_analysis = None

        signal = {"action": "LONG", "confidence": 0.9, "atr": 10, "indicators": {}}
        balance = {"total": 500, "free": 500}

        bot._evaluate_trade(signal, balance, [], 2000)

        bot.order_mgr.place_market_order.assert_called_once()
        self.assertEqual(bot._current_ai_analysis["risk_level"], "HIGH")

    def test_manage_positions_closes_early_when_ai_exit_advisor_flags_bad_conditions(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot.data_fetcher = MagicMock()
        bot.data_fetcher.fetch_ohlcv.return_value = MagicMock()
        analyzed = MagicMock()
        analyzed.empty = False
        analyzed.iloc.__getitem__.return_value = {"atr": 10}
        bot.analyzer = MagicMock()
        bot.analyzer.calculate_all.return_value = analyzed
        bot.position_sizer = MagicMock()
        bot.position_sizer.calculate_sl_tp.return_value = {
            "trailing_activation": 15,
            "trailing_distance": 5,
        }
        bot.order_mgr = MagicMock()
        bot.order_mgr.update_trailing_stop.return_value = False
        bot.order_mgr.close_position.return_value = {"status": "closed", "pnl": -12}
        bot.risk_mgr = MagicMock()
        bot.telegram = MagicMock()
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_balance.return_value = {"total": 488}
        bot._current_news_sentiment = {
            "should_pause": True,
            "impact_level": "HIGH",
            "reasoning": "macro risk",
        }
        bot._current_ai_analysis = None
        bot.ai_analyzer = MagicMock()
        bot.ai_analyzer.analyze_exit_risk.return_value = {
            "close_early": True,
            "confidence": 0.83,
            "reasoning": "News risk elevated",
            "urgency": "HIGH",
        }

        positions = [{"symbol": "ETHUSDT", "entry_price": 2000, "side": "long", "size": 0.1}]

        bot._manage_positions(positions, 1988)

        bot.order_mgr.close_position.assert_called_once_with("ETHUSDT")
        close_payload = bot.telegram.notify_trade_close.call_args.args[0]
        self.assertEqual(close_payload["exit_reason"], "ai_risk_exit")

    def test_manage_positions_keeps_trade_when_ai_exit_advisor_says_hold(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot.data_fetcher = MagicMock()
        bot.data_fetcher.fetch_ohlcv.return_value = MagicMock()
        analyzed = MagicMock()
        analyzed.empty = False
        analyzed.iloc.__getitem__.return_value = {"atr": 10}
        bot.analyzer = MagicMock()
        bot.analyzer.calculate_all.return_value = analyzed
        bot.position_sizer = MagicMock()
        bot.position_sizer.calculate_sl_tp.return_value = {
            "trailing_activation": 15,
            "trailing_distance": 5,
        }
        bot.order_mgr = MagicMock()
        bot.order_mgr.update_trailing_stop.return_value = False
        bot.risk_mgr = MagicMock()
        bot.telegram = MagicMock()
        bot.exchange_mgr = MagicMock()
        bot._current_news_sentiment = {
            "should_pause": True,
            "impact_level": "HIGH",
            "reasoning": "macro risk",
        }
        bot._current_ai_analysis = None
        bot.ai_analyzer = MagicMock()
        bot.ai_analyzer.analyze_exit_risk.return_value = {
            "close_early": False,
            "confidence": 0.41,
            "reasoning": "Hold for now",
            "urgency": "LOW",
        }

        positions = [{"symbol": "ETHUSDT", "entry_price": 2000, "side": "long", "size": 0.1}]

        bot._manage_positions(positions, 1988)

        bot.order_mgr.close_position.assert_not_called()


class BacktestAndAiContextTests(unittest.TestCase):
    def test_backtest_config_downloads_hourly_timeframe_for_higher_tf_bias(self):
        self.assertIn("1h", config.BACKTEST_CONFIG["data_timeframes"])

    def test_ai_prompt_includes_explicit_indicator_context(self):
        analyzer = AIAnalyzer()

        prompt = analyzer._build_analysis_prompt(
            signal={"price": 2000, "action": "LONG", "confidence": 0.8, "rsi": 45, "atr": 20},
            indicators={"ema_50": 1980.5, "macd": 4.2, "macd_signal": 3.9, "volume_spike": True},
            news_sentiment=None,
        )

        self.assertIn("EMA 50", prompt)
        self.assertIn("1980.50", prompt)
        self.assertIn("MACD", prompt)
        self.assertIn("Volume Spike", prompt)


class TelegramNotifierTests(unittest.TestCase):
    def test_trade_open_notification_includes_balance(self):
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.send_message = MagicMock()

        notifier.notify_trade_open(
            {
                "symbol": "ETH/USDT",
                "direction": "LONG",
                "entry_price": 2000,
                "amount": 0.25,
                "stop_loss": 1975,
                "take_profit": 2050,
                "risk_amount": 7.5,
                "balance_after": 492.5,
            }
        )

        message = notifier.send_message.call_args.args[0]
        self.assertIn("Balance", message)
        self.assertIn("$492.50", message)

    def test_trade_close_notification_reports_pnl_percent_and_reason_label(self):
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.send_message = MagicMock()

        notifier.notify_trade_close(
            {
                "symbol": "ETHUSDT",
                "pnl": 18.25,
                "pnl_pct": 3.65,
                "exit_price": 2042,
                "exit_reason": "take_profit",
                "balance_after": 518.25,
            }
        )

        message = notifier.send_message.call_args.args[0]
        self.assertIn("+3.65%", message)
        self.assertIn("Take Profit", message)
        self.assertIn("$518.25", message)

    def test_handle_updates_processes_authorized_command_and_advances_offset(self):
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.chat_id = "123"
        notifier._command_handler = MagicMock(return_value="pong")
        notifier.send_message = MagicMock()

        notifier._handle_updates(
            [
                {
                    "update_id": 99,
                    "message": {
                        "chat": {"id": 123},
                        "text": "/healthcheck",
                    },
                }
            ]
        )

        notifier._command_handler.assert_called_once_with("/healthcheck")
        notifier.send_message.assert_called_once_with("pong")
        self.assertEqual(notifier._last_update_id, 100)


class TelegramCommandResponseTests(unittest.TestCase):
    def test_handle_telegram_command_returns_balance_snapshot(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot._running = True
        bot._cycle_count = 12
        bot.dashboard_data = {"last_update": "2026-03-22T10:00:00", "status": "running"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_balance.return_value = {"total": 525.5, "free": 500.0, "used": 25.5}
        bot.exchange_mgr.get_positions.return_value = []
        bot.exchange_mgr.get_current_price.return_value = 2010.0

        response = bot._handle_telegram_command("/balance")

        self.assertIn("$525.50", response)
        self.assertIn("$500.00", response)
        self.assertIn("$25.50", response)

    def test_handle_telegram_command_returns_live_position_pnl(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot._running = True
        bot._cycle_count = 12
        bot.dashboard_data = {"last_update": "2026-03-22T10:00:00", "status": "running"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_balance.return_value = {"total": 525.5, "free": 500.0, "used": 25.5}
        bot.exchange_mgr.get_current_price.return_value = 2100.0
        bot.exchange_mgr.get_positions.return_value = [
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "size": 0.5,
                "entry_price": 2000.0,
                "unrealized_pnl": 50.0,
                "liquidation_price": 1800.0,
                "leverage": 5,
            }
        ]

        response = bot._handle_telegram_command("/position")

        self.assertIn("$50.00", response)
        self.assertIn("+5.00%", response)
        self.assertIn("ETHUSDT", response)

    def test_handle_telegram_command_close_returns_safe_message_when_no_position(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot._running = True
        bot._cycle_count = 12
        bot.dashboard_data = {"last_update": "2026-03-22T10:00:00", "status": "running"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_positions.return_value = []
        bot.exchange_mgr.get_balance.return_value = {"total": 500.0, "free": 500.0, "used": 0.0}
        bot.order_mgr = MagicMock()

        response = bot._handle_telegram_command("/close")

        self.assertIn("No open position", response)
        bot.order_mgr.close_position.assert_not_called()

    def test_handle_telegram_command_close_closes_position_and_reports_result(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot._running = True
        bot._cycle_count = 12
        bot.dashboard_data = {"last_update": "2026-03-22T10:00:00", "status": "running"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_positions.return_value = [
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "size": 0.5,
                "entry_price": 2000.0,
                "unrealized_pnl": 50.0,
                "liquidation_price": 1800.0,
                "leverage": 5,
            }
        ]
        bot.exchange_mgr.get_balance.return_value = {"total": 550.0, "free": 550.0, "used": 0.0}
        bot.order_mgr = MagicMock()
        bot.order_mgr.close_position.return_value = {
            "status": "closed",
            "exit_price": 2100.0,
            "pnl": 50.0,
        }

        response = bot._handle_telegram_command("/close")

        bot.order_mgr.close_position.assert_called_once_with("ETHUSDT")
        self.assertIn("MANUAL CLOSE", response)
        self.assertIn("$50.00", response)
        self.assertIn("+5.00%", response)
        self.assertIn("$550.00", response)

    def test_handle_telegram_command_help_includes_close(self):
        bot = main.TradingBot.__new__(main.TradingBot)
        bot._running = True
        bot._cycle_count = 12
        bot.dashboard_data = {"last_update": "2026-03-22T10:00:00", "status": "running"}
        bot.exchange_mgr = MagicMock()
        bot.exchange_mgr.get_positions.return_value = []
        bot.exchange_mgr.get_balance.return_value = {"total": 500.0, "free": 500.0, "used": 0.0}

        response = bot._handle_telegram_command("/help")

        self.assertIn("/close", response)


class ExchangeAndOrderRoutingTests(unittest.TestCase):
    def test_place_market_order_routes_sl_tp_to_algo_orders(self):
        exchange = MagicMock()
        exchange.place_order.return_value = {"orderId": 123, "avgPrice": "2000"}
        exchange.place_algo_order.side_effect = [
            {"algoId": 501},
            {"algoId": 502},
        ]

        with patch("core.order_manager.trade_logger.log_trade"):
            order_mgr = OrderManager(exchange)
            trade = order_mgr.place_market_order(
                side="buy",
                amount=0.01,
                symbol="ETH/USDT",
                stop_loss=1980,
                take_profit=2040,
            )

        self.assertEqual(trade["sl_order_id"], "501")
        self.assertEqual(trade["tp_order_id"], "502")
        self.assertEqual(exchange.place_algo_order.call_count, 2)

    def test_close_position_falls_back_to_current_price_when_avg_price_is_zero_string(self):
        exchange = MagicMock()
        exchange.get_positions.return_value = [
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "size": 0.01,
                "entry_price": 2000.0,
                "unrealized_pnl": 1.25,
            }
        ]
        exchange.place_order.return_value = {"avgPrice": "0.0"}
        exchange.get_current_price.return_value = 2010.5

        with patch("core.order_manager.trade_logger.log_trade"):
            order_mgr = OrderManager(exchange)
            result = order_mgr.close_position("ETH/USDT")

        self.assertEqual(result["status"], "closed")
        self.assertEqual(result["exit_price"], 2010.5)

    def test_exchange_cancel_all_orders_also_cancels_algo_orders(self):
        exchange = ExchangeManager.__new__(ExchangeManager)
        exchange._private_request = MagicMock(side_effect=[{"ok": True}, {"ok": True}])

        result = ExchangeManager.cancel_all_orders(exchange, "ETH/USDT")

        self.assertEqual(result, {"ok": True})
        calls = exchange._private_request.call_args_list
        self.assertEqual(calls[0].args[1], "/fapi/v1/allOpenOrders")
        self.assertEqual(calls[1].args[1], "/fapi/v1/algoOpenOrders")


if __name__ == "__main__":
    unittest.main()
