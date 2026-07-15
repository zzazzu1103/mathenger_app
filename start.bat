@echo off
cd /d "%~dp0"
title Mathenger

echo ============================================
echo    Mathenger - Math Worksheet Generator
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not installed.
  echo.
  echo Please install Python from:
  echo   https://www.python.org/downloads/
  echo During setup, CHECK the box "Add python.exe to PATH".
  echo Then double-click this file again.
  echo.
  pause
  exit /b
)

echo [1/2] Installing required parts (first run only, may take 1-2 min)...
python -m pip install -r requirements.txt

echo.
echo [2/2] Starting the app. A browser window will open in a moment.
echo   - Keep this black window open while using the app.
echo   - Close this window when you are done.
echo.

timeout /t 2 >nul
start "" http://127.0.0.1:5000
python app.py

echo.
echo The app has stopped. You can close this window now.
pause
