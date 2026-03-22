# 12-Month Backtest Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tune the 12-month ETH/USDT backtest until it satisfies Profit Factor > 1.5, Max Drawdown < 20%, and Net Profit > 800 USD, or stop with evidence if the current architecture cannot reach that target.

**Architecture:** Keep the existing backtest engine and signal generator as the core loop, then improve them incrementally with regime filters, tighter entry quality, and more defensive capital management. Use local historical data where possible and add small regression tests around any new decision helpers before changing production logic.

**Tech Stack:** Python 3.12, unittest, pandas, numpy

---

### Task 1: Establish a trustworthy baseline

**Files:**
- Read: `data/historical/ETH_USDT_15m.csv`
- Read: `data/historical/ETH_USDT_5m.csv`
- Modify: `backtest/engine.py`
- Modify: `analysis/signals.py`
- Modify: `config.py`
- Test: `tests/test_backtest_optimization.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the targeted tests and verify they fail for the expected missing behavior**
- [ ] **Step 3: Run a baseline 12-month backtest from local data and capture metrics**
- [ ] **Step 4: Implement the smallest strategy and risk-management changes justified by the baseline**
- [ ] **Step 5: Re-run tests and backtest after each change set**
- [ ] **Step 6: Stop when all three targets are satisfied or when evidence shows the current design cannot get there without a larger redesign**
