# HLC Trade History

**Paper trades — no real orders.** Written by the bot (`src/hlc_history.py`). ₹ = points × qty, before charges.

**All days: 2 trade(s), -4.40 points, ₹-180**

| Date | Market | ATM | CE / PE yesterday | Buyer's day | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|---|
| 2026-09-29 | SENSEX | 72900 | PROFIT BOOKING / PANIC | yes | 1 | -50.00 | ₹-15,000 | replayed |
| 2026-09-29 | NIFTY | 22800 | PROFIT BOOKING / PANIC | yes | 1 | +45.60 | ₹+14,820 | replayed |

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
