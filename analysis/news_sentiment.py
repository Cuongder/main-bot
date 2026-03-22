"""
News & Sentiment Analysis Module
Fetches crypto news and market sentiment data
"""
import requests
import time
from utils.logger import logger


class NewsSentiment:
    """
    Fetches crypto news from free APIs and calculates market sentiment.
    Sources: CryptoPanic, Alternative.me Fear & Greed Index
    """

    def __init__(self):
        self._news_cache = []
        self._news_cache_time = 0
        self._fear_greed_cache = None
        self._fear_greed_cache_time = 0
        self.news_cache_ttl = 300      # 5 minutes
        self.fg_cache_ttl = 3600       # 1 hour

    def get_latest_news(self, limit=20) -> list:
        """
        Fetch latest crypto news from CryptoPanic (free, no API key needed)

        Returns list of: {title, source, url, published_at, kind}
        """
        now = time.time()
        if self._news_cache and now - self._news_cache_time < self.news_cache_ttl:
            return self._news_cache[:limit]

        try:
            # CryptoPanic free API (no auth required for basic)
            url = "https://cryptopanic.com/api/free/v1/posts/"
            params = {
                'auth_token': 'free',
                'currencies': 'ETH',
                'kind': 'news',
                'public': 'true',
            }

            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                news = []
                for item in data.get('results', [])[:limit]:
                    news.append({
                        'title': item.get('title', ''),
                        'source': item.get('source', {}).get('title', 'Unknown'),
                        'url': item.get('url', ''),
                        'published_at': item.get('published_at', ''),
                        'kind': item.get('kind', 'news'),
                    })

                self._news_cache = news
                self._news_cache_time = now
                logger.info(f"📰 Fetched {len(news)} news items")
                return news

            else:
                logger.warning(f"⚠️ CryptoPanic API error: {response.status_code}")
                # Fallback: try alternative free source
                return self._fetch_alternative_news(limit)

        except Exception as e:
            logger.error(f"❌ News fetch error: {e}")
            return self._news_cache[:limit] if self._news_cache else []

    def _fetch_alternative_news(self, limit=20) -> list:
        """Fallback news source using CoinGecko or other free APIs"""
        try:
            # Try CoinGecko status updates as alternative
            url = "https://api.coingecko.com/api/v3/news"
            response = requests.get(url, timeout=15, headers={
                'Accept': 'application/json',
            })

            if response.status_code == 200:
                data = response.json()
                news = []
                for item in data.get('data', [])[:limit]:
                    news.append({
                        'title': item.get('title', ''),
                        'source': item.get('author', 'CoinGecko'),
                        'url': item.get('url', ''),
                        'published_at': item.get('updated_at', ''),
                        'kind': 'news',
                    })
                return news
        except Exception:
            pass

        return []

    def get_fear_greed_index(self) -> dict:
        """
        Fetch Fear & Greed Index from Alternative.me (free, no key needed)

        Returns: {value: 0-100, classification: str, timestamp: str}
        0 = Extreme Fear, 100 = Extreme Greed
        """
        now = time.time()
        if self._fear_greed_cache and now - self._fear_greed_cache_time < self.fg_cache_ttl:
            return self._fear_greed_cache

        try:
            url = "https://api.alternative.me/fng/?limit=1"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get('data'):
                    item = data['data'][0]
                    result = {
                        'value': int(item.get('value', 50)),
                        'classification': item.get('value_classification', 'Neutral'),
                        'timestamp': item.get('timestamp', ''),
                    }
                    self._fear_greed_cache = result
                    self._fear_greed_cache_time = now
                    logger.info(f"😱 Fear & Greed Index: {result['value']} ({result['classification']})")
                    return result

        except Exception as e:
            logger.error(f"❌ Fear & Greed API error: {e}")

        # Default neutral
        return {'value': 50, 'classification': 'Neutral', 'timestamp': ''}

    def get_sentiment_score(self) -> dict:
        """
        Get overall market sentiment combining news and fear/greed.

        Returns:
            dict with: score (-1 to 1), fear_greed, news_count, is_extreme
        """
        fg = self.get_fear_greed_index()
        news = self.get_latest_news(10)

        # Convert Fear & Greed to -1 to 1 scale
        fg_score = (fg['value'] - 50) / 50  # 0->-1, 50->0, 100->1

        # Check for extreme conditions
        is_extreme = fg['value'] <= 15 or fg['value'] >= 85

        return {
            'score': fg_score,
            'fear_greed_value': fg['value'],
            'fear_greed_label': fg['classification'],
            'news_count': len(news),
            'news_items': news,
            'is_extreme': is_extreme,
        }
