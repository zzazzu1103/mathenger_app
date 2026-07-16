"""SQLite 문제 은행 저장소."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    file BLOB NOT NULL,
    n_problems INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,            -- 원본 문서 내 순서 (1부터)
    text TEXT NOT NULL DEFAULT '',   -- 검색/미리보기용 평문
    blob BLOB NOT NULL,              -- 원본 레코드 바이트
    year TEXT DEFAULT '',            -- 연도
    track TEXT DEFAULT '',           -- 계열
    month TEXT DEFAULT '',           -- 출제월
    origin TEXT DEFAULT '',          -- 출처
    number TEXT DEFAULT '',          -- 문항번호
    subject TEXT DEFAULT '',         -- 과목
    unit_major TEXT DEFAULT '',      -- 대단원
    unit_mid TEXT DEFAULT '',        -- 중단원
    unit_small TEXT DEFAULT '',      -- 소단원
    idea TEXT DEFAULT '',            -- 메인 아이디어
    calc_point TEXT DEFAULT '',      -- 계산상의 포인트
    caution TEXT DEFAULT '',         -- 표현상의 주의점
    UNIQUE(source_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_problems_subject ON problems(subject, unit_major, unit_mid);
"""

META_FIELDS = [
    "year", "track", "month", "origin", "number", "subject",
    "unit_major", "unit_mid", "unit_small", "idea", "calc_point", "caution",
]

META_LABELS = {
    "year": "연도", "track": "계열", "month": "출제월", "origin": "출처",
    "number": "문항번호", "subject": "과목", "unit_major": "대단원",
    "unit_mid": "중단원", "unit_small": "소단원", "idea": "메인 아이디어",
    "calc_point": "계산상의 포인트", "caution": "표현상의 주의점",
}


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """스키마/데이터 버전 올림. v2: 저장된 blob에서 전체 텍스트 재추출
    (수식·표·글상자 내용을 미리보기와 검색에 포함시키기 위함)."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    if version >= 2:
        return
    from .hwp.richtext import extract_problem_view

    for row in conn.execute("SELECT id, blob FROM problems").fetchall():
        try:
            text = extract_problem_view(row["blob"]).text
        except Exception:
            continue
        if text.strip():
            conn.execute("UPDATE problems SET text = ? WHERE id = ?", (text, row["id"]))
    conn.execute("PRAGMA user_version = 2")
    conn.commit()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_source(conn: sqlite3.Connection, name: str, file_bytes: bytes, n_problems: int) -> int:
    cur = conn.execute(
        "INSERT INTO sources (name, sha256, file, n_problems) VALUES (?, ?, ?, ?)",
        (name, sha256(file_bytes), file_bytes, n_problems),
    )
    return cur.lastrowid


def find_source_by_hash(conn: sqlite3.Connection, file_bytes: bytes):
    return conn.execute(
        "SELECT id, name FROM sources WHERE sha256 = ?", (sha256(file_bytes),)
    ).fetchone()


def add_problem(conn: sqlite3.Connection, source_id: int, seq: int, text: str,
                blob: bytes, meta: dict[str, str]) -> int:
    fields = {k: str(meta.get(k, "") or "").strip() for k in META_FIELDS}
    cols = ", ".join(["source_id", "seq", "text", "blob"] + META_FIELDS)
    marks = ", ".join(["?"] * (4 + len(META_FIELDS)))
    cur = conn.execute(
        f"INSERT INTO problems ({cols}) VALUES ({marks})",
        [source_id, seq, text, blob] + [fields[k] for k in META_FIELDS],
    )
    return cur.lastrowid


def search_problems(conn: sqlite3.Connection, keyword: str = "", **filters) -> list[sqlite3.Row]:
    where = ["1=1"]
    args: list = []
    for key, value in filters.items():
        if key in META_FIELDS and value:
            where.append(f"{key} = ?")
            args.append(value)
    if keyword:
        like = f"%{keyword}%"
        where.append("(text LIKE ? OR idea LIKE ? OR calc_point LIKE ? OR caution LIKE ?)")
        args += [like, like, like, like]
    sql = (
        "SELECT p.*, s.name AS source_name FROM problems p "
        "JOIN sources s ON s.id = p.source_id "
        f"WHERE {' AND '.join(where)} ORDER BY p.source_id, p.seq"
    )
    return conn.execute(sql, args).fetchall()


def distinct_values(conn: sqlite3.Connection, field: str) -> list[str]:
    if field not in META_FIELDS:
        raise ValueError(field)
    rows = conn.execute(
        f"SELECT DISTINCT {field} FROM problems WHERE {field} != '' ORDER BY {field}"
    ).fetchall()
    return [r[0] for r in rows]


def get_problems(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT p.*, s.name AS source_name FROM problems p "
        f"JOIN sources s ON s.id = p.source_id WHERE p.id IN ({marks})",
        ids,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def get_source_file(conn: sqlite3.Connection, source_id: int) -> bytes:
    row = conn.execute("SELECT file FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise KeyError(f"source {source_id}")
    return row["file"]


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, n_problems, created_at FROM sources ORDER BY id"
    ).fetchall()


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
