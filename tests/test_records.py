import struct

import pytest

from mathenger.hwp.records import (
    extract_text,
    pack_record,
    parse_records,
    set_divide_sort,
)


def test_parse_roundtrip_simple():
    blob = pack_record(66, 0, b"\x01" * 24) + pack_record(67, 1, b"\x41\x00\x0d\x00")
    records = parse_records(blob)
    assert [(r.tag, r.level, r.size) for r in records] == [(66, 0, 24), (67, 1, 4)]
    assert b"".join(r.raw(blob) for r in records) == blob


def test_parse_extended_size():
    payload = b"\x00" * 5000  # 0xFFF 이상 → 확장 헤더
    blob = pack_record(67, 1, payload)
    (rec,) = parse_records(blob)
    assert rec.size == 5000
    assert rec.header_len == 8
    assert rec.payload(blob) == payload


def test_parse_rejects_truncated():
    blob = pack_record(66, 0, b"\x00" * 24)[:-3]
    with pytest.raises(ValueError):
        parse_records(blob)


def _utf16(*codes):
    return b"".join(struct.pack("<H", c) for c in codes)


def test_extract_text_skips_extended_controls():
    # 탭(9)과 개체 앵커(11)는 8워드를 차지한다
    payload = _utf16(ord("가")) + _utf16(9, 0, 0, 0, 0, 0, 0, 0) + _utf16(ord("나"), 13)
    assert extract_text(payload) == "가\t나\n"

    payload = _utf16(11, 0, 0, 0, 0, 0, 0, 0) + _utf16(ord("A"))
    assert extract_text(payload) == "A"


def test_set_divide_sort():
    header_payload = bytearray(24)
    blob = pack_record(66, 0, bytes(header_payload)) + pack_record(67, 1, _utf16(13))
    out = set_divide_sort(blob, 0x08)
    records = parse_records(out)
    assert records[0].payload(out)[11] == 0x08
    # 나머지 바이트는 그대로
    assert out[: 4 + 11] == blob[: 4 + 11]
    assert out[4 + 12 :] == blob[4 + 12 :]


def test_dedupe_para_instance_ids():
    from mathenger.hwp.builder import _dedupe_para_instance_ids

    def para(instance_id):
        payload = bytearray(24)
        struct.pack_into("<I", payload, 18, instance_id)
        return pack_record(66, 0, bytes(payload))

    section = para(100) + para(100) + para(101) + para(100)
    out = _dedupe_para_instance_ids(section)
    records = parse_records(out)
    ids = [struct.unpack_from("<I", r.payload(out), 18)[0] for r in records]
    assert ids[0] == 100          # 첫 등장 유지
    assert ids[2] == 101          # 원본 유지
    assert len(set(ids)) == 4     # 전부 고유
    assert 102 not in (100, 101)  # 새 ID는 기존과 충돌하지 않음
