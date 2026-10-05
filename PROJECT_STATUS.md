# Sniper Strategy Bot — Project Status

**This file is the single source of truth for the project.** If it and any other file (README, code comments, old chats, `Bava Details for bot.docx`, the old `SNIPER_SPEC.md`) disagree, this file is correct and the other one should be fixed to match. Update "Current Status" and "Open Decisions" after every meaningful work session.

## Goal

An automated trading bot for the owner (Sasikumar, Zerodha client UTC038) that runs the owner's **Sniper** options-buying strategy on NIFTY (NSE) and SENSEX (BSE) weekly options: a morning plan from the previous day's closing premiums, then square-number entries, stops and targets through the day. Validation order: backtest → paper trading on live data (current phase) → real orders only after paper results match expectations.

## Core Decisions/Rules

Decided and stable — **do not change without the owner's explicit confirmation.** Dates show when a rule was confirmed. Section numbers (§1–§5) are referenced from code comments.

### Project rules

- **Options buyer only.** R1/R2/R3 and S1/S2/S3 levels are **not** part of this strategy.
- **Broker: Zerodha** via Kite Connect (app "Sniper_Bot", type Connect, client UTC038, redirect `https://127.0.0.1`). Decided 2026-09-27.
- **Paper mode only** until the owner explicitly says to place real orders. The bot logs "WOULD BUY / WOULD EXIT" and never calls an order API.
- **Replaced strategy:** this repo used to hold an unrelated "SPFS" strategy (EMA trend, 70% Sniper, 20-point squares, same-side OTM). On 2026-09-27 the owner replaced it entirely with Sniper and asked that no old concepts be kept. The SPFS code is only in git history (commit `bf1c059` and earlier).
- **Decide vs execute:** the Sniper logic (`sniper_signal.py`, `sniper_engine.py`) only decides; anything that talks to the broker stays outside it, so an execution layer can be swapped in later.
- **Independent of the sibling "share-market-bro" bot** (older XGBoost/rule-based NIFTY bot, its own Kite app/account). No runtime code is shared; anything reused is copied here. Never import from that project's folder.
- **Security:** API key/secret, tokens → `.env` only (gitignored). Never in code, commits or chats. If exposed, regenerate the secret on developers.kite.trade.

### §1 Daily setup (previous trading day's data)

| Step | Rule |
|---|---|
| Index close | Previous trading day close (skip weekends/holidays) |
| Nearest ATM | Nearest 100-multiple strike to the index close |
| OTM strikes | OTM CE = ATM + 100, OTM PE = ATM − 100 (**both NIFTY and SENSEX**, confirmed 2026-09-29) |
| Sniper | `(OTM CE close + OTM PE close) / 2` |
| Gap check | ATM CE close − Sniper ≥ min gap **AND** ATM PE close − Sniper ≥ min gap |
| Min gap | NIFTY **25**, SENSEX **40** (SENSEX 45 → 35 → 40 on 2026-09-29) |
| SENSEX: widen the OTMs | **SENSEX only** (owner, 29-09): ATM stays the **nearest round strike** (no shifts); the OTMs move out one strike at a time (±100, ±200, …, up to ±500) until **both gaps ≥ 40**. 29-09: ATM 72800, ±100 PE gap −22.62, ±200 +20.85, **±300 → Sniper 295.70, gaps +204.70 / +62.15** → plan (the old shift rule gave no plan). |
| NIFTY: move one OTM out (fallback) | **NIFTY** (owner, 01-10): the ATM shifts run first (§5 unchanged); only if they still fail after 3 shifts, keep the nearest ATM and move the OTMs out one strike at a time — **CE up or PE down** — nearest combinations first (+200/−100 and +100/−200, then +300/−100, +200/−200, +100/−300, … up to 500). The first distance where both gaps ≥ 25 wins; if several pass, the one whose smaller gap is biggest. 01-10: close 22620.5, shifts flipped 22600 ↔ 22700 → ATM 22600, **22800 CE / 22500 PE → Sniper 76.03, gaps +88.47 / +38.62** (owner chose this over 22700 CE / 22400 PE, gaps +81.87 / +32.02). |
| Shift | PE fails → ATM +100. CE fails → ATM −100. Recalculate. Max 3 shifts. Both fail → no plan |
| Expiry | Nearest expiry on/after the trading day (expiry day uses the same-day expiry) |

### §2 Entry logic

When one side's ATM premium falls from its yesterday close, watch the **opposite-side OTM**:
- ATM CE falling (market down) → buy **OTM PE** (ATM − 100)
- ATM PE falling (market up) → buy **OTM CE** (ATM + 100)

| Half | Entry window | Trigger level |
|---|---|---|
| First half | 09:30 – 12:00 | Falling ATM's **yesterday close** |
| Second half | **after 12:00** – 15:00 (was 12:30; owner, 29-09) | **Sniper** value |

- **Windows count by candle close time** (2026-09-29): the candle closing **at 09:30** (09:25–09:30) is already in the first half, up to the one closing at 12:00; second half = candles closing **after 12:00** (12:05) to 15:00 (no entry on the 15:00 close; owner moved it from 12:30 on 29-09 — "the second entry only after 12, never before").
- **Signal** (2026-09-29): a 5-minute OTM candle **closes above the trigger** (first half: the falling ATM's yesterday close; second half: Sniper). Above the trigger is enough — no square has to be crossed yet.
- **Entry at the upcoming square number** (2026-09-29), as orders from the next candle:
  - signal close still **below** the plan square n² (e.g. trigger 84.20, close 90, n² = 100) → buy when price **rises to 100**;
  - signal close already **above** a square k² (e.g. 101.90 > 100) → buy at **100 if price comes back**, or at the **next square 121 if it runs up first**;
  - SL/target are measured from the square actually bought (100 → SL 81, target 144; 121 → SL 100, target 169). Unfilled at the window's end → cancelled, no trade.
- **ATM below Sniper = extra confidence** (2026-09-29, owner's concept): when the falling ATM is already below Sniper, ATM sellers are strong, so the opposite OTM sees profit-booking / panic exits — a buying opportunity for us as buyers. **Recorded as a HIGH-confidence tag on the signal/trade, not a required condition**, so results with and without it can be compared in `history/`.
- Worked case, 29-09-2026: 22700 PE, trigger 84.20. The 09:25–09:30 candle closed 101.90 → signal. The next candle's low was 90.45 → **bought at 100**. The 09:35 candle's high was 148.85 → **144 target, +44**.
- Superseded the same week: "the candle must cross the square, then buy at the close" (28-09) and "buy at the next square it crosses" (28-09). The engine keeps the old behaviour behind `fill_at_square=False` for comparison only.

### §3 Square-number levels

- `n = ceil(sqrt(trigger))` → **Entry = n²** (the square at or above the trigger, never below)
- **SL = (n − 1)²**, **Target = (n + 2)²** (or from k when a higher square k² was crossed, §2)
- Example: trigger 89.15 → entry 100 (10²), SL 81, target 144

### §4 Limits and exits

- Max **2 trades/day** (one per half). **Exit everything by 15:00.**
- **A second trade only after the first is stopped out** (owner, 30-09, Sniper and HLC): first trade hits its target → no more trades that day; only a stop-loss exit allows the next trade. Implemented strictly: any other exit (trailing stop, level exit, 15:00) also ends the day, and an open trade blocks new entries.
- **Sideways** (all 4 strikes — ATM CE, ATM PE, OTM CE, OTM PE — below their yesterday close) = no trade. Expiry day: same rules.
- **Trailing SL** (2026-09-28): each time a 5-minute candle **closes above** a square k², SL moves up to (k − 1)². **Only moves up, never down.** Entry 100: close above 121 → SL 100; above 144 → SL 121; above 169 → SL 144.
- **Target stays — book the profit there** (2026-09-28): a trade in profit must not give it back.
- **Quantity per trade** (2026-09-28): **NIFTY 5 lots = 325** (lot 65), **SENSEX 15 lots = 300** (lot 20).

### §5 Worked example (owner's, data 25-09-2026 → trading 28-09-2026)

NIFTY close 23140.5 → nearest ATM 23100.

| ATM | OTM CE | OTM PE | Sniper | ATM CE gap | ATM PE gap | Result |
|---|---|---|---|---|---|---|
| 23100 | 23200 CE 89.15 | 23000 PE 34.25 | 61.70 | 147.40 → +85.70 ✓ | 59.20 → −2.50 ✗ | Shift up |
| **23200** | 23300 CE 48.8 | 23100 PE 59.2 | **54.00** | 89.15 → +35.15 ✓ | 99.80 → +45.80 ✓ | **Final** |

| Half | Scenario | Buy | Trigger | Entry | SL | Target |
|---|---|---|---|---|---|---|
| First | Market down | 23100 PE | ATM CE close 89.15 | 100 | 81 | 144 |
| First | Market up | 23300 CE | ATM PE close 99.80 | 100 | 81 | 144 |
| Second | Market down | 23100 PE | Sniper 54 | 64 | 49 | 100 |
| Second | Market up | 23300 CE | Sniper 54 | 64 | 49 | 100 |

`tests/test_sniper_signal.py` reproduces this exactly.

### HLC strategy (second strategy — built and running live in paper mode; rules still being refined with the owner)

Owner started it on 2026-09-29. NIFTY 50 and SENSEX only. Runs separately from Sniper (own dashboard/history), paper mode first. The owner's own sheet for 29-09 (data 28-09) is the test example.

- **ATM selection:** from the previous day's index close, check the nearby strikes and pick the one where the **CE close and PE close are nearest each other**. Owner's example: close 23080; 23100 has CE 150 / PE 225 (gap 75), 23150 has CE 165 / PE 175 (gap 10) → ATM 23150. On 29-09 SENSEX this picks 72900 (gap 42) over 72800 (gap 142), matching the sheet.
- **Inputs:** that ATM's CE and PE previous-day **High, Low, Close**. The sheet labels the leg that closed near its low **PROFIT BOOKING** (CE: 298.5 → 84.20) and the one that closed near its high **PANIC** (PE: 8.4 → 71.45). How to derive the label exactly, and how it's used, isn't confirmed yet.
- **Levels:** R1 = ATM + CE close; S1 = ATM − PE close; R2 = ATM + (CE + PE); S2 = ATM − (CE + PE); **R3 = R2 + CE close; S3 = S2 − PE close** (confirmed 29-09).
- Sheet check, 29-09: NIFTY ATM 22800, CE 84.20 / PE 71.45 → R1 22884.20, R2 22955.65, R3 23039.85, S1 22728.55, S2 22644.35, S3 22572.90. SENSEX ATM 72900, CE 444.20 / PE 402.10 → R1 73344.20, R2 73746.30, R3 74190.50, S1 72497.90, S2 72053.70, S3 71651.60.
- **Dropped by the owner:** the sheet's "Earth level" (pre-open ± 26.11% of the previous day's range) and the "SIDEWAY" label.
- **ATM search:** as many strikes as needed; normally found within 2–3 strikes of the close.
- **Trading rules (owner, 2026-09-29):**
  - Window 09:30–15:00, **1 or 2 trades a day**, **5-minute candles**.
  - **"Close" level = yesterday's NIFTY (index) close.** Travel: a candle closing below Close → price heads to S1; below S1 → S2 (and so on); likewise upwards to R1, R2, R3. **Target = the next level.**
  - **Entry only after candlestick confirmation, on BOTH the index chart and the option premium chart.** Support patterns: Morning Star, Hammer, Bullish Engulfing, Bullish Harami. At support/resistance also: Doji, Spinning Top, Hanging Man. If the CE side doesn't confirm, the PUT side may; either way the index must confirm too.
  - **Buy the morning ATM strike only** (CE or PE) — even if the balanced strike has moved by 09:30 (owner, 29-09; replaces an earlier "ATM at entry time" reading).
  - **No trade before 09:30** (confirmed 29-09).
  - **FIB trade — the morning trade** (owner, 30-09; **replaced the 09:30 gap trade**): take the **first 5-minute index candle's range**. **Side** = where the last closed candle sits against yesterday's close (above → CE, below → PE); it can change until the entry — 30-09 NIFTY opened below but the 2nd/3rd candles closed above → CE. **Entry from 09:30** when the index retraces to **0.75** of the first candle (reverse Fibonacci; **changed from 0.618 on 30-09 afternoon for a smaller SL**): CE at high − 0.75 × range, PE at low + 0.75 × range. The side keeps following the latest candle close until the entry (owner said "OK" to this reading; fixing the side at 09:30 was the alternative). **SL on the index**: CE = first candle's low, PE = first candle's high. **Targets R1 → R2 (CE) / S1 → S2 (PE), never beyond R2/S2**, level-trailing as before. Morning ATM strike. One FIB trade a day. 30-09 NIFTY: first candle H 22718.45 / L 22659.80. At 0.618 the CE entry 22682.20 was touched at 09:30 (CE @ 130, the live bot's trade that day). At 0.75 the CE level 22674.46 isn't reached (low 22681.15), the 09:30 candle closes below the close → PE side → PE 0.75 level 22703.79 hit at 09:35 → PE @ 176.85, SL above 22718.45 hit at 09:45 (−2.80).
  - **FIB direction fixed (owner, 2026-10-01, from the SENSEX chart):** the **side** still comes from yesterday's close (below → PE, above → CE), but the **Fib is drawn along the first candle's swing**, not by side or colour: low made first then high (up swing, from the 09:15–09:19 one-minute candles) → level = **high − f × range**, reached when the index dips to it; high first → level = **low + f × range**. **f = 0.75** (owner confirmed 01-10 after briefly choosing 0.618). Only candles **from 09:30** count (the 09:25 candle doesn't). SL unchanged (CE first low / PE first high). 01-10 SENSEX: L 72187.62 (09:15) → H 72450.34 (09:16), up swing, below close → PE side, level 72253.3; after 09:30 the low was 72307.86 → **no FIB trade** (the live bot had bought PE @ 322.60 at low + 0.75 × range = 72384.66 → SL −128.95). The owner also marked a **later PE entry (≈10:35–11:05, PE base ~172–250)** as the trade to take — a separate signal, not specified yet (likely the premium-retest trade).
  - **CONFIRM ("double confirmation") trade (owner, 2026-10-01; built):** side from yesterday's close. The index comes back into the first candle's **Fib 0.75–0.786 zone** from outside (PE: previous close above the zone, zone = low + 0.75…0.786 × range; CE: from below, zone = high − 0.75…0.786 × range) **and** the ATM premium of that side shows a bullish pattern (Morning Star, Engulfing, Hammer, …) on the same candle or one candle before/after → buy at the close. **SL = entry − 50 (SENSEX) / − 25 (NIFTY)**, targets **S1 → S2 (PE) / R1 → R2 (CE)**. Counts toward the 2-a-day limit; a second trade still only after a stop-out. Owner's example: 01-10 SENSEX PE Morning Star 10:30–10:40 with the index in the zone at 10:45. The replay fires earlier (10:20, PE Bullish Engulfing at 10:15 → 249.10, SL −50 at 10:30), then 10:35 PE Doji → 200.80.
  - **PANIC-side premium targets (owner, 2026-10-01; built):** a trade on the side whose leg was PANIC yesterday (morning ATM strike) also has **premium targets**: yesterday's high, then the option's earlier daily highs going back, each higher than the last (as far back as the data goes, ~90 days). **Whichever comes first** — index level (S1/R1 …) or premium high — is the target. A premium candle touching the high without closing above → exit; closing above → the next earlier high becomes the target.
  - **Reversal patterns (owner, 2026-10-01: "all reversal patterns"):** bullish = Morning Star, Bullish Engulfing, Piercing Line, Bullish Harami, Hammer, **Inverted Hammer**, Doji, Spinning Top; bearish = Evening Star, Bearish Engulfing, **Dark Cloud Cover**, Bearish Harami, Hanging Man, **Shooting Star**, Doji, Spinning Top (new ones in bold).
  - **Buyer's day = keep trading (owner, 2026-10-01; built for HLC and Sniper):** on a buyer's day (yesterday's ATM CE / PE: one PROFIT BOOKING, one PANIC) there is **no 2-a-day limit and no "only after a stop-out" rule**. HLC **BREAKOUT** re-entry: after a trade booked at a target — premium high → the premium closes above it; index level → the index closes beyond it — buy the same option again, targets the next premium high / index levels up to S3/R3. 01-10 replay: HLC SENSEX 4 trades **+556.25 = +₹1,66,875**, HLC NIFTY 4 trades **+81.15 = +₹26,374**. **Sniper:** after a TARGET, a candle closing above the target → new order at the next square (normal square entry/SL/target). 01-10 replay: Sniper NIFTY 3 trades +₹23,075, Sniper SENSEX 2 trades +₹8,100. Re-entering after stops too was tried for Sniper SENSEX: 11 trades, −₹23,700 → dropped.
  - **Big gap day** (|open − yesterday's close| ≥ **150 NIFTY / 300 SENSEX**; owner said 150–200 / 300–500): trades use the **round strike nearest the market** at entry instead of the morning ATM; **levels unchanged**; and the trade also **exits when the index pattern turns** against it (directional reversal patterns; Doji/Spinning Top don't count) (owner, 29-09).
  - **SL = entry premium − 25 points (NIFTY) / − 50 points (SENSEX)** (owner, 29-09; replaced "previous candle low", which stopped the 29-09 replay's CE trade out one candle after entry).
  - **Target = the next level; if the index breaks it and keeps going, the SL moves to that level** and the next level becomes the target (confirmed 29-09).
  - **Reversal trade at S3:** a CE pattern at S3 → buy CE; exits step up through S2, S1, Close (confirmed 29-09).
  - **Quantity:** NIFTY 325, SENSEX 300; increase later once it proves itself.
- **PANIC / PROFIT BOOKING label** (confirmed 29-09): for each ATM leg (CE, PE), yesterday's **close nearer its low = PROFIT BOOKING**, **close nearer its high = PANIC**. Matches the sheet: NIFTY CE 298.5/77.05/84.20 → PB, PE 94/8.4/71.45 → PANIC; SENSEX CE 800/416.7/444.20 → PB, PE 448/105/402.10 → PANIC.
- **Owner's 29-09 example (checked against Kite data):** open 22732.5 < close 22780.25 → PE side; S1 broken 09:15, S2 09:25; at 09:30 bought ATM PE; S3 (22572.90) touched on the 09:35 candle (day low 22569.7) = target and the day's reversal point.
- **Built 29-09** (`hlc_signal.py`, `hlc_engine.py`, `hlc_live.py --replay`), replay only so far. **29-09 NIFTY replay:** gap-down PE 22800 @ 177.10 at 09:30 → S3 target 222.70 (+45.60); S3 reversal (index Bullish Engulfing + CE Spinning Top) CE 22800 @ 10.00 → S2 broken, SL to S2 → S1 target 33.65 (+23.65). **+69.25 points = +₹22,506** (325 qty).
  - **Owner's reading of the labels — information only, not a rule** (29-09): a trade on the **PROFIT BOOKING** side tends to head back towards that leg's **yesterday high**; the **PANIC** side moves **fast**. A day with one leg PROFIT BOOKING and the other PANIC (like 29-09) is a good day for buyers. To be shown on the HLC morning plan/dashboard; targets stay levels only.
  - **PANIC side takes over** (owner, 29-09 — this is how the label is used): yesterday's ATM PE was PANIC and today the ATM PE trades **above yesterday's PE high** → **no CE trades that day**; a PANIC CE above its high → no PE trades. 29-09: PE high 94 broken at 09:15 (133.90) → the 10:15 CE reversal is blocked; replay = the gap PE only, **+45.60 = +₹14,820**.
  - **Low premium** (entry − 25/50 ≤ 0) (owner, 29-09): **from 13:30** (≈4 hours of trading, so the day low is meaningful) → buy at the close, **SL = the option's day low − 1**. **Before 13:30** (e.g. expiry-day morning) → buy only if the **next candle breaks the confirmation candle's high** (filled there), **SL = below the lowest low of the last 2 candles**; not triggered on the next candle → cancelled. (History: "pattern low" SL sat 0.35 under a 10.00 entry; "day low − 1" at 10:15 was hit at 11:05 just before the rally.)
- **Premium retest trade — an ADDITIONAL HLC trade type (owner, 30-09; being specified, not built).** Owner's SENSEX 30-09 chart: 72800 PE closing below its yesterday close (360.65) → CE side; the 72800 CE retests a low (11:15 low 211.25; the day's low was 196.60 in the morning) and holds; confirmation candle 11:25 (close 256.80) → buy ~255.87, SL 211.12 (below the retest low), target 449.68 = CE's yesterday high (hit at 12:45, high 494.20); index Target 1 = Fib 0.75 R1 → Close = 72977.86. Owner's answers (30-09): the retest candle itself is not the entry; the next candle bullish (or a Doji then a bullish candle) → enter on the following candle (≈ the bullish candle's close); target 1 = the option's day high (the chart used yesterday's high 449.68), with index Fib 0.75/0.786 as another confirmation. **A first build was reverted the same day**: at 11:25 both the CE (256.80 < 326.15) and the PE (312.10 < 360.65) were below their yesterday closes, so "opposite premium below its close" couldn't choose the side and missed the owner's CE entry, while it took unwanted 09:30 PE entries (SENSEX −64.50, NIFTY −57.60 in replay). Open: how the side is chosen when both premiums are below their closes, and whether the trade is looked for all day or only after the FIB trade.
- **Fibonacci — still open (30-09):** (the first-candle entry was first described at 0.75, then settled at **0.618** — built as the FIB trade above)
  - Targets level by level, at most S2 / R2 (confirmed). When one side goes sideways, book at Fibonacci 0.75: **CE: R2 (1) → Close (0); PE: S2 (1) → Close (0)** — 0.75 near R2/S2 (confirmed from the owner's chart: 30-09 NIFTY ≈ 23009 / 22549). How the bot should detect "sideways" is open.
  - The owner's chart also had Fib on the PE premium (yesterday's high 273.59 → low 134.87, 0.75 ≈ 238.9) — meaning not confirmed.
  - Premium rule (unclear): on a sideways day, a premium candle closing above yesterday's high and close → Fib on that candle, entry at 0.618. Agreed to settle these after the close with a marked-up chart.
- **Still unclear (asked 29-09):** whether the 09:30 gap trade needs a candlestick pattern; how close to a level a pattern must form; precise pattern and swing definitions; whether the target is judged on the index or the premium; strike step (NIFTY 50 / SENSEX 100?).

### Sniper implementation conventions (current behaviour where the §1–§4 rules leave room)

Not yet explicitly confirmed by the owner — listed again in Open Decisions.
1. **Fills:** a buy at the square fills at the square, or at the candle's open if it opened beyond it (gap). If one candle touches both the limit square and the next square and its open doesn't show which came first, the **higher** price is assumed. On the fill candle a low at/below the SL counts as stopped out; the target is checked from the next candle.
2. **Orders wait across candles** until filled or the half's window ends (one order per half).
3. **Sideways checked per candle**, not for the whole day (a whole-day check would need future data).
4. **"Falling" ATM** = below its yesterday close on the entry candle.
5. A second-half trade **may open while a first-half trade is still running**.
6. **Stop before target** if one candle's range crosses both. Stop/target fill at their level.
7. **Shift oscillation** (PE fails at one ATM, CE at the next) is followed literally until the 3-shift limit; then NIFTY moves one OTM out (owner, 01-10, see §1) and SENSEX widens the OTMs (§1).
8. **Previous close** = Zerodha's official daily close for each contract.
9. **"Falling ATM"** (below its yesterday close) is the only required ATM condition at the signal; ATM below Sniper only adds the HIGH-confidence tag (§2).

## Non-Obvious Technical Findings

1. **No historical option premiums for expired contracts** on Kite. The backtester therefore uses Black-Scholes **estimates** from NIFTY spot with 20-day realized volatility. Square levels are sensitive to exact premiums, so backtest P&L is directional only.
2. **Kite's daily close ≠ the last 5-minute close.** E.g. 23100 PE on 25-09: last 5-min close 58.80, official daily close 59.20. The owner's 23200 PE figure 99.80 vs Zerodha's 100.10 flips the entry from 100 to 121 (√100.10 > 10).
3. **Kite Connect app type must be "Connect"** (paid). "Personal" is free but has no historical or live market data.
4. **"The user is not enabled for the app"** at login = the app's Zerodha Client ID doesn't match the login ID. The app was first saved with the form's grey placeholder `AB1234`; fixed to UTC038 in the app settings (editable, no need to recreate).
5. **Login flow:** Zerodha passes through `kite.zerodha.com/connect/finish?...sess_id=...` (not usable) before redirecting to `https://127.0.0.1/?...request_token=...`. The final page shows "site can't be reached" — that is expected. A request_token works **once, for a few minutes**. Sessions expire ~06:00 the next day, so login is daily.
6. **Pasting into the cmd login prompt has been unreliable** (window closing, stale tokens). Reliable fallback: the owner pastes the `127.0.0.1/?request_token=...` address into the Claude chat and Claude exchanges it (script in the 2026-09-29 session) — safe because the token is single-use and useless without the API secret.
7. **The bot stops if its cmd window is closed or the laptop sleeps.** On 2026-09-28 the bot stopped after 10:45 (no "Day finished", no trades CSV, second half not watched). Set Windows sleep to Never on trading days.
8. **5-minute option candles are available within the 20 s poll delay**; Kite also returns the still-forming candle, which the bot skips. Historical API limit is 3 requests/second (0.35 s pause built in).
9. **Instrument facts** (checked 2026-09-28/29): NIFTY index token 256265, options on NFO, Tuesday weekly expiry, lot 65. SENSEX index token 265, options on BFO (`SENSEX26O01…` symbols), Thursday weekly expiry, lot 20. Both 100-point strike steps.
10. **SENSEX with ±100 OTM often fails the gap check**: at ~72,800 adjacent strikes differ by only ~50 in premium, so the shift loop oscillates (72900 ↔ 73000) and ends in no plan — happened on 2026-09-29 at both 45 and 35 min gap.
11. **Restarting the live bot mid-day is safe:** it replays today's closed candles in order and marks any entry from that replay as "catch-up" in the log. Python code changes need a restart; `dashboard.html` is re-read on every request, so page edits apply on refresh.
12. **Windows environment:** Python 3.12 and Git were installed with winget on 2026-09-27. `py`/`git` only work in shells opened after the install. PowerShell 5.1 mangles quotes in `python -c "..."` — put scripts in files. `.bat` files need CRLF line endings.
13. **Git push from Claude's shell can't prompt for GitHub login** (`GCM_INTERACTIVE=never`, `GIT_TERMINAL_PROMPT=0`), and cmd windows Claude opens inherit that. The one-time login must happen in a cmd the owner opens (Win+R → cmd). After that, the stored credential lets Claude push.
15. **SENSEX closing prices are only final after 08:30 the next morning** (owner, 29-09). SENSEX bots (Sniper and HLC) wait until 08:31 before building the morning plan; NIFTY doesn't wait.
14. **Refreshing cached CSVs by overwrite can silently truncate history** (happened in the sibling project). Any future fetch script must fetch a range larger than the existing cache.

## Full Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Replace SPFS with the Sniper rules; pure logic + tests; backtest on estimated premiums | ✅ Done 2026-09-27 |
| 1 | Morning plan from real previous-day closes | ✅ Done — `sniper_live.py --plan-only`, dashboard, JSON; matched §5 on real Zerodha data |
| 2 | Paper mode: live 5-min watch, "would buy/exit" alerts, dashboard, ₹ P&L | 🟡 **Running since 2026-09-28** (NIFTY; SENSEX added 2026-09-29). Needs several full days of clean results |
| 3 | Real orders via Zerodha, owner's quantity, daily max-loss stop | ⏳ Not started — needs owner go-ahead, daily max loss, order mode, SEBI algo/static-IP compliance |
| — | Backtest on real option data | ⏳ Blocked on a source of expired-option history |

## Current Status (last updated: 2026-10-05)

**What's built and verified.** The full Sniper rule set (§1–§4) runs in one engine (`sniper_engine.SniperDay`) shared by the backtester and the live paper bot. 56 tests pass, including §5 reproduced exactly, a fake-clock full trading day, and the 28-09 gap-day entry. The live bot logs in to Zerodha, builds the morning plan from real closes, polls real 5-minute option candles, and shows everything on a local dashboard (NIFTY :8050, SENSEX :8051) with ₹ P&L for the configured quantity.

**How the rules got here (2026-09-27/28), in order:**
- The first Sniper backtest let the bot buy any candle already above the square. That bought above its own targets and lost ~5,300 estimated points, so a **cross requirement** was added. The owner confirmed it on 28-09 (a gap-down day), first as "no cross = no trade".
- Minutes later the owner refined it: if the OTM is already above, buy the **next square it crosses**, with SL/target from that square (§2). The bot was restarted at 09:49 to apply it.
- **Trailing SL** was added on the owner's request. The backtest (estimated premiums, 140 days, 63 trades) compared three exit rules: fixed SL + target **+106** pts; trailing + target **+153**; trailing without target **+199**. The owner chose trailing + target ("book the profit, never give it back"), even though no-target scored higher.
- The **big-gap ATM rule** (re-pick ATM from today's open after a 100–150 point gap) was proposed by the owner but **not built**. On 28-09 the open gap was only 75 points (the big fall came after the open), so it would not have changed that day.

**First live paper day, 2026-09-28 (NIFTY).** Plan ATM 23200, Sniper 54 (matches §5 except the 100.10 vs 99.80 close). NIFTY opened 23064.9 and fell ~280 points by 09:40. The 23100 PE jumped 59 → 164 before 09:30. The bot bought **325 × 23100 PE @ 197.25** (09:30 candle crossed 196; SL 169 → trailed to 196). It hit the **256 target at 10:45: +58.75 points = +₹19,094** before charges. That entry was found on the 09:49 restart's catch-up and is marked as such. **The bot then stopped** (window closed or laptop sleep), so the second half wasn't watched and no trades CSV was written. The result is in `data/paper_trades/log_2026-09-28.txt`.

**2026-09-29 (NIFTY expiry day).**
- Login via `start_bot.bat` failed twice. The owner then pasted the redirect URL into chat and Claude completed the login (Finding 6). The laptop was restarted in between.
- NIFTY plan: close 22780.25 → ATM 22800, no shift, Sniper 39.58. First half: 22700 PE above 100 (81/144) or 22900 CE above 81 (64/121). Second half: either side above 49 (36/81). 325 qty.
- **SENSEX support added** (`--market SENSEX`, 300 qty, BFO contracts, own dashboard port). The owner lowered the SENSEX min gap 45 → 35 and kept ±100 strikes. SENSEX still had **no plan** today (gap check oscillated, Finding 10).
- `start_bot.bat` now starts both markets after one login.
- **Permanent day-by-day history added** (`history/`, written by the bot after every entry/exit so a mid-day stop still leaves a record). 28-09 was backfilled from its log. Both bots were restarted at 09:24, before the entry window, to start recording.
- **Pushed to GitHub** (github.com/Jdingara/share_market_bava, `main`, commit `7d2469c`, author Sasikumar). The first push needed a one-time GitHub browser login in a fresh cmd window (Finding 13); later pushes use the stored credential.
- **The NIFTY bot died after its 09:40 entry** (no traceback captured; likely an unhandled Kite/network error on a poll). Data-fetch errors now log and retry at the next candle instead of ending the day.
- **Entry rules reworked with the owner during the session** (see §2): the candle closing at 09:30 counts, the signal is a close above the trigger, and the buy is at the upcoming square (limit back to it, or the next square if it runs). Under the old rules the bot had bought 22700 PE at 139.70 (09:35 candle, crossing 121). Each change was applied by restarting the bot, which replays the day's candles (catch-up). Final: **signal 101.90 on the 09:30 close → bought at 100 → 144 target, +44 points = +₹14,300**.
- **Day's result (paper, before charges):** Sniper NIFTY +29 pts = **+₹9,425** (first half 22700 PE 100→144 +44, second half 64→SL 49 −15); Sniper SENSEX +29 pts = **+₹8,700** (after the 14:00 restart with the new ±OTM rule, catch-up: 72500 PE 576→SL 529 −47 on the fill candle, then 324→400 +76); HLC NIFTY **+₹14,820** and HLC SENSEX **−₹15,000** (replayed after the close and recorded — the live HLC bot was only finished at ~16:00).
- **HLC live bot built** (`hlc_live.py` live mode, `hlc_dashboard.html` on :8052/:8053, `hlc_history.py` → `history/hlc/`). `start_bot.bat` now starts all four bots after one login. Not yet run live — first live day 30-09.
- Data note: Zerodha's 28-09 high for SENSEX 72900 PE is 488; the owner's sheet shows 448 (asked). — see `history/TRADE_HISTORY.md`.

**2026-09-30 (first day with all 4 bots live).** Login again via chat (the cmd paste in the start_bot window still doesn't run from Claude-launched windows). SENSEX plans waited for 08:31 as intended. Owner changes during the day: HLC morning trade → first-candle Fibonacci (0.618, then 0.75 for a smaller SL); a second trade only after the first is stopped out (both strategies); a premium "retest" trade type was attempted and reverted (see HLC section). The live bots ran on the rules at their start (HLC restarted at 12:37 onto the 0.618 FIB). **Results (paper):** Sniper NIFTY −21 pts = −₹6,825; Sniper SENSEX +29 = +₹8,700; HLC NIFTY −42.10 = −₹13,682 (FIB CE @ 130, index below the first low); HLC SENSEX −35.90 = −₹10,770 (FIB CE @ 167.40 at 14:25). **Day −₹22,577.** Bug found and fixed: bots sharing a history file could overwrite each other's rows (HLC SENSEX's final row was lost) — writes are now locked.

**2026-10-01 (SENSEX expiry).** Login via chat again; all 4 bots started at 09:00. Sniper SENSEX: ATM 72500, OTM ±200, Sniper 170.45. Sniper NIFTY first gave no plan (shifts flipped 22600 ↔ 22700). The owner OK'd a NIFTY fallback after failed shifts (keeps §5 the same): first both OTMs ±200 (restart 09:06, Sniper 63.33), then refined by the owner to **move only one OTM out — CE up or PE down, whichever gives 25** (restart 09:17 → ATM 22600, 22800 CE / 22500 PE, Sniper 76.03). HLC FIB trade: both live HLC bots bought PE at 09:30 (SENSEX −128.95, NIFTY −33.30); the owner said the SENSEX entry was wrong → FIB direction rule fixed in code (see HLC section), HLC bots restarted at 11:36, 11:43 and 12:03 onto the new rules (FIB 0.75 + swing direction, CONFIRM trade, PANIC premium targets). **Final day result (paper, before charges, from each bot's last restart with the day's rules — catch-up, not all live):** Sniper NIFTY 3 trades +71 = **+₹23,075**; Sniper SENSEX 2 trades +27 = **+₹8,100**; HLC SENSEX 4 trades +556.25 = **+₹1,66,875**; HLC NIFTY 4 trades +81.15 = **+₹26,374**. **Day +₹2,24,424.** What the bots actually did live under the morning rules: Sniper +₹14,300 / +₹18,000 (one trade each); HLC SENSEX PE −128.95 and HLC NIFTY PE −33.30 at 09:30 before the fixes. 100 tests pass. 96 tests pass.

**2026-10-05 (Monday; 02-10 holiday).** Login via chat at 09:19; all 4 bots started 09:19 (plans from 01-10 closes). Sniper NIFTY: shifts flipped 22400 ↔ 22500 → the new one-OTM fallback gave ATM 22400, **22600 CE / 22300 PE**, Sniper 66.65. Sniper SENSEX: new weekly expiry 08-10, ATM 71900, OTM ±300, Sniper 435.10. HLC NIFTY ATM 22450, HLC SENSEX ATM 72100. Both legs PROFIT BOOKING in both markets → **not a buyer's day** (2-trade limit applies). First full live day of the 01-10 rules. **Two HLC bugs found from the owner's SENSEX chart and fixed (bots restarted 14:18):** (1) on a big-gap day the bought strike (72600 PE) stopped being fetched once the index moved, so the Close target at 12:00 was never seen — the live bot now fetches every strike the index has been near today; (2) a REVERSAL at R1 with the index just above R1 took R1 as its own target (NIFTY exited +1.55) — reversal targets now start beyond the pattern's level. After the fix: HLC NIFTY PE 41.55 → Close 86.60 (+45.05 = ₹14,641); HLC SENSEX PE 72600 442.75 → 513.95 at 10:05 on the big-gap "pattern turned" exit (+71.20 = ₹21,360). Owner's own trade: 72200 PE ≈330 at 09:55, SL 270, held to Close (high ≈617).

## Open Decisions
- **HLC big-gap day:** keep the "exit when the index pattern turns" rule (05-10 SENSEX exited at 513.95 while the owner held to Close ≈ 600)? And which strike — nearest the market (72600) or the owner's 72200?
- **CONFIRM trade filter:** on 01-10 it fired at 10:20 (−50) before the owner's Morning Star entry — Morning Star only, or another filter?
- **New re-entry rules** (HLC BREAKOUT, Sniper buyer's-day continuation) have no dedicated unit tests yet — checked only by the 01-10 replay.

- **Big-gap ATM rule:** threshold 100 or 150 points? (Proposed 28-09, not built.)
- **Previous close source:** Zerodha official close (bot's current choice) or the owner's figure (e.g. 99.80 vs 100.10)?
- **Daily max loss** at which the bot stops for the day (needed before real orders).
- **Second-half last entry time:** 15:00 per rules, or 14:30?
- **ATM reversal trade** (Morning Star / Bullish Engulfing / Bullish Harami on the ATM chart): dropped completely?
- **Order mode for Phase 3:** fully automatic, or alert + manual confirm?
- **Where the bot runs** (laptop vs cloud VPS) and SEBI algo/static-IP compliance with Zerodha.
- **Implementation conventions 1–9** above: confirm, especially #1 (worse price when a candle touches both squares).
- **HIGH-confidence tag as a filter?** After enough days in `history/`, compare HIGH vs normal trades and decide whether to trade only HIGH ones.
- **Excel morning plan:** the old spec mentioned `sniper_phase1.py` (plan → Excel), not in this repo — still wanted?
- **Real option data** for a meaningful backtest (Kite has none for expired contracts).

## Repo Structure

```
PROJECT_STATUS.md        # this file - single source of truth (rules, findings, roadmap, status)
CLAUDE.md, AGENTS.md     # pointers for AI tools to this file (keep word-for-word in sync)
README.md                # how to install and run
SNIPER_SPEC.md           # stub pointing here (the rules moved into Core Decisions on 2026-09-29)
start_bot.bat            # daily login, then 4 paper bots: Sniper NIFTY/SENSEX (:8050/:8051), HLC NIFTY/SENSEX (:8052/:8053)
.env.example             # credentials template -> copy to .env (gitignored)
requirements.txt
Bava Details for bot.docx  # an earlier write-up of the strategy - superseded by this file
src/
  sniper_signal.py       # pure rules: ATM/OTM/Sniper, gap check + shifts, squares, windows, sideways; NIFTY/SENSEX configs
  sniper_engine.py       # candle-by-candle entries/exits, trailing SL - shared by backtest and live
  sniper_live.py         # live paper bot on Zerodha data (--market, --plan-only, --replay)
  kite_auth.py           # daily Kite Connect login
  dashboard.py/.html     # local dashboard (NIFTY :8050, SENSEX :8051)
  history.py             # writes history/ (per-day plan, trades, P&L)
  hlc_signal.py          # HLC: ATM choice, levels, labels, candlestick patterns
  hlc_engine.py          # HLC: gap/reversal trades, level targets and trailing, SL rules, PANIC block
  hlc_live.py            # HLC paper bot (live and --replay), dashboard state
  hlc_history.py         # writes history/hlc/
  hlc_dashboard.html     # HLC dashboard page
  sniper_backtester.py   # backtest on cached NIFTY candles with estimated premiums
  options_pricing.py     # Black-Scholes estimates, expiry helpers
tests/                   # 58 tests: rules (§5), engine/backtest, live bot (fake Kite + fake clock)
history/                 # permanent record, committed: days.csv, trades.csv, TRADE_HISTORY.md (all days, newest first)
  hlc/                   # HLC's own record: days.csv, trades.csv, HLC_HISTORY.md
data/
  historical/            # cached NIFTY daily + 5-minute candles (committed)
  backtest_results/      # backtest output (gitignored)
  paper_trades/          # raw per-day plans, logs, trades (gitignored - history/ is the permanent record)
.cache/                  # today's Kite session token (gitignored)
```
