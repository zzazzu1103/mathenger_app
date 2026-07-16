"""명령줄 도구.

사용 예:
    python -m mathenger.cli import 문제모음.hwp 정리.xlsx
    python -m mathenger.cli list
    python -m mathenger.cli build 학습지.hwp 3 1 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db
from .hwp.builder import WorksheetOptions
from .importer import import_pair
from .worksheet import generate_worksheet

DEFAULT_DB = Path.home() / "Mathenger" / "mathenger.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mathenger", description="HWP 문제은행 CLI")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB 경로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="HWP(+엑셀) 가져오기")
    p_import.add_argument("hwp")
    p_import.add_argument("xlsx", nargs="?")

    sub.add_parser("list", help="문제 목록 출력")

    p_build = sub.add_parser("build", help="학습지 생성")
    p_build.add_argument("output")
    p_build.add_argument("ids", nargs="+", type=int, help="문제 ID (순서대로)")
    p_build.add_argument("--separator", choices=["column", "page", "spacing"], default="column")
    p_build.add_argument("--source-label", action="store_true", help="문제 위에 출처 표시")
    p_build.add_argument("--answer-page", action="store_true", help="정답 및 해설 페이지 추가")

    args = parser.parse_args(argv)
    conn = db.connect(args.db)

    if args.cmd == "import":
        hwp_bytes = Path(args.hwp).read_bytes()
        xlsx_bytes = Path(args.xlsx).read_bytes() if args.xlsx else None
        report = import_pair(conn, Path(args.hwp).name, hwp_bytes, xlsx_bytes)
        print(f"문제 {report.n_problems}개 가져옴, 메타데이터 {report.n_matched}개 연결 (원본 #{report.source_id})")
        for w in report.warnings:
            print("경고:", w)

    elif args.cmd == "list":
        for r in db.search_problems(conn):
            preview = r["text"][:36].replace("\n", " ")
            print(f'#{r["id"]:3d} [{r["year"]} {r["month"]} {r["origin"]} {r["number"]}] '
                  f'{r["subject"]}/{r["unit_mid"]} | {preview}')

    elif args.cmd == "build":
        options = WorksheetOptions(
            separator=args.separator,
            source_label=args.source_label,
            answer_page=args.answer_page,
        )
        data = generate_worksheet(conn, args.ids, options)
        Path(args.output).write_bytes(data)
        print(f"{args.output} 생성 ({len(data):,} bytes, 문제 {len(args.ids)}개)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
