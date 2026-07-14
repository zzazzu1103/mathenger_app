"""원본 OLE 컨테이너를 구조 변경 없이 '제자리 패치'한다.

새 컨테이너를 처음부터 쓰는 대신, 한글이 정상적으로 여는 원본 파일의
바이트를 그대로 두고 지정한 스트림의 **내용만** 같은 자리(같은 섹터
체인)에 덮어쓴다. 새 내용이 기존 스트림보다 짧으면 나머지는 0으로
채운다. 컨테이너 구조(FAT/디렉터리/크기 필드)가 원본과 완전히 같아
호환성 문제가 생길 수 없다.

- 압축 본문(zlib raw deflate)은 마지막 블록에서 해제가 끝나므로 뒤에
  붙는 0 패딩은 무시된다.
- PrvText(UTF-16LE)는 0 패딩이 곧 널 종결이라 문제없다.
"""

from __future__ import annotations

import struct

SECTOR = 512
MINI_SECTOR = 64
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF


class PatchError(ValueError):
    pass


class PatchTooLarge(PatchError):
    """새 내용이 기존 스트림 공간보다 크다."""


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

        # DIFAT → FAT 섹터 목록
        difat: list[int] = [
            struct.unpack_from("<I", data, 76 + i * 4)[0] for i in range(109)
        ]
        sid = self.first_difat
        while sid not in (ENDOFCHAIN, FREESECT):
            off = self._sector_off(sid)
            difat += struct.unpack_from("<127I", data, off)
            (sid,) = struct.unpack_from("<I", data, off + 508)
        self.fat: list[int] = []
        for s in difat:
            if s in (ENDOFCHAIN, FREESECT):
                continue
            self.fat += struct.unpack_from("<128I", data, self._sector_off(s))

        # 디렉터리 엔트리
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
                    {"name": name, "type": data[e + 66], "start": start, "size": size}
                )
            sid = self.fat[sid]

        root = self.entries[0]
        self.mini_chain = self._chain(root["start"]) if root.get("size") else []

        # 미니 FAT
        self.minifat: list[int] = []
        sid = self.first_minifat
        while sid not in (ENDOFCHAIN, FREESECT):
            self.minifat += struct.unpack_from(
                "<128I", data, self._sector_off(sid)
            )
            sid = self.fat[sid]

    def _sector_off(self, sid: int) -> int:
        return 512 + sid * SECTOR

    def _chain(self, start: int) -> list[int]:
        chain = []
        sid = start
        while sid not in (ENDOFCHAIN, FREESECT):
            chain.append(sid)
            sid = self.fat[sid]
            if len(chain) > len(self.fat):
                raise PatchError("FAT 체인 순환")
        return chain

    def _mini_off(self, mini_sid: int) -> int:
        """미니 섹터 번호 → 파일 오프셋 (루트 미니 스트림 체인 경유)."""
        byte_off = mini_sid * MINI_SECTOR
        big = self.mini_chain[byte_off // SECTOR]
        return self._sector_off(big) + byte_off % SECTOR

    def find_stream(self, name: str) -> dict:
        found = [e for e in self.entries if e.get("name") == name and e.get("type") == 2]
        if not found:
            raise PatchError(f"스트림을 찾을 수 없음: {name}")
        if len(found) > 1:
            raise PatchError(f"같은 이름의 스트림이 여러 개: {name}")
        return found[0]

    def patch_stream(self, name: str, new_data: bytes) -> None:
        entry = self.find_stream(name)
        size = entry["size"]
        if len(new_data) > size:
            raise PatchTooLarge(
                f"'{name}' 새 내용({len(new_data):,}B)이 원본 공간({size:,}B)보다 큽니다."
            )
        padded = new_data + b"\x00" * (size - len(new_data))
        if size < self.mini_cutoff:
            # 미니 스트림: 64바이트 조각으로 나눠 쓴다
            chain = []
            sid = entry["start"]
            while sid not in (ENDOFCHAIN, FREESECT):
                chain.append(sid)
                sid = self.minifat[sid]
            for i, mini_sid in enumerate(chain):
                part = padded[i * MINI_SECTOR : (i + 1) * MINI_SECTOR]
                off = self._mini_off(mini_sid)
                self.data[off : off + len(part)] = part
        else:
            for i, sid in enumerate(self._chain(entry["start"])):
                part = padded[i * SECTOR : (i + 1) * SECTOR]
                off = self._sector_off(sid)
                self.data[off : off + len(part)] = part


def patch_streams(
    container: bytes,
    replacements: dict[str, bytes],
    allow_truncate: set[str] | None = None,
) -> bytes:
    """원본 컨테이너에서 지정 스트림들의 내용만 교체한 사본을 돌려준다.

    allow_truncate에 포함된 스트림은 공간이 모자라면 잘라서 넣는다
    (미리보기 텍스트처럼 잘려도 무방한 스트림용).
    """
    cfb = _Cfb(container)
    for name, data in replacements.items():
        if allow_truncate and name in allow_truncate:
            capacity = cfb.find_stream(name)["size"]
            data = data[:capacity]
        cfb.patch_stream(name, data)
    return bytes(cfb.data)
