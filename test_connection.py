"""Diagnose why no trades are generated"""
import pandas as pd
from core.exchange import ExchangeManager
from backtest.data_collector import DataCollector
from analysis.technical import TechnicalAnalyzer
from analysis.signals import SignalGenerator
from config import SIGNAL_CONFIG

# Load historical data
collector = DataCollector(None)  # We just need to load cached data
df = collector.load_data(timeframe='15m')

if df.empty:
    print("No cached data found!")
    exit()

print(f"Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}")

# Analyze
analyzer = TechnicalAnalyzer()
sig_gen = SignalGenerator()

analyzed = analyzer.calculate_all(df.copy())
print(f"Analyzed {len(analyzed)} candles")

# Check signal scores across the dataset
max_long = 0
max_short = 0
signal_count = 0
above_50 = 0
above_60 = 0
above_70 = 0

# Sample every 100 candles to be fast
for i in range(200, len(analyzed), 50):
    window = analyzed.iloc[max(0, i-100):i+1]
    multi_tf = {'entry': window}
    signal = sig_gen.generate_signal(multi_tf)
    
    long_s = signal['long_score']
    short_s = signal['short_score']
    max_score = max(long_s, short_s)
    
    if max_score > max_long if long_s > short_s else max_score > max_short:
        if long_s > short_s:
            max_long = max(max_long, long_s)
        else:
            max_short = max(max_short, short_s)
    
    if max_score >= 0.50:
        above_50 += 1
    if max_score >= 0.60:
        above_60 += 1
    if max_score >= 0.70:
        above_70 += 1
    signal_count += 1

    if signal_count <= 5:
        print(f"\nSample {signal_count}: L={long_s:.3f} S={short_s:.3f} Action={signal['action']}")
        if signal.get('scores'):
            for k, v in signal['scores'].items():
                print(f"  {k}: L={v.get('long',0):.3f} S={v.get('short',0):.3f}")

print(f"\n{'='*50}")
print(f"Total samples: {signal_count}")
print(f"Max long score: {max_long:.3f}")
print(f"Max short score: {max_short:.3f}")
print(f"Above 50%: {above_50} ({above_50/signal_count*100:.1f}%)")
print(f"Above 60%: {above_60} ({above_60/signal_count*100:.1f}%)")
print(f"Above 70%: {above_70} ({above_70/signal_count*100:.1f}%)")
print(f"Current min_confidence: {SIGNAL_CONFIG['min_confidence']}")
