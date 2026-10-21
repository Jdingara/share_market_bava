# Vengat ORB - Trade History

**Paper trades - no real orders.** Opening range = the index's 09:15-09:20 candle; a close outside it buys the ATM CE / PE (NIFTY 2 lots, SENSEX 6 lots), SL the other end of the range, target 1:2. Written by `src/orb_history.py`.

**All days: 24 trade(s), ₹+42,920**

| Date | Market | Range | Trades | P&L points | P&L ₹ | Status |
|---|---|---|---|---|---|---|
| 2026-10-21 | SENSEX | 74149.89 - 74479.28 | 7 | -32.90 | ₹-3,948 | finished |
| 2026-10-21 | NIFTY | 22976.15 - 23063.6 | 4 | +74.95 | ₹+9,744 | finished |
| 2026-10-20 | SENSEX |  -  | 0 | +0.00 | ₹+0 | finished |
| 2026-10-20 | NIFTY |  -  | 0 | +0.00 | ₹+0 | finished |
| 2026-10-19 | SENSEX | 74513 - 74849.75 | 8 | +265.00 | ₹+31,800 | finished |
| 2026-10-19 | NIFTY | 23074.6 - 23175.25 | 5 | +40.95 | ₹+5,324 | finished |

## 2026-10-21

### NIFTY - range 22976.15 - 23063.6 (finished)

| Buy | Entry | Fill | SL / target (index) | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|
| 130 x 23100 CE | 09:30 | 181.8 | 23065.65 / 23215.65 | 153.35 (09:45) | SL - index reached 23065.7 in candle 09:45 | -28.45 | -3698 |
| 130 x 22950 PE | 10:05 | 155.9 | 23018.1 / 22868.1 | 206.35 (11:30) | TARGET 1:2 - index reached 22868.1 in candle 11:30 | 50.45 | 6558 |
| 130 x 22850 PE | 11:30 | 157.3 | 22912.8 / 22762.8 | 228 (12:10) | TARGET 1:2 - index reached 22762.8 in candle 12:10 | 70.7 | 9191 |
| 130 x 22750 PE | 12:25 | 182.55 | 22787.5 / 22637.5 | 164.8 (15:10) | 15:16 square-off | -17.75 | -2308 |

### SENSEX - range 74149.89 - 74479.28 (finished)

| Buy | Entry | Fill | SL / target (index) | Exit | Reason | Points | ₹ |
|---|---|---|---|---|---|---|---|
| 120 x 74700 CE | 09:30 | 320.9 | 74557.08 / 74857.08 | 244.1 (09:45) | SL - index reached 74557.1 in candle 09:45 | -76.8 | -9216 |
| 120 x 74100 PE | 10:10 | 329.65 | 74242.76 / 73942.76 | 252.25 (10:30) | SL - index reached 74242.8 in candle 10:30 | -77.4 | -9288 |
| 120 x 74100 PE | 11:15 | 346.2 | 74199.17 / 73899.17 | 454.1 (11:30) | TARGET 1:2 - index reached 73899.2 in candle 11:30 | 107.9 | 12948 |
| 120 x 73900 PE | 11:30 | 345.35 | 73974.56 / 73674.56 | 449.65 (12:00) | TARGET 1:2 - index reached 73674.6 in candle 12:00 | 104.3 | 12516 |
| 120 x 73500 PE | 12:25 | 394.6 | 73570.01 / 73270.01 | 334.3 (12:30) | SL - index reached 73570 in candle 12:30 | -60.3 | -7236 |
| 120 x 73600 PE | 12:30 | 386.15 | 73679.3 / 73379.3 | 449.45 (13:40) | TARGET 1:2 - index reached 73379.3 in candle 13:40 | 63.3 | 7596 |
| 120 x 73400 PE | 13:40 | 333.5 | 73497.4 / 73197.4 | 239.6 (15:10) | SL - index reached 73497.4 in candle 15:10 | -93.9 | -11268 |

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
