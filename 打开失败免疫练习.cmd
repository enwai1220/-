@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0scripts\launcher.py"
) else (
  python "%~dp0scripts\launcher.py"
)
if errorlevel 1 pause
