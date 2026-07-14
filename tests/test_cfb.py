import io

import olefile
import pytest

from mathenger.hwp.cfb import CfbWriter


def _roundtrip(streams: dict[str, bytes], clsid: bytes = b"\x00" * 16) -> None:
    writer = CfbWriter(root_clsid=clsid)
    for name, data in streams.items():
        writer.add_stream(name, data)
    blob = writer.tobytes()

    assert olefile.isOleFile(io.BytesIO(blob))
    ole = olefile.OleFileIO(io.BytesIO(blob))
    names = {"/".join(e) for e in ole.listdir(streams=True, storages=False)}
    assert names == set(streams)
    for name, data in streams.items():
        assert ole.openstream(name).read() == data, name


def test_small_streams_in_ministream():
    _roundtrip({"A": b"x" * 10, "B": b"y" * 100, "C": b""})


def test_large_stream_in_fat():
    _roundtrip({"Big": bytes(range(256)) * 64, "Small": b"hi"})  # 16KB + 2B


def test_nested_storages():
    _roundtrip({
        "FileHeader": b"H" * 256,
        "BinData/BIN0001.jpg": b"\xff\xd8" + b"\x00" * 9000,
        "BinData/BIN0002.jpg": b"\xff\xd8" + b"\x11" * 50,
        "BodyText/Section0": b"S" * 5000,
        "DocInfo": b"D" * 2000,
    })


def test_boundary_sizes():
    # 미니 스트림 컷오프(4096) 경계
    _roundtrip({
        "At4095": b"a" * 4095,
        "At4096": b"b" * 4096,
        "At64": b"c" * 64,
        "At65": b"d" * 65,
        "At512": b"e" * 512,
    })


def test_many_streams_bst():
    _roundtrip({f"S{i:03d}": bytes([i]) * (i + 1) for i in range(60)})


def test_duplicate_stream_rejected():
    writer = CfbWriter()
    writer.add_stream("A", b"1")
    with pytest.raises(ValueError):
        writer.add_stream("A", b"2")
