import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
main.init_sqlite()
win = main.Main()
win.current_user = {"username": "build-test", "display_name": "Build-Test"}
win.setWindowTitle(f"PraxisPro v{main.APP_VERSION} - Build-Test")
win.resize(1280, 820)
win.show()
app.processEvents()
os.makedirs("test-output", exist_ok=True)
pixmap = win.grab()
path = "test-output/PraxisPro-Dashboard.png"
if pixmap.isNull() or not pixmap.save(path, "PNG"):
    raise SystemExit("Screenshot konnte nicht erzeugt werden")
print(f"Screenshot erstellt: {pixmap.width()}x{pixmap.height()} -> {path}")
win.close()
