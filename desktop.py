"""데스크톱 실행 진입점 (PyInstaller exe용).

Python 설치 없이 쓸 수 있도록 이 파일을 PyInstaller로 하나의 실행파일로
묶는다. 실행하면 로컬 웹서버를 띄우고 브라우저를 자동으로 연다.
"""

from __future__ import annotations

import socket
import threading
import webbrowser

from app import app


def _pick_port(candidates=(5000, 5001, 5050, 8000, 8080)) -> int:
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # 전부 사용 중이면 아무 빈 포트나
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 48)
    print("  Mathenger - 수학 문제은행 / 학습지 생성기")
    print("=" * 48)
    print(f"\n  브라우저가 자동으로 열립니다: {url}")
    print("  이 창을 닫으면 프로그램이 종료됩니다.\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
