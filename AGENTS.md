# Agent Instructions

Before doing anything in this repo, read **`PROJECT_STATUS.md`** in full. It contains the project goal, the SPFS strategy rules (which must not be changed without explicit user confirmation), the current backtest status, and non-obvious technical findings.

After completing any meaningful work session, update `PROJECT_STATUS.md`'s "Current Status" and "Open Decisions" sections so the next session (by any AI or human) has accurate context — treat it as the project's persistent memory, not just onboarding material.

This project is a sibling of, and shares no runtime code with, the separate "share-market-bro" repo (the older XGBoost/rule-based NIFTY bot, which keeps running unchanged and independently, with its own Kite Connect API app and Zerodha account). Any building block this project needs from that one (pricing math, trend calculation, etc.) is kept as its own independent copy here on purpose - do not add an import that reaches into the other project's folder.
