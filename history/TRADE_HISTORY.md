# Trade History

**Paper trades — no real orders.** Written automatically by the bot (`src/history.py`) after every entry/exit;
don't edit by hand, change `history/days.csv` / `history/trades.csv` instead. ₹ = points × qty, before brokerage and charges.

**All days: 1 trade(s), +58.75 points, ₹+19,094**

| Date | Market | ATM | Sniper | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|
| 2026-09-29 | SENSEX | no plan | – | 0 | +0.00 | ₹+0 | no plan |
| 2026-09-29 | NIFTY | 22800 | 39.58 | 0 | +0.00 | ₹+0 | watching |
| 2026-09-28 | NIFTY | 23200 | 54.0 | 1 | +58.75 | ₹+19,094 | stopped early |

## 2026-09-29 (Tue)

### NIFTY — watching (last update 2026-09-29 09:27)

- NIFTY close 22780.25 on 2026-09-28, expiry 2026-09-29, qty 325.
- Plan: ATM 22800 after 0 shift(s), Sniper 39.58.
- No trade yet.

### SENSEX — no plan (last update 2026-09-29 09:27)

- SENSEX close 72771.72 on 2026-09-28, expiry 2026-10-01, qty 300.
- No plan: still failing after 3 shifts — no trading that day.

## 2026-09-28 (Mon)

### NIFTY — stopped early (last update 2026-09-29 09:24)

- NIFTY close 23140.5 on 2026-09-25, expiry 2026-09-29, qty 325.
- Plan: ATM 23200 after 1 shift(s), Sniper 54.0.
- Note: Bot stopped after 10:45 (window closed or laptop asleep) - second half not watched. Restarted at 09:23 and 09:49 for rule changes; the entry was found on the 09:49 catch-up.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 325 × NIFTY26SEP23100PE | 09:30 (catch-up) | 197.25 | 196 | 169 → 196 | 256 | 256 (10:40) | TARGET | +58.75 | ₹+19,094 |
