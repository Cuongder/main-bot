"""
Signal Generator
Generates trading signals using multi-indicator confluence scoring
"""
import pandas as pd
from config import SIGNAL_CONFIG, TIMEFRAMES, ACTIVE_STRATEGY
from analysis.technical import TechnicalAnalyzer
from utils.logger import logger


class SignalGenerator:
    """
    Generates LONG/SHORT signals based on multi-indicator confluence.
    Each indicator contributes a weighted score (0-1).
    Only signals with total score >= min_confidence are actionable.
    """

    def __init__(self, config=None):
        self.config = config or SIGNAL_CONFIG
        self.analyzer = TechnicalAnalyzer()
        self.weights = self.config['weights']
        self.min_confidence = self.config['min_confidence']

    def generate_signal(self, multi_tf_data: dict) -> dict:
        """
        Generate trading signal from multi-timeframe data.

        Args:
            multi_tf_data: dict of {tf_name: DataFrame}

        Returns:
            dict with: action (LONG/SHORT/NONE), confidence, details
        """
        if 'entry' not in multi_tf_data or multi_tf_data['entry'].empty:
            return self._no_signal("No entry timeframe data")

        if ACTIVE_STRATEGY == 'MEAN_REVERSION':
            return self._generate_mean_reversion_signal(multi_tf_data)
        else:
            return self._generate_trend_signal(multi_tf_data)

    def _generate_trend_signal(self, multi_tf_data: dict) -> dict:
        """Original Trend Following logic"""

        # Analyze entry timeframe
        entry_df = self.analyzer.calculate_all(multi_tf_data['entry'])
        if entry_df.empty:
            return self._no_signal("Not enough data for analysis")

        latest = entry_df.iloc[-1]
        prev = entry_df.iloc[-2] if len(entry_df) > 1 else latest

        # Calculate individual scores
        scores = {}

        # 1. EMA Crossover Score (0 to 1)
        scores['ema_crossover'] = self._score_ema(latest, prev)

        # 2. RSI Zone Score
        scores['rsi_zone'] = self._score_rsi(latest)

        # 3. MACD Signal Score
        scores['macd_signal'] = self._score_macd(latest, prev)

        # 4. Bollinger Position Score
        scores['bollinger_position'] = self._score_bollinger(latest)

        # 5. Volume Confirmation Score
        scores['volume_confirmation'] = self._score_volume(latest)

        # 6. Multi-timeframe Alignment Score
        scores['multi_tf_alignment'] = self._score_multi_tf(multi_tf_data)

        # Calculate weighted long and short scores
        long_score = sum(
            scores[k]['long'] * self.weights[k]
            for k in scores
        )
        short_score = sum(
            scores[k]['short'] * self.weights[k]
            for k in scores
        )

        # Determine action
        action = 'NONE'
        confidence = 0
        details = []

        if long_score >= self.min_confidence and long_score > short_score:
            action = 'LONG'
            confidence = long_score
            details = [f"{k}: L={v['long']:.2f}" for k, v in scores.items()]
        elif short_score >= self.min_confidence and short_score > long_score:
            action = 'SHORT'
            confidence = short_score
            details = [f"{k}: S={v['short']:.2f}" for k, v in scores.items()]
        else:
            details = [f"L={long_score:.2f}, S={short_score:.2f} (min: {self.min_confidence})"]

        # Extract key levels
        atr = float(latest.get('atr', 0))

        signal = {
            'action': action,
            'confidence': round(confidence, 4),
            'long_score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'scores': {k: {sk: round(sv, 3) for sk, sv in v.items()} for k, v in scores.items()},
            'details': details,
            'price': float(latest['close']),
            'atr': atr,
            'rsi': float(latest.get('rsi', 50)),
            'ema_9': float(latest.get('ema_9', 0)),
            'ema_21': float(latest.get('ema_21', 0)),
            'ema_50': float(latest.get('ema_50', 0)),
            'bb_upper': float(latest.get('bb_upper', 0)),
            'bb_lower': float(latest.get('bb_lower', 0)),
            'high_volatility': bool(latest.get('high_volatility', 0)),
            'indicators': {
                'ema_50': float(latest.get('ema_50', 0)),
                'macd': float(latest.get('macd', 0)),
                'macd_signal': float(latest.get('macd_signal', 0)),
                'volume_spike': bool(latest.get('volume_spike', 0)),
                'high_volatility': bool(latest.get('high_volatility', 0)),
            },
        }

        if action != 'NONE':
            logger.info(f"🎯 Signal: {action} | Confidence: {confidence:.2%} | Price: {latest['close']:.2f}")
            for d in details:
                logger.debug(f"   └─ {d}")

        return signal

    def _score_ema(self, latest, prev) -> dict:
        """Score EMA crossover signals"""
        long_score = 0.0
        short_score = 0.0

        # Price above/below EMAs
        if latest['close'] > latest['ema_50']:
            long_score += 0.4
        else:
            short_score += 0.4

        # Fast EMA above slow
        if latest['ema_9'] > latest['ema_21']:
            long_score += 0.3
        else:
            short_score += 0.3

        # Recent crossover (stronger signal)
        if latest.get('ema_bullish_cross', 0):
            long_score += 0.3
        elif latest.get('ema_bearish_cross', 0):
            short_score += 0.3
        else:
            # Trend continuation
            if latest['ema_9'] > latest['ema_21']:
                long_score += 0.15
            else:
                short_score += 0.15

        return {'long': min(long_score, 1.0), 'short': min(short_score, 1.0)}

    def _score_rsi(self, latest) -> dict:
        """Score RSI conditions"""
        rsi = latest.get('rsi', 50)
        long_score = 0.0
        short_score = 0.0

        if rsi < 30:
            long_score = 1.0  # Oversold - strong long
        elif rsi < 40:
            long_score = 0.7  # Getting oversold
        elif rsi < 50:
            long_score = 0.5  # Below midpoint
        elif rsi < 60:
            short_score = 0.5  # Above midpoint
        elif rsi < 70:
            short_score = 0.7  # Getting overbought
        else:
            short_score = 1.0  # Overbought - strong short

        # RSI divergence bonus
        if latest.get('rsi_bullish_div', 0):
            long_score = min(long_score + 0.3, 1.0)
        if latest.get('rsi_bearish_div', 0):
            short_score = min(short_score + 0.3, 1.0)

        return {'long': long_score, 'short': short_score}

    def _score_macd(self, latest, prev) -> dict:
        """Score MACD signals"""
        long_score = 0.0
        short_score = 0.0

        macd = latest.get('macd', 0)
        signal = latest.get('macd_signal', 0)
        histogram = latest.get('macd_histogram', 0)

        # MACD above/below signal line
        if macd > signal:
            long_score += 0.4
        else:
            short_score += 0.4

        # Histogram direction
        prev_hist = prev.get('macd_histogram', 0)
        if histogram > prev_hist:
            long_score += 0.3
        else:
            short_score += 0.3

        # Fresh crossover
        if latest.get('macd_bullish', 0):
            long_score += 0.3
        elif latest.get('macd_bearish', 0):
            short_score += 0.3

        return {'long': min(long_score, 1.0), 'short': min(short_score, 1.0)}

    def _generate_mean_reversion_signal(self, multi_tf_data: dict) -> dict:
        """
        Generate trading signal based on Mean Reversion strategy.
        Hunts for extreme conditions where price has deviated too far from the mean (EMA50/BB).
        """
        entry_df = self.analyzer.calculate_all(multi_tf_data['entry'])
        if entry_df.empty:
            return self._no_signal("Not enough data for analysis")

        latest = entry_df.iloc[-1]
        
        long_score = 0.0
        short_score = 0.0
        details = []

        # 1. Price Deviation from EMA50 (Weight: 40%)
        price_dev = (latest['close'] - latest['ema_50']) / latest['ema_50']
        if price_dev < -0.015:
            long_score += 0.40
            details.append(f"Price Dev: L=1.00 (Extreme drop {-price_dev:.2%})")
        elif price_dev < -0.010:
            long_score += 0.40 * 0.7
            details.append(f"Price Dev: L=0.70 (Drop {-price_dev:.2%})")
            
        if price_dev > 0.015:
            short_score += 0.40
            details.append(f"Price Dev: S=1.00 (Extreme pump {price_dev:.2%})")
        elif price_dev > 0.010:
            short_score += 0.40 * 0.7
            details.append(f"Price Dev: S=0.70 (Pump {price_dev:.2%})")

        # 2. Extreme RSI (Weight: 30%)
        rsi = latest.get('rsi', 50)
        if rsi < 25:
            long_score += 0.30
            details.append(f"RSI: L=1.00 (Extreme Oversold {rsi:.1f})")
        elif rsi < 30:
            long_score += 0.30 * 0.7
            details.append(f"RSI: L=0.70 (Oversold {rsi:.1f})")
            
        if rsi > 75:
            short_score += 0.30
            details.append(f"RSI: S=1.00 (Extreme Overbought {rsi:.1f})")
        elif rsi > 70:
            short_score += 0.30 * 0.7
            details.append(f"RSI: S=0.70 (Overbought {rsi:.1f})")

        # 3. Bollinger Bands Extremes (Weight: 30%)
        pband = latest.get('bb_pband', 0.5)
        if pband < 0.0:
            long_score += 0.30
            details.append(f"BB: L=1.00 (Below Lower Band)")
        elif pband < 0.1:
            long_score += 0.30 * 0.7
            details.append(f"BB: L=0.70 (Near Lower Band)")
            
        if pband > 1.0:
            short_score += 0.30
            details.append(f"BB: S=1.00 (Above Upper Band)")
        elif pband > 0.9:
            short_score += 0.30 * 0.7
            details.append(f"BB: S=0.70 (Near Upper Band)")

        # Determine action
        action = 'NONE'
        confidence = 0
        
        # Mean Reversion requires high confidence (e.g. 0.90) which is defined in config typically, 
        # but since we combined it, we check against config threshold
        if long_score >= self.min_confidence and long_score > short_score:
            action = 'LONG'
            confidence = long_score
        elif short_score >= self.min_confidence and short_score > long_score:
            action = 'SHORT'
            confidence = short_score
        else:
            details.append(f"Total: L={long_score:.2f}, S={short_score:.2f} (min: {self.min_confidence})")

        atr = float(latest.get('atr', 0))

        signal = {
            'action': action,
            'confidence': round(confidence, 4),
            'long_score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'scores': {}, # Omitted for mean reversion
            'details': details,
            'price': float(latest['close']),
            'atr': atr,
            'rsi': float(latest.get('rsi', 50)),
            'ema_9': float(latest.get('ema_9', 0)),
            'ema_21': float(latest.get('ema_21', 0)),
            'ema_50': float(latest.get('ema_50', 0)),
            'bb_upper': float(latest.get('bb_upper', 0)),
            'bb_lower': float(latest.get('bb_lower', 0)),
            'high_volatility': bool(latest.get('high_volatility', 0)),
            'indicators': {
                'ema_50': float(latest.get('ema_50', 0)),
                'macd': float(latest.get('macd', 0)),
                'macd_signal': float(latest.get('macd_signal', 0)),
                'volume_spike': bool(latest.get('volume_spike', 0)),
                'high_volatility': bool(latest.get('high_volatility', 0)),
            },
        }

        if action != 'NONE':
            logger.info(f"🎯 ⚡ Mean Reversion Signal: {action} | Confidence: {confidence:.2%} | Price: {latest['close']:.2f}")
            for d in details:
                logger.debug(f"   └─ {d}")

        return signal

    def _score_bollinger(self, latest) -> dict:
        """Score Bollinger Band position"""
        long_score = 0.0
        short_score = 0.0

        pband = latest.get('bb_pband', 0.5)  # 0=lower, 1=upper

        if pband < 0.1:
            long_score = 1.0      # Near lower band - potential bounce
        elif pband < 0.3:
            long_score = 0.7
        elif pband < 0.5:
            long_score = 0.4
        elif pband < 0.7:
            short_score = 0.4
        elif pband < 0.9:
            short_score = 0.7
        else:
            short_score = 1.0     # Near upper band - potential reversal

        # Squeeze detection bonus (breakout potential)
        if latest.get('bb_squeeze', 0):
            long_score = min(long_score + 0.2, 1.0)
            short_score = min(short_score + 0.2, 1.0)

        return {'long': long_score, 'short': short_score}

    def _score_volume(self, latest) -> dict:
        """Score volume confirmation"""
        long_score = 0.5  # Neutral default
        short_score = 0.5

        # OBV trending up = bullish volume
        if latest.get('obv_trend', 0):
            long_score = 0.7
            short_score = 0.3
        else:
            long_score = 0.3
            short_score = 0.7

        # Volume spike adds weight to current direction
        if latest.get('volume_spike', 0):
            if latest['close'] > latest.get('ema_9', latest['close']):
                long_score = min(long_score + 0.3, 1.0)
            else:
                short_score = min(short_score + 0.3, 1.0)

        return {'long': long_score, 'short': short_score}

    def _score_multi_tf(self, multi_tf_data: dict) -> dict:
        """Score multi-timeframe alignment"""
        long_votes = 0
        short_votes = 0
        total_votes = 0

        for tf_name, df in multi_tf_data.items():
            if tf_name == 'entry' or df.empty:
                continue

            analyzed = self.analyzer.calculate_all(df)
            if analyzed.empty:
                continue

            latest = analyzed.iloc[-1]
            total_votes += 1

            # Check trend direction
            if latest['close'] > latest.get('ema_50', latest['close']):
                long_votes += 1
            else:
                short_votes += 1

            # MACD direction
            if latest.get('macd', 0) > latest.get('macd_signal', 0):
                long_votes += 0.5
                total_votes += 0.5
            else:
                short_votes += 0.5
                total_votes += 0.5

        if total_votes == 0:
            return {'long': 0.5, 'short': 0.5}

        return {
            'long': long_votes / total_votes,
            'short': short_votes / total_votes
        }

    def _no_signal(self, reason: str) -> dict:
        """Return a no-signal result"""
        return {
            'action': 'NONE',
            'confidence': 0,
            'long_score': 0,
            'short_score': 0,
            'scores': {},
            'details': [reason],
            'price': 0,
            'atr': 0,
            'rsi': 50,
            'high_volatility': False,
            'indicators': {},
        }
