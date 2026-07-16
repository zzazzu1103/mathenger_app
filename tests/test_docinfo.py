import struct

from mathenger.hwp.docinfo import (
    IDMAP_CHAR_SHAPE, IDMAP_PARA_SHAPE, augment_for_source_label,
)
from mathenger.hwp.records import pack_record, parse_records


def _fake_docinfo():
    # ID_MAPPINGS(17): 18개 카운트, CharShape=2, ParaShape=1
    counts = [0] * 18
    counts[IDMAP_CHAR_SHAPE] = 2
    counts[IDMAP_PARA_SHAPE] = 1
    idmap = pack_record(17, 0, struct.pack("<18i", *counts))
    char0 = pack_record(21, 0, bytes(74))
    char1 = pack_record(21, 0, bytes(74))
    para0 = pack_record(25, 0, bytes(58))
    return idmap + char0 + char1 + para0


def test_augment_adds_shapes():
    di = _fake_docinfo()
    new_di, char_id, para_id = augment_for_source_label(di)
    assert char_id == 2 and para_id == 1  # 새 ID = 기존 개수

    recs = parse_records(new_di)
    assert sum(1 for r in recs if r.tag == 21) == 3
    assert sum(1 for r in recs if r.tag == 25) == 2

    idmap = next(r for r in recs if r.tag == 17)
    counts = struct.unpack_from("<18i", idmap.payload(new_di), 0)
    assert counts[IDMAP_CHAR_SHAPE] == 3
    assert counts[IDMAP_PARA_SHAPE] == 2

    # 새 글자 모양: 7pt 회색
    new_char = [r for r in recs if r.tag == 21][-1].payload(new_di)
    assert struct.unpack_from("<i", new_char, 42)[0] == 700
    assert struct.unpack_from("<I", new_char, 52)[0] == 0x00999999
    # 새 문단 모양: 오른쪽 정렬(비트 2~4 = 2)
    new_para = [r for r in recs if r.tag == 25][-1].payload(new_di)
    assert ((struct.unpack_from("<I", new_para, 0)[0] >> 2) & 0b111) == 2
