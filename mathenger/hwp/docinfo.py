"""DocInfo에 '작고 흐린 오른쪽정렬' 글자·문단 모양을 추가한다.

출처 라벨(문제 위 오른쪽에 작게 표시)을 넣으려면 그 스타일에 해당하는
CHAR_SHAPE(작은 회색 글자)와 PARA_SHAPE(오른쪽 정렬)가 DocInfo에 있어야
한다. 기존 모양을 복제·수정해 새 모양으로 추가하고 새 ID를 돌려준다.
"""

from __future__ import annotations

import struct

from .records import parse_records, pack_record

HWPTAG_ID_MAPPINGS = 17
HWPTAG_CHAR_SHAPE = 21
HWPTAG_PARA_SHAPE = 25

# ID_MAPPINGS 배열 내 항목 위치 (각 SInt4)
IDMAP_CHAR_SHAPE = 9
IDMAP_PARA_SHAPE = 13

# CHAR_SHAPE 페이로드 오프셋
CS_BASE_SIZE = 42  # SInt4, 1/100 pt (예: 700 = 7pt)
CS_CHAR_COLOR = 52  # UInt4 COLORREF 0x00BBGGRR

LABEL_SIZE = 700  # 7pt
LABEL_COLOR = 0x00999999  # 흐린 회색
ALIGN_RIGHT = 2  # PARA_SHAPE property1 bits 2~4


def augment_for_source_label(docinfo: bytes) -> tuple[bytes, int, int]:
    """(새 DocInfo, char_shape_id, para_shape_id)를 돌려준다."""
    records = parse_records(docinfo)

    idmap = _find(records, HWPTAG_ID_MAPPINGS)
    char_records = [r for r in records if r.tag == HWPTAG_CHAR_SHAPE]
    para_records = [r for r in records if r.tag == HWPTAG_PARA_SHAPE]
    if not idmap or not char_records or not para_records:
        raise ValueError("DocInfo에서 필요한 모양 레코드를 찾지 못했습니다.")

    counts = _read_counts(docinfo, idmap)
    char_id = counts[IDMAP_CHAR_SHAPE]
    para_id = counts[IDMAP_PARA_SHAPE]

    # 새 글자 모양: 첫 글자 모양을 복제해 크기·색만 변경
    cs_payload = bytearray(char_records[0].payload(docinfo))
    struct.pack_into("<i", cs_payload, CS_BASE_SIZE, LABEL_SIZE)
    struct.pack_into("<I", cs_payload, CS_CHAR_COLOR, LABEL_COLOR)
    new_char = pack_record(HWPTAG_CHAR_SHAPE, char_records[0].level, bytes(cs_payload))

    # 새 문단 모양: 첫 문단 모양을 복제해 오른쪽 정렬로 변경
    ps_payload = bytearray(para_records[0].payload(docinfo))
    (prop1,) = struct.unpack_from("<I", ps_payload, 0)
    prop1 = (prop1 & ~(0b111 << 2)) | (ALIGN_RIGHT << 2)
    struct.pack_into("<I", ps_payload, 0, prop1)
    new_para = pack_record(HWPTAG_PARA_SHAPE, para_records[0].level, bytes(ps_payload))

    last_char_end = char_records[-1].end
    last_para_end = para_records[-1].end

    # 그룹 순서를 지키려고 각 모양의 마지막 레코드 뒤에 새 레코드를 끼운다
    new_idmap = _bump_counts(docinfo, idmap)
    out = bytearray()
    for rec in records:
        if rec is idmap:
            out += new_idmap
        else:
            out += rec.raw(docinfo)
        if rec.end == last_char_end and rec.tag == HWPTAG_CHAR_SHAPE:
            out += new_char
        if rec.end == last_para_end and rec.tag == HWPTAG_PARA_SHAPE:
            out += new_para

    return bytes(out), char_id, para_id


def _find(records, tag):
    for r in records:
        if r.tag == tag:
            return r
    return None


def _read_counts(docinfo: bytes, idmap) -> list[int]:
    p = idmap.payload(docinfo)
    n = len(p) // 4
    return list(struct.unpack(f"<{n}i", p[: n * 4]))


def _bump_counts(docinfo: bytes, idmap) -> bytes:
    payload = bytearray(idmap.payload(docinfo))
    for idx in (IDMAP_CHAR_SHAPE, IDMAP_PARA_SHAPE):
        (v,) = struct.unpack_from("<i", payload, idx * 4)
        struct.pack_into("<i", payload, idx * 4, v + 1)
    return pack_record(HWPTAG_ID_MAPPINGS, idmap.level, bytes(payload))
