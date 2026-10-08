from pathlib import Path
from PIL import Image

assets = Path(__file__).resolve().parent / "assets"
jpg = assets / "logo.jpg"
png = assets / "logo.png"
ico = assets / "PraxisPro.ico"

# The legacy logo.png has a damaged IDAT CRC. Use the intact original JPG
# as the source of truth, then rebuild BOTH packaged PNG and Windows icon.
source = jpg if jpg.is_file() else png
if not source.is_file():
    raise SystemExit("PraxisPro logo missing (assets/logo.jpg / assets/logo.png)")

with Image.open(source) as original:
    original.load()  # fail early on unreadable/corrupt input
    img = original.convert("RGBA")

# Regenerate the PNG so invoice rendering and installed assets use valid bytes.
if source != png:
    img.save(png, format="PNG")
    with Image.open(png) as check:
        check.verify()
img.save(
    ico,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
           (64, 64), (128, 128), (256, 256)],
)
if not ico.is_file() or ico.stat().st_size < 1000:
    raise SystemExit("PraxisPro.ico could not be generated")
print(f"PraxisPro assets regenerated from {source.name}: {png.name}, {ico.name}")
