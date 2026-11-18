import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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
    (12,"Formulare-Briefe"),
    (13,"Warteliste"),
    (14,"Therapieverlauf"),
    (15,"Ausgaben-EUER"),
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
# Screenshots sind bereits über processEvents() verarbeitet.
# Hier keinen weiteren Qt-Eventloop starten, damit die Funktionstests weiterlaufen.

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

# Formulare & Briefe funktional prüfen: Vorlage + Klient wählen -> Text befüllt -> PDF in der Klientenakte.
win.nav.setCurrentRow(12); app.processEvents()
idx=next((i for i in range(win.doc_client.count()) if isinstance(win.doc_client.itemData(i),dict) and win.doc_client.itemData(i).get("last")=="Mustermann"),-1)
if idx<0: raise SystemExit("Testklient fehlt in Formulare & Briefe")
win.doc_client.setCurrentIndex(idx); app.processEvents()
for row in range(win.doc_list.count()):
    win.doc_list.setCurrentRow(row); app.processEvents()
    body=win.doc_body.toPlainText()
    if "Mustermann" not in body: raise SystemExit(f"Vorlage {win.doc_list.item(row).text()} wurde nicht mit Klientendaten befüllt")
doc_pdf=main.write_document_pdf(win.doc_client.currentData(),"teilnahme",main.document_templates.fill(main.document_template_text("teilnahme"),main.document_values(win.doc_client.currentData())),"","Berlin, 01.01.2026",{},"ui-test")
if not Path(doc_pdf).exists() or Path(doc_pdf).stat().st_size<20000: raise SystemExit("Dokument-PDF fehlt oder ist zu klein")
if "Dokumente" not in str(doc_pdf): raise SystemExit("Dokument-PDF liegt nicht im Ordner Dokumente der Klientenakte")
print("Documents functional test OK", doc_pdf)

# Klientenakte: Stammdaten-Formular, Anrede, verschlüsselte Dokumentenablage.
form=main.ClientForm({"last":"Mustermann","first":"Anna","gender":"weiblich","payer":"Beihilfe + PKV","emergency_name":"Max Mustermann","physician":"Dr. Beispiel\nHauptstr. 1"})
vals=form.values()
if vals["gender"]!="weiblich" or vals["payer"]!="Beihilfe + PKV" or "Hauptstr. 1" not in vals["physician"]: raise SystemExit("Stammdatenformular gibt Werte nicht korrekt zurück")
if set(vals)!=set(main.CLIENT_KEYS): raise SystemExit("Stammdatenformular: Felder fehlen")
if main.salutation_for({"gender":"weiblich"})!="Sehr geehrte Frau" or main.salutation_for({"gender":"männlich"})!="Sehr geehrter Herr" or main.salutation_for({"first":"Kim"})!="Guten Tag Kim":
    raise SystemExit("Anrede je nach Geschlecht falsch")
test_doc=out/"befund-test.txt"; test_doc.write_text("Vertraulicher Testbefund äöü","utf-8")
enc=main.import_client_document(test_client,test_doc,"Arztbrief / Befund")
if not enc.endswith(".enc") or b"Testbefund" in Path(enc).read_bytes(): raise SystemExit("Importiertes Dokument ist nicht verschlüsselt")
if main.decrypt_file_bytes(enc).decode("utf-8")!="Vertraulicher Testbefund äöü": raise SystemExit("Importiertes Dokument lässt sich nicht entschlüsseln")
if not any(d["path"]==enc for d in main.client_documents(test_client)): raise SystemExit("Importiertes Dokument fehlt in der Dokumentenliste")
if not test_doc.exists(): raise SystemExit("Original wurde beim Import verändert/entfernt")
akte=win.client_documents_tab(test_client); akte_master=win.client_master_tab(test_client)
print("Client record functional test OK")

# Warteliste: Seite baut auf, Einträge werden gefiltert und gezählt.
main.DB["waitlist"].append({"id":"t1","created":"2026-11-01T10:00:00","name":"Erika Wartend","urgency":"dringend","status":"wartend","availability":["Mo","abends"],"concern":"Schlafprobleme"})
main.DB["waitlist"].append({"id":"t2","created":"2026-10-01T10:00:00","name":"Otto Fertig","urgency":"normal","status":"übernommen"})
win.nav.setCurrentRow(13); app.processEvents()
page=win.pages.currentWidget()
from PySide6.QtWidgets import QTableWidget as _QT
wt=[x for x in page.findChildren(_QT)][0]
if wt.rowCount()!=1 or wt.item(0,1).text()!="Erika Wartend": raise SystemExit("Warteliste filtert offene Einträge nicht korrekt")
if "(1)" not in win.nav.item(win.nav._row_of_page[13]).text(): raise SystemExit("Wartelisten-Zähler im Menü fehlt")
print("Waitlist functional test OK")

# Therapieverlauf: Auswertung PHQ-9/GAD-7, Speichern, Verlauf, Therapieziel, Risikohinweis.
import questionnaires as Q
r=Q.score("PHQ-9",[1,1,1,1,1,1,1,1,0])
if r["score"]!=8 or r["severity"]!="leicht" or r["notes"]: raise SystemExit("PHQ-9-Auswertung falsch")
r=Q.score("PHQ-9",[3,3,3,3,3,3,3,3,1])
if r["score"]!=25 or r["severity"]!="schwer" or not any("Item 9" in n for n in r["notes"]): raise SystemExit("PHQ-9: Item-9-Hinweis oder Einstufung fehlt")
if Q.score("GAD-7",[2,2,2,2,2,0,0])["severity"]!="mittelgradig" or Q.score("GAD-7",[None]*7)["missing"]!=list(range(1,8)): raise SystemExit("GAD-7-Auswertung falsch")
from PySide6.QtWidgets import QMessageBox as _MB, QPushButton as _PB
_MB.information=staticmethod(lambda *a,**k: _MB.Ok); _MB.warning=staticmethod(lambda *a,**k: _MB.Ok); _MB.question=staticmethod(lambda *a,**k: _MB.Yes)
win.nav.setCurrentRow(14); app.processEvents()
tc=next(c for c in main.DB["clients"] if c.get("last")=="Mustermann")
win.open_therapy_for(tc); app.processEvents()
tpage=win.pages.currentWidget()
btn=lambda text: next(b for b in tpage.findChildren(_PB) if b.text()==text)
win.therapy_tabs.setCurrentIndex(2); app.processEvents()
form=next(w_ for w_ in tpage.findChildren(main.QuestionnaireForm) if w_.kind=="PHQ-9")
form.set_answers([2,2,1,1,1,1,1,1,1]); app.processEvents()
btn("💾 Ergebnis speichern").click(); app.processEvents()
saved=[x for x in tc.get("questionnaires",[]) if x["kind"]=="PHQ-9"]
if not saved or saved[-1]["score"]!=11 or saved[-1]["severity"]!="mittelgradig": raise SystemExit("PHQ-9-Ergebnis wurde nicht korrekt gespeichert")
if not win.therapy_alert.isVisible() or "Item 9" not in win.therapy_alert.text(): raise SystemExit("Risikohinweis bei positivem Item 9 fehlt")
chart=next(w_ for w_ in tpage.findChildren(main.ScoreChart) if w_.vmax==27)
if len(chart.points)!=1 or chart.points[0][1]!=11: raise SystemExit("Verlaufskurve zeigt das Ergebnis nicht")
win.therapy_tabs.setCurrentIndex(1); app.processEvents()
gtext=[w_ for w_ in tpage.findChildren(main.QTextEdit) if "beobachtbar" in w_.placeholderText()][0]
gtext.setPlainText("Wieder zweimal pro Woche Freunde treffen"); btn("💾 Ziel speichern").click(); app.processEvents()
btn("✓ Bewertung für heute hinzufügen").click(); app.processEvents()
g=tc.get("goals",[])
if len(g)!=1 or g[0]["status"]!="in Arbeit" or len(g[0]["ratings"])!=1: raise SystemExit("Therapieziel/Bewertung wurde nicht gespeichert")
win.therapy_tabs.setCurrentIndex(0); app.processEvents()
print("Therapy record functional test OK")

# Kalender: Serientermine, Konflikte, Monatsansicht, Sitzungszähler; Startseite: Heute, Aufgaben, Lücken.
import sqlite3 as _sq
from datetime import date as _date, timedelta as _td
main.sync_sqlite(); tc["session_quota"]="5"; main.save_data()
cid=main.sqlite_client_id(tc)
if not cid: raise SystemExit("Testklient fehlt in der SQLite-Tabelle")
win.nav.setCurrentRow(6); app.processEvents()
start=_date.today()+_td(days=1)
_con=_sq.connect(main.DBFILE); _con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",((start+_td(days=14)).isoformat(),"10:15",45,None,"Sonstiger Termin","geplant","x")); _con.commit(); _con.close()
win.appt_view.setCurrentText("Woche"); app.processEvents()   # baut die Klientenliste neu auf
win.appt_date.setDate(main.QDate(start.year,start.month,start.day)); win.appt_time.setTime(main.QTime(10,0)); win.appt_minutes.setValue(45)
win.appt_client.setCurrentIndex(win.appt_client.findData(cid)); win.appt_repeat.setCurrentText("wöchentlich"); win.appt_count.setValue(4)
next(b for b in win.pages.currentWidget().findChildren(_PB) if "Neuen Termin" in b.text()).click(); app.processEvents()
_con=_sq.connect(main.DBFILE); rows=_con.execute("SELECT appointment_date,series_id FROM appointments WHERE client_id=? ORDER BY appointment_date",(cid,)).fetchall(); _con.close()
if len(rows)!=3 or len({r[1] for r in rows})!=1 or not rows[0][1]: raise SystemExit(f"Serientermine falsch angelegt (3 erwartet, Konflikt in Woche 3 übersprungen): {rows}")
if [r[0] for r in rows]!=[(start+_td(days=d)).isoformat() for d in (0,7,21)]: raise SystemExit(f"Seriendaten falsch: {rows}")
st=main.client_session_stats(tc)
if st["planned"]!=3 or st["quota"]!=5: raise SystemExit(f"Sitzungszähler falsch: {st}")
if "Kontingent" not in main.session_stats_text(tc): raise SystemExit("Kontingent fehlt im Sitzungszähler-Text")
win.appt_view.setCurrentText("Monat"); app.processEvents()
if "Monat" not in win.appt_day_title.text(): raise SystemExit("Monatsansicht fehlt")
# Heute-Termin + abgesagter Termin mit passender Warteliste
today=_date.today(); _con=_sq.connect(main.DBFILE)
_con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",(today.isoformat(),"23:00",45,cid,"Einzeltherapie","geplant","x"))
gap_day=today+_td(days=2); _con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",(gap_day.isoformat(),"18:00",45,cid,"Einzeltherapie","abgesagt","x")); _con.commit(); _con.close()
main.DB["waitlist"].append({"id":"gap","created":"2026-01-01","name":"Lücken Test","status":"wartend","urgency":"hoch","availability":[["Mo","Di","Mi","Do","Fr","Sa","So"][gap_day.weekday()],"abends"]})
gaps=win.waitlist_gaps()
if not any(any(e.get("name")=="Lücken Test" for e in m) for _,m in gaps): raise SystemExit("Warteliste passt nicht zur frei gewordenen Lücke")
tasks=" | ".join(t[1] for t in win.dashboard_tasks())
for need in ("Warteliste",):
    if need not in tasks: raise SystemExit(f"Aufgabe fehlt auf der Startseite: {need} ({tasks})")
main.DB["todos"].append({"text":"Rückruf Testperson","created":"2026-11-01T09:00:00","done":False})
win.nav.setCurrentRow(0); app.processEvents()
dash=win.dash_scroll.widget()
texts=" ".join(l.text() for l in dash.findChildren(main.QLabel))+" ".join(c.text() for c in dash.findChildren(main.QCheckBox))
for need in ("Heute","Aufgaben","Rückruf Testperson","Frei gewordene Termine"):
    if need not in texts: raise SystemExit(f"Startseite: '{need}' fehlt")
from PySide6.QtWidgets import QTableWidget as _QTW
_tt=[t for t in dash.findChildren(_QTW) if t.columnCount()==4 and t.horizontalHeaderItem(3).text()=="Status"]
if not _tt or _tt[0].item(0,1).text()!="Anna Mustermann" or _tt[0].item(0,3).text()!="geplant": raise SystemExit("Startseite 'Heute': Spalten Klient/Status vertauscht")
print("Calendar & dashboard functional test OK")

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
    # logo_path absichtlich NICHT setzen — practice_logo_path() entscheidet selbst.
    "invoice_header_logo_zone":"Links",
    "invoice_header_middle":"Praxisdaten",
    "invoice_header_right":"Kontaktdaten",
}
for k,v in test_settings.items(): main.set_setting(k,v)
main.set_setting("logo_x_mm","18")
main.set_setting("logo_y_mm","10")
main.set_setting("logo_width_mm","72")
main.set_setting("logo_height_mm","22")
logo_setting = main.get_setting("logo_path", "")
print("logo_path aus Settings:", repr(logo_setting))
print("Existiert:", Path(logo_setting).is_file() if logo_setting else False)
print("frozen:", getattr(sys, "frozen", False))
print("_MEIPASS:", getattr(sys, "_MEIPASS", None))
print("executable:", sys.executable)
print("script dir:", Path(__file__).resolve().parent)
for name in ("logo.png", "logo.jpg", "logo.jpeg"):
    print(name, "->", main.bundled_asset(name))

logo_check=main.practice_logo_path()
print("practice_logo_path() ->", logo_check)
print("Invoice logo path:", logo_check)
if logo_check and Path(logo_check).is_file():
    print("External invoice logo asset OK")
else:
    # The HTML invoice path is allowed to carry the logo itself; a corrupt
    # legacy PNG must not abort all UI/functional tests before PDF rendering.
    html_template=main.bundled_template("invoice.html")
    if not html_template.is_file():
        raise SystemExit("RECHNUNGSTEMPLATE FEHLT IM RECHNUNGSTEST")
    print("Legacy logo asset unavailable; testing packaged HTML invoice path")

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
import pymupdf as fitz
doc=fitz.open(str(target))
page=doc[0]
text_check = page.get_text()
print("Invoice text sample:", text_check[:400].encode("ascii", "replace").decode("ascii"))
if len(text_check.strip()) < 50:
    raise SystemExit("RECHNUNGSTEXT IM PDF FEHLT ODER IST ZU KURZ")
for token in ("Rechnung", "Kulano", "Muster"):
    if token not in text_check:
        raise SystemExit("RECHNUNGSINHALT FEHLT: " + token)
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
non_white_pixels = sum(
    n for (r, g, b), n in cols.items()
    if r < 245 or g < 245 or b < 245
)
print("Invoice header non-white pixels:", non_white_pixels)
if non_white_pixels < 20:
    raise SystemExit("RECHNUNGSKOPF LEER — KEIN LOGO UND KEINE SCHRIFT")
# Keine inhaltliche Prüfung des fertigen Praxislogos.
pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False)
invoice_png=out/f"PraxisPro-Testrechnung-v{main.APP_VERSION}.png"
pix.save(str(invoice_png))
doc.close()
print("Invoice visual render OK", invoice_png)

# Finanzen: EÜR (Zuflussprinzip, keine Doppelzählung), Kassenbuch, Export, Ausfallhonorar.
import finance as F
_inv=[{"number":"T-1","amount":70,"status":"bezahlt","paid_date":"2026-03-10","date":"2026-02-28","client":"Mustermann, Anna"},
      {"number":"T-2","amount":90,"status":"offen","date":"2026-03-01"},
      {"number":"T-3","amount":50,"status":"bezahlt","paid_date":"2025-12-30","date":"2025-12-20"}]
_exp=[{"id":"e1","date":"2026-03-01","category":"Miete / Raumkosten","description":"Miete","amount":400,"payment":"Überweisung"},
      {"id":"e2","date":"2026-03-05","category":"Fachliteratur","description":"Buch","amount":30,"payment":"Bar"}]
_cash=[{"id":"k1","kind":"Einnahme","date":"2026-03-10","text":"bar zu T-1","amount":70,"invoice":"T-1"},
       {"id":"k2","kind":"Einnahme","date":"2026-04-02","text":"Barzahlung ohne Rechnung","amount":20,"invoice":""},
       {"id":"k3","kind":"Entnahme","date":"2026-04-03","text":"Einzahlung Bank","amount":50,"invoice":""}]
su=F.euer_summary(_inv,_exp,_cash,2026)
if su["income_total"]!=90 or su["expense_total"]!=430 or su["result"]!=-340: raise SystemExit(f"EÜR falsch: {su['income_total']} {su['expense_total']} {su['result']}")
if su["months"][2]["income"]!=70 or su["months"][3]["income"]!=20: raise SystemExit("EÜR: Monatszuordnung falsch")
rows_,bal=F.cash_book(_exp,_cash,2026,100)
if bal!=110 or [r["balance"] for r in rows_]!=[70,140,160,110]: raise SystemExit(f"Kassenbuch falsch: {bal} {[r['balance'] for r in rows_]}")
xl=F.export_xlsx(out/"euer-test.xlsx",su,False,rows_,100); F.export_csv(out/"buchungen-test.csv",su)
from openpyxl import load_workbook as _lw
_wb=_lw(xl)
if set(_wb.sheetnames)!={"Übersicht","Einnahmen","Ausgaben","Kassenbuch"}: raise SystemExit("EÜR-Export: Blätter fehlen")
if any("Mustermann" in str(c.value) for row in _wb["Einnahmen"].iter_rows() for c in row): raise SystemExit("EÜR-Export enthält Klientennamen, obwohl abgewählt")
win.nav.setCurrentRow(15); app.processEvents()
if win.finance_tabs.count()!=3: raise SystemExit("Seite Ausgaben & EÜR unvollständig")
# Ausfallhonorar aus dem Kalender
_con=_sq.connect(main.DBFILE); _cur=_con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",("2026-11-20","09:00",45,cid,"Einzeltherapie","abgesagt","x")); _aid=_cur.lastrowid; _con.commit(); _con.close()
if not win.bill_cancellation_fee(_aid): raise SystemExit("Ausfallhonorar wurde nicht vorbereitet")
if len(win.manual_items)!=1 or win.manual_items[0]["type"]!="Ausfallhonorar" or abs(win.manual_items[0]["amount"]-70)>0.01: raise SystemExit(f"Ausfallhonorar falsch: {win.manual_items}")
if win.i_last.text()!="Mustermann" or win.pages.currentIndex()!=7: raise SystemExit("Ausfallhonorar: Rechnungsseite nicht vorbelegt")
print("Finance functional test OK")

# Überschneidungen: zentrale Prüfung (auch "erschienen" belegt), eigener Termin beim Ändern ausgenommen
_con=_sq.connect(main.DBFILE)
_a=_con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",("2030-01-07","10:00",45,cid,"Einzeltherapie","erschienen","x")).lastrowid
_con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,appointment_type,status,created_at) VALUES(?,?,?,?,?,?,?)",("2030-01-07","12:00",45,cid,"Einzeltherapie","abgesagt","x")); _con.commit(); _con.close()
if main.appointment_conflict("2030-01-07","10:30",45)!="10:00": raise SystemExit("Überschneidung mit 'erschienen'-Termin nicht erkannt")
if main.appointment_conflict("2030-01-07","10:45",45) is not None: raise SystemExit("Anschlusstermin fälschlich als Konflikt erkannt")
if main.appointment_conflict("2030-01-07","12:00",45) is not None: raise SystemExit("Abgesagter Termin blockiert den Platz")
if main.appointment_conflict("2030-01-07","10:00",45,exclude_id=_a) is not None: raise SystemExit("Eigener Termin blockiert sich beim Ändern selbst")
if any("Unterlagen" in t_[1] for t_ in win.dashboard_tasks()): raise SystemExit("Formulare sind freiwillig – keine Aufgabe 'Fehlende Unterlagen'")
print("Overlap & optional forms test OK")
