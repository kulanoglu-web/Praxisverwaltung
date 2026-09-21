import sys, json, os, re, math, shutil, sqlite3, base64, hashlib
from pathlib import Path
from datetime import datetime, date
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl, QEvent
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog,QSplitter,QListWidget,QStackedWidget,QFrame,QGridLayout,QInputDialog,QScrollArea,QSlider)
from PySide6.QtCore import QDate,QTime
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap, QDesktopServices
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from cryptography.fernet import Fernet, InvalidToken

APP_VERSION = "0.11.17"
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

def decrypt_file_bytes(path):
    p=Path(path)
    try:
        data=p.read_bytes()
        return Fernet(encryption_key()).decrypt(data) if p.suffix==".enc" else data
    except Exception:return b""

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
        p=Path(path); img=QImage()
        if p.suffix==".enc":
            raw=decrypt_file_bytes(p); img.loadFromData(raw,"PNG")
        else: img=QImage(str(path))
        if not img.isNull(): self.image=img.convertToFormat(QImage.Format_ARGB32).scaled(1200,700,Qt.IgnoreAspectRatio,Qt.SmoothTransformation); self.history=[]; self.update(); return True
        return False
from openpyxl import Workbook, load_workbook

def bundled_asset(name):
    base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))
    return base/"assets"/name

def practice_logo_path():
    custom=get_setting("logo_path","")
    if custom and Path(custom).exists(): return Path(custom)
    for name in ("logo.png","logo.jpg"):
        bundled=bundled_asset(name)
        if bundled.exists(): return bundled
    return None

DATA=ROOT/"praxisdaten.json.enc"
for p in [ROOT/"Klienten",ROOT/"Einnahmen",ROOT/"Backups",DBDIR]: p.mkdir(parents=True,exist_ok=True)

def init_sqlite():
    con=sqlite3.connect(DBFILE); con.execute("PRAGMA foreign_keys=ON"); con.execute("PRAGMA journal_mode=WAL"); con.execute("PRAGMA synchronous=NORMAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS clients(
      id INTEGER PRIMARY KEY, first TEXT NOT NULL, last TEXT NOT NULL, dob TEXT,
      address TEXT, diagnosis TEXT, phone TEXT, email TEXT, created_at TEXT, updated_at TEXT,
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
    ucols=[r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()]
    if "recovery_question" not in ucols: con.execute("ALTER TABLE users ADD COLUMN recovery_question TEXT")
    if "recovery_answer_hash" not in ucols: con.execute("ALTER TABLE users ADD COLUMN recovery_answer_hash TEXT")
    if "failed_attempts" not in ucols: con.execute("ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0")
    if "locked_until" not in ucols: con.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    cols=[r[1] for r in con.execute("PRAGMA table_info(clients)").fetchall()]
    if "client_key" not in cols: con.execute("ALTER TABLE clients ADD COLUMN client_key TEXT")
    if "phone" not in cols: con.execute("ALTER TABLE clients ADD COLUMN phone TEXT")
    if "email" not in cols: con.execute("ALTER TABLE clients ADD COLUMN email TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_clients_client_key ON clients(client_key)")
    defaults={
      "practice_name":"Psychologische Privatpraxis","owner_name":"Erdoğan Kulanoğlu",
      "qualifications":"Psychologe M. Sc. · Sozialarbeiter B.A. · Heilpraktiker für Psychotherapie",
      "address":"Schönwalder Str. 59, 13585 Berlin","phone":"0176 43605753","fax":"030 43205928",
      "email":"info@psychologe-spandau.de","website":"www.psychologe-spandau.de","tax_number":"19/405/00254",
      "iban":"DE13 5001 0517 5404 0811 30","bic":"INGDDEFFXXX","paypal":"erdogankulanoglu@hotmail.com",
      "manufacturer":"Erdoğan Kulanoğlu","copyright":"© 2026 Erdoğan Kulanoğlu. Alle Rechte vorbehalten.","logo_path":"","auto_lock_minutes":"15","travel_surcharge":"25"
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
        vals=(encrypt_text(x.get("first","")),encrypt_text(x.get("last","")),encrypt_text(x.get("dob","")),encrypt_text(x.get("address","")),encrypt_text(x.get("diagnosis","")),encrypt_text(x.get("phone","")),encrypt_text(x.get("email","")),x.get("created_at",""),datetime.now().isoformat(timespec="seconds"),ck)
        if row: cur.execute("UPDATE clients SET first=?,last=?,dob=?,address=?,diagnosis=?,phone=?,email=?,created_at=?,updated_at=?,client_key=? WHERE id=?",vals+(row[0],))
        else: cur.execute("INSERT INTO clients(first,last,dob,address,diagnosis,phone,email,created_at,updated_at,client_key) VALUES(?,?,?,?,?,?,?,?,?,?)",vals)
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

def normalize_recovery_answer(value):
    return " ".join(str(value).strip().lower().split())

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
    rates={r[0]:r for r in get_fee_rates()}
    row=rates.get(typ)
    if row:
        _,unit,regular,reduced_amount,mode=row
        unit=max(1,int(unit)); rate=float(reduced_amount if reduced and reduced_amount is not None else regular)
        if mode=="started_unit": return math.ceil(max(1,minutes)/unit)*rate
        if mode=="proportional_plus_travel": return minutes/unit*rate+float(get_setting("travel_surcharge","25") or 25)
        if mode=="fixed": return rate
        return minutes/unit*rate
    rate=60 if reduced else 70
    return minutes/45*rate

def update_excel():
    # Buchhaltungsübersicht standardmäßig ohne Klientennamen/Diagnosen.
    year=datetime.now().year; f=ROOT/"Einnahmen"/f"Einnahmen_{year}.xlsx"
    wb=Workbook(); ws=wb.active; ws.title="Einnahmen"
    ws.append(["Rechnungsnummer","Rechnungsdatum","Zahlungsdatum","Status","Betrag"]); ws.freeze_panes="A2"; ws.auto_filter.ref="A1:E1"
    for i in DB["invoices"]:
        if str(i.get("number","")).startswith(str(year)):
            ws.append([i["number"],i["date"],i.get("paid_date",""),i.get("status","offen"),i["amount"]])
    ov=wb.create_sheet("Jahresübersicht"); ov.append(["Kennzahl","Betrag"])
    total=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")!="storniert")
    paid=sum(float(i["amount"]) for i in DB["invoices"] if str(i.get("number","")).startswith(str(year)) and i.get("status")=="bezahlt")
    ov.append(["Rechnungsbetrag",total]); ov.append(["Bezahlt",paid]); ov.append(["Offen",total-paid])
    for col,width in {"A":20,"B":16,"C":16,"D":14,"E":14}.items(): ws.column_dimensions[col].width=width
    wb.save(f)

class PasswordResetDialog(QDialog):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Passwort zurücksetzen"); self.setMinimumWidth(440)
        v=QVBoxLayout(self); v.addWidget(QLabel("Passwort vergessen"))
        self.username=QLineEdit(); self.username.setPlaceholderText("Benutzername"); v.addWidget(self.username)
        self.question=QLabel("Benutzername eingeben und Sicherheitsfrage laden."); self.question.setWordWrap(True); v.addWidget(self.question)
        load=QPushButton("Sicherheitsfrage laden"); load.clicked.connect(self.load_question); v.addWidget(load)
        self.answer=QLineEdit(); self.answer.setPlaceholderText("Antwort"); v.addWidget(self.answer)
        self.p1=QLineEdit(); self.p1.setEchoMode(QLineEdit.Password); self.p1.setPlaceholderText("Neues Passwort – mindestens 8 Zeichen"); v.addWidget(self.p1)
        self.p2=QLineEdit(); self.p2.setEchoMode(QLineEdit.Password); self.p2.setPlaceholderText("Neues Passwort wiederholen"); v.addWidget(self.p2)
        b=QPushButton("Passwort zurücksetzen"); b.clicked.connect(self.reset_password); v.addWidget(b)
    def load_question(self):
        con=sqlite3.connect(DBFILE); row=con.execute("SELECT recovery_question FROM users WHERE username=? AND active=1",(self.username.text().strip(),)).fetchone(); con.close()
        self.question.setText(row[0] if row and row[0] else "Für diesen Benutzer ist keine Sicherheitsfrage hinterlegt.")
    def reset_password(self):
        username=self.username.text().strip(); con=sqlite3.connect(DBFILE); row=con.execute("SELECT recovery_answer_hash,COALESCE(failed_attempts,0),locked_until FROM users WHERE username=? AND active=1",(username,)).fetchone()
        if row and row[2]:
            try:
                if datetime.now()<datetime.fromisoformat(row[2]): con.close(); QMessageBox.warning(self,"Passwort zurücksetzen","Zur Sicherheit ist die Wiederherstellung vorübergehend gesperrt."); return
            except ValueError: pass
        if not row or not row[0] or not verify_password(normalize_recovery_answer(self.answer.text()),row[0]):
            if row:
                attempts=row[1]+1; locked=(datetime.now()+timedelta(minutes=10)).isoformat(timespec="seconds") if attempts>=5 else None
                con.execute("UPDATE users SET failed_attempts=?,locked_until=? WHERE username=?",(0 if locked else attempts,locked,username)); con.commit()
            con.close(); audit("PASSWORD_RESET_FAILED","Sicherheitsantwort falsch",username); QMessageBox.warning(self,"Passwort zurücksetzen","Benutzername oder Sicherheitsantwort ist nicht korrekt."); return
        if len(self.p1.text())<8 or self.p1.text()!=self.p2.text():
            con.close(); QMessageBox.warning(self,"Passwort","Zwei gleiche Passwörter mit mindestens 8 Zeichen erforderlich."); return
        con.execute("UPDATE users SET password_hash=?,failed_attempts=0,locked_until=NULL WHERE username=?",(password_hash(self.p1.text()),username)); con.commit(); con.close()
        audit("PASSWORD_RESET","Passwort über Sicherheitsfrage zurückgesetzt",username); QMessageBox.information(self,"Passwort","Das Passwort wurde geändert."); self.accept()

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__(); self.user=None; self.setWindowTitle("PraxisPro – Anmeldung"); self.setMinimumWidth(420)
        v=QVBoxLayout(self); t=QLabel("PRAXISPRO"); t.setStyleSheet("font-size:28px;font-weight:800;color:#17324d"); v.addWidget(t)
        v.addWidget(QLabel(get_setting("practice_name","Psychologische Privatpraxis")))
        self.username=QLineEdit(); self.username.setPlaceholderText("Benutzername")
        self.password=QLineEdit(); self.password.setPlaceholderText("Passwort"); self.password.setEchoMode(QLineEdit.Password)
        v.addWidget(self.username); v.addWidget(self.password)
        self.info=QLabel(""); self.info.setWordWrap(True); v.addWidget(self.info)
        b=QPushButton("Anmelden"); b.setMinimumHeight(48); b.clicked.connect(self.try_login); v.addWidget(b)
        forgot=QPushButton("Passwort vergessen?"); forgot.setFlat(True); forgot.clicked.connect(lambda:PasswordResetDialog().exec()); v.addWidget(forgot)
        self.password.returnPressed.connect(self.try_login)
    def try_login(self):
        username=self.username.text().strip(); con=sqlite3.connect(DBFILE); row=con.execute("SELECT username,display_name,role,password_hash,COALESCE(failed_attempts,0),locked_until FROM users WHERE username=? AND active=1",(username,)).fetchone()
        if row and row[5]:
            try:
                until=datetime.fromisoformat(row[5])
                if datetime.now()<until: con.close(); self.info.setText("Anmeldung vorübergehend gesperrt. Bitte später erneut versuchen."); audit("LOGIN_BLOCKED","Temporäre Anmeldesperre",username); return
            except ValueError: pass
        if row and verify_password(self.password.text(),row[3]):
            con.execute("UPDATE users SET failed_attempts=0,locked_until=NULL WHERE username=?",(username,)); con.commit(); con.close()
            self.user={"username":row[0],"display_name":row[1],"role":row[2]}; audit("LOGIN","Erfolgreiche Anmeldung",row[0]); self.accept()
        else:
            if row:
                attempts=row[4]+1; locked=(datetime.now()+timedelta(minutes=5)).isoformat(timespec="seconds") if attempts>=5 else None
                con.execute("UPDATE users SET failed_attempts=?,locked_until=? WHERE username=?",(0 if locked else attempts,locked,username)); con.commit()
            con.close(); audit("LOGIN_FAILED","Fehlgeschlagene Anmeldung",username); self.info.setText("Benutzername oder Passwort ist nicht korrekt. Nach 5 Fehlversuchen erfolgt eine 5-Minuten-Sperre."); self.password.clear()

def ensure_first_user():
    con=sqlite3.connect(DBFILE); count=con.execute("SELECT COUNT(*) FROM users").fetchone()[0]; con.close()
    if count: return True
    d=QDialog(); d.setWindowTitle("PraxisPro – Ersteinrichtung"); d.setMinimumWidth(460); v=QVBoxLayout(d)
    v.addWidget(QLabel("Ersten Administrator anlegen"))
    name=QLineEdit("Erdogan"); name.setPlaceholderText("Benutzername")
    display=QLineEdit(get_setting("owner_name","Erdoğan Kulanoğlu")); display.setPlaceholderText("Anzeigename")
    p1=QLineEdit(); p1.setEchoMode(QLineEdit.Password); p1.setPlaceholderText("Passwort – mindestens 8 Zeichen")
    p2=QLineEdit(); p2.setEchoMode(QLineEdit.Password); p2.setPlaceholderText("Passwort wiederholen")
    question=QLineEdit(); question.setPlaceholderText("Sicherheitsfrage, z. B. Name meiner ersten Schule?")
    answer=QLineEdit(); answer.setPlaceholderText("Antwort auf die Sicherheitsfrage")
    for w in (name,display,p1,p2,question,answer): v.addWidget(w)
    buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); v.addWidget(buttons)
    def create():
        if not name.text().strip() or len(p1.text())<8 or p1.text()!=p2.text() or not question.text().strip() or not answer.text().strip(): QMessageBox.warning(d,"Ersteinrichtung","Benutzername, zwei gleiche Passwörter, Sicherheitsfrage und Antwort sind erforderlich."); return
        con=sqlite3.connect(DBFILE); con.execute("INSERT INTO users(username,display_name,role,active,password_hash,created_at,recovery_question,recovery_answer_hash) VALUES(?,?,?,?,?,?,?,?)",(name.text().strip(),display.text().strip() or name.text().strip(),"Administrator",1,password_hash(p1.text()),datetime.now().isoformat(timespec="seconds"),question.text().strip(),password_hash(normalize_recovery_answer(answer.text())))); con.commit(); con.close(); audit("FIRST_ADMIN_CREATED",display.text().strip(),name.text().strip()); d.accept()
    buttons.accepted.connect(create); buttons.rejected.connect(d.reject)
    return d.exec()==QDialog.Accepted

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.current_user={}; self.last_activity=datetime.now(); self.setWindowTitle(f"PraxisPro v{APP_VERSION} – Erdoğan Kulanoğlu"); self.resize(1280,820); self.setMinimumSize(1050,700)
        self.started=None; self.acc=0; self.running=False; self.restore_draft_pending=True
        shell=QWidget(); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(225); sv=QVBoxLayout(sidebar); sv.setContentsMargins(12,14,12,14)
        brand=QLabel("PRAXISPRO  v"+APP_VERSION+"\n"+get_setting("practice_name","Psychologische Privatpraxis")); brand.setObjectName("brand"); brand.setWordWrap(True); sv.addWidget(brand)
        self.nav=QListWidget(); self.nav.setObjectName("nav")
        for x in ["⌂  Dashboard","＋  Sitzung","✦  Sitzungsassistent","♙  Klienten","♙＋ Neuer Klient","▤  Neue Rechnung","▣  Rechnungen","⚙  Praxiseinstellungen","?  Benutzerhandbuch"]: self.nav.addItem(x)
        sv.addWidget(self.nav,1)
        foot=QLabel(get_setting("copyright","© 2026 Erdoğan Kulanoğlu")); foot.setObjectName("sidefoot"); sv.addWidget(foot)
        content=QWidget(); contentv=QVBoxLayout(content); contentv.setContentsMargins(0,0,0,0); contentv.setSpacing(0)
        topbar=QFrame(); topbar.setObjectName("topBrandBar"); topbar.setFixedHeight(96); tb=QHBoxLayout(topbar); tb.setContentsMargins(24,8,28,8); tb.addStretch()
        self.top_logo=QLabel(); self.top_logo.setAlignment(Qt.AlignRight|Qt.AlignVCenter); self.top_logo.setMinimumWidth(330)
        logo_path=practice_logo_path()
        if logo_path:
            px=QPixmap(str(logo_path))
            if not px.isNull(): self.top_logo.setPixmap(px.scaled(330,78,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        tb.addWidget(self.top_logo); contentv.addWidget(topbar)
        self.pages=QStackedWidget(); self.pages.addWidget(self.dashboard_ui()); self.pages.addWidget(self.session_ui()); self.pages.addWidget(self.helper_ui()); self.pages.addWidget(self.clients_ui()); self.pages.addWidget(self.new_client_page()); self.pages.addWidget(self.invoice_ui()); self.pages.addWidget(self.invoices_ui()); self.pages.addWidget(self.settings_ui()); self.pages.addWidget(self.manual_ui()); contentv.addWidget(self.pages,1)
        self.nav.currentRowChanged.connect(self.navigate); self.nav.setCurrentRow(0)
        root.addWidget(sidebar); root.addWidget(content,1); self.setCentralWidget(shell)
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.wallclock=QLabel(); self.userbadge=QLabel()
        self.statusBar().addWidget(self.userbadge); self.statusBar().addPermanentWidget(self.wallclock)
        self.update_user_badge()
        self.walltimer=QTimer(self); self.walltimer.timeout.connect(self.update_wallclock); self.walltimer.start(250); self.update_wallclock(); self.locktimer=QTimer(self); self.locktimer.timeout.connect(self.check_autolock); self.locktimer.start(30000)
        self.setStyleSheet("""
        QMainWindow { background:#f4f6f8; }
        #sidebar { background:#132f47; border:0; }
        #brand { color:white; font-size:17px; font-weight:800; padding:5px 8px 12px 8px; letter-spacing:.3px; }
        #sidefoot { color:#b9c8d5; font-size:12px; padding:10px; }
        #nav { background:transparent; border:0; outline:0; color:#dce7ef; font-size:14px; }
        #nav::item { padding:9px 10px; margin:1px 0; border-radius:8px; min-height:21px; }
        #nav::item:selected { background:#2f7de1; color:white; font-weight:700; }
        #nav::item:hover:!selected { background:#244d70; color:white; }
        QStackedWidget { background:#f4f6f8; }\n        #topBrandBar { background:white; border-bottom:1px solid #dce3e9; }
        #pageTitle { font-size:30px; font-weight:800; color:#17324d; }
        #pageSub { font-size:15px; color:#607080; padding-bottom:8px; }
        #statCard { background:white; border:1px solid #dce3e9; border-radius:14px; min-height:115px; }
        #cardCaption { color:#6b7b88; font-size:12px; font-weight:700; }
        #cardValue { color:#17324d; font-size:27px; font-weight:800; }
        #infoBox { background:white; border:1px solid #dce3e9; border-radius:10px; padding:14px; color:#607080; }
        #clientHeader { background:white; border:1px solid #dce3e9; border-radius:14px; padding:12px; }
        #clientName { color:#17324d; font-size:24px; font-weight:800; }
        #clientBadge { background:#e8f0f6; color:#17324d; border-radius:10px; padding:8px 14px; font-weight:700; }
        #sectionTitle { color:#17324d; font-size:16px; font-weight:800; padding-top:2px; }
        #formCard { background:white; border:1px solid #d4e0ea; border-radius:12px; padding:12px; }
        #sessionScroll { background:#f4f6f8; border:0; }
        #sessionScroll > QWidget > QWidget { background:#f4f6f8; }
        QScrollBar:vertical { background:#eef2f5; width:12px; margin:2px; border-radius:6px; }
        QScrollBar::handle:vertical { background:#9fb0bf; min-height:38px; border-radius:6px; }
        QScrollBar:horizontal { background:#eef2f5; height:12px; margin:2px; border-radius:6px; }
        QScrollBar::handle:horizontal { background:#9fb0bf; min-width:38px; border-radius:6px; }
        QTabWidget::pane { border:0; background:white; border-radius:12px; }
        QTabBar::tab { background:#e9eef3; padding:12px 20px; margin:2px; border-radius:8px; font-size:14px; }
        QTabBar::tab:selected { background:#17324d; color:white; font-weight:700; }
        QLabel { color:#1f2933; font-size:13px; }
        QLineEdit,QTextEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox {
            background:white; border:2px solid #b8c7d4; border-radius:9px; padding:8px 10px; min-height:24px; font-size:13px;
            selection-background-color:#17324d;
        }
        QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus,QTimeEdit:focus,QSpinBox:focus {
            border:2px solid #356b92;
        }
        QPushButton { background:#1f6fb2; color:white; border:0; border-radius:9px; padding:9px 14px; font-size:13px; font-weight:600; }
        QPushButton:hover { background:#244d70; }
        QPushButton:disabled { background:#c8d2dc; color:#71808c; }
        QPushButton:pressed { background:#10283d; }
        QCheckBox { spacing:8px; font-size:13px; min-height:26px; }
        QLineEdit[readOnly="true"] { background:#f4f7f9; color:#607080; }
        QTableWidget { background:white; alternate-background-color:#f6f8fa; border:1px solid #d8e0e7; border-radius:8px; gridline-color:#e6ebef; font-size:13px; }
        QHeaderView::section { background:#edf2f6; color:#243746; padding:9px; border:0; border-bottom:1px solid #ccd6df; font-weight:700; }
        QSplitter::handle { background:#d5dde5; height:7px; margin:3px 0; border-radius:3px; }
        QStatusBar { background:#17324d; color:white; }
        QStatusBar QLabel { color:white; font-weight:700; padding:4px 10px; }
        """)
        self.autosave=QTimer(self); self.autosave.timeout.connect(self.autosave_session); self.autosave.start(15000)
        QTimer.singleShot(500,self.restore_draft)
    def update_user_badge(self):
        u=self.current_user or {}; self.userbadge.setText("Angemeldet: "+u.get("display_name",u.get("username",""))+" · "+u.get("role",""))
    def update_wallclock(self):
        now=QTime.currentTime(); self.wallclock.setText("● LIVE  "+now.toString("HH:mm:ss"))
        if hasattr(self,"session_live_clock"): self.session_live_clock.setText(now.toString("HH:mm:ss"))
    def event(self,e):
        if e.type() in (QEvent.MouseButtonPress,QEvent.KeyPress,QEvent.TouchBegin): self.last_activity=datetime.now()
        return super().event(e)
    def check_autolock(self):
        mins=int(get_setting("auto_lock_minutes","15") or 15)
        if mins>0 and (datetime.now()-self.last_activity).total_seconds()>=mins*60:
            self.locktimer.stop(); dlg=LoginDialog()
            if dlg.exec()!=QDialog.Accepted: QApplication.quit(); return
            self.current_user=dlg.user; self.update_user_badge(); self.last_activity=datetime.now(); self.locktimer.start(30000); audit("UNLOCK","Anwendung entsperrt",self.current_user.get("username",""))

    def role(self):
        return (self.current_user or {}).get("role","Therapeut")
    def can_edit(self): return self.role() in ("Administrator","Therapeut")
    def is_admin(self): return self.role()=="Administrator"
    def navigate(self,index):
        # Einstellungen mit Benutzer-/Sicherheitsverwaltung nur für Administratoren.
        if index==7 and not self.is_admin():
            QMessageBox.warning(self,"Keine Berechtigung","Praxiseinstellungen und Benutzerverwaltung sind Administratoren vorbehalten.")
            self.nav.blockSignals(True); self.nav.setCurrentRow(self.pages.currentIndex()); self.nav.blockSignals(False); return
        self.pages.setCurrentIndex(index)
    def require_edit(self):
        if self.can_edit(): return True
        QMessageBox.warning(self,"Nur Lesen","Dieser Benutzer hat nur Leserechte und kann keine Daten verändern.")
        return False

    def session_ui(self):
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(22,16,22,14); v.setSpacing(14)
        top=QHBoxLayout(); head=QVBoxLayout(); title=QLabel("▣  Sitzungsnotiz"); title.setObjectName("pageTitle"); subtitle=QLabel("Sitzung dokumentieren · Klientendaten · Notizen · Handschrift · Speichern"); subtitle.setObjectName("pageSub"); head.addWidget(title); head.addWidget(subtitle)
        self.clock=QLabel("00:00:00"); self.clock.setAlignment(Qt.AlignCenter); self.clock.setFixedSize(155,48); self.clock.setStyleSheet("font-size:24px;font-weight:800;border:2px solid #8091a1;border-radius:10px;background:white")
        timerbtn=QPushButton("▶  Timer starten"); timerbtn.setFixedHeight(48); timerbtn.setMinimumWidth(155); timerbtn.setStyleSheet("background:#16a34a;color:white;font-weight:800;font-size:14px"); timerbtn.clicked.connect(self.start_session)
        self.session_live_clock=QLabel(QTime.currentTime().toString("HH:mm:ss")); self.session_live_clock.setAlignment(Qt.AlignCenter); self.session_live_clock.setFixedSize(120,48); self.session_live_clock.setToolTip("Aktuelle Uhrzeit – live"); self.session_live_clock.setStyleSheet("font-size:19px;font-weight:800;color:#17324d;background:#e8f0f6;border-radius:10px")
        top.addLayout(head); top.addStretch(); top.addWidget(self.session_live_clock); top.addWidget(self.clock); top.addWidget(timerbtn); v.addLayout(top)

        row=QHBoxLayout(); row.setSpacing(14)
        session=QFrame(); session.setObjectName("formCard"); sg=QGridLayout(session); sg.setContentsMargins(16,12,16,14); sg.setHorizontalSpacing(10); sg.setVerticalSpacing(9)
        st=QLabel("▤  Sitzungsdaten"); st.setObjectName("sectionTitle"); sg.addWidget(st,0,0,1,3)
        self.client_pick=QComboBox(); self.client_pick.setEditable(True); self.client_pick.setInsertPolicy(QComboBox.NoInsert); self.client_pick.setPlaceholderText("Klient auswählen …"); self.client_pick.addItem("Klient auswählen …")
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())): self.client_pick.addItem(f"{cc.get('last','')}, {cc.get('first','')}",cc)
        newclient=QPushButton("＋ Neuer Klient"); newclient.setMinimumHeight(42); newclient.clicked.connect(self.open_new_client_dialog)
        self.s_date=QDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_date.setDisplayFormat("dd.MM.yyyy")
        self.s_start=QTimeEdit(); self.s_end=QTimeEdit(); self.s_start.setDisplayFormat("HH:mm"); self.s_end.setDisplayFormat("HH:mm")
        self.s_type=QComboBox(); self.s_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"]); self.s_red=QCheckBox("Ermäßigter Satz")
        for x in (self.client_pick,self.s_date,self.s_start,self.s_end,self.s_type): x.setMinimumHeight(42)
        sg.addWidget(QLabel("Klient *"),1,0); sg.addWidget(self.client_pick,1,1); sg.addWidget(newclient,1,2)
        for rr,(lab,field) in enumerate([("Datum *",self.s_date),("Beginn *",self.s_start),("Ende *",self.s_end),("Art *",self.s_type)],2): sg.addWidget(QLabel(lab),rr,0); sg.addWidget(field,rr,1,1,2)
        sg.addWidget(self.s_red,6,1,1,2); sg.setColumnStretch(1,2); sg.setColumnStretch(2,1); session.setMinimumWidth(480); session.setMinimumHeight(335); row.addWidget(session,5)

        details=QFrame(); details.setObjectName("formCard"); dg=QGridLayout(details); dg.setContentsMargins(16,12,16,14); dg.setHorizontalSpacing(8); dg.setVerticalSpacing(9)
        dt=QLabel("●  Klientendaten"); dt.setObjectName("sectionTitle"); dg.addWidget(dt,0,0,1,2)
        self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit()
        for x in (self.s_last,self.s_first,self.s_dob): x.setMinimumHeight(42); x.setReadOnly(True); x.setPlaceholderText("–")
        self.s_phone=QLineEdit(); self.s_email=QLineEdit()
        for x in (self.s_phone,self.s_email): x.setMinimumHeight(42); x.setReadOnly(True); x.setPlaceholderText("–")
        for rr,(lab,field) in enumerate([("Nachname",self.s_last),("Vorname",self.s_first),("Geburtsdatum",self.s_dob),("Telefon",self.s_phone),("E-Mail",self.s_email)],1): dg.addWidget(QLabel(lab),rr,0); dg.addWidget(field,rr,1)
        details.setMinimumWidth(320); details.setMinimumHeight(335); editclient=QPushButton("♙ Klientendaten bearbeiten"); editclient.setFixedHeight(42); dg.addWidget(editclient,6,0,1,2); row.addWidget(details,3)

        quick=QFrame(); quick.setObjectName("formCard"); qg=QGridLayout(quick); qg.setContentsMargins(16,12,16,14); qg.setHorizontalSpacing(8); qg.setVerticalSpacing(9)
        qt=QLabel("♙＋  Klient schnell anlegen"); qt.setObjectName("sectionTitle"); qg.addWidget(qt,0,0,1,2)
        qlast=QLineEdit(); qfirst=QLineEdit(); qdob=QLineEdit(); qdob.setPlaceholderText("TT.MM.JJJJ"); qphone=QLineEdit(); qmail=QLineEdit()
        for x in (qlast,qfirst,qdob,qphone,qmail): x.setMinimumHeight(42)
        qg.addWidget(QLabel("Nachname *"),1,0); qg.addWidget(QLabel("Vorname *"),1,1); qg.addWidget(qlast,2,0); qg.addWidget(qfirst,2,1)
        qg.addWidget(QLabel("Geburtsdatum"),3,0,1,2); qg.addWidget(qdob,4,0,1,2); qg.addWidget(QLabel("Telefon"),5,0); qg.addWidget(QLabel("E-Mail"),5,1); qg.addWidget(qphone,6,0); qg.addWidget(qmail,6,1)
        qsave=QPushButton("Klient anlegen"); qsave.setFixedHeight(42); qg.addWidget(qsave,7,0,1,2); quick.setMinimumWidth(370); quick.setMinimumHeight(335); row.addWidget(quick,4); v.addLayout(row)

        def add_quick():
            if not self.require_edit(): return
            if not qlast.text().strip() or not qfirst.text().strip(): return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
            cc={"last":qlast.text().strip(),"first":qfirst.text().strip(),"dob":qdob.text().strip(),"phone":qphone.text().strip(),"email":qmail.text().strip(),"address":"","diagnosis":""}
            if any(x.get("last","").lower()==cc["last"].lower() and x.get("first","").lower()==cc["first"].lower() and x.get("dob","")==cc["dob"] for x in DB["clients"]): return QMessageBox.warning(self,"Klient","Dieser Klient ist bereits vorhanden.")
            DB["clients"].append(cc); save_data(); audit("CLIENT_CREATED","Klient schnell angelegt",self.current_user.get("username","") if self.current_user else ""); self.client_pick.addItem(f"{cc['last']}, {cc['first']}",cc); self.client_pick.setCurrentIndex(self.client_pick.count()-1); qlast.clear(); qfirst.clear(); qdob.clear(); qphone.clear(); qmail.clear()
        qsave.clicked.connect(add_quick)
        def picked(_):
            cc=self.client_pick.currentData()
            if isinstance(cc,dict):
                self.s_last.setText(cc.get("last","")); self.s_first.setText(cc.get("first","")); self.s_dob.setText(cc.get("dob","")); self.s_phone.setText(cc.get("phone","")); self.s_email.setText(cc.get("email",""))
        self.client_pick.currentIndexChanged.connect(picked)
        editclient.clicked.connect(self.edit_session_client)

        notesbox=QFrame(); notesbox.setObjectName("formCard"); nv=QVBoxLayout(notesbox); nv.setContentsMargins(16,12,16,14); nv.setSpacing(10); nhead=QHBoxLayout(); nh=QLabel("▤  Therapienotizen"); nh.setObjectName("sectionTitle"); nhead.addWidget(nh); nhead.addStretch(); template=QComboBox(); template.addItems(["Vorlagen","Erstgespräch","Verlauf","Abschluss"]); template.setMinimumWidth(175); template.setMinimumHeight(40); nhead.addWidget(template); nv.addLayout(nhead)
        self.notes=QTextEdit(); self.notes.setPlaceholderText("Hier können Sie Ihre Therapienotizen eingeben …");
        note_tools=QHBoxLayout(); bullet=QPushButton("• Aufzählung"); timestamp=QPushButton("⏱ Zeitmarke"); clear_note=QPushButton("Notiz leeren")
        for b in (bullet,timestamp,clear_note): b.setMinimumHeight(38); note_tools.addWidget(b)
        note_tools.addStretch(); nv.addLayout(note_tools)
        def insert_bullet():
            cur=self.notes.textCursor(); cur.insertText("• "); self.notes.setTextCursor(cur); self.notes.setFocus()
        def insert_timestamp():
            cur=self.notes.textCursor(); cur.insertText(datetime.now().strftime("[%H:%M] ")); self.notes.setTextCursor(cur); self.notes.setFocus()
        def clear_notes():
            if self.notes.toPlainText().strip() and QMessageBox.question(self,"Notiz leeren","Therapienotiz wirklich vollständig leeren?")!=QMessageBox.Yes: return
            self.notes.clear()
        bullet.clicked.connect(insert_bullet); timestamp.clicked.connect(insert_timestamp); clear_note.clicked.connect(clear_notes)
        note_templates={"Erstgespräch":"Anliegen / Auftrag:\n\nAktuelle Situation:\n\nRessourcen:\n\nZiele / Vereinbarungen:\n","Verlauf":"Aktueller Verlauf:\n\nBeobachtungen / Veränderungen:\n\nInterventionen:\n\nVereinbarungen / nächster Schritt:\n","Abschluss":"Rückblick / Zielerreichung:\n\nStabilisierende Faktoren:\n\nOffene Themen:\n\nAbschlussvereinbarung:\n"}
        def apply_note_template(text):
            if text in note_templates and (not self.notes.toPlainText().strip() or QMessageBox.question(self,"Vorlage einsetzen","Vorhandene Notiz durch die gewählte Vorlage ersetzen?")==QMessageBox.Yes): self.notes.setPlainText(note_templates[text])
            template.setCurrentIndex(0)
        template.currentTextChanged.connect(apply_note_template)
        self.notes.setMinimumHeight(145); self.notes.setMaximumHeight(220); self.notes.setStyleSheet("font-size:13px"); nv.addWidget(self.notes); v.addWidget(notesbox)

        self.ink=InkCanvas(); self.current_ink_file=""; inkhead=QHBoxLayout(); inklabel=QLabel("✎  Handschrift / Touch / Stift"); inklabel.setObjectName("sectionTitle"); inkhead.addWidget(inklabel); inkhead.addStretch()
        width=QSpinBox(); width.setRange(1,10); width.setValue(3); width.setSuffix(" px"); width.valueChanged.connect(self.ink.set_width); eraser=QCheckBox("Radierer"); eraser.toggled.connect(self.ink.set_eraser)
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); clearink=QPushButton("Zeichenfläche löschen"); clearink.clicked.connect(self.ink.clear); saveink=QPushButton("💾 Notiz speichern"); saveink.clicked.connect(self.save_ink_note); fullscreen=QPushButton("⛶ Notizbuch"); fullscreen.clicked.connect(self.open_ink_fullscreen)
        for x in (QLabel("Stärke:"),width,eraser,undo,saveink,clearink,fullscreen):
            if hasattr(x,"setMinimumHeight"): x.setMinimumHeight(40)
            inkhead.addWidget(x)
        self.inkbox=QFrame(); self.inkbox.setObjectName("formCard"); self.inkv=QVBoxLayout(self.inkbox); self.inkv.setContentsMargins(16,12,16,14); self.inkv.setSpacing(10); self.inkv.addLayout(inkhead); self.ink.setMinimumHeight(235); self.ink.setStyleSheet("background:white;border:1px dashed #b8c7d4;border-radius:8px"); self.inkv.addWidget(self.ink); v.addWidget(self.inkbox,1)
        h=QHBoxLayout()
        buttons=[("▶ Sitzung starten",self.start_session,"background:#16a34a"),("⏸ Pause/Fortsetzen",self.pause,"background:#1683d8"),("■ Sitzung beenden",self.end_session,"background:#e11d48"),("💾 Speichern",self.save_session,"background:#f8fafc;color:#1261a0;border:1px solid #9bb7cf")]
        for text_,fn,style in buttons:
            b=QPushButton(text_); b.setMinimumHeight(48); b.setStyleSheet(style+";font-weight:800;font-size:13px"); b.clicked.connect(fn); h.addWidget(b)
        v.addLayout(h)
        scroll=QScrollArea(); scroll.setObjectName("sessionScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded); page.setMinimumWidth(0); scroll.setWidget(page); return scroll

    def open_new_client_dialog(self):
        if not self.require_edit(): return
        dlg=QDialog(self); dlg.setWindowTitle("Neuen Klienten anlegen"); dlg.setMinimumWidth(520); form=QFormLayout(dlg)
        last=QLineEdit(); first=QLineEdit(); dob=QLineEdit(); dob.setPlaceholderText("TT.MM.JJJJ"); address=QLineEdit(); diagnosis=QLineEdit(); phone=QLineEdit(); email=QLineEdit()
        form.addRow("Nachname *",last); form.addRow("Vorname *",first); form.addRow("Geburtsdatum",dob); form.addRow("Telefon",phone); form.addRow("E-Mail",email); form.addRow("Adresse",address); form.addRow("Diagnose",diagnosis)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); form.addRow(buttons)
        def save_client():
            if not last.text().strip() or not first.text().strip(): return QMessageBox.warning(dlg,"Fehlt","Vorname und Nachname sind erforderlich.")
            exists=next((x for x in DB["clients"] if x.get("last","").lower()==last.text().strip().lower() and x.get("first","").lower()==first.text().strip().lower() and x.get("dob","")==dob.text().strip()),None)
            if exists:return QMessageBox.warning(dlg,"Klient","Dieser Klient ist bereits vorhanden.")
            cc={"last":last.text().strip(),"first":first.text().strip(),"dob":dob.text().strip(),"phone":phone.text().strip(),"email":email.text().strip(),"address":address.text().strip(),"diagnosis":diagnosis.text().strip()}; DB["clients"].append(cc); save_data()
            if hasattr(self,"client_pick"): self.client_pick.addItem(f"{cc['last']}, {cc['first']}",cc); self.client_pick.setCurrentIndex(self.client_pick.count()-1)
            audit("CLIENT_CREATED","Klient angelegt",self.current_user.get("username","") if self.current_user else ""); dlg.accept()
        buttons.accepted.connect(save_client); buttons.rejected.connect(dlg.reject); dlg.exec()

    def edit_session_client(self):
        cc=self.client_pick.currentData() if hasattr(self,"client_pick") else None
        if not isinstance(cc,dict): return QMessageBox.information(self,"Klient","Bitte zuerst einen Klienten auswählen.")
        dlg=QDialog(self); dlg.setWindowTitle("Klientendaten bearbeiten"); dlg.setMinimumWidth(540); form=QFormLayout(dlg)
        fields={}
        for key,label in [("last","Nachname *"),("first","Vorname *"),("dob","Geburtsdatum"),("phone","Telefon"),("email","E-Mail"),("address","Adresse"),("diagnosis","Diagnose (optional)")]:
            ed=QLineEdit(str(cc.get(key,""))); fields[key]=ed; form.addRow(label,ed)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); form.addRow(buttons)
        def save_edit():
            if not fields["last"].text().strip() or not fields["first"].text().strip(): return QMessageBox.warning(dlg,"Fehlt","Vorname und Nachname sind erforderlich.")
            for key,ed in fields.items(): cc[key]=ed.text().strip()
            save_data(); self.s_last.setText(cc.get("last","")); self.s_first.setText(cc.get("first","")); self.s_dob.setText(cc.get("dob","")); self.s_phone.setText(cc.get("phone","")); self.s_email.setText(cc.get("email",""))
            idx=self.client_pick.currentIndex(); self.client_pick.setItemText(idx,f'{cc.get("last","")}, {cc.get("first","")}'); audit("CLIENT_UPDATED","Klientendaten bearbeitet",self.current_user.get("username","") if self.current_user else ""); dlg.accept()
        buttons.accepted.connect(save_edit); buttons.rejected.connect(dlg.reject); dlg.exec()

    def save_ink_note(self):
        last=self.s_last.text().strip() if hasattr(self,"s_last") else ""
        first=self.s_first.text().strip() if hasattr(self,"s_first") else ""
        if not last or not first: return QMessageBox.warning(self,"Freihand-Notiz","Bitte zuerst einen Klienten auswählen.")
        folder=client_folder(last,first)/"Sitzungen"; folder.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); tmp=folder/f"Freihand_{stamp}.png"
        if not self.ink.save_png(tmp): return QMessageBox.warning(self,"Freihand-Notiz","Die Notiz konnte nicht gespeichert werden.")
        enc=encrypt_file(tmp); self.current_ink_file=enc; audit("INK_NOTE_SAVED",f"Freihand-Notiz gespeichert: {last}, {first}",self.current_user.get("username","") if self.current_user else "")
        QMessageBox.information(self,"Freihand-Notiz","Die Freihand-Notiz wurde verschlüsselt beim Klienten gespeichert.\n\n"+str(Path(enc).name))

    def open_ink_fullscreen(self):
        dlg=QDialog(self); dlg.setWindowTitle("Freihand-Notizbuch"); dlg.resize(1280,800); dlg.setMinimumSize(760,520); dlg.setWindowFlag(Qt.WindowMaximizeButtonHint,True)
        v=QVBoxLayout(dlg); bar=QHBoxLayout(); title=QLabel("Handschrift / Stift"); title.setStyleSheet("font-size:22px;font-weight:700"); bar.addWidget(title); bar.addStretch()
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); erase=QCheckBox("Radierer"); erase.setChecked(self.ink.eraser); erase.toggled.connect(self.ink.set_eraser)
        width=QSpinBox(); width.setRange(1,10); width.setValue(self.ink.pen_width); width.valueChanged.connect(self.ink.set_width)
        zoom=QSlider(Qt.Horizontal); zoom.setRange(60,180); zoom.setValue(100); zoom.setFixedWidth(170); zoomlabel=QLabel("100 %")
        save=QPushButton("💾 Notiz speichern"); save.clicked.connect(self.save_ink_note); clear=QPushButton("Löschen"); clear.clicked.connect(self.ink.clear); full=QPushButton("⛶ Vollbild"); full.setCheckable(True); full.toggled.connect(lambda on: dlg.showFullScreen() if on else dlg.showNormal()); close=QPushButton("✓ Zur Sitzung"); close.clicked.connect(dlg.accept)
        for x in (undo,erase,QLabel("Stärke"),width,QLabel("Ansicht"),zoom,zoomlabel,save,clear,full,close): bar.addWidget(x)
        v.addLayout(bar); holder=QScrollArea(); holder.setWidgetResizable(False); holder.setAlignment(Qt.AlignCenter); self.ink.setParent(holder); holder.setWidget(self.ink)
        basew,baseh=max(1200,self.ink.image.width()),max(700,self.ink.image.height())
        def scale_ink(value):
            zoomlabel.setText(f"{value} %"); self.ink.resize(int(basew*value/100),int(baseh*value/100))
        zoom.valueChanged.connect(scale_ink); scale_ink(100); v.addWidget(holder,1)
        dlg.exec()
        self.ink.setParent(self.inkbox); self.inkv.addWidget(self.ink); self.ink.show()

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
        # F-Code-Schnellzugriff als Arbeitshilfe (keine automatische Diagnose)
        fcodes={
          "F32.0":"Leichte depressive Episode","F32.1":"Mittelgradige depressive Episode","F32.2":"Schwere depressive Episode ohne psychotische Symptome","F33.0":"Rezidivierende depressive Störung, gegenwärtig leichte Episode","F33.1":"Rezidivierende depressive Störung, gegenwärtig mittelgradige Episode","F40.0":"Agoraphobie","F40.1":"Soziale Phobien","F41.0":"Panikstörung","F41.1":"Generalisierte Angststörung","F43.0":"Akute Belastungsreaktion","F43.1":"Posttraumatische Belastungsstörung","F43.2":"Anpassungsstörungen","F45.0":"Somatisierungsstörung","F50.0":"Anorexia nervosa","F50.2":"Bulimia nervosa","F51.0":"Nichtorganische Insomnie","F60.3":"Emotional instabile Persönlichkeitsstörung","F90.0":"Einfache Aktivitäts- und Aufmerksamkeitsstörung"
        }
        codebox=QFrame(); codebox.setObjectName("formCard"); cg=QHBoxLayout(codebox); self.help_fcode=QComboBox(); self.help_fcode.setEditable(True); self.help_fcode.addItem("F-Code auswählen / suchen …");
        for code,name in fcodes.items(): self.help_fcode.addItem(f"{code} – {name}")
        cg.addWidget(QLabel("ICD-10-GM / F-Code")); cg.addWidget(self.help_fcode,1); v.addWidget(codebox)
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
        p=ROOT/"Sitzung_Autosave.json.enc"
        legacy=ROOT/"Sitzung_Autosave.json"
        if not p.exists() and not legacy.exists(): return
        try:
            if p.exists(): d=json.loads(decrypt_text(p.read_text(encoding="utf-8")))
            else:
                d=json.loads(legacy.read_text(encoding="utf-8")); p.write_text(encrypt_text(json.dumps(d,ensure_ascii=False)),encoding="utf-8"); legacy.unlink()
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
        inkdraft=ROOT/"Sitzung_Autosave_Handschrift.png"; self.ink.save_png(inkdraft); encrypted_ink=encrypt_file(inkdraft); draft["ink_file"]=encrypted_ink
        (ROOT/"Sitzung_Autosave.json.enc").write_text(encrypt_text(json.dumps(draft,ensure_ascii=False)),encoding="utf-8")
    def fill_session_client(self):
        last,first=self.s_last.text().strip().lower(),self.s_first.text().strip().lower()
        x=next((c for c in DB["clients"] if c.get("last","").lower()==last and (not first or c.get("first","").lower()==first)),None)
        if x:
            self.s_first.setText(x.get("first","")); self.s_last.setText(x.get("last","")); self.s_dob.setText(x.get("dob","")); self.s_phone.setText(x.get("phone","")); self.s_email.setText(x.get("email",""))
    def start_session(self):
        if not self.require_edit(): return
        now=datetime.now(); self.s_date.setDate(QDate.currentDate()); self.s_start.setTime(QTime.currentTime()); self.s_end.setTime(QTime.currentTime()); self.started=now; self.acc=0; self.running=True; self.update_wallclock()
    def pause(self):
        if not self.require_edit(): return
        if self.running and self.started: self.acc+=(datetime.now()-self.started).total_seconds(); self.running=False
        else:self.started=datetime.now(); self.running=True
    def elapsed(self):
        x=self.acc
        if self.running and self.started:x+=(datetime.now()-self.started).total_seconds()
        return int(x)
    def tick(self):
        s=self.elapsed(); self.clock.setText(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}")
    def end_session(self):
        if not self.require_edit(): return
        if self.running and self.started:self.acc+=(datetime.now()-self.started).total_seconds()
        self.running=False
        # Endzeit wird beim Beenden mit der realen Uhrzeit vorbelegt, bleibt aber editierbar.
        self.s_end.setTime(QTime.currentTime()); self.update_wallclock()
    def save_session(self):
        if not self.require_edit(): return
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
        d=client_dir(c)/"Sitzungen"; inkfile=d/f"{rec['date']}_{rec['id']}_Handschrift.png"; self.ink.save_png(inkfile); rec["ink_file"]=encrypt_file(inkfile)
        DB["sessions"].append(rec); save_data(); (d/f"{rec['date']}_Sitzung.json.enc").write_text(encrypt_text(json.dumps(rec,ensure_ascii=False,indent=2)),encoding="utf-8")
        for auto in (ROOT/"Sitzung_Autosave.json.enc",ROOT/"Sitzung_Autosave.json",ROOT/"Sitzung_Autosave_Handschrift.png",ROOT/"Sitzung_Autosave_Handschrift.png.enc"):
            if auto.exists():
                try:auto.unlink()
                except Exception:pass
        QMessageBox.information(self,"Gespeichert",f"Sitzung gespeichert: {mins} Minuten.")
    def invoice_ui(self):
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(28,24,28,34); v.setSpacing(16)
        title=QLabel("Neue Rechnung"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Einzelrechnung oder Sammelrechnung aus noch nicht abgerechneten Sitzungen"); sub.setObjectName("pageSub"); v.addWidget(sub)
        card=QFrame(); card.setObjectName("formCard"); f=QFormLayout(card); f.setSpacing(12)
        self.i_no=QLineEdit(next_no()); self.i_last=QLineEdit(); self.i_first=QLineEdit(); self.i_addr=QLineEdit(); self.i_diag=QLineEdit(); self.pending_sessions=None; self.manual_items=[]
        for ed in (self.i_no,self.i_last,self.i_first,self.i_addr,self.i_diag): ed.setMinimumHeight(40)
        self.i_date=QDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_date.setDisplayFormat("dd.MM.yyyy"); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Sonstige"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigter Satz")
        self.i_start=QTimeEdit(); self.i_start.setDisplayFormat("HH:mm"); self.i_end=QTimeEdit(); self.i_end.setDisplayFormat("HH:mm")
        for ed in (self.i_date,self.i_type,self.i_min,self.i_start,self.i_end): ed.setMinimumHeight(40)
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
        self.itemtable=QTableWidget(0,6); self.itemtable.setHorizontalHeaderLabels(["Datum","Zeit","Min.","Leistung","Satz","Betrag"]); self.itemtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.itemtable.setSelectionBehavior(QTableWidget.SelectRows); self.itemtable.setEditTriggers(QTableWidget.NoEditTriggers); self.itemtable.setMinimumHeight(170); self.itemtable.setMaximumHeight(260); v.addWidget(self.itemtable)
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
        qrow=QHBoxLayout(); q=QPushButton("Unberechnete Sitzungen laden / Sammelrechnung"); q.setMinimumHeight(50); q.clicked.connect(self.load_unbilled_sessions)
        quarter=QComboBox(); quarter.setMinimumHeight(50); quarter.addItems(["Alle offenen Sitzungen","1. Quartal","2. Quartal","3. Quartal","4. Quartal"]); quarter.setMinimumWidth(180); self.invoice_quarter=quarter
        qrow.addWidget(q,1); qrow.addWidget(quarter); v.addLayout(qrow)
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
        b=QPushButton("PDF-Rechnung erstellen"); b.setMinimumHeight(60); b.clicked.connect(self.make_invoice); v.addWidget(b); v.addSpacing(20); scroll.setWidget(page); outer.addWidget(scroll); return w
    def fill_invoice_client(self):
        last,first=self.i_last.text().strip().lower(),self.i_first.text().strip().lower()
        x=next((c for c in DB["clients"] if c.get("last","").lower()==last and (not first or c.get("first","").lower()==first)),None)
        if x:
            self.i_first.setText(x.get("first","")); self.i_last.setText(x.get("last","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis",""))
    def load_unbilled_sessions(self):
        last,first=self.i_last.text().strip().lower(),self.i_first.text().strip().lower()
        rows=sorted([s for s in DB["sessions"] if not s.get("billed") and s.get("last","").lower()==last and s.get("first","").lower()==first],key=lambda s:(s.get("date",""),s.get("start","")))
        qidx=self.invoice_quarter.currentIndex() if hasattr(self,"invoice_quarter") else 0
        if qidx:
            def in_quarter(s):
                try:
                    m=int(str(s.get("date","")).split("-")[1]); return ((m-1)//3)+1==qidx
                except Exception:return False
            rows=[s for s in rows if in_quarter(s)]
        if not rows: return QMessageBox.information(self,"Sitzungen","Keine unberechneten Sitzungen für diesen Klienten gefunden.")
        dlg=QDialog(self); dlg.setWindowTitle("Unberechnete Sitzungen auswählen"); dlg.resize(920,560); lay=QVBoxLayout(dlg)
        info=QLabel(f"{len(rows)} unberechnete Sitzungen gefunden. Bitte die Leistungen für diese Rechnung auswählen."); info.setWordWrap(True); lay.addWidget(info)
        table=QTableWidget(0,6); table.setHorizontalHeaderLabels(["Übernehmen","Datum","Zeit","Min.","Leistung","Betrag"]); table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for s in rows:
            rr=table.rowCount(); table.insertRow(rr); chk=QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable|Qt.ItemIsEnabled); chk.setCheckState(Qt.Checked); table.setItem(rr,0,chk)
            amount=amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False)))
            vals=[s.get("date",""),f'{s.get("start","")}–{s.get("end","")}',str(s.get("minutes",0)),s.get("type",""),f"{amount:.2f} €"]
            for j,val in enumerate(vals,1): table.setItem(rr,j,QTableWidgetItem(str(val)))
        lay.addWidget(table)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); lay.addWidget(buttons); buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
        if dlg.exec()!=QDialog.Accepted:return
        selected=[s for idx,s in enumerate(rows) if table.item(idx,0) and table.item(idx,0).checkState()==Qt.Checked]
        if not selected:return QMessageBox.information(self,"Sitzungen","Es wurde keine Sitzung ausgewählt.")
        self.pending_sessions=selected; self.manual_items=[]
        if hasattr(self,"itemtable"):
            self.itemtable.setRowCount(0)
            for s in selected:
                rr=self.itemtable.rowCount(); self.itemtable.insertRow(rr); amount=amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False)))
                vals=[s.get("date",""),f'{s.get("start","")}–{s.get("end","")}',str(s.get("minutes",0)),s.get("type",""),"ermäßigt" if s.get("reduced") else "regulär",f"{amount:.2f} €"]
                for j,val in enumerate(vals):self.itemtable.setItem(rr,j,QTableWidgetItem(str(val)))
        self.iteminfo.setText(f"{len(selected)} Sitzungen für Sammelrechnung ausgewählt")
        rows=selected
        details="\n".join(f'{s.get("date","")} | {s.get("start","")}–{s.get("end","")} | {s.get("minutes",0)} Min. | {s.get("type","")}' for s in rows)
        total=sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows)
        QMessageBox.information(self,"Quartals-/Sammelrechnung",f"{len(rows)} unberechnete Sitzungen gefunden.\n\n{details}\n\nGesamt: {total:.2f} €\n\nBitte vor PDF-Erstellung kontrollieren.")
    def make_invoice(self):
        if not self.require_edit(): return
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
        # Layout nach der bisherigen Praxis-Rechnungsvorlage
        logo_path=practice_logo_path()
        if logo_path:
            try: can.drawImage(str(logo_path),W-230,H-110,width=180,height=72,preserveAspectRatio=True,mask="auto")
            except Exception: pass
        owner=get_setting("owner_name","Erdoğan Kulanoğlu"); address=get_setting("address","")
        can.setFillColor(HexColor("#000000")); can.setFont("Helvetica",7)
        can.drawString(50,H-125,f"{owner} · {address}")
        y=H-145; can.setFont("Helvetica",10); can.drawString(50,y,f"{first} {last}"); y-=14
        if self.i_addr.text().strip():
            for line in self.i_addr.text().strip().splitlines(): can.drawString(50,y,line); y-=13
        can.setFont("Helvetica",10); can.drawRightString(W-50,H-235,datetime.now().strftime("%d.%m.%Y"))
        can.setFont("Helvetica-Bold",11); can.drawCentredString(W/2,H-270,f"Rechnungsnummer {no}")
        can.setFont("Helvetica",10); can.drawString(50,H-300,"Für meine Bemühungen erlaube ich mir Ihnen folgende Leistungen in Rechnung zu stellen:")
        if self.i_diag.text().strip():
            can.drawString(50,H-320,"Diagnose: "+self.i_diag.text().strip())
            table_y=H-350
        else: table_y=H-335
        can.setFont("Helvetica-Bold",10); can.drawString(50,table_y+18,"Leistungen:")
        items=[]
        if rows:
            for s in rows:
                items.append({"date":s.get("date",""),"start":s.get("start",""),"end":s.get("end",""),"minutes":int(s.get("minutes",0)),"type":s.get("type",""),"reduced":bool(s.get("reduced",False)),"amount":float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False)))))})
        else:
            items=[{"date":self.i_date.date().toString("dd.MM.yyyy"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amt}]
        def display_date(value):
            try:return datetime.strptime(str(value),"%Y-%m-%d").strftime("%d.%m.%Y")
            except:return str(value)
        x=[50,112,198,286,394,456,W-50]; rowh=18
        headers=["Datum","Anfang–Ende","Dauer in Minuten","Leistung","Ermäßigt","Betrag"]
        can.setLineWidth(.5); can.setFont("Helvetica-Bold",8)
        for j,h in enumerate(headers): can.drawString(x[j]+3,table_y-12,h)
        can.line(x[0],table_y,x[-1],table_y); can.line(x[0],table_y-rowh,x[-1],table_y-rowh)
        for xx in x: can.line(xx,table_y,xx,table_y-rowh*(len(items)+2))
        cy=table_y-rowh
        can.setFont("Helvetica",8)
        for it in items:
            vals=[display_date(it["date"]),f'{it["start"]}–{it["end"]}',str(it["minutes"]),it["type"],"Ja" if it["reduced"] else "Nein",f'{it["amount"]:.2f} €'.replace(".",",")]
            for j,val in enumerate(vals):
                if j==5: can.drawRightString(x[j+1]-4,cy-12,val)
                else: can.drawString(x[j]+3,cy-12,val)
            cy-=rowh; can.line(x[0],cy,x[-1],cy)
        can.setFont("Helvetica-Bold",8); can.drawString(x[0]+3,cy-12,"Rechnungssumme:"); can.drawRightString(x[-1]-4,cy-12,f'{amt:.2f} €'.replace(".",","))
        cy-=rowh; can.line(x[0],cy,x[-1],cy)
        pay_y=cy-42; can.setFont("Helvetica",9)
        iban=get_setting("iban",""); bic=get_setting("bic",""); paypal=get_setting("paypal","")
        text=f"Bitte überweisen Sie den o.g. Betrag in den nächsten 14 Tagen auf die folgende Bankverbindung: IBAN: {iban} - BIC: {bic} mit dem Verwendungszweck: {no}."
        words=text.split(); line=""; lines=[]
        for word in words:
            test=(line+" "+word).strip()
            if can.stringWidth(test,"Helvetica",9)>W-100: lines.append(line); line=word
            else: line=test
        if line: lines.append(line)
        for line in lines: can.drawString(50,pay_y,line); pay_y-=13
        if paypal: can.drawString(50,pay_y,f"Sie können den Betrag auch per PayPal an {paypal} senden."); pay_y-=38
        else: pay_y-=25
        can.drawString(50,pay_y,"Mit freundlichen Grüßen"); pay_y-=35
        can.drawString(50,pay_y,owner); pay_y-=18
        can.setFont("Helvetica-Bold",9); can.drawString(50,pay_y,"Dieses Dokument wurde elektronisch erstellt und ist auch ohne Unterschrift und Stempel gültig.")
        footer_y=58; can.setFont("Helvetica",6.5)
        footer=[
          f'{owner} - {get_setting("qualifications","")}',
          get_setting("address","")+" - Steuernummer: "+get_setting("tax_number",""),
          "Tel.: "+get_setting("phone","")+" - Fax: "+get_setting("fax","")+" - "+get_setting("email","")+" - "+get_setting("website",""),
          "Bankverbindung: IBAN: "+iban+" - BIC: "+bic,
          "Die Leistungen als Heilpraktiker sind nach § 4 Nr. 14 Buchstabe a UStG von der Umsatzsteuer befreit."
        ]
        for line in footer:
            can.drawCentredString(W/2,footer_y,line); footer_y-=9
        can.save()
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
    def new_client_page(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(16)
        title=QLabel("Neuen Klienten anlegen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Stammdaten einmal erfassen und anschließend direkt für Sitzungen und Rechnungen verwenden."); sub.setObjectName("pageSub"); v.addWidget(sub)
        card=QFrame(); card.setObjectName("formCard"); form=QFormLayout(card); form.setSpacing(14)
        last=QLineEdit(); first=QLineEdit(); dob=QLineEdit(); dob.setPlaceholderText("TT.MM.JJJJ"); phone=QLineEdit(); email=QLineEdit(); address=QLineEdit(); diagnosis=QLineEdit()
        for x in (last,first,dob,phone,email,address,diagnosis): x.setMinimumHeight(44)
        form.addRow("Nachname *",last); form.addRow("Vorname *",first); form.addRow("Geburtsdatum",dob); form.addRow("Telefon",phone); form.addRow("E-Mail",email); form.addRow("Adresse",address); form.addRow("Diagnose (optional)",diagnosis); v.addWidget(card)
        row=QHBoxLayout(); save=QPushButton("💾 Klient anlegen"); save.setMinimumHeight(52); session=QPushButton("＋ Anlegen und Sitzung öffnen"); session.setMinimumHeight(52)
        def create(go_session=False):
            if not self.require_edit():return
            if not last.text().strip() or not first.text().strip():return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
            cc={"last":last.text().strip(),"first":first.text().strip(),"dob":dob.text().strip(),"phone":phone.text().strip(),"email":email.text().strip(),"address":address.text().strip(),"diagnosis":diagnosis.text().strip()}
            if any(x.get("last","").lower()==cc["last"].lower() and x.get("first","").lower()==cc["first"].lower() and x.get("dob","")==cc["dob"] for x in DB["clients"]):return QMessageBox.warning(self,"Klient","Dieser Klient ist bereits vorhanden.")
            DB["clients"].append(cc); save_data(); audit("CLIENT_CREATED","Klient angelegt",self.current_user.get("username","") if self.current_user else "")
            if hasattr(self,"client_pick"): self.client_pick.addItem(f"{cc['last']}, {cc['first']}",cc)
            if go_session:
                self.s_last.setText(cc["last"]); self.s_first.setText(cc["first"]); self.s_dob.setText(cc["dob"]); self.s_phone.setText(cc.get("phone","")); self.s_email.setText(cc.get("email","")); self.client_pick.setCurrentIndex(self.client_pick.count()-1); self.nav.setCurrentRow(1)
            else:
                QMessageBox.information(self,"Klient","Klient wurde angelegt."); last.clear(); first.clear(); dob.clear(); phone.clear(); email.clear(); address.clear(); diagnosis.clear()
        save.clicked.connect(lambda:create(False)); session.clicked.connect(lambda:create(True)); row.addWidget(save); row.addWidget(session); v.addLayout(row); v.addStretch(); return w

    def clients_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Klienten"); title.setObjectName("pageTitle"); v.addWidget(title)
        tools=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Klient suchen …"); search.setClearButtonEnabled(True); tools.addWidget(search,1); v.addLayout(tools)
        t=QTableWidget(0,5); t.setHorizontalHeaderLabels(["Nachname","Vorname","Geburtsdatum","Telefon","E-Mail"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); t.setAlternatingRowColors(True); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers)
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
            r=t.rowCount(); t.insertRow(r)
            for j,k in enumerate(["last","first","dob","phone","email"]): t.setItem(r,j,QTableWidgetItem(str(cc.get(k,""))))
        v.addWidget(t)
        def filter_clients(txt):
            q=txt.strip().lower()
            for row in range(t.rowCount()):
                hay=" ".join(t.item(row,col).text().lower() if t.item(row,col) else "" for col in range(t.columnCount()))
                t.setRowHidden(row,q not in hay)
        search.textChanged.connect(filter_clients)
        opensessions=QPushButton("Klientenakte öffnen"); opensessions.setMinimumHeight(48)
        editclient=QPushButton("Klientendaten bearbeiten"); editclient.setMinimumHeight(48)
        def show_sessions():
            r=t.currentRow()
            if r<0:return
            last=t.item(r,0).text(); first=t.item(r,1).text()
            rows=[s for s in DB["sessions"] if s.get("last")==last and s.get("first")==first]
            dlg=QDialog(self); dlg.setWindowTitle(f"Klientenakte – {first} {last}"); dlg.resize(980,700); lay=QVBoxLayout(dlg)
            head=QFrame(); head.setObjectName("clientHeader"); hv=QHBoxLayout(head); person=QVBoxLayout(); nm=QLabel(f"{first} {last}"); nm.setObjectName("clientName"); dob=t.item(r,2).text() if t.item(r,2) else ""; meta=QLabel(("Geburtsdatum: "+dob) if dob else "Geburtsdatum nicht hinterlegt"); meta.setObjectName("pageSub"); person.addWidget(nm);person.addWidget(meta);hv.addLayout(person);hv.addStretch(); phone=t.item(r,3).text() if t.item(r,3) else ""; email=t.item(r,4).text() if t.item(r,4) else ""
            cc=next((x for x in DB["clients"] if x.get("last")==last and x.get("first")==first),{})
            contact=QLabel(" · ".join(x for x in [phone,email,cc.get("address","")] if x) or "Keine Kontaktdaten hinterlegt"); contact.setObjectName("pageSub"); contact.setWordWrap(True); person.addWidget(contact)
            count=QLabel(f"{len(rows)} Sitzungen"); count.setObjectName("clientBadge");hv.addWidget(count);lay.addWidget(head)
            stats=QHBoxLayout()
            total_minutes=sum(int(s.get("minutes",0) or 0) for s in rows); unbilled=sum(1 for s in rows if not s.get("billed"))
            client_invoice_keys={f"{last}, {first}",f"{first} {last}"}
            client_invoices=[i for i in DB["invoices"] if str(i.get("client","")).strip() in client_invoice_keys]
            open_invoices=[i for i in client_invoices if i.get("status","offen")=="offen"]
            open_amount=sum(float(i.get("amount",0) or 0) for i in open_invoices)
            for txt in (f"Gesamt: {len(rows)} Sitzungen",f"Therapiezeit: {total_minutes} Min.",f"Nicht abgerechnet: {unbilled}",f"Offene Rechnungen: {len(open_invoices)} · {open_amount:.2f} €"):
                badge=QLabel(txt); badge.setObjectName("clientBadge"); badge.setAlignment(Qt.AlignCenter); badge.setMinimumHeight(38); stats.addWidget(badge)
            lay.addLayout(stats)
            section=QLabel("Sitzungsverlauf"); section.setObjectName("sectionTitle"); lay.addWidget(section)
            st=QTableWidget(0,6); st.setHorizontalHeaderLabels(["Datum","Beginn","Ende","Min.","Art","Abgerechnet"]); st.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            for s in sorted(rows,key=lambda x:x.get("date",""),reverse=True):
                rr=st.rowCount(); st.insertRow(rr)
                vals=[s.get("date",""),s.get("start",""),s.get("end",""),str(s.get("minutes","")),s.get("type",""),"Ja" if s.get("billed") else "Nein"]
                for j,x in enumerate(vals):st.setItem(rr,j,QTableWidgetItem(x))
            lay.addWidget(st)
            invsection=QLabel("Rechnungen des Klienten"); invsection.setObjectName("sectionTitle"); lay.addWidget(invsection)
            it=QTableWidget(0,5); it.setHorizontalHeaderLabels(["Nr.","Datum","Status","Betrag","Zahlungsdatum"]); it.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); it.setSelectionBehavior(QTableWidget.SelectRows); it.setEditTriggers(QTableWidget.NoEditTriggers); it.setMaximumHeight(180)
            for inv in reversed(client_invoices):
                ir=it.rowCount(); it.insertRow(ir); vals=[inv.get("number",""),inv.get("date",""),inv.get("status","offen"),f'{float(inv.get("amount",0) or 0):.2f} €',inv.get("paid_date","")]
                for j,val in enumerate(vals): it.setItem(ir,j,QTableWidgetItem(str(val)))
            lay.addWidget(it)
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
                    lab=QLabel(); pix=QPixmap(); pix.loadFromData(decrypt_file_bytes(ink)); lab.setPixmap(pix.scaled(820,380,Qt.KeepAspectRatio,Qt.SmoothTransformation)); lab.setAlignment(Qt.AlignCenter); nv.addWidget(lab)
                buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(nd.reject); nv.addWidget(buttons); nd.exec()
            view.clicked.connect(open_selected)
            invoice=QPushButton("Neue Rechnung für diesen Klienten")
            def invoice_from_record():
                self.i_last.setText(last); self.i_first.setText(first); self.i_addr.setText(cc.get("address","")); self.i_diag.setText(cc.get("diagnosis","")); dlg.accept(); self.nav.setCurrentRow(5)
            invoice.clicked.connect(invoice_from_record)
            open_invoice=QPushButton("Ausgewählte Rechnung öffnen")
            def open_client_invoice():
                rr=it.currentRow()
                if rr<0:return QMessageBox.information(dlg,"Rechnung","Bitte zuerst eine Rechnung auswählen.")
                no=it.item(rr,0).text(); inv=next((x for x in client_invoices if x.get("number")==no),None)
                if not inv:return
                p=inv.get("pdf","")
                if p and Path(p).exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
                else: QMessageBox.information(dlg,"PDF","Das Rechnungs-PDF konnte nicht gefunden werden.")
            open_invoice.clicked.connect(open_client_invoice); it.cellDoubleClicked.connect(lambda *_: open_client_invoice())
            actionrow=QHBoxLayout(); actionrow.addWidget(view); actionrow.addWidget(edit); actionrow.addWidget(invoice); actionrow.addWidget(open_invoice); lay.addLayout(actionrow)
            close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dlg.reject); lay.addWidget(close); dlg.exec()
        opensessions.clicked.connect(show_sessions); t.cellDoubleClicked.connect(lambda *_: show_sessions())
        def edit_client_master():
            r=t.currentRow()
            if r<0: return QMessageBox.information(self,"Klient","Bitte zuerst einen Klienten auswählen.")
            last=t.item(r,0).text(); first=t.item(r,1).text()
            cc=next((x for x in DB["clients"] if x.get("last")==last and x.get("first")==first),None)
            if not cc:return
            dlg=QDialog(self); dlg.setWindowTitle("Klientendaten bearbeiten"); dlg.setMinimumWidth(560); form=QFormLayout(dlg); fields={}
            for key,label in [("last","Nachname *"),("first","Vorname *"),("dob","Geburtsdatum"),("phone","Telefon"),("email","E-Mail"),("address","Adresse"),("diagnosis","Diagnose (optional)")]:
                ed=QLineEdit(str(cc.get(key,""))); fields[key]=ed; form.addRow(label,ed)
            buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); form.addRow(buttons)
            def save_master():
                new_last=fields["last"].text().strip(); new_first=fields["first"].text().strip()
                if not new_last or not new_first:return QMessageBox.warning(dlg,"Fehlt","Vorname und Nachname sind erforderlich.")
                old_last,old_first=cc.get("last",""),cc.get("first","")
                name_changed=(old_last!=new_last or old_first!=new_first)
                if name_changed:
                    duplicate=next((x for x in DB["clients"] if x is not cc and x.get("last","").lower()==new_last.lower() and x.get("first","").lower()==new_first.lower() and x.get("dob","")==fields["dob"].text().strip()),None)
                    if duplicate:return QMessageBox.warning(dlg,"Klient","Ein Klient mit diesem Namen und Geburtsdatum existiert bereits.")
                    if QMessageBox.question(dlg,"Name ändern",f"Name von {old_first} {old_last} in {new_first} {new_last} ändern?\n\nZugehörige Sitzungen und Rechnungen werden mit aktualisiert.")!=QMessageBox.Yes:return
                    for sess in DB["sessions"]:
                        if sess.get("last")==old_last and sess.get("first")==old_first:
                            sess["last"]=new_last; sess["first"]=new_first
                    old_keys={f"{old_last}, {old_first}",f"{old_first} {old_last}"}
                    for inv in DB["invoices"]:
                        if str(inv.get("client","")).strip() in old_keys: inv["client"]=f"{new_last}, {new_first}"
                for key,ed in fields.items():cc[key]=ed.text().strip()
                save_data()
                for j,key in enumerate(["last","first","dob","phone","email"]):t.setItem(r,j,QTableWidgetItem(str(cc.get(key,""))))
                audit("CLIENT_UPDATED",("Klientenname und Verknüpfungen aktualisiert" if name_changed else "Klientenstammdaten bearbeitet"),self.current_user.get("username","") if self.current_user else ""); dlg.accept()
            buttons.accepted.connect(save_master); buttons.rejected.connect(dlg.reject); dlg.exec()
        editclient.clicked.connect(edit_client_master)
        newclientbtn=QPushButton("＋ Neuen Klienten anlegen"); newclientbtn.setMinimumHeight(48); newclientbtn.clicked.connect(lambda:self.nav.setCurrentRow(4))
        mainactions=QHBoxLayout(); mainactions.addWidget(opensessions); mainactions.addWidget(editclient); mainactions.addWidget(newclientbtn); v.addLayout(mainactions)
        clientactions=QHBoxLayout()
        tosession=QPushButton("＋ Neue Sitzung für Klient"); toinvoice=QPushButton("▤ Neue Rechnung für Klient")
        def selected_client():
            r=t.currentRow()
            if r<0:
                QMessageBox.information(self,"Klient","Bitte zuerst einen Klienten auswählen."); return None
            last=t.item(r,0).text(); first=t.item(r,1).text()
            return next((x for x in DB["clients"] if x.get("last")==last and x.get("first")==first),None)
        def client_to_session():
            x=selected_client()
            if not x:return
            self.client_pick.setCurrentText(f"{x.get('last','')}, {x.get('first','')}"); self.s_last.setText(x.get("last","")); self.s_first.setText(x.get("first","")); self.s_dob.setText(x.get("dob","")); self.s_phone.setText(x.get("phone","")); self.s_email.setText(x.get("email","")); self.nav.setCurrentRow(1)
        def client_to_invoice():
            x=selected_client()
            if not x:return
            self.i_last.setText(x.get("last","")); self.i_first.setText(x.get("first","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis","")); self.nav.setCurrentRow(5)
        tosession.clicked.connect(client_to_session); toinvoice.clicked.connect(client_to_invoice); clientactions.addWidget(tosession); clientactions.addWidget(toinvoice); v.addLayout(clientactions)
        openink=QPushButton("Letzte Handschrift des ausgewählten Klienten anzeigen"); openink.setMinimumHeight(45)
        def show_ink():
            r=t.currentRow()
            if r<0:return
            last=t.item(r,0).text(); first=t.item(r,1).text()
            rows=[s for s in DB["sessions"] if s.get("last")==last and s.get("first")==first and s.get("ink_file") and Path(s.get("ink_file","")).exists()]
            rows.sort(key=lambda s:(s.get("date",""),s.get("start","")),reverse=True)
            if not rows:return QMessageBox.information(self,"Handschrift","Keine handschriftliche Notiz gefunden.")
            data=decrypt_file_bytes(rows[0].get("ink_file","")); pix=QPixmap()
            if not data or not pix.loadFromData(data):return QMessageBox.warning(self,"Handschrift","Die handschriftliche Notiz konnte nicht gelesen werden.")
            dlg=QMessageBox(self); dlg.setWindowTitle("Handschriftliche Notiz"); dlg.setIconPixmap(pix.scaled(900,550,Qt.KeepAspectRatio,Qt.SmoothTransformation)); dlg.exec()
        openink.clicked.connect(show_ink); v.addWidget(openink)
        b=QPushButton("Klientenliste aktualisieren"); b.setMinimumHeight(45)
        def refresh():
            t.setRowCount(0)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                r=t.rowCount(); t.insertRow(r)
                for j,k in enumerate(["last","first","dob","phone","email"]): t.setItem(r,j,QTableWidgetItem(str(cc.get(k,""))))
        b.clicked.connect(refresh); v.addWidget(b); return w
    def invoices_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Rechnungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Offene, bezahlte und stornierte Rechnungen verwalten"); sub.setObjectName("pageSub"); v.addWidget(sub)
        filters=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Rechnung oder Klient suchen …"); search.setClearButtonEnabled(True)
        statusfilter=QComboBox(); statusfilter.addItems(["Alle Status","offen","überfällig","bezahlt","storniert"]); statusfilter.setMinimumWidth(150)
        filters.addWidget(search,1); filters.addWidget(statusfilter); v.addLayout(filters)
        t=QTableWidget(0,8); t.setHorizontalHeaderLabels(["Nr.","Datum","Klient","Status","Zahlungsdatum","Mahnstufe","Letzte Erinnerung","Betrag"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers); t.setAlternatingRowColors(True); t.setToolTip("Doppelklick öffnet die Rechnungsdetails")
        for i in reversed(DB["invoices"]):
            r=t.rowCount(); t.insertRow(r); vals=[i.get("number",""),i.get("date",""),i.get("client",""),i.get("status","offen"),i.get("paid_date",""),str(i.get("reminder_count",0)),i.get("reminder_date",""),f'{float(i.get("amount",0)):.2f} €']
            for j,x in enumerate(vals): t.setItem(r,j,QTableWidgetItem(str(x)))
        def filt(_=None):
            q=search.text().lower().strip(); sf=statusfilter.currentText()
            for r in range(t.rowCount()):
                hay=" ".join(t.item(r,j).text().lower() for j in range(t.columnCount()) if t.item(r,j))
                status=t.item(r,3).text() if t.item(r,3) else ""
                overdue=False
                if status=="offen":
                    try: overdue=(date.today()-datetime.strptime(t.item(r,1).text(),"%Y-%m-%d").date()).days>14
                    except Exception: pass
                status_miss=(sf=="überfällig" and not overdue) or (sf not in ("Alle Status","überfällig") and status!=sf)
                t.setRowHidden(r,(q not in hay) or status_miss)
                if status=="offen":
                    try:
                        inv_date=datetime.strptime(t.item(r,1).text(),"%Y-%m-%d").date()
                        if (date.today()-inv_date).days>14:
                            for j in range(t.columnCount()):
                                if t.item(r,j): t.item(r,j).setToolTip("Zahlungsziel von 14 Tagen überschritten")
                    except Exception: pass
        search.textChanged.connect(filt); statusfilter.currentTextChanged.connect(filt); v.addWidget(t)
        summary=QHBoxLayout()
        overdue_count=0
        today=date.today()
        for inv in DB["invoices"]:
            if inv.get("status","offen")=="offen":
                try:
                    if (today-datetime.strptime(inv.get("date",""),"%Y-%m-%d").date()).days>14: overdue_count+=1
                except Exception: pass
        open_total=sum(float(x.get("amount",0)) for x in DB["invoices"] if x.get("status","offen")=="offen")
        paid_total=sum(float(x.get("amount",0)) for x in DB["invoices"] if x.get("status")=="bezahlt")
        for txt in (f"Offen: {open_total:.2f} €",f"Bezahlt: {paid_total:.2f} €",f"Überfällig >14 Tage: {overdue_count}",f"Rechnungen: {len(DB['invoices'])}"):
            lab=QLabel(txt); lab.setObjectName("clientBadge"); lab.setAlignment(Qt.AlignCenter); lab.setMinimumHeight(40); summary.addWidget(lab)
        v.addLayout(summary)
        h=QHBoxLayout()
        paid=QPushButton("✓ Als bezahlt markieren"); paid.setMinimumHeight(50)
        def selected_invoice():
            r=t.currentRow()
            if r<0:
                QMessageBox.information(self,"Rechnung","Bitte zuerst eine Rechnung auswählen."); return None,None
            no=t.item(r,0).text(); return r,next((x for x in DB["invoices"] if x.get("number")==no),None)
        def mark_paid():
            r,inv=selected_invoice()
            if inv:
                if inv.get("status")=="storniert": return QMessageBox.warning(self,"Status","Eine stornierte Rechnung kann nicht als bezahlt markiert werden.")
                if inv.get("status")=="bezahlt": return QMessageBox.information(self,"Status","Diese Rechnung ist bereits als bezahlt markiert.")
                if QMessageBox.question(self,"Zahlung","Rechnung "+str(inv.get("number",""))+" als bezahlt markieren?")!=QMessageBox.Yes:return
                inv["status"]="bezahlt"; inv["paid_date"]=datetime.now().strftime("%Y-%m-%d"); inv["reminder_closed"]=True; save_data(); update_excel(); audit("INVOICE_PAID","Rechnung "+str(inv.get("number",""))+" als bezahlt markiert",self.current_user.get("username","") if self.current_user else ""); t.item(r,3).setText("bezahlt"); t.item(r,4).setText(inv["paid_date"]); t.item(r,5).setText(str(inv.get("reminder_count",0))); t.item(r,6).setText(inv.get("reminder_date",""))
        paid.clicked.connect(mark_paid); h.addWidget(paid)
        cancel=QPushButton("Rechnung stornieren"); cancel.setMinimumHeight(50)
        def cancel_invoice():
            r,inv=selected_invoice()
            if not inv:return
            if inv.get("status")=="storniert": return QMessageBox.information(self,"Stornieren","Diese Rechnung ist bereits storniert.")
            msg=f'Rechnung {inv.get("number","")} wirklich stornieren?'
            if inv.get("status")=="bezahlt": msg+="\n\nAchtung: Die Rechnung ist bereits als bezahlt markiert."
            if QMessageBox.question(self,"Stornieren",msg)!=QMessageBox.Yes:return
            inv["status"]="storniert"; inv["cancelled_date"]=datetime.now().strftime("%Y-%m-%d"); inv["paid_date"]=""; inv["reminder_closed"]=True
            no=inv.get("number","")
            released=0
            for s in DB["sessions"]:
                if s.get("invoice_number")==no:
                    s["billed"]=False; s["invoice_number"]=""; released+=1
            save_data(); update_excel(); audit("INVOICE_CANCELLED","Rechnung "+str(no)+" storniert",self.current_user.get("username","") if self.current_user else ""); t.item(r,3).setText("storniert"); t.item(r,4).setText("")
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
        openpdf.clicked.connect(open_pdf); h.addWidget(openpdf)
        remind=QPushButton("Zahlungserinnerung"); remind.setMinimumHeight(50)
        def payment_reminder():
            _,inv=selected_invoice()
            if not inv:return
            if inv.get("status")!="offen":return QMessageBox.information(self,"Zahlungserinnerung","Eine Zahlungserinnerung ist nur für offene Rechnungen vorgesehen.")
            if int(inv.get("reminder_count",0))>=3 and QMessageBox.question(self,"Mahnstufe",f'Für diese Rechnung wurden bereits {inv.get("reminder_count",0)} Erinnerungen erfasst. Weitere Erinnerung dokumentieren?')!=QMessageBox.Yes:return
            try: days=(date.today()-datetime.strptime(inv.get("date",""),"%Y-%m-%d").date()).days
            except Exception: days=0
            if days<=14 and QMessageBox.question(self,"Zahlungserinnerung",f"Das 14-tägige Zahlungsziel ist noch nicht überschritten ({days} Tage). Trotzdem Erinnerung erfassen?")!=QMessageBox.Yes:return
            inv["reminder_date"]=datetime.now().strftime("%Y-%m-%d"); inv["reminder_count"]=int(inv.get("reminder_count",0))+1
            save_data(); t.item(t.currentRow(),5).setText(str(inv["reminder_count"])); t.item(t.currentRow(),6).setText(inv["reminder_date"]); audit("PAYMENT_REMINDER",f'Zahlungserinnerung zu Rechnung {inv.get("number","")} erfasst',self.current_user.get("username","") if self.current_user else "")
            QMessageBox.information(self,"Zahlungserinnerung",f'Zahlungserinnerung für Rechnung {inv.get("number","")} wurde dokumentiert.\n\nMahnstufe: {inv["reminder_count"]}\nOffener Betrag: {float(inv.get("amount",0)):.2f} €\nDatum: {inv["reminder_date"]}\n\nDie ursprüngliche Rechnung wurde nicht verändert.')
        remind.clicked.connect(payment_reminder); h.addWidget(remind)
        details=QPushButton("Details"); details.setMinimumHeight(50)
        def invoice_details():
            _,inv=selected_invoice()
            if not inv:return
            items=inv.get("items",[])
            lines="\n".join(f'{x.get("date","")}  {x.get("start","")}–{x.get("end","")}  {x.get("minutes",0)} Min.  {x.get("type","")}  {float(x.get("amount",0)):.2f} €' for x in items) or "Keine Einzelpositionen gespeichert."
            QMessageBox.information(self,"Rechnungsdetails",f'Rechnung: {inv.get("number","")}\nKlient: {inv.get("client","")}\nStatus: {inv.get("status","offen")}\nZahlungsdatum: {inv.get("paid_date","") or "–"}\nLetzte Zahlungserinnerung: {inv.get("reminder_date","") or "–"}\nMahnstufe: {inv.get("reminder_count",0)}\nBetrag: {float(inv.get("amount",0)):.2f} €\n\n{lines}')
        details.clicked.connect(invoice_details); t.cellDoubleClicked.connect(lambda *_: invoice_details()); h.addWidget(details); v.addLayout(h)
        backup=QPushButton("Datensicherung erstellen"); backup.setMinimumHeight(48)
        def do_backup():
            dest=ROOT/"Backups"/datetime.now().strftime("Backup_%Y-%m-%d_%H-%M-%S"); dest.mkdir(parents=True,exist_ok=True)
            if DATA.exists(): shutil.copy2(DATA,dest/DATA.name)
            if DBFILE.exists():
                con=sqlite3.connect(DBFILE); out=sqlite3.connect(dest/DBFILE.name); con.backup(out); out.close(); con.close()
            # Exporte (PDF/XLSX) bleiben bewusst außerhalb der verschlüsselten Datensicherung.
            # Der lokale Hauptschlüssel wird niemals zusammen mit dem Backup kopiert.
            for src in (ROOT/"Klienten").rglob("*.enc"):
                rel=src.relative_to(ROOT/"Klienten"); target=dest/"Klienten"/rel; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,target)
            # Separater Wiederherstellungsschlüssel: bewusst nicht im Backup-Ordner.
            key_export=ROOT/"Backups"/("Wiederherstellungsschluessel_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".key")
            if KEYFILE.exists(): shutil.copy2(KEYFILE,key_export)
            (dest/"Backup_Info.txt").write_text("Praxisverwaltung Sicherung\nErstellt: "+datetime.now().isoformat(timespec="seconds")+"\nKlienten: "+str(len(DB.get("clients",[])))+"\nSitzungen: "+str(len(DB.get("sessions",[])))+"\nRechnungen: "+str(len(DB.get("invoices",[])))+"\nDer Wiederherstellungsschlüssel wurde separat erstellt und darf nicht zusammen mit dem Backup aufbewahrt werden.",encoding="utf-8")
            QMessageBox.information(self,"Sicherung","Sicherung erstellt:\n"+str(dest)+"\n\nWiederherstellungsschlüssel separat erstellt:\n"+str(key_export)+"\n\nBitte Schlüssel und Backup getrennt aufbewahren.")
        backup.clicked.connect(lambda: do_backup() if self.require_edit() else None); v.addWidget(backup)
        restore=QPushButton("Datensicherung wiederherstellen …"); restore.setMinimumHeight(48)
        def do_restore():
            if not self.is_admin(): return QMessageBox.warning(self,"Keine Berechtigung","Wiederherstellung ist Administratoren vorbehalten.")
            folder=QFileDialog.getExistingDirectory(self,"Backup-Ordner auswählen",str(ROOT/"Backups"))
            if not folder:return
            key,_=QFileDialog.getOpenFileName(self,"Wiederherstellungsschlüssel auswählen",str(ROOT/"Backups"),"Schlüssel (*.key);;Alle Dateien (*)")
            if not key:return
            src=Path(folder)
            if not (src/DATA.name).exists() or not (src/DBFILE.name).exists(): return QMessageBox.warning(self,"Wiederherstellung","Der ausgewählte Ordner enthält kein vollständiges PraxisPro-Backup.")
            try:
                testkey=Path(key).read_bytes(); token=(src/DATA.name).read_text(encoding="utf-8")
                if token.startswith("enc:"): Fernet(testkey).decrypt(token[4:].encode("ascii"))
            except Exception:return QMessageBox.critical(self,"Wiederherstellung","Der Schlüssel passt nicht zu dieser Sicherung.")
            if QMessageBox.question(self,"Wiederherstellung","Die aktuellen Praxisdaten werden ersetzt. Fortfahren?")!=QMessageBox.Yes:return
            stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); safety=ROOT/"Backups"/("Vor_Wiederherstellung_"+stamp); safety.mkdir(parents=True,exist_ok=True)
            if DATA.exists():shutil.copy2(DATA,safety/DATA.name)
            if DBFILE.exists():shutil.copy2(DBFILE,safety/DBFILE.name)
            if KEYFILE.exists():shutil.copy2(KEYFILE,safety/KEYFILE.name)
            shutil.copy2(key,KEYFILE); shutil.copy2(src/DATA.name,DATA); shutil.copy2(src/DBFILE.name,DBFILE)
            if (src/"Klienten").exists(): shutil.copytree(src/"Klienten",ROOT/"Klienten",dirs_exist_ok=True)
            audit("BACKUP_RESTORE","Datensicherung wiederhergestellt",self.current_user.get("username","") if self.current_user else "")
            QMessageBox.information(self,"Wiederherstellung","Wiederherstellung abgeschlossen. PraxisPro wird jetzt beendet. Bitte anschließend neu starten."); QApplication.quit()
        restore.clicked.connect(do_restore); v.addWidget(restore); return w
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
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); body=QWidget(); v=QVBoxLayout(body); v.setContentsMargins(32,26,32,36); v.setSpacing(16)
        title=QLabel("Praxiseinstellungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Praxisdaten, Abrechnung, Honorare und Benutzer übersichtlich verwalten."); sub.setObjectName("pageSub"); v.addWidget(sub)
        tabs=QTabWidget(); tabs.setDocumentMode(True); tabs.setMinimumHeight(650); v.addWidget(tabs); scroll.setWidget(body); outer.addWidget(scroll)
        general=QWidget(); gv=QVBoxLayout(general); gv.setContentsMargins(20,22,20,28); gv.setSpacing(18)
        form=QFormLayout(); form.setHorizontalSpacing(28); form.setVerticalSpacing(14); form.setLabelAlignment(Qt.AlignLeft|Qt.AlignVCenter); fields={}
        labels=[("practice_name","Praxisname"),("owner_name","Inhaber / Praxisleitung"),("qualifications","Qualifikationen"),("address","Anschrift"),("phone","Telefon"),("fax","Fax"),("email","E-Mail"),("website","Website"),("manufacturer","Herstellername"),("copyright","Copyright")]
        for key,label in labels:
            ed=QLineEdit(get_setting(key)); ed.setMinimumHeight(42); fields[key]=ed; form.addRow(label,ed)
        logo=QLineEdit(get_setting("logo_path")); logo.setMinimumHeight(42); fields["logo_path"]=logo; choose=QPushButton("Logo auswählen …"); choose.setMinimumHeight(42)
        def pick_logo():
            p,_=QFileDialog.getOpenFileName(self,"Praxislogo auswählen","","Bilder (*.png *.jpg *.jpeg)")
            if p: logo.setText(p)
        choose.clicked.connect(pick_logo); lr=QHBoxLayout(); lr.addWidget(logo,1); lr.addWidget(choose); form.addRow("Praxislogo",lr)
        gv.addLayout(form)
        appearance=QFrame(); appearance.setObjectName("formCard"); af=QFormLayout(appearance)
        theme=QComboBox(); theme.addItems(["PraxisPro Blau","Petrol","Grün","Gold","Violett"]); theme.setCurrentText(get_setting("ui_theme","PraxisPro Blau"))
        fontsize=QSpinBox(); fontsize.setRange(10,18); fontsize.setValue(int(get_setting("ui_font_size","13"))); fontsize.setSuffix(" px")
        density=QComboBox(); density.addItems(["Kompakt","Normal","Groß"]); density.setCurrentText(get_setting("ui_density","Kompakt"))
        af.addRow("Farbschema",theme); af.addRow("Schriftgröße",fontsize); af.addRow("Darstellung",density); gv.addWidget(appearance)
        save=QPushButton("Praxiseinstellungen speichern"); save.setMinimumHeight(54)
        def save_settings():
            for k,ed in fields.items(): set_setting(k,ed.text().strip())
            set_setting("auto_lock_minutes",lock.value()); set_setting("travel_surcharge",travel.value()); set_setting("ui_theme",theme.currentText()); set_setting("ui_font_size",fontsize.value()); set_setting("ui_density",density.currentText())
            QMessageBox.information(self,"Gespeichert","Die Praxisvorlage wurde gespeichert. Deine bisherigen Daten bleiben die Standardvorlage.")
        save.clicked.connect(save_settings); gv.addSpacing(8); gv.addWidget(save); gv.addStretch(); tabs.addTab(general,"Praxisdaten")
        billing=QWidget(); bv=QVBoxLayout(billing); bv.setContentsMargins(20,22,20,28); bv.setSpacing(18)
        bf=QFormLayout(); bf.setHorizontalSpacing(28); bf.setVerticalSpacing(14)
        for key,label in [("tax_number","Steuernummer"),("iban","IBAN"),("bic","BIC"),("paypal","PayPal")]:
            ed=QLineEdit(get_setting(key)); ed.setMinimumHeight(42); fields[key]=ed; bf.addRow(label,ed)
        lockrow=QHBoxLayout(); lock=QSpinBox(); lock.setRange(1,120); lock.setValue(int(get_setting("auto_lock_minutes","15"))); lock.setSuffix(" Minuten"); lockrow.addWidget(lock); lockrow.addStretch(); bf.addRow("Automatische Sperre",lockrow)
        travel=QDoubleSpinBox(); travel.setRange(0,500); travel.setDecimals(2); travel.setValue(float(get_setting("travel_surcharge","25"))); travel.setSuffix(" €"); bf.addRow("Hausbesuch Anfahrt",travel)
        bv.addLayout(bf); save2=QPushButton("Abrechnung & Sicherheit speichern"); save2.setMinimumHeight(48); save2.clicked.connect(save_settings); bv.addWidget(save2); bv.addStretch(); tabs.addTab(billing,"Abrechnung & Bank")
        ratespage=QWidget(); rv=QVBoxLayout(ratespage); rv.setContentsMargins(16,16,16,16); rv.setSpacing(10)
        rates=QLabel("Honorarsätze"); rates.setObjectName("sectionTitle"); rv.addWidget(rates)
        rt=QTableWidget(0,5); rt.setHorizontalHeaderLabels(["Leistung","Einheit Min.","Regulär €","Ermäßigt €","Abrechnung"]); rt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for name,mins,amount,reduced,mode in get_fee_rates():
            r=rt.rowCount(); rt.insertRow(r)
            for j,val in enumerate([name,mins,amount,reduced if reduced is not None else "",mode]): rt.setItem(r,j,QTableWidgetItem(str(val)))
        rv.addWidget(rt,1)
        ratebuttons=QHBoxLayout(); saverates=QPushButton("Honorarsätze speichern"); addrate=QPushButton("Neue Leistung")
        def save_rates():
            con=sqlite3.connect(DBFILE)
            for r in range(rt.rowCount()):
                name=(rt.item(r,0).text() if rt.item(r,0) else "").strip()
                if not name: continue
                try: mins=int(rt.item(r,1).text()); amount=float(rt.item(r,2).text().replace(",", ".")); reduced=float(rt.item(r,3).text().replace(",", ".")) if rt.item(r,3) and rt.item(r,3).text().strip() else None; mode=(rt.item(r,4).text().strip() if rt.item(r,4) else "proportional") or "proportional"
                except: QMessageBox.warning(self,"Honorare",f"Bitte Werte in Zeile {r+1} prüfen."); con.close(); return
                con.execute("INSERT INTO fee_rates(name,minutes,amount,reduced_amount,billing_mode,active) VALUES(?,?,?,?,?,1) ON CONFLICT(name) DO UPDATE SET minutes=excluded.minutes,amount=excluded.amount,reduced_amount=excluded.reduced_amount,active=1",(name,mins,amount,reduced,mode))
            con.commit(); con.close(); QMessageBox.information(self,"Honorare","Honorarsätze gespeichert.")
        def add_rate():
            r=rt.rowCount(); rt.insertRow(r)
            for j,val in enumerate(["Neue Leistung","45","70","60","proportional"]):rt.setItem(r,j,QTableWidgetItem(val))
            rt.setCurrentCell(r,0); rt.editItem(rt.item(r,0))
        saverates.clicked.connect(save_rates); addrate.clicked.connect(add_rate); ratebuttons.addWidget(saverates); ratebuttons.addWidget(addrate); ratebuttons.addStretch(); rv.addLayout(ratebuttons)
        hint=QLabel("Honorarsätze können hier bearbeitet und um eigene Leistungen erweitert werden."); hint.setWordWrap(True); hint.setObjectName("pageSub"); rv.addWidget(hint); tabs.addTab(ratespage,"Honorare")
        userspage=QWidget(); uv=QVBoxLayout(userspage); uv.setContentsMargins(16,16,16,16); uv.setSpacing(10)
        users=QLabel("Benutzer / Therapeuten"); users.setObjectName("sectionTitle"); uv.addWidget(users)
        ub=QPushButton("Benutzer anlegen")
        def add_user():
            name,ok=QInputDialog.getText(self,"Benutzer","Benutzername:")
            if not ok or not name.strip():return
            display,ok=QInputDialog.getText(self,"Benutzer","Anzeigename:")
            if not ok or not display.strip():return
            pwd,ok=QInputDialog.getText(self,"Benutzer","Passwort:",QLineEdit.Password)
            if not ok or len(pwd)<8:return QMessageBox.warning(self,"Passwort","Bitte mindestens 8 Zeichen verwenden.")
            rq,ok=QInputDialog.getText(self,"Benutzer","Sicherheitsfrage:")
            if not ok or not rq.strip():return
            ra,ok=QInputDialog.getText(self,"Benutzer","Antwort auf die Sicherheitsfrage:")
            if not ok or not ra.strip():return
            try:
                con=sqlite3.connect(DBFILE); con.execute("INSERT INTO users(username,display_name,role,active,password_hash,created_at,recovery_question,recovery_answer_hash) VALUES(?,?,?,?,?,?,?,?)",(name.strip(),display.strip(),"Therapeut",1,password_hash(pwd),datetime.now().isoformat(timespec="seconds"),rq.strip(),password_hash(normalize_recovery_answer(ra)))); con.commit(); con.close(); audit("USER_CREATED",display.strip()); QMessageBox.information(self,"Benutzer","Benutzer wurde angelegt.")
            except sqlite3.IntegrityError: QMessageBox.warning(self,"Benutzer","Dieser Benutzername existiert bereits.")
        ub.clicked.connect(add_user); uv.addWidget(ub)
        ut=QTableWidget(0,4); ut.setHorizontalHeaderLabels(["Benutzername","Anzeigename","Rolle","Aktiv"]); ut.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        def refresh_users():
            ut.setRowCount(0); con=sqlite3.connect(DBFILE); rows=con.execute("SELECT username,display_name,role,active FROM users ORDER BY display_name").fetchall(); con.close()
            for row in rows:
                r=ut.rowCount(); ut.insertRow(r)
                for j,val in enumerate([row[0],row[1],row[2],"Ja" if row[3] else "Nein"]): ut.setItem(r,j,QTableWidgetItem(str(val)))
        def toggle_user():
            r=ut.currentRow()
            if r<0:return
            username=ut.item(r,0).text()
            if self.current_user and username==self.current_user.get("username"): return QMessageBox.warning(self,"Benutzer","Der aktuell angemeldete Benutzer kann nicht deaktiviert werden.")
            con=sqlite3.connect(DBFILE); row=con.execute("SELECT active FROM users WHERE username=?",(username,)).fetchone()
            if row: con.execute("UPDATE users SET active=? WHERE username=?",(0 if row[0] else 1,username)); con.commit()
            con.close(); audit("USER_STATUS","Benutzerstatus geändert: "+username,self.current_user.get("username","") if self.current_user else ""); refresh_users()
        def change_role():
            r=ut.currentRow()
            if r<0:return
            username=ut.item(r,0).text(); role,ok=QInputDialog.getItem(self,"Rolle ändern","Rolle:",["Administrator","Therapeut","Lesen"],0,False)
            if not ok:return
            con=sqlite3.connect(DBFILE); con.execute("UPDATE users SET role=? WHERE username=?",(role,username)); con.commit(); con.close(); audit("USER_ROLE","Rolle geändert: "+username+" -> "+role,self.current_user.get("username","") if self.current_user else ""); refresh_users()
        def recovery_for_user():
            r=ut.currentRow()
            if r<0:return
            username=ut.item(r,0).text()
            rq,ok=QInputDialog.getText(self,"Sicherheitsfrage","Neue Sicherheitsfrage für "+username+":")
            if not ok or not rq.strip():return
            ra,ok=QInputDialog.getText(self,"Sicherheitsfrage","Antwort:")
            if not ok or not ra.strip():return
            con=sqlite3.connect(DBFILE); con.execute("UPDATE users SET recovery_question=?,recovery_answer_hash=?,failed_attempts=0,locked_until=NULL WHERE username=?",(rq.strip(),password_hash(normalize_recovery_answer(ra)),username)); con.commit(); con.close()
            audit("RECOVERY_UPDATED","Sicherheitsfrage aktualisiert: "+username,self.current_user.get("username","") if self.current_user else ""); QMessageBox.information(self,"Sicherheitsfrage","Sicherheitsfrage wurde aktualisiert.")
        def admin_password_reset():
            r=ut.currentRow()
            if r<0:return
            username=ut.item(r,0).text(); pwd,ok=QInputDialog.getText(self,"Passwort setzen","Neues Passwort für "+username+":",QLineEdit.Password)
            if not ok:return
            if len(pwd)<8:return QMessageBox.warning(self,"Passwort","Bitte mindestens 8 Zeichen verwenden.")
            con=sqlite3.connect(DBFILE); con.execute("UPDATE users SET password_hash=?,failed_attempts=0,locked_until=NULL WHERE username=?",(password_hash(pwd),username)); con.commit(); con.close()
            audit("ADMIN_PASSWORD_RESET","Passwort administrativ zurückgesetzt: "+username,self.current_user.get("username","") if self.current_user else ""); QMessageBox.information(self,"Passwort","Neues Passwort wurde gespeichert.")
        ur=QHBoxLayout(); toggle=QPushButton("Aktivieren / Deaktivieren"); rolebtn=QPushButton("Rolle ändern"); recoverybtn=QPushButton("Sicherheitsfrage setzen"); resetbtn=QPushButton("Passwort setzen")
        toggle.clicked.connect(toggle_user); rolebtn.clicked.connect(change_role); recoverybtn.clicked.connect(recovery_for_user); resetbtn.clicked.connect(admin_password_reset)
        for b in (toggle,rolebtn,recoverybtn,resetbtn): ur.addWidget(b)
        ur.addStretch()
        uv.addWidget(ut,1); uv.addLayout(ur); refresh_users(); tabs.addTab(userspage,"Benutzer & Sicherheit")
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
        today=date.today(); overdue=[]
        for inv in DB["invoices"]:
            if inv.get("status","offen")!="offen": continue
            try:
                invdate=datetime.strptime(inv.get("date",""),"%Y-%m-%d").date()
                days=(today-invdate).days
                if days>14: overdue.append((days,inv))
            except Exception: pass
        if overdue:
            overdue.sort(key=lambda z:z[0],reverse=True)
            alert=QFrame(); alert.setObjectName("formCard"); av=QVBoxLayout(alert); ah=QHBoxLayout()
            al=QLabel(f"⚠ {len(overdue)} überfällige Rechnung(en)"); al.setObjectName("sectionTitle"); ah.addWidget(al); ah.addStretch()
            showoverdue=QPushButton("Überfällige Rechnungen anzeigen"); showoverdue.setMinimumHeight(40)
            def go_overdue():
                self.nav.setCurrentRow(6)
            showoverdue.clicked.connect(go_overdue); ah.addWidget(showoverdue); av.addLayout(ah)
            preview=[]
            for days,inv in overdue[:3]:
                preview.append(f'{inv.get("number","")} · {inv.get("client","")} · {float(inv.get("amount",0) or 0):.2f} € · {days} Tage')
            ap=QLabel("\n".join(preview)); ap.setObjectName("pageSub"); ap.setWordWrap(True); av.addWidget(ap); v.addWidget(alert)
        quick=QLabel("Schnellzugriff"); quick.setObjectName("sectionTitle"); v.addWidget(quick)
        actions=QHBoxLayout(); new_session=QPushButton("＋  Neue Sitzung"); new_session.setMinimumHeight(52); new_session.clicked.connect(lambda:self.nav.setCurrentRow(1)); new_invoice=QPushButton("▤  Neue Rechnung"); new_invoice.setMinimumHeight(52); new_invoice.clicked.connect(lambda:self.nav.setCurrentRow(5)); clients=QPushButton("♙  Klienten verwalten"); clients.setMinimumHeight(52); clients.clicked.connect(lambda:self.nav.setCurrentRow(3)); actions.addWidget(new_session);actions.addWidget(new_invoice);actions.addWidget(clients);v.addLayout(actions)
        info=QLabel(f"Datenbank: {DBFILE}\nDatenordner: {ROOT}"); info.setObjectName("infoBox"); info.setWordWrap(True); v.addWidget(info); v.addStretch(); return w
if __name__ == "__main__":
    app=QApplication(sys.argv); app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}")
    if not ensure_first_user(): sys.exit(0)
    login=LoginDialog()
    if login.exec()!=QDialog.Accepted: sys.exit(0)
    win=Main(); win.current_user=login.user; win.setWindowTitle(f"PraxisPro v{APP_VERSION} – "+login.user.get("display_name","")); win.show(); sys.exit(app.exec())
