"""장바구니 문제들로 학습지 HWP를 생성하는 서비스 레이어.

컨테이너는 원본 파일을 '제자리 패치'해서 만든다: 한글이 정상적으로 여는
원본 파일의 구조(FAT/디렉터리)를 그대로 두고 본문(Section0)과 미리보기
텍스트(PrvText)의 내용만 교체한다. 그래서 생성 파일의 컨테이너 호환성이
원본과 동일하게 보장된다.
"""

from __future__ import annotations

import sqlite3

from . import db
from .hwp.builder import WorksheetOptions, build_section, make_prvtext
from .hwp.patcher import MINI_CUTOFF, PatchTooLarge, patch_streams, stream_info
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
    original = db.get_source_file(conn, source_id)
    source = HwpSource.from_bytes(original)
    split = split_problems(source.body_section())

    section = build_section(
        prologue=split.prologue,
        problem_blobs=[p["blob"] for p in problems],
        empty_para=split.empty_para,
        options=options,
    )
    compressed = source.compress_body(section, level=9)

    # OLE 규격상 스트림은 크기(4096 기준)에 따라 놓이는 곳이 달라서,
    # 새 본문이 너무 작으면 원본과 같은 쪽(일반 섹터)에 머물도록 부풀린다.
    info = stream_info(original, "Section0")
    if not info["is_mini"] and len(compressed) < MINI_CUTOFF:
        compressed = source.compress_body(section, level=0)
        while len(compressed) < MINI_CUTOFF and split.empty_para:
            section = section + split.empty_para
            compressed = source.compress_body(section, level=0)

    try:
        return patch_streams(
            original,
            {
                "Section0": compressed,
                "PrvText": make_prvtext([p["text"] for p in problems]),
            },
            resize={"Section0"},
            allow_truncate={"PrvText"},
        )
    except PatchTooLarge as exc:
        raise ValueError(
            "학습지 본문이 원본 문서보다 커서 만들 수 없습니다. "
            "문제 수를 줄여서 다시 시도해 주세요. "
            f"({exc})"
        ) from exc
