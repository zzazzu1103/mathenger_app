"""Mathenger 웹 앱 — 수학 문제 검색 & 학습지(HWP) 생성.

실행:  python app.py  →  http://127.0.0.1:5000
"""

from __future__ import annotations

import datetime
import io
import os
import secrets
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from mathenger import db
from mathenger.hwp.builder import SEP_COLUMN, SEP_PAGE, SEP_SPACING, WorksheetOptions
from mathenger.hwp.reader import HwpSource
from mathenger.hwp.richtext import extract_problem_view
from mathenger.importer import import_pair
from mathenger.worksheet import generate_worksheet

# 문제은행은 사용자 홈 폴더에 영구 보관한다. 앱 폴더를 지우거나
# 새 버전을 내려받아도 등록한 문제들이 그대로 유지된다.
INSTANCE_DIR = Path.home() / "Mathenger"
DB_PATH = INSTANCE_DIR / "mathenger.db"
SECRET_PATH = INSTANCE_DIR / "secret_key"
_LEGACY_DB = Path(__file__).parent / "instance" / "mathenger.db"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB 업로드 상한

INSTANCE_DIR.mkdir(exist_ok=True)
if _LEGACY_DB.exists() and not DB_PATH.exists():
    import shutil

    shutil.copy2(_LEGACY_DB, DB_PATH)  # 예전 위치에 있던 문제은행을 이어받는다
if SECRET_PATH.exists():
    app.secret_key = SECRET_PATH.read_bytes()
else:
    app.secret_key = secrets.token_bytes(32)
    SECRET_PATH.write_bytes(app.secret_key)


def get_db():
    if "db" not in g:
        g.db = db.connect(DB_PATH)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def get_cart() -> list[int]:
    return session.get("cart", [])


def save_cart(cart: list[int]) -> None:
    session["cart"] = cart
    session.modified = True


# ── 검색 ──────────────────────────────────────────────────────


@app.route("/")
def index():
    conn = get_db()
    filters = {
        key: request.args.get(key, "").strip()
        for key in ("subject", "unit_major", "unit_mid", "unit_small", "origin", "year")
    }
    keyword = request.args.get("q", "").strip()
    searched = bool(request.args)
    results = db.search_problems(conn, keyword=keyword, **filters) if searched else []
    options = {
        key: db.distinct_values(conn, key)
        for key in ("subject", "unit_major", "unit_mid", "unit_small", "origin", "year")
    }
    return render_template(
        "index.html",
        results=results,
        options=options,
        filters=filters,
        keyword=keyword,
        searched=searched,
        cart=get_cart(),
        sources=db.list_sources(conn),
    )


@app.route("/problem/<int:problem_id>")
def problem_detail(problem_id: int):
    conn = get_db()
    rows = db.get_problems(conn, [problem_id])
    if not rows:
        flash("문제를 찾을 수 없습니다.", "error")
        return redirect(url_for("index"))
    p = rows[0]
    try:
        n_images = len(extract_problem_view(p["blob"]).image_bin_ids)
    except Exception:
        n_images = 0
    return render_template("problem.html", p=p, cart=get_cart(),
                           labels=db.META_LABELS, n_images=n_images)


_stream_cache: dict[int, dict[str, bytes]] = {}


def _source_streams(source_id: int) -> dict[str, bytes]:
    if source_id not in _stream_cache:
        _stream_cache.clear()  # 원본은 커봐야 수 MB — 하나만 캐시
        _stream_cache[source_id] = HwpSource.from_bytes(
            db.get_source_file(get_db(), source_id)
        ).streams
    return _stream_cache[source_id]


@app.route("/problem/<int:problem_id>/image/<int:index>")
def problem_image(problem_id: int, index: int):
    conn = get_db()
    rows = db.get_problems(conn, [problem_id])
    if not rows:
        return "", 404
    p = rows[0]
    try:
        bin_ids = extract_problem_view(p["blob"]).image_bin_ids
        bin_id = bin_ids[index]
    except Exception:
        return "", 404
    streams = _source_streams(p["source_id"])
    prefix = f"BinData/BIN{bin_id:04X}."
    for name, data in streams.items():
        if name.startswith(prefix):
            ext = name.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "bmp": "image/bmp", "gif": "image/gif"}.get(ext, "application/octet-stream")
            return send_file(io.BytesIO(data), mimetype=mime)
    return "", 404


# ── 장바구니 ──────────────────────────────────────────────────


@app.post("/cart/add")
def cart_add():
    cart = get_cart()
    added = 0
    for raw in request.form.getlist("problem_id"):
        pid = int(raw)
        if pid not in cart:
            cart.append(pid)
            added += 1
    save_cart(cart)
    if added:
        flash(f"{added}개 문제를 담았습니다.", "info")
    return redirect(request.referrer or url_for("index"))


@app.post("/cart/remove")
def cart_remove():
    pid = int(request.form["problem_id"])
    cart = [c for c in get_cart() if c != pid]
    save_cart(cart)
    return redirect(request.referrer or url_for("cart_view"))


@app.post("/cart/clear")
def cart_clear():
    save_cart([])
    flash("장바구니를 비웠습니다.", "info")
    return redirect(url_for("cart_view"))


@app.post("/cart/move")
def cart_move():
    pid = int(request.form["problem_id"])
    direction = request.form["direction"]
    cart = get_cart()
    if pid in cart:
        i = cart.index(pid)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(cart):
            cart[i], cart[j] = cart[j], cart[i]
    save_cart(cart)
    return redirect(url_for("cart_view"))


@app.route("/cart")
def cart_view():
    conn = get_db()
    problems = db.get_problems(conn, get_cart())
    multi_source = len({p["source_id"] for p in problems}) > 1
    return render_template("cart.html", problems=problems, cart=get_cart(),
                           multi_source=multi_source)


# ── 학습지 생성 ───────────────────────────────────────────────


@app.post("/generate")
def generate():
    conn = get_db()
    cart = get_cart()
    if not cart:
        flash("장바구니가 비어 있습니다.", "error")
        return redirect(url_for("cart_view"))
    separator = request.form.get("separator", SEP_COLUMN)
    if separator not in (SEP_COLUMN, SEP_PAGE, SEP_SPACING):
        separator = SEP_COLUMN
    options = WorksheetOptions(
        separator=separator,
        spacing=max(0, min(20, int(request.form.get("spacing", 2)))),
        numbering=request.form.get("numbering") == "on",
        answer_page=request.form.get("answer_page") == "on",
    )
    try:
        data = generate_worksheet(conn, cart, options)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cart_view"))
    filename = request.form.get("filename", "").strip() or (
        "학습지_" + datetime.date.today().strftime("%Y%m%d")
    )
    if not filename.lower().endswith(".hwp"):
        filename += ".hwp"
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype="application/x-hwp",
    )


# ── 가져오기 ──────────────────────────────────────────────────


@app.route("/import", methods=["GET", "POST"])
def import_view():
    conn = get_db()
    if request.method == "POST":
        hwp_file = request.files.get("hwp")
        xlsx_file = request.files.get("xlsx")
        if not hwp_file or not hwp_file.filename:
            flash("한글(.hwp) 파일을 선택해 주세요.", "error")
            return redirect(url_for("import_view"))
        xlsx_bytes = xlsx_file.read() if xlsx_file and xlsx_file.filename else None
        try:
            report = import_pair(
                conn,
                hwp_name=os.path.basename(hwp_file.filename),
                hwp_bytes=hwp_file.read(),
                xlsx_bytes=xlsx_bytes,
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("import_view"))
        flash(
            f"'{report.source_name}'에서 문제 {report.n_problems}개를 가져왔고 "
            f"{report.n_matched}개에 메타데이터를 연결했습니다.",
            "info",
        )
        for warning in report.warnings:
            flash(warning, "warn")
        return redirect(url_for("index"))
    return render_template("import.html", sources=db.list_sources(conn), cart=get_cart())


@app.post("/source/<int:source_id>/delete")
def source_delete(source_id: int):
    conn = get_db()
    db.delete_source(conn, source_id)
    conn.commit()
    # 삭제된 원본의 문제가 장바구니에 남지 않게 정리
    remaining = {p["id"] for p in db.get_problems(conn, get_cart())}
    save_cart([c for c in get_cart() if c in remaining])
    flash("원본과 딸린 문제를 삭제했습니다.", "info")
    return redirect(url_for("import_view"))


if __name__ == "__main__":
    app.run(debug=True)
