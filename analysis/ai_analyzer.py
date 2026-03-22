"""
AI-Powered Market Analyzer
Uses cx/gpt-5.4 model for intelligent market analysis and trade confirmation
"""
import json
import aiohttp
import asyncio
import time
from config import AI_API_URL, AI_API_KEY, AI_MODEL
from utils.logger import logger


class AIAnalyzer:
    """
    Uses AI model to analyze market conditions and confirm trade signals.
    Acts as the final decision gate before order placement.
    """

    def __init__(self):
        self.api_url = AI_API_URL
        self.api_key = AI_API_KEY
        self.model = AI_MODEL
        self._last_call_time = 0
        self._min_interval = 30  # Minimum 30s between calls

    def _build_headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    async def _call_ai(self, messages: list, max_tokens=1000) -> str:
        """Make async call to AI API"""
        # Rate limiting
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

        payload = {
            'model': self.model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': 0.3,  # Low temperature for consistent analysis
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/chat/completions",
                    headers=self._build_headers(),
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    self._last_call_time = time.time()

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"❌ AI API error {response.status}: {error_text}")
                        return ""

                    result = await response.json()
                    return result['choices'][0]['message']['content']

        except asyncio.TimeoutError:
            logger.error("❌ AI API timeout")
            return ""
        except Exception as e:
            logger.error(f"❌ AI API error: {e}")
            return ""

    def call_ai_sync(self, messages: list, max_tokens=1000) -> str:
        """Synchronous wrapper for AI calls"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._call_ai(messages, max_tokens))
                    return future.result(timeout=90)
            else:
                return loop.run_until_complete(self._call_ai(messages, max_tokens))
        except RuntimeError:
            return asyncio.run(self._call_ai(messages, max_tokens))

    def analyze_market(self, signal: dict, indicators: dict, news_sentiment: dict = None) -> dict:
        """
        Ask AI to analyze market conditions and confirm/reject a trade signal.

        Returns:
            dict with: confirmed (bool), confidence (0-1), reasoning, risk_level
        """
        # Build analysis prompt
        prompt = self._build_analysis_prompt(signal, indicators, news_sentiment)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert crypto futures trader and market analyst. "
                    "Analyze the provided market data and trading signal. "
                    "Respond ONLY in valid JSON format with these fields: "
                    '{"confirmed": true/false, "confidence": 0.0-1.0, '
                    '"reasoning": "brief explanation", "risk_level": "LOW/MEDIUM/HIGH", '
                    '"suggested_action": "LONG/SHORT/WAIT", '
                    '"market_condition": "TRENDING_UP/TRENDING_DOWN/RANGING/VOLATILE"}'
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        response = self.call_ai_sync(messages, max_tokens=500)

        if not response:
            logger.warning("⚠️ AI analysis unavailable, using signal as-is")
            return {
                'confirmed': signal.get('action') != 'NONE',
                'confidence': signal.get('confidence', 0),
                'reasoning': 'AI unavailable - using technical signal only',
                'risk_level': 'MEDIUM',
                'suggested_action': signal.get('action', 'WAIT'),
                'market_condition': 'UNKNOWN',
            }

        # Parse response
        return self._parse_ai_response(response, signal)

    def analyze_news_impact(self, news_items: list, current_price: float) -> dict:
        """
        Ask AI to analyze news impact on trading decisions.

        Returns:
            dict with: sentiment (-1 to 1), impact_level, should_pause, reasoning
        """
        if not news_items:
            return {
                'sentiment': 0,
                'impact_level': 'NONE',
                'should_pause': False,
                'reasoning': 'No recent news'
            }

        news_text = "\n".join([
            f"- [{n.get('source', 'Unknown')}] {n.get('title', '')}"
            for n in news_items[:10]
        ])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a crypto news analyst. Analyze these recent crypto news headlines "
                    "and assess their potential impact on ETH/USDT price. "
                    "Respond ONLY in valid JSON: "
                    '{"sentiment": -1.0 to 1.0, "impact_level": "NONE/LOW/MEDIUM/HIGH/EXTREME", '
                    '"should_pause": true/false, "reasoning": "brief explanation", '
                    '"expected_direction": "UP/DOWN/NEUTRAL"}'
                )
            },
            {
                "role": "user",
                "content": f"Current ETH price: ${current_price:.2f}\n\nRecent news:\n{news_text}"
            }
        ]

        response = self.call_ai_sync(messages, max_tokens=300)

        if not response:
            return {
                'sentiment': 0,
                'impact_level': 'UNKNOWN',
                'should_pause': False,
                'reasoning': 'AI unavailable'
            }

        try:
            # Try to extract JSON from response
            result = self._extract_json(response)
            return {
                'sentiment': float(result.get('sentiment', 0)),
                'impact_level': result.get('impact_level', 'UNKNOWN'),
                'should_pause': bool(result.get('should_pause', False)),
                'reasoning': result.get('reasoning', ''),
                'expected_direction': result.get('expected_direction', 'NEUTRAL'),
            }
        except Exception as e:
            logger.error(f"❌ Failed to parse news analysis: {e}")
            return {
                'sentiment': 0,
                'impact_level': 'UNKNOWN',
                'should_pause': False,
                'reasoning': f'Parse error: {str(e)}'
            }

    def _build_analysis_prompt(self, signal: dict, indicators: dict, news_sentiment: dict = None) -> str:
        """Build comprehensive analysis prompt"""
        parts = [
            f"## Trading Signal Analysis Request",
            f"**Pair**: ETH/USDT | **Leverage**: 5x",
            f"**Current Price**: ${signal.get('price', 0):.2f}",
            f"**Signal**: {signal.get('action', 'NONE')} | Confidence: {signal.get('confidence', 0):.2%}",
            "",
            "### Technical Indicators:",
            f"- RSI(14): {signal.get('rsi', 50):.1f}",
            f"- EMA 9: ${signal.get('ema_9', 0):.2f} | EMA 21: ${signal.get('ema_21', 0):.2f}",
            f"- ATR: ${signal.get('atr', 0):.2f}",
            f"- Bollinger: Upper ${signal.get('bb_upper', 0):.2f} | Lower ${signal.get('bb_lower', 0):.2f}",
            "",
            f"### Score Breakdown:",
        ]

        if indicators:
            parts.extend([
                "",
                "### Additional Indicator Context:",
            ])

            if 'ema_50' in indicators:
                parts.append(f"- EMA 50: ${float(indicators['ema_50']):.2f}")
            if 'macd' in indicators and 'macd_signal' in indicators:
                parts.append(
                    f"- MACD: {float(indicators['macd']):.2f} | "
                    f"Signal: {float(indicators['macd_signal']):.2f}"
                )
            if 'volume_spike' in indicators:
                parts.append(f"- Volume Spike: {'YES' if indicators['volume_spike'] else 'NO'}")
            if 'high_volatility' in indicators:
                parts.append(f"- High Volatility: {'YES' if indicators['high_volatility'] else 'NO'}")

        for k, v in signal.get('scores', {}).items():
            parts.append(f"- {k}: Long={v.get('long', 0):.2f} Short={v.get('short', 0):.2f}")

        if news_sentiment:
            parts.extend([
                "",
                f"### News Sentiment:",
                f"- Sentiment Score: {news_sentiment.get('sentiment', 0):.2f}",
                f"- Impact Level: {news_sentiment.get('impact_level', 'UNKNOWN')}",
                f"- Direction: {news_sentiment.get('expected_direction', 'NEUTRAL')}",
            ])

        parts.extend([
            "",
            "Should this trade be executed? Consider risk with 5x leverage and $500 capital.",
            "Focus on: trend alignment, momentum, volatility, and risk/reward."
        ])

        return "\n".join(parts)

    def _parse_ai_response(self, response: str, signal: dict) -> dict:
        """Parse AI response into structured result"""
        try:
            result = self._extract_json(response)
            return {
                'confirmed': bool(result.get('confirmed', False)),
                'confidence': float(result.get('confidence', 0)),
                'reasoning': result.get('reasoning', ''),
                'risk_level': result.get('risk_level', 'MEDIUM'),
                'suggested_action': result.get('suggested_action', 'WAIT'),
                'market_condition': result.get('market_condition', 'UNKNOWN'),
            }
        except Exception as e:
            logger.error(f"❌ Failed to parse AI response: {e}")
            return {
                'confirmed': False,
                'confidence': 0,
                'reasoning': f'Parse error: {str(e)}',
                'risk_level': 'HIGH',
                'suggested_action': 'WAIT',
                'market_condition': 'UNKNOWN',
            }

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from AI response (handles markdown code blocks)"""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code block
        import re
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Try finding JSON object in text
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))

        raise ValueError(f"No JSON found in response: {text[:200]}")
