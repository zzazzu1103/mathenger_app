#!/bin/bash
# Mac launcher - double-click to start the app.
cd "$(dirname "$0")"

echo "============================================"
echo "   Mathenger - Math Worksheet Generator"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python3 is not installed."
  echo "Install it from https://www.python.org/downloads/ and run again."
  read -r -p "Press Enter to close..."
  exit 1
fi

echo "[1/2] Installing required parts (first run only, may take 1-2 min)..."
python3 -m pip install -r requirements.txt
echo
echo "[2/2] Starting the app. A browser window will open in a moment."
echo "  - Press Control+C or close this window when you are done."
echo

sleep 2
open http://127.0.0.1:5000
python3 app.py
