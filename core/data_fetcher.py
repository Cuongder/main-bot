"""
Market Data Fetcher
Fetches OHLCV candlestick data for multiple timeframes
"""
import pandas as pd
import time
from config import TRADING_PAIR, TIMEFRAMES
from utils.logger import logger


class DataFetcher:
    """Fetches and caches market data from Binance"""

    def __init__(self, exchange_manager):
        self.exchange = exchange_manager.exchange
        self._cache = {}
        self._cache_expiry = {}

    def fetch_ohlcv(self, symbol=None, timeframe='15m', limit=200) -> pd.DataFrame:
        """
        Fetch OHLCV data and return as DataFrame

        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        """
        symbol = symbol or TRADING_PAIR
        cache_key = f"{symbol}_{timeframe}"

        # Check cache (valid for 30 seconds for live data)
        now = time.time()
        if cache_key in self._cache and now - self._cache_expiry.get(cache_key, 0) < 30:
            return self._cache[cache_key]

        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            df = pd.DataFrame(ohlcv, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume'
            ])

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)

            # Convert to float
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            # Cache
            self._cache[cache_key] = df
            self._cache_expiry[cache_key] = now

            return df

        except Exception as e:
            logger.error(f"❌ Failed to fetch OHLCV {symbol} {timeframe}: {e}")
            # Return cached data if available
            if cache_key in self._cache:
                logger.warning("⚠️ Using cached data")
                return self._cache[cache_key]
            return pd.DataFrame()

    def fetch_multi_timeframe(self, symbol=None) -> dict:
        """
        Fetch data for all configured timeframes

        Returns: dict of {timeframe_name: DataFrame}
        """
        symbol = symbol or TRADING_PAIR
        data = {}

        for tf_name, tf_value in TIMEFRAMES.items():
            df = self.fetch_ohlcv(symbol, tf_value)
            if not df.empty:
                data[tf_name] = df
                logger.debug(f"📊 Fetched {len(df)} candles for {tf_value}")
            else:
                logger.warning(f"⚠️ No data for {tf_value}")

        return data

    def get_recent_candles(self, symbol=None, timeframe='15m', count=50) -> pd.DataFrame:
        """Get most recent N candles"""
        df = self.fetch_ohlcv(symbol, timeframe, limit=count)
        return df.tail(count) if not df.empty else df

    def fetch_historical_ohlcv(self, symbol=None, timeframe='15m', since=None, limit=1000) -> pd.DataFrame:
        """
        Fetch historical OHLCV data with pagination
        Used for backtesting data collection
        """
        symbol = symbol or TRADING_PAIR
        all_data = []
        current_since = since

        while True:
            try:
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol, timeframe,
                    since=current_since,
                    limit=min(limit, 1000)
                )

                if not ohlcv:
                    break

                all_data.extend(ohlcv)

                # Move to next batch
                current_since = ohlcv[-1][0] + 1  # +1ms to avoid overlap

                # Rate limit
                time.sleep(self.exchange.rateLimit / 1000)

                # Check if we've got enough
                if len(ohlcv) < 1000:
                    break

                logger.debug(f"📦 Fetched {len(all_data)} candles so far...")

            except Exception as e:
                logger.error(f"❌ Error fetching historical data: {e}")
                time.sleep(5)
                continue

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        # Remove duplicates
        df = df[~df.index.duplicated(keep='last')]
        df.sort_index(inplace=True)

        logger.info(f"📊 Downloaded {len(df)} historical candles for {symbol} {timeframe}")
        return df
