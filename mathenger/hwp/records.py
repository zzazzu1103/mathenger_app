"""HWP 5.0 레코드 파싱 유틸리티.

HWP 5.0의 DocInfo/BodyText 스트림은 (tag, level, size) 헤더를 가진
레코드의 연속이다. 여기서는 레코드를 바이트 그대로 보존하면서
경계와 문단 텍스트만 해석한다 — 수식(EQEDIT)·표·그림 등 개체의
내용은 절대 재해석하지 않으므로 재조립 시 깨질 여지가 없다.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# 본문(BodyText) 레코드 태그
HWPTAG_PARA_HEADER = 66
HWPTAG_PARA_TEXT = 67
HWPTAG_PARA_CHAR_SHAPE = 68
HWPTAG_PARA_LINE_SEG = 69
HWPTAG_CTRL_HEADER = 71

# 문단 텍스트에서 8워드(16바이트)를 차지하는 제어 문자들.
# (1~9: 확장/인라인 컨트롤, 11~12, 14~23 포함. 10/13/24~31은 1워드)
EXTENDED_CONTROL_CHARS = frozenset(
    list(range(1, 10)) + [11, 12] + list(range(14, 24))
)

# PARA_HEADER 페이로드 내 "나눔 종류" 바이트 오프셋과 비트
DIVIDE_SORT_OFFSET = 11
DIVIDE_SECTION = 0x01  # 구역 나누기
DIVIDE_MULTI_COLUMN = 0x02  # 다단 나누기
DIVIDE_PAGE = 0x04  # 쪽 나누기
DIVIDE_COLUMN = 0x08  # 단 나누기


@dataclass(frozen=True)
class Record:
    pos: int  # 스트림 내 시작 오프셋(헤더 포함)
    tag: int
    level: int
    size: int  # 페이로드 크기
    header_len: int  # 4 또는 8 (확장 크기)

    @property
    def end(self) -> int:
        return self.pos + self.header_len + self.size

    def payload(self, data: bytes) -> bytes:
        start = self.pos + self.header_len
        return data[start : start + self.size]

    def raw(self, data: bytes) -> bytes:
        return data[self.pos : self.end]


def parse_records(data: bytes) -> list[Record]:
    """스트림 전체를 레코드 목록으로 파싱한다."""
    records: list[Record] = []
    pos = 0
    n = len(data)
    while pos < n:
        if pos + 4 > n:
            raise ValueError(f"잘린 레코드 헤더 (offset {pos})")
        (header,) = struct.unpack_from("<I", data, pos)
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        header_len = 4
        if size == 0xFFF:  # 확장 크기
            (size,) = struct.unpack_from("<I", data, pos + 4)
            header_len = 8
        if pos + header_len + size > n:
            raise ValueError(f"레코드가 스트림 밖을 가리킴 (offset {pos})")
        records.append(Record(pos, tag, level, size, header_len))
        pos += header_len + size
    return records


def pack_record(tag: int, level: int, payload: bytes) -> bytes:
    """레코드 바이트를 생성한다 (크기에 따라 확장 헤더 사용)."""
    size = len(payload)
    if size < 0xFFF:
        header = (tag & 0x3FF) | ((level & 0x3FF) << 10) | (size << 20)
        return struct.pack("<I", header) + payload
    header = (tag & 0x3FF) | ((level & 0x3FF) << 10) | (0xFFF << 20)
    return struct.pack("<II", header, size) + payload


def extract_text(para_text_payload: bytes) -> str:
    """PARA_TEXT 페이로드에서 사람이 읽을 텍스트만 뽑는다.

    제어 문자(수식·개체 앵커 등)는 건너뛴다. 검색/미리보기 용도.
    """
    n = len(para_text_payload) // 2
    chars = struct.unpack(f"<{n}H", para_text_payload[: n * 2])
    out: list[str] = []
    i = 0
    while i < n:
        c = chars[i]
        if c in EXTENDED_CONTROL_CHARS:
            if c == 9:
                out.append("\t")
            i += 8
        elif c < 32:
            if c in (10, 13):
                out.append("\n")
            i += 1
        else:
            out.append(chr(c))
            i += 1
    return "".join(out)


def ctrl_id(ctrl_header_payload: bytes) -> str:
    """CTRL_HEADER 페이로드의 컨트롤 ID를 'secd' 같은 문자열로 돌려준다."""
    (raw,) = struct.unpack_from("<I", ctrl_header_payload, 0)
    return struct.pack(">I", raw).decode("ascii", errors="replace")


def set_divide_sort(para_header_raw: bytes, flags: int) -> bytes:
    """PARA_HEADER 레코드(raw)의 나눔 종류 바이트에 플래그를 OR 한다."""
    records = parse_records(para_header_raw)
    rec = records[0]
    if rec.tag != HWPTAG_PARA_HEADER:
        raise ValueError("PARA_HEADER 레코드가 아님")
    offset = rec.pos + rec.header_len + DIVIDE_SORT_OFFSET
    out = bytearray(para_header_raw)
    out[offset] |= flags
    return bytes(out)
