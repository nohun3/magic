# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


datas = [
    ("templates", "templates"),
    ("pc/config/settings.yaml", "pc/config"),
]

model_cache = Path.home() / ".paddlex" / "official_models"
for model_name in (
    "PP-OCRv5_mobile_det",
    "PP-OCRv5_mobile_rec",
    "korean_PP-OCRv5_mobile_rec",
):
    model_dir = model_cache / model_name
    if not model_dir.is_dir():
        raise FileNotFoundError(f"Required OCR model cache is missing: {model_dir}")
    datas.append(
        (str(model_dir), f".paddlex/official_models/{model_name}")
    )
binaries = []
hiddenimports = collect_submodules("pc")

for package in ("paddle", "paddleocr", "paddlex"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    ["pc/routine/gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="STM200",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="STM200",
    contents_directory=".",
)
