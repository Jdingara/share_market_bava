# SPFS Options Strategy — Project Status

This file is the single source of truth for this project's goal, decisions, and current progress. Any AI assistant (Claude, Codex, or otherwise) or human picking this up should read this file first before making changes. Keep it updated as the project progresses — update the "Current Status" and "Open Decisions" sections whenever a phase completes or a new decision is made.

## Relationship to the sibling project

This is a **separate, independent project** from the older "share-market-bro" NIFTY options bot (rule-based + XGBoost signal, currently running live on its own Kite Connect API app and Zerodha account). That project continues unchanged. This one exists because the user wants to try a genuinely different strategy ("SPFS") without risking or entangling the working system — separate codebase, and eventually a separate Kite Connect API app and separate Zerodha account once this moves past backtesting.

**No runtime code is shared between the two repos.** Building blocks this project needs (Black-Scholes pricing, strike/expiry math, EMA trend calculation) are kept as independent copies here (`src/options_pricing.py`, `src/trend_bias.py`), not imports reaching into the other project's folder — so this project keeps working even if the sibling project's folder is moved, renamed, or deleted.

## Goal

Build and validate the SPFS options trading strategy for NIFTY 50 weekly options, following the same disciplined validation order as the sibling project: **backtest first (measure a real historical edge) → paper trading (simulated orders, real live data) → live trading (real money) — never skip ahead.**

## The SPFS Strategy Rules (as currently specified — do not change without explicit user confirmation)

Reconciled 2026-07-26/27 from two of the user's strategy write-ups that directly contradicted each other on the most important point (one had the ATM strike migrating dynamically with price; the other locked it for the whole day). The user chose the locked-ATM version. Reconciled via several rounds of clarifying questions rather than guessing:

1. **Daily ATM lock**: `atm_strike = nearest_strike(today's actual opening spot)`, computed once and never re-picked for the rest of the day. This single computation already handles the "huge gap" exception for free — `nearest_strike`'s 50-point quantization means a gap under half a strike-width leaves the ATM unchanged, and any bigger gap naturally produces a new strike. No separate gap-threshold branch exists or is needed.
2. **Direction**: the daily EMA20-vs-EMA50 trend bias (`trend_bias.daily_trend_bias`, using only days strictly before the traded day) picks CE (bullish) or PE (bearish); **neutral trend → no ATM locked, no trade that day** (no-trade is a valid, expected outcome — never forced).
3. **OTM strike**: same option type as ATM, one strike further out of the money (confirmed explicitly by the user — not the opposite type).
4. **Sniper level** = 30% drop from the ATM contract's own previous trading day's closing premium (Black-Scholes-simulated, same reason as #6 below — no real historical option premiums are fetchable).
5. **OTM confirmation**: within a single candle, ATM's *lowest reachable* premium that candle ≤ Sniper level, AND OTM's *highest reachable* premium that candle > ATM's previous-day close. (See Technical Finding #2 below for why each leg is checked at its own favorable extreme, not the same shared spot value.)
6. **Square Number entry**: a 20-point grid applied to the OTM contract's premium. After confirmation, wait for OTM's premium to reach/cross the next Square Number above its current value (re-evaluated fresh every candle); enter at that square price.
7. **Trade management**: stop-loss = one square below entry (-20 points), target = two squares above entry (+40 points), both fixed — no momentum-based target extension (the sibling project has direct evidence, from its own real trade data, that trailing/momentum-based exits underperformed a simple fixed target there).
8. Both CALL and PUT sides supported symmetrically.
9. Intra-candle crossing convention: check each candle's high/low range (not just close); if both stop and target are theoretically crossable within one candle, conservatively assume the stop hit first.

**Explicitly deferred, not built (v1 scope):**
- The "fake breakout → consolidation → retest → reversal candle → second-chance entry" retry path from the original discussion. v1 just returns a clean no-trade result when OTM never confirms.
- Any live or paper trading code. This is backtest-only for now.

## Non-Obvious Technical Findings

1. **Kite Connect has no historical option premium data for expired contracts** (confirmed in the sibling project — the earliest listed expiry in the live instrument dump is always today's date). `src/options_pricing.py` simulates premiums via Black-Scholes using real historical NIFTY spot prices, with historical/realized volatility standing in for implied volatility. Same permanent API constraint as the sibling project, not something to fix later.
2. **A same-candle, same-spot confirmation check is mathematically impossible, not just imprecise — found and fixed 2026-07-27 before the first real backtest run.** The initial implementation checked ATM-decayed-to-Sniper and OTM-broken-out at the same single spot value (a candle's close). Since OTM and ATM are the same option type with OTM's strike further out, no-arbitrage guarantees OTM's premium can never exceed ATM's premium at any shared spot/vol/time point — so requiring ATM ≤ 70% of its old close (low) while OTM simultaneously exceeds that same old close (necessarily higher than ATM, which is already capped lower) can never be true at one spot value. **Fixed** by checking each leg at its own favorable extreme within the candle's high/low range instead (ATM's lowest reachable premium vs. OTM's highest reachable premium, each within the same candle) — the same "did price touch this level today" convention the sibling project already uses for stop/target crossings.
3. **`data_fetch.py`-style tools that overwrite (not merge) a cached CSV are a real risk when refreshing historical data** — this bit the sibling project during this same work session: refreshing with too small a `--days` value silently truncated ~230 days of cached history. This project's `data/historical/*.csv` files were copied from the sibling project's already-recovered, full-range cache (2025-06-23 through 2026-07-15) — if this project ever builds its own `data_fetch.py`, always pass a `--days` value comfortably larger than the existing cached range, never a "just fill the gap" small one.
4. **`data/historical/*.csv` is committed to git here**, unlike the sibling project (which gitignores it and regenerates via `data_fetch.py` + Kite auth). This project has no fetch mechanism yet — once it gets its own Kite Connect API app and `data_fetch.py`/`auth.py` equivalents, reconsider whether to keep committing this data or switch to the sibling project's gitignore convention.

## Current Status (last updated: 2026-07-27)

**Built and backtested, but not yet a working strategy.** `src/spfs_signal.py` (pure ATM/Sniper/Square math) and `src/spfs_backtester.py` (day-by-day replay, simulating both the ATM and OTM contracts' premiums via Black-Scholes per 5-minute candle) are complete, with 24 passing unit tests (`tests/test_spfs_signal.py`, `tests/test_spfs_backtester.py`) covering the pure functions and the confirmation→entry→exit state machine (via synthetic candle data + monkeypatched pricing, isolating the state machine from real Black-Scholes curvature).

**Honest backtest result (140 real cached days, 2025-12-17 to 2026-07-15): 5 no-trade days (neutral trend), 135 no-trade days (OTM never confirmed on the same candle as ATM's decay), ZERO trades taken.**

Investigated *why* via `tests/manual_spfs_sanity_check.py` rather than assuming the rule was simply too strict by design: on several individual days (e.g. 2026-07-06, 07-07, 07-09, 07-10) the OTM leg cleared its threshold AND the ATM leg separately reached Sniper *at some point that day* — but hand-tracing 2026-06-11 candle-by-candle confirmed they never land on the *same* candle. OTM's premium peak tends to occur early (right when a favorable spot move happens); ATM's premium trough tends to occur later (cumulative theta decay layered on top of the day's price action). Different times of day, for different underlying reasons — because ATM and OTM premiums are otherwise highly correlated (same underlying, same vol, same expiry). **This is a genuine structural finding about the rule exactly as specified, not a bug in this codebase.**

A rough diagnostic found that loosening the check to "both conditions true independently, anywhere in the same day" (not the same candle) would have qualified roughly 24 of the 135 no-confirmation days — a plausible starting point if the rule gets revisited, but not yet decided or built.

**This project was migrated into its own separate repo/folder on 2026-07-27**, at the user's explicit request, to keep it fully independent from the sibling XGBoost bot (separate code, and eventually a separate Kite Connect API app + separate Zerodha account). All SPFS source/test files were copied over with the sibling project's shared dependencies (`options_pricing.py` in full, and a new minimal `trend_bias.py` extracted from the sibling's larger `signal_engine.py` — SPFS only ever needed the EMA20/50 trend calculation from that file, not its RSI/Fibonacci/candlestick confluence logic). Verified fully standalone: all 24 tests and the backtester itself were re-run from this new location with zero dependency on the sibling project's folder, producing byte-identical results.

## Open Decisions

- **Zero trades on the strict same-candle confirmation rule — decide how to proceed.** Options: (a) loosen the timing to same-day instead of same-candle (~24/135 no-confirmation days would qualify per the diagnostic above), (b) adjust the Sniper %/Square interval/OTM distance and re-backtest, or (c) conclude SPFS isn't viable as specified and stop here. Not decided yet — do not change the rule unilaterally.
- **New Kite Connect API app + new Zerodha account** — needed before this project can move to paper trading (matching the sibling project's Phase 4). Not started; the user indicated this will be a genuinely separate app/account from the sibling project's.
- **Fake-breakout/reversal retry path** (from the original strategy discussion) — deliberately deferred out of v1. Revisit only after the core mechanic above is either fixed to produce real trades, or replaced.
- **Whether to keep committing `data/historical/*.csv`** once this project gets its own data-fetching capability (see Technical Finding #4).

## Repo Structure

```
Share_Market_Bava_SPFS/
  PROJECT_STATUS.md     # this file - read first
  README.md             # setup/usage instructions
  requirements.txt
  src/
    options_pricing.py  # Black-Scholes premium simulation + strike/expiry helpers (independent copy)
    trend_bias.py        # minimal EMA20/EMA50 daily trend calc (independent extraction)
    spfs_signal.py         # pure ATM/Sniper/Square Number logic
    spfs_backtester.py       # day-by-day replay + reporting
  tests/
    test_spfs_signal.py       # unit tests for the pure functions
    test_spfs_backtester.py    # state-machine regression tests (synthetic data)
    manual_spfs_sanity_check.py # non-automated, human-eyeball check against real cached data
  data/
    historical/           # cached NIFTY 50 daily + 5-minute candles (committed - see Technical Finding #4)
    backtest_results/      # spfs_trades.csv from the last backtester run (gitignored)
```
