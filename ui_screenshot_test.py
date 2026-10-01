import os, sys
from pathlib import Path
os.environ["QT_SCALE_FACTOR"]="1"
from PySide6.QtWidgets import QApplication, QScrollArea, QLineEdit, QComboBox, QTextEdit, QListWidget
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

out=Path("ui_test_output"); out.mkdir(parents=True, exist_ok=True)
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
        # Basis-Usability: fokussierbare Eingabefelder dürfen keine Nullgröße haben.
        page=win.pages.currentWidget()
        for widget_type in (QLineEdit,QComboBox,QTextEdit,QListWidget):
            for child in page.findChildren(widget_type):
                if child.isVisible() and (child.width()<40 or child.height()<18):
                    raise SystemExit(f"Zu kleines Eingabefeld auf {name} bei {width}x{height}: {child.objectName()} {child.width()}x{child.height()}")
        print("UI screenshot OK", name, f"{width}x{height}", shot.width(), shot.height())
        saved += 1

expected=len(resolutions)*len(pages)
if saved < expected:
    raise SystemExit(f"Zu wenige Seiten-/Auflösungs-Screenshots erstellt: {saved}/{expected}")
QTimer.singleShot(100, app.quit)
app.exec()


# Sitzungsassistent funktional prüfen: ICD-Auswahl -> Thema/Symptome -> Notizübernahme.
# Die vorhandene Assistentenseite verwenden. helper_ui() schreibt seine Widgets nach
# self.*; ein zweiter Aufruf würde diese Referenzen überschreiben und die Signal-Closures
# der bereits eingebauten Seite von den aktuell referenzierten Widgets trennen.
win.pages.setCurrentIndex(2)
app.processEvents()
idx=win.help_fcode.findText("F43.1", main.Qt.MatchStartsWith)
if idx < 0: raise SystemExit("F43.1 fehlt im Sitzungsassistenten")
win.help_fcode.setCurrentIndex(idx); app.processEvents()
if win.help_topic.currentText()!="PTBS / Trauma": raise SystemExit("F43.1 schaltet nicht auf PTBS / Trauma")
if win.symptom_list.count()<5: raise SystemExit("PTBS-Symptomliste wurde nicht geladen")
win.symptom_list.clearSelection()
first_symptom=win.symptom_list.item(0)
first_symptom.setSelected(True)
from PySide6.QtCore import QItemSelectionModel
idx0=win.symptom_list.indexFromItem(first_symptom)
win.symptom_list.selectionModel().select(idx0,QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
app.processEvents()
if not win.symptom_list.selectedItems(): raise SystemExit("Symptomauswahl wurde vom QListWidget nicht übernommen")
win.symptom_list.itemSelectionChanged.emit()
app.processEvents()
import unicodedata
summary_text=unicodedata.normalize("NFC",win.help_text.toPlainText())
selected_text=unicodedata.normalize("NFC",first_symptom.text())
if selected_text not in summary_text:
    raise SystemExit("Ausgewähltes Symptom fehlt in der Assistenten-Zusammenfassung")
print("Assistant functional test OK: F43.1 -> PTBS / Trauma -> symptoms")

# Echte Rechnung im isolierten Windows-Test erzeugen.
# Sie wird ausschließlich durch PraxisPro selbst erstellt, nicht extern nachgebaut.
win.nav.setCurrentRow(7); app.processEvents()
# Rechnungsseite frisch aufbauen, damit alle Widgets sicher zur aktuellen Seite gehören.
old=win.pages.widget(7)
fresh=win.invoice_ui()
win.pages.removeWidget(old); old.deleteLater(); win.pages.insertWidget(7,fresh)
win.pages.setCurrentIndex(7); app.processEvents()

# Praxisdaten für den Rechnungstest über die Einstellungen setzen.
test_settings={
    "practice_name":"Psychologische Privatpraxis",
    "owner_name":"Erdoğan Kulanoğlu",
    "qualifications":"Psychologe M.Sc. | Sozialarbeiter B.A.",
    "practice_subtitle":"Ehe-, Familien- und Lebensberatung | Zertifizierter Systemischer Berater und Therapeut nach dem SIT-Modell",
    "address":"Schönwalder Str. 59, 13585 Berlin",
    "phone":"0176 43605753",
    "landline":"030 12127420",
    "fax":"030 43205928",
    "email":"info@psychologe-spandau.de",
    "website":"www.psychologe-spandau.de",
    "tax_number":"19/405/00254",
    "iban":"DE13 5001 0517 5404 0811 30",
    "bic":"INGDDEFFXXX",
    "paypal":"erdogankulanoglu@hotmail.com",
    "logo_path":str((Path("assets")/"logo.png").resolve()),
    "invoice_header_logo_zone":"Links",
    "invoice_header_middle":"Praxisdaten",
    "invoice_header_right":"Kontaktdaten",
}
for k,v in test_settings.items(): main.set_setting(k,v)
main.set_setting("logo_x_mm","18")
main.set_setting("logo_y_mm","10")
main.set_setting("logo_width_mm","72")
main.set_setting("logo_height_mm","22")
logo_check=main.practice_logo_path()
print("Invoice logo path:", logo_check)
if not logo_check or not Path(logo_check).is_file():
    raise SystemExit("ECHTES PRAXISLOGO FEHLT IM RECHNUNGSTEST")

win.i_no.setText("TEST-2026-001")
win.i_first.setText("Anna"); win.i_last.setText("Mustermann")
win.i_addr.setText("Musterstraße 12, 13597 Berlin")
win.i_diag.setText("F43.2")
win.i_date.setDate(main.QDate(2026,9,28))
win.i_start.setTime(main.QTime(10,0)); win.i_end.setTime(main.QTime(10,45))
win.i_type.setCurrentText("Einzeltherapie"); win.i_min.setValue(45); win.i_red.setChecked(False)

# Dialoge im CI automatisch schließen, damit make_invoice vollständig durchläuft.
from PySide6.QtWidgets import QMessageBox
orig_exec=QMessageBox.exec
QMessageBox.exec=lambda self: QMessageBox.Rejected
try:
    win.make_invoice()
finally:
    QMessageBox.exec=orig_exec

invoice=next((x for x in main.DB["invoices"] if x.get("number")=="TEST-2026-001"),None)
if not invoice: raise SystemExit("Testrechnung wurde nicht in der Rechnungsdatenbank angelegt")
pdf=Path(invoice["pdf"])
if not pdf.exists() or pdf.stat().st_size < 1000: raise SystemExit("Testrechnung-PDF fehlt oder ist leer")
target=out/f"PraxisPro-Testrechnung-v{main.APP_VERSION}.pdf"
target.write_bytes(pdf.read_bytes())
print("Invoice generation test OK", target, target.stat().st_size)
import fitz
doc=fitz.open(str(target))
page=doc[0]
text_check=page.get_text()
for expected in ("Erdoğan Kulanoğlu","Schönwalder","Musterstraße"):
    if expected not in text_check:
        raise SystemExit("UNICODE-FEHLER IN RECHNUNG: "+expected)
# Prüfe das gerenderte Ergebnis pixelbasiert. Das funktioniert auch bei
# ReportLab-InlineImages, die PyMuPDF nicht als separaten Bildblock meldet.
clip=fitz.Rect(10,10,page.rect.width*0.62,page.rect.height*0.25)
lpix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=clip,alpha=False)
samples=lpix.samples
print("Invoice header raster:", lpix.width, lpix.height, "channels", lpix.n, "sample-range", min(samples), max(samples))
# Diagnose häufigste Nicht-Weiß-Farben im gerenderten Kopf.
from collections import Counter
cols=Counter()
for i in range(0,len(samples),lpix.n):
    rgb=(samples[i],samples[i+1],samples[i+2])
    if min(rgb)<245: cols[rgb]+=1
print("Invoice header top colors:", cols.most_common(15))
# Sichtbares Praxislogo im linken Kopfbereich zwingend prüfen.
brand_pixels=sum(n for (r,g,b),n in cols.items() if r > g*1.25 and r > b*1.25 and r > 70)
print("Invoice logo brand pixels:",brand_pixels)
if brand_pixels < 40:
    raise SystemExit("PRAXISLOGO IM FERTIGEN PDF NICHT SICHTBAR")
# Keine inhaltliche Prüfung des fertigen Praxislogos.
pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False)
invoice_png=out/f"PraxisPro-Testrechnung-v{main.APP_VERSION}.png"
pix.save(str(invoice_png))
doc.close()
print("Invoice visual render OK", invoice_png)

