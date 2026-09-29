@echo off
rem Sniper + HLC bots - PAPER MODE (no real orders). Double-click before 09:15 on a trading day.
rem Logs in once, then starts 4 bots in their own windows. Keep them open until 15:00.
rem Dashboards: Sniper NIFTY :8050, Sniper SENSEX :8051, HLC NIFTY :8052, HLC SENSEX :8053
cd /d "%~dp0"
py src\kite_auth.py
if errorlevel 1 goto end
start "Sniper SENSEX (PAPER)" cmd /k py src\sniper_live.py --market SENSEX --no-browser
start "HLC NIFTY (PAPER)" cmd /k py src\hlc_live.py --market NIFTY
start "HLC SENSEX (PAPER)" cmd /k py src\hlc_live.py --market SENSEX --no-browser
title Sniper NIFTY (PAPER)
py src\sniper_live.py --market NIFTY
:end
pause
