# SPFS Options Strategy — Project Status

This file is the single source of truth for this project's goal, decisions, and current progress. Any AI assistant (Claude, Codex, or otherwise) or human picking this up should read this file first before making changes. Keep it updated as the project progresses — update the "Current Status" and "Open Decisions" sections whenever a phase completes or a new decision is made.

## Relationship to the sibling project

This is a **separate, independent project** from the older "share-market-bro" NIFTY options bot (rule-based + XGBoost signal, currently running live on its own Kite Connect API app and Zerodha account). That project continues unchanged. This one exists because the user wants to try a genuinely different strategy ("SPFS") without risking or entangling the working system — separate codebase, and eventually a separate Kite Connect API app and separate Zerodha account once this moves past backtesting.

**No runtime code is shared between the two repos.** Building blocks this project needs (Black-Scholes pricing, strike/expiry math, EMA trend calculation) are kept as independent copies here (`src/options_pricing.py`, `src/trend_bias.py`), not imports reaching into the other project's folder — so this project keeps working even if the sibling project's folder is moved, renamed, or deleted.

## Goal

Build and validate the SPFS options trading strategy for NIFTY 50 weekly options, following the same disciplined validation order as the sibling project: **backtest first (measure a real historical edge) → paper trading (simulated orders, real live data) → live trading (real money) — never skip ahead.**

## The SPFS Strategy Rules (as currently specified — do not change without explicit user confirmation)

Reconciled 2026-07-26/27 from two of the user's strategy write-ups that directly contradicted each other on the most important point (one had the ATM strike migrating dynamically with price; the other locked it for the whole day). The user chose the locked-ATM version. Reconciled via several rounds of clarifying questions rather than guessing:

1. **Daily ATM lock**: primary reference price is the **previous trading day's closing index value**, not today's open — computed once before the session and never re-picked intraday. **Correction 2026-07-27**: an earlier implementation used *today's opening spot* instead, on the mistaken belief that this was an equivalent simplification. The user corrected this directly with a concrete example — the reference price is yesterday's close, not today's open.

   **Refined further the same day, per the user's own worked example (shared as `Bava Details for bot.docx`, found and read before committing anything - see Non-Obvious Technical Findings)**: the ATM is NOT just `nearest_strike(previous_close)` rounding. Starting from that as a center point, search the strikes within **3 strikes above and 3 below** (`ATM_SEARCH_RADIUS_STRIKES = 3`, "max 6 strikes" per the user) and pick whichever strike has the previous day's **closest CE and PE closing premiums** (`_closest_ce_pe_strike` in `spfs_signal.py`, using Black-Scholes to simulate both legs off the previous close) — the standard "true ATM via put-call parity" definition, not simple spot-rounding. The user's own worked example: previous close 23922 rounds to 23900 naively, but checking CE/PE gaps across 23750–24000 shows 24000 has the smallest gap, so 24000 is the real ATM. This search always runs (the user's explicit choice, not just a tie-break near a strike boundary).

   Today's actual open is used only for the huge-gap exception: if it has moved a full strike interval (50pts) or more away from the (now CE/PE-gap-refined) previous-close-based ATM, that stale ATM is discarded in favor of **simple `nearest_strike()` rounding of today's open** — deliberately NOT re-run through the CE/PE-gap search, since that search is only meaningful using previous-close pricing near where the previous close actually was; a gap scenario means today's open sits far outside where that pricing means anything (tried running the refined search here first, found it just walks to whichever edge of the search window is nearest yesterday's close - not a real refinement - see Current Status).
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
5. **Always read a file before committing/pushing it, even if it wasn't explicitly shared in chat.** A file (`Bava Details for bot.docx`) appeared directly in this project's folder mid-session, picked up by `git add -A`. It was opened and read before staging/committing it — turned out to be a real, useful strategy refinement (the CE/PE-gap ATM search, see Strategy Rule #1), not sensitive data, but that had to be confirmed by actually reading it, not assumed either way.

## Current Status (last updated: 2026-07-27)

**Built and backtested, but not yet a working strategy.** `src/spfs_signal.py` (pure ATM/Sniper/Square math) and `src/spfs_backtester.py` (day-by-day replay, simulating both the ATM and OTM contracts' premiums via Black-Scholes per 5-minute candle) are complete, with 24 passing unit tests (`tests/test_spfs_signal.py`, `tests/test_spfs_backtester.py`) covering the pure functions and the confirmation→entry→exit state machine (via synthetic candle data + monkeypatched pricing, isolating the state machine from real Black-Scholes curvature).

**Honest backtest result (140 real cached days, 2025-12-17 to 2026-07-15): 5 no-trade days (neutral trend), 135 no-trade days (OTM never confirmed on the same candle as ATM's decay), ZERO trades taken.**

Investigated *why* via `tests/manual_spfs_sanity_check.py` rather than assuming the rule was simply too strict by design: on several individual days (e.g. 2026-07-06, 07-07, 07-09, 07-10) the OTM leg cleared its threshold AND the ATM leg separately reached Sniper *at some point that day* — but hand-tracing 2026-06-11 candle-by-candle confirmed they never land on the *same* candle. OTM's premium peak tends to occur early (right when a favorable spot move happens); ATM's premium trough tends to occur later (cumulative theta decay layered on top of the day's price action). Different times of day, for different underlying reasons — because ATM and OTM premiums are otherwise highly correlated (same underlying, same vol, same expiry). **This is a genuine structural finding about the rule exactly as specified, not a bug in this codebase.**

A rough diagnostic found that loosening the check to "both conditions true independently, anywhere in the same day" (not the same candle) would have qualified roughly 24 of the 135 no-confirmation days — a plausible starting point if the rule gets revisited, but not yet decided or built.

**This project was migrated into its own separate repo/folder on 2026-07-27**, at the user's explicit request, to keep it fully independent from the sibling XGBoost bot (separate code, and eventually a separate Kite Connect API app + separate Zerodha account). All SPFS source/test files were copied over with the sibling project's shared dependencies (`options_pricing.py` in full, and a new minimal `trend_bias.py` extracted from the sibling's larger `signal_engine.py` — SPFS only ever needed the EMA20/50 trend calculation from that file, not its RSI/Fibonacci/candlestick confluence logic). Verified fully standalone: all 24 tests and the backtester itself were re-run from this new location with zero dependency on the sibling project's folder, producing byte-identical results.

**ATM lock rule corrected the same day, right after the migration** (see Strategy Rule #1 above for the full before/after): the user pointed out directly that ATM must be locked off the *previous day's closing index value*, not today's open, with a concrete example (previous close 23922 → ATM 23900). The earlier "today's open already handles the gap exception for free" reasoning was a mistaken oversimplification — the real rule needs previous-close as the primary reference *and* a genuine gap-check branch on top, which the fix now implements (`lock_atm_strike(previous_close_spot, day_open_spot)`, `ATM_GAP_THRESHOLD = 50`). 2 new/rewritten unit tests cover the previous-close basis, a small-move no-override case, and both a clear gap and an exactly-at-threshold gap; full suite now 26 passing.

**Re-ran the backtest after the previous-close fix: 1 trade (was 0), a target hit, +40 points (+25%)** — still just n=1, only confirming the pipeline runs end-to-end.

**Refined the ATM rule further the same session, per `Bava Details for bot.docx`** (see Strategy Rule #1): replaced simple `nearest_strike(previous_close)` rounding with the CE/PE-gap-minimizing search across ±3 strikes. Also tested applying that same refined search to the huge-gap exception branch - found it degenerates to just walking to whichever edge of the search window is nearest yesterday's close (not a real refinement, since previous-close pricing has no meaningful signal near a strike far away from where it actually closed), so the gap-exception branch was kept as simple rounding of today's open. 2 new tests added (`test_closest_ce_pe_strike_finds_exact_minimum_gap_within_radius`, `test_closest_ce_pe_strike_clamped_to_search_radius`), existing `lock_atm_strike` tests rewritten with monkeypatched Black-Scholes for deterministic control (real BS numbers would require hand-verifying a forward-price/interest-rate calculation to predict expected results) - full suite now 28 passing.

**Re-ran the real backtest with the fully refined ATM rule: back to 0 trades.** Under this project's simplified flat-volatility Black-Scholes model (no strike-dependent skew), the CE/PE-gap-minimizing strike is mathematically very close to simple nearest-strike rounding anyway (the two only diverge by the tiny interest-rate forward adjustment) - so this refinement, while a real and correct improvement going forward (and likely to matter more against real live quotes, which do have skew), had almost no effect on which strike gets chosen in this backtest, and the one trade found under the simpler rule apparently depended on exactly the strike shift this refinement undoes. **Honest current state: the strategy, fully as specified today, produces 0-1 trades across 140 real days** - still not remotely a validated edge, and the same-candle confirmation rule (Strategy Rule #5) remains the dominant reason, unaffected by any ATM-selection refinement since it's about the correlation between ATM/OTM premiums, not which exact strike is chosen.

## Open Decisions

- **0-1 trades across 140 days even after two real ATM-rule corrections — the same-candle confirmation rule (Strategy Rule #5) is the real bottleneck, not ATM selection.** Options: (a) loosen the confirmation timing to same-day instead of same-candle (a pre-fix diagnostic found ~24/135 no-confirmation days would have qualified under the old ATM rule - worth re-checking against the current ATM logic, not yet done), (b) adjust the Sniper %/Square interval/OTM distance and re-backtest, or (c) conclude SPFS isn't viable as specified and stop here. Not decided yet — do not change the rule unilaterally.
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
