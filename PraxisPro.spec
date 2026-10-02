# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=(
        [('assets/logo.png', 'assets')]
        + ([('assets/paypal.png', 'assets')] if __import__('pathlib').Path('assets/paypal.png').is_file() else [])
        + ([('templates', 'templates')] if __import__('pathlib').Path('templates').is_dir() else [])
    ),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PraxisPro', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False)
