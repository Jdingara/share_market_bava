@echo off
rem EMERGENCY STOP for the real-money bots: every bot sells what it holds and stops buying for today.
cd /d "%~dp0"
echo stop> STOP
echo All bots will sell everything and stop trading within a few seconds.
echo (start_live.bat removes this STOP file the next morning.)
pause
