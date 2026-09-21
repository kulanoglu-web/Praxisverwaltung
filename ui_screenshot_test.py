import os, sys
from pathlib import Path
os.environ["QT_SCALE_FACTOR"]="1"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import main

app=QApplication(sys.argv)
app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}")
win=main.Main()
win.current_user={"username":"ui-test","display_name":"UI-Test","role":"Administrator"}
win.update_user_badge()
win.setWindowTitle(f"PraxisPro v{main.APP_VERSION} – UI-Test")
win.setMinimumSize(800,600)
win.resize(1600,900)
win.nav.setCurrentRow(1)
win.show()
app.processEvents()
QTimer.singleShot(1200, app.quit)
app.exec()
app.processEvents()
out=Path("test-artifacts"); out.mkdir(exist_ok=True)
shot=win.grab()
if shot.isNull(): raise SystemExit("Screenshot konnte nicht erstellt werden")
if not shot.save(str(out/"PraxisPro-Sitzung-1600x900.png")): raise SystemExit("Screenshot konnte nicht gespeichert werden")
if win.pages.currentIndex()!=1: raise SystemExit(f"UI-Test falsche Seite: {win.pages.currentIndex()}")
if shot.width() < 1200 or shot.height() < 700: raise SystemExit(f"UI-Test Screenshot zu klein: {shot.width()}x{shot.height()}")
print("UI screenshot OK", shot.width(), shot.height())
