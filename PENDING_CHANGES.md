# Pending rule changes (owner's decisions, not yet in code)

Rules are not changed during the week (owner, 21-10: "daily matri amaikka kudathu"). Decisions collected here are
replayed over the past days at the weekend, shown to the owner, and only then added to that strategy's branch.

| Date | Strategy (branch) | Decision | Status |
|---|---|---|---|
| 21-10 | #1 Sniper (`sniper`) | The 2nd entry must also look at the OPPOSITE side, not only the first trade's side (21-10: morning CE, then the market went down - no PE 2nd entry). | to replay + add at the weekend |
| 21-10 | #2 HLC (`hlc`) | The 12:30 2nd entry must follow the CURRENT trend (CE or PE by the market's direction then), not the morning trade's side (21-10: 12:30 PM reversal took CE while the market was falling). | to replay + add at the weekend |
| 23-10 | #4 Lalitha (`lalitha`) | No entry on the 09:15 first 3-min candle (gap days blow every indicator up: 23-10 SENSEX RSI 75.6 only on 09:15, entry -Rs 14,950). Owner said ok to replay at the weekend first. | to replay + add at the weekend |
| 23-10 | #4 Lalitha (`lalitha`) | Bug (not a rule): before 09:15 the bot asks Zerodha with from > to ('from date cannot be after to date') every 3 min - fix after market hours. | fix after 15:30 |
