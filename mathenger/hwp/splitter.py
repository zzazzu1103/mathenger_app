"""본문 Section 스트림을 문제 단위 블록으로 분리한다.

분리 알고리즘 (업로드된 기출 모음 파일로 검증됨):

1. 최상위(level 0) 문단들을 모은다. 첫 문단은 구역/단 정의(secd/cold)를
   담는 머리 문단이므로 '프롤로그'로 따로 보관한다.
2. PARA_LINE_SEG의 세로 위치(y)가 줄어드는 지점 = 새 페이지 시작.
3. 페이지 안에서 문제의 끝은 (a) 선택지 문단(⑤ 포함) 또는
   (b) '구하시오'가 들어간 문단. 그 뒤에 오는 개체 전용 문단(그림 등)과
   "[4점]" 같은 배점 전용 문단은 현재 문제에 붙인다.
4. 다음 실제 텍스트 문단부터 새 문제가 시작된다.

문제 블록은 원본 스트림의 연속된 바이트 조각(레코드 경계 정렬)으로
보관하므로 수식·표·그림이 바이트 단위로 그대로 유지된다.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from .records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
    Record,
    ctrl_id,
    extract_text,
    parse_records,
)

# 문제 본문에 영향 없는 레이아웃성 컨트롤들
LAYOUT_CTRL_IDS = {"secd", "cold", "pghd", "pgfd", "nwno", "pgct", "pgnp", "head", "foot"}

_SCORE_ONLY = re.compile(r"^[\s\[\]0-9점\.]+$")


@dataclass
class Paragraph:
    index: int
    rec_start: int  # records 리스트 내 시작 인덱스
    rec_end: int  # exclusive
    byte_start: int
    byte_end: int
    text: str = ""
    y0: int | None = None
    ctrls: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def has_object(self) -> bool:
        return any(c not in LAYOUT_CTRL_IDS for c in self.ctrls)

    @property
    def visible(self) -> bool:
        return self.has_text or self.has_object


@dataclass
class ProblemBlock:
    seq: int  # 1-based, 문서 내 순서
    para_start: int
    para_end: int  # inclusive
    blob: bytes  # 원본 레코드 바이트 그대로
    text: str  # 검색/미리보기용 평문


@dataclass
class SplitResult:
    prologue: bytes  # 구역 정의를 담은 머리 문단(들)
    problems: list[ProblemBlock]
    empty_para: bytes  # 간격용 빈 문단 템플릿 (없으면 b"")
    warnings: list[str] = field(default_factory=list)


def _collect_paragraphs(data: bytes, records: list[Record]) -> list[Paragraph]:
    starts = [i for i, r in enumerate(records) if r.tag == HWPTAG_PARA_HEADER and r.level == 0]
    if not starts:
        return []
    paras: list[Paragraph] = []
    for j, s in enumerate(starts):
        e = starts[j + 1] if j + 1 < len(starts) else len(records)
        p = Paragraph(
            index=j,
            rec_start=s,
            rec_end=e,
            byte_start=records[s].pos,
            byte_end=records[e - 1].end,
        )
        for k in range(s, e):
            rec = records[k]
            if rec.level != 1:
                continue
            if rec.tag == HWPTAG_PARA_TEXT:
                p.text += extract_text(rec.payload(data))
            elif rec.tag == HWPTAG_PARA_LINE_SEG and p.y0 is None and rec.size >= 36:
                p.y0 = struct.unpack_from("<i", data, rec.pos + rec.header_len + 4)[0]
            elif rec.tag == HWPTAG_CTRL_HEADER:
                p.ctrls.append(ctrl_id(rec.payload(data)))
        paras.append(p)
    return paras


def _is_problem_end(p: Paragraph) -> bool:
    return "⑤" in p.text or "구하시오" in p.text


def _is_attachable_tail(p: Paragraph) -> bool:
    """문제 끝 표지 뒤에 붙일 수 있는 문단: 개체 전용 또는 '[4점]' 류."""
    if not p.has_text:
        return True
    return bool(_SCORE_ONLY.fullmatch(p.text.strip()))


def split_problems(data: bytes) -> SplitResult:
    """압축 해제된 Section 스트림을 문제 블록들로 나눈다."""
    records = parse_records(data)
    paras = _collect_paragraphs(data, records)
    if not paras:
        return SplitResult(prologue=b"", problems=[], empty_para=b"")

    warnings: list[str] = []

    # 프롤로그: 구역 정의를 담은 첫 문단
    prologue = data[paras[0].byte_start : paras[0].byte_end]
    if paras[0].has_text:
        warnings.append("첫 문단에 텍스트가 있어 프롤로그와 문제가 섞였을 수 있습니다.")
    body = paras[1:]

    # 간격용 빈 문단 템플릿: 텍스트/개체/컨트롤이 전혀 없는 가장 단순한 문단
    empty_para = b""
    for p in body:
        if not p.visible and not p.ctrls:
            empty_para = data[p.byte_start : p.byte_end]
            break

    # 페이지 그룹 (y 리셋 = 새 페이지)
    pages: list[list[Paragraph]] = []
    cur: list[Paragraph] = []
    prev_y: int | None = None
    for p in body:
        if (
            cur
            and p.y0 is not None
            and prev_y is not None
            and p.y0 < prev_y
        ):
            pages.append(cur)
            cur = []
        cur.append(p)
        if p.y0 is not None:
            prev_y = p.y0
    if cur:
        pages.append(cur)

    # 페이지 안에서 문제 단위로 분리
    groups: list[list[Paragraph]] = []
    for page in pages:
        block: list[Paragraph] = []
        ended = False
        for p in page:
            if ended and p.visible and not _is_attachable_tail(p):
                _strip_and_add(groups, block)
                block = []
                ended = False
            if not p.visible:
                if block:
                    block.append(p)
                continue
            block.append(p)
            if _is_problem_end(p):
                ended = True
        if block:
            _strip_and_add(groups, block)
            if block and not ended and any(p.visible for p in block):
                first = next(p for p in block if p.visible)
                warnings.append(
                    f"문단 {first.index}에서 시작하는 문제의 끝 표지(선택지/구하시오)를 찾지 못해 "
                    f"페이지 끝까지를 한 문제로 묶었습니다."
                )

    problems = []
    for i, g in enumerate(groups):
        blob = data[g[0].byte_start : g[-1].byte_end]
        problems.append(
            ProblemBlock(
                seq=i + 1,
                para_start=g[0].index,
                para_end=g[-1].index,
                blob=blob,
                text=_problem_text(blob, g),
            )
        )
    return SplitResult(prologue=prologue, problems=problems, empty_para=empty_para, warnings=warnings)


def _problem_text(blob: bytes, paras: list[Paragraph]) -> str:
    """수식·표·글상자 내용까지 담은 전체 텍스트. 실패하면 단순 텍스트."""
    from .richtext import extract_problem_view

    try:
        rich = extract_problem_view(blob).text
        if rich.strip():
            return rich
    except Exception:
        pass
    return _clean_text(paras)


def _strip_and_add(groups: list[list[Paragraph]], block: list[Paragraph]) -> None:
    while block and not block[0].visible:
        block.pop(0)
    while block and not block[-1].visible:
        block.pop()
    if block:
        groups.append(block)


def _clean_text(paras: list[Paragraph]) -> str:
    text = "\n".join(p.text.strip() for p in paras if p.has_text)
    return re.sub(r"\n{2,}", "\n", text).strip()
