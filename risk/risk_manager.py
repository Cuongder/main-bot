"""
Risk Manager - Circuit breakers and trade validation
Prevents catastrophic losses through multiple safety checks
"""
import time
from datetime import datetime, timedelta
from config import RISK_CONFIG, INITIAL_CAPITAL
from utils.logger import logger, trade_logger


class RiskManager:
    """
    Multi-layer risk management system:
    1. Daily loss limit
    2. Max drawdown protection
    3. Consecutive loss handling
    4. Max concurrent positions
    5. Volatility filter
    6. News event filter
    """

    def __init__(self, config=None):
        self.config = config or RISK_CONFIG
        self.initial_capital = INITIAL_CAPITAL
        self._consecutive_losses = 0
        self._daily_pnl = 0
        self._daily_reset_date = datetime.utcnow().strftime('%Y-%m-%d')
        self._paused_until = 0
        self._trade_count_today = 0

    def can_trade(self, balance: float, open_positions: int,
                  volatility_high: bool = False, news_pause: bool = False) -> dict:
        """
        Run all risk checks before allowing a trade.

        Returns:
            dict with: allowed (bool), reasons (list of why not)
        """
        self._reset_daily_if_needed()

        reasons = []

        # 1. Check daily loss limit
        if abs(self._daily_pnl) >= self.config['max_daily_loss']:
            reasons.append(f"Daily loss limit reached (${self._daily_pnl:.2f})")

        # 2. Check max drawdown
        drawdown_pct = (self.initial_capital - balance) / self.initial_capital
        if drawdown_pct >= self.config['max_drawdown_pct']:
            reasons.append(
                f"Max drawdown exceeded ({drawdown_pct:.1%} >= {self.config['max_drawdown_pct']:.1%})"
            )

        # 3. Check minimum balance
        if balance < self.config['min_balance']:
            reasons.append(f"Balance below minimum (${balance:.2f} < ${self.config['min_balance']})")

        # 4. Check max concurrent positions
        if open_positions >= self.config['max_concurrent_positions']:
            reasons.append(
                f"Max positions reached ({open_positions}/{self.config['max_concurrent_positions']})"
            )

        # 5. Check volatility filter
        if volatility_high:
            reasons.append("High volatility detected - waiting for calmer market")

        # 6. Check news pause
        if news_pause:
            reasons.append("Paused due to significant news event")

        # 7. Check if paused
        if time.time() < self._paused_until:
            remaining = int(self._paused_until - time.time())
            reasons.append(f"Trading paused for {remaining}s")

        allowed = len(reasons) == 0

        if not allowed:
            logger.warning(f"🚫 Trade blocked: {'; '.join(reasons)}")
        else:
            logger.debug("✅ Risk check passed")

        return {
            'allowed': allowed,
            'reasons': reasons,
            'daily_pnl': round(self._daily_pnl, 2),
            'drawdown_pct': round(drawdown_pct * 100, 2),
            'consecutive_losses': self._consecutive_losses,
            'open_positions': open_positions,
        }

    def record_trade_result(self, pnl: float, is_win: bool):
        """Record a trade result for risk tracking"""
        self._daily_pnl += pnl
        self._trade_count_today += 1

        if is_win:
            self._consecutive_losses = 0
            logger.info(f"✅ Win recorded: +${pnl:.2f} | Daily PnL: ${self._daily_pnl:.2f}")
        else:
            self._consecutive_losses += 1
            logger.warning(
                f"❌ Loss recorded: -${abs(pnl):.2f} | "
                f"Consecutive losses: {self._consecutive_losses} | "
                f"Daily PnL: ${self._daily_pnl:.2f}"
            )

            # Pause after max consecutive losses
            if self._consecutive_losses >= self.config['max_consecutive_losses']:
                pause_duration = 1800  # 30 minutes
                self._paused_until = time.time() + pause_duration
                logger.warning(
                    f"⏸️ Trading paused for 30min after {self._consecutive_losses} consecutive losses"
                )

    def get_adjusted_risk(self) -> float:
        """Get risk percentage adjusted for current conditions"""
        base_risk = self.config['max_risk_per_trade']

        # Reduce risk after consecutive losses
        if self._consecutive_losses >= self.config['max_consecutive_losses']:
            base_risk *= self.config['loss_reduction_factor']

        # Reduce risk if already have daily losses
        if self._daily_pnl < 0:
            remaining_budget = self.config['max_daily_loss'] - abs(self._daily_pnl)
            if remaining_budget < self.config['max_daily_loss'] * 0.5:
                base_risk *= 0.75  # 25% reduction when >50% of daily budget used

        return base_risk

    def get_max_position_value(self, balance: float) -> float:
        """Get maximum allowed position value"""
        return balance * self.config.get('max_position_pct', 0.04) / self.config['max_risk_per_trade']

    def _reset_daily_if_needed(self):
        """Reset daily counters at midnight UTC"""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        if today != self._daily_reset_date:
            logger.info(f"📅 Daily reset: PnL was ${self._daily_pnl:.2f}, {self._trade_count_today} trades")
            self._daily_pnl = 0
            self._trade_count_today = 0
            self._daily_reset_date = today

    def get_status(self) -> dict:
        """Get current risk manager status"""
        return {
            'daily_pnl': round(self._daily_pnl, 2),
            'consecutive_losses': self._consecutive_losses,
            'trade_count_today': self._trade_count_today,
            'is_paused': time.time() < self._paused_until,
            'adjusted_risk': round(self.get_adjusted_risk() * 100, 2),
        }
