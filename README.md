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

## Automatic daily start (set up 2026-10-08)

Two Windows scheduled tasks (Mon–Fri) do the daily routine:
- **SniperBot Daily Start, 08:40** → `daily_start.ps1`: `git pull`, opens the Zerodha login page — **you log in (password + TOTP); no copy-paste** — `src\auto_login.py` catches the redirect and saves the session, then the 4 bots start hidden in the background and the dashboard opens. Log: `data\paper_trades\daily_start_<date>.txt`.
- **SniperBot Daily Push, 15:10** → `daily_push.ps1`: commits `history\` and pushes it to GitHub. Log: `data\paper_trades\daily_push_<date>.txt`.

One-time: on developers.kite.trade set the app's **Redirect URL to `http://127.0.0.1:5000/callback`**. The PC must be on (lid open, plugged in) at 08:40; if you don't log in within 30 minutes, the bots don't start that day. Zerodha requires the daily login to be manual, so it can't be automated further. Manage the tasks in Task Scheduler (or `schtasks /Query /TN "SniperBot Daily Start"`).

## Run the paper bot by hand (every trading day, before 09:15)

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

Some days have **no Sniper plan** (the gap check fails even at the relaxed gap) — that's intended: the bot only trades the owner's setups. The window says "NO PLAN TODAY" and keeps the dashboard open.

### `sniper_live.py` options

| Flag | Meaning |
|---|---|
| `--market NIFTY` / `--market SENSEX` | Which index (default NIFTY) |
| `--plan-only` | Show today's morning plan, don't watch the market |
| `--replay YYYY-MM-DD` | Re-run a recent day on its real candles (contracts must still be listed; once a day's weekly expiry has passed the replay uses the current expiry's contracts, so old SENSEX replays aren't reliable) |
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
