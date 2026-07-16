"""HWP 5.0 파일 읽기 (OLE 복합 문서 → 스트림 사전)."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

import olefile

HWP_SIGNATURE = b"HWP Document File"


class HwpFormatError(ValueError):
    pass


@dataclass
class HwpSource:
    """원본 HWP 파일의 모든 스트림을 메모리에 든 채로 보관한다.

    학습지 생성 시 DocInfo/BinData 등을 그대로 재사용하기 위해
    스트림을 바이트 그대로 유지한다.
    """

    streams: dict[str, bytes] = field(default_factory=dict)  # "BinData/BIN0001.jpg" 형태
    root_clsid: bytes = b"\x00" * 16
    compressed: bool = True

    @classmethod
    def from_bytes(cls, blob: bytes) -> "HwpSource":
        import io

        if not olefile.isOleFile(io.BytesIO(blob)):
            raise HwpFormatError(
                "OLE 복합 문서가 아닙니다. 한글 5.0 (.hwp) 파일인지 확인하세요. "
                "(hwpx 형식이라면 '다른 이름으로 저장'에서 .hwp 5.0 형식을 선택해 주세요)"
            )
        ole = olefile.OleFileIO(io.BytesIO(blob))
        try:
            streams: dict[str, bytes] = {}
            for entry in ole.listdir(streams=True, storages=False):
                name = "/".join(entry)
                streams[name] = ole.openstream(entry).read()
            root_clsid = _clsid_to_bytes(ole.root.clsid) if ole.root else b"\x00" * 16
        finally:
            ole.close()

        header = streams.get("FileHeader")
        if header is None or not header.startswith(HWP_SIGNATURE):
            raise HwpFormatError("FileHeader가 없거나 서명이 다릅니다. HWP 5.0 파일이 아닙니다.")
        (flags,) = struct.unpack_from("<I", header, 36)
        if flags & 0x2:
            raise HwpFormatError("암호화된 HWP 파일은 지원하지 않습니다.")
        if flags & 0x4 or flags & 0x10:
            raise HwpFormatError("배포용/DRM 문서는 지원하지 않습니다.")
        return cls(streams=streams, root_clsid=root_clsid, compressed=bool(flags & 0x1))

    @classmethod
    def from_file(cls, path: str) -> "HwpSource":
        with open(path, "rb") as fh:
            return cls.from_bytes(fh.read())

    def body_section(self, index: int = 0) -> bytes:
        """압축 해제된 BodyText/Section{index} 레코드 스트림."""
        name = f"BodyText/Section{index}"
        raw = self.streams.get(name)
        if raw is None:
            raise HwpFormatError(f"{name} 스트림이 없습니다.")
        return zlib.decompress(raw, -15) if self.compressed else raw

    def section_count(self) -> int:
        return sum(1 for k in self.streams if k.startswith("BodyText/Section"))

    def decompress(self, raw: bytes) -> bytes:
        """압축 스트림(DocInfo 등)을 압축 해제한다."""
        return zlib.decompress(raw, -15) if self.compressed else raw

    def compress_body(self, data: bytes, level: int = zlib.Z_DEFAULT_COMPRESSION) -> bytes:
        """HWP 방식으로 압축한다: raw deflate + CRC32 + 원본 크기 (gzip 꼬리표).

        한글은 이 8바이트 꼬리표로 무결성을 검증하므로 빠뜨리면
        '손상된 파일'로 판정된다.
        """
        if not self.compressed:
            return data
        co = zlib.compressobj(level=level, wbits=-15)
        deflated = co.compress(data) + co.flush()
        footer = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
        return deflated + footer


def _clsid_to_bytes(clsid: str) -> bytes:
    """olefile이 주는 'XXXXXXXX-XXXX-...' 문자열을 원래 16바이트로 되돌린다."""
    if not clsid or clsid == "00000000-0000-0000-0000-000000000000":
        return b"\x00" * 16
    parts = clsid.split("-")
    d1 = int(parts[0], 16)
    d2 = int(parts[1], 16)
    d3 = int(parts[2], 16)
    d4 = bytes.fromhex(parts[3] + parts[4])
    return struct.pack("<IHH", d1, d2, d3) + d4
