"""Stellt Logo und Programm-Icon sicher, ohne bereits gute Dateien zu überschreiben.

- assets/PraxisPro.ico  : wird nur erzeugt, wenn es fehlt oder defekt ist (das mitgelieferte Symbol-Icon bleibt erhalten)
- assets/logo.png       : wird nur aus logo.jpg neu erzeugt, wenn die PNG fehlt oder nicht lesbar ist
"""
from pathlib import Path
from PIL import Image

assets = Path(__file__).resolve().parent / "assets"
jpg, png, ico = assets / "logo.jpg", assets / "logo.png", assets / "PraxisPro.ico"


def readable(path):
    try:
        with Image.open(path) as im:
            im.load()
        return True
    except Exception:
        return False


if not readable(png):
    if not readable(jpg):
        raise SystemExit("PraxisPro logo missing/damaged (assets/logo.png and assets/logo.jpg)")
    with Image.open(jpg) as original:
        original.load()
        original.convert("RGBA").save(png, format="PNG")
    print("assets/logo.png was damaged or missing and was regenerated from logo.jpg")
else:
    print("assets/logo.png is intact - kept")

if not (ico.is_file() and ico.stat().st_size > 1000 and readable(ico)):
    source = png if readable(png) else jpg
    with Image.open(source) as original:
        original.load()
        original.convert("RGBA").save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("assets/PraxisPro.ico was missing or damaged and was generated from", source.name)
else:
    print("assets/PraxisPro.ico is intact - kept")
if not ico.is_file() or ico.stat().st_size < 1000:
    raise SystemExit("PraxisPro.ico could not be generated")
