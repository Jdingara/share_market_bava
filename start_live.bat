@echo off
rem Sniper + HLC bots - REAL MONEY (real Zerodha orders). Double-click before 09:15 on a trading day.
rem Needs LIVE_TRADING=YES in .env. Money: whatever is in the Zerodha account at 09:20, shared by the 4 bots.
rem Emergency stop: double-click stop_all.bat (sells everything, no more trades today).
rem Dashboards: Sniper NIFTY :8050, Sniper SENSEX :8051, HLC NIFTY :8052, HLC SENSEX :8053
cd /d "%~dp0"
if exist STOP del STOP
py src\kite_auth.py
if errorlevel 1 goto end
start "Sniper SENSEX (REAL)" cmd /k py src\sniper_live.py --market SENSEX --no-browser --real
start "HLC NIFTY (REAL)" cmd /k py src\hlc_live.py --market NIFTY --real
start "HLC SENSEX (REAL)" cmd /k py src\hlc_live.py --market SENSEX --no-browser --real
title Sniper NIFTY (REAL)
py src\sniper_live.py --market NIFTY --real
:end
pause
