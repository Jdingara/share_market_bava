# Pending rule changes (owner's decisions, not yet in code)

Rules are not changed during the week (owner, 21-10: "daily matri amaikka kudathu"). Decisions collected here are
replayed over the past days at the weekend, shown to the owner, and only then added to that strategy's branch.

| Date | Strategy (branch) | Decision | Status |
|---|---|---|---|
| 21-10 | #1 Sniper (`sniper`) | The 2nd entry must also look at the OPPOSITE side, not only the first trade's side (21-10: morning CE, then the market went down - no PE 2nd entry). | to replay + add at the weekend |
| 21-10 | #2 HLC (`hlc`) | The 12:30 2nd entry must follow the CURRENT trend (CE or PE by the market's direction then), not the morning trade's side (21-10: 12:30 PM reversal took CE while the market was falling). | to replay + add at the weekend |
| 23-10 | #2 HLC (`hlc`) | Same idea, owner's charts: after 12:30 the index reached S2 (NIFTY 22399.8, low 22372 at 12:50) / Fib 0.786 (SENSEX ~72500, low 72452) -> reversal (12:50-12:55 Morning Star) -> 13:15 confirmation retest -> CE entry (NIFTY ran to 22579, SENSEX to 73095). Owner's NIFTY strike: 22500 CE (OTM above the then-ATM 22400) bought ~129 at ~13:25-13:30 after the second S2 test, ran to ~260; SENSEX: CE entry on the 13:15 retest of Fib 0.786. Bot took the 13-10 same-side PM reversal (SENSEX PE -16). Conflicts with 13-10 "2nd entry on the same option". Owner's rule (23-10): 2nd entry = a candle confirmation, then when the INDEX DIRECTION CHANGES, take the entry (on the new direction's side). Owner (23-10, more): some days it keeps the same direction (then the 2nd entry stays on that side); as said before it runs to S2 (R2) or turns at the Fib 0.786 (close -> S2/R2) - a turn there + candle confirmation = the other side. NIFTY 50 leads and SENSEX follows, so SENSEX's 2nd entry may also take NIFTY's confirmation. NOTE: the existing R2_OR_FIB_REVERSAL exit books at the Fib 0.75 (close -> S2) - owner now says 0.786: ask which. | replay vs 13-10 rule at the weekend |
| 23-10 | #4 Lalitha (`lalitha`) | No entry on the 09:15 first 3-min candle (gap days blow every indicator up: 23-10 SENSEX RSI 75.6 only on 09:15, entry -Rs 14,950). Owner said ok to replay at the weekend first. | to replay + add at the weekend |
| 23-10 | #4 Lalitha (`lalitha`) | Bug (not a rule): before 09:15 the bot asks Zerodha with from > to ('from date cannot be after to date') every 3 min - fix after market hours. | fix after 15:30 |

## 23-10 changes already put in (owner said "now") - to re-check at the weekend against all earlier rules
| Date | Strategy (branch) | Owner's remark (market that day) | What went in | Check against |
|---|---|---|---|---|
| 23-10 | #2 HLC (`hlc`) | NIFTY/SENSEX PE charts: target = option yesterday high / S1-S2, first one -> SL there, then TSL | BREAKOUT_FIRST_TARGET_LOCK (index S1/S2/S3, premium Fib 0.786, premium yesterday high) | 12-10 PB Fib 0.786 exit, 13-10 profit lock steps, 22-10 breakout target |
| 23-10 | #3 ORB (`orb`) | retest 0.5-0.618 -> then "entry tottal entry" | ZONE_TOUCH (0.5 touch), ZONE_CONFIRM off, 0.75 off | 22-10 0.75 retest (+16,880 / +39,600 on 22-10) - replay all three over the week |
| 23-10 | #1 Sniper (`sniper`) | SENSEX 10:15 ATM CE confirmation -> OTM 73100 PE square 676 -> 784 | confirm entry always OTM; confirming ATM leg must have closed above the Sniper yesterday | 19-10 / 22-10 ATM-confirm rules, 21-10 pending "2nd entry opposite side" |
