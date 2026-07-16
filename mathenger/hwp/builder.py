"""선택한 문제 블록들로 새 HWP(학습지)를 조립한다.

핵심 원리: 원본 파일의 FileHeader/DocInfo/BinData/기타 스트림을 그대로
복사하고 BodyText/Section0만 새로 구성한다. 문제 블록은 원본 레코드
바이트를 그대로 이어 붙이므로 글자 모양·문단 모양·수식·표·그림 참조가
전부 유효하게 유지된다 (DocInfo가 동일하기 때문).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .cfb import CfbWriter
from .reader import HwpSource
from .records import (
    DIVIDE_COLUMN,
    DIVIDE_PAGE,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_TEXT,
    pack_record,
    parse_records,
    set_divide_sort,
)

# 문제 사이 구분 방식
SEP_COLUMN = "column"  # 각 문제를 새 단에서 시작 (원본과 같은 2단 배치에 적합)
SEP_PAGE = "page"  # 각 문제를 새 쪽에서 시작
SEP_SPACING = "spacing"  # 빈 문단 몇 개로 간격만 두기


@dataclass
class WorksheetOptions:
    separator: str = SEP_COLUMN
    spacing: int = 2  # SEP_SPACING일 때 삽입할 빈 문단 수 / 그 외에는 문제 뒤 여백
    numbering: bool = False  # 문제 앞에 "1." 번호 문단 삽입 (원본에 번호가 없을 때)
    number_format: str = "{n}."
    answer_page: bool = False  # 문서 끝에 '정답 및 해설' 페이지(새 쪽) 추가
    source_label: bool = False  # 문제 위에 작고 흐린 출처 표시


@dataclass
class LabelStyle:
    """출처 라벨 문단에 쓸 글자·문단 모양 ID (DocInfo에 미리 추가된 것)."""

    char_shape_id: int
    para_shape_id: int


def build_section(
    prologue: bytes,
    problem_blobs: list[bytes],
    empty_para: bytes,
    options: WorksheetOptions | None = None,
    source_labels: list[str] | None = None,
    label_style: LabelStyle | None = None,
) -> bytes:
    """선택한 문제 블록들로 새 본문(Section) 레코드 스트림을 만든다."""
    options = options or WorksheetOptions()
    if not problem_blobs:
        raise ValueError("선택된 문제가 없습니다.")

    divide_flag = {SEP_COLUMN: DIVIDE_COLUMN, SEP_PAGE: DIVIDE_PAGE}.get(options.separator)
    use_labels = options.source_label and source_labels and label_style and empty_para

    body = bytearray(prologue)
    for i, blob in enumerate(problem_blobs):
        chunk = bytearray()
        if use_labels:
            chunk += _make_text_para(
                empty_para, source_labels[i],
                char_shape_id=label_style.char_shape_id,
                para_shape_id=label_style.para_shape_id,
            )
        if options.numbering and empty_para:
            chunk += _make_text_para(empty_para, options.number_format.format(n=i + 1))
        chunk += blob
        if i > 0 and divide_flag:
            # 문제 묶음(라벨·번호 포함)의 첫 문단에 나눔 플래그를 건다
            chunk = bytearray(set_divide_sort(bytes(chunk), divide_flag))
        body += chunk
        if options.separator == SEP_SPACING and empty_para:
            body += empty_para * max(0, options.spacing)

    if options.answer_page and empty_para:
        body += _make_answer_page(empty_para, len(problem_blobs))

    section = _dedupe_para_instance_ids(bytes(body))
    section = _mark_last_paragraph(section)
    # 조립 결과가 올바른 레코드 스트림인지 검증 (깨진 파일 생성 방지)
    parse_records(section)
    return section


def _mark_last_paragraph(section: bytes) -> bytes:
    """최상위 문단 리스트의 종결 표시를 바로잡는다.

    PARA_HEADER 첫 UINT32의 최상위 비트(0x80000000)는 '문단 리스트의
    마지막 문단' 표시다. 한글은 이 종결 표시가 없는(또는 중간에 잘못
    있는) 문서를 '손상된 파일'로 거부한다. 문서 중간에서 잘라 온
    문단들로 조립하므로, 마지막 최상위 문단에만 표시를 세우고 나머지는
    지운다. (표/글상자 안 문단 리스트는 블록 안에 원본 그대로 보존되어
    이미 올바르다.)
    """
    records = parse_records(section)
    tops = [r for r in records if r.tag == HWPTAG_PARA_HEADER and r.level == 0]
    if not tops:
        return section
    out = bytearray(section)
    for i, rec in enumerate(tops):
        off = rec.pos + rec.header_len
        (value,) = struct.unpack_from("<I", out, off)
        if i == len(tops) - 1:
            value |= 0x80000000
        else:
            value &= 0x7FFFFFFF
        struct.pack_into("<I", out, off, value)
    return bytes(out)


def _dedupe_para_instance_ids(section: bytes) -> bytes:
    """복제로 생긴 중복 문단 instance ID에 새 고유값을 발급한다.

    간격용 빈 문단이나 번호 문단은 같은 템플릿을 복제해 넣므로 문단
    고유 번호(PARA_HEADER +18의 UINT32)가 중복된다. 한글은 문단 고유
    번호가 중복된 문서를 '손상된 파일'로 거부하므로, 두 번째 이후
    등장하는 중복 ID를 문서 안에서 유일한 값으로 바꾼다. 원본에서 온
    문단들의 ID는 그대로 둔다 (첫 등장은 유지).
    """
    records = parse_records(section)
    headers = [r for r in records if r.tag == HWPTAG_PARA_HEADER]
    out = bytearray(section)
    used = {
        struct.unpack_from("<I", out, r.pos + r.header_len + 18)[0] for r in headers
    }
    seen: set[int] = set()
    for rec in headers:
        off = rec.pos + rec.header_len + 18
        (instance_id,) = struct.unpack_from("<I", out, off)
        if instance_id in seen:
            fresh = (instance_id + 1) & 0xFFFFFFFF
            while fresh in used:
                fresh = (fresh + 1) & 0xFFFFFFFF
            struct.pack_into("<I", out, off, fresh)
            used.add(fresh)
            seen.add(fresh)
        else:
            seen.add(instance_id)
    return bytes(out)


def build_worksheet(
    source: HwpSource,
    prologue: bytes,
    problem_blobs: list[bytes],
    empty_para: bytes,
    options: WorksheetOptions | None = None,
    preview_texts: list[str] | None = None,
) -> bytes:
    """컨테이너를 새로 써서 학습지 HWP를 만든다 (실험적 경로).

    한글의 컨테이너 파서 호환성이 완전히 검증되지 않아, 실제 생성은
    patcher.patch_streams(원본 제자리 패치)를 쓰는 쪽을 권장한다.
    """
    section = build_section(prologue, problem_blobs, empty_para, options)

    writer = CfbWriter(root_clsid=source.root_clsid)
    written = set()

    def put(name: str, data: bytes) -> None:
        writer.add_stream(name, data)
        written.add(name)

    put("FileHeader", source.streams["FileHeader"])
    put("BodyText/Section0", source.compress_body(section))
    if preview_texts is not None:
        put("PrvText", make_prvtext(preview_texts))
        written.add("PrvText")

    for name, data in source.streams.items():
        if name in written or name.startswith("BodyText/Section"):
            continue
        if name == "PrvText" and preview_texts is not None:
            continue
        writer.add_stream(name, data)

    return writer.tobytes()


def _make_answer_page(empty_para: bytes, n_problems: int) -> bytes:
    """새 쪽에서 시작하는 '정답 및 해설' 페이지를 만든다.

    제목 문단에 쪽 나누기 플래그를 걸고, 문제마다 번호 문단과 답을 적을
    빈 문단을 넣는다. (출처는 학습지 본문 쪽 라벨에서 표시하므로 제외)
    """
    title = _make_text_para(empty_para, "[ 정답 및 해설 ]")
    out = bytearray(set_divide_sort(title, DIVIDE_PAGE))
    out += empty_para
    for n in range(n_problems):
        out += _make_text_para(empty_para, f"{n + 1}.")
        out += empty_para * 2  # 답과 풀이를 적을 공간
    return bytes(out)


# PARA_HEADER 페이로드 오프셋: paraShapeId(u2)=8, charShapeCount(u2)=12
_PS_PARASHAPE_OFF = 8
_PS_CHARCOUNT_OFF = 12


def _make_text_para(
    empty_para_template: bytes,
    text: str,
    char_shape_id: int | None = None,
    para_shape_id: int | None = None,
) -> bytes:
    """빈 문단 템플릿을 복제해 짧은 텍스트 문단을 만든다.

    char_shape_id/para_shape_id를 주면 그 글자·문단 모양을 적용한다
    (출처 라벨처럼 작고 흐린 오른쪽정렬 문단용). 없으면 템플릿 모양을
    그대로 물려받는다.
    """
    records = parse_records(empty_para_template)
    chars = text + "\r"
    payload = chars.encode("utf-16-le")
    out = bytearray()
    inserted = False
    for rec in records:
        raw = rec.raw(empty_para_template)
        if rec.tag == HWPTAG_PARA_HEADER:
            hdr = bytearray(raw)
            base = rec.header_len
            (old,) = struct.unpack_from("<I", hdr, base)
            struct.pack_into("<I", hdr, base, (old & 0x80000000) | len(chars))
            if para_shape_id is not None:
                struct.pack_into("<H", hdr, base + _PS_PARASHAPE_OFF, para_shape_id)
            if char_shape_id is not None:
                struct.pack_into("<H", hdr, base + _PS_CHARCOUNT_OFF, 1)
            out += hdr
            out += pack_record(HWPTAG_PARA_TEXT, rec.level + 1, payload)
            inserted = True
        elif rec.tag == HWPTAG_PARA_TEXT:
            continue  # 템플릿에 있었다면 교체됨
        elif rec.tag == HWPTAG_PARA_CHAR_SHAPE and char_shape_id is not None:
            # 문단 전체를 지정 글자 모양으로: (위치0, charShapeId) 한 쌍
            out += pack_record(
                HWPTAG_PARA_CHAR_SHAPE, rec.level,
                struct.pack("<II", 0, char_shape_id),
            )
        else:
            out += raw
    if not inserted:
        raise ValueError("템플릿에 PARA_HEADER가 없습니다.")
    return bytes(out)


def make_prvtext(texts: list[str], limit: int = 1000) -> bytes:
    joined = "\r\n".join(t.strip() for t in texts if t.strip())
    return joined[:limit].encode("utf-16-le")
