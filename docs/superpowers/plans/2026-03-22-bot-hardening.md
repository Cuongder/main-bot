# Trading Bot Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot's operational safety features behave as intended by wiring live dashboard state correctly, enforcing dynamic risk and volatility gating, aligning backtest timeframes, and passing richer market context into AI confirmation.

**Architecture:** Keep the current module boundaries and entry points intact. Add a small regression test suite around the existing modules, then make targeted code changes in `main.py`, `risk/position_sizer.py`, `config.py`, and `analysis/ai_analyzer.py` so behavior matches the current design intent.

**Tech Stack:** Python 3.12, unittest, Flask, pandas, ccxt

---

### Task 1: Add regression tests for the hardening pass

**Files:**
- Create: `tests/test_bot_hardening.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run the targeted test module and verify the failures point to the missing behavior**
- [ ] **Step 3: Implement the minimal production changes**
- [ ] **Step 4: Re-run the targeted tests and confirm they pass**
- [ ] **Step 5: Run a broader verification command for the touched modules**

