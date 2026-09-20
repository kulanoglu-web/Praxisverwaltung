import sys, json, os, re, math, shutil, sqlite3, base64, hashlib
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog,QSplitter,QListWidget,QStackedWidget,QFrame,QGridLayout,QInputDialog)
from PySide6.QtCore import QDate,QTime
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QDesktopServices
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from cryptography.fernet import Fernet, InvalidToken

ROOT=Path.home()/"Documents"/"Praxisverwaltung"
DBDIR=ROOT/"Datenbank"; DBFILE=DBDIR/"Praxisverwaltung.db"
KEYFILE=DBDIR/"praxis.key"

def encryption_key():
    DBDIR.mkdir(parents=True,exist_ok=True)
    if KEYFILE.exists(): return KEYFILE.read_bytes()
    key=Fernet.generate_key(); KEYFILE.write_bytes(key)
    try: os.chmod(KEYFILE,0o600)
    except Exception: pass
    return key

def encrypt_text(value):
    if value is None or value=="": return value or ""
    s=str(value)
    if s.startswith("enc:"): return s
    return "enc:"+Fernet(encryption_key()).encrypt(s.encode("utf-8")).decode("ascii")

def decrypt_text(value):
    if not value: return ""
    s=str(value)
    if not s.startswith("enc:"): return s
    try:return Fernet(encryption_key()).decrypt(s[4:].encode("ascii")).decode("utf-8")
    except (InvalidToken,ValueError):return "[Verschlüsselte Daten nicht lesbar]"

def encrypt_file(path):
    p=Path(path)
    if not p.exists(): return ""
    out=p.with_suffix(p.suffix+".enc"); out.write_bytes(Fernet(encryption_key()).encrypt(p.read_bytes()))
    try:p.unlink()
    except Exception:pass
    return str(out)

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
    def load_png(self,path):
        img=QImage(str(path))
        if not img.isNull(): self.image=img.convertToFormat(QImage.Format_ARGB32).scaled(1200,700,Qt.IgnoreAspectRatio,Qt.SmoothTransformation); self.history=[]; self.update(); return True
        return False
from openpyxl import Workbook, load_workbook

DATA=ROOT/"praxisdaten.json.enc"
for p in [ROOT/"Klienten",ROOT/"Einnahmen",ROOT/"Backups",DBDIR]: p.mkdir(parents=True,exist_ok=True)

def init_sqlite():
    con=sqlite3.connect(DBFILE); con.execute("PRAGMA foreign_keys=ON"); con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
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
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      display_name TEXT NOT NULL, role TEXT DEFAULT 'Therapeut', active INTEGER DEFAULT 1,
      password_hash TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS audit_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, username TEXT,
      action TEXT NOT NULL, details TEXT);
    CREATE TABLE IF NOT EXISTS fee_rates(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
      minutes INTEGER NOT NULL DEFAULT 45, amount REAL NOT NULL DEFAULT 70,
      reduced_amount REAL, billing_mode TEXT DEFAULT 'proportional', active INTEGER DEFAULT 1);
    """)
    cols=[r[1] for r in con.execute("PRAGMA table_info(clients)").fetchall()]
    if "client_key" not in cols: con.execute("ALTER TABLE clients ADD COLUMN client_key TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_clients_client_key ON clients(client_key)")
    defaults={
      "practice_name":"Psychologische Privatpraxis","owner_name":"Erdoğan Kulanoğlu",
      "qualifications":"Psychologe M. Sc. · Sozialarbeiter B.A. · Heilpraktiker für Psychotherapie",
      "address":"Schönwalder Str. 59, 13585 Berlin","phone":"0176 43605753","fax":"030 43205928",
      "email":"info@psychologe-spandau.de","website":"www.psychologe-spandau.de","tax_number":"19/405/00254",
      "iban":"DE13 5001 0517 5404 0811 30","bic":"INGDDEFFXXX","paypal":"erdogankulanoglu@hotmail.com",
      "manufacturer":"Erdoğan Kulanoğlu","copyright":"© 2026 Erdoğan Kulanoğlu. Alle Rechte vorbehalten.","logo_path":""
    }
    for k,v in defaults.items(): con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    for name,mins,amount,reduced,mode in [("Einzeltherapie",45,70,60,"proportional"),("Paargespräch",45,70,60,"proportional"),("Onlinegespräch",45,70,60,"proportional"),("Notfalltelefonat",30,45,45,"started_unit"),("Hausbesuch",45,70,60,"proportional_plus_travel")]:
        con.execute("INSERT OR IGNORE INTO fee_rates(name,minutes,amount,reduced_amount,billing_mode) VALUES(?,?,?,?,?)",(name,mins,amount,reduced,mode))
    con.commit(); con.close()

def sync_sqlite():
    init_sqlite(); con=sqlite3.connect(DBFILE); cur=con.cursor()
    for x in DB.get("clients",[]):
        ck=hashlib.sha256((x.get("first","").strip().lower()+"|"+x.get("last","").strip().lower()+"|"+x.get("dob","").strip()).encode("utf-8")).hexdigest()
        row=cur.execute("SELECT id FROM clients WHERE client_key=? ORDER BY id DESC LIMIT 1",(ck,)).fetchone()
        vals=(encrypt_text(x.get("first","")),encrypt_text(x.get("last","")),encrypt_text(x.get("dob","")),encrypt_text(x.get("address","")),encrypt_text(x.get("diagnosis","")),x.get("created_at",""),datetime.now().isoformat(timespec="seconds"),ck)
        if row: cur.execute("UPDATE clients SET first=?,last=?,dob=?,address=?,diagnosis=?,created_at=?,updated_at=?,client_key=? WHERE id=?",vals+(row[0],))
        else: cur.execute("INSERT INTO clients(first,last,dob,address,diagnosis,created_at,updated_at,client_key) VALUES(?,?,?,?,?,?,?,?)",vals)
    con.commit()
    for s in DB.get("sessions",[]):
        ck=hashlib.sha256((s.get("first","").strip().lower()+"|"+s.get("last","").strip().lower()+"|"+s.get("dob","").strip()).encode("utf-8")).hexdigest(); cur.execute("SELECT id FROM clients WHERE client_key=? ORDER BY id DESC LIMIT 1",(ck,)); row=cur.fetchone(); cid=row[0] if row else None
        cur.execute("""INSERT INTO sessions(id,client_id,date,start,end,minutes,type,reduced,notes,ink_file,billed,invoice_number,corrected_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET client_id=excluded.client_id,date=excluded.date,start=excluded.start,end=excluded.end,minutes=excluded.minutes,type=excluded.type,reduced=excluded.reduced,notes=excluded.notes,ink_file=excluded.ink_file,billed=excluded.billed,invoice_number=excluded.invoice_number,corrected_at=excluded.corrected_at""",(s.get("id"),cid,s.get("date",""),s.get("start",""),s.get("end",""),s.get("minutes",0),s.get("type",""),1 if s.get("reduced") else 0,encrypt_text(s.get("notes","")),encrypt_text(s.get("ink_file","")),1 if s.get("billed") else 0,s.get("invoice_number",""),s.get("corrected_at","")))
    for i in DB.get("invoices",[]):
        cur.execute("""INSERT INTO invoices(number,date,client,address,diagnosis,amount,status,paid_date,pdf)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(number) DO UPDATE SET date=excluded.date,client=excluded.client,address=excluded.address,diagnosis=excluded.diagnosis,amount=excluded.amount,status=excluded.status,paid_date=excluded.paid_date,pdf=excluded.pdf""",(i.get("number",""),i.get("date",""),encrypt_text(i.get("client","")),encrypt_text(i.get("address","")),encrypt_text(i.get("diagnosis","")),i.get("amount",0),i.get("status","offen"),i.get("paid_date",""),i.get("pdf","")))
        cur.execute("SELECT id FROM invoices WHERE number=?",(i.get("number",""),)); ir=cur.fetchone()
        if ir and i.get("items") is not None:
            iid=ir[0]; cur.execute("DELETE FROM invoice_items WHERE invoice_id=?",(iid,))
            for it in i.get("items",[]):
                cur.execute("""INSERT INTO invoice_items(invoice_id,session_id,service_date,start,end,minutes,type,reduced,amount)
                VALUES(?,?,?,?,?,?,?,?,?)""",(iid,it.get("id"),it.get("date",""),it.get("start",""),it.get("end",""),it.get("minutes",0),it.get("type",""),1 if it.get("reduced") else 0,it.get("amount",0)))
    con.commit(); con.close()

def get_setting(key,default=""):
    con=sqlite3.connect(DBFILE); row=con.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); con.close()
    return row[0] if row else default

def set_setting(key,value):
    con=sqlite3.connect(DBFILE); con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value))); con.commit(); con.close()

def password_hash(password,salt=None):
    salt=salt or os.urandom(16); digest=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,310000)
    return base64.b64encode(salt).decode()+":"+base64.b64encode(digest).decode()

def verify_password(password,stored):
    try:
        a,b=stored.split(":",1); salt=base64.b64decode(a); expected=base64.b64decode(b)
        got=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,310000)
        import hmac; return hmac.compare_digest(got,expected)
    except:return False

def audit(action,details="",username=""):
    con=sqlite3.connect(DBFILE); con.execute("INSERT INTO audit_log(created_at,username,action,details) VALUES(?,?,?,?)",(datetime.now().isoformat(timespec="seconds"),username,action,details)); con.commit(); con.close()

def get_fee_rates():
    con=sqlite3.connect(DBFILE); rows=con.execute("SELECT name,minutes,amount,reduced_amount,billing_mode FROM fee_rates WHERE active=1 ORDER BY id").fetchall(); con.close()
    return rows

def load_data():
    legacy=ROOT/"praxisdaten.json"
    if DATA.exists():
        try:return json.loads(decrypt_text(DATA.read_text(encoding="utf-8")))
        except:return {}
    if legacy.exists():
        try:
            d=json.loads(legacy.read_text(encoding="utf-8")); DATA.write_text(encrypt_text(json.dumps(d,ensure_ascii=False)),encoding="utf-8")
            legacy.unlink(); return d
        except:return {}
    return {}
DB=load_data(); DB.setdefault("clients",[]); DB.setdefault("sessions",[]); DB.setdefault("invoices",[])
init_sqlite(); sync_sqlite()

def save_data():
    DATA.write_text(encrypt_text(json.dumps(DB,ensure_ascii=False)),encoding="utf-8")
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
    ws.append(["Rechnungsnummer","Rechnungsdatum","Zahlungsdatum","Klient","Status","Betrag"]); ws.freeze_panes="A2"; ws.auto_filter.ref="A1:F1"
    for i in DB["invoices"]:
        if str(i.get("number","")).startswith(str(year)):
            ws.append([i["number"],i["date"],i.get("paid_date",""),i["client"],i.get("status","offen"),i["amount"]])
    ov=wb.create_sheet("Jahresübersicht"); ov.append(["Kennzahl","Betrag"])
    total=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")!="storniert")
    paid=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")=="bezahlt")
    ov.append(["Rechnungsbetrag",total]); ov.append(["Bezahlt",paid]); ov.append(["Offen",total-paid]); ws.column_dimensions["A"].width=20; ws.column_dimensions["B"].width=16; ws.column_dimensions["C"].width=16; ws.column_dimensions["D"].width=28; ws.column_dimensions["E"].width=14; ws.column_dimensions["F"].width=14
    wb.save(f)

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Praxisverwaltung"); self.resize(1280,820); self.setMinimumSize(1050,700)
        self.started=None; self.acc=0; self.running=False; self.restore_draft_pending=True
        shell=QWidget(); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(225); sv=QVBoxLayout(sidebar); sv.setContentsMargins(14,20,14,20)
        brand=QLabel("PRAXISPRO\n"+get_setting("practice_name","Psychologische Privatpraxis")); brand.setObjectName("brand"); brand.setWordWrap(True); sv.addWidget(brand)
        self.nav=QListWidget(); self.nav.setObjectName("nav")
        for x in ["⌂  Dashboard","＋  Sitzung","✦  Sitzungsassistent","♙  Klienten","▤  Neue Rechnung","▣  Rechnungen","⚙  Praxiseinstellungen","?  Benutzerhandbuch"]: self.nav.addItem(x)
        sv.addWidget(self.nav,1)
        foot=QLabel(get_setting("copyright","© 2026 Erdoğan Kulanoğlu")); foot.setObjectName("sidefoot"); sv.addWidget(foot)
        self.pages=QStackedWidget(); self.pages.addWidget(self.dashboard_ui()); self.pages.addWidget(self.session_ui()); self.pages.addWidget(self.helper_ui()); self.pages.addWidget(self.clients_ui()); self.pages.addWidget(self.invoice_ui()); self.pages.addWidget(self.invoices_ui()); self.pages.addWidget(self.settings_ui()); self.pages.addWidget(self.manual_ui())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        root.addWidget(sidebar); root.addWidget(self.pages,1); self.setCentralWidget(shell)
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.wallclock=QLabel()
        self.statusBar().addPermanentWidget(self.wallclock)
        self.walltimer=QTimer(self); self.walltimer.timeout.connect(self.update_wallclock); self.walltimer.start(250); self.update_wallclock()
        self.setStyleSheet("""
        QMainWindow { background:#f4f6f8; }
        #sidebar { background:#132f47; border:0; }
        #brand { color:white; font-size:20px; font-weight:800; padding:8px 10px 24px 10px; letter-spacing:.5px; }
        #sidefoot { color:#b9c8d5; font-size:12px; padding:10px; }
        #nav { background:transparent; border:0; outline:0; color:#dce7ef; font-size:15px; }
        #nav::item { padding:14px 12px; margin:3px 0; border-radius:8px; }
        #nav::item:selected { background:#2f7de1; color:white; font-weight:700; }
        #nav::item:hover:!selected { background:#244d70; color:white; }
        QStackedWidget { background:#f4f6f8; }
        #pageTitle { font-size:30px; font-weight:800; color:#17324d; }
        #pageSub { font-size:15px; color:#607080; padding-bottom:8px; }
        #statCard { background:white; border:1px solid #dce3e9; border-radius:14px; min-height:115px; }
        #cardCaption { color:#6b7b88; font-size:12px; font-weight:700; }
        #cardValue { color:#17324d; font-size:27px; font-weight:800; }
        #infoBox { background:white; border:1px solid #dce3e9; border-radius:10px; padding:14px; color:#607080; }
        #clientHeader { background:white; border:1px solid #dce3e9; border-radius:14px; padding:12px; }
        #clientName { color:#17324d; font-size:24px; font-weight:800; }
        #clientBadge { background:#e8f0f6; color:#17324d; border-radius:10px; padding:8px 14px; font-weight:700; }
        #sectionTitle { color:#17324d; font-size:18px; font-weight:700; padding-top:8px; }
        #formCard { background:white; border:1px solid #dce3e9; border-radius:14px; padding:18px; }
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
        self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit(); self.s_dob.setPlaceholderText("TT.MM.JJJJ")
        for field in (self.s_last,self.s_first,self.s_dob): field.setMinimumWidth(420); field.setMinimumHeight(38)
        self.s_date=QDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_date.setDisplayFormat("dd.MM.yyyy"); self.s_start=QTimeEdit(); self.s_end=QTimeEdit(); self.s_start.setDisplayFormat("HH:mm"); self.s_end.setDisplayFormat("HH:mm")
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
                inkfile=d.get("ink_file","")
                if inkfile and Path(inkfile).exists(): self.ink.load_png(inkfile)
                self.acc=int(d.get("seconds",0)); self.running=False; self.started=None
                self.nav.setCurrentRow(1)
        except Exception: pass
    def autosave_session(self):
        if not self.running and not self.notes.toPlainText().strip() and not self.s_last.text().strip() and not self.s_first.text().strip(): return
        draft={"last":self.s_last.text(),"first":self.s_first.text(),"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"seconds":self.elapsed(),"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"running":self.running}
        inkdraft=ROOT/"Sitzung_Autosave_Handschrift.png"; self.ink.save_png(inkdraft); draft["ink_file"]=str(inkdraft)
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
        if self.s_start.time()==self.s_end.time() and self.elapsed()==0:return QMessageBox.warning(self,"Zeitangabe","Bitte Beginn und Ende prüfen oder den Sitzungstimer verwenden.")
        c=next((x for x in DB["clients"] if x["last"].lower()==last.lower() and x["first"].lower()==first.lower()),None)
        if not c:c={"last":last,"first":first,"dob":self.s_dob.text().strip(),"address":"","diagnosis":""}; DB["clients"].append(c)
        else: c["dob"]=self.s_dob.text().strip() or c.get("dob","")
        # Abrechnungsdauer folgt den manuell dokumentierten Beginn-/Endzeiten.
        # Der Live-Timer bleibt eine unabhängige Kontrollanzeige.
        start_t=self.s_start.time(); end_t=self.s_end.time()
        mins=start_t.secsTo(end_t)//60 if start_t.isValid() and end_t.isValid() else 0
        if mins <= 0: mins=max(1,round(self.elapsed()/60))
        rec={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"last":last,"first":first,"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"minutes":mins,"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"billed":False}
        d=client_dir(c)/"Sitzungen"; inkfile=d/f"{rec['date']}_{rec['id']}_Handschrift.png"; self.ink.save_png(inkfile); rec["ink_file"]=str(inkfile)
        DB["sessions"].append(rec); save_data(); (d/f"{rec['date']}_Sitzung.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
        auto=ROOT/"Sitzung_Autosave.json"
        if auto.exists(): auto.unlink()
        QMessageBox.information(self,"Gespeichert",f"Sitzung gespeichert: {mins} Minuten.")
    def invoice_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Neue Rechnung"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Einzelrechnung oder Sammelrechnung aus noch nicht abgerechneten Sitzungen"); sub.setObjectName("pageSub"); v.addWidget(sub)
        card=QFrame(); card.setObjectName("formCard"); f=QFormLayout(card); f.setSpacing(12)
        self.i_no=QLineEdit(next_no()); self.i_last=QLineEdit(); self.i_first=QLineEdit(); self.i_addr=QLineEdit(); self.i_diag=QLineEdit(); self.pending_sessions=None; self.manual_items=[]
        self.i_date=QDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_date.setDisplayFormat("dd.MM.yyyy"); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Sonstige"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigter Satz")
        self.i_start=QTimeEdit(); self.i_start.setDisplayFormat("HH:mm"); self.i_end=QTimeEdit(); self.i_end.setDisplayFormat("HH:mm")
        for a,b in [("Rechnungsnummer",self.i_no),("Nachname",self.i_last),("Vorname",self.i_first),("Adresse (optional)",self.i_addr),("Diagnose (optional)",self.i_diag),("Leistungsdatum",self.i_date),("Beginn",self.i_start),("Ende",self.i_end),("Leistung",self.i_type),("Dauer Minuten",self.i_min)]:f.addRow(a,b)
        def invoice_times():
            secs=self.i_start.time().secsTo(self.i_end.time())
            if secs>0:self.i_min.setValue(max(1,secs//60))
        self.i_start.timeChanged.connect(invoice_times); self.i_end.timeChanged.connect(invoice_times)
        self.i_last.editingFinished.connect(self.fill_invoice_client); self.i_first.editingFinished.connect(self.fill_invoice_client)
        f.addRow("",self.i_red); v.addWidget(card)
        itemrow=QHBoxLayout()
        additem=QPushButton("＋ Leistung zur Rechnung hinzufügen"); additem.setMinimumHeight(46)
        self.iteminfo=QLabel("Noch keine zusätzlichen Leistungen"); self.iteminfo.setObjectName("pageSub")
        def add_manual_item():
            typ=self.i_type.currentText(); mins=self.i_min.value()
            if typ=="Sonstige":
                val,ok=QInputDialog.getDouble(self,"Sonstige Leistung","Betrag in €",0,0,100000,2)
                if not ok:return
                amount=round(val,2)
            else: amount=round(amount_for(mins,typ,self.i_red.isChecked()),2)
            self.manual_items.append({"date":self.i_date.date().toString("yyyy-MM-dd"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amount})
            self.pending_sessions=None; self.iteminfo.setText(f"{len(self.manual_items)} Leistungen · {sum(x['amount'] for x in self.manual_items):.2f} €")
        additem.clicked.connect(add_manual_item); itemrow.addWidget(additem); itemrow.addWidget(self.iteminfo,1); v.addLayout(itemrow)
        self.itemtable=QTableWidget(0,6); self.itemtable.setHorizontalHeaderLabels(["Datum","Zeit","Min.","Leistung","Satz","Betrag"]); self.itemtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.itemtable.setSelectionBehavior(QTableWidget.SelectRows); self.itemtable.setEditTriggers(QTableWidget.NoEditTriggers); self.itemtable.setMaximumHeight(190); v.addWidget(self.itemtable)
        def refresh_items():
            self.itemtable.setRowCount(0)
            for it in self.manual_items:
                r=self.itemtable.rowCount(); self.itemtable.insertRow(r)
                vals=[it.get("date",""),f'{it.get("start","")}–{it.get("end","")}',str(it.get("minutes",0)),it.get("type",""),"ermäßigt" if it.get("reduced") else "regulär",f'{float(it.get("amount",0)):.2f} €']
                for j,val in enumerate(vals): self.itemtable.setItem(r,j,QTableWidgetItem(str(val)))
            self.iteminfo.setText("Noch keine zusätzlichen Leistungen" if not self.manual_items else f"{len(self.manual_items)} Leistungen · {sum(float(x.get('amount',0)) for x in self.manual_items):.2f} €")
        additem.clicked.connect(refresh_items)
        itembuttons=QHBoxLayout(); removeitem=QPushButton("Ausgewählte Leistung entfernen"); clearitems=QPushButton("Leistungen leeren")
        def remove_manual_item():
            r=self.itemtable.currentRow()
            if 0<=r<len(self.manual_items): self.manual_items.pop(r); refresh_items()
        def clear_manual_items(): self.manual_items.clear(); refresh_items()
        removeitem.clicked.connect(remove_manual_item); clearitems.clicked.connect(clear_manual_items); itembuttons.addWidget(removeitem); itembuttons.addWidget(clearitems); v.addLayout(itembuttons)
        q=QPushButton("Unberechnete Sitzungen laden / Sammelrechnung"); q.setMinimumHeight(50); q.clicked.connect(self.load_unbilled_sessions); v.addWidget(q)
        preview=QPushButton("Rechnung vor Erstellung prüfen"); preview.setMinimumHeight(50)
        def preview_invoice():
            no=self.i_no.text().strip(); last=self.i_last.text().strip(); first=self.i_first.text().strip()
            rows=self.pending_sessions or self.manual_items
            if rows:
                lines="\n".join(f'{s.get("date","")}  {s.get("start","")}–{s.get("end","")}  {s.get("minutes",0)} Min.  {s.get("type","")}  {float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))):.2f} €' for s in rows)
                total=sum(float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))) for s in rows)
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
        rows=sorted([s for s in DB["sessions"] if not s.get("billed") and s.get("last","").lower()==last and s.get("first","").lower()==first],key=lambda s:(s.get("date",""),s.get("start","")))
        if not rows: return QMessageBox.information(self,"Sitzungen","Keine unberechneten Sitzungen für diesen Klienten gefunden.")
        self.pending_sessions=rows
        details="\n".join(f'{s.get("date","")} | {s.get("start","")}–{s.get("end","")} | {s.get("minutes",0)} Min. | {s.get("type","")}' for s in rows)
        total=sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows)
        QMessageBox.information(self,"Quartals-/Sammelrechnung",f"{len(rows)} unberechnete Sitzungen gefunden.\n\n{details}\n\nGesamt: {total:.2f} €\n\nBitte vor PDF-Erstellung kontrollieren.")
    def make_invoice(self):
        no=self.i_no.text().strip()
        if not no:return QMessageBox.warning(self,"Fehlt","Eine Rechnungsnummer ist erforderlich.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+",no):return QMessageBox.warning(self,"Rechnungsnummer","Bitte nur Buchstaben, Zahlen, Punkt, Bindestrich oder Unterstrich verwenden.")
        if any(x["number"]==no for x in DB["invoices"]):return QMessageBox.warning(self,"Doppelt","Diese Rechnungsnummer existiert bereits.")
        last,first=self.i_last.text().strip(),self.i_first.text().strip()
        if not last or not first:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
        rows=getattr(self,"pending_sessions",None) or self.manual_items
        if rows:
            mins=sum(int(s.get("minutes",0)) for s in rows); typ="Sammelrechnung"; amt=round(sum(float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))) for s in rows),2)
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
        can.drawString(50,H-87,"Ehe-, Familien- und Lebensberater · Zertifizierter systemischer Berater und Therapeut nach dem SIT-Modell")
        can.drawString(50,H-102,"Schönwalder Str. 59, 13585 Berlin · Mobil: 0176 43605753 · Fax: 030 43205928")
        can.drawString(50,H-117,"info@psychologe-spandau.de · www.psychologe-spandau.de · Steuernummer: 19/405/00254")
        can.setFont("Helvetica-Bold",16); can.drawString(50,H-150,f"Rechnung {no}")
        can.setFont("Helvetica",9); can.drawRightString(W-50,H-150,"Rechnungsdatum: "+datetime.now().strftime("%d.%m.%Y"))
        can.setFont("Helvetica",11); y=H-185; can.drawString(50,y,f"{first} {last}"); y-=16
        if self.i_addr.text().strip():can.drawString(50,y,self.i_addr.text().strip()); y-=16
        if self.i_diag.text().strip():can.drawString(50,y,"Diagnose: "+self.i_diag.text().strip()); y-=22
        if rows:
            for s in rows:
                a=float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False)))))
                can.drawString(50,y,f'{s.get("date","")}   {s.get("start","")}–{s.get("end","")}   {s.get("minutes",0)} Min.   {s.get("type","")}'); can.drawRightString(W-50,y,f"{a:.2f} EUR"); y-=18
        else:
            can.drawString(50,y,f"{self.i_date.date().toString('dd.MM.yyyy')}   {mins} Min.   {typ}"); can.drawRightString(W-50,y,f"{amt:.2f} EUR"); y-=18
        y-=17
        can.setFont("Helvetica-Bold",12); can.drawRightString(W-50,y,f"Gesamt: {amt:.2f} EUR"); y-=35
        can.setFont("Helvetica",9); can.drawString(50,y,"Zahlbar innerhalb von 14 Tagen. Verwendungszweck: "+no); y-=14
        can.drawString(50,y,"IBAN DE13 5001 0517 5404 0811 30 · BIC INGDDEFFXXX"); y-=14
        can.drawString(50,y,"PayPal: erdogankulanoglu@hotmail.com"); y-=14
        can.drawString(50,y,"Leistungen als Heilpraktiker sind nach § 4 Nr. 14 Buchstabe a UStG umsatzsteuerbefreit.")
        can.drawString(50,55,"Elektronisch erstellt und ohne Unterschrift/Stempel gültig."); can.save()
        invoice_items=[]
        if rows:
            for s in rows:
                invoice_items.append({"id":s.get("id"),"date":s.get("date",""),"start":s.get("start",""),"end":s.get("end",""),"minutes":int(s.get("minutes",0)),"type":s.get("type",""),"reduced":bool(s.get("reduced",False)),"amount":round(float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))),2)})
        else:
            invoice_items=[{"id":None,"date":self.i_date.date().toString("yyyy-MM-dd"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amt}]
        DB["invoices"].append({"number":no,"date":datetime.now().strftime("%Y-%m-%d"),"client":f"{last}, {first}","address":self.i_addr.text().strip(),"diagnosis":self.i_diag.text().strip(),"amount":amt,"status":"offen","paid_date":"","pdf":str(pdf),"items":invoice_items})
        if rows:
            ids={s.get("id") for s in rows}
            for s in DB["sessions"]:
                if s.get("id") in ids: s["billed"]=True; s["invoice_number"]=no
            self.pending_sessions=None
        self.manual_items=[]; self.iteminfo.setText("Noch keine zusätzlichen Leistungen")
        if hasattr(self,"itemtable"): self.itemtable.setRowCount(0)
        save_data(); update_excel(); self.i_no.setText(next_no())
        QMessageBox.information(self,"Fertig",f"PDF gespeichert:\n{pdf}")
    def clients_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Klienten"); title.setObjectName("pageTitle"); v.addWidget(title)
        tools=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Klient suchen …"); search.setClearButtonEnabled(True); tools.addWidget(search,1); v.addLayout(tools)
        t=QTableWidget(0,3); t.setHorizontalHeaderLabels(["Nachname","Vorname","Geburtsdatum"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); t.setAlternatingRowColors(True); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers)
        for c in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())): r=t.rowCount();t.insertRow(r);[t.setItem(r,j,QTableWidgetItem(str(c.get(k,"")))) for j,k in enumerate(["last","first","dob"])]
        v.addWidget(t)
        def filter_clients(txt):
            q=txt.strip().lower()
            for row in range(t.rowCount()):
                hay=" ".join(t.item(row,col).text().lower() if t.item(row,col) else "" for col in range(t.columnCount()))
                t.setRowHidden(row,q not in hay)
        search.textChanged.connect(filter_clients)
        opensessions=QPushButton("Klientenakte öffnen"); opensessions.setMinimumHeight(48)
        def show_sessions():
            r=t.currentRow()
            if r<0:return
            last=t.item(r,0).text(); first=t.item(r,1).text()
            rows=[s for s in DB["sessions"] if s.get("last")==last and s.get("first")==first]
            dlg=QDialog(self); dlg.setWindowTitle(f"Klientenakte – {first} {last}"); dlg.resize(980,700); lay=QVBoxLayout(dlg)
            head=QFrame(); head.setObjectName("clientHeader"); hv=QHBoxLayout(head); person=QVBoxLayout(); nm=QLabel(f"{first} {last}"); nm.setObjectName("clientName"); dob=t.item(r,2).text() if t.item(r,2) else ""; meta=QLabel(("Geburtsdatum: "+dob) if dob else "Geburtsdatum nicht hinterlegt"); meta.setObjectName("pageSub"); person.addWidget(nm);person.addWidget(meta);hv.addLayout(person);hv.addStretch(); count=QLabel(f"{len(rows)} Sitzungen"); count.setObjectName("clientBadge");hv.addWidget(count);lay.addWidget(head)
            section=QLabel("Sitzungsverlauf"); section.setObjectName("sectionTitle"); lay.addWidget(section)
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
            edit.clicked.connect(edit_selected)
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
            view.clicked.connect(open_selected)
            actionrow=QHBoxLayout(); actionrow.addWidget(view); actionrow.addWidget(edit); lay.addLayout(actionrow)
            close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dlg.reject); lay.addWidget(close); dlg.exec()
        opensessions.clicked.connect(show_sessions); t.cellDoubleClicked.connect(lambda *_: show_sessions()); v.addWidget(opensessions)
        clientactions=QHBoxLayout()
        tosession=QPushButton("Neue Sitzung für Klient"); toinvoice=QPushButton("Neue Rechnung für Klient")
        def selected_client():
            r=t.currentRow()
            if r<0:return None
            last=t.item(r,0).text(); first=t.item(r,1).text()
            return next((x for x in DB["clients"] if x.get("last")==last and x.get("first")==first),None)
        def client_to_session():
            x=selected_client()
            if not x:return
            self.s_last.setText(x.get("last","")); self.s_first.setText(x.get("first","")); self.s_dob.setText(x.get("dob","")); self.nav.setCurrentRow(1)
        def client_to_invoice():
            x=selected_client()
            if not x:return
            self.i_last.setText(x.get("last","")); self.i_first.setText(x.get("first","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis","")); self.nav.setCurrentRow(4)
        tosession.clicked.connect(client_to_session); toinvoice.clicked.connect(client_to_invoice); clientactions.addWidget(tosession); clientactions.addWidget(toinvoice); v.addLayout(clientactions)
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
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Rechnungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Offene, bezahlte und stornierte Rechnungen verwalten"); sub.setObjectName("pageSub"); v.addWidget(sub)
        search=QLineEdit(); search.setPlaceholderText("Rechnung oder Klient suchen …"); search.setClearButtonEnabled(True); v.addWidget(search)
        t=QTableWidget(0,5); t.setHorizontalHeaderLabels(["Nr.","Datum","Klient","Status","Betrag"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers); t.setAlternatingRowColors(True)
        for i in reversed(DB["invoices"]):
            r=t.rowCount(); t.insertRow(r); vals=[i.get("number",""),i.get("date",""),i.get("client",""),i.get("status","offen"),f'{float(i.get("amount",0)):.2f} €']
            for j,x in enumerate(vals): t.setItem(r,j,QTableWidgetItem(str(x)))
        def filt(q):
            q=q.lower().strip()
            for r in range(t.rowCount()): t.setRowHidden(r,q not in " ".join(t.item(r,j).text().lower() for j in range(t.columnCount()) if t.item(r,j)))
        search.textChanged.connect(filt); v.addWidget(t)
        h=QHBoxLayout()
        paid=QPushButton("✓ Als bezahlt markieren"); paid.setMinimumHeight(50)
        def selected_invoice():
            r=t.currentRow()
            if r<0:return None,None
            no=t.item(r,0).text(); return r,next((x for x in DB["invoices"] if x.get("number")==no),None)
        def mark_paid():
            r,inv=selected_invoice()
            if inv:
                if inv.get("status")=="storniert": return QMessageBox.warning(self,"Status","Eine stornierte Rechnung kann nicht als bezahlt markiert werden.")
                inv["status"]="bezahlt"; inv["paid_date"]=datetime.now().strftime("%Y-%m-%d"); save_data(); update_excel(); t.item(r,3).setText("bezahlt")
        paid.clicked.connect(mark_paid); h.addWidget(paid)
        cancel=QPushButton("Rechnung stornieren"); cancel.setMinimumHeight(50)
        def cancel_invoice():
            r,inv=selected_invoice()
            if not inv:return
            if inv.get("status")=="storniert": return QMessageBox.information(self,"Stornieren","Diese Rechnung ist bereits storniert.")
            msg=f'Rechnung {inv.get("number","")} wirklich stornieren?'
            if inv.get("status")=="bezahlt": msg+="\n\nAchtung: Die Rechnung ist bereits als bezahlt markiert."
            if QMessageBox.question(self,"Stornieren",msg)!=QMessageBox.Yes:return
            inv["status"]="storniert"; inv["cancelled_date"]=datetime.now().strftime("%Y-%m-%d")
            no=inv.get("number","")
            released=0
            for s in DB["sessions"]:
                if s.get("invoice_number")==no:
                    s["billed"]=False; s["invoice_number"]=""; released+=1
            save_data(); update_excel(); t.item(r,3).setText("storniert")
            QMessageBox.information(self,"Storniert",f"Rechnung {no} wurde storniert.\n{released} verknüpfte Sitzung(en) sind wieder abrechenbar.")
        cancel.clicked.connect(cancel_invoice); h.addWidget(cancel)
        openpdf=QPushButton("PDF öffnen"); openpdf.setMinimumHeight(50)
        def open_pdf():
            _,inv=selected_invoice()
            if not inv:return
            p=inv.get("pdf","")
            if p and Path(p).exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))); return
            client=inv.get("client","")
            if "," in client:
                last,first=[x.strip() for x in client.split(",",1)]
                guess=client_dir({"last":last,"first":first})/"Rechnungen"/f"Rechnung_{inv.get('number','')}.pdf"
                if guess.exists(): inv["pdf"]=str(guess); save_data(); QDesktopServices.openUrl(QUrl.fromLocalFile(str(guess))); return
            QMessageBox.information(self,"PDF","Das PDF konnte nicht gefunden werden.")
        openpdf.clicked.connect(open_pdf); h.addWidget(openpdf); v.addLayout(h)
        backup=QPushButton("Datensicherung erstellen"); backup.setMinimumHeight(48)
        def do_backup():
            dest=ROOT/"Backups"/datetime.now().strftime("Backup_%Y-%m-%d_%H-%M-%S"); dest.mkdir(parents=True,exist_ok=True)
            if DATA.exists(): shutil.copy2(DATA,dest/DATA.name)
            if DBFILE.exists():
                con=sqlite3.connect(DBFILE); out=sqlite3.connect(dest/DBFILE.name); con.backup(out); out.close(); con.close()
            for x in (ROOT/"Einnahmen").glob("*.xlsx"): shutil.copy2(x,dest/x.name)
            shutil.copytree(ROOT/"Klienten",dest/"Klienten",dirs_exist_ok=True); if KEYFILE.exists(): shutil.copy2(KEYFILE,dest/KEYFILE.name)
            (dest/"Backup_Info.txt").write_text("Praxisverwaltung Sicherung\nErstellt: "+datetime.now().isoformat(timespec="seconds")+"\nDatenbank: "+str(DBFILE)+"\nKlienten: "+str(len(DB.get("clients",[])))+"\nSitzungen: "+str(len(DB.get("sessions",[])))+"\nRechnungen: "+str(len(DB.get("invoices",[]))),encoding="utf-8"); QMessageBox.information(self,"Sicherung",f"Sicherung erstellt:\n{dest}")
        backup.clicked.connect(do_backup); v.addWidget(backup); return w
    def manual_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Benutzerhandbuch"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("PraxisPro – Kurzanleitung und wichtige Hinweise"); sub.setObjectName("pageSub"); v.addWidget(sub)
        text=QTextEdit(); text.setReadOnly(True); text.setStyleSheet("font-size:15px;padding:14px;line-height:1.4;")
        text.setPlainText("""PRAXISPRO – BENUTZERHANDBUCH

1. ZWECK DER SOFTWARE
PraxisPro unterstützt die lokale Organisation einer psychologischen bzw. therapeutischen Privatpraxis. Dazu gehören Klientenverwaltung, Sitzungsdokumentation, handschriftliche Notizen, Rechnungen, Einnahmenübersicht und Datensicherung.

2. WICHTIGER HINWEIS ZUR ABRECHNUNG
PraxisPro verfügt derzeit über KEINE Schnittstelle zur direkten Abrechnung mit gesetzlichen oder privaten Krankenkassen, Kassenärztlichen Vereinigungen, Abrechnungsstellen oder vergleichbaren externen Abrechnungssystemen.

Die Rechnungsfunktion dient der Erstellung und Verwaltung eigener Rechnungen. Eine elektronische Übermittlung oder automatische Erstattung durch eine Krankenkasse erfolgt nicht. Ob und in welcher Höhe Kosten von einer privaten Krankenversicherung, Beihilfe oder einem anderen Kostenträger übernommen werden, muss außerhalb der Software geklärt werden.

3. KLIENTEN
Unter „Klienten“ können Stammdaten und vorhandene Sitzungen eingesehen werden. Von dort kann direkt eine neue Sitzung oder Rechnung für den ausgewählten Klienten begonnen werden.

4. SITZUNGEN
Beginn und Ende bleiben manuell veränderbar. Zusätzlich steht ein Sitzungstimer zur Verfügung. Therapienotizen können per Tastatur und über die Handschrift-/Stiftfläche dokumentiert werden. Notizen werden nicht automatisch auf Rechnungen übernommen.

5. SITZUNGSASSISTENT
Der Sitzungsassistent stellt Fragen und therapeutische Anregungen als Arbeitshilfe bereit. Diese Inhalte ersetzen keine fachliche Diagnostik, Indikationsstellung oder therapeutische Entscheidung.

6. RECHNUNGEN
Mehrere Leistungen können zu einer Rechnung zusammengefasst werden. Rechnungsnummern werden fortlaufend vorgeschlagen und können kontrolliert werden. Rechnungen können als bezahlt oder storniert gekennzeichnet werden. Bei einer Stornierung werden verknüpfte Sitzungen wieder zur Abrechnung freigegeben.

7. HONORARE UND PRAXISDATEN
Praxisname, Anschrift, Kontaktdaten, Bankverbindung, Logo und weitere Angaben sind als Praxisvorlage konfigurierbar. Die mitgelieferte Vorlage enthält die Daten der Praxis Erdoğan Kulanoğlu. Honorarsätze werden ebenfalls als konfigurierbare Praxisdaten geführt.

8. MEHRERE BENUTZER
Die Software wird für eine spätere Nutzung durch mehrere Therapeutinnen und Therapeuten vorbereitet. Benutzerkonten, Rollen und passwortgeschützter Zugang werden schrittweise integriert.

9. DATENSICHERUNG
Sicherungen sollten regelmäßig erstellt und zusätzlich auf einem geeigneten geschützten Datenträger aufbewahrt werden. Besonders Sitzungsnotizen und Gesundheitsdaten sind vertrauliche Daten.

10. DATENSCHUTZ / AKTUELLER ENTWICKLUNGSSTAND
Die Anwendung befindet sich noch in Entwicklung. Solange lokale Datenbank, Notizen, Handschriftdateien und Sicherungen nicht vollständig verschlüsselt und die vorgesehenen Zugriffsschutzfunktionen fertiggestellt sind, sollte die Testversion nicht für echte Patientendaten eingesetzt werden.

11. HERSTELLER
PraxisPro
Hersteller: Erdoğan Kulanoğlu
© 2026 Erdoğan Kulanoğlu. Alle Rechte vorbehalten.

Die Praxisdaten des jeweiligen Nutzers können unabhängig von diesen Herstellerangaben angepasst werden.
""")
        v.addWidget(text,1)
        note=QLabel("Hinweis: Das Handbuch wird mit der weiteren Entwicklung der Software ergänzt."); note.setObjectName("pageSub"); v.addWidget(note)
        return w

    def settings_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Praxiseinstellungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Vorlage anpassen – Praxisdaten, Bankverbindung, Herstellerangaben und Logo."); sub.setObjectName("pageSub"); v.addWidget(sub)
        form=QFormLayout(); fields={}
        labels=[("practice_name","Praxisname"),("owner_name","Inhaber / Praxisleitung"),("qualifications","Qualifikationen"),("address","Anschrift"),("phone","Telefon"),("fax","Fax"),("email","E-Mail"),("website","Website"),("tax_number","Steuernummer"),("iban","IBAN"),("bic","BIC"),("paypal","PayPal"),("manufacturer","Herstellername"),("copyright","Copyright")]
        for key,label in labels:
            ed=QLineEdit(get_setting(key)); fields[key]=ed; form.addRow(label,ed)
        logo=QLineEdit(get_setting("logo_path")); fields["logo_path"]=logo; choose=QPushButton("Logo auswählen …")
        def pick_logo():
            p,_=QFileDialog.getOpenFileName(self,"Praxislogo auswählen","","Bilder (*.png *.jpg *.jpeg)")
            if p: logo.setText(p)
        choose.clicked.connect(pick_logo); lr=QHBoxLayout(); lr.addWidget(logo,1); lr.addWidget(choose); form.addRow("Praxislogo",lr)
        v.addLayout(form)
        save=QPushButton("Praxiseinstellungen speichern"); save.setMinimumHeight(52)
        def save_settings():
            for k,ed in fields.items(): set_setting(k,ed.text().strip())
            QMessageBox.information(self,"Gespeichert","Die Praxisvorlage wurde gespeichert. Deine bisherigen Daten bleiben die Standardvorlage.")
        save.clicked.connect(save_settings); v.addWidget(save)
        rates=QLabel("Honorarsätze"); rates.setObjectName("sectionTitle"); v.addWidget(rates)
        rt=QTableWidget(0,4); rt.setHorizontalHeaderLabels(["Leistung","Einheit Min.","Regulär €","Ermäßigt €"]); rt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for name,mins,amount,reduced,mode in get_fee_rates():
            r=rt.rowCount(); rt.insertRow(r)
            for j,val in enumerate([name,mins,amount,reduced if reduced is not None else ""]): rt.setItem(r,j,QTableWidgetItem(str(val)))
        v.addWidget(rt)
        ratebuttons=QHBoxLayout(); saverates=QPushButton("Honorarsätze speichern"); addrate=QPushButton("Neue Leistung")
        def save_rates():
            con=sqlite3.connect(DBFILE)
            for r in range(rt.rowCount()):
                name=(rt.item(r,0).text() if rt.item(r,0) else "").strip()
                if not name: continue
                try: mins=int(rt.item(r,1).text()); amount=float(rt.item(r,2).text().replace(",", ".")); reduced=float(rt.item(r,3).text().replace(",", ".")) if rt.item(r,3) and rt.item(r,3).text().strip() else None
                except: QMessageBox.warning(self,"Honorare",f"Bitte Werte in Zeile {r+1} prüfen."); con.close(); return
                con.execute("INSERT INTO fee_rates(name,minutes,amount,reduced_amount,billing_mode,active) VALUES(?,?,?,?,?,1) ON CONFLICT(name) DO UPDATE SET minutes=excluded.minutes,amount=excluded.amount,reduced_amount=excluded.reduced_amount,active=1",(name,mins,amount,reduced,"proportional"))
            con.commit(); con.close(); QMessageBox.information(self,"Honorare","Honorarsätze gespeichert.")
        def add_rate():
            r=rt.rowCount(); rt.insertRow(r)
            for j,val in enumerate(["Neue Leistung","45","70","60"]):rt.setItem(r,j,QTableWidgetItem(val))
            rt.setCurrentCell(r,0); rt.editItem(rt.item(r,0))
        saverates.clicked.connect(save_rates); addrate.clicked.connect(add_rate); ratebuttons.addWidget(saverates); ratebuttons.addWidget(addrate); v.addLayout(ratebuttons)
        hint=QLabel("Honorarsätze können hier bearbeitet und um eigene Leistungen erweitert werden."); hint.setWordWrap(True); hint.setObjectName("pageSub"); v.addWidget(hint)
        users=QLabel("Benutzer / Therapeuten"); users.setObjectName("sectionTitle"); v.addWidget(users)
        ub=QPushButton("Benutzer anlegen")
        def add_user():
            name,ok=QInputDialog.getText(self,"Benutzer","Benutzername:")
            if not ok or not name.strip():return
            display,ok=QInputDialog.getText(self,"Benutzer","Anzeigename:")
            if not ok or not display.strip():return
            pwd,ok=QInputDialog.getText(self,"Benutzer","Passwort:",QLineEdit.Password)
            if not ok or len(pwd)<8:return QMessageBox.warning(self,"Passwort","Bitte mindestens 8 Zeichen verwenden.")
            try:
                con=sqlite3.connect(DBFILE); con.execute("INSERT INTO users(username,display_name,role,active,password_hash,created_at) VALUES(?,?,?,?,?,?)",(name.strip(),display.strip(),"Therapeut",1,password_hash(pwd),datetime.now().isoformat(timespec="seconds"))); con.commit(); con.close(); audit("USER_CREATED",display.strip()); QMessageBox.information(self,"Benutzer","Benutzer wurde angelegt.")
            except sqlite3.IntegrityError: QMessageBox.warning(self,"Benutzer","Dieser Benutzername existiert bereits.")
        ub.clicked.connect(add_user); v.addWidget(ub)
        return w

    def dashboard_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(18)
        y=str(datetime.now().year); billed=sum(float(i.get("amount",0)) for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status")!="storniert"); paid=sum(float(i.get("amount",0)) for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status")=="bezahlt"); open_amt=billed-paid
        title=QLabel("Herzlich willkommen!"); title.setObjectName("pageTitle"); sub=QLabel(f"Psychologische Privatpraxis · Überblick {y}"); sub.setObjectName("pageSub"); v.addWidget(title); v.addWidget(sub)
        cards=QGridLayout(); cards.setSpacing(14)
        def card(caption,value):
            box=QFrame(); box.setObjectName("statCard"); q=QVBoxLayout(box); a=QLabel(caption); a.setObjectName("cardCaption"); b=QLabel(value); b.setObjectName("cardValue"); q.addWidget(a);q.addWidget(b);return box
        cards.addWidget(card("ABGERECHNET",f"{billed:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,0)
        cards.addWidget(card("BEZAHLT",f"{paid:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,1)
        cards.addWidget(card("OFFEN",f"{open_amt:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")),0,2)
        cards.addWidget(card("KLIENTEN",str(len(DB["clients"]))),1,0); cards.addWidget(card("SITZUNGEN "+y,str(sum(1 for s in DB["sessions"] if str(s.get("date","")).startswith(y)))),1,1); cards.addWidget(card("OFFENE RECHNUNGEN",str(sum(1 for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status","offen")=="offen"))),1,2); v.addLayout(cards)
        quick=QLabel("Schnellzugriff"); quick.setObjectName("sectionTitle"); v.addWidget(quick)
        actions=QHBoxLayout(); new_session=QPushButton("＋  Neue Sitzung"); new_session.setMinimumHeight(52); new_session.clicked.connect(lambda:self.nav.setCurrentRow(1)); new_invoice=QPushButton("▤  Neue Rechnung"); new_invoice.setMinimumHeight(52); new_invoice.clicked.connect(lambda:self.nav.setCurrentRow(4)); clients=QPushButton("♙  Klienten verwalten"); clients.setMinimumHeight(52); clients.clicked.connect(lambda:self.nav.setCurrentRow(3)); actions.addWidget(new_session);actions.addWidget(new_invoice);actions.addWidget(clients);v.addLayout(actions)
        info=QLabel(f"Datenbank: {DBFILE}\nDatenordner: {ROOT}"); info.setObjectName("infoBox"); info.setWordWrap(True); v.addWidget(info); v.addStretch(); return w
app=QApplication(sys.argv); app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}"); win=Main();win.show();sys.exit(app.exec())
