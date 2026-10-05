# Share Market Bava — Sniper Bot

> **Read [PROJECT_STATUS.md](PROJECT_STATUS.md) first** — the strategy rules, decisions, current status and known gotchas all live there. This README only covers how to install and run things.

The bot is in **paper mode**: it uses real Zerodha market data but only reports what it *would* buy and sell. It never places orders.

## Install

1. Python 3.12+ and Git (on Windows: `winget install Python.Python.3.12` and `winget install Git.Git`, then open a new terminal).
2. From the repo folder:
   ```
   py -m pip install -r requirements.txt
   ```
3. Zerodha **Kite Connect** app (developers.kite.trade): type **Connect**, redirect URL `https://127.0.0.1`, Zerodha Client ID = your Kite login ID.
4. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` and `KITE_API_SECRET`. Optional: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for phone alerts.

## Run the paper bot (every trading day, before 09:15)

Double-click **`start_bot.bat`**. It:
1. opens Zerodha login — log in, then copy the address the browser lands on (`https://127.0.0.1/?...request_token=...`; the page itself shows an error, that's normal) and paste it into the window;
2. starts four bots in their own windows: **Sniper NIFTY, Sniper SENSEX, HLC NIFTY, HLC SENSEX**.

Keep all the windows open and the laptop awake until 15:00.

Or step by step in cmd:
```
py src\kite_auth.py
py src\sniper_live.py --market NIFTY
py src\sniper_live.py --market SENSEX      (in a second window)
```

### `sniper_live.py` options

| Flag | Meaning |
|---|---|
| `--market NIFTY` / `--market SENSEX` | Which index (default NIFTY) |
| `--plan-only` | Show today's morning plan, don't watch the market |
| `--replay YYYY-MM-DD` | Re-run a recent day on its real candles (contracts must still be listed — about the current and previous expiry week) |
| `--speed N` | Replay speed, seconds per candle (default 0.5) |
| `--no-browser` | Don't open the dashboard automatically |

### Dashboard

- NIFTY: http://127.0.0.1:8050
- SENSEX: http://127.0.0.1:8051

It shows the morning plan, the 4 possible trades, premium charts with entry/SL/target lines, paper trades with ₹ P&L, and the log. It refreshes every 3 seconds and is reachable from this PC only.

### History (all days)

`history\TRADE_HISTORY.md` — every trading day, newest first: the plan, each paper trade, and P&L in points and ₹, with a running total. Updated by the bot after every buy/exit. The same data is in `history\days.csv` and `history\trades.csv` (open in Excel).

### Raw output

`data\paper_trades\`: `plan_<date>.json`, `log_<date>.txt`, `trades_<date>.csv` (SENSEX files are prefixed `SENSEX_`, replays `replay_`).

## REAL MONEY (from ~25 Oct 2026 - read this first)

`start_live.bat` runs the same 4 bots with **real Zerodha orders**. Rules (owner, 2026-10-05) are in PROJECT_STATUS.md, "Real-money rules".

1. Add `LIVE_TRADING=YES` to `.env` (without it `--real` refuses to start).
2. Put the day's money in the Zerodha account before 09:20. At 09:20 the bots split it (Sniper SENSEX → Sniper NIFTY → HLC SENSEX → HLC NIFTY; 4, 3, 2 or 1 equal parts) and buy as many lots as each share allows (max NIFTY 5 lots / SENSEX 15 lots). Not enough for 1 lot → that bot says so and doesn't trade.
3. Double-click **`start_live.bat`** before 09:15 and log in as usual.
4. **Emergency stop:** double-click **`stop_all.bat`** - every bot sells what it holds and stops for the day. The same happens automatically when all bots together have lost 50% of the morning money.

Every order is intraday (MIS), and the stop-loss sits at Zerodha as an SL order, so a position stays protected if the laptop sleeps. Real trades are recorded in `history\live\trades.csv` and sent to Telegram if configured. One bot by hand: `py src\sniper_live.py --market NIFTY --real` (same for `hlc_live.py`).

## HLC bot

Second strategy (rules in PROJECT_STATUS.md, "HLC strategy"). `start_bot.bat` starts it with Sniper. Manually:
```
py src\hlc_live.py --market NIFTY
py src\hlc_live.py --market SENSEX
```
Dashboard: NIFTY http://127.0.0.1:8052, SENSEX http://127.0.0.1:8053. History: `history\hlc\HLC_HISTORY.md`.

Replay a recent day on its real candles: `py src\hlc_live.py --replay 2026-09-29 --market NIFTY` — add `--dashboard` to view it on the dashboard, `--record` to save it to history.

## Backtest

```
py src\sniper_backtester.py
```
Uses the cached NIFTY candles in `data\historical\` with **estimated** option premiums. Writes `data\backtest_results\sniper_days.csv` and `sniper_trades.csv`.

## Tests

```
py -m pytest tests/ -v
```
No network or credentials needed (the live-bot tests use a fake Kite client and a fake clock).
