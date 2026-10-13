# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

datas = []
for _f in ("assets/logo.png", "assets/paypal.png", "assets/PraxisPro.ico"):
    if not Path(_f).is_file():
        raise SystemExit(f"FEHLT: {_f} - Build abgebrochen (sonst fehlt das Bild in der Rechnung)")
    datas.append((_f, "assets"))
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
