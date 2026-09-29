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
2. starts the **SENSEX** bot in a second window and the **NIFTY** bot in the first.

Keep both windows open and the laptop awake until 15:00.

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
