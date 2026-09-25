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
win.show()
app.processEvents()

# Realistische Testdaten nur im isolierten CI-Testprozess: Sitzung nicht leer aufnehmen.
test_client={"last":"Mustermann","first":"Anna","dob":"14.05.1988","phone":"030 1234567","email":"anna.mustermann@example.test","address":"Musterstraße 12, 13597 Berlin","diagnosis":"F43.2"}
if not any(x.get("last")==test_client["last"] and x.get("first")==test_client["first"] for x in main.DB["clients"]):
    main.DB["clients"].append(test_client)

# Seiten werden beim Navigieren neu aufgebaut. Deshalb Testklient erst NACH
# dem Öffnen der Sitzungsseite in deren frisch erzeugte Widgets einsetzen.
def prepare_session_page():
    # Main erzeugt alle Seiten einmalig; Navigation wechselt nur den Stack.
    # client_pick kann durch andere Seitenaufbauten als Attribut überschrieben worden sein.
    # Deshalb die Sitzungsseite gezielt neu erzeugen und in Slot 1 ersetzen.
    old=win.pages.widget(1)
    fresh=win.session_ui()
    win.pages.removeWidget(old)
    old.deleteLater()
    win.pages.insertWidget(1,fresh)
    win.pages.setCurrentIndex(1)
    app.processEvents()
    win.client_pick.addItem("Mustermann, Anna",test_client)
    win.client_pick.setCurrentIndex(win.client_pick.count()-1)
    win.s_start.setTime(main.QTime(10,0))
    win.s_end.setTime(main.QTime(10,45))
    win.s_type.setCurrentText("Einzeltherapie")
    win.session_diag.setText("F43.2 – Testeintrag")
    app.processEvents()

out=Path("test-artifacts"); out.mkdir(exist_ok=True)
pages=[
    (0,"Dashboard"),
    (1,"Sitzung"),
    (2,"Sitzungsassistent"),
    (3,"Klienten"),
    (4,"Neuer-Klient"),
    (5,"Paarakte"),
    (6,"Terminkalender"),
    (7,"Neue-Rechnung"),
    (8,"Rechnungen"),
    (9,"Praxiseinstellungen"),
    (10,"Benutzerhandbuch"),
]
saved=0
# Mehrere typische Desktop-/Notebook-Auflösungen prüfen. Damit fallen starre,
# überlappende Layouts bereits im Build auf und nicht erst auf dem Praxis-PC.
resolutions=[(1024,768),(1280,720),(1366,768),(1600,900),(1920,1080)]
for width,height in resolutions:
    win.resize(width,height)
    app.processEvents()
    for index, name in pages:
        if index >= win.nav.count():
            continue
        win.nav.setCurrentRow(index)
        app.processEvents()
        if index == 1:
            prepare_session_page()
        shot=win.grab()
        if shot.isNull():
            raise SystemExit(f"Screenshot {name} konnte nicht erstellt werden")
        path=out/f"PraxisPro-{name}-{width}x{height}.png"
        if not shot.save(str(path)):
            raise SystemExit(f"Screenshot {name} konnte nicht gespeichert werden")
        # Fenster darf nicht über die angeforderte Auflösung hinauswachsen.
        if shot.width() > width or shot.height() > height:
            raise SystemExit(f"UI überschreitet Zielauflösung {width}x{height}: {shot.width()}x{shot.height()}")
        print("UI screenshot OK", name, f"{width}x{height}", shot.width(), shot.height())
        saved += 1

expected=len(resolutions)*len(pages)
if saved < expected:
    raise SystemExit(f"Zu wenige Seiten-/Auflösungs-Screenshots erstellt: {saved}/{expected}")
QTimer.singleShot(100, app.quit)
app.exec()
