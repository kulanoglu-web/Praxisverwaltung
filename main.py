import sys, json, os, re, math, shutil, sqlite3
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog,QSplitter,QListWidget,QStackedWidget,QFrame,QGridLayout)
from PySide6.QtCore import QDate,QTime
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

class InkCanvas(QWidget):
    def __init__(self):
        super().__init__(); self.setMinimumHeight(220); self.setAttribute(Qt.WA_StaticContents); self.image=QImage(1200,700,QImage.Format_ARGB32); self.image.fill(Qt.white); self.last=QPoint(); self.drawing=False; self.pen_width=3; self.eraser=False; self.history=[]
    def paintEvent(self,e): QPainter(self).drawImage(self.rect(),self.image)
    def pointer(self,e):
        return QPoint(int(e.position().x()*self.image.width()/max(1,self.width())),int(e.position().y()*self.image.height()/max(1,self.height())))
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:self.history.append(self.image.copy()); self.history=self.history[-30:]; self.last=self.pointer(e);self.drawing=True
    def mouseMoveEvent(self,e):
        if self.drawing:
            p=self.pointer(e); q=QPainter(self.image); q.setRenderHint(QPainter.Antialiasing); q.setPen(QPen(Qt.white if self.eraser else Qt.black,self.pen_width if not self.eraser else max(12,self.pen_width*4),Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin)); q.drawLine(self.last,p); q.end(); self.last=p; self.update()
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton:self.drawing=False
    def clear(self): self.history.append(self.image.copy()); self.image.fill(Qt.white); self.update()
    def undo(self):
        if self.history: self.image=self.history.pop(); self.update()
    def set_eraser(self,on): self.eraser=on
    def set_width(self,w): self.pen_width=w
    def save_png(self,path): return self.image.save(str(path),"PNG")
from openpyxl import Workbook, load_workbook

ROOT=Path.home()/"Documents"/"Praxisverwaltung"
DATA=ROOT/"praxisdaten.json"
DBDIR=ROOT/"Datenbank"; DBFILE=DBDIR/"Praxisverwaltung.db"
for p in [ROOT/"Klienten",ROOT/"Einnahmen",ROOT/"Backups",DBDIR]: p.mkdir(parents=True,exist_ok=True)

def init_sqlite():
    con=sqlite3.connect(DBFILE); con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS clients(
      id INTEGER PRIMARY KEY, first TEXT NOT NULL, last TEXT NOT NULL, dob TEXT,
      address TEXT, diagnosis TEXT, created_at TEXT, updated_at TEXT,
      UNIQUE(first,last,dob));
    CREATE TABLE IF NOT EXISTS sessions(
      id TEXT PRIMARY KEY, client_id INTEGER, date TEXT, start TEXT, end TEXT,
      minutes INTEGER, type TEXT, reduced INTEGER DEFAULT 0, notes TEXT,
      ink_file TEXT, billed INTEGER DEFAULT 0, invoice_number TEXT, corrected_at TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id));
    CREATE TABLE IF NOT EXISTS invoices(
      id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE NOT NULL, date TEXT,
      client_id INTEGER, client TEXT, address TEXT, diagnosis TEXT, amount REAL,
      status TEXT DEFAULT 'offen', paid_date TEXT, pdf TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id));
    CREATE TABLE IF NOT EXISTS invoice_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
      session_id TEXT, service_date TEXT, start TEXT, end TEXT, minutes INTEGER,
      type TEXT, reduced INTEGER DEFAULT 0, amount REAL,
      FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES sessions(id));
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    """); con.commit(); con.close()

def sync_sqlite():
    init_sqlite(); con=sqlite3.connect(DBFILE); cur=con.cursor()
    for x in DB.get("clients",[]):
        cur.execute("""INSERT INTO clients(first,last,dob,address,diagnosis,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(first,last,dob) DO UPDATE SET
        address=excluded.address,diagnosis=excluded.diagnosis,updated_at=excluded.updated_at""",
        (x.get("first",""),x.get("last",""),x.get("dob",""),x.get("address",""),x.get("diagnosis",""),x.get("created_at",""),datetime.now().isoformat(timespec="seconds")))
    con.commit()
    for s in DB.get("sessions",[]):
        cur.execute("SELECT id FROM clients WHERE first=? AND last=? ORDER BY id DESC LIMIT 1",(s.get("first",""),s.get("last",""))); row=cur.fetchone(); cid=row[0] if row else None
        cur.execute("""INSERT OR REPLACE INTO sessions(id,client_id,date,start,end,minutes,type,reduced,notes,ink_file,billed,invoice_number,corrected_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(s.get("id"),cid,s.get("date",""),s.get("start",""),s.get("end",""),s.get("minutes",0),s.get("type",""),1 if s.get("reduced") else 0,s.get("notes",""),s.get("ink_file",""),1 if s.get("billed") else 0,s.get("invoice_number",""),s.get("corrected_at","")))
    for i in DB.get("invoices",[]):
        cur.execute("""INSERT OR REPLACE INTO invoices(number,date,client,address,diagnosis,amount,status,paid_date,pdf)
        VALUES(?,?,?,?,?,?,?,?,?)""",(i.get("number",""),i.get("date",""),i.get("client",""),i.get("address",""),i.get("diagnosis",""),i.get("amount",0),i.get("status","offen"),i.get("paid_date",""),i.get("pdf","")))
    con.commit(); con.close()

def load_data():
    if DATA.exists():
        try:return json.loads(DATA.read_text(encoding="utf-8"))
        except:return {}
    return {}
DB=load_data(); DB.setdefault("clients",[]); DB.setdefault("sessions",[]); DB.setdefault("invoices",[])
init_sqlite(); sync_sqlite()

def save_data():
    DATA.write_text(json.dumps(DB,ensure_ascii=False,indent=2),encoding="utf-8")
    sync_sqlite()

def safe(s): return re.sub(r'[<>:"/\\|?*]','_',s).strip()

def client_dir(c):
    p=ROOT/"Klienten"/safe(f"{c.get('last','')}, {c.get('first','')}")
    for x in ["Stammdaten","Sitzungen","Rechnungen","Dokumente"]:(p/x).mkdir(parents=True,exist_ok=True)
    return p

def next_no():
    y=str(datetime.now().year); nums=[]
    for i in DB["invoices"]:
        n=str(i.get("number",""))
        if n.startswith(y):
            try:nums.append(int(n[4:]))
            except:pass
    return y+f"{(max(nums,default=0)+1):04d}"

def amount_for(minutes,typ,reduced):
    rate=60 if reduced else 70
    if typ=="Notfalltelefonat": return math.ceil(max(1,minutes)/30)*45
    if typ=="Hausbesuch": return minutes/45*rate+25
    return minutes/45*rate

def update_excel():
    year=datetime.now().year; f=ROOT/"Einnahmen"/f"Einnahmen_{year}.xlsx"
    wb=Workbook(); ws=wb.active; ws.title="Einnahmen"
    ws.append(["Rechnungsnummer","Rechnungsdatum","Zahlungsdatum","Klient","Status","Betrag"])
    for i in DB["invoices"]:
        if str(i.get("number","")).startswith(str(year)):
            ws.append([i["number"],i["date"],i.get("paid_date",""),i["client"],i.get("status","offen"),i["amount"]])
    ov=wb.create_sheet("Jahresübersicht"); ov.append(["Kennzahl","Betrag"])
    total=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")!="storniert")
    paid=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")=="bezahlt")
    ov.append(["Rechnungsbetrag",total]); ov.append(["Bezahlt",paid]); ov.append(["Offen",total-paid])
    wb.save(f)

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Praxisverwaltung"); self.resize(1280,820); self.setMinimumSize(1050,700)
        self.started=None; self.acc=0; self.running=False; self.restore_draft_pending=True
        shell=QWidget(); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(225); sv=QVBoxLayout(sidebar); sv.setContentsMargins(14,20,14,20)
        brand=QLabel("PRAXIS\nVERWALTUNG"); brand.setObjectName("brand"); sv.addWidget(brand)
        self.nav=QListWidget(); self.nav.setObjectName("nav")
        for x in ["Übersicht","Sitzung","Sitzungsassistent","Klienten","Neue Rechnung","Rechnungen"]: self.nav.addItem(x)
        sv.addWidget(self.nav,1)
        foot=QLabel("Lokale Praxisverwaltung"); foot.setObjectName("sidefoot"); sv.addWidget(foot)
        self.pages=QStackedWidget(); self.pages.addWidget(self.dashboard_ui()); self.pages.addWidget(self.session_ui()); self.pages.addWidget(self.helper_ui()); self.pages.addWidget(self.clients_ui()); self.pages.addWidget(self.invoice_ui()); self.pages.addWidget(self.invoices_ui())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        root.addWidget(sidebar); root.addWidget(self.pages,1); self.setCentralWidget(shell)
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.wallclock=QLabel()
        self.statusBar().addPermanentWidget(self.wallclock)
        self.walltimer=QTimer(self); self.walltimer.timeout.connect(self.update_wallclock); self.walltimer.start(250); self.update_wallclock()
        self.setStyleSheet("""
        QMainWindow { background:#f4f6f8; }
        #sidebar { background:#132f47; border:0; }
        #brand { color:white; font-size:21px; font-weight:800; padding:8px 10px 20px 10px; letter-spacing:1px; }
        #sidefoot { color:#b9c8d5; font-size:12px; padding:10px; }
        #nav { background:transparent; border:0; outline:0; color:#dce7ef; font-size:15px; }
        #nav::item { padding:14px 12px; margin:3px 0; border-radius:8px; }
        #nav::item:selected { background:#ffffff; color:#17324d; font-weight:700; }
        #nav::item:hover:!selected { background:#244d70; color:white; }
        QStackedWidget { background:#f4f6f8; }
        #pageTitle { font-size:30px; font-weight:800; color:#17324d; }
        #pageSub { font-size:15px; color:#607080; padding-bottom:8px; }
        #statCard { background:white; border:1px solid #dce3e9; border-radius:14px; min-height:115px; }
        #cardCaption { color:#6b7b88; font-size:12px; font-weight:700; }
        #cardValue { color:#17324d; font-size:27px; font-weight:800; }
        #infoBox { background:white; border:1px solid #dce3e9; border-radius:10px; padding:14px; color:#607080; }
        QTabWidget::pane { border:0; background:white; border-radius:12px; }
        QTabBar::tab { background:#e9eef3; padding:12px 20px; margin:2px; border-radius:8px; font-size:14px; }
        QTabBar::tab:selected { background:#17324d; color:white; font-weight:700; }
        QLabel { color:#1f2933; font-size:14px; }
        QLineEdit,QTextEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox {
            background:white; border:1px solid #cbd5df; border-radius:8px; padding:8px; font-size:15px;
            selection-background-color:#17324d;
        }
        QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus,QTimeEdit:focus,QSpinBox:focus {
            border:2px solid #356b92;
        }
        QPushButton { background:#17324d; color:white; border:0; border-radius:9px; padding:10px 16px; font-size:14px; font-weight:600; }
        QPushButton:hover { background:#244d70; }
        QPushButton:pressed { background:#10283d; }
        QCheckBox { spacing:8px; font-size:14px; }
        QTableWidget { background:white; alternate-background-color:#f6f8fa; border:1px solid #d8e0e7; border-radius:8px; gridline-color:#e6ebef; font-size:14px; }
        QHeaderView::section { background:#edf2f6; color:#243746; padding:9px; border:0; border-bottom:1px solid #ccd6df; font-weight:700; }
        QSplitter::handle { background:#d5dde5; height:7px; margin:3px 0; border-radius:3px; }
        QStatusBar { background:#17324d; color:white; }
        QStatusBar QLabel { color:white; font-weight:700; padding:4px 10px; }
        """)
        self.autosave=QTimer(self); self.autosave.timeout.connect(self.autosave_session); self.autosave.start(15000)
        QTimer.singleShot(500,self.restore_draft)
    def update_wallclock(self):
        self.wallclock.setText("LIVE  "+QTime.currentTime().toString("HH:mm:ss"))
    def session_ui(self):
        w=QWidget(); v=QVBoxLayout(w); top=QHBoxLayout()
        title=QLabel("Sitzungsnotiz"); title.setStyleSheet("font-size:26px;font-weight:700")
        self.clock=QLabel("00:00:00"); self.clock.setAlignment(Qt.AlignCenter); self.clock.setStyleSheet("font-size:32px;font-weight:800;padding:12px;border:2px solid #777;border-radius:10px")
        top.addWidget(title); top.addStretch(); top.addWidget(self.clock); v.addLayout(top)
        f=QFormLayout(); f.setLabelAlignment(Qt.AlignRight); f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit()
        for field in (self.s_last,self.s_first,self.s_dob): field.setMinimumWidth(420); field.setMinimumHeight(38)
        self.s_date=QDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_start=QTimeEdit(); self.s_end=QTimeEdit()
        self.s_type=QComboBox(); self.s_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"])
        self.s_red=QCheckBox("Ermäßigter Satz")
        for a,b in [("Nachname",self.s_last),("Vorname",self.s_first),("Geburtsdatum",self.s_dob),("Datum",self.s_date),("Beginn",self.s_start),("Ende",self.s_end),("Art",self.s_type)]:f.addRow(a,b)
        self.s_last.editingFinished.connect(self.fill_session_client); self.s_first.editingFinished.connect(self.fill_session_client)
        f.addRow("",self.s_red); v.addLayout(f)
        self.notes=QTextEdit(); self.notes.setPlaceholderText("Therapienotizen per Tastatur …"); self.notes.setMinimumHeight(100); self.notes.setStyleSheet("font-size:18px;padding:10px")
        inkhead=QHBoxLayout(); inkhead.addWidget(QLabel("Handschrift / Touch / Stift"))
        self.ink=InkCanvas()
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo)
        eraser=QCheckBox("Radierer"); eraser.toggled.connect(self.ink.set_eraser)
        width=QSpinBox(); width.setRange(1,10); width.setValue(3); width.setSuffix(" px"); width.valueChanged.connect(self.ink.set_width)
        clearink=QPushButton("Zeichenfläche löschen"); clearink.clicked.connect(self.ink.clear)
        inkhead.addStretch(); inkhead.addWidget(QLabel("Stärke")); inkhead.addWidget(width); inkhead.addWidget(eraser); inkhead.addWidget(undo); inkhead.addWidget(clearink)
        inkbox=QWidget(); inkv=QVBoxLayout(inkbox); inkv.setContentsMargins(0,0,0,0); inkv.addLayout(inkhead); inkv.addWidget(self.ink)
        splitter=QSplitter(Qt.Vertical); splitter.addWidget(self.notes); splitter.addWidget(inkbox); splitter.setStretchFactor(0,1); splitter.setStretchFactor(1,3); splitter.setSizes([180,430]); v.addWidget(splitter,1)
        h=QHBoxLayout()
        for text,fn in [("▶ Sitzung starten",self.start_session),("⏸ Pause/Fortsetzen",self.pause),("■ Sitzung beenden",self.end_session),("💾 Speichern",self.save_session)]: 
            b=QPushButton(text); b.setMinimumHeight(55); b.clicked.connect(fn); h.addWidget(b)
        v.addLayout(h); return w
    def helper_ui(self):
        w=QWidget(); v=QVBoxLayout(w)
        title=QLabel("Sitzungsassistent – Fragen & Interventionen"); title.setStyleSheet("font-size:24px;font-weight:700"); v.addWidget(title)
        hint=QLabel("Arbeitshilfe zur Gesprächsführung – keine automatische Diagnose."); hint.setWordWrap(True); v.addWidget(hint)
        topics={
          "Selbstwert / Selbstbewusstsein":{
            "Fragen":["In welchen Situationen zweifeln Sie besonders an sich?","Was sagen Sie innerlich zu sich, wenn etwas nicht gelingt?","Was gelingt Ihnen trotz der aktuellen Belastung?","Welche eigenen Grenzen möchten Sie klarer vertreten?","Wer würde zuerst bemerken, dass Sie selbstsicherer geworden sind – woran?"],
            "VT":["Selbstabwertende automatische Gedanken erfassen und prüfen.","Verhaltensübungen mit kleinen, erreichbaren Schritten planen.","Ressourcen- und Erfolgstagebuch als mögliche Übung besprechen."],
            "TP":["Wiederkehrende Beziehungserfahrungen und Selbstbewertungen explorieren.","Affekte bei Kritik, Ablehnung oder Anerkennung genauer wahrnehmen."],
            "Systemisch":["Ausnahmen vom Problem und vorhandene Kompetenzen erfragen.","Zirkuläre Fragen zur Wahrnehmung durch wichtige Bezugspersonen nutzen.","Skalierungsfragen und kleine nächste Schritte entwickeln."]},
          "Paar – Kommunikation / Konflikte":{
            "Fragen":["Woran merken Sie beide, dass ein Konflikt beginnt?","Was passiert typischerweise unmittelbar danach?","Was wünschen Sie sich in diesem Moment vom anderen?","Wann gelingt Kommunikation zwischen Ihnen besser?","Was möchten Sie trotz des Konflikts an Ihrer Beziehung bewahren?"],
            "VT":["Konkrete Konfliktsituationen und Verhalten beider Partner analysieren.","Ich-Botschaften, aktives Zuhören und vereinbarte Gesprächspausen erproben."],
            "TP":["Verletzlichkeit, Erwartungen und wiederkehrende Beziehungsmuster explorieren.","Bedeutung von Nähe, Zurückweisung und Abhängigkeit für beide Partner betrachten."],
            "Systemisch":["Interaktionskreislauf statt Schuldfrage sichtbar machen.","Zirkuläre Fragen, Perspektivwechsel und Ressourcen des Paares nutzen."]},
          "Depressive Beschwerden":{
            "Fragen":["Was belastet Sie derzeit am stärksten?","Was hat sich bei Stimmung, Interesse oder Antrieb verändert?","Wie sind Schlaf, Appetit und Konzentration?","Was gibt Ihnen aktuell noch Halt oder Entlastung?","Gab es Gedanken, nicht mehr leben zu wollen oder sich etwas anzutun?"],
            "VT":["Aktivitätsniveau und Verstärkerverlust explorieren.","Kleine realistische Aktivitäten und Tagesstruktur besprechen.","Belastende Gedanken und deren Wirkung untersuchen."],
            "TP":["Aktuelle Auslöser, Verluste, Konflikte und Beziehungserfahrungen explorieren.","Umgang mit Ärger, Schuld, Trauer und Selbstwert betrachten."],
            "Systemisch":["Ausnahmen und unterstützende Beziehungen identifizieren.","Veränderungen im sozialen System und hilfreiche Rückmeldeschleifen betrachten."]},
          "Stress / Überlastung":{
            "Fragen":["Welche Anforderungen kosten Sie aktuell am meisten Kraft?","Woran merken Sie frühzeitig, dass Ihre Belastungsgrenze erreicht ist?","Was können Sie beeinflussen – und was derzeit nicht?","Welche Erholungszeiten funktionieren tatsächlich?","Was müsste sich in den nächsten zwei Wochen verändern, damit es etwas leichter wird?"],
            "VT":["Belastungen, Bewertungen und Bewältigungsverhalten strukturiert erfassen.","Erholung, Priorisierung, Grenzen und konkrete Verhaltensschritte planen."],
            "TP":["Innere Ansprüche, Schuldgefühle und Konflikte zwischen eigenen und fremden Erwartungen explorieren.","Wiederkehrende Muster von Leistung, Anerkennung und Überforderung betrachten."],
            "Systemisch":["Rollen, Erwartungen und Wechselwirkungen im Umfeld sichtbar machen.","Ressourcen, Unterstützer und veränderbare Rahmenbedingungen aktivieren."]},
          "Trauer / Verlust":{
            "Fragen":["Was vermissen Sie im Moment am stärksten?","Welche Situationen machen den Verlust besonders spürbar?","Was hilft Ihnen, die Verbindung zur verstorbenen oder verlorenen Person auf eine gute Weise zu bewahren?","Wer kann Sie in schweren Momenten unterstützen?","Was darf trotz der Trauer langsam wieder Raum bekommen?"],
            "VT":["Alltag, Rückzug und hilfreiche Aktivitäten behutsam betrachten.","Belastende Bewertungen und Schuldgedanken explorieren, ohne Trauer zu pathologisieren."],
            "TP":["Bedeutung der Beziehung, Ambivalenzen und Verlustaffekte explorieren.","Frühere Verlusterfahrungen und aktuelle Beziehungsmuster berücksichtigen."],
            "Systemisch":["Veränderungen in Familie und Rollen nach dem Verlust betrachten.","Rituale, Erinnerungen und soziale Ressourcen einbeziehen."]},
          "Trennung / Beziehungskrise":{
            "Fragen":["Was ist für Sie an der aktuellen Situation am schwersten?","Was möchten Sie klären, bevor Sie eine Entscheidung treffen?","Welche Bedürfnisse kommen in der Beziehung zu kurz?","Welche Grenzen sind für Sie nicht verhandelbar?","Wie würde ein respektvoller nächster Schritt aussehen – unabhängig vom Ausgang?"],
            "VT":["Konkrete Situationen, Gedanken, Gefühle und Reaktionen auseinanderhalten.","Entscheidungsdruck reduzieren und kurzfristig hilfreiche Handlungen planen."],
            "TP":["Bindungswünsche, Kränkungen, Verlustängste und wiederkehrende Beziehungsmuster explorieren.","Ambivalenzen aushalten und deren Bedeutung verstehen."],
            "Systemisch":["Beziehungsmuster und gegenseitige Reaktionen zirkulär betrachten.","Auswirkungen möglicher Veränderungen auf Familie und Umfeld einbeziehen."]},
          "Eifersucht / Vertrauen":{
            "Fragen":["Was löst die Eifersucht typischerweise aus?","Was befürchten Sie in diesem Moment?","Welche Verhaltensweisen geben kurzfristig Sicherheit, verschärfen aber langfristig den Konflikt?","Was würde Vertrauen für Sie konkret bedeuten?","Welche Vereinbarungen wären für beide Seiten fair und überprüfbar?"],
            "VT":["Auslöser, Bewertungen, Kontrollverhalten und kurzfristige Verstärkung analysieren.","Alternative Reaktionen und tolerierbare Unsicherheit schrittweise erarbeiten."],
            "TP":["Ängste vor Verlust, Beschämung oder Austauschbarkeit explorieren.","Frühere Bindungs- und Beziehungserfahrungen berücksichtigen."],
            "Systemisch":["Eifersuchts- und Rückzugsschleifen zwischen beiden Partnern sichtbar machen.","Transparente Regeln und beobachtbare Veränderungen gemeinsam definieren."]},
          "Schlafprobleme":{
            "Fragen":["Wie sehen Ihre Schlafenszeiten an typischen Tagen aus?","Was passiert gedanklich und körperlich, wenn Sie nicht einschlafen können?","Was tun Sie nachts, wenn Sie wach liegen?","Welche Faktoren verbessern oder verschlechtern Ihren Schlaf?","Wie wirkt sich der Schlafmangel tagsüber aus?"],
            "VT":["Schlafgewohnheiten und aufrechterhaltende Verhaltensweisen erfassen.","Bei passender Indikation evidenzbasierte schlafbezogene Verhaltensstrategien besprechen."],
            "TP":["Nächtliche Grübelthemen, Affekte und aktuelle Konflikte explorieren.","Bedeutung von Kontrolle, Loslassen und innerer Anspannung betrachten."],
            "Systemisch":["Tagesstruktur, familiäre Routinen und Umweltfaktoren einbeziehen.","Unterstützende Veränderungen im Alltagssystem identifizieren."]},
          "Angst / Panik":{
            "Fragen":["Wann tritt die Angst besonders auf?","Welche Gedanken und Körperempfindungen bemerken Sie zuerst?","Was tun Sie, um die Angst zu vermeiden oder zu kontrollieren?","Was befürchten Sie, könnte im schlimmsten Fall passieren?","Wann war die Angst geringer und was war dann anders?"],
            "VT":["Angstkreislauf und Sicherheitsverhalten gemeinsam herausarbeiten.","Geeignete Expositionsschritte nur nach individueller Prüfung planen."],
            "TP":["Bedeutung der Angst in aktuellen Beziehungen und Konflikten explorieren.","Affekte und innere Konflikte rund um Autonomie, Nähe oder Kontrolle betrachten."],
            "Systemisch":["Funktion und Kontext der Angst im Lebenssystem explorieren.","Ausnahmen, Ressourcen und Perspektiven wichtiger Bezugspersonen einbeziehen."]}
        }
        row=QHBoxLayout(); self.help_topic=QComboBox(); self.help_topic.addItems(topics.keys()); row.addWidget(QLabel("Thema")); row.addWidget(self.help_topic,1); v.addLayout(row)
        self.help_text=QTextEdit(); self.help_text.setReadOnly(True); self.help_text.setStyleSheet("font-size:17px;padding:10px"); v.addWidget(self.help_text,1)
        def render():
            d=topics[self.help_topic.currentText()]; parts=["FRAGEN"]+["• "+x for x in d["Fragen"]]
            for key in ["VT","TP","Systemisch"]: parts+=["",key]+["• "+x for x in d[key]]
            self.help_text.setPlainText("\n".join(parts))
        self.help_topic.currentTextChanged.connect(render); render()
        add=QPushButton("Ausgewählten Text in Sitzungsnotiz übernehmen"); add.setMinimumHeight(55)
        def add_note():
            x=self.help_text.textCursor().selectedText().strip()
            if not x:return QMessageBox.information(self,"Auswahl","Bitte zuerst eine Frage oder einen Hinweis markieren.")
            self.notes.append(x)
        add.clicked.connect(add_note); v.addWidget(add)
        return w

    def restore_draft(self):
        p=ROOT/"Sitzung_Autosave.json"
        if not p.exists(): return
        try:
            d=json.loads(p.read_text(encoding="utf-8"))
            if QMessageBox.question(self,"Sitzung wiederherstellen","Es gibt eine automatisch gespeicherte Sitzung. Wiederherstellen?")==QMessageBox.Yes:
                self.s_last.setText(d.get("last","")); self.s_first.setText(d.get("first","")); self.s_dob.setText(d.get("dob",""))
                qd=QDate.fromString(d.get("date",""),"yyyy-MM-dd")
                if qd.isValid(): self.s_date.setDate(qd)
                qs=QTime.fromString(d.get("start",""),"HH:mm")
                if qs.isValid(): self.s_start.setTime(qs)
                qe=QTime.fromString(d.get("end",""),"HH:mm")
                if qe.isValid(): self.s_end.setTime(qe)
                self.s_type.setCurrentText(d.get("type","Einzeltherapie")); self.s_red.setChecked(bool(d.get("reduced",False))); self.notes.setPlainText(d.get("notes",""))
                self.acc=int(d.get("seconds",0)); self.running=False; self.started=None
        except Exception: pass
    def autosave_session(self):
        if not self.running and not self.notes.toPlainText().strip(): return
        draft={"last":self.s_last.text(),"first":self.s_first.text(),"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"seconds":self.elapsed(),"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"running":self.running}
        (ROOT/"Sitzung_Autosave.json").write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding="utf-8")
    def fill_session_client(self):
        last,first=self.s_last.text().strip().lower(),self.s_first.text().strip().lower()
        x=next((c for c in DB["clients"] if c.get("last","").lower()==last and (not first or c.get("first","").lower()==first)),None)
        if x:
            self.s_first.setText(x.get("first","")); self.s_last.setText(x.get("last","")); self.s_dob.setText(x.get("dob",""))
    def start_session(self):
        now=datetime.now(); self.s_date.setDate(QDate.currentDate()); self.started=now; self.acc=0; self.running=True; self.update_wallclock()
    def pause(self):
        if self.running and self.started: self.acc+=(datetime.now()-self.started).total_seconds(); self.running=False
        else:self.started=datetime.now(); self.running=True
    def elapsed(self):
        x=self.acc
        if self.running and self.started:x+=(datetime.now()-self.started).total_seconds()
        return int(x)
    def tick(self):
        s=self.elapsed(); self.clock.setText(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}")
    def end_session(self):
        if self.running and self.started:self.acc+=(datetime.now()-self.started).total_seconds()
        self.running=False
        # Endzeit wird beim Beenden mit der realen Uhrzeit vorbelegt, bleibt aber editierbar.
        self.s_end.setTime(QTime.currentTime()); self.update_wallclock()
    def save_session(self):
        last=self.s_last.text().strip(); first=self.s_first.text().strip()
        if not last or not first:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
        c=next((x for x in DB["clients"] if x["last"].lower()==last.lower() and x["first"].lower()==first.lower()),None)
        if not c:c={"last":last,"first":first,"dob":self.s_dob.text().strip(),"address":"","diagnosis":""}; DB["clients"].append(c)
        else: c["dob"]=self.s_dob.text().strip() or c.get("dob","")
        # Abrechnungsdauer folgt den manuell dokumentierten Beginn-/Endzeiten.
        # Der Live-Timer bleibt eine unabhängige Kontrollanzeige.
        start_t=self.s_start.time(); end_t=self.s_end.time()
        mins=start_t.secsTo(end_t)//60 if start_t.isValid() and end_t.isValid() else 0
        if mins <= 0: mins=max(1,round(self.elapsed()/60))
        rec={"id":datetime.now().strftime("%Y%m%d%H%M%S"),"last":last,"first":first,"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"minutes":mins,"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"billed":False}
        DB["sessions"].append(rec); save_data(); d=client_dir(c)/"Sitzungen"; (d/f"{rec['date']}_Sitzung.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
        inkfile=d/f"{rec['date']}_{rec['id']}_Handschrift.png"; self.ink.save_png(inkfile); rec["ink_file"]=str(inkfile); save_data()
        auto=ROOT/"Sitzung_Autosave.json"
        if auto.exists(): auto.unlink()
        QMessageBox.information(self,"Gespeichert",f"Sitzung gespeichert: {mins} Minuten.")
    def invoice_ui(self):
        w=QWidget(); v=QVBoxLayout(w); f=QFormLayout()
        self.i_no=QLineEdit(next_no()); self.i_last=QLineEdit(); self.i_first=QLineEdit(); self.i_addr=QLineEdit(); self.i_diag=QLineEdit(); self.pending_sessions=None
        self.i_date=QDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigt")
        for a,b in [("Rechnungsnummer",self.i_no),("Nachname",self.i_last),("Vorname",self.i_first),("Adresse (optional)",self.i_addr),("Diagnose (optional)",self.i_diag),("Leistungsdatum",self.i_date),("Leistung",self.i_type),("Dauer Minuten",self.i_min)]:f.addRow(a,b)
        self.i_last.editingFinished.connect(self.fill_invoice_client); self.i_first.editingFinished.connect(self.fill_invoice_client)
        f.addRow("",self.i_red); v.addLayout(f)
        q=QPushButton("Unberechnete Sitzungen laden / Sammelrechnung"); q.setMinimumHeight(50); q.clicked.connect(self.load_unbilled_sessions); v.addWidget(q)
        preview=QPushButton("Rechnung vor Erstellung prüfen"); preview.setMinimumHeight(50)
        def preview_invoice():
            no=self.i_no.text().strip(); last=self.i_last.text().strip(); first=self.i_first.text().strip()
            rows=self.pending_sessions
            if rows:
                lines="\n".join(f'{s.get("date","")}  {s.get("start","")}–{s.get("end","")}  {s.get("minutes",0)} Min.  {s.get("type","")}  {amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))):.2f} €' for s in rows)
                total=sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows)
            else:
                total=amount_for(self.i_min.value(),self.i_type.currentText(),self.i_red.isChecked()); lines=f'{self.i_date.date().toString("dd.MM.yyyy")}  {self.i_min.value()} Min.  {self.i_type.currentText()}  {total:.2f} €'
            QMessageBox.information(self,"Rechnung prüfen",f"Rechnung {no}\n{first} {last}\n\n{lines}\n\nGesamt: {total:.2f} €")
        preview.clicked.connect(preview_invoice); v.addWidget(preview)
        b=QPushButton("PDF-Rechnung erstellen"); b.setMinimumHeight(60); b.clicked.connect(self.make_invoice); v.addWidget(b); return w
    def fill_invoice_client(self):
        last,first=self.i_last.text().strip().lower(),self.i_first.text().strip().lower()
        x=next((c for c in DB["clients"] if c.get("last","").lower()==last and (not first or c.get("first","").lower()==first)),None)
        if x:
            self.i_first.setText(x.get("first","")); self.i_last.setText(x.get("last","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis",""))
    def load_unbilled_sessions(self):
        last,first=self.i_last.text().strip().lower(),self.i_first.text().strip().lower()
        rows=[s for s in DB["sessions"] if not s.get("billed") and s.get("last","").lower()==last and s.get("first","").lower()==first]
        if not rows: return QMessageBox.information(self,"Sitzungen","Keine unberechneten Sitzungen für diesen Klienten gefunden.")
        self.pending_sessions=rows
        details="\n".join(f'{s.get("date","")} | {s.get("start","")}–{s.get("end","")} | {s.get("minutes",0)} Min. | {s.get("type","")}' for s in rows)
        total=sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows)
        QMessageBox.information(self,"Quartals-/Sammelrechnung",f"{len(rows)} unberechnete Sitzungen gefunden.\n\n{details}\n\nGesamt: {total:.2f} €\n\nBitte vor PDF-Erstellung kontrollieren.")
    def make_invoice(self):
        no=self.i_no.text().strip()
        if any(x["number"]==no for x in DB["invoices"]):return QMessageBox.warning(self,"Doppelt","Diese Rechnungsnummer existiert bereits.")
        last,first=self.i_last.text().strip(),self.i_first.text().strip()
        if not last or not first:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
        rows=getattr(self,"pending_sessions",None)
        if rows:
            mins=sum(int(s.get("minutes",0)) for s in rows); typ="Sammelrechnung"; amt=round(sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows),2)
        else:
            mins=self.i_min.value(); typ=self.i_type.currentText(); amt=round(amount_for(mins,typ,self.i_red.isChecked()),2)
        c=next((x for x in DB["clients"] if x.get("last","").lower()==last.lower() and x.get("first","").lower()==first.lower()),None)
        if not c:
            c={"last":last,"first":first,"dob":"","address":self.i_addr.text().strip(),"diagnosis":self.i_diag.text().strip()}; DB["clients"].append(c)
        else:
            if self.i_addr.text().strip(): c["address"]=self.i_addr.text().strip()
            if self.i_diag.text().strip(): c["diagnosis"]=self.i_diag.text().strip()
        d=client_dir(c)/"Rechnungen"; pdf=d/f"Rechnung_{no}.pdf"
        can=canvas.Canvas(str(pdf),pagesize=A4); W,H=A4
        # Praxis-Logo als druckfähige Wortmarke
        can.setFillColor(HexColor("#17324d")); can.circle(W-92,H-63,31,stroke=1,fill=0)
        can.setFont("Helvetica-Bold",12); can.drawCentredString(W-92,H-61,"EK")
        can.setFillColor(HexColor("#000000"))
        can.setFont("Helvetica-Bold",13); can.drawString(50,H-55,"Erdoğan Kulanoğlu – Psychologische Privatpraxis")
        can.setFont("Helvetica",9); can.drawString(50,H-72,"Psychologe M. Sc. · Sozialarbeiter B.A. · Heilpraktiker für Psychotherapie")
        can.drawString(50,H-87,"Schönwalder Str. 59, 13585 Berlin · Steuernummer: 19/405/00254")
        can.setFont("Helvetica-Bold",16); can.drawString(50,H-135,f"Rechnung {no}")
        can.setFont("Helvetica",11); y=H-170; can.drawString(50,y,f"{first} {last}"); y-=16
        if self.i_addr.text().strip():can.drawString(50,y,self.i_addr.text().strip()); y-=16
        if self.i_diag.text().strip():can.drawString(50,y,"Diagnose: "+self.i_diag.text().strip()); y-=22
        if rows:
            for s in rows:
                a=amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False)))
                can.drawString(50,y,f'{s.get("date","")}   {s.get("start","")}–{s.get("end","")}   {s.get("minutes",0)} Min.   {s.get("type","")}'); can.drawRightString(W-50,y,f"{a:.2f} EUR"); y-=18
        else:
            can.drawString(50,y,f"{self.i_date.date().toString('dd.MM.yyyy')}   {mins} Min.   {typ}"); can.drawRightString(W-50,y,f"{amt:.2f} EUR"); y-=18
        y-=17
        can.setFont("Helvetica-Bold",12); can.drawRightString(W-50,y,f"Gesamt: {amt:.2f} EUR"); y-=35
        can.setFont("Helvetica",9); can.drawString(50,y,"Zahlbar innerhalb von 14 Tagen. Verwendungszweck: "+no); y-=14
        can.drawString(50,y,"IBAN DE13 5001 0517 5404 0811 30 · BIC INGDDEFFXXX"); y-=14
        can.drawString(50,y,"Leistungen als Heilpraktiker sind nach § 4 Nr. 14 Buchstabe a UStG umsatzsteuerbefreit.")
        can.drawString(50,55,"Elektronisch erstellt und ohne Unterschrift/Stempel gültig."); can.save()
        DB["invoices"].append({"number":no,"date":datetime.now().strftime("%Y-%m-%d"),"client":f"{last}, {first}","amount":amt,"status":"offen","paid_date":""})
        if rows:
            ids={s.get("id") for s in rows}
            for s in DB["sessions"]:
                if s.get("id") in ids: s["billed"]=True; s["invoice_number"]=no
            self.pending_sessions=None
        save_data(); update_excel(); self.i_no.setText(next_no())
        QMessageBox.information(self,"Fertig",f"PDF gespeichert:\n{pdf}")
    def clients_ui(self):
        w=QWidget(); v=QVBoxLayout(w); t=QTableWidget(0,3); t.setHorizontalHeaderLabels(["Nachname","Vorname","Geburtsdatum"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for c in DB["clients"]: r=t.rowCount();t.insertRow(r);[t.setItem(r,j,QTableWidgetItem(str(c.get(k,"")))) for j,k in enumerate(["last","first","dob"])]
        v.addWidget(t)
        opensessions=QPushButton("Sitzungen des ausgewählten Klienten öffnen"); opensessions.setMinimumHeight(45)
        def show_sessions():
            r=t.currentRow()
            if r<0:return
            last=t.item(r,0).text(); first=t.item(r,1).text()
            rows=[s for s in DB["sessions"] if s.get("last")==last and s.get("first")==first]
            dlg=QDialog(self); dlg.setWindowTitle(f"Sitzungen – {first} {last}"); dlg.resize(900,600); lay=QVBoxLayout(dlg)
            st=QTableWidget(0,6); st.setHorizontalHeaderLabels(["Datum","Beginn","Ende","Min.","Art","Abgerechnet"]); st.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            for s in sorted(rows,key=lambda x:x.get("date",""),reverse=True):
                rr=st.rowCount(); st.insertRow(rr)
                vals=[s.get("date",""),s.get("start",""),s.get("end",""),str(s.get("minutes","")),s.get("type",""),"Ja" if s.get("billed") else "Nein"]
                for j,x in enumerate(vals):st.setItem(rr,j,QTableWidgetItem(x))
            lay.addWidget(st)
            edit=QPushButton("Ausgewählte Sitzung korrigieren")
            def edit_selected():
                rr=st.currentRow()
                if rr<0:return
                date=st.item(rr,0).text(); start=st.item(rr,1).text(); s=next((x for x in rows if x.get("date")==date and x.get("start")==start),None)
                if not s:return
                ed=QDialog(dlg); ed.setWindowTitle("Sitzung korrigieren"); form=QFormLayout(ed)
                mins=QSpinBox(); mins.setRange(1,1000); mins.setValue(int(s.get("minutes",45)))
                typ=QComboBox(); typ.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"]); typ.setCurrentText(s.get("type","Einzeltherapie"))
                note=QTextEdit(); note.setPlainText(s.get("notes","")); form.addRow("Dauer Minuten",mins); form.addRow("Art",typ); form.addRow("Notiz",note)
                buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); form.addRow(buttons)
                def save_edit():
                    s["minutes"]=mins.value(); s["type"]=typ.currentText(); s["notes"]=note.toPlainText(); s["corrected_at"]=datetime.now().isoformat(timespec="seconds"); save_data()
                    d=client_dir({"last":last,"first":first})/"Sitzungen"; jf=d/f'{s.get("date","")}_Sitzung.json'; jf.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding="utf-8"); st.item(rr,3).setText(str(s["minutes"])); st.item(rr,4).setText(s["type"]); ed.accept()
                buttons.accepted.connect(save_edit); buttons.rejected.connect(ed.reject); ed.exec()
            edit.clicked.connect(edit_selected); lay.addWidget(edit)
            view=QPushButton("Ausgewählte Sitzung / Notiz öffnen")
            def open_selected():
                rr=st.currentRow()
                if rr<0:return
                date=st.item(rr,0).text(); start=st.item(rr,1).text()
                s=next((x for x in rows if x.get("date")==date and x.get("start")==start),None)
                if not s:return
                nd=QDialog(dlg); nd.setWindowTitle(f"Sitzungsnotiz {date}"); nd.resize(900,700); nv=QVBoxLayout(nd)
                tx=QTextEdit(); tx.setReadOnly(True); tx.setPlainText(s.get("notes","")); nv.addWidget(tx)
                ink=s.get("ink_file","")
                if ink and Path(ink).exists():
                    lab=QLabel(); pix=QPixmap(ink); lab.setPixmap(pix.scaled(820,380,Qt.KeepAspectRatio,Qt.SmoothTransformation)); lab.setAlignment(Qt.AlignCenter); nv.addWidget(lab)
                buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(nd.reject); nv.addWidget(buttons); nd.exec()
            view.clicked.connect(open_selected); lay.addWidget(view); close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dlg.reject); lay.addWidget(close); dlg.exec()
        opensessions.clicked.connect(show_sessions); v.addWidget(opensessions)
        openink=QPushButton("Letzte Handschrift des ausgewählten Klienten anzeigen"); openink.setMinimumHeight(45)
        def show_ink():
            r=t.currentRow()
            if r<0:return
            last=t.item(r,0).text(); first=t.item(r,1).text(); d=client_dir({"last":last,"first":first})/"Sitzungen"; files=sorted(d.glob("*_Handschrift.png"),reverse=True)
            if not files:return QMessageBox.information(self,"Handschrift","Keine handschriftliche Notiz gefunden.")
            dlg=QMessageBox(self); dlg.setWindowTitle("Handschriftliche Notiz"); pix=QPixmap(str(files[0])); dlg.setIconPixmap(pix.scaled(900,550,Qt.KeepAspectRatio,Qt.SmoothTransformation)); dlg.exec()
        openink.clicked.connect(show_ink); v.addWidget(openink)
        b=QPushButton("Klientenliste aktualisieren"); b.setMinimumHeight(45)
        def refresh():
            t.setRowCount(0)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                r=t.rowCount(); t.insertRow(r)
                for j,k in enumerate(["last","first","dob"]): t.setItem(r,j,QTableWidgetItem(str(cc.get(k,""))))
        b.clicked.connect(refresh); v.addWidget(b); return w
    def invoices_ui(self):
        w=QWidget(); v=QVBoxLayout(w); t=QTableWidget(0,5); t.setHorizontalHeaderLabels(["Nr.","Datum","Klient","Status","Betrag"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i in reversed(DB["invoices"]):
            r=t.rowCount(); t.insertRow(r)
            vals=[i.get("number",""),i.get("date",""),i.get("client",""),i.get("status","offen"),f'{float(i.get("amount",0)):.2f} €']
            for j,x in enumerate(vals): t.setItem(r,j,QTableWidgetItem(str(x)))
        v.addWidget(t)
        h=QHBoxLayout()
        paid=QPushButton("Ausgewählte Rechnung als bezahlt markieren"); paid.setMinimumHeight(50)
        def mark_paid():
            r=t.currentRow()
            if r<0:return
            no=t.item(r,0).text(); inv=next((x for x in DB["invoices"] if x.get("number")==no),None)
            if inv: inv["status"]="bezahlt"; inv["paid_date"]=datetime.now().strftime("%Y-%m-%d"); save_data(); update_excel(); t.item(r,3).setText("bezahlt")
        paid.clicked.connect(mark_paid); h.addWidget(paid)
        backup=QPushButton("Datensicherung erstellen"); backup.setMinimumHeight(50)
        def do_backup():
            dest=ROOT/"Backups"/datetime.now().strftime("Backup_%Y-%m-%d_%H-%M-%S"); dest.mkdir(parents=True,exist_ok=True)
            if DATA.exists(): shutil.copy2(DATA,dest/DATA.name)
            if DBFILE.exists():
                con=sqlite3.connect(DBFILE); out=sqlite3.connect(dest/DBFILE.name); con.backup(out); out.close(); con.close()
            for x in (ROOT/"Einnahmen").glob("*.xlsx"): shutil.copy2(x,dest/x.name)
            docs=dest/"Klienten"; shutil.copytree(ROOT/"Klienten",docs,dirs_exist_ok=True)
            QMessageBox.information(self,"Sicherung",f"Sicherung erstellt:\n{dest}")
        backup.clicked.connect(do_backup); h.addWidget(backup); v.addLayout(h); return w
    def dashboard_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(18)
        y=str(datetime.now().year); billed=sum(float(i.get("amount",0)) for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status")!="storniert"); paid=sum(float(i.get("amount",0)) for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status")=="bezahlt"); open_amt=billed-paid
        title=QLabel("Übersicht"); title.setObjectName("pageTitle"); sub=QLabel(f"Psychologische Privatpraxis · {y}"); sub.setObjectName("pageSub"); v.addWidget(title); v.addWidget(sub)
        cards=QGridLayout(); cards.setSpacing(14)
        def card(caption,value):
            box=QFrame(); box.setObjectName("statCard"); q=QVBoxLayout(box); a=QLabel(caption); a.setObjectName("cardCaption"); b=QLabel(value); b.setObjectName("cardValue"); q.addWidget(a);q.addWidget(b);return box
        cards.addWidget(card("ABGERECHNET",f"{billed:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,0)
        cards.addWidget(card("BEZAHLT",f"{paid:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,1)
        cards.addWidget(card("OFFEN",f"{open_amt:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,2)
        cards.addWidget(card("KLIENTEN",str(len(DB["clients"]))),1,0); cards.addWidget(card("SITZUNGEN",str(len(DB["sessions"]))),1,1); cards.addWidget(card("OFFENE RECHNUNGEN",str(sum(1 for i in DB["invoices"] if i.get("status","offen")=="offen"))),1,2); v.addLayout(cards)
        actions=QHBoxLayout(); new_session=QPushButton("Neue Sitzung"); new_session.setMinimumHeight(52); new_session.clicked.connect(lambda:self.nav.setCurrentRow(1)); new_invoice=QPushButton("Neue Rechnung"); new_invoice.setMinimumHeight(52); new_invoice.clicked.connect(lambda:self.nav.setCurrentRow(4)); clients=QPushButton("Klienten öffnen"); clients.setMinimumHeight(52); clients.clicked.connect(lambda:self.nav.setCurrentRow(3)); actions.addWidget(new_session);actions.addWidget(new_invoice);actions.addWidget(clients);v.addLayout(actions)
        info=QLabel(f"Datenbank: {DBFILE}\nDatenordner: {ROOT}"); info.setObjectName("infoBox"); info.setWordWrap(True); v.addWidget(info); v.addStretch(); return w
app=QApplication(sys.argv); app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}"); win=Main();win.show();sys.exit(app.exec())
