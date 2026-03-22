"""
Position Sizing Calculator
Determines safe position sizes based on risk management rules
"""
from config import RISK_CONFIG, LEVERAGE
from utils.logger import logger


class PositionSizer:
    """
    Calculates position size to ensure max 1-2% risk per trade.

    Formula:
        Risk Amount = Balance × Risk%
        Position Size = Risk Amount / (SL Distance as %)
        Margin Required = Position Size / Leverage
    """

    def __init__(self, config=None):
        self.config = config or RISK_CONFIG

    def calculate_position(self, balance: float, entry_price: float,
                           stop_loss_price: float, side: str = 'LONG',
                           risk_pct: float = None) -> dict:
        """
        Calculate safe position size.

        Args:
            balance: Current account balance (USDT)
            entry_price: Expected entry price
            stop_loss_price: Stop-loss price
            side: 'LONG' or 'SHORT'

        Returns:
            dict with: position_size, margin_required, risk_amount, contracts
        """
        if entry_price <= 0 or stop_loss_price <= 0 or balance <= 0:
            return self._zero_position("Invalid price or balance")

        # Calculate stop-loss distance
        if side == 'LONG':
            sl_distance = entry_price - stop_loss_price
        else:
            sl_distance = stop_loss_price - entry_price

        if sl_distance <= 0:
            return self._zero_position("Invalid stop-loss distance")

        sl_pct = sl_distance / entry_price

        # Risk amount
        risk_pct = self.config['max_risk_per_trade'] if risk_pct is None else risk_pct
        risk_amount = balance * risk_pct

        # Position size in USDT
        position_size = risk_amount / sl_pct

        # Cap position to leverage limit
        max_position = balance * LEVERAGE
        if position_size > max_position:
            position_size = max_position
            risk_amount = position_size * sl_pct
            logger.warning(f"⚠️ Position capped to {LEVERAGE}x leverage: ${position_size:.2f}")

        # Margin required
        margin_required = position_size / LEVERAGE

        # Number of contracts (ETH quantity)
        contracts = position_size / entry_price

        result = {
            'position_size': round(position_size, 2),  # Total USDT value
            'margin_required': round(margin_required, 2),
            'risk_amount': round(risk_amount, 2),
            'risk_pct': round(risk_pct * 100, 2),
            'contracts': round(contracts, 4),  # ETH quantity
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
            'sl_distance': round(sl_distance, 2),
            'sl_pct': round(sl_pct * 100, 3),
            'side': side,
            'leverage': LEVERAGE,
            'valid': True,
        }

        logger.info(
            f"📐 Position: {contracts:.4f} ETH (${position_size:.2f}) | "
            f"Margin: ${margin_required:.2f} | Risk: ${risk_amount:.2f} ({risk_pct*100:.1f}%)"
        )

        return result

    def calculate_sl_tp(self, entry_price: float, atr: float, side: str = 'LONG') -> dict:
        """
        Calculate dynamic SL/TP based on ATR.

        Args:
            entry_price: Entry price
            atr: Current ATR value
            side: 'LONG' or 'SHORT'

        Returns:
            dict with: stop_loss, take_profit, trailing_activation, trailing_distance
        """
        sl_distance = atr * self.config['sl_atr_multiplier']
        tp_distance = atr * self.config['tp_atr_multiplier']
        trail_activation = atr * self.config['trailing_activation_atr']
        trail_distance = atr * self.config['trailing_distance_atr']

        if side == 'LONG':
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # Verify R:R ratio
        rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0
        if rr_ratio < self.config['min_risk_reward']:
            logger.warning(f"⚠️ R:R ratio {rr_ratio:.2f} below minimum {self.config['min_risk_reward']}")

        result = {
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2),
            'sl_distance': round(sl_distance, 2),
            'tp_distance': round(tp_distance, 2),
            'rr_ratio': round(rr_ratio, 2),
            'trailing_activation': round(trail_activation, 2),
            'trailing_distance': round(trail_distance, 2),
        }

        logger.info(
            f"🎯 SL: ${stop_loss:.2f} | TP: ${take_profit:.2f} | "
            f"R:R = 1:{rr_ratio:.1f}"
        )

        return result

    def adjust_for_consecutive_losses(self, base_risk: float, consecutive_losses: int) -> float:
        """Reduce risk after consecutive losses"""
        if consecutive_losses >= self.config['max_consecutive_losses']:
            adjusted = base_risk * self.config['loss_reduction_factor']
            logger.warning(
                f"⚠️ {consecutive_losses} consecutive losses - reducing risk: "
                f"{base_risk*100:.1f}% -> {adjusted*100:.1f}%"
            )
            return adjusted
        return base_risk

    def _zero_position(self, reason: str) -> dict:
        """Return zero position with reason"""
        logger.warning(f"⚠️ Zero position: {reason}")
        return {
            'position_size': 0,
            'margin_required': 0,
            'risk_amount': 0,
            'contracts': 0,
            'valid': False,
            'reason': reason,
        }
