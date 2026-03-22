"""
Main Trading Bot Orchestrator
24/7 automated trading loop with all components integrated
"""
import sys
import time
import signal
import threading
import traceback
from datetime import datetime

from config import (
    TRADING_PAIR, LEVERAGE, MAIN_LOOP_INTERVAL,
    NEWS_CHECK_INTERVAL, AI_ANALYSIS_INTERVAL
)

from core.exchange import ExchangeManager
from core.data_fetcher import DataFetcher
from core.order_manager import OrderManager
from analysis.technical import TechnicalAnalyzer
from analysis.signals import SignalGenerator
from analysis.ai_analyzer import AIAnalyzer
from analysis.news_sentiment import NewsSentiment
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from notifications.telegram import TelegramNotifier
from utils.logger import logger, trade_logger


class TradingBot:
    """
    Main trading bot orchestrator.
    Runs 24/7 with:
    - Technical analysis every 60 seconds
    - News sentiment check every 5 minutes
    - AI analysis every 15 minutes
    """

    def __init__(self):
        logger.info("🤖 Initializing Trading Bot...")

        # Core components
        self.exchange_mgr = ExchangeManager()
        self.data_fetcher = DataFetcher(self.exchange_mgr)
        self.order_mgr = OrderManager(self.exchange_mgr)

        # Analysis
        self.analyzer = TechnicalAnalyzer()
        self.signal_gen = SignalGenerator()
        self.ai_analyzer = AIAnalyzer()
        self.news_sentiment = NewsSentiment()

        # Risk management
        self.position_sizer = PositionSizer()
        self.risk_mgr = RiskManager()

        # Notifications
        self.telegram = TelegramNotifier()

        # State
        self._running = False
        self._last_news_check = 0
        self._last_ai_analysis = 0
        self._current_news_sentiment = None
        self._current_ai_analysis = None
        self._cycle_count = 0

        # Dashboard data (shared with dashboard server)
        self.dashboard_data = {
            'status': 'initializing',
            'balance': 0,
            'positions': [],
            'last_signal': None,
            'risk_status': {},
            'news_sentiment': None,
            'cycle_count': 0,
            'last_update': None,
        }

    def start(self):
        """Start the trading bot"""
        logger.info("="*60)
        logger.info("🚀 STARTING CRYPTO TRADING BOT")
        logger.info(f"📊 Pair: {TRADING_PAIR} | ⚡ Leverage: {LEVERAGE}x")
        logger.info("="*60)

        try:
            # Initialize exchange
            self.exchange_mgr.load_markets()
            self.exchange_mgr.set_leverage()

            # Get initial balance
            balance = self.exchange_mgr.get_balance()
            logger.info(f"💵 Account Balance: ${balance['total']:.2f}")
            self.dashboard_data['balance'] = balance['total']

            # Send startup notification
            self.telegram.notify_startup(balance['total'])
            self.telegram.start_command_loop(self._handle_telegram_command)

            # Start main loop
            self._running = True
            self.dashboard_data['status'] = 'running'

            # Handle graceful shutdown
            signal.signal(signal.SIGINT, self._handle_shutdown)
            signal.signal(signal.SIGTERM, self._handle_shutdown)

            self._main_loop()

        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            logger.error(traceback.format_exc())
            self.telegram.notify_error(f"Fatal error: {str(e)}")
            self.dashboard_data['status'] = 'error'

    def _main_loop(self):
        """Main trading loop - runs every MAIN_LOOP_INTERVAL seconds"""
        while self._running:
            try:
                self._cycle_count += 1
                cycle_start = time.time()

                logger.debug(f"\n{'─'*40} Cycle #{self._cycle_count} {'─'*40}")

                # 1. Update balance and positions
                balance = self.exchange_mgr.get_balance()
                positions = self.exchange_mgr.get_positions()
                current_price = self.exchange_mgr.get_current_price()

                self.dashboard_data['balance'] = balance['total']
                self.dashboard_data['positions'] = positions
                self.dashboard_data['last_update'] = datetime.utcnow().isoformat()
                self.dashboard_data['cycle_count'] = self._cycle_count
                self._sync_closed_position_alerts(positions, current_price)

                # 2. Check news sentiment (every 5 minutes)
                now = time.time()
                if now - self._last_news_check >= NEWS_CHECK_INTERVAL:
                    self._update_news_sentiment(current_price)
                    self._last_news_check = now

                # 3. Fetch market data (multi-timeframe)
                multi_tf_data = self.data_fetcher.fetch_multi_timeframe()

                if not multi_tf_data:
                    logger.warning("⚠️ No market data available, skipping cycle")
                    time.sleep(MAIN_LOOP_INTERVAL)
                    continue

                # 4. Generate trading signal
                signal = self.signal_gen.generate_signal(multi_tf_data)
                self.dashboard_data['last_signal'] = signal

                # 5. Monitor existing positions (trailing stops)
                if positions:
                    self._manage_positions(positions, current_price)

                # 6. Check for new trade opportunity
                if signal['action'] != 'NONE' and not positions:
                    self._evaluate_trade(signal, balance, positions, current_price)

                # 7. Update risk status
                risk_status = self.risk_mgr.get_status()
                self.dashboard_data['risk_status'] = risk_status

                # Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, MAIN_LOOP_INTERVAL - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except KeyboardInterrupt:
                self._handle_shutdown(None, None)
                break
            except Exception as e:
                logger.error(f"❌ Cycle error: {e}")
                logger.error(traceback.format_exc())
                time.sleep(MAIN_LOOP_INTERVAL)

    def _evaluate_trade(self, signal: dict, balance: dict, positions: list,
                        current_price: float):
        """Evaluate whether to execute a trade signal"""
        # Risk check
        news_pause = (self._current_news_sentiment or {}).get('should_pause', False)
        volatility_high = signal.get('high_volatility', False)

        risk_check = self.risk_mgr.can_trade(
            balance=balance['total'],
            open_positions=len(positions),
            volatility_high=volatility_high,
            news_pause=news_pause,
        )

        if not risk_check['allowed']:
            for reason in risk_check['reasons']:
                logger.warning(f"🚫 {reason}")
                self.telegram.notify_circuit_breaker(reason)
            return

        # AI confirmation (every 15 minutes or on strong signals)
        now = time.time()
        if now - self._last_ai_analysis >= AI_ANALYSIS_INTERVAL or signal['confidence'] >= 0.8:
            logger.info("🧠 Requesting AI analysis...")
            ai_result = self.ai_analyzer.analyze_market(
                signal,
                signal.get('indicators', {}),
                self._current_news_sentiment
            )
            self._current_ai_analysis = ai_result
            self._last_ai_analysis = now

            if not ai_result.get('confirmed', False):
                logger.info(f"🧠 AI rejected trade: {ai_result.get('reasoning', 'No reason')}")
                return

            logger.info(
                f"🧠 AI confirmed: {ai_result.get('suggested_action')} | "
                f"Confidence: {ai_result.get('confidence', 0):.2%} | "
                f"Risk: {ai_result.get('risk_level', 'UNKNOWN')}"
            )

        # Calculate position size
        entry_price = current_price
        atr = signal.get('atr', 0)

        if atr <= 0:
            logger.warning("⚠️ ATR is zero, cannot calculate SL/TP")
            return

        sl_tp = self.position_sizer.calculate_sl_tp(entry_price, atr, signal['action'])

        # Check R:R ratio
        if sl_tp['rr_ratio'] < 1.5:
            logger.info(f"⚠️ R:R ratio too low ({sl_tp['rr_ratio']:.2f}), skipping")
            return

        # Calculate position
        adjusted_risk = self.risk_mgr.get_adjusted_risk()
        pos = self.position_sizer.calculate_position(
            balance['free'],
            entry_price,
            sl_tp['stop_loss'],
            signal['action'],
            risk_pct=adjusted_risk,
        )

        if not pos.get('valid'):
            logger.warning(f"⚠️ Invalid position: {pos.get('reason', 'unknown')}")
            return

        # Execute trade
        side = 'buy' if signal['action'] == 'LONG' else 'sell'
        logger.info(f"\n🎯 EXECUTING {signal['action']} TRADE")

        trade_result = self.order_mgr.place_market_order(
            side=side,
            amount=pos['contracts'],
            stop_loss=sl_tp['stop_loss'],
            take_profit=sl_tp['take_profit'],
        )

        if trade_result.get('status') != 'failed':
            trade_result['risk_amount'] = pos['risk_amount']
            trade_result['balance_after'] = self.exchange_mgr.get_balance()['total']
            self.telegram.notify_trade_open(trade_result)
            logger.info(f"✅ Trade opened successfully!")
        else:
            logger.error(f"❌ Trade failed: {trade_result.get('error')}")
            self.telegram.notify_error(f"Trade failed: {trade_result.get('error')}")

    def _manage_positions(self, positions: list, current_price: float):
        """Monitor and manage open positions"""
        for pos in positions:
            entry_price = pos['entry_price']
            side = pos['side'].upper()

            # Get ATR for trailing stop calculation
            try:
                df = self.data_fetcher.fetch_ohlcv(timeframe='15m', limit=50)
                analyzed = self.analyzer.calculate_all(df)
                if not analyzed.empty:
                    atr = float(analyzed.iloc[-1].get('atr', 0))
                    sl_tp = self.position_sizer.calculate_sl_tp(entry_price, atr, side)

                    # Check trailing stop
                    should_close = self.order_mgr.update_trailing_stop(
                        symbol=pos['symbol'],
                        current_price=current_price,
                        entry_price=entry_price,
                        side=side,
                        trail_activation=sl_tp['trailing_activation'],
                        trail_distance=sl_tp['trailing_distance'],
                    )

                    if should_close:
                        result = self.order_mgr.close_position(pos['symbol'])
                        if result.get('status') == 'closed':
                            pnl = result.get('pnl', 0)
                            self.risk_mgr.record_trade_result(pnl, pnl > 0)
                            self.telegram.notify_trade_close({
                                'symbol': pos['symbol'],
                                'exit_price': current_price,
                                'pnl': pnl,
                                'pnl_pct': self._calculate_pnl_pct(
                                    pnl,
                                    entry_price,
                                    pos.get('size', 0),
                                ),
                                'exit_reason': 'trailing_stop',
                                'balance_after': self.exchange_mgr.get_balance()['total'],
                            })
            except Exception as e:
                logger.error(f"❌ Position management error: {e}")

    def _update_news_sentiment(self, current_price: float):
        """Update news sentiment analysis"""
        try:
            sentiment_data = self.news_sentiment.get_sentiment_score()

            if sentiment_data.get('news_items'):
                ai_news = self.ai_analyzer.analyze_news_impact(
                    sentiment_data['news_items'], current_price
                )
                sentiment_data.update(ai_news)

            self._current_news_sentiment = sentiment_data
            self.dashboard_data['news_sentiment'] = sentiment_data

            if sentiment_data.get('should_pause'):
                logger.warning(
                    f"⚠️ News alert: {sentiment_data.get('reasoning', 'Significant event detected')}"
                )
                self.telegram.notify_circuit_breaker(
                    f"News event: {sentiment_data.get('reasoning', '')}"
                )

        except Exception as e:
            logger.error(f"❌ News sentiment error: {e}")

    def _handle_shutdown(self, signum, frame):
        """Graceful shutdown handler"""
        logger.info("\n🛑 Shutting down trading bot...")
        self._running = False
        self.dashboard_data['status'] = 'stopped'
        self.telegram.stop_command_loop()

        # Close any open positions? (Optional - comment out to keep positions)
        # positions = self.exchange_mgr.get_positions()
        # for pos in positions:
        #     self.order_mgr.close_position(pos['symbol'])

        self.telegram.send_message("🛑 <b>Trading bot stopped</b>")
        logger.info("👋 Bot shutdown complete")
        sys.exit(0)


    def _sync_closed_position_alerts(self, positions: list, current_price: float):
        """Detect exchange-side TP/SL closures and notify once."""
        closure_events = self.order_mgr.sync_position_state(positions, current_price)
        if not closure_events:
            return

        balance_after = self.exchange_mgr.get_balance()['total']
        for event in closure_events:
            pnl = self._calculate_closed_trade_pnl(event, current_price)
            self.risk_mgr.record_trade_result(pnl, pnl > 0)
            self.telegram.notify_trade_close({
                'symbol': event.get('symbol', TRADING_PAIR),
                'exit_price': current_price,
                'pnl': pnl,
                'pnl_pct': self._calculate_pnl_pct(
                    pnl,
                    float(event.get('entry_price', 0) or 0),
                    float(event.get('amount', 0) or 0),
                ),
                'exit_reason': event.get('exit_reason', 'unknown'),
                'balance_after': balance_after,
            })

    def _handle_telegram_command(self, command: str) -> str:
        """Handle Telegram bot commands."""
        normalized = (command or "").strip().split()[0].lower()

        if normalized == '/healthcheck':
            price = self.exchange_mgr.get_current_price()
            positions = self.exchange_mgr.get_positions()
            last_update = self.dashboard_data.get('last_update', 'n/a')
            status = 'RUNNING' if self._running else 'STOPPED'
            return (
                f"🟢 <b>HEALTHCHECK</b>\n\n"
                f"Status: <b>{status}</b>\n"
                f"Cycles: {self._cycle_count}\n"
                f"Open Positions: {len(positions)}\n"
                f"Price: ${price:.2f}\n"
                f"Last Update: {last_update}"
            )

        if normalized == '/balance':
            balance = self.exchange_mgr.get_balance()
            return (
                f"💵 <b>BALANCE</b>\n\n"
                f"Total: ${balance['total']:.2f}\n"
                f"Free: ${balance['free']:.2f}\n"
                f"Used: ${balance['used']:.2f}"
            )

        if normalized == '/position':
            positions = self.exchange_mgr.get_positions()
            if not positions:
                return "📭 <b>POSITION</b>\n\nNo open position."

            current_price = self.exchange_mgr.get_current_price()
            lines = ["📌 <b>POSITION</b>", ""]
            for pos in positions:
                pnl = float(pos.get('unrealized_pnl', 0) or 0)
                pnl_pct = self._calculate_pnl_pct(
                    pnl,
                    float(pos.get('entry_price', 0) or 0),
                    float(pos.get('size', 0) or 0),
                )
                lines.extend([
                    f"Symbol: <b>{pos.get('symbol', TRADING_PAIR)}</b>",
                    f"Side: <b>{str(pos.get('side', '')).upper()}</b>",
                    f"Size: {float(pos.get('size', 0) or 0):.4f}",
                    f"Entry: ${float(pos.get('entry_price', 0) or 0):.2f}",
                    f"Mark: ${current_price:.2f}",
                    f"PnL: {'+' if pnl >= 0 else '-'}${abs(pnl):.2f} ({pnl_pct:+.2f}%)",
                    f"Leverage: {int(pos.get('leverage', LEVERAGE) or LEVERAGE)}x",
                    f"Liquidation: ${float(pos.get('liquidation_price', 0) or 0):.2f}",
                    "",
                ])
            return "\n".join(lines).strip()

        if normalized == '/close':
            positions = self.exchange_mgr.get_positions()
            if not positions:
                return "📭 <b>MANUAL CLOSE</b>\n\nNo open position to close."

            target = positions[0]
            result = self.order_mgr.close_position(target.get('symbol', TRADING_PAIR))
            if result.get('status') != 'closed':
                error = result.get('error', 'Unknown error')
                return f"🔴 <b>MANUAL CLOSE FAILED</b>\n\n{error}"

            pnl = float(result.get('pnl', 0) or 0)
            size = float(target.get('size', 0) or 0)
            entry_price = float(target.get('entry_price', 0) or 0)
            pnl_pct = self._calculate_pnl_pct(pnl, entry_price, size)
            balance_after = self.exchange_mgr.get_balance()['total']
            return (
                f"🛑 <b>MANUAL CLOSE</b>\n\n"
                f"Symbol: <b>{target.get('symbol', TRADING_PAIR)}</b>\n"
                f"Exit Price: ${float(result.get('exit_price', 0) or 0):.2f}\n"
                f"PnL: {'+' if pnl >= 0 else '-'}${abs(pnl):.2f} ({pnl_pct:+.2f}%)\n"
                f"Balance: ${balance_after:.2f}"
            )

        return (
            "🤖 <b>AVAILABLE COMMANDS</b>\n\n"
            "/healthcheck\n"
            "/balance\n"
            "/position\n"
            "/close"
        )

    def _calculate_pnl_pct(self, pnl: float, entry_price: float, size: float) -> float:
        """Calculate unrealized/realized PnL percent from position notional."""
        notional = entry_price * size
        if notional <= 0:
            return 0.0
        return (pnl / notional) * 100

    def _calculate_closed_trade_pnl(self, trade: dict, exit_price: float) -> float:
        """Estimate realized PnL for tracked TP/SL closures."""
        entry_price = float(trade.get('entry_price', 0) or 0)
        amount = float(trade.get('amount', 0) or 0)
        direction = trade.get('direction', '')
        if direction == 'LONG':
            return (exit_price - entry_price) * amount
        return (entry_price - exit_price) * amount


def run_backtest():
    """Run backtesting with historical data"""
    from backtest.data_collector import DataCollector
    from backtest.engine import BacktestEngine
    from backtest.report import BacktestReport

    logger.info("🔬 Starting Backtest Mode...")

    # Create exchange for data download (uses ccxt public API)
    exchange_mgr = ExchangeManager()
    exchange_mgr.load_markets()

    # Download data using ccxt exchange object
    collector = DataCollector(exchange_mgr.exchange)
    data = collector.download_all_timeframes()

    if '15m' not in data:
        logger.error("❌ No 15m data available for backtesting")
        return

    # Run backtest
    engine = BacktestEngine()
    higher_tf = data.get('1h', None)
    metrics = engine.run(data['15m'], higher_tf)

    # Generate report
    report = BacktestReport()
    report_path = report.generate_report(metrics)
    report.save_metrics_json(metrics)

    logger.info(f"\n📄 Report saved to: {report_path}")
    return metrics


def run_dashboard(bot_data=None):
    """Start the web dashboard"""
    from dashboard.server import create_app
    app = create_app(bot_data)
    app.run(host='0.0.0.0', port=5555, debug=False)


def start_trade_mode():
    """Start dashboard and trading bot with shared dashboard state"""
    bot = TradingBot()

    dashboard_thread = threading.Thread(
        target=run_dashboard,
        args=(bot.dashboard_data,),
        daemon=True
    )
    dashboard_thread.start()
    logger.info("Dashboard started at http://localhost:5555")

    bot.start()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Crypto Trading Bot')
    parser.add_argument('mode', nargs='?', default='trade',
                        choices=['trade', 'backtest', 'dashboard', 'download'],
                        help='Run mode: trade, backtest, dashboard, or download')
    args = parser.parse_args()

    if args.mode == 'trade':
        start_trade_mode()

    elif args.mode == 'backtest':
        run_backtest()

    elif args.mode == 'dashboard':
        run_dashboard()

    elif args.mode == 'download':
        from backtest.data_collector import DataCollector

        exchange_mgr = ExchangeManager()
        exchange_mgr.load_markets()
        collector = DataCollector(exchange_mgr.exchange)
        collector.download_all_timeframes()
