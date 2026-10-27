@echo off
setlocal
title College Fleet Command - Checks
cd /d "%~dp0"
python "%~dp0scripts\check.py"
if errorlevel 1 (
  pause
  exit /b 1
)
echo All checks passed.
pause
exit /b 0
