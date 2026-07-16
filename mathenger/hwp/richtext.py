"""문제 블록의 '전체 내용' 텍스트 추출 (미리보기·검색용).

단순 텍스트 추출(records.extract_text)은 수식·표·글상자 내용을
건너뛴다. 여기서는 레코드 트리를 재귀적으로 따라가며

- 수식(eqed)은 스크립트를 ⟨ ⟩ 안에 인라인으로,
- 표(tbl)의 셀 문단들은 【 】 블록으로,
- 글상자/도형(gso) 속 문단은 〔 〕 블록으로,
- 그림은 [그림N] 표시(+BinData ID 수집)

형태로 사람이 읽을 수 있는 전체 텍스트를 만든다. 어떤 경우에도
실패하면 호출 측에서 단순 텍스트로 대체할 수 있게 예외를 올린다.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_TEXT,
    Record,
    ctrl_id,
    parse_records,
)

HWPTAG_SHAPE_PICTURE = 85
HWPTAG_EQEDIT = 88

# CTRL_HEADER 레코드와 짝을 이루는 문단 텍스트 앵커 문자들
CTRL_ANCHOR_CODES = frozenset({2, 3, 11, 15, 16, 17, 18, 21, 22, 23})
# 8워드를 차지하지만 컨트롤 레코드가 없는 인라인 문자들 (탭 등)
INLINE8_CODES = frozenset({4, 5, 6, 7, 8, 9, 19, 20})

PICTURE_BINID_OFFSET = 71  # SHAPE_PICTURE 페이로드 내 BinData ID(u16) 위치


@dataclass
class ProblemView:
    text: str = ""
    image_bin_ids: list[int] = field(default_factory=list)


def extract_problem_view(blob: bytes, latex: bool = False) -> ProblemView:
    """문제 블록(레코드 바이트)에서 전체 텍스트와 그림 ID 목록을 뽑는다.

    latex=True이면 수식을 ⟨스크립트⟩ 대신 \\( LaTeX \\) 로 감싸 반환한다
    (브라우저 MathJax 렌더링용). False면 검색·평문 미리보기용.
    """
    records = parse_records(blob)
    view = ProblemView()
    lines: list[str] = []
    i = 0
    while i < len(records):
        rec = records[i]
        if rec.tag == HWPTAG_PARA_HEADER:
            text, i = _render_para(blob, records, i, view, latex)
            if text.strip():
                lines.append(text.rstrip())
        else:
            i += 1
    view.text = "\n".join(lines).strip()
    return view


def _span_end(records: list[Record], start: int) -> int:
    """records[start]의 하위 레코드가 끝나는 인덱스(exclusive)."""
    base = records[start].level
    j = start + 1
    while j < len(records) and records[j].level > base:
        j += 1
    return j


def _render_para(blob: bytes, records: list[Record], start: int, view: ProblemView,
                 latex: bool = False):
    """PARA_HEADER 하나(하위 포함)를 텍스트로 만든다. (text, 다음 인덱스) 반환."""
    para_level = records[start].level
    end = _span_end(records, start)

    text_payloads: list[bytes] = []
    ctrls: list[int] = []  # 이 문단의 직계 CTRL_HEADER 인덱스들
    j = start + 1
    while j < end:
        rec = records[j]
        if rec.level == para_level + 1:
            if rec.tag == HWPTAG_PARA_TEXT:
                text_payloads.append(rec.payload(blob))
            elif rec.tag == HWPTAG_CTRL_HEADER:
                ctrls.append(j)
        j += 1

    blocks: list[str] = []  # 표/글상자처럼 문단 뒤에 붙일 블록들
    out: list[str] = []
    k = 0  # 앵커 ↔ 컨트롤 짝 맞추기용

    for payload in text_payloads:
        n = len(payload) // 2
        chars = struct.unpack(f"<{n}H", payload[: n * 2])
        p = 0
        while p < n:
            c = chars[p]
            if c in CTRL_ANCHOR_CODES:
                if k < len(ctrls):
                    inline, block = _render_ctrl(blob, records, ctrls[k], view, latex)
                    out.append(inline)
                    if block:
                        blocks.append(block)
                    k += 1
                p += 8
            elif c in INLINE8_CODES:
                if c == 9:
                    out.append("\t")
                p += 8
            elif c < 32:
                if c in (10, 13):
                    out.append("\n")
                p += 1
            else:
                out.append(chr(c))
                p += 1

    text = "".join(out)
    if blocks:
        text = text.rstrip("\n") + "\n" + "\n".join(blocks)
    return text, end


def _render_ctrl(blob: bytes, records: list[Record], idx: int, view: ProblemView,
                 latex: bool = False):
    """CTRL_HEADER 하나를 (인라인 문자열, 블록 문자열) 로 렌더링."""
    cid = ctrl_id(records[idx].payload(blob))
    end = _span_end(records, idx)

    if cid == "eqed":
        for j in range(idx + 1, end):
            if records[j].tag == HWPTAG_EQEDIT:
                script = _eq_script(records[j].payload(blob))
                if latex:
                    from .eqscript import to_latex

                    return f" \\({to_latex(script)}\\) ", ""
                return f"⟨{script}⟩", ""
        return "⟨수식⟩", ""

    if cid in ("tbl ", "gso "):
        pictures = [
            records[j] for j in range(idx + 1, end)
            if records[j].tag == HWPTAG_SHAPE_PICTURE
        ]
        for pic in pictures:
            payload = pic.payload(blob)
            if len(payload) >= PICTURE_BINID_OFFSET + 2:
                (bin_id,) = struct.unpack_from("<H", payload, PICTURE_BINID_OFFSET)
                if bin_id:
                    view.image_bin_ids.append(bin_id)

        # 내부 문단들(가장 얕은 층만 — 더 깊은 중첩은 재귀가 처리)
        inner_levels = [
            records[j].level for j in range(idx + 1, end)
            if records[j].tag == HWPTAG_PARA_HEADER
        ]
        inner_texts: list[str] = []
        if inner_levels:
            shallowest = min(inner_levels)
            j = idx + 1
            while j < end:
                if records[j].tag == HWPTAG_PARA_HEADER and records[j].level == shallowest:
                    text, j = _render_para(blob, records, j, view, latex)
                    if text.strip():
                        inner_texts.append(text.strip())
                else:
                    j += 1

        if pictures and not inner_texts:
            return f"[그림{len(view.image_bin_ids)}]", ""
        if inner_texts:
            open_, close = ("【", "】") if cid == "tbl " else ("〔", "〕")
            marker = "[그림]" if pictures else ""
            return marker, open_ + "  ".join(inner_texts) + close
        return "[도형]" if cid == "gso " else "[표]", ""

    return "", ""  # 구역 정의·쪽번호 등 레이아웃 컨트롤


def _eq_script(payload: bytes) -> str:
    (n,) = struct.unpack_from("<H", payload, 4)
    script = payload[6 : 6 + n * 2].decode("utf-16-le", errors="replace")
    return script.replace("`", " ").strip()
