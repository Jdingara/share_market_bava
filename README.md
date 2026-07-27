# Share Market Bava — SPFS Strategy

> **See `PROJECT_STATUS.md` for the full project state** — goal, strategy rules, current backtest result, and technical findings. Read that first, especially after a break or when picking this up with a different AI assistant.

A new, independent NIFTY 50 options trading strategy ("SPFS": locked ATM + Sniper premium level + OTM confirmation + Square Number execution), built as a **separate project** from the older XGBoost/rule-based bot (a different repo - see `PROJECT_STATUS.md` for why). This project will get its own Kite Connect API app and its own Zerodha account once it's ready to move past backtesting.

## Current phase: backtest only

There is no live or paper trading code here yet, and no `.env`/Kite credentials are wired up. Everything so far is a historical backtest against cached NIFTY 50 candles, following the same validation order as the sibling project: **backtest first, prove out a real edge, only then build paper trading, only then consider real money.**

**Honest current result: 0 trades across 140 real cached trading days.** The strategy's confirmation rule, as specified, requires two conditions on the *same 5-minute candle* that in practice occur on different candles within the same day (see `PROJECT_STATUS.md`'s Current Status for the full explanation). This is not yet a working, tradeable strategy — it's a documented starting point for the next iteration.

## Setup

```
py -m pip install -r requirements.txt
```

No Kite Connect credentials needed yet — the backtester only uses the cached CSVs already committed under `data/historical/`. (Unlike the sibling project's `.gitignore`, these CSVs *are* committed here, since there's no `data_fetch.py`/Kite auth in this project yet to regenerate them - see `PROJECT_STATUS.md`.)

## Usage

**Run the SPFS backtest:**
```
py src/spfs_backtester.py
```
Prints a day-by-day outcome summary and writes `data/backtest_results/spfs_trades.csv`.

**Run the test suite:**
```
py -m pytest tests/ -v
```

**Hand-verify a few real days** (prints per-day setup, Sniper level, and how close each day came to confirming, even on days that didn't trade):
```
py tests/manual_spfs_sanity_check.py
```

## Repo structure

```
Share_Market_Bava_SPFS/
  PROJECT_STATUS.md       # read first
  src/
    options_pricing.py     # Black-Scholes premium simulation + strike/expiry helpers (independent copy)
    trend_bias.py            # minimal EMA20/EMA50 daily trend calc (independent extraction, not an import)
    spfs_signal.py             # pure ATM/Sniper/Square Number logic
    spfs_backtester.py          # day-by-day replay + reporting
  tests/
    test_spfs_signal.py           # unit tests for the pure functions
    test_spfs_backtester.py        # state-machine regression tests (synthetic data)
    manual_spfs_sanity_check.py     # non-automated, human-eyeball check against real cached data
  data/
    historical/               # cached NIFTY 50 daily + 5-minute candles (committed - see note above)
    backtest_results/          # spfs_trades.csv from the last backtester run (gitignored)
```
