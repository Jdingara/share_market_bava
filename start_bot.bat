@echo off
rem Sniper bot - PAPER MODE (no real orders). Double-click before 09:15 on a trading day.
rem Logs in once, then runs SENSEX in a second window and NIFTY in this one.
cd /d "%~dp0"
py src\kite_auth.py
if errorlevel 1 goto end
start "Sniper Bot SENSEX (PAPER)" cmd /k py src\sniper_live.py --market SENSEX
title Sniper Bot NIFTY (PAPER)
py src\sniper_live.py --market NIFTY
:end
pause
