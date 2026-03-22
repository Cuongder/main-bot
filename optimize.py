import json
import numpy as np
import pandas as pd
from backtest.engine import BacktestEngine
from backtest.data_collector import DataCollector
import config

def optimize():
    print("Loading data...")
    config.ACTIVE_STRATEGY = 'MEAN_REVERSION'
    try:
        df = pd.read_csv('data/historical/ETH_USDT_15m.csv', index_col='timestamp', parse_dates=True)
    except Exception as e:
        print(f"No data: {e}")
    if df.empty:
        print("No data")
        return
        
    engine = BacktestEngine(initial_capital=500)
    
    best_pf = 0
    best_params = None
    
    # Grid search parameters for Mean Reversion
    confidences = [0.60, 0.70, 0.80, 0.90]
    sl_mults = [1.5, 2.0, 2.5]
    tp_mults = [1.0, 1.5, 2.0]
    
    for conf in confidences:
        for sl in sl_mults:
            for tp in tp_mults:
                if tp / sl > 1.5:  # Mean reversion rarely has R:R > 1.5
                    continue
                
                print(f"Testing MR Conf={conf}, SL={sl}, TP={tp}")
                
                # Apply params
                engine.min_confidence = conf
                
                # Hacky applying config
                original_sl = config.RISK_CONFIG['sl_atr_multiplier']
                original_tp = config.RISK_CONFIG['tp_atr_multiplier']
                config.RISK_CONFIG['sl_atr_multiplier'] = sl
                config.RISK_CONFIG['tp_atr_multiplier'] = tp
                
                res = engine.run(df)
                
                PF = res.get('profit_factor', 0)
                DD = res.get('max_drawdown_pct', 0)
                trades = res.get('total_trades', 0)
                net = res.get('net_profit', 0)
                
                print(f"  -> PF={PF:.2f}, DD={DD:.1f}%, Trades={trades}, Net={net:.2f}")
                
                if trades >= 10 and DD < 20.0 and PF > 1.5:
                    print(f"!!! FOUND TARGET !!! PF={PF}, DD={DD}")
                    if PF > best_pf:
                        best_pf = PF
                        best_params = (conf, sl, tp)
                        
                # Restore
                config.RISK_CONFIG['sl_atr_multiplier'] = original_sl
                config.RISK_CONFIG['tp_atr_multiplier'] = original_tp
                
    if best_params:
        print(f"\nWINNER: Conf={best_params[0]}, SL={best_params[1]}, TP={best_params[2]} (PF={best_pf})")
    else:
        print("\nCould not find parameters to reach PF > 1.5 and DD < 20%")

if __name__ == '__main__':
    optimize()
