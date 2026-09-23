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

# Realistische Testdaten nur im isolierten CI-Testprozess: Sitzung nicht leer aufnehmen.
test_client={"last":"Mustermann","first":"Anna","dob":"14.05.1988","phone":"030 1234567","email":"anna.mustermann@example.test","address":"Musterstraße 12, 13597 Berlin","diagnosis":"F43.2"}
if not any(x.get("last")==test_client["last"] and x.get("first")==test_client["first"] for x in main.DB["clients"]):
    main.DB["clients"].append(test_client)
# Die Sitzungsseite wurde beim Main-Aufbau bereits erzeugt; Testklient direkt in die Auswahl laden.
if hasattr(win,"client_pick"):
    win.client_pick.addItem("Mustermann, Anna",test_client)
    win.client_pick.setCurrentIndex(win.client_pick.count()-1)
if hasattr(win,"s_start"): win.s_start.setTime(main.QTime(10,0))
if hasattr(win,"s_end"): win.s_end.setTime(main.QTime(10,45))
if hasattr(win,"s_type"): win.s_type.setCurrentText("Einzeltherapie")
if hasattr(win,"session_diag"): win.session_diag.setText("F43.2 – Testeintrag")
app.processEvents()

out=Path("test-artifacts"); out.mkdir(exist_ok=True)
pages=[
    (0,"Dashboard"),
    (1,"Sitzung"),
    (2,"Sitzungsassistent"),
    (3,"Klienten"),
    (4,"Neuer-Klient"),
    (5,"Neue-Rechnung"),
    (6,"Rechnungen"),
    (7,"Praxiseinstellungen"),
    (8,"Benutzerhandbuch"),
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

if saved < 9:
    raise SystemExit(f"Zu wenige Seiten-Screenshots erstellt: {saved}")
QTimer.singleShot(100, app.quit)
app.exec()
