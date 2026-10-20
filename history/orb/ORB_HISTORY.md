# Vengat ORB - Trade History

**Paper trades - no real orders.** Opening range = the index's 09:15-09:20 candle; a close outside it buys the ATM CE / PE (NIFTY 2 lots, SENSEX 6 lots), SL the other end of the range, target 1:2. Written by `src/orb_history.py`.

**All days: 13 trade(s), ₹+37,124**

| Date | Market | Range | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|
| 2026-10-20 | SENSEX |  -  | 0 | +0.00 | ₹+0 | finished |
| 2026-10-20 | NIFTY |  -  | 0 | +0.00 | ₹+0 | finished |
| 2026-10-19 | SENSEX | 74513 - 74849.75 | 8 | +265.00 | ₹+31,800 | finished |
| 2026-10-19 | NIFTY | 23074.6 - 23175.25 | 5 | +40.95 | ₹+5,324 | finished |

## 2026-10-20

### NIFTY - range  -  (finished)
- No trade.

### SENSEX - range  -  (finished)
- No trade.

## 2026-10-19

### NIFTY - range 23074.6 - 23175.25 (finished)

| Buy | Entry | Fill | SL / target (index) | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|
| 130 x 23050 PE | 09:55 | 86.5 | 23090.9 / 22940.9 | 65.45 (10:00) | SL - index reached 23090.9 in candle 10:00 | -21.05 | -2736 |
| 130 x 23050 PE | 10:00 | 65.45 | 23119.05 / 22969.05 | 49.9 (10:30) | SL - index reached 23119 in candle 10:30 | -15.55 | -2022 |
| 130 x 23050 PE | 10:35 | 66.15 | 23101 / 22951.0 | 130.4 (12:00) | TARGET 1:2 - index reached 22951 in candle 12:00 | 64.25 | 8352 |
| 130 x 22950 PE | 12:25 | 63.85 | 22995.8 / 22845.8 | 96.15 (13:45) | TARGET 1:2 - index reached 22845.8 in candle 13:45 | 32.3 | 4199 |
| 130 x 22850 PE | 13:45 | 32.65 | 22924.3 / 22774.3 | 13.65 (15:10) | 15:16 square-off | -19.0 | -2470 |

### SENSEX - range 74513 - 74849.75 (finished)

| Buy | Entry | Fill | SL / target (index) | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|
| 120 x 74400 PE | 09:55 | 462.35 | 74517.48 / 74217.48 | 416.3 (10:00) | SL - index reached 74517.5 in candle 10:00 | -46.05 | -5526 |
| 120 x 74500 PE | 10:00 | 468.4 | 74564.83 / 74264.83 | 438.9 (10:30) | SL - index reached 74564.8 in candle 10:30 | -29.5 | -3540 |
| 120 x 74500 PE | 10:30 | 438.9 | 74577.76 / 74277.76 | 627.7 (11:35) | TARGET 1:2 - index reached 74277.8 in candle 11:35 | 188.8 | 22656 |
| 120 x 74200 PE | 11:35 | 448.5 | 74291.99 / 73991.99 | 540.5 (12:15) | TARGET 1:2 - index reached 73992 in candle 12:15 | 92.0 | 11040 |
| 120 x 74000 PE | 12:25 | 416.75 | 74120.89 / 73820.89 | 520.8 (13:20) | TARGET 1:2 - index reached 73820.9 in candle 13:20 | 104.05 | 12486 |
| 120 x 73800 PE | 13:20 | 412.45 | 73895.63 / 73595.63 | 399.05 (13:40) | SL - index reached 73895.6 in candle 13:40 | -13.4 | -1608 |
| 120 x 73800 PE | 13:40 | 399.05 | 73866.13 / 73566.13 | 384.1 (14:05) | SL - index reached 73866.1 in candle 14:05 | -14.95 | -1794 |
| 120 x 73800 PE | 14:05 | 384.1 | 73917.13 / 73617.13 | 368.15 (15:10) | 15:16 square-off | -15.95 | -1914 |
