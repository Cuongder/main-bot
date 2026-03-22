"""
Historical Data Collector for Backtesting
Downloads and caches 6-12 months of OHLCV data
"""
import os
import time
import pandas as pd
from datetime import datetime, timedelta
from config import TRADING_PAIR, BACKTEST_CONFIG
from utils.logger import logger


class DataCollector:
    """
    Downloads historical OHLCV data from Binance for backtesting.
    Supports incremental updates and local caching.
    """

    def __init__(self, exchange):
        self.exchange = exchange
        self.data_dir = os.path.join('data', 'historical')
        os.makedirs(self.data_dir, exist_ok=True)

    def download_data(self, symbol=None, timeframe='15m', months=None) -> pd.DataFrame:
        """
        Download historical data and save to CSV.

        Args:
            symbol: Trading pair (default: ETH/USDT)
            timeframe: Candle timeframe (5m, 15m, etc.)
            months: Number of months to download

        Returns:
            DataFrame with OHLCV data
        """
        symbol = symbol or TRADING_PAIR
        months = months or BACKTEST_CONFIG['data_months']

        # Calculate start date
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)
        since = int(start_date.timestamp() * 1000)

        file_name = f"{symbol.replace('/', '_')}_{timeframe}.csv"
        file_path = os.path.join(self.data_dir, file_name)

        # Check existing data for incremental update
        existing_df = self._load_cached(file_path)
        if existing_df is not None and not existing_df.empty:
            last_timestamp = existing_df.index[-1]
            since = int(last_timestamp.timestamp() * 1000) + 1
            logger.info(f"📦 Incremental update from {last_timestamp}")

        # Download
        logger.info(f"⬇️ Downloading {symbol} {timeframe} data ({months} months)...")
        all_data = []
        current_since = since
        batch_count = 0

        while current_since < int(end_date.timestamp() * 1000):
            try:
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol, timeframe,
                    since=current_since,
                    limit=1000
                )

                if not ohlcv:
                    break

                all_data.extend(ohlcv)
                current_since = ohlcv[-1][0] + 1
                batch_count += 1

                if batch_count % 10 == 0:
                    logger.info(f"   📊 Downloaded {len(all_data)} candles...")

                # Rate limit
                time.sleep(self.exchange.rateLimit / 1000 + 0.1)

                if len(ohlcv) < 1000:
                    break

            except Exception as e:
                logger.error(f"❌ Download error: {e}")
                time.sleep(5)
                continue

        if not all_data:
            logger.warning("⚠️ No new data downloaded")
            return existing_df if existing_df is not None else pd.DataFrame()

        # Create DataFrame
        new_df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume'
        ])
        new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
        new_df.set_index('timestamp', inplace=True)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            new_df[col] = new_df[col].astype(float)

        # Merge with existing
        if existing_df is not None and not existing_df.empty:
            combined_df = pd.concat([existing_df, new_df])
            combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
            combined_df.sort_index(inplace=True)
        else:
            combined_df = new_df

        # Save to CSV
        combined_df.to_csv(file_path)
        logger.info(
            f"✅ Saved {len(combined_df)} candles to {file_path} "
            f"({combined_df.index[0]} to {combined_df.index[-1]})"
        )

        return combined_df

    def download_all_timeframes(self, symbol=None, months=None) -> dict:
        """Download data for all configured backtest timeframes"""
        symbol = symbol or TRADING_PAIR
        months = months or BACKTEST_CONFIG['data_months']
        data = {}

        for tf in BACKTEST_CONFIG['data_timeframes']:
            logger.info(f"\n{'='*50}\n📥 Downloading {tf} data...\n{'='*50}")
            df = self.download_data(symbol, tf, months)
            if not df.empty:
                data[tf] = df
                logger.info(f"✅ {tf}: {len(df)} candles")
            else:
                logger.warning(f"⚠️ {tf}: No data")

        return data

    def load_data(self, symbol=None, timeframe='15m') -> pd.DataFrame:
        """Load cached data from CSV"""
        symbol = symbol or TRADING_PAIR
        file_name = f"{symbol.replace('/', '_')}_{timeframe}.csv"
        file_path = os.path.join(self.data_dir, file_name)
        return self._load_cached(file_path) or pd.DataFrame()

    def _load_cached(self, file_path: str) -> pd.DataFrame:
        """Load data from CSV file"""
        if not os.path.exists(file_path):
            return None

        try:
            df = pd.read_csv(file_path, index_col='timestamp', parse_dates=True)
            logger.info(f"📂 Loaded {len(df)} candles from cache")
            return df
        except Exception as e:
            logger.error(f"❌ Failed to load cached data: {e}")
            return None

    def get_data_info(self) -> list:
        """Get info about cached data files"""
        info = []
        for f in os.listdir(self.data_dir):
            if f.endswith('.csv'):
                path = os.path.join(self.data_dir, f)
                try:
                    df = pd.read_csv(path, index_col='timestamp', parse_dates=True)
                    info.append({
                        'file': f,
                        'candles': len(df),
                        'start': str(df.index[0]),
                        'end': str(df.index[-1]),
                        'size_mb': round(os.path.getsize(path) / 1024 / 1024, 2),
                    })
                except Exception:
                    info.append({'file': f, 'error': 'Could not read'})
        return info
