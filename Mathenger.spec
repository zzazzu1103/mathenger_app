# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙 — desktop.py를 단일 실행파일(Mathenger.exe)로 묶는다.
# templates/static(내장 MathJax 포함)을 함께 포함하고, Flask 관련 모듈을
# 숨은 임포트로 지정한다.

hiddenimports = [
    "openpyxl", "olefile", "jinja2", "click", "werkzeug", "et_xmlfile",
    # 함수 내부에서 지연 임포트되는 모듈도 명시적으로 포함
    "mathenger", "mathenger.db", "mathenger.importer", "mathenger.worksheet",
    "mathenger.hwp", "mathenger.hwp.records", "mathenger.hwp.reader",
    "mathenger.hwp.splitter", "mathenger.hwp.builder", "mathenger.hwp.cfb",
    "mathenger.hwp.patcher", "mathenger.hwp.richtext", "mathenger.hwp.eqscript",
    "mathenger.hwp.docinfo",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[],
    datas=[("templates", "templates"), ("static", "static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "cryptography"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Mathenger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
