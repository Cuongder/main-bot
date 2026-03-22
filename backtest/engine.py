"""
Backtesting Engine v2
Optimized: uses pre-calculated indicators directly, tuned for PF>1.5 & DD<20%
"""
import pandas as pd
import numpy as np
from analysis.technical import TechnicalAnalyzer
from risk.position_sizer import PositionSizer
from config import BACKTEST_CONFIG, RISK_CONFIG, LEVERAGE, ACTIVE_STRATEGY
from utils.logger import logger


class BacktestEngine:
    """
    Simulate trading strategy on historical OHLCV data.
    Uses an integrated signal scoring system optimized for backtest speed,
    supporting both TREND_FOLLOWING and MEAN_REVERSION strategies.
    """

    def __init__(self, initial_capital=None, commission=None, slippage=None):
        self.initial_capital = initial_capital or BACKTEST_CONFIG['initial_capital']
        self.commission = commission or BACKTEST_CONFIG['commission_rate']
        self.slippage = slippage or BACKTEST_CONFIG['slippage_pct']

        self.analyzer = TechnicalAnalyzer()
        self.position_sizer = PositionSizer()

        # Tunable parameters (loaded from config to support repeatable research)
        self.min_confidence = BACKTEST_CONFIG.get('min_confidence', 0.60)
        self.cooldown_bars = BACKTEST_CONFIG.get('cooldown_bars', 4)
        self.max_hold_bars = BACKTEST_CONFIG.get('max_hold_bars', 96)

        # Results
        self.trades = []
        self.equity_curve = []
        self.balance = self.initial_capital
        self.peak_balance = self.initial_capital

    def run(self, df: pd.DataFrame, higher_tf_df: pd.DataFrame = None) -> dict:
        """
        Run backtest on historical data.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 BACKTEST: {len(df)} candles | Capital: ${self.initial_capital}")
        logger.info(f"   Threshold: {self.min_confidence:.0%} | Cooldown: {self.cooldown_bars} bars")
        logger.info(f"{'='*60}")

        # Reset state
        self.trades = []
        self.equity_curve = []
        self.balance = self.initial_capital
        self.peak_balance = self.initial_capital

        # Calculate indicators on full dataset at once (fast)
        analyzed_df = self.analyzer.calculate_all(df.copy())
        if analyzed_df.empty:
            return {'error': 'Not enough data for analysis'}

        # Pre-calculate higher TF indicators
        htf_analyzed = None
        if higher_tf_df is not None and not higher_tf_df.empty:
            htf_analyzed = self.analyzer.calculate_all(higher_tf_df.copy())

        # Pre-calculate both range and trend setups, then select per regime.
        mr_signals = self._compute_signals_mean_reversion(analyzed_df)
        tf_signals = self._compute_regime_trend_signals(analyzed_df)
        signals_df = analyzed_df.copy()
        signals_df['mr_long_score'] = mr_signals['long_score']
        signals_df['mr_short_score'] = mr_signals['short_score']
        signals_df['tf_long_score'] = tf_signals['long_score']
        signals_df['tf_short_score'] = tf_signals['short_score']

        # Track state
        position = None
        consecutive_losses = 0
        daily_pnl = 0
        current_day = None
        last_trade_bar = -self.cooldown_bars  # Allow first trade

        logger.info(f"📊 Processing {len(signals_df)} candles...")

        # Walk through each candle
        for i in range(60, len(signals_df)):
            bar_time = signals_df.index[i]
            row = signals_df.iloc[i]
            price = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])
            atr = float(row.get('atr', 0) or 0)

            # Daily reset
            bar_day = str(bar_time.date())
            if bar_day != current_day:
                current_day = bar_day
                daily_pnl = 0

            # Record equity
            unrealized_pnl = 0
            if position:
                if position['side'] == 'LONG':
                    unrealized_pnl = (price - position['entry']) * position['amount']
                else:
                    unrealized_pnl = (position['entry'] - price) * position['amount']

            self.equity_curve.append({
                'timestamp': bar_time,
                'balance': self.balance + unrealized_pnl,
                'price': price,
            })

            # Check position exit conditions
            if position:
                exit_result = self._check_exit(position, high, low, price, atr, i)
                if exit_result:
                    pnl = exit_result['pnl']
                    commission_cost = position['position_value'] * self.commission * 2
                    pnl -= commission_cost

                    self.balance += pnl
                    daily_pnl += pnl

                    if self.balance > self.peak_balance:
                        self.peak_balance = self.balance

                    if pnl > 0:
                        consecutive_losses = 0
                    else:
                        consecutive_losses += 1

                    self.trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': bar_time,
                        'side': position['side'],
                        'entry_price': position['entry'],
                        'exit_price': exit_result['exit_price'],
                        'amount': position['amount'],
                        'pnl': round(pnl, 2),
                        'pnl_pct': round(pnl / self.initial_capital * 100, 2),
                        'exit_reason': exit_result['reason'],
                        'balance_after': round(self.balance, 2),
                    })
                    last_trade_bar = i
                    position = None
                    continue

            # Check entry conditions (only if no position)
            if position is None and atr > 0:
                # Cooldown between trades
                if i - last_trade_bar < self.cooldown_bars:
                    continue

                # Risk checks
                if abs(daily_pnl) >= RISK_CONFIG['max_daily_loss']:
                    continue

                drawdown = (self.peak_balance - self.balance) / self.peak_balance if self.peak_balance > 0 else 0
                # In backtesting, we want to see the full performance, so we just track drawdown
                # instead of permanently stopping the bot. In live trading, this would trigger an alert/halt.
                # if drawdown >= RISK_CONFIG['max_drawdown_pct']:
                #     continue

                regime = 'RANGE'
                htf_latest = None
                if htf_analyzed is not None and not htf_analyzed.empty:
                    htf_row = htf_analyzed[htf_analyzed.index <= bar_time]
                    if not htf_row.empty:
                        htf_latest = htf_row.iloc[-1]
                        regime = self._classify_regime(htf_latest)

                action, confidence, style = self._select_regime_trade(
                    regime=regime,
                    mr_long=float(row.get('mr_long_score', 0) or 0),
                    mr_short=float(row.get('mr_short_score', 0) or 0),
                    tf_long=float(row.get('tf_long_score', 0) or 0),
                    tf_short=float(row.get('tf_short_score', 0) or 0),
                )

                if action:
                    sl_tp = self._calculate_style_sl_tp(price, atr, action, style)
                    risk_mult = self._risk_multiplier(regime, confidence, style)
                    if consecutive_losses >= RISK_CONFIG['max_consecutive_losses']:
                        risk_mult = RISK_CONFIG['loss_reduction_factor']

                    entry_price = price * (1 + self.slippage) if action == 'LONG' else price * (1 - self.slippage)

                    pos_calc = self.position_sizer.calculate_position(
                        self.balance,
                        entry_price,
                        sl_tp['stop_loss'],
                        action,
                        risk_pct=self._base_risk_pct() * risk_mult,
                    )

                    if pos_calc.get('valid'):
                        contracts = pos_calc['contracts']
                        position = {
                            'side': action,
                            'style': style,
                            'regime': regime,
                            'confidence': round(confidence, 4),
                            'entry': entry_price,
                            'amount': contracts,
                            'position_value': pos_calc['position_size'],
                            'sl': sl_tp['stop_loss'],
                            'tp': sl_tp['take_profit'],
                            'trail_activation': sl_tp['trailing_activation'],
                            'trail_distance': sl_tp['trailing_distance'],
                            'best_price': entry_price,
                            'trail_active': False,
                            'entry_time': bar_time,
                            'entry_bar': i,
                        }

        # Close remaining position
        if position:
            last_price = float(signals_df.iloc[-1]['close'])
            if position['side'] == 'LONG':
                pnl = (last_price - position['entry']) * position['amount']
            else:
                pnl = (position['entry'] - last_price) * position['amount']
            commission_cost = position['position_value'] * self.commission * 2
            pnl -= commission_cost
            self.balance += pnl
            self.trades.append({
                'entry_time': position['entry_time'],
                'exit_time': signals_df.index[-1],
                'side': position['side'],
                'entry_price': position['entry'],
                'exit_price': last_price,
                'amount': position['amount'],
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl / self.initial_capital * 100, 2),
                'exit_reason': 'end_of_data',
                'balance_after': round(self.balance, 2),
            })

        metrics = self._calculate_metrics()
        return metrics

    def _classify_regime(self, htf_row) -> str:
        """Classify higher timeframe market structure."""
        close = float(htf_row.get('close', 0) or 0)
        ema_50 = float(htf_row.get('ema_50', 0) or 0)
        macd = float(htf_row.get('macd', 0) or 0)
        macd_signal = float(htf_row.get('macd_signal', 0) or 0)
        if close > ema_50 and macd > macd_signal:
            return 'TREND_UP'
        if close < ema_50 and macd < macd_signal:
            return 'TREND_DOWN'
        return 'RANGE'

    def _select_regime_trade(self, regime: str, mr_long: float, mr_short: float,
                             tf_long: float, tf_short: float):
        """Choose the strategy style that matches the current regime."""
        if regime == 'RANGE':
            threshold = max(self.min_confidence + 0.1, 0.7)
            if mr_long >= threshold and mr_long > mr_short:
                return 'LONG', mr_long, 'MEAN_REVERSION'
            if mr_short >= threshold and mr_short > mr_long:
                return 'SHORT', mr_short, 'MEAN_REVERSION'
            return None, 0, None

        if regime == 'TREND_UP':
            trend_confidence = mr_long + BACKTEST_CONFIG['trend_confidence_bonus']
            if trend_confidence >= max(self.min_confidence + 0.1, 0.7) and trend_confidence > mr_short:
                return 'LONG', trend_confidence, 'TREND_FOLLOWING'
            return None, 0, None

        if regime == 'TREND_DOWN':
            trend_confidence = mr_short + BACKTEST_CONFIG['trend_confidence_bonus']
            if trend_confidence >= max(self.min_confidence + 0.1, 0.7) and trend_confidence > mr_long:
                return 'SHORT', trend_confidence, 'TREND_FOLLOWING'
            return None, 0, None

        return None, 0, None

    def _risk_multiplier(self, regime: str, confidence: float, style: str) -> float:
        """Scale risk toward the cleanest setups while keeping drawdown bounded."""
        multiplier = 1.0
        if style == 'TREND_FOLLOWING' and regime.startswith('TREND'):
            multiplier = BACKTEST_CONFIG['trend_risk_multiplier']
        elif style == 'MEAN_REVERSION' and regime == 'RANGE':
            multiplier = BACKTEST_CONFIG['range_risk_multiplier']

        if confidence >= 0.9:
            multiplier += 0.25
        elif confidence < 0.75:
            multiplier -= 0.1

        return max(0.5, min(multiplier, 5.25))

    def _base_risk_pct(self) -> float:
        """Return the base risk budget used for backtesting."""
        return BACKTEST_CONFIG.get('risk_per_trade', RISK_CONFIG['max_risk_per_trade'])

    def _calculate_style_sl_tp(self, entry_price: float, atr: float, action: str, style: str) -> dict:
        """Apply a more ambitious reward profile for trend trades."""
        if style == 'TREND_FOLLOWING':
            sl_distance = atr * 1.6
            tp_distance = atr * 4.8
            trail_activation = atr * 2.4
            trail_distance = atr * 1.2

            if action == 'LONG':
                stop_loss = entry_price - sl_distance
                take_profit = entry_price + tp_distance
            else:
                stop_loss = entry_price + sl_distance
                take_profit = entry_price - tp_distance

            return {
                'stop_loss': round(stop_loss, 2),
                'take_profit': round(take_profit, 2),
                'sl_distance': round(sl_distance, 2),
                'tp_distance': round(tp_distance, 2),
                'rr_ratio': round(tp_distance / sl_distance, 2),
                'trailing_activation': round(trail_activation, 2),
                'trailing_distance': round(trail_distance, 2),
            }

        return self.position_sizer.calculate_sl_tp(entry_price, atr, action)

    def _compute_signals_mean_reversion(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute scores for Mean Reversion strategy.
        Hunts for extreme conditions where price has deviated too far from the mean (EMA50/BB).
        """
        df = df.copy()
        df['long_score'] = 0.0
        df['short_score'] = 0.0

        # === 1. Price Deviation from EMA50 ===
        # Very strong weight if price is extremely far from EMA50
        price_dev = (df['close'] - df['ema_50']) / df['ema_50']
        
        # Long when price drops significantly BELOW EMA50
        dev_long = np.where(price_dev < -0.015, 1.0,  # > 1.5% below (strong!)
                   np.where(price_dev < -0.010, 0.7,
                   np.where(price_dev < -0.005, 0.4, 0.0)))
        
        # Short when price rises significantly ABOVE EMA50
        dev_short = np.where(price_dev > 0.015, 1.0,
                    np.where(price_dev > 0.010, 0.7,
                    np.where(price_dev > 0.005, 0.4, 0.0)))

        df['long_score'] += pd.Series(dev_long, index=df.index) * 0.40
        df['short_score'] += pd.Series(dev_short, index=df.index) * 0.40

        # === 2. Extreme RSI ===
        rsi = df['rsi'].fillna(50)
        rsi_long = np.where(rsi < 25, 1.0,
                   np.where(rsi < 30, 0.7, 0.0))
        rsi_short = np.where(rsi > 75, 1.0,
                    np.where(rsi > 70, 0.7, 0.0))

        df['long_score'] += pd.Series(rsi_long, index=df.index) * 0.30
        df['short_score'] += pd.Series(rsi_short, index=df.index) * 0.30

        # === 3. Bollinger Bands Extremes ===
        pband = df.get('bb_pband', pd.Series(0.5, index=df.index)).fillna(0.5)

        bb_long = np.where(pband < 0.0, 1.0,  # Below lower band
                  np.where(pband < 0.1, 0.7, 0.0))
        bb_short = np.where(pband > 1.0, 1.0, # Above upper band
                   np.where(pband > 0.9, 0.7, 0.0))

        df['long_score'] += pd.Series(bb_long, index=df.index) * 0.30
        df['short_score'] += pd.Series(bb_short, index=df.index) * 0.30

        # Log stats
        max_scores = df[['long_score', 'short_score']].max(axis=1)
        logger.info(f"📊 Mean Reversion stats: max_long={df['long_score'].max():.3f} max_short={df['short_score'].max():.3f}")
        logger.info(f"   Signals > 0.90: {(max_scores >= 0.90).sum()} bars")

        return df

    def _compute_signals_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute long/short scores for TREND FOLLOWING strategy.
        Balanced bidirectional scoring - generates both LONG and SHORT signals.
        """
        df = df.copy()
        df['long_score'] = 0.0
        df['short_score'] = 0.0

        # === 1. EMA Trend (weight: 0.25) ===
        # Trend direction based on price vs EMA50 and EMA alignment
        ema_long = pd.Series(0.0, index=df.index)
        ema_short = pd.Series(0.0, index=df.index)

        above_ema50 = df['close'] > df['ema_50']
        ema9_above_21 = df['ema_9'] > df['ema_21']

        # EMA alignment (all bullish or all bearish)
        ema_long += above_ema50.astype(float) * 0.35
        ema_short += (~above_ema50).astype(float) * 0.35

        ema_long += ema9_above_21.astype(float) * 0.35
        ema_short += (~ema9_above_21).astype(float) * 0.35

        # EMA crossover (fresh signal)
        cross_up = ema9_above_21 & (~ema9_above_21.shift(1).fillna(True))
        cross_down = (~ema9_above_21) & (ema9_above_21.shift(1).fillna(False))
        ema_long += cross_up.astype(float) * 0.30
        ema_short += cross_down.astype(float) * 0.30

        df['long_score'] += ema_long.clip(upper=1.0) * 0.25
        df['short_score'] += ema_short.clip(upper=1.0) * 0.25

        # === 2. RSI - Symmetric (weight: 0.15) ===
        rsi = df['rsi'].fillna(50)
        # Centered at 50: below 50 = long bias, above 50 = short bias
        rsi_long = np.where(rsi < 25, 1.0,
                   np.where(rsi < 35, 0.8,
                   np.where(rsi < 45, 0.6,
                   np.where(rsi < 50, 0.3, 0.0))))
        rsi_short = np.where(rsi > 75, 1.0,
                    np.where(rsi > 65, 0.8,
                    np.where(rsi > 55, 0.6,
                    np.where(rsi > 50, 0.3, 0.0))))

        df['long_score'] += pd.Series(rsi_long, index=df.index) * 0.15
        df['short_score'] += pd.Series(rsi_short, index=df.index) * 0.15

        # === 3. MACD (weight: 0.25) ===
        macd = df['macd'].fillna(0)
        macd_sig = df['macd_signal'].fillna(0)
        macd_hist = df['macd_histogram'].fillna(0)
        prev_hist = macd_hist.shift(1).fillna(0)

        macd_long = pd.Series(0.0, index=df.index)
        macd_short = pd.Series(0.0, index=df.index)

        # MACD above/below signal
        macd_long += (macd > macd_sig).astype(float) * 0.35
        macd_short += (macd < macd_sig).astype(float) * 0.35

        # Histogram momentum
        macd_long += (macd_hist > prev_hist).astype(float) * 0.30
        macd_short += (macd_hist < prev_hist).astype(float) * 0.30

        # MACD crossover (strongest signal)
        macd_cross_up = (macd > macd_sig) & (macd.shift(1) <= macd_sig.shift(1))
        macd_cross_down = (macd < macd_sig) & (macd.shift(1) >= macd_sig.shift(1))
        macd_long += macd_cross_up.astype(float) * 0.35
        macd_short += macd_cross_down.astype(float) * 0.35

        df['long_score'] += macd_long.clip(upper=1.0) * 0.25
        df['short_score'] += macd_short.clip(upper=1.0) * 0.25

        # === 4. Bollinger Bands - Symmetric around 0.5 (weight: 0.15) ===
        pband = df.get('bb_pband', pd.Series(0.5, index=df.index)).fillna(0.5)

        # Below 0.5 → long score, above 0.5 → short score (mean reversion)
        bb_long = np.where(pband < 0.05, 1.0,
                  np.where(pband < 0.20, 0.8,
                  np.where(pband < 0.35, 0.5,
                  np.where(pband < 0.50, 0.2, 0.0))))
        bb_short = np.where(pband > 0.95, 1.0,
                   np.where(pband > 0.80, 0.8,
                   np.where(pband > 0.65, 0.5,
                   np.where(pband > 0.50, 0.2, 0.0))))

        df['long_score'] += pd.Series(bb_long, index=df.index) * 0.15
        df['short_score'] += pd.Series(bb_short, index=df.index) * 0.15

        # === 5. Volume Confirmation (weight: 0.10) ===
        vol_ma = df['volume'].rolling(20).mean()
        vol_spike = (df['volume'] > vol_ma * 1.5)
        price_up = df['close'] > df['close'].shift(1)

        vol_long = pd.Series(0.5, index=df.index)
        vol_short = pd.Series(0.5, index=df.index)
        vol_long = vol_long.where(~vol_spike, vol_long + price_up.astype(float) * 0.4)
        vol_short = vol_short.where(~vol_spike, vol_short + (~price_up).astype(float) * 0.4)

        df['long_score'] += vol_long.clip(upper=1.0) * 0.10
        df['short_score'] += vol_short.clip(upper=1.0) * 0.10

        # === 6. Stochastic RSI - Symmetric (weight: 0.10) ===
        stoch_k = df.get('stoch_rsi_k', pd.Series(50, index=df.index)).fillna(50)

        stoch_long = np.where(stoch_k < 15, 1.0,
                    np.where(stoch_k < 30, 0.7,
                    np.where(stoch_k < 45, 0.3, 0.0)))
        stoch_short = np.where(stoch_k > 85, 1.0,
                     np.where(stoch_k > 70, 0.7,
                     np.where(stoch_k > 55, 0.3, 0.0)))

        df['long_score'] += pd.Series(stoch_long, index=df.index) * 0.10
        df['short_score'] += pd.Series(stoch_short, index=df.index) * 0.10

        # Log stats
        max_long = df['long_score'].max()
        max_short = df['short_score'].max()
        max_scores = df[['long_score', 'short_score']].max(axis=1)
        logger.info(f"📊 Signal stats: max_long={max_long:.3f} max_short={max_short:.3f}")
        logger.info(f"   Above 55%: {(max_scores >= 0.55).sum()} bars")
        logger.info(f"   Above 60%: {(max_scores >= 0.60).sum()} bars")
        logger.info(f"   LONG signals: {((df['long_score'] >= self.min_confidence) & (df['long_score'] > df['short_score'])).sum()}")
        logger.info(f"   SHORT signals: {((df['short_score'] >= self.min_confidence) & (df['short_score'] > df['long_score'])).sum()}")

        return df

    def _compute_regime_trend_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Selective trend-following scores used by the regime-aware engine."""
        df = df.copy()
        df['long_score'] = 0.0
        df['short_score'] = 0.0

        close = df['close']
        ema_21 = df['ema_21']
        ema_50 = df['ema_50']
        ema_200 = df['ema_200']
        rsi = df['rsi'].fillna(50)
        adx = df.get('adx', pd.Series(15.0, index=df.index)).fillna(15.0)
        pband = df.get('bb_pband', pd.Series(0.5, index=df.index)).fillna(0.5)
        macd = df['macd'].fillna(0)
        macd_sig = df['macd_signal'].fillna(0)
        macd_hist = df['macd_histogram'].fillna(0)
        prev_hist = macd_hist.shift(1).fillna(0)
        vol_ma = df['volume'].rolling(20).mean()
        vol_spike = (df['volume'] > vol_ma * 1.2).fillna(False)

        trend_up = (close > ema_50) & (ema_50 > ema_200) & (macd > macd_sig) & (adx >= 18)
        trend_down = (close < ema_50) & (ema_50 < ema_200) & (macd < macd_sig) & (adx >= 18)

        pullback_long = (close <= ema_21 * 1.01) & (pband <= 0.45) & rsi.between(38, 58)
        pullback_short = (close >= ema_21 * 0.99) & (pband >= 0.55) & rsi.between(42, 62)

        momentum_long = (macd_hist > prev_hist) & (macd_hist > 0)
        momentum_short = (macd_hist < prev_hist) & (macd_hist < 0)

        breakout_long = vol_spike & (close > df['bb_upper'] * 0.995) & (rsi < 72)
        breakout_short = vol_spike & (close < df['bb_lower'] * 1.005) & (rsi > 28)

        df['long_score'] += trend_up.astype(float) * 0.35
        df['short_score'] += trend_down.astype(float) * 0.35
        df['long_score'] += pullback_long.astype(float) * 0.25
        df['short_score'] += pullback_short.astype(float) * 0.25
        df['long_score'] += momentum_long.astype(float) * 0.20
        df['short_score'] += momentum_short.astype(float) * 0.20
        df['long_score'] += breakout_long.astype(float) * 0.20
        df['short_score'] += breakout_short.astype(float) * 0.20

        max_scores = df[['long_score', 'short_score']].max(axis=1)
        logger.info(
            f"Selective trend stats: max_long={df['long_score'].max():.3f} "
            f"max_short={df['short_score'].max():.3f}"
        )
        logger.info(f"   Selective trend signals >= 0.60: {(max_scores >= 0.60).sum()} bars")

        return df

    def _check_exit(self, position: dict, high: float, low: float,
                    close: float, atr: float, current_bar: int) -> dict:
        """Check if position should be exited"""

        # Max hold time
        bars_held = current_bar - position.get('entry_bar', 0)
        if bars_held >= self.max_hold_bars:
            if position['side'] == 'LONG':
                pnl = (close - position['entry']) * position['amount']
            else:
                pnl = (position['entry'] - close) * position['amount']
            return {'exit_price': close, 'pnl': pnl, 'reason': 'max_hold_time'}

        if position['side'] == 'LONG':
            if low <= position['sl']:
                pnl = (position['sl'] - position['entry']) * position['amount']
                return {'exit_price': position['sl'], 'pnl': pnl, 'reason': 'stop_loss'}

            if high >= position['tp']:
                pnl = (position['tp'] - position['entry']) * position['amount']
                return {'exit_price': position['tp'], 'pnl': pnl, 'reason': 'take_profit'}

            # Trailing stop
            if close > position['best_price']:
                position['best_price'] = close

            profit = close - position['entry']
            if profit >= position['trail_activation'] and not position['trail_active']:
                position['trail_active'] = True
                position['sl'] = close - position['trail_distance']
            elif position['trail_active']:
                new_sl = position['best_price'] - position['trail_distance']
                if new_sl > position['sl']:
                    position['sl'] = new_sl

        else:  # SHORT
            if high >= position['sl']:
                pnl = (position['entry'] - position['sl']) * position['amount']
                return {'exit_price': position['sl'], 'pnl': pnl, 'reason': 'stop_loss'}

            if low <= position['tp']:
                pnl = (position['entry'] - position['tp']) * position['amount']
                return {'exit_price': position['tp'], 'pnl': pnl, 'reason': 'take_profit'}

            if close < position['best_price']:
                position['best_price'] = close

            profit = position['entry'] - close
            if profit >= position['trail_activation'] and not position['trail_active']:
                position['trail_active'] = True
                position['sl'] = close + position['trail_distance']
            elif position['trail_active']:
                new_sl = position['best_price'] + position['trail_distance']
                if new_sl < position['sl']:
                    position['sl'] = new_sl

        return None

    def _calculate_metrics(self) -> dict:
        """Calculate backtest performance metrics"""
        if not self.trades:
            return {'total_trades': 0, 'error': 'No trades executed'}

        trades_df = pd.DataFrame(self.trades)
        equity_df = pd.DataFrame(self.equity_curve)

        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]

        total_profit = float(wins['pnl'].sum()) if len(wins) > 0 else 0
        total_loss = float(abs(losses['pnl'].sum())) if len(losses) > 0 else 0

        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # Max Drawdown
        if not equity_df.empty:
            equity_df['peak'] = equity_df['balance'].cummax()
            equity_df['drawdown'] = (equity_df['peak'] - equity_df['balance']) / equity_df['peak']
            max_drawdown = float(equity_df['drawdown'].max() * 100)
        else:
            max_drawdown = 0

        # Sharpe Ratio
        if not equity_df.empty and len(equity_df) > 1:
            returns = equity_df['balance'].pct_change().dropna()
            if returns.std() > 0:
                sharpe = float(returns.mean() / returns.std() * np.sqrt(35040))
            else:
                sharpe = 0
        else:
            sharpe = 0

        win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0
        avg_win = float(wins['pnl'].mean()) if len(wins) > 0 else 0
        avg_loss = float(losses['pnl'].mean()) if len(losses) > 0 else 0

        # Trading days and daily profit
        if not trades_df.empty:
            first_trade = pd.Timestamp(trades_df.iloc[0]['entry_time'])
            last_trade = pd.Timestamp(trades_df.iloc[-1]['exit_time'])
            trading_days = max((last_trade - first_trade).days, 1)
            daily_avg = (self.balance - self.initial_capital) / trading_days
        else:
            trading_days = 0
            daily_avg = 0

        metrics = {
            'total_trades': len(trades_df),
            'winning_trades': len(wins),
            'losing_trades': len(losses),
            'win_rate': round(win_rate, 2),
            'total_profit': round(total_profit, 2),
            'total_loss': round(total_loss, 2),
            'net_profit': round(self.balance - self.initial_capital, 2),
            'net_profit_pct': round((self.balance - self.initial_capital) / self.initial_capital * 100, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'largest_win': round(float(wins['pnl'].max()), 2) if len(wins) > 0 else 0,
            'largest_loss': round(float(losses['pnl'].min()), 2) if len(losses) > 0 else 0,
            'avg_rr_ratio': round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0,
            'final_balance': round(self.balance, 2),
            'initial_capital': self.initial_capital,
            'trading_days': trading_days,
            'daily_avg_profit': round(daily_avg, 2),
            'trades': self.trades,
            'equity_curve': self.equity_curve,
            'meets_target': profit_factor > 1.5 and max_drawdown < 20,
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"📊 BACKTEST RESULTS")
        logger.info(f"{'='*60}")
        logger.info(f"📈 Net Profit:     ${metrics['net_profit']:.2f} ({metrics['net_profit_pct']:.1f}%)")
        logger.info(f"📊 Total Trades:   {metrics['total_trades']} over {trading_days} days")
        logger.info(f"✅ Win Rate:       {metrics['win_rate']:.1f}%")
        logger.info(f"💰 Profit Factor:  {metrics['profit_factor']:.2f}")
        logger.info(f"📉 Max Drawdown:   {metrics['max_drawdown_pct']:.1f}%")
        logger.info(f"📐 Sharpe Ratio:   {metrics['sharpe_ratio']:.2f}")
        logger.info(f"💵 Final Balance:  ${metrics['final_balance']:.2f}")
        logger.info(f"📅 Daily Avg:      ${metrics['daily_avg_profit']:.2f}")
        target_met = "✅ YES" if metrics['meets_target'] else "❌ NO"
        logger.info(f"🎯 Meets Target:   {target_met} (PF>1.5 & DD<20%)")
        logger.info(f"{'='*60}")

        return metrics
