@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0scripts\open-things.py"
) else (
  python "%~dp0scripts\open-things.py"
)
if errorlevel 1 pause
