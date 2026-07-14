"""최소 기능의 OLE2/CFB(복합 파일 바이너리) 라이터.

HWP 5.0 컨테이너를 쓰기 위한 용도. v3 형식(512바이트 섹터)로 기록하며
4096바이트 미만 스트림은 미니 스트림에 배치한다. FAT 섹터가 109개
이하(대략 50MB)인 파일만 지원한다 — 학습지 용도로는 충분하다.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SECTOR = 512
MINI_SECTOR = 64
MINI_CUTOFF = 4096

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD

TYPE_STORAGE = 1
TYPE_STREAM = 2
TYPE_ROOT = 5

NOSTREAM = 0xFFFFFFFF


@dataclass
class _Entry:
    name: str
    type: int
    clsid: bytes = b"\x00" * 16
    data: bytes = b""
    children: dict[str, "_Entry"] = field(default_factory=dict)
    # 배치 결과
    sid: int = -1
    start_sector: int = ENDOFCHAIN
    left: int = NOSTREAM
    right: int = NOSTREAM
    child: int = NOSTREAM


def _name_key(name: str):
    # CFB 정렬 규칙: 이름 길이 우선, 그다음 대문자 비교
    return (len(name), name.upper())


class CfbWriter:
    def __init__(self, root_clsid: bytes = b"\x00" * 16):
        self._root = _Entry("Root Entry", TYPE_ROOT, clsid=root_clsid)

    def add_stream(self, path: str, data: bytes) -> None:
        """'BinData/BIN0001.jpg' 같은 경로로 스트림을 추가한다."""
        parts = path.split("/")
        node = self._root
        for part in parts[:-1]:
            if part not in node.children:
                node.children[part] = _Entry(part, TYPE_STORAGE)
            node = node.children[part]
            if node.type != TYPE_STORAGE:
                raise ValueError(f"스트림 아래에 스트림을 만들 수 없음: {path}")
        leaf = parts[-1]
        if leaf in node.children:
            raise ValueError(f"중복 스트림: {path}")
        if len(leaf.encode("utf-16-le")) > 62:
            raise ValueError(f"이름이 너무 긺: {leaf}")
        node.children[leaf] = _Entry(leaf, TYPE_STREAM, data=data)

    def tobytes(self) -> bytes:
        entries = self._assign_sids()

        # ── 미니 스트림 구성 ────────────────────────────────
        mini_data = bytearray()
        minifat: list[int] = []
        big_streams: list[_Entry] = []
        for e in entries:
            if e.type != TYPE_STREAM:
                continue
            if len(e.data) < MINI_CUTOFF and len(e.data) > 0:
                start = len(minifat)
                n = -(-len(e.data) // MINI_SECTOR)
                mini_data += e.data
                if len(mini_data) % MINI_SECTOR:
                    mini_data += b"\x00" * (MINI_SECTOR - len(mini_data) % MINI_SECTOR)
                minifat += list(range(start + 1, start + n)) + [ENDOFCHAIN]
                e.start_sector = start
            elif len(e.data) == 0:
                e.start_sector = ENDOFCHAIN
            else:
                big_streams.append(e)

        mini_bytes = bytes(mini_data)
        minifat_sectors = -(-len(minifat) * 4 // SECTOR) if minifat else 0

        dir_count = len(entries)
        dir_sectors = -(-dir_count * 128 // SECTOR)

        ministream_sectors = -(-len(mini_bytes) // SECTOR)
        big_sector_counts = [-(-len(e.data) // SECTOR) for e in big_streams]
        data_sectors = ministream_sectors + sum(big_sector_counts)

        # FAT 섹터 수 고정점 계산
        fat_sectors = 0
        while True:
            total = fat_sectors + dir_sectors + minifat_sectors + data_sectors
            need = -(-total // 128)
            if need == fat_sectors:
                break
            fat_sectors = need
        if fat_sectors > 109:
            raise ValueError("파일이 너무 큽니다 (DIFAT 미지원)")

        # 섹터 배치: [FAT][DIR][MINIFAT][MINISTREAM][BIG...]
        fat_start = 0
        dir_start = fat_start + fat_sectors
        minifat_start = dir_start + dir_sectors
        ministream_start = minifat_start + minifat_sectors
        big_start = ministream_start + ministream_sectors
        total_sectors = big_start + sum(big_sector_counts)

        fat = [FREESECT] * (fat_sectors * 128)
        for i in range(fat_sectors):
            fat[fat_start + i] = FATSECT

        def chain(start: int, count: int) -> None:
            for i in range(count):
                fat[start + i] = start + i + 1 if i + 1 < count else ENDOFCHAIN

        chain(dir_start, dir_sectors)
        if minifat_sectors:
            chain(minifat_start, minifat_sectors)
        if ministream_sectors:
            chain(ministream_start, ministream_sectors)

        pos = big_start
        for e, n in zip(big_streams, big_sector_counts):
            e.start_sector = pos
            chain(pos, n)
            pos += n

        self._root.start_sector = ministream_start if ministream_sectors else ENDOFCHAIN
        self._root.data = mini_bytes  # 크기 기록용

        # ── 헤더 ────────────────────────────────────────────
        header = bytearray(512)
        header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        struct.pack_into("<H", header, 24, 0x003E)
        struct.pack_into("<H", header, 26, 0x0003)
        struct.pack_into("<H", header, 28, 0xFFFE)
        struct.pack_into("<H", header, 30, 9)
        struct.pack_into("<H", header, 32, 6)
        struct.pack_into("<I", header, 40, 0)  # num dir sectors (v3: 0)
        struct.pack_into("<I", header, 44, fat_sectors)
        struct.pack_into("<I", header, 48, dir_start)
        struct.pack_into("<I", header, 52, 0)  # transaction signature
        struct.pack_into("<I", header, 56, MINI_CUTOFF)
        struct.pack_into("<I", header, 60, minifat_start if minifat_sectors else ENDOFCHAIN)
        struct.pack_into("<I", header, 64, minifat_sectors)
        struct.pack_into("<I", header, 68, ENDOFCHAIN)  # first DIFAT sector
        struct.pack_into("<I", header, 72, 0)  # num DIFAT sectors
        for i in range(109):
            struct.pack_into("<I", header, 76 + i * 4,
                             fat_start + i if i < fat_sectors else FREESECT)

        # ── 본문 섹터 조립 ──────────────────────────────────
        out = bytearray(header)
        out += b"".join(struct.pack("<I", v) for v in fat)

        dir_bytes = bytearray()
        for e in entries:
            dir_bytes += self._pack_entry(e)
        dir_bytes += b"\x00" * (dir_sectors * SECTOR - len(dir_bytes))
        out += dir_bytes

        if minifat_sectors:
            mf = b"".join(struct.pack("<I", v) for v in minifat)
            mf += b"\xff" * (minifat_sectors * SECTOR - len(mf))
            out += mf

        if ministream_sectors:
            padded = mini_bytes + b"\x00" * (ministream_sectors * SECTOR - len(mini_bytes))
            out += padded

        for e in big_streams:
            n = -(-len(e.data) // SECTOR)
            out += e.data + b"\x00" * (n * SECTOR - len(e.data))

        assert len(out) == 512 + total_sectors * SECTOR
        return bytes(out)

    # ── 디렉터리 트리 ───────────────────────────────────────
    def _assign_sids(self) -> list[_Entry]:
        """루트부터 순회하며 SID를 부여하고 형제 BST를 구성한다."""
        entries: list[_Entry] = []

        def visit(node: _Entry) -> None:
            node.sid = len(entries)
            entries.append(node)
            kids = sorted(node.children.values(), key=lambda c: _name_key(c.name))
            for kid in kids:
                visit(kid)
            node.child = self._build_bst(kids)

        visit(self._root)
        return entries

    @staticmethod
    def _build_bst(sorted_children: list[_Entry]) -> int:
        """정렬된 형제 목록으로 균형 BST를 만들고 루트 SID를 돌려준다."""
        def build(lo: int, hi: int) -> int:
            if lo > hi:
                return NOSTREAM
            mid = (lo + hi) // 2
            node = sorted_children[mid]
            node.left = build(lo, mid - 1)
            node.right = build(mid + 1, hi)
            return node.sid

        return build(0, len(sorted_children) - 1)

    @staticmethod
    def _pack_entry(e: _Entry) -> bytes:
        name_utf16 = e.name.encode("utf-16-le")
        buf = bytearray(128)
        buf[0 : len(name_utf16)] = name_utf16
        struct.pack_into("<H", buf, 64, len(name_utf16) + 2)
        buf[66] = e.type
        buf[67] = 1  # black
        struct.pack_into("<I", buf, 68, e.left)
        struct.pack_into("<I", buf, 72, e.right)
        struct.pack_into("<I", buf, 76, e.child)
        buf[80:96] = e.clsid
        if e.type == TYPE_STORAGE:
            start, size = 0, 0
        else:  # 스트림 또는 루트(미니 스트림)
            size = len(e.data)
            start = e.start_sector if size else ENDOFCHAIN
        struct.pack_into("<I", buf, 116, start)
        struct.pack_into("<Q", buf, 120, size)
        return bytes(buf)
