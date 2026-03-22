"""
Order Manager
Handles order placement, modification, and tracking on Binance Futures
Uses ExchangeManager's direct REST API for demo trading
"""
import time
from config import TRADING_PAIR, LEVERAGE
from utils.logger import logger, trade_logger


class OrderManager:
    """
    Manages futures orders: placement, SL/TP, trailing stops, and position tracking.
    """

    def __init__(self, exchange_manager):
        self.exchange_mgr = exchange_manager
        self._active_orders = {}
        self._trailing_stops = {}

    def place_market_order(self, side: str, amount: float, symbol=None,
                           stop_loss: float = None, take_profit: float = None) -> dict:
        """
        Place a market order with optional SL/TP.

        Args:
            side: 'buy' (LONG) or 'sell' (SHORT)
            amount: Quantity in base currency (ETH)
            symbol: Trading pair
            stop_loss: Stop-loss price
            take_profit: Take-profit price

        Returns:
            dict with order details
        """
        symbol = symbol or TRADING_PAIR

        try:
            # Place main order
            order = self.exchange_mgr.place_order(
                symbol=symbol,
                side=side,
                order_type='MARKET',
                quantity=amount,
            )

            if order.get('error'):
                logger.error(f"❌ Order failed: {order}")
                return {'status': 'failed', 'error': order.get('msg', 'Unknown error')}

            order_id = str(order.get('orderId', ''))
            entry_price = float(order.get('avgPrice', 0) or order.get('price', 0))

            # If avgPrice is 0, get current price
            if entry_price == 0:
                entry_price = self.exchange_mgr.get_current_price(symbol)

            logger.info(
                f"📈 {'LONG' if side == 'buy' else 'SHORT'} Market Order placed: "
                f"{amount:.4f} ETH @ ${entry_price:.2f}"
            )

            # Place SL/TP orders
            sl_order_id = None
            tp_order_id = None

            if stop_loss:
                sl_result = self._place_stop_loss(symbol, side, amount, stop_loss)
                sl_order_id = self._extract_conditional_order_id(sl_result)

            if take_profit:
                tp_result = self._place_take_profit(symbol, side, amount, take_profit)
                tp_order_id = self._extract_conditional_order_id(tp_result)

            # Track order
            trade_info = {
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'direction': 'LONG' if side == 'buy' else 'SHORT',
                'amount': amount,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'status': 'open',
                'opened_at': time.time(),
            }

            self._active_orders[order_id] = trade_info

            # Log trade
            trade_logger.log_trade({
                **trade_info,
                'type': 'OPEN',
            })

            return trade_info

        except Exception as e:
            logger.error(f"❌ Order placement failed: {e}")
            return {'status': 'failed', 'error': str(e)}

    def _place_stop_loss(self, symbol: str, entry_side: str,
                         amount: float, price: float) -> dict:
        """Place stop-loss order"""
        sl_side = 'SELL' if entry_side.lower() == 'buy' else 'BUY'
        try:
            result = self.exchange_mgr.place_algo_order(
                symbol=symbol,
                side=sl_side,
                order_type='STOP_MARKET',
                quantity=amount,
                trigger_price=price,
                reduce_only=True,
            )
            if not result.get('error'):
                logger.info(f"🛡️ Stop-Loss set @ ${price:.2f}")
            else:
                logger.error(f"❌ SL order failed: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ SL order failed: {e}")
            return {'error': True}

    def _place_take_profit(self, symbol: str, entry_side: str,
                           amount: float, price: float) -> dict:
        """Place take-profit order"""
        tp_side = 'SELL' if entry_side.lower() == 'buy' else 'BUY'
        try:
            result = self.exchange_mgr.place_algo_order(
                symbol=symbol,
                side=tp_side,
                order_type='TAKE_PROFIT_MARKET',
                quantity=amount,
                trigger_price=price,
                reduce_only=True,
            )
            if not result.get('error'):
                logger.info(f"🎯 Take-Profit set @ ${price:.2f}")
            else:
                logger.error(f"❌ TP order failed: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ TP order failed: {e}")
            return {'error': True}

    def close_position(self, symbol=None, order_id=None) -> dict:
        """Close an open position at market price"""
        symbol = symbol or TRADING_PAIR
        try:
            positions = self.exchange_mgr.get_positions()
            for pos in positions:
                if symbol.replace('/', '') in pos['symbol']:
                    close_side = 'SELL' if pos['side'] == 'long' else 'BUY'
                    amount = pos['size']

                    result = self.exchange_mgr.place_order(
                        symbol=symbol,
                        side=close_side,
                        order_type='MARKET',
                        quantity=amount,
                        reduce_only=True,
                    )

                    if result.get('error'):
                        logger.error(f"❌ Close failed: {result}")
                        return {'status': 'failed', 'error': result.get('msg', '')}

                    avg_price = float(result.get('avgPrice', 0) or 0)
                    exit_price = avg_price if avg_price > 0 else self.exchange_mgr.get_current_price(symbol)
                    pnl = pos['unrealized_pnl']

                    logger.info(
                        f"📉 Position closed: {amount:.4f} ETH @ ${exit_price:.2f} | "
                        f"PnL: ${pnl:.2f}"
                    )

                    # Cancel associated SL/TP orders
                    self.exchange_mgr.cancel_all_orders(symbol)

                    # Log trade
                    trade_logger.log_trade({
                        'symbol': symbol,
                        'type': 'CLOSE',
                        'side': close_side,
                        'amount': amount,
                        'exit_price': exit_price,
                        'pnl': pnl,
                        'status': 'closed',
                    })

                    # Clean up tracking
                    if order_id and order_id in self._active_orders:
                        del self._active_orders[order_id]
                    else:
                        self._remove_tracked_order(symbol)

                    return {
                        'status': 'closed',
                        'exit_price': exit_price,
                        'pnl': pnl,
                    }

            logger.warning(f"⚠️ No open position found for {symbol}")
            return {'status': 'no_position'}

        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return {'status': 'failed', 'error': str(e)}

    def update_trailing_stop(self, symbol: str, current_price: float,
                             entry_price: float, side: str,
                             trail_activation: float, trail_distance: float):
        """
        Update trailing stop-loss based on current price movement.
        Called periodically from the main loop.
        """
        key = f"{symbol}_{side}"

        if key not in self._trailing_stops:
            self._trailing_stops[key] = {
                'activated': False,
                'best_price': entry_price,
                'current_sl': None,
            }

        trail = self._trailing_stops[key]

        if side == 'LONG':
            profit = current_price - entry_price
            if profit >= trail_activation and not trail['activated']:
                trail['activated'] = True
                trail['best_price'] = current_price
                trail['current_sl'] = current_price - trail_distance
                logger.info(f"🔄 Trailing stop activated @ ${trail['current_sl']:.2f}")

            elif trail['activated'] and current_price > trail['best_price']:
                trail['best_price'] = current_price
                trail['current_sl'] = current_price - trail_distance
                logger.debug(f"🔄 Trailing stop updated @ ${trail['current_sl']:.2f}")

            if trail['activated'] and current_price <= trail['current_sl']:
                logger.info(f"🔔 Trailing stop hit @ ${current_price:.2f}")
                return True

        else:  # SHORT
            profit = entry_price - current_price
            if profit >= trail_activation and not trail['activated']:
                trail['activated'] = True
                trail['best_price'] = current_price
                trail['current_sl'] = current_price + trail_distance

            elif trail['activated'] and current_price < trail['best_price']:
                trail['best_price'] = current_price
                trail['current_sl'] = current_price + trail_distance

            if trail['activated'] and current_price >= trail['current_sl']:
                return True

        return False

    def sync_position_state(self, positions: list, current_price: float) -> list:
        """Detect tracked orders that were closed by exchange-side TP/SL orders."""
        open_symbols = {str(pos.get('symbol', '')).replace('/', '') for pos in positions}
        closed_events = []

        for order_id, trade in list(self._active_orders.items()):
            tracked_symbol = str(trade.get('symbol', '')).replace('/', '')
            if tracked_symbol in open_symbols:
                continue

            event = dict(trade)
            event['exit_reason'] = self._infer_exit_reason(trade, current_price)
            event['status'] = 'closed'
            closed_events.append(event)
            del self._active_orders[order_id]

        return closed_events

    def _remove_tracked_order(self, symbol: str):
        """Remove the first tracked order for a symbol."""
        normalized = symbol.replace('/', '')
        for order_id, trade in list(self._active_orders.items()):
            if str(trade.get('symbol', '')).replace('/', '') == normalized:
                del self._active_orders[order_id]
                return

    def _infer_exit_reason(self, trade: dict, current_price: float) -> str:
        """Infer whether the exchange closed a tracked trade via TP or SL."""
        direction = trade.get('direction', '')
        stop_loss = float(trade.get('stop_loss', 0) or 0)
        take_profit = float(trade.get('take_profit', 0) or 0)

        if direction == 'LONG':
            if take_profit and current_price >= take_profit:
                return 'take_profit'
            if stop_loss and current_price <= stop_loss:
                return 'stop_loss'
        else:
            if take_profit and current_price <= take_profit:
                return 'take_profit'
            if stop_loss and current_price >= stop_loss:
                return 'stop_loss'

        return 'unknown'

    def _extract_conditional_order_id(self, result: dict):
        """Return the server-side id for either regular or algo orders."""
        if result.get('error'):
            return None
        order_id = result.get('algoId', result.get('orderId', ''))
        return str(order_id) if order_id not in (None, '') else None

    def get_active_orders(self) -> dict:
        """Get currently tracked active orders"""
        return self._active_orders.copy()

    def cancel_all_orders(self, symbol=None):
        """Cancel all open orders"""
        symbol = symbol or TRADING_PAIR
        self.exchange_mgr.cancel_all_orders(symbol)
