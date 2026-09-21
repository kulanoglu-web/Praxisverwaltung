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
if win.width() < 1500 or win.pages.currentIndex()!=1: raise SystemExit("UI-Test fehlgeschlagen")
print("UI screenshot OK", shot.width(), shot.height())
