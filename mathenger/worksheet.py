"""장바구니 문제들로 학습지 HWP를 생성하는 서비스 레이어."""

from __future__ import annotations

import sqlite3

from . import db
from .hwp.builder import WorksheetOptions, build_worksheet
from .hwp.reader import HwpSource
from .hwp.splitter import split_problems


def generate_worksheet(
    conn: sqlite3.Connection,
    problem_ids: list[int],
    options: WorksheetOptions | None = None,
) -> bytes:
    """선택한 문제 ID들(순서 유지)로 학습지 HWP 바이트를 만든다."""
    problems = db.get_problems(conn, problem_ids)
    if not problems:
        raise ValueError("선택된 문제가 없습니다.")
    missing = set(problem_ids) - {p["id"] for p in problems}
    if missing:
        raise ValueError(f"존재하지 않는 문제 ID: {sorted(missing)}")

    source_ids = {p["source_id"] for p in problems}
    if len(source_ids) > 1:
        names = sorted({p["source_name"] for p in problems})
        raise ValueError(
            "서로 다른 원본 파일의 문제를 한 학습지에 담을 수 없습니다. "
            f"(선택된 원본: {', '.join(names)}) 원본 파일별로 나눠서 만들어 주세요. "
            "글꼴·수식 정의가 원본마다 달라 섞으면 서식이 깨질 수 있기 때문입니다."
        )

    source_id = source_ids.pop()
    source = HwpSource.from_bytes(db.get_source_file(conn, source_id))
    split = split_problems(source.body_section())

    return build_worksheet(
        source=source,
        prologue=split.prologue,
        problem_blobs=[p["blob"] for p in problems],
        empty_para=split.empty_para,
        options=options,
        preview_texts=[p["text"] for p in problems],
    )
