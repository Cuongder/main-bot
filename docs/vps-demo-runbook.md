# VPS Demo Runbook

## Before copying to VPS

Run the local verification suite:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall notifications/telegram.py main.py core/exchange.py core/order_manager.py tests/test_bot_hardening.py tests/test_backtest_optimization.py tests/test_preflight.py
```

Run the preflight report:

```powershell
python preflight_check.py --smoke-order
```

Optional live smoke test on demo Binance:

```powershell
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

## On the VPS

1. Install Python and dependencies:

```powershell
pip install -r requirements.txt
```

2. Copy `.env.local`.

3. Run the preflight report first:

```powershell
python preflight_check.py --smoke-order
```

4. If Binance and Telegram both pass, run the live smoke test once:

```powershell
python preflight_check.py --live-order-smoke --symbol ETH/USDT --amount 0.01
```

5. Start the bot:

```powershell
python main.py trade
```

## What good looks like

- Binance returns non-zero balance and live price.
- Telegram check returns `ok: true`.
- `--live-order-smoke` opens and closes a tiny ETH demo position cleanly.
- No leftover `ETHUSDT` position remains.
- No leftover algo orders remain for `ETHUSDT`.
- `/healthcheck`, `/balance`, `/position`, and `/close` respond in Telegram.

## Current local baseline

- Binance demo connectivity: passed.
- Binance live order smoke test: passed.
- Telegram live connectivity from local machine: failed due network timeout to `api.telegram.org`.
- Conclusion: VPS should re-run Telegram verification before 24/7 demo launch.
