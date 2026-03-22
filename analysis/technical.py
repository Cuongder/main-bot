"""
Technical Analysis Module
Calculates all technical indicators for trading signals
"""
import pandas as pd
import numpy as np
import ta
from config import TA_CONFIG
from utils.logger import logger


class TechnicalAnalyzer:
    """Calculates technical indicators on OHLCV data"""

    def __init__(self, config=None):
        self.config = config or TA_CONFIG

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators and add as columns to DataFrame"""
        if df.empty or len(df) < 50:
            logger.warning("⚠️ Not enough data for technical analysis")
            return df

        df = df.copy()

        # Trend Indicators
        df = self._add_ema(df)
        df = self._add_macd(df)

        # Momentum Indicators
        df = self._add_rsi(df)
        df = self._add_stoch_rsi(df)

        # Volatility Indicators
        df = self._add_bollinger_bands(df)
        df = self._add_atr(df)
        df = self._add_adx(df)

        # Volume Indicators
        df = self._add_obv(df)
        df = self._add_volume_sma(df)

        # Drop NaN rows from indicator warmup
        df.dropna(inplace=True)

        return df

    def _add_ema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA indicators"""
        df['ema_9'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_fast'])
        df['ema_21'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_medium'])
        df['ema_50'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_slow'])

        # EMA 200 only if enough data
        if len(df) >= 200:
            df['ema_200'] = ta.trend.ema_indicator(df['close'], window=self.config['ema_trend'])
        else:
            df['ema_200'] = df['ema_50']  # Fallback

        # Crossover signals
        df['ema_fast_cross'] = (df['ema_9'] > df['ema_21']).astype(int)
        df['ema_fast_cross_prev'] = df['ema_fast_cross'].shift(1)
        df['ema_bullish_cross'] = ((df['ema_fast_cross'] == 1) & (df['ema_fast_cross_prev'] == 0)).astype(int)
        df['ema_bearish_cross'] = ((df['ema_fast_cross'] == 0) & (df['ema_fast_cross_prev'] == 1)).astype(int)

        return df

    def _add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MACD indicator"""
        macd = ta.trend.MACD(
            df['close'],
            window_slow=self.config['macd_slow'],
            window_fast=self.config['macd_fast'],
            window_sign=self.config['macd_signal']
        )
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_histogram'] = macd.macd_diff()

        # MACD crossover
        df['macd_bullish'] = ((df['macd'] > df['macd_signal']) &
                              (df['macd'].shift(1) <= df['macd_signal'].shift(1))).astype(int)
        df['macd_bearish'] = ((df['macd'] < df['macd_signal']) &
                              (df['macd'].shift(1) >= df['macd_signal'].shift(1))).astype(int)

        return df

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add RSI indicator"""
        df['rsi'] = ta.momentum.rsi(df['close'], window=self.config['rsi_period'])

        # RSI zones
        df['rsi_overbought'] = (df['rsi'] > self.config['rsi_overbought']).astype(int)
        df['rsi_oversold'] = (df['rsi'] < self.config['rsi_oversold']).astype(int)

        # RSI divergence detection (simplified)
        df['rsi_rising'] = (df['rsi'] > df['rsi'].shift(1)).astype(int)
        df['price_rising'] = (df['close'] > df['close'].shift(1)).astype(int)
        df['rsi_bullish_div'] = ((df['rsi_rising'] == 1) & (df['price_rising'] == 0)).astype(int)
        df['rsi_bearish_div'] = ((df['rsi_rising'] == 0) & (df['price_rising'] == 1)).astype(int)

        return df

    def _add_stoch_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Stochastic RSI"""
        stoch_rsi = ta.momentum.StochRSIIndicator(
            df['close'],
            window=self.config['stoch_rsi_period'],
            smooth1=self.config['stoch_rsi_k'],
            smooth2=self.config['stoch_rsi_d']
        )
        df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
        df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()

        return df

    def _add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Bollinger Bands"""
        bb = ta.volatility.BollingerBands(
            df['close'],
            window=self.config['bb_period'],
            window_dev=self.config['bb_std']
        )
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_middle'] = bb.bollinger_mavg()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = bb.bollinger_wband()
        df['bb_pband'] = bb.bollinger_pband()  # Position within bands (0-1)

        # Bollinger squeeze (low volatility -> potential breakout)
        df['bb_squeeze'] = (df['bb_width'] < df['bb_width'].rolling(20).mean() * 0.75).astype(int)

        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Average True Range"""
        df['atr'] = ta.volatility.average_true_range(
            df['high'], df['low'], df['close'],
            window=self.config['atr_period']
        )
        # ATR as percentage of price
        df['atr_pct'] = df['atr'] / df['close'] * 100

        # Volatility level (compared to 20-period average)
        df['atr_sma'] = df['atr'].rolling(20).mean()
        df['high_volatility'] = (df['atr'] > df['atr_sma'] * 1.5).astype(int)

        return df

    def _add_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ADX trend-strength indicator"""
        df['adx'] = ta.trend.adx(
            df['high'], df['low'], df['close'],
            window=14
        )
        df['trend_strength'] = np.where(df['adx'] >= 25, 'strong',
                               np.where(df['adx'] >= 18, 'moderate', 'weak'))
        return df

    def _add_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add On-Balance Volume"""
        df['obv'] = ta.volume.on_balance_volume(df['close'], df['volume'])
        df['obv_sma'] = df['obv'].rolling(20).mean()
        df['obv_trend'] = (df['obv'] > df['obv_sma']).astype(int)

        return df

    def _add_volume_sma(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume SMA for spike detection"""
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_spike'] = (df['volume'] > df['volume_sma'] * 1.5).astype(int)

        return df

    def get_latest_indicators(self, df: pd.DataFrame) -> dict:
        """Get the most recent indicator values as a dictionary"""
        if df.empty:
            return {}

        analyzed = self.calculate_all(df)
        if analyzed.empty:
            return {}

        latest = analyzed.iloc[-1]
        return latest.to_dict()
