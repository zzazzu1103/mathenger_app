#!/bin/bash
# 맥(Mac)용 실행 파일 — 더블클릭하면 앱이 켜집니다.
cd "$(dirname "$0")"

echo "============================================"
echo "   Mathenger  수학 문제은행 / 학습지 생성기"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[오류] Python3가 설치되어 있지 않습니다."
  echo "  https://www.python.org/downloads/ 에서 설치 후 다시 실행해 주세요."
  read -r -p "엔터를 누르면 닫힙니다..."
  exit 1
fi

echo "[1/2] 처음 실행이면 필요한 부품을 내려받습니다 (1~2분 걸릴 수 있어요)..."
python3 -m pip install -r requirements.txt
echo
echo "[2/2] 앱을 시작합니다. 잠시 후 브라우저가 자동으로 열립니다."
echo "  * 다 쓰면 이 창에서 Control+C 를 누르거나 창을 닫으세요."
echo

sleep 2
open http://127.0.0.1:5000
python3 app.py
