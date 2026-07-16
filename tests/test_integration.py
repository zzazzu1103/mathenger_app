"""실제 HWP/엑셀 파일이 있을 때만 도는 통합 테스트.

MATHENGER_TEST_HWP / MATHENGER_TEST_XLSX 환경 변수에 파일 경로를 주면
전체 흐름(임포트→검색→학습지 생성→재파싱)을 검증한다.
(기출문제 저작권 때문에 실제 파일은 저장소에 넣지 않는다.)
"""

import os

import pytest

from mathenger import db
from mathenger.hwp.builder import WorksheetOptions
from mathenger.hwp.reader import HwpSource
from mathenger.hwp.records import parse_records
from mathenger.hwp.splitter import split_problems
from mathenger.importer import import_pair
from mathenger.worksheet import generate_worksheet

HWP_PATH = os.environ.get("MATHENGER_TEST_HWP")
XLSX_PATH = os.environ.get("MATHENGER_TEST_XLSX")

pytestmark = pytest.mark.skipif(
    not (HWP_PATH and os.path.exists(HWP_PATH)),
    reason="MATHENGER_TEST_HWP 환경 변수로 실제 HWP 파일 경로를 지정해야 실행됨",
)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_full_flow(conn):
    hwp = _read(HWP_PATH)
    xlsx = _read(XLSX_PATH) if XLSX_PATH and os.path.exists(XLSX_PATH) else None

    report = import_pair(conn, "test.hwp", hwp, xlsx)
    assert report.n_problems > 0
    if xlsx:
        assert report.n_matched == min(report.n_problems, report.n_meta_rows)

    rows = db.search_problems(conn)
    assert len(rows) == report.n_problems

    picked = [rows[0]["id"], rows[-1]["id"], rows[len(rows) // 2]["id"]]
    for separator in ("column", "page", "spacing"):
        for source_label in (True, False):
            out = generate_worksheet(
                conn, picked,
                WorksheetOptions(separator=separator, source_label=source_label,
                                 answer_page=True),
            )
            ws = HwpSource.from_bytes(out)
            body = ws.body_section()
            parse_records(body)  # 레코드 무결성

            # 선택한 문제의 개체(수식 등) 수가 보존되는지
            src = HwpSource.from_bytes(hwp)
            split = split_problems(src.body_section())
            by_id = {r["id"]: r for r in rows}
            expected_eq = 0
            for pid in picked:
                blob = by_id[pid]["blob"]
                expected_eq += sum(1 for r in parse_records(blob) if r.tag == 88)
            got_eq = sum(1 for r in parse_records(body) if r.tag == 88)
            assert got_eq == expected_eq


def test_duplicate_import_skips_problems(conn):
    hwp = _read(HWP_PATH)
    first = import_pair(conn, "a.hwp", hwp, None)
    assert first.n_added == first.n_problems
    assert first.n_skipped == 0

    # 같은 문서를 다시 넣으면 전부 중복으로 걸러지고 새 원본은 생기지 않는다
    second = import_pair(conn, "b.hwp", hwp, None)
    assert second.n_added == 0
    assert second.n_skipped == second.n_problems
    assert second.source_id == 0

    from mathenger import db as _db
    assert len(_db.list_sources(conn)) == 1


def test_metadata_edit(conn):
    from mathenger import db as _db

    hwp = _read(HWP_PATH)
    import_pair(conn, "a.hwp", hwp, None)
    pid = _db.search_problems(conn)[0]["id"]
    _db.update_problem_meta(conn, pid, {"subject": "미적분1", "idea": "테스트 아이디어"})
    row = _db.get_problems(conn, [pid])[0]
    assert row["subject"] == "미적분1" and row["idea"] == "테스트 아이디어"
