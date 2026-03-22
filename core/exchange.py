"""
Binance Futures Exchange Connection
Uses ccxt for public data + custom auth for private demo API calls
"""
import ccxt
import hashlib
import hmac
import time
import requests
from config import (
    BINANCE_API_KEY, BINANCE_SECRET_KEY,
    BINANCE_TESTNET, TRADING_PAIR, LEVERAGE
)
from utils.logger import logger


DEMO_BASE_URL = 'https://demo-fapi.binance.com'


class ExchangeManager:
    """
    Manages exchange connection and operations.
    Uses ccxt for public market data + direct REST for private demo API.
    """

    def __init__(self):
        # Public exchange instance (no auth, live data)
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
            },
        })
        self._markets_loaded = False
        self._api_key = BINANCE_API_KEY
        self._api_secret = BINANCE_SECRET_KEY

        if BINANCE_TESTNET:
            logger.info("🔧 Connected to Binance Futures DEMO TRADING")
        else:
            # For live, add auth to ccxt
            self.exchange.apiKey = self._api_key
            self.exchange.secret = self._api_secret
            logger.info("🔴 Connected to Binance Futures LIVE")

    def _sign(self, query_string: str) -> str:
        """Create HMAC SHA256 signature for Binance API"""
        return hmac.new(
            self._api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _private_request(self, method: str, endpoint: str, params: dict = None) -> dict:
        """Make authenticated request to demo Binance Futures API"""
        params = params or {}
        params['timestamp'] = int(time.time() * 1000)

        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        signature = self._sign(query_string)
        query_string += f'&signature={signature}'

        url = f"{DEMO_BASE_URL}{endpoint}?{query_string}"
        headers = {'X-MBX-APIKEY': self._api_key}

        try:
            if method.upper() == 'GET':
                resp = requests.get(url, headers=headers, timeout=15)
            elif method.upper() == 'POST':
                resp = requests.post(url, headers=headers, timeout=15)
            elif method.upper() == 'DELETE':
                resp = requests.delete(url, headers=headers, timeout=15)
            else:
                resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                return resp.json()
            else:
                error = resp.json() if resp.text else {'msg': f'HTTP {resp.status_code}'}
                logger.error(f"❌ API error: {error}")
                return {'error': True, **error}

        except Exception as e:
            logger.error(f"❌ Request error: {e}")
            return {'error': True, 'msg': str(e)}

    def load_markets(self):
        """Load market info (public data, no auth needed)"""
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._markets_loaded = True
            logger.info(f"📊 Markets loaded. Trading: {TRADING_PAIR}")

    def set_leverage(self, symbol=None, leverage=None):
        """Set leverage for a trading pair"""
        symbol = symbol or TRADING_PAIR
        leverage = leverage or LEVERAGE

        if not BINANCE_TESTNET:
            try:
                self.exchange.set_leverage(leverage, symbol)
                logger.info(f"⚡ Leverage set to {leverage}x for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set leverage: {e}")
            return

        # Demo API: set margin type and leverage
        binance_symbol = symbol.replace('/', '')
        try:
            # Set isolated margin
            result = self._private_request('POST', '/fapi/v1/marginType', {
                'symbol': binance_symbol,
                'marginType': 'ISOLATED',
            })
            if not result.get('error'):
                logger.info(f"📐 Margin mode set to ISOLATED for {symbol}")
        except Exception:
            pass

        try:
            result = self._private_request('POST', '/fapi/v1/leverage', {
                'symbol': binance_symbol,
                'leverage': leverage,
            })
            if not result.get('error'):
                logger.info(f"⚡ Leverage set to {leverage}x for {symbol}")
            else:
                logger.warning(f"⚠️ Leverage response: {result}")
        except Exception as e:
            logger.warning(f"⚠️ Could not set leverage: {e}")

    def get_balance(self) -> dict:
        """Get futures account balance"""
        if not BINANCE_TESTNET:
            try:
                balance = self.exchange.fetch_balance()
                usdt = balance.get('USDT', {})
                return {
                    'total': float(usdt.get('total', 0)),
                    'free': float(usdt.get('free', 0)),
                    'used': float(usdt.get('used', 0)),
                }
            except Exception as e:
                logger.error(f"❌ Failed to fetch balance: {e}")
                return {'total': 0, 'free': 0, 'used': 0}

        # Demo API
        result = self._private_request('GET', '/fapi/v2/account')
        if result.get('error'):
            return {'total': 0, 'free': 0, 'used': 0}

        for asset in result.get('assets', []):
            if asset['asset'] == 'USDT':
                return {
                    'total': float(asset.get('walletBalance', 0)),
                    'free': float(asset.get('availableBalance', 0)),
                    'used': float(asset.get('walletBalance', 0)) - float(asset.get('availableBalance', 0)),
                }
        return {'total': 0, 'free': 0, 'used': 0}

    def get_positions(self) -> list:
        """Get open positions"""
        if not BINANCE_TESTNET:
            try:
                positions = self.exchange.fetch_positions([TRADING_PAIR])
                return self._parse_ccxt_positions(positions)
            except Exception as e:
                logger.error(f"❌ Failed to fetch positions: {e}")
                return []

        # Demo API
        result = self._private_request('GET', '/fapi/v2/account')
        if result.get('error'):
            return []

        open_positions = []
        for pos in result.get('positions', []):
            amt = float(pos.get('positionAmt', 0))
            if amt != 0:
                open_positions.append({
                    'symbol': pos['symbol'],
                    'side': 'long' if amt > 0 else 'short',
                    'size': abs(amt),
                    'entry_price': float(pos.get('entryPrice', 0)),
                    'unrealized_pnl': float(pos.get('unrealizedProfit', 0)),
                    'liquidation_price': float(pos.get('liquidationPrice', 0)),
                    'leverage': int(pos.get('leverage', LEVERAGE)),
                    'margin_mode': pos.get('marginType', 'isolated').lower(),
                })

        return open_positions

    def place_order(self, symbol: str, side: str, order_type: str,
                    quantity: float, price: float = None, 
                    stop_price: float = None, reduce_only: bool = False) -> dict:
        """Place an order on demo API"""
        binance_symbol = symbol.replace('/', '')
        params = {
            'symbol': binance_symbol,
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': f"{quantity:.4f}",
        }

        if price and order_type.upper() in ('LIMIT', 'STOP', 'TAKE_PROFIT'):
            params['price'] = f"{price:.2f}"
            params['timeInForce'] = 'GTC'

        if stop_price and order_type.upper() in ('STOP_MARKET', 'TAKE_PROFIT_MARKET', 'STOP', 'TAKE_PROFIT'):
            params['stopPrice'] = f"{stop_price:.2f}"

        if reduce_only:
            params['reduceOnly'] = 'true'

        result = self._private_request('POST', '/fapi/v1/order', params)
        return result

    def place_algo_order(self, symbol: str, side: str, order_type: str,
                         quantity: float = None, trigger_price: float = None,
                         price: float = None, reduce_only: bool = False,
                         close_position: bool = False) -> dict:
        """Place a conditional/algo order on Binance Futures."""
        binance_symbol = symbol.replace('/', '')
        params = {
            'algoType': 'CONDITIONAL',
            'symbol': binance_symbol,
            'side': side.upper(),
            'type': order_type.upper(),
        }

        if quantity is not None and not close_position:
            params['quantity'] = f"{quantity:.4f}"
        if trigger_price is not None:
            params['triggerPrice'] = f"{trigger_price:.2f}"
        if price is not None and order_type.upper() in ('STOP', 'TAKE_PROFIT'):
            params['price'] = f"{price:.2f}"
            params['timeInForce'] = 'GTC'
        if reduce_only:
            params['reduceOnly'] = 'true'
        if close_position:
            params['closePosition'] = 'true'

        return self._private_request('POST', '/fapi/v1/algoOrder', params)

    def cancel_order(self, symbol: str, order_id: str) -> dict:
        """Cancel an order"""
        binance_symbol = symbol.replace('/', '')
        return self._private_request('DELETE', '/fapi/v1/order', {
            'symbol': binance_symbol,
            'orderId': order_id,
        })

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol"""
        binance_symbol = symbol.replace('/', '')
        result = self._private_request('DELETE', '/fapi/v1/allOpenOrders', {
            'symbol': binance_symbol,
        })
        self._private_request('DELETE', '/fapi/v1/algoOpenOrders', {
            'symbol': binance_symbol,
        })
        return result

    def get_ticker(self, symbol=None) -> dict:
        """Get current price ticker (public data)"""
        symbol = symbol or TRADING_PAIR
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                'symbol': symbol,
                'last': float(ticker['last']),
                'bid': float(ticker['bid'] or ticker['last']),
                'ask': float(ticker['ask'] or ticker['last']),
                'volume': float(ticker.get('baseVolume', 0) or 0),
                'change_pct': float(ticker.get('percentage', 0) or 0),
            }
        except Exception as e:
            logger.warning(f"⚠️ ccxt ticker failed, using REST fallback: {e}")
            # Fallback: direct REST call
            try:
                binance_symbol = symbol.replace('/', '')
                resp = requests.get(
                    f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={binance_symbol}",
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    price = float(data['price'])
                    return {
                        'symbol': symbol,
                        'last': price,
                        'bid': price,
                        'ask': price,
                        'volume': 0,
                        'change_pct': 0,
                    }
            except Exception as e2:
                logger.error(f"❌ Fallback ticker also failed: {e2}")
            return {}

    def get_current_price(self, symbol=None) -> float:
        """Get current price of a symbol"""
        ticker = self.get_ticker(symbol)
        return ticker.get('last', 0)

    def _parse_ccxt_positions(self, positions):
        """Parse ccxt position data"""
        return [
            {
                'symbol': p['symbol'],
                'side': p['side'],
                'size': float(p['contracts']),
                'entry_price': float(p['entryPrice']) if p['entryPrice'] else 0,
                'unrealized_pnl': float(p['unrealizedPnl']) if p['unrealizedPnl'] else 0,
                'liquidation_price': float(p['liquidationPrice']) if p['liquidationPrice'] else 0,
                'leverage': int(p['leverage']) if p['leverage'] else LEVERAGE,
                'margin_mode': p.get('marginMode', 'isolated'),
            }
            for p in positions
            if p['contracts'] and float(p['contracts']) > 0
        ]
