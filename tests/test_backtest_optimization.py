import unittest
from unittest.mock import Mock

import pandas as pd
import config
from backtest.engine import BacktestEngine


class BacktestOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = BacktestEngine(initial_capital=500)

    def test_classifies_bullish_trend_regime(self):
        regime = self.engine._classify_regime({
            "close": 2500,
            "ema_50": 2450,
            "ema_200": 2300,
            "macd": 12,
            "macd_signal": 8,
            "adx": 28,
        })

        self.assertEqual(regime, "TREND_UP")

    def test_classifies_range_when_direction_is_mixed(self):
        regime = self.engine._classify_regime({
            "close": 2500,
            "ema_50": 2490,
            "ema_200": 2480,
            "macd": 0.6,
            "macd_signal": 0.9,
            "adx": 28,
        })

        self.assertEqual(regime, "RANGE")

    def test_range_regime_prefers_mean_reversion_signal(self):
        action, confidence, style = self.engine._select_regime_trade(
            regime="RANGE",
            mr_long=0.84,
            mr_short=0.10,
            tf_long=0.25,
            tf_short=0.20,
        )

        self.assertEqual((action, style), ("LONG", "MEAN_REVERSION"))
        self.assertGreaterEqual(confidence, 0.84)

    def test_trend_regime_blocks_countertrend_trade(self):
        action, confidence, style = self.engine._select_regime_trade(
            regime="TREND_UP",
            mr_long=0.20,
            mr_short=0.91,
            tf_long=0.42,
            tf_short=0.10,
        )

        self.assertEqual((action, confidence, style), (None, 0, None))

    def test_trend_regime_prefers_trend_following_signal(self):
        action, confidence, style = self.engine._select_regime_trade(
            regime="TREND_DOWN",
            mr_long=0.15,
            mr_short=0.75,
            tf_long=0.10,
            tf_short=0.20,
        )

        self.assertEqual((action, style), ("SHORT", "TREND_FOLLOWING"))
        self.assertGreaterEqual(confidence, 0.77)

    def test_risk_multiplier_rewards_high_quality_trend_setup(self):
        multiplier = self.engine._risk_multiplier(
            regime="TREND_UP",
            confidence=0.82,
            style="TREND_FOLLOWING",
        )

        self.assertGreater(multiplier, 1.0)

    def test_backtest_engine_uses_backtest_risk_override(self):
        self.assertEqual(
            self.engine._base_risk_pct(),
            config.BACKTEST_CONFIG["risk_per_trade"],
        )

    def test_engine_reads_backtest_tuning_defaults_from_config(self):
        self.assertEqual(
            self.engine.min_confidence,
            config.BACKTEST_CONFIG["min_confidence"],
        )
        self.assertEqual(
            self.engine.cooldown_bars,
            config.BACKTEST_CONFIG["cooldown_bars"],
        )
        self.assertEqual(
            self.engine.max_hold_bars,
            config.BACKTEST_CONFIG["max_hold_bars"],
        )

    def test_run_passes_backtest_risk_budget_to_position_sizer(self):
        index = pd.date_range("2025-01-01", periods=61, freq="15min")
        df = pd.DataFrame(
            {
                "open": [100.0] * 61,
                "high": [101.0] * 61,
                "low": [99.0] * 61,
                "close": [100.0] * 61,
                "volume": [1000.0] * 61,
                "atr": [2.0] * 61,
            },
            index=index,
        )

        self.engine.analyzer.calculate_all = Mock(side_effect=lambda frame: frame)
        self.engine._compute_signals_mean_reversion = Mock(
            return_value=pd.DataFrame(
                {"long_score": [0.85] * 61, "short_score": [0.05] * 61},
                index=index,
            )
        )
        self.engine._compute_regime_trend_signals = Mock(
            return_value=pd.DataFrame(
                {"long_score": [0.2] * 61, "short_score": [0.1] * 61},
                index=index,
            )
        )
        self.engine._calculate_style_sl_tp = Mock(
            return_value={
                "stop_loss": 98.0,
                "take_profit": 103.0,
                "trailing_activation": 1.0,
                "trailing_distance": 0.5,
            }
        )

        captured = {}

        def fake_position(balance, entry_price, stop_loss, side, risk_pct=None):
            captured["risk_pct"] = risk_pct
            return {"valid": False}

        self.engine.position_sizer.calculate_position = Mock(side_effect=fake_position)

        self.engine.run(df)

        self.assertEqual(
            captured["risk_pct"],
            config.BACKTEST_CONFIG["risk_per_trade"] * config.BACKTEST_CONFIG["range_risk_multiplier"],
        )


if __name__ == "__main__":
    unittest.main()
