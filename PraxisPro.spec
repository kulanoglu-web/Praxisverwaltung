# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

datas = []
if Path("assets/logo.jpg").is_file():
    datas.append(("assets/logo.jpg", "assets"))
if Path("assets/logo.png").is_file():
    datas.append(("assets/logo.png", "assets"))
if Path("assets/paypal.png").is_file():
    datas.append(("assets/paypal.png", "assets"))
if Path("templates").is_dir():
    datas.append(("templates", "templates"))

# QtWebEngine wird über hiddenimports geladen; die PyInstaller-PySide6-Hooks
# sammeln die zugehörigen Qt-Binaries, Resources und Helper-Prozesse.
hiddenimports = [
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtNetwork",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Praxisverwaltung",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/PraxisPro.ico" if Path("assets/PraxisPro.ico").is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Praxisverwaltung",
)
