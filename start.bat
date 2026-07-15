@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Mathenger 학습지 생성기

echo ============================================
echo    Mathenger  수학 문제은행 / 학습지 생성기
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [오류] Python이 설치되어 있지 않습니다.
  echo.
  echo   https://www.python.org/downloads/ 에서 Python을 설치해 주세요.
  echo   설치 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크하세요.
  echo.
  echo 설치 후 이 파일을 다시 더블클릭하면 됩니다.
  echo.
  pause
  exit /b
)

echo [1/2] 처음 실행이면 필요한 부품을 내려받습니다 (1~2분 걸릴 수 있어요)...
python -m pip install -r requirements.txt
echo.
echo [2/2] 앱을 시작합니다. 잠시 후 인터넷 창(브라우저)이 자동으로 열립니다.
echo.
echo   * 이 검은 창은 앱이 켜져 있는 동안 그대로 두세요.
echo   * 다 쓰면 이 창을 닫으면 앱이 꺼집니다.
echo.

timeout /t 2 >nul
start "" http://127.0.0.1:5000
python app.py

echo.
echo 앱이 종료되었습니다. 창을 닫아도 됩니다.
pause
