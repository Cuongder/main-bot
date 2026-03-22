# Main Bot

Python trading bot for Binance Futures demo trading with:

- live trading loop
- backtesting
- Telegram notifications and commands
- VPS preflight checks

## Setup

1. Install Python 3.12+.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create `.env.local` from `.env.example`.

4. Run preflight checks:

```powershell
python preflight_check.py --smoke-order
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

5. Start the bot:

```powershell
python main.py trade
```

## Useful Commands

- `python main.py backtest`
- `python preflight_check.py --smoke-order`
- `python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01`

## Telegram Commands

- `/healthcheck`
- `/balance`
- `/position`
- `/close`

## VPS Notes

Detailed runbook: `docs/vps-demo-runbook.md`
