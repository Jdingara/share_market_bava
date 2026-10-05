# HLC Trade History

**Paper trades — no real orders.** Written by the bot (`src/hlc_history.py`). ₹ = points × qty, before charges.

**All days: 14 trade(s), +671.25 points, ₹+204,618**

| Date | Market | ATM | CE / PE yesterday | Buyer's day | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | SENSEX | 72100 | PROFIT BOOKING / PROFIT BOOKING | no | 1 | +71.20 | ₹+21,360 | watching |
| 2026-10-05 | NIFTY | 22450 | PROFIT BOOKING / PROFIT BOOKING | no | 1 | +45.05 | ₹+14,641 | watching |
| 2026-10-01 | SENSEX | 72500 | PROFIT BOOKING / PANIC | yes | 4 | +556.25 | ₹+166,875 | finished |
| 2026-10-01 | NIFTY | 22650 | PROFIT BOOKING / PANIC | yes | 4 | +81.15 | ₹+26,374 | finished |
| 2026-09-30 | SENSEX | 72800 | PANIC / PROFIT BOOKING | yes | 1 | -35.90 | ₹-10,770 | finished |
| 2026-09-30 | NIFTY | 22800 | PANIC / PROFIT BOOKING | yes | 1 | -42.10 | ₹-13,682 | finished |
| 2026-09-29 | SENSEX | 72900 | PROFIT BOOKING / PANIC | yes | 1 | -50.00 | ₹-15,000 | replayed |
| 2026-09-29 | NIFTY | 22800 | PROFIT BOOKING / PANIC | yes | 1 | +45.60 | ₹+14,820 | replayed |

## 2026-10-05 (Mon)

### NIFTY — watching (last update 2026-10-05 14:20)

- Close 22421.95, ATM 22450. R3 22835.2 · R2 22702.75 · R1 22582.45 · S1 22329.7 · S2 22197.25 · S3 22076.95.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 325 × 22450 PE | index Hanging Man at R1, PE Inverted Hammer | 09:35 | 41.55 | 16.55 (25 points) | 86.6 (12:00) | TARGET Close 22422 | +45.05 | ₹+14,641 |

### SENSEX — watching (last update 2026-10-05 14:20)

- Close 71909.7, ATM 72100 — BIG GAP day. R3 73775.3 · R2 73221.65 · R1 72653.65 · S1 71532 · S2 70978.35 · S3 70410.35.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 300 × 72600 PE | index Bearish Harami at R1, PE Bullish Harami | 09:50 | 442.75 | 392.75 (50 points) | 513.95 (10:05) | pattern turned: index Bullish Harami | +71.20 | ₹+21,360 |

## 2026-10-01 (Thu)

### NIFTY — finished (last update 2026-10-01 15:00)

- Close 22620.45, ATM 22650. R3 23062.0 · R2 22924.75 · R1 22787.25 · S1 22512.5 · S2 22375.25 · S3 22237.75.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| FIB | 325 × 22650 PE | first candle 0.75 at 22539.12 | 09:30 | 176 | 0.0 (index above first high 22590) | 142.7 (10:00) | SL (index above first high 22590) | -33.30 | ₹-10,822 |
| CONFIRM | 325 × 22650 PE | index in Fib 0.75-0.786 zone 22573.08-22575.52, PE Doji | 10:10 | 155.45 | 130.45 (25 points) | 189.1 (12:10) | TARGET premium high 193.15 | +33.65 | ₹+10,936 |
| BREAKOUT | 325 × 22650 PE | PE closed above the high 193.15 | 12:15 | 202.85 | 177.85 (25 points) | 308.65 (12:45) | TARGET S2 22375.2 | +105.80 | ₹+34,385 |
| BREAKOUT | 325 × 22650 PE | index closed beyond S2 22375.2 | 12:50 | 326.65 | 301.65 (25 points) | 301.65 (13:00) | SL (25 points) | -25.00 | ₹-8,125 |

### SENSEX — finished (last update 2026-10-01 15:00)

- Close 72480.29, ATM 72500. R3 73244.1 · R2 73011.55 · R1 72732.55 · S1 72221 · S2 71988.45 · S3 71709.45.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| CONFIRM | 300 × 72500 PE | index in Fib 0.75-0.786 zone 72384.66-72394.12, PE Bullish Engulfing | 10:20 | 249.1 | 199.1 (50 points) | 199.1 (10:30) | SL (50 points) | -50.00 | ₹-15,000 |
| CONFIRM | 300 × 72500 PE | index in Fib 0.75-0.786 zone 72384.66-72394.12, PE Doji | 10:35 | 200.8 | 150.8 (50 points) | 337.25 (12:10) | TARGET premium high 358 | +136.45 | ₹+40,935 |
| FIB | 300 × 72500 PE | first candle 0.75 at 72253.30 | 12:10 | 337.25 | 0.0 (index above first high 72450.3) | 573.25 (12:40) | TARGET S2 71988.4 | +236.00 | ₹+70,800 |
| BREAKOUT | 300 × 72500 PE | index closed beyond S2 71988.4 | 12:40 | 573.25 | 523.25 (50 points) | 807.05 (12:50) | TARGET S3 71709.4 | +233.80 | ₹+70,140 |

## 2026-09-30 (Wed)

### NIFTY — finished (last update 2026-09-30 15:00)

- Close 22716.2, ATM 22800. R3 23263.1 · R2 23107.0 · R1 22956.1 · S1 22649.1 · S2 22493.0 · S3 22342.1.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| FIB | 325 × 22800 CE | first candle 0.618 at 22682.20 | 09:30 | 130 | 0.0 (index below first low 22659.8) | 87.9 (14:25) | SL (index below first low 22659.8) | -42.10 | ₹-13,682 |

### SENSEX — finished (last update 2026-09-30 14:40)

- Close 72529.07, ATM 72800. R3 73812.95 · R2 73486.8 · R1 73126.15 · S1 72439.35 · S2 72113.2 · S3 71752.55.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.
- Note: Final row lost to a simultaneous write by the NIFTY bot; status restored after the close (trade and P&L were already final).

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| FIB | 300 × 72800 CE | first candle 0.618 at 72514.68 | 14:25 | 167.4 | 0.0 (index below first low 72440.1) | 131.5 (14:35) | SL (index below first low 72440.1) | -35.90 | ₹-10,770 |

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
