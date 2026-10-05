# Trade History

**Paper trades — no real orders.** Written automatically by the bot (`src/history.py`) after every entry/exit;
don't edit by hand, change `history/days.csv` / `history/trades.csv` instead. ₹ = points × qty, before brokerage and charges.

**All days: 16 trade(s), +186.75 points, ₹+58,569**

| Date | Market | ATM | Sniper | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|
| 2026-10-05 | SENSEX | 71900 | 435.1 | 1 | +0.00 | ₹+0 | finished |
| 2026-10-05 | NIFTY | 22400 | 66.65 | 2 | -36.00 | ₹-11,700 | finished |
| 2026-10-01 | SENSEX | 72500 | 170.45 | 2 | +27.00 | ₹+8,100 | finished |
| 2026-10-01 | NIFTY | 22600 | 76.03 | 3 | +71.00 | ₹+23,075 | finished |
| 2026-09-30 | SENSEX | 72500 | 173.72 | 2 | +29.00 | ₹+8,700 | finished |
| 2026-09-30 | NIFTY | 22800 | 109.75 | 1 | -21.00 | ₹-6,825 | finished |
| 2026-09-29 | SENSEX | 72800 | 295.7 | 2 | +29.00 | ₹+8,700 | finished |
| 2026-09-29 | NIFTY | 22800 | 39.58 | 2 | +29.00 | ₹+9,425 | finished |
| 2026-09-28 | NIFTY | 23200 | 54.0 | 1 | +58.75 | ₹+19,094 | stopped early |

## 2026-10-05 (Mon)

### NIFTY — finished (last update 2026-10-05 15:00)

- NIFTY close 22421.95 on 2026-10-01, expiry 2026-10-06, qty 325.
- Plan: ATM 22400 after 5 shift(s), Sniper 66.65.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 325 × NIFTY26O0622600CE | 09:35 ★ HIGH | 100.0 | 100 | 81 | 144 | 81 (10:00) | STOPLOSS | -19.00 | ₹-6,175 |
| second | 325 × NIFTY26O0622600CE | 13:45 ★ HIGH | 81.0 | 81 | 64 | 121 | 64 (14:00) | STOPLOSS | -17.00 | ₹-5,525 |

### SENSEX — finished (last update 2026-10-05 15:00)

- SENSEX close 71909.7 on 2026-10-01, expiry 2026-10-08, qty 300.
- Plan: ATM 71900 after 2 shift(s), Sniper 435.1.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 300 × SENSEX26O0872200CE | 09:30 ★ HIGH | 676.0 | 676 | 625 → 676 | 784 | 676 (09:55) | TRAIL_STOP | +0.00 | ₹+0 |

## 2026-10-01 (Thu)

### NIFTY — finished (last update 2026-10-01 15:00)

- NIFTY close 22620.45 on 2026-09-30, expiry 2026-10-06, qty 325.
- Plan: ATM 22600 after 5 shift(s), Sniper 76.03.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| second | 325 × NIFTY26O0622500PE | 12:05 (catch-up) | 100.0 | 100 | 81 → 100 | 144 | 144 (12:40) | TARGET | +44.00 | ₹+14,300 |
| second | 325 × NIFTY26O0622500PE | 12:45 (catch-up) | 169.0 | 169 | 144 → 169 | 225 | 225 (12:50) | TARGET | +56.00 | ₹+18,200 |
| second | 325 × NIFTY26O0622500PE | 13:00 (catch-up) | 225.0 | 225 | 196 | 289 | 196 (13:00) | STOPLOSS | -29.00 | ₹-9,425 |

### SENSEX — finished (last update 2026-10-01 15:00)

- SENSEX close 72480.29 on 2026-09-30, expiry 2026-10-01, qty 300.
- Plan: ATM 72500 after 1 shift(s), Sniper 170.45.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| second | 300 × SENSEX26O0172300PE | 12:10 (catch-up) ★ HIGH | 196.0 | 196 | 169 → 196 | 256 | 256 (12:20) | TARGET | +60.00 | ₹+18,000 |
| second | 300 × SENSEX26O0172300PE | 12:25 (catch-up) | 289.0 | 289 | 256 | 361 | 256 (12:25) | STOPLOSS | -33.00 | ₹-9,900 |

## 2026-09-30 (Wed)

### NIFTY — finished (last update 2026-09-30 15:00)

- NIFTY close 22716.2 on 2026-09-29, expiry 2026-10-06, qty 325.
- Plan: ATM 22800 after 1 shift(s), Sniper 109.75.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| second | 325 × NIFTY26O0622700PE | 12:15 | 121.0 | 121 | 100 | 169 | 100 (12:20) | STOPLOSS | -21.00 | ₹-6,825 |

### SENSEX — finished (last update 2026-09-30 15:00)

- SENSEX close 72529.07 on 2026-09-29, expiry 2026-10-01, qty 300.
- Plan: ATM 72500 after 4 shift(s), Sniper 173.72.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 300 × SENSEX26O0173000CE | 10:20 ★ HIGH | 256.0 | 256 | 225 | 324 | 225 (10:30) | STOPLOSS | -31.00 | ₹-9,300 |
| second | 300 × SENSEX26O0173000CE | 12:10 ★ HIGH | 196.0 | 196 | 169 | 256 | 256 (12:20) | TARGET | +60.00 | ₹+18,000 |

## 2026-09-29 (Tue)

### NIFTY — finished (last update 2026-09-29 15:00)

- NIFTY close 22780.25 on 2026-09-28, expiry 2026-09-29, qty 325.
- Plan: ATM 22800 after 0 shift(s), Sniper 39.58.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 325 × NIFTY26SEP22700PE | 09:30 (catch-up) ★ HIGH | 100.0 | 100 | 81 | 144 | 144 (09:35) | TARGET | +44.00 | ₹+14,300 |
| second | 325 × NIFTY26SEP22700PE | 12:30 ★ HIGH | 64.0 | 64 | 49 | 100 | 49 (12:40) | STOPLOSS | -15.00 | ₹-4,875 |

### SENSEX — finished (last update 2026-09-29 15:00)

- SENSEX close 72771.72 on 2026-09-28, expiry 2026-10-01, qty 300.
- Plan: ATM 72800 after 2 shift(s), Sniper 295.7.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 300 × SENSEX26O0172500PE | 09:40 (catch-up) ★ HIGH | 576.0 | 576 | 529 | 676 | 529 (09:40) | STOPLOSS | -47.00 | ₹-14,100 |
| second | 300 × SENSEX26O0172500PE | 12:20 (catch-up) | 324.0 | 324 | 289 → 324 | 400 | 400 (12:30) | TARGET | +76.00 | ₹+22,800 |

## 2026-09-28 (Mon)

### NIFTY — stopped early (last update 2026-09-29 09:24)

- NIFTY close 23140.5 on 2026-09-25, expiry 2026-09-29, qty 325.
- Plan: ATM 23200 after 1 shift(s), Sniper 54.0.
- Note: Bot stopped after 10:45 (window closed or laptop asleep) - second half not watched. Restarted at 09:23 and 09:49 for rule changes; the entry was found on the 09:49 catch-up.

| Half | Buy | Entry | Fill | Square | SL → trailed | Target | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|---|
| first | 325 × NIFTY26SEP23100PE | 09:30 (catch-up) | 197.25 | 196 | 169 → 196 | 256 | 256 (10:40) | TARGET | +58.75 | ₹+19,094 |
