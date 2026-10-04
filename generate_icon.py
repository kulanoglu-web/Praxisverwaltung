from pathlib import Path
from PIL import Image

src = Path("assets/logo.png")
dst = Path("assets/PraxisPro.ico")
if not src.is_file():
    raise SystemExit("assets/logo.png fehlt")
img = Image.open(src).convert("RGBA")
# Windows-Icon aus exakt dem mitgelieferten Praxislogo, mit mehreren Auflösungen.
img.save(dst, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"PraxisPro icon created: {dst}")
