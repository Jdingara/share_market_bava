# HLC Trade History

**Paper trades — no real orders.** Written by the bot (`src/hlc_history.py`). ₹ = points × qty, before charges.

**All days: 4 trade(s), -54.25 points, ₹-15,131**

| Date | Market | ATM | CE / PE yesterday | Buyer's day | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|---|
| 2026-09-30 | SENSEX | 72800 | PANIC / PROFIT BOOKING | yes | 1 | -50.00 | ₹-15,000 | watching |
| 2026-09-30 | NIFTY | 22800 | PANIC / PROFIT BOOKING | yes | 1 | +0.15 | ₹+49 | watching |
| 2026-09-29 | SENSEX | 72900 | PROFIT BOOKING / PANIC | yes | 1 | -50.00 | ₹-15,000 | replayed |
| 2026-09-29 | NIFTY | 22800 | PROFIT BOOKING / PANIC | yes | 1 | +45.60 | ₹+14,820 | replayed |

## 2026-09-30 (Wed)

### NIFTY — watching (last update 2026-09-30 09:55)

- Close 22716.2, ATM 22800. R3 23263.1 · R2 23107.0 · R1 22956.1 · S1 22649.1 · S2 22493.0 · S3 22342.1.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| GAP | 325 × 22800 PE | gap down open 22665.00 | 09:25 | 162.2 | 137.2 (25 points) | 162.35 (09:50) | closed back across Close 22716.2 | +0.15 | ₹+49 |

### SENSEX — watching (last update 2026-09-30 10:00)

- Close 72529.07, ATM 72800. R3 73812.95 · R2 73486.8 · R1 73126.15 · S1 72439.35 · S2 72113.2 · S3 71752.55.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| GAP | 300 × 72800 PE | gap down open 72441.15 | 09:25 | 338.8 | 288.8 (50 points) | 288.8 (09:55) | SL (50 points) | -50.00 | ₹-15,000 |

## 2026-09-29 (Tue)

### NIFTY — replayed (last update 2026-09-29 15:44)

- Close 22780.25, ATM 22800. R3 23039.85 · R2 22955.65 · R1 22884.2 · S1 22728.55 · S2 22644.35 · S3 22572.9.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.
- Note: Replayed on the day's real candles after the close (the live HLC bot wasn't running).

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| GAP | 325 × 22800 PE | gap down open 22732.45 | 09:25 | 177.1 | 152.1 (25 points) | 222.7 (09:35) | TARGET S3 22572.9 | +45.60 | ₹+14,820 |

### SENSEX — replayed (last update 2026-09-29 15:45)

- Close 72771.72, ATM 72900. R3 74190.5 · R2 73746.3 · R1 73344.2 · S1 72497.9 · S2 72053.7 · S3 71651.6.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.
- Note: Replayed on the day's real candles after the close (the live HLC bot wasn't running).

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| GAP | 300 × 72900 PE | gap down open 72633.68 | 09:25 | 724.5 | 674.5 (50 points) | 674.5 (11:10) | SL (50 points) | -50.00 | ₹-15,000 |
