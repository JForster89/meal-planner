@echo off
REM Thin wrapper so the desktop shortcut can run the PowerShell launcher
REM regardless of the machine's execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_planner.ps1"
