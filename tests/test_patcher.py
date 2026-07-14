import io

import olefile
import pytest

from mathenger.hwp.cfb import CfbWriter
from mathenger.hwp.patcher import PatchTooLarge, patch_streams


def _container(streams: dict[str, bytes]) -> bytes:
    writer = CfbWriter()
    for name, data in streams.items():
        writer.add_stream(name, data)
    return writer.tobytes()


def _read_all(blob: bytes) -> dict[str, bytes]:
    ole = olefile.OleFileIO(io.BytesIO(blob))
    return {
        "/".join(e): ole.openstream(e).read()
        for e in ole.listdir(streams=True, storages=False)
    }


def test_patch_big_stream_shorter_content():
    original = _container({"Big": b"A" * 9000, "Other": b"B" * 5000})
    patched = patch_streams(original, {"Big": b"C" * 4000})
    assert len(patched) == len(original)
    streams = _read_all(patched)
    # 크기 필드는 그대로(9000), 내용은 새 데이터 + 0 패딩
    assert streams["Big"] == b"C" * 4000 + b"\x00" * 5000
    assert streams["Other"] == b"B" * 5000


def test_patch_mini_stream():
    original = _container({"Mini": b"x" * 200, "Mini2": b"y" * 130, "Big": b"z" * 5000})
    patched = patch_streams(original, {"Mini": b"n" * 150})
    streams = _read_all(patched)
    assert streams["Mini"] == b"n" * 150 + b"\x00" * 50
    assert streams["Mini2"] == b"y" * 130
    assert streams["Big"] == b"z" * 5000


def test_patch_nested_path_by_name():
    original = _container({"Store/Section0": b"s" * 6000, "FileHeader": b"h" * 256})
    patched = patch_streams(original, {"Section0": b"t" * 100})
    streams = _read_all(patched)
    assert streams["Store/Section0"][:100] == b"t" * 100


def test_patch_too_large_raises():
    original = _container({"Big": b"A" * 5000})
    with pytest.raises(PatchTooLarge):
        patch_streams(original, {"Big": b"B" * 5001})


def test_patch_truncate_allowed():
    original = _container({"Prv": b"A" * 100, "Big": b"z" * 5000})
    patched = patch_streams(original, {"Prv": b"B" * 500}, allow_truncate={"Prv"})
    assert _read_all(patched)["Prv"] == b"B" * 100


def test_patch_only_touches_data_sectors():
    original = _container({"Big": b"A" * 9000, "Other": b"B" * 5000})
    patched = patch_streams(original, {"Big": b"C" * 9000})
    # 헤더(512B)와 구조 섹터는 완전히 동일해야 한다
    assert patched[:512] == original[:512]
    diff_sectors = {
        i for i in range((len(original) - 512) // 512)
        if patched[512 + i * 512 : 512 + (i + 1) * 512]
        != original[512 + i * 512 : 512 + (i + 1) * 512]
    }
    assert len(diff_sectors) <= 18  # Big의 체인(9000/512=18섹터)만 변경
