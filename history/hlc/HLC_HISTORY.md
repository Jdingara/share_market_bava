# HLC Trade History

**Paper trades — no real orders.** Written by the bot (`src/hlc_history.py`). ₹ = points × qty, before charges.

**All days: 29 trade(s), +1185.48 points, ₹+361,569**

| Date | Market | ATM | CE / PE yesterday | Buyer's day | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | SENSEX | 71600 | PROFIT BOOKING / PANIC | yes | 0 | +0.00 | ₹+0 | watching |
| 2026-10-09 | NIFTY | 22250 | PROFIT BOOKING / PANIC | yes | 1 | +0.00 | ₹+0 | watching |
| 2026-10-08 | SENSEX | 72500 | PROFIT BOOKING / PROFIT BOOKING | no | 4 | +215.01 | ₹+64,503 | finished |
| 2026-10-08 | NIFTY | 22600 | PROFIT BOOKING / PANIC | yes | 3 | +136.92 | ₹+44,499 | finished |
| 2026-10-07 | SENSEX | 73000 | PANIC / PROFIT BOOKING | yes | 2 | -77.15 | ₹-23,145 | finished |
| 2026-10-07 | NIFTY | 22750 | PANIC / PROFIT BOOKING | yes | 2 | -35.95 | ₹-11,684 | finished |
| 2026-10-06 | SENSEX | 72300 | PROFIT BOOKING / PROFIT BOOKING | no | 1 | +127.95 | ₹+38,385 | finished |
| 2026-10-06 | NIFTY | 22550 | PROFIT BOOKING / PROFIT BOOKING | no | 2 | +6.30 | ₹+2,048 | finished |
| 2026-10-05 | SENSEX | 72100 | PROFIT BOOKING / PROFIT BOOKING | no | 1 | +212.35 | ₹+63,705 | finished |
| 2026-10-05 | NIFTY | 22450 | PROFIT BOOKING / PROFIT BOOKING | no | 1 | +45.05 | ₹+14,641 | watching |
| 2026-10-01 | SENSEX | 72500 | PROFIT BOOKING / PANIC | yes | 4 | +556.25 | ₹+166,875 | finished |
| 2026-10-01 | NIFTY | 22650 | PROFIT BOOKING / PANIC | yes | 4 | +81.15 | ₹+26,374 | finished |
| 2026-09-30 | SENSEX | 72800 | PANIC / PROFIT BOOKING | yes | 1 | -35.90 | ₹-10,770 | finished |
| 2026-09-30 | NIFTY | 22800 | PANIC / PROFIT BOOKING | yes | 1 | -42.10 | ₹-13,682 | finished |
| 2026-09-29 | SENSEX | 72900 | PROFIT BOOKING / PANIC | yes | 1 | -50.00 | ₹-15,000 | replayed |
| 2026-09-29 | NIFTY | 22800 | PROFIT BOOKING / PANIC | yes | 1 | +45.60 | ₹+14,820 | replayed |

## 2026-10-09 (Fri)

### NIFTY — watching (last update 2026-10-09 09:35)

- Close 22231.8, ATM 22250. R3 22809.0 · R2 22529.5 · R1 22388.4 · S1 22108.9 · S2 21970.5 · S3 21691.0.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| CONFIRM | 325 × 22250 CE | index in Fib 0.75-0.786 zone 22317.27-22320.30, CE Bullish Engulfing | 09:25 | 223 | 198 (25 points) | open | OPEN | – | – |

### SENSEX — watching (last update 2026-10-09 08:40)

- Close 71593.24, ATM 71600. R3 73995.8 · R2 72797.9 · R1 72197.95 · S1 71000.05 · S2 70402.1 · S3 69204.2.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.
- No trade.

## 2026-10-08 (Thu)

### NIFTY — finished (last update 2026-10-08 15:00)

- Close 22603.05, ATM 22600. R3 23148.6 · R2 22874.3 · R1 22732.6 · S1 22458.3 · S2 22325.7 · S3 22051.4.
- CE PROFIT BOOKING, PE PANIC — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| TREND | 325 × 22600 PE | PE retest of its first 15-min close 193.05 | 09:40 | 193.05 | 168.05 (25 points) | 208.95 (09:45) | TARGET S1 22458.3 | +15.90 | ₹+5,168 |
| TREND | 325 × 22600 PE | PE Inverted Hammer, retest 200.2, Fib 0.618 205.41 | 09:55 | 205.41 | 180.41 (25 points) | 209.6 (10:25) | closed back across S1 22458.3 | +4.19 | ₹+1,362 |
| TREND | 325 × 22600 PE | PE Inverted Hammer, retest 208.5, Fib 0.618 217.97 | 10:35 | 217.97 | 192.97 (25 points) | 334.8 (13:35) | trailing SL 334.80 (50 below the high 384.8) | +116.83 | ₹+37,970 |

### SENSEX — finished (last update 2026-10-08 15:00)

- Close 72638.7, ATM 72500. R3 73455.4 · R2 72977.7 · R1 72762.9 · S1 72285.2 · S2 72022.3 · S3 71544.6.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| TREND | 300 × 72500 PE | PE retest of its first 15-min close 307.2 | 09:35 | 307.2 | 257.2 (50 points) | 317.2 (10:00) | closed back across S1 72285.2 | +10.00 | ₹+3,000 |
| TREND | 300 × 72500 PE | PE Inverted Hammer, retest 317.6, Fib 0.618 334.16 | 10:00 | 332.45 | 282.45 (50 points) | 282.45 (10:10) | SL (50 points) | -50.00 | ₹-15,000 |
| TREND | 300 × 72500 PE | PE retest of its first 15-min close 307.2 | 10:10 | 307.2 | 257.2 (50 points) | 344 (10:45) | trailing SL 344.00 (100 below the high 444) | +36.80 | ₹+11,040 |
| TREND | 300 × 72500 PE | PE Bullish Engulfing, retest 335.85, Fib 0.618 350.94 | 11:00 | 350.94 | 300.94 (50 points) | 569.15 (11:30) | trailing SL 569.15 (100 below the high 669.15) | +218.21 | ₹+65,463 |

## 2026-10-07 (Wed)

### NIFTY — finished (last update 2026-10-07 15:00)

- Close 22776.1, ATM 22750. R3 23206.35 · R2 23055.2 · R1 22901.15 · S1 22595.95 · S2 22444.8 · S3 22290.75.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 325 × 22750 CE | index Spinning Top at S1, CE Bullish Engulfing | 09:25 | 97.95 | 72.95 (25 points) | 72.95 (13:10) | SL (25 points) | -25.00 | ₹-8,125 |
| REVERSAL | 325 × 22750 CE | index Bullish Harami at S1, CE Bullish Harami | 14:40 | 85.65 | 60.65 (25 points) | 74.7 (14:55) | 15:00 exit | -10.95 | ₹-3,559 |

### SENSEX — finished (last update 2026-10-07 15:00)

- Close 73067.81, ATM 73000. R3 73988.45 · R2 73663.25 · R1 73325.2 · S1 72661.95 · S2 72336.75 · S3 71998.7.
- CE PANIC, PE PROFIT BOOKING — buyer’s day.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 300 × 73000 CE | index Bullish Engulfing at S1, CE Bullish Engulfing | 10:15 | 201.6 | 151.6 (50 points) | 151.6 (12:55) | SL (50 points) | -50.00 | ₹-15,000 |
| REVERSAL | 300 × 73000 CE | index Doji at S1, CE Doji | 13:35 | 111.05 | 61.05 (50 points) | 83.9 (14:55) | 15:00 exit | -27.15 | ₹-8,145 |

## 2026-10-06 (Tue)

### NIFTY — finished (last update 2026-10-06 15:21)

- Close 22555.75, ATM 22550. R3 22794.55 · R2 22711.95 · R1 22632.6 · S1 22470.65 · S2 22388.05 · S3 22308.7.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| FIB | 325 × 22550 CE | first candle 0.75 at 22611.47 | 09:30 | 99.9 | 0.0 (index below first low 22561.6) | 107 (10:05) | closed back across R1 22632.6 | +7.10 | ₹+2,308 |
| REVERSAL | 325 × 22550 PE | index Spinning Top at R2, PE Bullish Harami | 13:20 | 6.15 | 5.35 (2-candle low) | 5.35 (13:35) | SL (2-candle low) | -0.80 | ₹-260 |

### SENSEX — finished (last update 2026-10-06 15:21)

- Close 72382.47, ATM 72300. R3 73691.7 · R2 73211.85 · R1 72779.85 · S1 71868 · S2 71388.15 · S3 70956.15.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| FIB | 300 × 72300 CE | first candle 0.75 at 72541.87 | 09:30 | 569.1 | 0.0 (index below first low 72384.8) | 697.05 (12:10) | closed back across R1 72779.9 | +127.95 | ₹+38,385 |

## 2026-10-05 (Mon)

### NIFTY — watching (last update 2026-10-05 14:20)

- Close 22421.95, ATM 22450. R3 22835.2 · R2 22702.75 · R1 22582.45 · S1 22329.7 · S2 22197.25 · S3 22076.95.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 325 × 22450 PE | index Hanging Man at R1, PE Inverted Hammer | 09:35 | 41.55 | 16.55 (25 points) | 86.6 (12:00) | TARGET Close 22422 | +45.05 | ₹+14,641 |

### SENSEX — finished (last update 2026-10-05 15:00)

- Close 71909.7, ATM 72100. R3 73775.3 · R2 73221.65 · R1 72653.65 · S1 71532 · S2 70978.35 · S3 70410.35.
- CE PROFIT BOOKING, PE PROFIT BOOKING.

| Kind | Buy | Pattern | Entry | Fill | SL | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|---|---|
| REVERSAL | 300 × 72100 PE | index Bearish Harami at R1, PE Bullish Harami | 09:50 | 259.5 | 209.5 (50 points) | 471.85 (12:00) | TARGET Close 71909.7 | +212.35 | ₹+63,705 |

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
