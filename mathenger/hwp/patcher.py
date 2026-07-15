"""원본 OLE 컨테이너를 구조 변경 최소화로 '제자리 패치'한다.

새 컨테이너를 처음부터 쓰는 대신, 한글이 정상적으로 여는 원본 파일의
바이트를 유지한 채 지정한 스트림의 내용을 교체한다. 두 가지 방식:

- 고정 크기(fixed): 새 내용을 기존 크기에 맞춰 0으로 채운다.
  구조는 전혀 바뀌지 않는다. (PrvText처럼 패딩이 무해한 스트림용)
- 크기 조정(resize): 디렉터리의 크기 필드를 새 값으로 바꾸고 FAT 체인을
  정석대로 줄인다(남는 섹터는 FREESECT). 스트림 끝이 정확히 새 내용
  끝이 된다. (압축 본문처럼 꼬리표 위치가 중요한 스트림용)

주의: OLE 규격상 4096바이트 미만 스트림은 미니 스트림에, 이상은 일반
섹터에 놓이며 **리더는 크기 필드로 위치를 판별**한다. 따라서 resize로
크기가 4096 경계를 넘나들면 안 된다 (PatchError).
"""

from __future__ import annotations

import struct

SECTOR = 512
MINI_SECTOR = 64
MINI_CUTOFF = 4096
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF


class PatchError(ValueError):
    pass


class PatchTooLarge(PatchError):
    """새 내용이 기존 스트림의 섹터 체인 용량보다 크다."""


class _Cfb:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise PatchError("OLE 파일이 아닙니다.")
        (self.sector_shift,) = struct.unpack_from("<H", data, 30)
        if self.sector_shift != 9:
            raise PatchError("512바이트 섹터(v3) 파일만 지원합니다.")
        (self.num_fat,) = struct.unpack_from("<I", data, 44)
        (self.first_dir,) = struct.unpack_from("<I", data, 48)
        (self.mini_cutoff,) = struct.unpack_from("<I", data, 56)
        (self.first_minifat,) = struct.unpack_from("<I", data, 60)
        (self.first_difat,) = struct.unpack_from("<I", data, 68)

        # DIFAT → FAT 섹터 목록 (FAT 항목 위치 역산에 필요해 보관)
        difat: list[int] = [
            struct.unpack_from("<I", data, 76 + i * 4)[0] for i in range(109)
        ]
        sid = self.first_difat
        while sid not in (ENDOFCHAIN, FREESECT):
            off = self._sector_off(sid)
            difat += struct.unpack_from("<127I", data, off)
            (sid,) = struct.unpack_from("<I", data, off + 508)
        self.fat_sectors = [s for s in difat if s not in (ENDOFCHAIN, FREESECT)]
        self.fat: list[int] = []
        for s in self.fat_sectors:
            self.fat += struct.unpack_from("<128I", data, self._sector_off(s))

        # 미니 FAT (항목 위치 역산용으로 섹터 체인도 보관)
        self.minifat_sectors = self._chain(self.first_minifat) if self.first_minifat not in (ENDOFCHAIN, FREESECT) else []
        self.minifat: list[int] = []
        for s in self.minifat_sectors:
            self.minifat += struct.unpack_from("<128I", data, self._sector_off(s))

        # 디렉터리 엔트리 (파일 오프셋 포함)
        self.entries: list[dict] = []
        sid = self.first_dir
        while sid not in (ENDOFCHAIN, FREESECT):
            off = self._sector_off(sid)
            for k in range(4):
                e = off + k * 128
                (name_len,) = struct.unpack_from("<H", data, e + 64)
                if name_len < 2:
                    self.entries.append({})
                    continue
                name = bytes(data[e : e + name_len - 2]).decode("utf-16-le")
                (start,) = struct.unpack_from("<I", data, e + 116)
                (size,) = struct.unpack_from("<Q", data, e + 120)
                self.entries.append(
                    {"name": name, "type": data[e + 66], "start": start,
                     "size": size, "offset": e}
                )
            sid = self.fat[sid]

        root = self.entries[0]
        self.mini_chain = self._chain(root["start"]) if root.get("size") else []

    def _sector_off(self, sid: int) -> int:
        return 512 + sid * SECTOR

    def _chain(self, start: int, table: list[int] | None = None) -> list[int]:
        table = self.fat if table is None else table
        chain = []
        sid = start
        while sid not in (ENDOFCHAIN, FREESECT):
            chain.append(sid)
            sid = table[sid]
            if len(chain) > len(table):
                raise PatchError("체인 순환")
        return chain

    def _mini_off(self, mini_sid: int) -> int:
        """미니 섹터 번호 → 파일 오프셋 (루트 미니 스트림 체인 경유)."""
        byte_off = mini_sid * MINI_SECTOR
        big = self.mini_chain[byte_off // SECTOR]
        return self._sector_off(big) + byte_off % SECTOR

    def _set_fat(self, index: int, value: int) -> None:
        self.fat[index] = value
        sector = self.fat_sectors[index // 128]
        off = self._sector_off(sector) + (index % 128) * 4
        struct.pack_into("<I", self.data, off, value)

    def _set_minifat(self, index: int, value: int) -> None:
        self.minifat[index] = value
        sector = self.minifat_sectors[index // 128]
        off = self._sector_off(sector) + (index % 128) * 4
        struct.pack_into("<I", self.data, off, value)

    def find_stream(self, name: str) -> dict:
        found = [e for e in self.entries if e.get("name") == name and e.get("type") == 2]
        if not found:
            raise PatchError(f"스트림을 찾을 수 없음: {name}")
        if len(found) > 1:
            raise PatchError(f"같은 이름의 스트림이 여러 개: {name}")
        return found[0]

    # ── 쓰기 ────────────────────────────────────────────────

    def _write_chunks(self, entry: dict, payload: bytes) -> None:
        """스트림의 (미니)섹터 체인에 payload를 앞에서부터 채운다."""
        if entry["size"] < self.mini_cutoff:
            chain = self._chain(entry["start"], self.minifat)
            piece = MINI_SECTOR
            offsets = [self._mini_off(s) for s in chain]
        else:
            chain = self._chain(entry["start"])
            piece = SECTOR
            offsets = [self._sector_off(s) for s in chain]
        for i, off in enumerate(offsets):
            part = payload[i * piece : (i + 1) * piece]
            if not part:
                part = b"\x00" * piece  # 남는 섹터는 0으로 청소
            elif len(part) < piece:
                part = part + b"\x00" * (piece - len(part))
            self.data[off : off + piece] = part

    def patch_fixed(self, name: str, new_data: bytes) -> None:
        """크기 필드 유지, 남는 공간은 0 패딩 (구조 무변경)."""
        entry = self.find_stream(name)
        if len(new_data) > entry["size"]:
            raise PatchTooLarge(
                f"'{name}' 새 내용({len(new_data):,}B)이 기존 크기({entry['size']:,}B)보다 큽니다."
            )
        self._write_chunks(entry, new_data + b"\x00" * (entry["size"] - len(new_data)))

    def patch_resize(self, name: str, new_data: bytes) -> None:
        """내용 교체 + 크기 필드 갱신 + 체인 축소. 4096 경계는 못 넘는다."""
        entry = self.find_stream(name)
        old_size = entry["size"]
        new_size = len(new_data)
        is_mini = old_size < self.mini_cutoff
        if is_mini != (new_size < self.mini_cutoff):
            raise PatchError(
                f"'{name}' 크기 {old_size:,}B → {new_size:,}B 변경은 미니/일반 스트림 "
                f"경계(4096B)를 넘어 지원하지 않습니다."
            )
        table_get = self.minifat if is_mini else self.fat
        set_entry = self._set_minifat if is_mini else self._set_fat
        piece = MINI_SECTOR if is_mini else SECTOR

        chain = self._chain(entry["start"], table_get if is_mini else None)
        capacity = len(chain) * piece
        if new_size > capacity:
            raise PatchTooLarge(
                f"'{name}' 새 내용({new_size:,}B)이 체인 용량({capacity:,}B)보다 큽니다."
            )

        keep = max(1, -(-new_size // piece))
        # 내용 쓰기 (남는 섹터 0 청소 포함)
        self._write_chunks(entry, new_data + b"\x00" * (old_size - new_size if old_size > new_size else 0))
        # 체인 축소
        if keep < len(chain):
            set_entry(chain[keep - 1], ENDOFCHAIN)
            for sid in chain[keep:]:
                set_entry(sid, FREESECT)
        # 디렉터리 크기 필드 갱신
        struct.pack_into("<Q", self.data, entry["offset"] + 120, new_size)
        entry["size"] = new_size


def stream_info(container: bytes, name: str) -> dict:
    """스트림의 size/용량/미니 여부를 알려준다 (패치 전 사전 점검용)."""
    cfb = _Cfb(container)
    entry = cfb.find_stream(name)
    is_mini = entry["size"] < cfb.mini_cutoff
    if is_mini:
        chain = cfb._chain(entry["start"], cfb.minifat)
        capacity = len(chain) * MINI_SECTOR
    else:
        chain = cfb._chain(entry["start"])
        capacity = len(chain) * SECTOR
    return {"size": entry["size"], "capacity": capacity, "is_mini": is_mini}


def patch_streams(
    container: bytes,
    replacements: dict[str, bytes],
    allow_truncate: set[str] | None = None,
    resize: set[str] | None = None,
) -> bytes:
    """원본 컨테이너에서 지정 스트림들의 내용만 교체한 사본을 돌려준다.

    - resize에 든 스트림: 크기 필드/체인까지 정확히 줄인다.
    - allow_truncate에 든 스트림: 공간이 모자라면 잘라서 넣는다.
    - 그 외: 기존 크기 유지, 0 패딩.
    """
    cfb = _Cfb(container)
    for name, data in replacements.items():
        if resize and name in resize:
            cfb.patch_resize(name, data)
            continue
        if allow_truncate and name in allow_truncate:
            data = data[: cfb.find_stream(name)["size"]]
        cfb.patch_fixed(name, data)
    return bytes(cfb.data)
