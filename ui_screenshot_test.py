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
win.show()
app.processEvents()

out=Path("test-artifacts"); out.mkdir(exist_ok=True)
pages=[
    (0,"Dashboard"),
    (1,"Sitzung"),
    (2,"Klienten"),
    (3,"Rechnung"),
    (4,"Rechnungsverwaltung"),
    (5,"Einstellungen"),
]
saved=0
for index, name in pages:
    if index >= win.nav.count():
        continue
    win.nav.setCurrentRow(index)
    app.processEvents()
    shot=win.grab()
    if shot.isNull():
        raise SystemExit(f"Screenshot {name} konnte nicht erstellt werden")
    path=out/f"PraxisPro-{name}-1600x900.png"
    if not shot.save(str(path)):
        raise SystemExit(f"Screenshot {name} konnte nicht gespeichert werden")
    if shot.width() < 1000 or shot.height() < 700:
        raise SystemExit(f"UI-Test Screenshot zu klein: {shot.width()}x{shot.height()}")
    print("UI screenshot OK", name, shot.width(), shot.height())
    saved += 1

if saved < 5:
    raise SystemExit(f"Zu wenige Seiten-Screenshots erstellt: {saved}")
QTimer.singleShot(100, app.quit)
app.exec()
