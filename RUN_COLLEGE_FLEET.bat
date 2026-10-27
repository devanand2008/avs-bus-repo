@echo off
setlocal
title College Fleet Command
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python and enable Add to PATH.
  pause
  exit /b 1
)
python "%~dp0scripts\launch.py" %*
if errorlevel 1 (
  echo.
  echo Startup did not complete. Read the message above and README.md.
  pause
  exit /b 1
)
exit /b 0
