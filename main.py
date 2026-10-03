import sys
import subprocess, json, os, re, math, shutil, sqlite3, base64, hashlib, tempfile, time
from pathlib import Path
from datetime import datetime, date
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl, QEvent
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog,QSplitter,QListWidget,QListWidgetItem,QStackedWidget,QFrame,QGridLayout,QInputDialog,QScrollArea,QSlider,QSizePolicy,QCalendarWidget,QCompleter)
from PySide6.QtCore import QDate,QTime
from PySide6.QtGui import QKeySequence, QShortcut, QTextCharFormat, QImage, QPainter, QPen, QPixmap, QDesktopServices, QFont, QColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from cryptography.fernet import Fernet, InvalidToken

APP_VERSION="0.12.18"
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
    def paintEvent(self,e):
        p=QPainter(self); p.drawImage(self.rect(),self.image)
        # Live-Uhr direkt auf der Handschriftfläche; wird nicht in die gespeicherte Notiz eingebrannt.
        stamp=QTime.currentTime().toString("HH:mm:ss")
        p.setPen(QColor("#17324d")); font=QFont(); font.setPointSize(14); font.setBold(True); p.setFont(font)
        p.drawText(self.rect().adjusted(0,10,-14,0),Qt.AlignTop|Qt.AlignRight,stamp)
        p.end()
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
    """Findet Assets in Entwicklung sowie in PyInstaller onefile/onedir.

    WICHTIG: Gibt bei Nichtfund jetzt None zurück, nicht mehr den ersten
    (nicht existierenden) Kandidaten. Dadurch können Aufrufer sauber
    zwischen 'gefunden' und 'nicht gefunden' unterscheiden.
    """
    candidates = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        # PyInstaller onefile: entpackter Temp-Ordner
        candidates.append(Path(meipass) / "assets" / name)

    if getattr(sys, "frozen", False):
        # PyInstaller onefile UND onedir: Verzeichnis der EXE
        candidates.append(
            Path(sys.executable).resolve().parent / "assets" / name
        )

    # Entwicklungsmodus: Verzeichnis dieser .py-Datei
    candidates.append(
        Path(__file__).resolve().parent / "assets" / name
    )

    for path in candidates:
        if path.is_file():
            return path

    # NEU: ehrlich None zurückgeben, statt Phantom-Pfad.
    # Aufrufer muss jetzt explizit auf None prüfen.
    return None

def bundled_template(name):
    """Return a template shipped both from source and from the PyInstaller setup."""
    base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))
    return base/"templates"/name

def render_invoice_html(values):
    """Render the packaged UTF-8 invoice template without changing invoice data."""
    from html import escape
    template=bundled_template("invoice.html").read_text(encoding="utf-8")
    for key,value in values.items():
        template=template.replace("{{"+str(key)+"}}",str(value))
    return template

def render_invoice_pdf(html, out_path):
    """HTML -> A4-PDF über QWebEngineView. Wartet loadFinished UND pdfPrintingFinished ab."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtCore import QEventLoop, QMarginsF, QUrl, QTimer
        from PySide6.QtGui import QPageLayout, QPageSize
    except Exception as e:
        audit("INVOICE_HTML_NO_WEBENGINE", str(e)[:200])
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    view = QWebEngineView()
    state = {"loaded": False, "printed": False, "ok": False}
    layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))

    loop1 = QEventLoop()
    def on_loaded(ok):
        state["loaded"] = bool(ok)
        loop1.quit()
    view.loadFinished.connect(on_loaded)
    t1 = QTimer(); t1.setSingleShot(True); t1.timeout.connect(loop1.quit); t1.start(8000)
    view.setHtml(html, QUrl("about:blank"))
    loop1.exec(); t1.stop()
    if not state["loaded"]:
        audit("INVOICE_HTML_LOAD_TIMEOUT", str(out_path))
        view.deleteLater()
        return False

    loop2 = QEventLoop()
    def on_printed(path, ok):
        state["printed"] = True
        state["ok"] = bool(ok)
        loop2.quit()
    view.pdfPrintingFinished.connect(on_printed)
    t2 = QTimer(); t2.setSingleShot(True); t2.timeout.connect(loop2.quit); t2.start(8000)
    view.printToPdf(str(out_path), layout)
    loop2.exec(); t2.stop()
    if not state["printed"]:
        audit("INVOICE_HTML_PRINT_TIMEOUT", str(out_path))
        view.deleteLater()
        return False
    view.deleteLater()
    if not state["ok"]:
        audit("INVOICE_HTML_PRINT_FAILED", str(out_path))
        return False
    if not out_path.is_file() or out_path.stat().st_size <= 1000:
        audit("INVOICE_HTML_PDF_INVALID", str(out_path))
        audit("INVOICE_PDF_RESULT", f"ok=False path={out_path} size={out_path.stat().st_size if out_path.is_file() else 0}")
        return False
    audit("INVOICE_PDF_RESULT", f"ok=True path={out_path} size={out_path.stat().st_size}")
    return True

def _sepa_qr_data_uri(owner, iban, bic, amount, invoice_no):
    """Erzeugt den EPC-SEPA-QR als Base64-PNG Data-URI."""
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPM
        epc = "\n".join([
            "BCD", "002", "1", "SCT", bic.strip(), owner.strip(),
            iban.replace(" ", "").strip(), "EUR" + f"{float(amount):.2f}",
            "", "", invoice_no.strip()
        ])
        q = QrCodeWidget(epc)
        x1, y1, x2, y2 = q.getBounds()
        size = 120
        d = Drawing(size, size, transform=[size/(x2-x1), 0, 0, size/(y2-y1), 0, 0])
        d.add(q)
        png = renderPM.drawToString(d, fmt="PNG", bg=0xFFFFFF)
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    except Exception as e:
        audit("INVOICE_SEPA_QR_ERROR", str(e)[:200])
        return ""

def effective_practice_logo():
    """Benutzerlogo wenn brauchbar, sonst immer das mitgelieferte Standardlogo."""
    from reportlab.lib.utils import ImageReader

    def usable(path):
        try:
            p = Path(path)
            if not p.is_file():
                return None
            probe = ImageReader(str(p))
            probe.getSize()
            probe.getRGBData()
            return p
        except Exception as e:
            audit("INVOICE_LOGO_INVALID", f"{path} :: {str(e)[:200]}")
            return None

    custom = (get_setting("logo_path", "") or "").strip()
    if custom:
        cp = Path(custom)
        custom_candidates = [cp]
        if not cp.is_absolute():
            custom_candidates += [
                ROOT / cp,
                Path(__file__).resolve().parent / cp,
            ]
        for candidate in custom_candidates:
            ok = usable(candidate)
            if ok is not None:
                audit("INVOICE_LOGO_SOURCE", f"custom:{ok}")
                return ok

    # PyInstaller 6 onedir uses _MEIPASS == <app>/_internal. bundled_asset()
    # therefore remains the primary resolver. Explicit fallbacks make the
    # standard-logo contract robust across onefile/onedir/development.
    candidates = []
    bundled = bundled_asset("logo.png")
    if bundled is not None:
        candidates.append(bundled)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates += [
            exe_dir / "_internal" / "assets" / "logo.png",
            exe_dir / "assets" / "logo.png",
        ]
    candidates.append(Path(__file__).resolve().parent / "assets" / "logo.png")

    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ok = usable(candidate)
        if ok is not None:
            audit("INVOICE_LOGO_SOURCE", f"bundled:{ok}")
            return ok

    audit("INVOICE_LOGO_SOURCE", "missing:no_logo_found")
    return None

# Kompatibilitaet fuer bestehende UI-/Rechnungsaufrufe.
def practice_logo_path():
    return effective_practice_logo()

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
    CREATE TABLE IF NOT EXISTS appointments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, appointment_date TEXT NOT NULL, start_time TEXT NOT NULL,
      minutes INTEGER DEFAULT 45, client_id INTEGER, couple_id INTEGER, appointment_type TEXT,
      status TEXT DEFAULT 'geplant', note TEXT, created_at TEXT NOT NULL, username TEXT,
      FOREIGN KEY(client_id) REFERENCES clients(id));
    CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date,start_time);
    CREATE TABLE IF NOT EXISTS couples(
      id INTEGER PRIMARY KEY AUTOINCREMENT, partner_a_client_id INTEGER, partner_b_client_id INTEGER,
      partner_a_name TEXT, partner_b_name TEXT, status TEXT DEFAULT 'aktiv', created_at TEXT NOT NULL,
      FOREIGN KEY(partner_a_client_id) REFERENCES clients(id),
      FOREIGN KEY(partner_b_client_id) REFERENCES clients(id));
    CREATE TABLE IF NOT EXISTS couple_sessions(\n      id INTEGER PRIMARY KEY AUTOINCREMENT, couple_id INTEGER NOT NULL, session_date TEXT NOT NULL,\n      topic TEXT, shared_note TEXT, minutes INTEGER DEFAULT 45, username TEXT, created_at TEXT NOT NULL,\n      FOREIGN KEY(couple_id) REFERENCES couples(id));\n    CREATE TABLE IF NOT EXISTS couple_notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, couple_id INTEGER NOT NULL, created_at TEXT NOT NULL,
      note_type TEXT NOT NULL, note_text TEXT, username TEXT,
      FOREIGN KEY(couple_id) REFERENCES couples(id));
    CREATE TABLE IF NOT EXISTS couple_assessments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, client_label TEXT,
      partner_a TEXT, partner_b TEXT, topic TEXT, perspective_a TEXT, perspective_b TEXT,
      interaction_cycle TEXT, shared_goal TEXT, resources TEXT, children_involved INTEGER DEFAULT 0,
      safety_flag INTEGER DEFAULT 0, answers_a TEXT, answers_b TEXT, username TEXT,
      couple_id INTEGER, FOREIGN KEY(couple_id) REFERENCES couples(id));
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
    cacols=[r[1] for r in con.execute("PRAGMA table_info(couple_assessments)").fetchall()]
    if "couple_id" not in cacols: con.execute("ALTER TABLE couple_assessments ADD COLUMN couple_id INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS idx_couple_assessments_couple_id ON couple_assessments(couple_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_couples_partner_a ON couples(partner_a_client_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_couples_partner_b ON couples(partner_b_client_id)")
    defaults={
      "practice_name":"Psychologische Privatpraxis","owner_name":"Erdoğan Kulanoğlu",
      "qualifications":"Psychologe M.Sc. | Sozialarbeiter B.A.",
      "practice_subtitle":"Ehe-, Familien- und Lebensberatung | Zertifizierter Systemischer Berater und Therapeut nach dem SIT-Modell",
      "address":"Schönwalder Str. 59, 13585 Berlin","phone":"0176 43605753","landline":"030 12127420","fax":"030 43205928",
      "email":"info@psychologe-spandau.de","website":"www.psychologe-spandau.de","tax_number":"19/405/00254",
      "iban":"DE13 5001 0517 5404 0811 30","bic":"INGDDEFFXXX","paypal":"erdogankulanoglu@hotmail.com",
      "manufacturer":"Erdoğan Kulanoğlu","copyright":"© 2026 Erdoğan Kulanoğlu. Alle Rechte vorbehalten.","logo_path":"","invoice_header_logo_zone":"Links","invoice_header_middle":"Praxisdaten","invoice_header_right":"Kontaktdaten","logo_x_mm":"18","logo_y_mm":"7","logo_width_mm":"72","logo_height_mm":"22","auto_lock_minutes":"15","travel_surcharge":"25"
    }
    for k,v in defaults.items(): con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    # Schon installierte Standardwerte behutsam auf den freigegebenen Rechnungsstand migrieren.
    con.execute("UPDATE settings SET value=? WHERE key=? AND (value IS NULL OR value='')",("030 12127420","landline"))
    con.execute("UPDATE settings SET value=? WHERE key=? AND value=?",("7","logo_y_mm","10"))
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
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(195); sv=QVBoxLayout(sidebar); sv.setContentsMargins(12,14,12,14)
        brand=QLabel("PRAXISPRO  v"+APP_VERSION+"\n"+get_setting("practice_name","Psychologische Privatpraxis")); brand.setObjectName("brand"); brand.setWordWrap(True); sv.addWidget(brand)
        self.nav=QListWidget(); self.nav.setObjectName("nav")
        for x in ["⌂  Dashboard","＋  Sitzung","✦  Sitzungsassistent","♙  Klienten","♙＋ Neuer Klient","♥  Paarakte","▦  Terminkalender","▤  Neue Rechnung","▣  Rechnungen","⚙  Praxiseinstellungen","?  Hilfe · FAQ · Info"]: self.nav.addItem(x)
        sv.addWidget(self.nav,1)
        foot=QLabel(get_setting("copyright","© 2026 Erdoğan Kulanoğlu")); foot.setObjectName("sidefoot"); sv.addWidget(foot)
        content=QWidget(); contentv=QVBoxLayout(content); contentv.setContentsMargins(0,0,0,0); contentv.setSpacing(0)
        topbar=QFrame(); topbar.setObjectName("topBrandBar"); topbar.setFixedHeight(62); tb=QHBoxLayout(topbar); tb.setContentsMargins(16,5,18,5); tb.addStretch()
        self.top_logo=QLabel(); self.top_logo.setAlignment(Qt.AlignRight|Qt.AlignVCenter); self.top_logo.setMinimumWidth(220)
        logo_path=practice_logo_path()
        if logo_path:
            px=QPixmap(str(logo_path))
            if not px.isNull(): self.top_logo.setPixmap(px.scaled(220,46,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        lockbtn=QPushButton("🔒 Bildschirm sperren"); lockbtn.setMinimumHeight(34); lockbtn.setToolTip("PraxisPro sofort sperren (Strg+L)"); lockbtn.clicked.connect(self.lock_screen); tb.insertWidget(0,lockbtn)
        tb.addWidget(self.top_logo); contentv.addWidget(topbar)
        self.pages=QStackedWidget(); self.pages.addWidget(self.dashboard_ui()); self.pages.addWidget(self.session_ui()); self.pages.addWidget(self.helper_ui()); self.pages.addWidget(self.clients_ui()); self.pages.addWidget(self.new_client_page()); self.pages.addWidget(self.couples_ui()); self.pages.addWidget(self.calendar_ui()); self.pages.addWidget(self.invoice_ui()); self.pages.addWidget(self.invoices_ui()); self.pages.addWidget(self.settings_ui()); self.pages.addWidget(self.manual_ui()); contentv.addWidget(self.pages,1)
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
        #nav { background:transparent; border:0; outline:0; color:#dce7ef; font-size:12px; }
        #nav::item { padding:6px 8px; margin:1px 0; border-radius:8px; min-height:21px; }
        #nav::item:selected { background:#2f7de1; color:white; font-weight:700; }
        #nav::item:hover:!selected { background:#244d70; color:white; }
        QStackedWidget { background:#f4f6f8; }\n        #topBrandBar { background:white; border-bottom:1px solid #dce3e9; }
        #pageTitle { font-size:23px; font-weight:800; color:#17324d; }
        #pageSub { font-size:12px; color:#607080; padding-bottom:8px; }
        #statCard { background:white; border:1px solid #dce3e9; border-radius:14px; min-height:115px; }
        #cardCaption { color:#6b7b88; font-size:12px; font-weight:700; }
        #cardValue { color:#17324d; font-size:27px; font-weight:800; }
        #infoBox { background:white; border:1px solid #dce3e9; border-radius:10px; padding:14px; color:#607080; }
        #clientHeader { background:white; border:1px solid #dce3e9; border-radius:14px; padding:12px; }
        #clientName { color:#17324d; font-size:24px; font-weight:800; }
        #clientBadge { background:#e8f0f6; color:#17324d; border-radius:10px; padding:8px 14px; font-weight:700; }
        #sectionTitle { color:#17324d; font-size:13px; font-weight:800; padding-top:2px; }
        #formCard { background:white; border:1px solid #d4e0ea; border-radius:9px; padding:6px; }
        #sessionScroll { background:#f4f6f8; border:0; }
        #sessionScroll > QWidget > QWidget { background:#f4f6f8; }
        QScrollBar:vertical { background:#eef2f5; width:12px; margin:2px; border-radius:6px; }
        QScrollBar::handle:vertical { background:#9fb0bf; min-height:38px; border-radius:6px; }
        QScrollBar:horizontal { background:#eef2f5; height:12px; margin:2px; border-radius:6px; }
        QScrollBar::handle:horizontal { background:#9fb0bf; min-width:38px; border-radius:6px; }
        QTabWidget::pane { border:0; background:white; border-radius:12px; }
        QTabBar::tab { background:#e9eef3; padding:12px 20px; margin:2px; border-radius:8px; font-size:14px; }
        QTabBar::tab:selected { background:#17324d; color:white; font-weight:700; }
        QLabel { color:#1f2933; font-size:11px; }
        QLineEdit,QTextEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox {
            background:white; border:2px solid #b8c7d4; border-radius:9px; padding:4px 7px; min-height:18px; font-size:11px;
            selection-background-color:#17324d;
        }
        QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus,QTimeEdit:focus,QSpinBox:focus {
            border:2px solid #356b92;
        }
        QPushButton { background:#1f6fb2; color:white; border:0; border-radius:9px; padding:6px 10px; font-size:11px; font-weight:600; }
        QPushButton:hover { background:#244d70; }
        QPushButton:disabled { background:#c8d2dc; color:#71808c; }
        QPushButton:pressed { background:#10283d; }
        QCheckBox { spacing:5px; font-size:11px; min-height:20px; }
        QLineEdit[readOnly="true"] { background:#f4f7f9; color:#607080; }
        QTableWidget { background:white; alternate-background-color:#f6f8fa; border:1px solid #d8e0e7; border-radius:8px; gridline-color:#e6ebef; font-size:12px; }
        QHeaderView::section { background:#edf2f6; color:#243746; padding:6px; border:0; border-bottom:1px solid #ccd6df; font-weight:700; }
        QSplitter::handle { background:#d5dde5; height:7px; margin:3px 0; border-radius:3px; }
        QStatusBar { background:#17324d; color:white; }
        QStatusBar QLabel { color:white; font-weight:700; padding:4px 10px; }
        """)
        self.apply_appearance()
        QShortcut(QKeySequence("Ctrl+L"),self,activated=self.lock_screen)
        self.autosave=QTimer(self); self.autosave.timeout.connect(self.autosave_session); self.autosave.start(15000)
        QTimer.singleShot(500,self.restore_draft)
    def apply_appearance(self):
        theme=get_setting("ui_theme","PraxisPro Blau")
        font_size=max(9,min(16,int(get_setting("ui_font_size","12") or 12)))
        density=get_setting("ui_density","Kompakt")
        palettes={
            "PraxisPro Blau":("#132f47","#1f6fb2","#2f7de1","#17324d","#f4f6f8"),
            "Petrol":("#123c3d","#177b7d","#22999b","#174b4d","#f2f7f7"),
            "Grün":("#183d2b","#2e7d4f","#3f9b65","#205b39","#f3f7f4"),
            "Gold":("#493b18","#9a7417","#c59a2c","#6f5314","#faf8f2"),
            "Violett":("#34234d","#7048a3","#8b5fc1","#513373","#f7f4fa")}
        side,button,selected,dark,bg=palettes.get(theme,palettes["PraxisPro Blau"])
        if density=="Groß": pad,minh,navpad=8,26,9
        elif density=="Normal": pad,minh,navpad=6,22,7
        else: pad,minh,navpad=4,18,5
        self.setStyleSheet(f"""
        QMainWindow {{ background:{bg}; }}
        #sidebar {{ background:{side}; border:0; }}
        #brand {{ color:white; font-size:{font_size+5}px; font-weight:800; padding:5px 8px 12px 8px; }}
        #sidefoot {{ color:#d5dde5; font-size:{max(9,font_size-1)}px; padding:10px; }}
        #nav {{ background:transparent; border:0; outline:0; color:#e5edf3; font-size:{font_size}px; }}
        #nav::item {{ padding:{navpad}px 8px; margin:1px 0; border-radius:8px; min-height:{minh}px; }}
        #nav::item:selected {{ background:{selected}; color:white; font-weight:700; }}
        #nav::item:hover:!selected {{ background:{dark}; color:white; }}
        QStackedWidget,#sessionScroll,#sessionScroll > QWidget > QWidget {{ background:{bg}; }}
        #topBrandBar {{ background:white; border-bottom:1px solid #dce3e9; }}
        #pageTitle {{ font-size:{font_size+11}px; font-weight:800; color:{dark}; }}
        #pageSub {{ font-size:{font_size}px; color:#607080; padding-bottom:8px; }}
        #statCard,#formCard,#clientHeader {{ background:white; border:1px solid #d4e0ea; border-radius:10px; padding:{pad+2}px; }}
        #sectionTitle {{ color:{dark}; font-size:{font_size+2}px; font-weight:800; }}
        QLabel,QCheckBox {{ color:#1f2933; font-size:{font_size}px; }}
        QLineEdit,QTextEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox {{
          background:white; border:2px solid #b8c7d4; border-radius:9px; padding:{pad}px 7px; min-height:{minh}px; font-size:{font_size}px; selection-background-color:{dark};
        }}
        QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus,QTimeEdit:focus,QSpinBox:focus {{ border:2px solid {selected}; }}
        QPushButton {{ background:{button}; color:white; border:0; border-radius:9px; padding:{pad+2}px 10px; font-size:{font_size}px; font-weight:600; }}
        QPushButton:hover {{ background:{dark}; }} QPushButton:pressed {{ background:{side}; }}
        QTabBar::tab {{ background:#e9eef3; padding:{pad+6}px 18px; margin:2px; border-radius:8px; font-size:{font_size+1}px; }}
        QTabBar::tab:selected {{ background:{dark}; color:white; font-weight:700; }}
        QTableWidget {{ background:white; alternate-background-color:#f6f8fa; border:1px solid #d8e0e7; border-radius:8px; gridline-color:#e6ebef; font-size:{font_size}px; }}
        QHeaderView::section {{ background:#edf2f6; color:#243746; padding:{pad+2}px; border:0; border-bottom:1px solid #ccd6df; font-weight:700; }}
        QStatusBar {{ background:{dark}; color:white; }} QStatusBar QLabel {{ color:white; font-weight:700; padding:4px 10px; }}
        """)
        QApplication.instance().setFont(QFont(QApplication.instance().font().family(),font_size))

    def update_user_badge(self):
        u=self.current_user or {}; self.userbadge.setText("Angemeldet: "+u.get("display_name",u.get("username",""))+" · "+u.get("role",""))
    def update_wallclock(self):
        now=QTime.currentTime(); self.wallclock.setText("● LIVE  "+now.toString("HH:mm:ss"))
        if getattr(self,"session_live_clock",None) is not None:
            try: self.session_live_clock.setText(now.toString("HH:mm:ss"))
            except RuntimeError: pass
    def event(self,e):
        if e.type() in (QEvent.MouseButtonPress,QEvent.MouseButtonDblClick,QEvent.KeyPress,QEvent.TouchBegin,QEvent.Wheel):
            self.last_activity=datetime.now()
        return super().event(e)
    def lock_screen(self):
        """PraxisPro sofort verdecken und erst nach erneuter Anmeldung freigeben."""
        if getattr(self,"_screen_locked",False): return
        self._screen_locked=True
        self.locktimer.stop()
        audit("LOCK","Bildschirm manuell gesperrt",(self.current_user or {}).get("username",""))
        # Patientendaten während der Sperre vollständig ausblenden.
        central=self.centralWidget()
        old_title=self.windowTitle()
        if central: central.setVisible(False)
        self.setWindowTitle("PraxisPro – Bildschirm gesperrt")
        dlg=LoginDialog(); dlg.setWindowTitle("PraxisPro – Bildschirm gesperrt"); dlg.setModal(True)
        if dlg.exec()!=QDialog.Accepted:
            QApplication.quit(); return
        # Sperre ist kein Benutzerwechsel: standardmäßig denselben Benutzer verlangen.
        locked_user=(self.current_user or {}).get("username","")
        if locked_user and (dlg.user or {}).get("username","")!=locked_user:
            if central: central.setVisible(True)
            self.setWindowTitle(old_title)
            self._screen_locked=False; self.locktimer.start(30000)
            return QMessageBox.warning(self,"Bildschirm gesperrt","Bitte mit demselben Benutzer entsperren. Für einen Benutzerwechsel PraxisPro regulär neu anmelden.")
        self.current_user=dlg.user
        if central: central.setVisible(True)
        self.setWindowTitle(old_title)
        self.update_user_badge(); self.last_activity=datetime.now(); self._screen_locked=False; self.locktimer.start(30000)
        audit("UNLOCK","Bildschirm entsperrt",self.current_user.get("username",""))

    def check_autolock(self):
        mins=int(get_setting("auto_lock_minutes","15") or 15)
        if mins>0 and (datetime.now()-self.last_activity).total_seconds()>=mins*60:
            self.lock_screen()

    def role(self):
        return (self.current_user or {}).get("role","Therapeut")
    def can_edit(self): return self.role() in ("Administrator","Therapeut")
    def is_admin(self): return self.role()=="Administrator"
    def navigate(self,index):
        # Einstellungen mit Benutzer-/Sicherheitsverwaltung nur für Administratoren.
        if index==9 and not self.is_admin():
            QMessageBox.warning(self,"Keine Berechtigung","Praxiseinstellungen und Benutzerverwaltung sind Administratoren vorbehalten.")
            self.nav.blockSignals(True); self.nav.setCurrentRow(self.pages.currentIndex()); self.nav.blockSignals(False); return
        self.pages.setCurrentIndex(index)
    def require_edit(self):
        if self.can_edit(): return True
        QMessageBox.warning(self,"Nur Lesen","Dieser Benutzer hat nur Leserechte und kann keine Daten verändern.")
        return False

    def calendar_ui(self):
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Terminkalender"); title.setProperty("class","pageTitle"); v.addWidget(title)
        split=QSplitter(); left=QWidget(); lv=QVBoxLayout(left); right=QWidget(); rv=QVBoxLayout(right)
        self.appt_calendar=QCalendarWidget(); self.appt_calendar.setGridVisible(True)
        # Termine werden direkt im Monatskalender markiert. Bei mehreren Terminarten
        # erhält der Tag eine Mischmarkierung; Details bleiben in der Liste darunter.
        self.appt_calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        lv.addWidget(self.appt_calendar)
        quick=QHBoxLayout(); prev=QPushButton("‹ Tag"); today=QPushButton("Heute"); nxt=QPushButton("Tag ›"); quick.addWidget(prev); quick.addWidget(today); quick.addWidget(nxt); lv.addLayout(quick)
        self.appt_date=QDateEdit(QDate.currentDate()); self.appt_date.setCalendarPopup(True); self.appt_date.setDisplayFormat("dd.MM.yyyy")
        self.appt_time=QTimeEdit(QTime.currentTime()); self.appt_time.setDisplayFormat("HH:mm")
        self.appt_minutes=QSpinBox(); self.appt_minutes.setRange(5,300); self.appt_minutes.setValue(45); self.appt_minutes.setSuffix(" Min.")
        self.appt_type=QComboBox(); self.appt_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Sonstiger Termin"])
        form=QFormLayout(); form.addRow("Datum",self.appt_date); form.addRow("Beginn",self.appt_time); form.addRow("Dauer",self.appt_minutes); form.addRow("Terminart",self.appt_type)
        self.appt_client=QComboBox(); self.appt_client.setEditable(True); self.appt_client.setInsertPolicy(QComboBox.NoInsert); self.appt_client.setMaxVisibleItems(18)
        self.appt_client.lineEdit().setPlaceholderText("Klient suchen – Name eingeben …")
        self.appt_client.completer().setCompletionMode(QCompleter.PopupCompletion); self.appt_client.completer().setCaseSensitivity(Qt.CaseInsensitive); self.appt_client.completer().setFilterMode(Qt.MatchContains)
        self.appt_couple=QComboBox(); self.appt_couple.setEditable(True); self.appt_couple.setInsertPolicy(QComboBox.NoInsert); self.appt_couple.setMaxVisibleItems(18)
        self.appt_couple.lineEdit().setPlaceholderText("Paarakte suchen …")
        self.appt_couple.completer().setCompletionMode(QCompleter.PopupCompletion); self.appt_couple.completer().setCaseSensitivity(Qt.CaseInsensitive); self.appt_couple.completer().setFilterMode(Qt.MatchContains)
        def refresh_calendar_people():
            old_client=self.appt_client.currentData(); old_couple=self.appt_couple.currentData()
            self.appt_client.clear(); self.appt_couple.clear()
            self.appt_client.addItem("Klient optional",None); self.appt_couple.addItem("Paarakte optional",None)
            con=sqlite3.connect(DBFILE)
            for cid,first,last in con.execute("SELECT id,first,last FROM clients ORDER BY id DESC").fetchall(): self.appt_client.addItem((decrypt_text(first)+" "+decrypt_text(last)).strip(),cid)
            for cid,a,b in con.execute("SELECT id,partner_a_name,partner_b_name FROM couples WHERE status='aktiv' ORDER BY id DESC").fetchall(): self.appt_couple.addItem("#"+str(cid)+" "+decrypt_text(a)+" + "+decrypt_text(b),cid)
            con.close()
            for box,old in ((self.appt_client,old_client),(self.appt_couple,old_couple)):
                idx=box.findData(old)
                if idx>=0: box.setCurrentIndex(idx)
        refresh_calendar_people()
        form.addRow("Klient",self.appt_client); form.addRow("Paarakte",self.appt_couple)
        self.appt_status=QComboBox(); self.appt_status.addItems(["geplant","erschienen","abgesagt","ausgefallen"]); form.addRow("Status",self.appt_status)
        self.appt_note=QLineEdit(); self.appt_note.setPlaceholderText("Interne Terminnotiz – verschlüsselt"); form.addRow("Notiz",self.appt_note); rv.addLayout(form)
        actions=QHBoxLayout(); save=QPushButton("Termin speichern"); edit=QPushButton("Termin bearbeiten"); delete=QPushButton("Termin löschen"); start=QPushButton("▶ Sitzung starten"); actions.addWidget(save); actions.addWidget(edit); actions.addWidget(delete); actions.addWidget(start); rv.addLayout(actions)
        split.addWidget(left); split.addWidget(right); split.setStretchFactor(0,1); split.setStretchFactor(1,1); split.setMaximumHeight(455); v.addWidget(split,0)
        viewrow=QHBoxLayout(); self.appt_view=QComboBox(); self.appt_view.addItems(["Tag","Woche"]); viewrow.addWidget(QLabel("Ansicht")); viewrow.addWidget(self.appt_view); viewrow.addStretch(); v.addLayout(viewrow)
        self.appt_day_title=QLabel(); self.appt_day_title.setProperty("class","sectionTitle"); v.addWidget(self.appt_day_title)
        self.appt_list=QTableWidget(0,6); self.appt_list.setHorizontalHeaderLabels(["Zeit","Dauer","Art","Klient / Paar","Status","Notiz"]); self.appt_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.appt_list.setSelectionBehavior(QTableWidget.SelectRows); self.appt_list.setAlternatingRowColors(True); self.appt_list.setMinimumHeight(190); v.addWidget(self.appt_list,1)
        def refresh():
            refresh_calendar_people()
            selected=self.appt_calendar.selectedDate(); d=selected.toString("yyyy-MM-dd"); self.appt_date.setDate(selected)
            con=sqlite3.connect(DBFILE)
            if self.appt_view.currentText()=="Woche":
                monday=selected.addDays(1-selected.dayOfWeek()); sunday=monday.addDays(6); self.appt_day_title.setText("Woche "+monday.toString("dd.MM.")+" – "+sunday.toString("dd.MM.yyyy")); rows=con.execute("SELECT a.id,a.start_time,a.minutes,a.appointment_type,c.first,c.last,a.couple_id,a.status,a.note,a.appointment_date FROM appointments a LEFT JOIN clients c ON c.id=a.client_id WHERE a.appointment_date BETWEEN ? AND ? ORDER BY a.appointment_date,a.start_time",(monday.toString("yyyy-MM-dd"),sunday.toString("yyyy-MM-dd"))).fetchall()
            else:
                self.appt_day_title.setText("Termine am "+selected.toString("dd.MM.yyyy")); rows=[x+(d,) for x in con.execute("SELECT a.id,a.start_time,a.minutes,a.appointment_type,c.first,c.last,a.couple_id,a.status,a.note FROM appointments a LEFT JOIN clients c ON c.id=a.client_id WHERE a.appointment_date=? ORDER BY a.start_time",(d,)).fetchall()]
            con.close()
            # Monatsansicht: Tage mit Terminen farbig markieren.
            first=QDate(selected.year(),selected.month(),1); last=first.addMonths(1).addDays(-1)
            con2=sqlite3.connect(DBFILE)
            month_rows=con2.execute("SELECT appointment_date,appointment_type,status FROM appointments WHERE appointment_date BETWEEN ? AND ?",(first.toString("yyyy-MM-dd"),last.toString("yyyy-MM-dd"))).fetchall(); con2.close()
            day_types={}
            for adate,atype,astatus in month_rows:
                if astatus in ("abgesagt","ausgefallen"): continue
                day_types.setdefault(adate,[]).append(atype or "Sonstiger Termin")
            for day in range(1,last.day()+1):
                qd=QDate(selected.year(),selected.month(),day); fmt=QTextCharFormat()
                types=day_types.get(qd.toString("yyyy-MM-dd"),[])
                if types:
                    palette={"Einzeltherapie":"#8fc2ff","Paargespräch":"#ffc978","Onlinegespräch":"#8bd6a7","Notfalltelefonat":"#ff9b9b","Hausbesuch":"#c2a5ff","Sonstiger Termin":"#c6ccd2"}
                    unique=list(dict.fromkeys(types)); color=palette.get(unique[0],"#c6ccd2") if len(unique)==1 else "#ffd966"
                    fmt.setBackground(QColor(color)); fmt.setForeground(QColor("#17324d")); fmt.setFontWeight(700)
                    fmt.setToolTip(str(len(types))+" Termin"+("" if len(types)==1 else "e")+" · "+", ".join(unique))
                self.appt_calendar.setDateTextFormat(qd,fmt)
            self.appt_list.setRowCount(len(rows))
            for r,(aid,t,m,typ,first,last,couple,status,note,rowdate) in enumerate(rows):
                name=((decrypt_text(first) if first else "")+" "+(decrypt_text(last) if last else "")).strip()
                if couple: name=(name+" · " if name else "")+"Paarakte #"+str(couple)
                shown_time=(QDate.fromString(rowdate,"yyyy-MM-dd").toString("ddd dd.MM. ") if self.appt_view.currentText()=="Woche" else "")+t; vals=[shown_time,str(m)+" Min.",typ or "",name,status,decrypt_text(note)]
                for col,val in enumerate(vals):
                    item=QTableWidgetItem(str(val))
                    # Terminarten sofort visuell unterscheiden.
                    tint={"Einzeltherapie":"#e8f2ff","Paargespräch":"#fff1dc","Onlinegespräch":"#e8f8ee","Notfalltelefonat":"#ffe9e9","Hausbesuch":"#f1eaff","Sonstiger Termin":"#f1f3f5"}.get(typ or "","#ffffff")
                    item.setBackground(QColor(tint))
                    if status in ("abgesagt","ausgefallen"): item.setForeground(QColor("#8a8f96"))
                    self.appt_list.setItem(r,col,item)
                self.appt_list.item(r,0).setData(Qt.UserRole,aid)
        def store():
            if not self.require_edit(): return
            d=self.appt_date.date().toString("yyyy-MM-dd"); t=self.appt_time.time().toString("HH:mm"); cid=self.appt_client.currentData(); couple=self.appt_couple.currentData()
            if cid and couple: QMessageBox.warning(self,"Termin","Bitte entweder Klient oder Paarakte zuordnen, nicht beides."); return
            con=sqlite3.connect(DBFILE)
            requested_start=QTime.fromString(t,"HH:mm"); requested_end=requested_start.addSecs(self.appt_minutes.value()*60); conflict=None
            for eid,estart,eminutes in con.execute("SELECT id,start_time,minutes FROM appointments WHERE appointment_date=? AND status='geplant'",(d,)).fetchall():
                existing_start=QTime.fromString(estart,"HH:mm"); existing_end=existing_start.addSecs(int(eminutes)*60)
                if requested_start < existing_end and requested_end > existing_start:
                    conflict=(eid,estart,eminutes); break
            if conflict: con.close(); QMessageBox.warning(self,"Terminkonflikt","Der Termin überschneidet sich mit einem bestehenden Termin um "+str(conflict[1])+" Uhr."); return
            con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,couple_id,appointment_type,status,note,created_at,username) VALUES(?,?,?,?,?,?,?,?,?,?)",(d,t,self.appt_minutes.value(),cid,couple,self.appt_type.currentText(),self.appt_status.currentText(),encrypt_text(self.appt_note.text().strip()),datetime.now().isoformat(timespec="seconds"),self.current_user.get("username",""))); con.commit(); con.close()
            audit("APPOINTMENT_CREATE",d+" "+t,self.current_user.get("username","")); self.appt_note.clear(); self.appt_calendar.setSelectedDate(self.appt_date.date()); refresh()
        def selected_id():
            row=self.appt_list.currentRow()
            return self.appt_list.item(row,0).data(Qt.UserRole) if row>=0 and self.appt_list.item(row,0) else None
        def edit_selected():
            if not self.require_edit(): return
            aid=selected_id()
            if not aid: return
            con=sqlite3.connect(DBFILE); row=con.execute("SELECT appointment_date,start_time,minutes,client_id,couple_id,appointment_type,status,note FROM appointments WHERE id=?",(aid,)).fetchone(); con.close()
            if not row: return
            d,t,m,cid,couple,typ,status,note=row
            refresh_calendar_people()
            self.appt_date.setDate(QDate.fromString(d,"yyyy-MM-dd")); self.appt_time.setTime(QTime.fromString(t,"HH:mm")); self.appt_minutes.setValue(m); self.appt_type.setCurrentText(typ or "Einzeltherapie"); self.appt_status.setCurrentText(status or "geplant"); self.appt_note.setText(decrypt_text(note))
            for box,val in ((self.appt_client,cid),(self.appt_couple,couple)):
                idx=box.findData(val); box.setCurrentIndex(idx if idx>=0 else 0)
            QMessageBox.information(self,"Termin bearbeiten","Der Termin wurde in die Eingabefelder geladen.\n\nKlient oder Paarakte sowie Datum, Uhrzeit, Dauer, Terminart, Status und Notiz können jetzt geändert werden. Anschließend erneut „Termin bearbeiten“ klicken, um die Änderungen zu speichern.")
            edit.setText("Änderungen speichern")
            edit.setProperty("editingAppointmentId",aid)
            return
        def save_edit_if_active():
            aid=edit.property("editingAppointmentId")
            if not aid: return False
            cid=self.appt_client.currentData(); couple=self.appt_couple.currentData()
            if cid and couple:
                QMessageBox.warning(self,"Termin","Bitte entweder Klient oder Paarakte zuordnen, nicht beides."); return True
            con=sqlite3.connect(DBFILE)
            con.execute("UPDATE appointments SET appointment_date=?,start_time=?,minutes=?,client_id=?,couple_id=?,appointment_type=?,status=?,note=? WHERE id=?",(self.appt_date.date().toString("yyyy-MM-dd"),self.appt_time.time().toString("HH:mm"),self.appt_minutes.value(),cid,couple,self.appt_type.currentText(),self.appt_status.currentText(),encrypt_text(self.appt_note.text().strip()),aid))
            con.commit(); con.close(); audit("APPOINTMENT_UPDATE",str(aid),self.current_user.get("username",""))
            edit.setProperty("editingAppointmentId",None); edit.setText("Termin bearbeiten"); refresh(); return True
        original_edit_selected=edit_selected
        def edit_selected():
            if save_edit_if_active(): return
            original_edit_selected()
        def start_session():
            aid=selected_id()
            if not aid: return
            con=sqlite3.connect(DBFILE); row=con.execute("SELECT appointment_date,start_time,minutes,client_id,appointment_type FROM appointments WHERE id=?",(aid,)).fetchone(); con.close()
            if not row: return
            d,t,m,cid,typ=row
            self.nav.setCurrentRow(1); app=QApplication.instance(); app.processEvents() if app else None
            if hasattr(self,"s_date"): self.s_date.setDate(QDate.fromString(d,"yyyy-MM-dd")); self.s_start.setTime(QTime.fromString(t,"HH:mm")); self.s_end.setTime(QTime.fromString(t,"HH:mm").addSecs(int(m)*60)); self.s_type.setCurrentText(typ if typ in ["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"] else "Einzeltherapie")
            if cid and hasattr(self,"client_pick"):
                for n in range(self.client_pick.count()):
                    data=self.client_pick.itemData(n)
                    if isinstance(data,dict) and data.get("id")==cid: self.client_pick.setCurrentIndex(n); break
        def remove():
            if not self.require_edit(): return
            row=self.appt_list.currentRow()
            if row<0: return
            aid=self.appt_list.item(row,0).data(Qt.UserRole)
            if QMessageBox.question(self,"Termin löschen","Ausgewählten Termin wirklich löschen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            con=sqlite3.connect(DBFILE); con.execute("DELETE FROM appointments WHERE id=?",(aid,)); con.commit(); con.close(); audit("APPOINTMENT_DELETE",str(aid),self.current_user.get("username","")); refresh()
        save.clicked.connect(store); edit.clicked.connect(edit_selected); delete.clicked.connect(remove); start.clicked.connect(start_session); self.appt_calendar.selectionChanged.connect(refresh); self.appt_view.currentTextChanged.connect(lambda *_: refresh())
        today.clicked.connect(lambda: self.appt_calendar.setSelectedDate(QDate.currentDate())); prev.clicked.connect(lambda: self.appt_calendar.setSelectedDate(self.appt_calendar.selectedDate().addDays(-1))); nxt.clicked.connect(lambda: self.appt_calendar.setSelectedDate(self.appt_calendar.selectedDate().addDays(1)))
        refresh(); return page

    def couples_ui(self):
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Paarakte"); title.setProperty("class","pageTitle"); v.addWidget(title)
        info=QLabel("Partner A und Partner B aus vorhandenen Klientenakten auswählen. Gemeinsame und vertrauliche Notizen werden getrennt gespeichert.")
        info.setWordWrap(True); v.addWidget(info)
        row=QHBoxLayout(); self.couple_a=QComboBox(); self.couple_b=QComboBox()
        def refresh_couple_clients():
            old_a=self.couple_a.currentData(); old_b=self.couple_b.currentData()
            self.couple_a.clear(); self.couple_b.clear()
            self.couple_a.addItem("Partner A auswählen",None); self.couple_b.addItem("Partner B auswählen",None)
            con=sqlite3.connect(DBFILE)
            for cid,first,last in con.execute("SELECT id,first,last FROM clients ORDER BY id DESC").fetchall():
                name=(decrypt_text(first)+" "+decrypt_text(last)).strip()
                self.couple_a.addItem(name,cid); self.couple_b.addItem(name,cid)
            con.close()
            for box,old in ((self.couple_a,old_a),(self.couple_b,old_b)):
                idx=box.findData(old)
                if idx>=0: box.setCurrentIndex(idx)
        refresh_couple_clients()
        refresh_clients_btn=QPushButton("↻ Klienten aktualisieren"); refresh_clients_btn.clicked.connect(refresh_couple_clients)
        row.addWidget(self.couple_a); row.addWidget(self.couple_b); row.addWidget(refresh_clients_btn); v.addLayout(row)
        save=QPushButton("Paarakte anlegen"); v.addWidget(save)
        self.couple_list=QListWidget(); self.couple_list.setMaximumHeight(150); v.addWidget(self.couple_list)
        note_row=QHBoxLayout(); self.couple_note_type=QComboBox()
        self.couple_note_type.addItems(["Gemeinsame Notiz","Vertraulich – Partner A","Vertraulich – Partner B"])
        note_row.addWidget(self.couple_note_type); note_save=QPushButton("Notiz speichern"); note_row.addWidget(note_save); v.addLayout(note_row)
        self.couple_note=QTextEdit(); self.couple_note.setPlaceholderText("Notiz zur ausgewählten Paarakte …"); self.couple_note.setMaximumHeight(120); v.addWidget(self.couple_note)
        session_row=QHBoxLayout(); self.couple_session_topic=QLineEdit(); self.couple_session_topic.setPlaceholderText("Sitzungsthema")
        self.couple_session_minutes=QSpinBox(); self.couple_session_minutes.setRange(5,300); self.couple_session_minutes.setValue(45); self.couple_session_minutes.setSuffix(" Min.")
        session_save=QPushButton("Paarsitzung speichern"); session_row.addWidget(self.couple_session_topic,1); session_row.addWidget(self.couple_session_minutes); session_row.addWidget(session_save); v.addLayout(session_row)
        self.couple_session_note=QTextEdit(); self.couple_session_note.setPlaceholderText("Gemeinsame Sitzungsdokumentation …"); self.couple_session_note.setMaximumHeight(100); v.addWidget(self.couple_session_note)
        self.couple_history_filter=QComboBox()
        self.couple_history_filter.addItems(["Gemeinsamer Verlauf","Vertraulich – Partner A","Vertraulich – Partner B"])
        self.couple_history_filter.setToolTip("Vertrauliche Partnernotizen werden niemals im gemeinsamen Verlauf angezeigt.")
        v.addWidget(self.couple_history_filter)
        self.couple_history=QListWidget()
        v.addWidget(self.couple_history,1)
        def selected_id():
            item=self.couple_list.currentItem()
            return item.data(Qt.UserRole) if item else None
        def refresh_history():
            self.couple_history.clear(); cid=selected_id()
            if not cid: return
            view=self.couple_history_filter.currentText()
            con=sqlite3.connect(DBFILE)
            if view=="Gemeinsamer Verlauf":
                rows=con.execute("SELECT created_at,note_type,note_text FROM couple_notes WHERE couple_id=? AND note_type=? ORDER BY id DESC",(cid,"Gemeinsame Notiz")).fetchall()
                sessions=con.execute("SELECT session_date,topic,shared_note,minutes FROM couple_sessions WHERE couple_id=? ORDER BY id DESC",(cid,)).fetchall()
                assessments=con.execute("SELECT created_at,topic,interaction_cycle,shared_goal,safety_flag FROM couple_assessments WHERE couple_id=? ORDER BY id DESC",(cid,)).fetchall()
            else:
                rows=con.execute("SELECT created_at,note_type,note_text FROM couple_notes WHERE couple_id=? AND note_type=? ORDER BY id DESC",(cid,view)).fetchall()
                sessions=[]; assessments=[]
            con.close()
            for date,topic,note,mins in sessions:
                self.couple_history.addItem(f"{date[:16]} · Paarsitzung · {mins} Min. · {decrypt_text(topic)}" + chr(10) + decrypt_text(note))
            for created,topic,cycle,goal,risk in assessments:
                flag=" · SICHERHEIT" if risk else ""
                self.couple_history.addItem(f"{created[:16]} · Paar-Assessment · {topic}{flag}" + chr(10) + "Kreislauf: " + decrypt_text(cycle) + " · Ziel: " + decrypt_text(goal))
            for created,kind,txt in rows:
                self.couple_history.addItem(f"{created[:16]} · {kind}" + chr(10) + decrypt_text(txt))
        def refresh():
            self.couple_list.clear(); con=sqlite3.connect(DBFILE)
            rows=con.execute("SELECT id,partner_a_name,partner_b_name,status,created_at FROM couples ORDER BY id DESC").fetchall(); con.close()
            for cid,a,b,status,created in rows:
                item=QListWidgetItem(f"#{cid}  {decrypt_text(a)}  +  {decrypt_text(b)}   · {status} · {created[:10]}")
                item.setData(Qt.UserRole,cid); self.couple_list.addItem(item)
        def create():
            if not self.require_edit(): return
            aid=self.couple_a.currentData(); bid=self.couple_b.currentData()
            if not aid or not bid: QMessageBox.warning(self,"Paarakte","Bitte beide Partner auswählen."); return
            if aid==bid: QMessageBox.warning(self,"Paarakte","Partner A und Partner B müssen unterschiedliche Klienten sein."); return
            an=self.couple_a.currentText(); bn=self.couple_b.currentText(); con=sqlite3.connect(DBFILE)
            exists=con.execute("SELECT id FROM couples WHERE (partner_a_client_id=? AND partner_b_client_id=?) OR (partner_a_client_id=? AND partner_b_client_id=?)",(aid,bid,bid,aid)).fetchone()
            if exists: con.close(); QMessageBox.information(self,"Paarakte",f"Für dieses Paar besteht bereits Paarakte #{exists[0]}."); return
            con.execute("INSERT INTO couples(partner_a_client_id,partner_b_client_id,partner_a_name,partner_b_name,status,created_at) VALUES(?,?,?,?,?,?)",(aid,bid,encrypt_text(an),encrypt_text(bn),"aktiv",datetime.now().isoformat(timespec="seconds")))
            con.commit(); con.close(); audit("COUPLE_CREATE",f"{an} + {bn}",self.current_user.get("username","")); refresh()
        def save_note():
            if not self.require_edit(): return
            cid=selected_id(); txt=self.couple_note.toPlainText().strip()
            if not cid: QMessageBox.warning(self,"Paarakte","Bitte zuerst eine Paarakte auswählen."); return
            if not txt: return
            kind=self.couple_note_type.currentText()
            if kind.startswith("Vertraulich"):
                answer=QMessageBox.question(self,"Vertrauliche Partnernotiz","Diese Notiz wird ausschließlich im vertraulichen Bereich gespeichert und nicht im gemeinsamen Verlauf angezeigt. Speichern?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
                if answer!=QMessageBox.Yes: return
            con=sqlite3.connect(DBFILE)
            con.execute("INSERT INTO couple_notes(couple_id,created_at,note_type,note_text,username) VALUES(?,?,?,?,?)",(cid,datetime.now().isoformat(timespec="seconds"),kind,encrypt_text(txt),self.current_user.get("username","")))
            con.commit(); con.close(); audit("COUPLE_NOTE",f"Paarakte #{cid}: {kind}",self.current_user.get("username","")); self.couple_note.clear(); refresh_history()
        def save_session():
            if not self.require_edit(): return
            cid=selected_id(); topic=self.couple_session_topic.text().strip(); note=self.couple_session_note.toPlainText().strip()
            if not cid: QMessageBox.warning(self,"Paarakte","Bitte zuerst eine Paarakte auswählen."); return
            if not topic and not note: QMessageBox.warning(self,"Paarsitzung","Bitte Thema oder Sitzungsnotiz eintragen."); return
            now=datetime.now().isoformat(timespec="seconds"); con=sqlite3.connect(DBFILE)
            con.execute("INSERT INTO couple_sessions(couple_id,session_date,topic,shared_note,minutes,username,created_at) VALUES(?,?,?,?,?,?,?)",(cid,now,encrypt_text(topic),encrypt_text(note),self.couple_session_minutes.value(),self.current_user.get("username",""),now))
            con.commit(); con.close()
            audit("COUPLE_SESSION",f"Paarakte #{cid}",self.current_user.get("username",""))
            self.couple_session_topic.clear(); self.couple_session_note.clear(); refresh_history()
        save.clicked.connect(create)
        note_save.clicked.connect(save_note)
        session_save.clicked.connect(save_session)
        self.couple_list.currentItemChanged.connect(lambda *_: refresh_history())
        refresh()
        return page

    def session_ui(self):
        self.session_live_clock=None
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setObjectName("sessionScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body=QWidget(); body.setMinimumWidth(0); v=QVBoxLayout(body); v.setContentsMargins(16,10,16,12); v.setSpacing(8)
        top=QHBoxLayout(); head=QVBoxLayout(); title=QLabel("▣  Sitzungsnotiz"); title.setObjectName("pageTitle"); subtitle=QLabel("Sitzung dokumentieren · Klientendaten · Notizen · Handschrift · Speichern"); subtitle.setObjectName("pageSub"); head.addWidget(title); head.addWidget(subtitle)
        self.clock=QLabel("00:00:00"); self.clock.setAlignment(Qt.AlignCenter); self.clock.setFixedSize(118,36); self.clock.setStyleSheet("font-size:20px;font-weight:800;border:2px solid #8091a1;border-radius:10px;background:white")
        timerbtn=QPushButton("▶  Timer starten"); timerbtn.setFixedHeight(36); timerbtn.setMinimumWidth(118); timerbtn.setStyleSheet("background:#16a34a;color:white;font-weight:800;font-size:14px"); timerbtn.clicked.connect(self.start_session)
        self.session_live_clock=QLabel(QTime.currentTime().toString("HH:mm:ss")); self.session_live_clock.setAlignment(Qt.AlignCenter); self.session_live_clock.setFixedSize(94,36); self.session_live_clock.setToolTip("Aktuelle Uhrzeit – live"); self.session_live_clock.setStyleSheet("font-size:16px;font-weight:800;color:#17324d;background:#e8f0f6;border-radius:10px")
        top.addLayout(head); top.addStretch(); top.addWidget(self.session_live_clock); top.addWidget(self.clock); top.addWidget(timerbtn); v.addLayout(top)

        row=QHBoxLayout(); row.setSpacing(6); row.setContentsMargins(0,0,0,0)
        session=QFrame(); session.setObjectName("formCard"); sg=QGridLayout(session); sg.setContentsMargins(10,8,10,10); sg.setHorizontalSpacing(7); sg.setVerticalSpacing(6)
        st=QLabel("▤  Sitzungsdaten"); st.setObjectName("sectionTitle"); sg.addWidget(st,0,0,1,3)
        self.client_pick=QComboBox(); self.client_pick.setEditable(True); self.client_pick.setInsertPolicy(QComboBox.NoInsert); self.client_pick.setPlaceholderText("Klient auswählen …"); self.client_pick.addItem("Klient auswählen …",None)
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())): self.client_pick.addItem(f"{cc.get('last','')}, {cc.get('first','')}",cc)
        newclient=QPushButton("＋ Neu"); newclient.setMinimumHeight(28); newclient.setMaximumWidth(72); newclient.clicked.connect(self.open_new_client_dialog)
        self.s_date=QDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_date.setDisplayFormat("dd.MM.yyyy")
        self.s_start=QTimeEdit(QTime.currentTime()); self.s_end=QTimeEdit(QTime.currentTime().addSecs(45*60)); self.s_start.setDisplayFormat("HH:mm"); self.s_end.setDisplayFormat("HH:mm")
        self.s_type=QComboBox(); self.s_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"]); self.s_red=QCheckBox("Ermäßigter Satz")
        self.partner_pick=QComboBox(); self.partner_pick.setEditable(True); self.partner_pick.setInsertPolicy(QComboBox.NoInsert); self.partner_pick.addItem("Zweiten Partner auswählen …",None)
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())): self.partner_pick.addItem(f"{cc.get('last','')}, {cc.get('first','')}",cc)
        self.partner_label=QLabel("2. Partner *"); self.partner_label.setVisible(False); self.partner_pick.setVisible(False)
        def update_partner_choice(text):
            is_pair=(text=="Paargespräch"); self.partner_label.setVisible(is_pair); self.partner_pick.setVisible(is_pair)
            if not is_pair: self.partner_pick.setCurrentIndex(0)
        self.s_type.currentTextChanged.connect(update_partner_choice)
        for x in (self.client_pick,self.s_date,self.s_start,self.s_end,self.s_type,self.partner_pick): x.setMinimumHeight(28)
        sg.addWidget(QLabel("Klient *"),1,0); sg.addWidget(self.client_pick,1,1); sg.addWidget(newclient,1,2)
        for rr,(lab,field) in enumerate([("Datum *",self.s_date),("Beginn *",self.s_start),("Ende *",self.s_end),("Art *",self.s_type)],2): sg.addWidget(QLabel(lab),rr,0); sg.addWidget(field,rr,1,1,2)
        sg.addWidget(self.partner_label,6,0); sg.addWidget(self.partner_pick,6,1,1,2)
        sg.addWidget(self.s_red,7,1,1,2); sg.setColumnStretch(1,2); sg.setColumnStretch(2,1); session.setMinimumWidth(0); session.setMaximumWidth(410); session.setMinimumHeight(270); row.addWidget(session,4)

        details=QFrame(); details.setObjectName("formCard"); dg=QGridLayout(details); dg.setContentsMargins(10,8,10,10); dg.setHorizontalSpacing(7); dg.setVerticalSpacing(6)
        dt=QLabel("●  Klientendaten"); dt.setObjectName("sectionTitle"); dg.addWidget(dt,0,0,1,2)
        self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit()
        for x in (self.s_last,self.s_first,self.s_dob): x.setMinimumHeight(30); x.setReadOnly(True); x.setPlaceholderText("–")
        self.s_phone=QLineEdit(); self.s_email=QLineEdit()
        for x in (self.s_phone,self.s_email): x.setMinimumHeight(30); x.setReadOnly(True); x.setPlaceholderText("–")
        for rr,(lab,field) in enumerate([("Nachname",self.s_last),("Vorname",self.s_first),("Geburtsdatum",self.s_dob),("Telefon",self.s_phone),("E-Mail",self.s_email)],1): dg.addWidget(QLabel(lab),rr,0); dg.addWidget(field,rr,1)
        details.setMinimumWidth(0); details.setMaximumWidth(330); details.setMinimumHeight(270); editclient=QPushButton("♙ Klientendaten bearbeiten"); editclient.setFixedHeight(30); dg.addWidget(editclient,6,0,1,2); row.addWidget(details,3)

        quick=QFrame(); quick.setObjectName("formCard"); qg=QGridLayout(quick); qg.setContentsMargins(10,8,10,10); qg.setHorizontalSpacing(7); qg.setVerticalSpacing(6)
        qt=QLabel("♙＋  Klient schnell anlegen"); qt.setObjectName("sectionTitle"); qg.addWidget(qt,0,0,1,2)
        qlast=QLineEdit(); qfirst=QLineEdit(); qdob=QLineEdit(); qdob.setPlaceholderText("TT.MM.JJJJ"); qphone=QLineEdit(); qmail=QLineEdit()
        for x in (qlast,qfirst,qdob,qphone,qmail): x.setMinimumHeight(30)
        qg.addWidget(QLabel("Nachname *"),1,0); qg.addWidget(QLabel("Vorname *"),1,1); qg.addWidget(qlast,2,0); qg.addWidget(qfirst,2,1)
        qg.addWidget(QLabel("Geburtsdatum"),3,0,1,2); qg.addWidget(qdob,4,0,1,2); qg.addWidget(QLabel("Telefon"),5,0); qg.addWidget(QLabel("E-Mail"),5,1); qg.addWidget(qphone,6,0); qg.addWidget(qmail,6,1)
        qsave=QPushButton("Klient anlegen"); qsave.setFixedHeight(30); qg.addWidget(qsave,7,0,1,2); quick.setMinimumWidth(0); quick.setMaximumWidth(330); quick.setMinimumHeight(270); row.addWidget(quick,3); v.addLayout(row)

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
                if hasattr(self,"session_diag"): self.session_diag.setText(cc.get("diagnosis",""))
        self.client_pick.currentIndexChanged.connect(picked)
        # Beim Programmstart/Sitzungsformular niemals automatisch einen Klienten laden.
        self.client_pick.blockSignals(True); self.client_pick.setCurrentIndex(0); self.client_pick.setEditText("Klient auswählen …"); self.client_pick.blockSignals(False)
        for field in (self.s_last,self.s_first,self.s_dob,self.s_phone,self.s_email): field.clear()
        editclient.clicked.connect(self.edit_session_client)

        clinical=QFrame(); clinical.setObjectName("formCard"); cg=QGridLayout(clinical); cg.setContentsMargins(10,8,10,10); cg.setHorizontalSpacing(7); cg.setVerticalSpacing(8)
        ct=QLabel("◉  Leistung & Diagnose"); ct.setObjectName("sectionTitle"); cg.addWidget(ct,0,0,1,4)
        self.session_diag=QLineEdit(); self.session_diag.setPlaceholderText("F-Code oder Diagnose, z. B. F32.1"); self.session_diag.setMinimumHeight(30)
        fquick=QComboBox(); fquick.setEditable(True); fquick.addItems(["F-Code auswählen …","F32.0 – Leichte depressive Episode","F32.1 – Mittelgradige depressive Episode","F32.2 – Schwere depressive Episode ohne psychotische Symptome","F33.0 – Rezidivierende depressive Störung, gegenwärtig leichte Episode","F33.1 – Rezidivierende depressive Störung, gegenwärtig mittelgradige Episode","F40.0 – Agoraphobie","F40.1 – Soziale Phobien","F41.0 – Panikstörung","F41.1 – Generalisierte Angststörung","F43.0 – Akute Belastungsreaktion","F43.1 – Posttraumatische Belastungsstörung","F43.2 – Anpassungsstörungen","F51.0 – Nichtorganische Insomnie"])
        def use_fcode(text):
            if " – " in text: self.session_diag.setText(text)
        fquick.currentTextChanged.connect(use_fcode)
        cg.addWidget(QLabel("Verdachtsdiagnose / ICD"),1,0); cg.addWidget(self.session_diag,1,1,1,2); cg.addWidget(fquick,1,3)
        self.session_diag.setToolTip("Arbeitsdiagnose/Verdacht; keine automatische gesicherte Diagnosestellung.")
        tip=QLabel("Verdachtsdiagnose ist optional und wird nicht automatisch als gesicherte Diagnose übernommen."); tip.setObjectName("pageSub"); tip.setWordWrap(True); cg.addWidget(tip,2,1,1,3); v.addWidget(clinical)

        notesbox=QFrame(); notesbox.setObjectName("formCard"); nv=QVBoxLayout(notesbox); nv.setContentsMargins(16,12,16,14); nv.setSpacing(10); nhead=QHBoxLayout(); nh=QLabel("▤  Therapienotizen"); nh.setObjectName("sectionTitle"); nhead.addWidget(nh); nhead.addStretch(); template=QComboBox(); template.addItems(["Vorlagen","Erstgespräch","Verlauf","Abschluss"]); template.setMinimumWidth(130); template.setMaximumWidth(160); template.setMinimumHeight(30); nhead.addWidget(template); nv.addLayout(nhead)
        self.notes=QTextEdit(); self.notes.setPlaceholderText("Hier können Sie Ihre Therapienotizen eingeben …");
        note_tools=QHBoxLayout(); bullet=QPushButton("• Aufzählung"); timestamp=QPushButton("⏱ Zeitmarke"); clear_note=QPushButton("Notiz leeren")
        for b in (bullet,timestamp,clear_note): b.setMinimumHeight(30); note_tools.addWidget(b)
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
        homeworkbox=QFrame(); homeworkbox.setObjectName("formCard"); hv=QVBoxLayout(homeworkbox); hh=QLabel("✓ Hausaufgaben / Vereinbarungen bis zur nächsten Sitzung"); hh.setObjectName("sectionTitle"); hv.addWidget(hh)
        self.session_homework=QTextEdit(); self.session_homework.setPlaceholderText("Hausaufgaben, Übungen, Beobachtungsaufträge oder konkrete Vereinbarungen …"); self.session_homework.setMinimumHeight(80); self.session_homework.setMaximumHeight(140)
        hwbar=QHBoxLayout(); hwgen=QPushButton("✦ Vorschläge aus Verdachtsdiagnose"); hwgen.setMinimumHeight(32); hwbar.addWidget(hwgen); hwbar.addStretch(); hv.addLayout(hwbar)
        def suggest_homework():
            d=self.session_diag.text().strip().upper()
            suggestions=[]
            if d.startswith(("F32","F33")): suggestions=["Aktivitäten- und Stimmungstagebuch führen.","Eine kleine angenehme oder sinnvolle Aktivität konkret planen und durchführen.","Belastende automatische Gedanken notieren und alternative Sichtweisen sammeln."]
            elif d.startswith(("F40","F41")): suggestions=["Angstauslöser, Gedanken, Körperreaktionen und Verhalten kurz protokollieren.","Eine vereinbarte kleine Annäherungsübung durchführen und Angstverlauf dokumentieren.","Atem-/Entspannungsübung regelmäßig erproben und Wirkung notieren."]
            elif d.startswith("F43.1"): suggestions=["Belastungsniveau und Auslöser beobachten; keine eigenständige Trauma-Konfrontation durchführen.","Eine vereinbarte Stabilisierungs-/Groundingübung üben.","Hilfreiche Ressourcen und sichere Situationen notieren."]
            elif d.startswith("F43.2"): suggestions=["Belastende Situationen und eigene Reaktionen kurz protokollieren.","Eine realistische entlastende Aktivität oder einen nächsten kleinen Schritt planen.","Unterstützende Personen und vorhandene Ressourcen sammeln."]
            elif d.startswith("F51"): suggestions=["Schlafprotokoll führen (Schlafenszeit, Wachphasen, Aufstehen, Tagesbefinden).","Möglichst konstante Aufstehzeit erproben.","Abendliche Aktivierung und Grübelzeiten beobachten."]
            elif d.startswith("F90"): suggestions=["Eine Aufgabe in kleine Schritte zerlegen und mit sichtbarer Checkliste bearbeiten.","Ablenkungen und Konzentrationsphasen kurz protokollieren.","Eine konkrete Alltagsroutine mit Erinnerungshilfe erproben."]
            else: suggestions=["Eine konkrete Beobachtungsaufgabe für die Woche vereinbaren.","Auslöser, Gedanken, Gefühle und Verhalten in relevanten Situationen kurz notieren."]
            text="\n".join("• "+x for x in suggestions)
            existing=self.session_homework.toPlainText().strip()
            self.session_homework.setPlainText((existing+"\n\n" if existing else "")+text)
        hwgen.clicked.connect(suggest_homework)
        hv.addWidget(self.session_homework); v.addWidget(homeworkbox)

        self.ink=InkCanvas(); self.current_ink_file=""; self.current_ocr_text=""; inkhead=QHBoxLayout(); inklabel=QLabel("✎  Handschrift / Touch / Stift"); inklabel.setObjectName("sectionTitle"); inkhead.addWidget(inklabel); inkhead.addStretch()
        width=QSpinBox(); width.setRange(1,10); width.setValue(3); width.setSuffix(" px"); width.valueChanged.connect(self.ink.set_width); eraser=QCheckBox("Radierer"); eraser.toggled.connect(self.ink.set_eraser)
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); clearink=QPushButton("Zeichenfläche löschen"); clearink.clicked.connect(self.ink.clear); saveink=QPushButton("💾 Notiz speichern"); saveink.clicked.connect(self.save_ink_note); ocrink=QPushButton("⌨ Handschrift → Text"); ocrink.setToolTip("Lokale Windows-Handschrifterkennung; erkannter Text wird vor Übernahme angezeigt."); ocrink.clicked.connect(self.ink_to_text); fullscreen=QPushButton("⛶ Notizbuch"); fullscreen.clicked.connect(self.open_ink_fullscreen)
        for x in (QLabel("Stärke:"),width,eraser,undo,saveink,ocrink,clearink,fullscreen):
            if hasattr(x,"setMinimumHeight"): x.setMinimumHeight(40)
            inkhead.addWidget(x)
        self.inkbox=QFrame(); self.inkbox.setObjectName("formCard"); self.inkv=QVBoxLayout(self.inkbox); self.inkv.setContentsMargins(16,12,16,14); self.inkv.setSpacing(10); self.inkv.addLayout(inkhead); self.ink.setMinimumHeight(235); self.ink.setStyleSheet("background:white;border:1px dashed #b8c7d4;border-radius:8px"); self.inkv.addWidget(self.ink); v.addWidget(self.inkbox,1)
        h=QHBoxLayout()
        buttons=[("▶ Sitzung starten",self.start_session,"background:#16a34a"),("⏸ Pause/Fortsetzen",self.pause,"background:#1683d8"),("■ Sitzung beenden",self.end_session,"background:#e11d48"),("💾 Speichern",self.save_session,"background:#f8fafc;color:#1261a0;border:1px solid #9bb7cf")]
        for text_,fn,style in buttons:
            b=QPushButton(text_); b.setMinimumHeight(48); b.setStyleSheet(style+";font-weight:800;font-size:13px"); b.clicked.connect(fn); h.addWidget(b)
        v.addLayout(h)
        body.setMinimumWidth(0); body.setMaximumWidth(1180); scroll.setWidget(body); outer.addWidget(scroll); return page

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

    def ink_to_text(self):
        """Handschrift lokal mit Windows OCR erkennen."""
        if not hasattr(self,"ink") or self.ink.image.isNull():
            return QMessageBox.warning(self,"Handschrift erkennen","Keine Handschrift vorhanden.")
        tmp=Path(tempfile.gettempdir())/f"PraxisPro_OCR_{os.getpid()}_{int(time.time()*1000)}.png"
        src=self.ink.image
        work=src.convertToFormat(QImage.Format_Grayscale8).scaled(src.width()*2,src.height()*2,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        if not work.save(str(tmp),"PNG"):
            return QMessageBox.warning(self,"Handschrift erkennen","Die Zeichenfläche konnte nicht vorbereitet werden.")
        ps=r'''$ErrorActionPreference="Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
function Await($op,$type) {
  $asTask=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1} | Select-Object -First 1)
  $task=$asTask.MakeGenericMethod($type).Invoke($null,@($op))
  $task.Wait()
  return $task.Result
}
$path=$env:PRAXISPRO_OCR_PATH
$file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
$decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$langs=[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
$preferred=$langs | Where-Object { $_.LanguageTag -like 'de-*' } | Select-Object -First 1
if ($null -eq $preferred) { $preferred=$langs | Where-Object { $_.LanguageTag -like 'tr-*' } | Select-Object -First 1 }
if ($null -eq $preferred) { $preferred=$langs | Select-Object -First 1 }
if ($null -eq $preferred) { throw 'Keine Windows-OCR-Sprache installiert. Bitte Deutsch oder Türkisch als Windows-Sprachfunktion installieren.' }
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($preferred)
if ($null -eq $engine) { throw ('Windows OCR konnte nicht gestartet werden: '+$preferred.LanguageTag) }
$result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$result.Text
'''
        try:
            env=os.environ.copy(); env["PRAXISPRO_OCR_PATH"]=str(tmp.resolve())
            QApplication.setOverrideCursor(Qt.WaitCursor); QApplication.processEvents()
            run=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-Command",ps],env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=45)
            recognized=run.stdout.strip()
            if run.returncode!=0 or not recognized:
                detail=(run.stderr or "Keine Schrift erkannt.").strip()[:900]
                audit("INK_OCR_ERROR",detail,self.current_user.get("username","") if self.current_user else "")
                return QMessageBox.warning(self,"Handschrift erkennen","OCR konnte keinen Text liefern.\n\n"+detail)
            dlg=QDialog(self); dlg.setWindowTitle("Handschrift → Text prüfen"); dlg.resize(720,500); v=QVBoxLayout(dlg)
            v.addWidget(QLabel("Erkannten Text prüfen und bei Bedarf korrigieren (Deutsch/Türkisch):"))
            edit=QTextEdit(); edit.setPlainText(recognized); v.addWidget(edit,1)
            buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Save).setText("In Therapienotiz übernehmen"); v.addWidget(buttons)
            def accept_text():
                cleaned=edit.toPlainText().strip()
                if cleaned:
                    existing=self.notes.toPlainText().rstrip(); self.notes.setPlainText((existing+"\n\n" if existing else "")+cleaned)
                dlg.accept()
            buttons.accepted.connect(accept_text); buttons.rejected.connect(dlg.reject); dlg.exec()
        except Exception as e:
            audit("INK_OCR_EXCEPTION",str(e)[:900],self.current_user.get("username","") if self.current_user else "")
            QMessageBox.warning(self,"Handschrift erkennen","OCR-Fehler:\n\n"+str(e)[:900])
        finally:
            if QApplication.overrideCursor() is not None: QApplication.restoreOverrideCursor()
            try: tmp.unlink(missing_ok=True)
            except Exception: pass

    def open_ink_fullscreen(self):
        dlg=QDialog(self); dlg.setWindowTitle("Freihand-Notizbuch"); dlg.resize(1280,800); dlg.setMinimumSize(760,520); dlg.setWindowFlag(Qt.WindowMaximizeButtonHint,True)
        v=QVBoxLayout(dlg); bar=QHBoxLayout(); title=QLabel("Handschrift / Stift"); title.setStyleSheet("font-size:22px;font-weight:700"); bar.addWidget(title); bar.addStretch()
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); erase=QCheckBox("Radierer"); erase.setChecked(self.ink.eraser); erase.toggled.connect(self.ink.set_eraser)
        width=QSpinBox(); width.setRange(1,10); width.setValue(self.ink.pen_width); width.valueChanged.connect(self.ink.set_width)
        zoom=QSlider(Qt.Horizontal); zoom.setRange(60,180); zoom.setValue(100); zoom.setFixedWidth(170); zoomlabel=QLabel("100 %")
        save=QPushButton("💾 Notiz speichern"); save.clicked.connect(self.save_ink_note); ocr=QPushButton("⌨ Handschrift → Text"); ocr.clicked.connect(self.ink_to_text); clear=QPushButton("Löschen"); clear.clicked.connect(self.ink.clear); full=QPushButton("⛶ Vollbild"); full.setCheckable(True); full.toggled.connect(lambda on: dlg.showFullScreen() if on else dlg.showNormal()); close=QPushButton("✓ Zur Sitzung"); close.clicked.connect(dlg.accept)
        for x in (undo,erase,QLabel("Stärke"),width,QLabel("Ansicht"),zoom,zoomlabel,save,ocr,clear,full,close): bar.addWidget(x)
        v.addLayout(bar); holder=QScrollArea(); holder.setWidgetResizable(True); holder.setAlignment(Qt.AlignCenter); self.ink.setMinimumSize(360,240); self.ink.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding); self.ink.setParent(holder); holder.setWidget(self.ink)
        basew,baseh=max(360,holder.viewport().width()),max(240,holder.viewport().height())
        def scale_ink(value):
            zoomlabel.setText(f"{value} %"); self.ink.setMinimumSize(max(360,int(basew*value/100)),max(240,int(baseh*value/100)))
        zoom.valueChanged.connect(scale_ink); scale_ink(100); v.addWidget(holder,1)
        dlg.exec()
        self.ink.setParent(self.inkbox); self.inkv.addWidget(self.ink); self.ink.show()

    def helper_ui(self):
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body=QWidget(); body.setMinimumWidth(0); v=QVBoxLayout(body); v.setContentsMargins(16,10,16,14); v.setSpacing(6)
        title=QLabel("Sitzungsassistent – Fragen & Interventionen"); title.setStyleSheet("font-size:20px;font-weight:700"); v.addWidget(title)
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
            "Systemisch":["Funktion und Kontext der Angst im Lebenssystem explorieren.","Ausnahmen, Ressourcen und Perspektiven wichtiger Bezugspersonen einbeziehen."]},
          "Selbstverletzung / Suizidgedanken":{"Fragen":["Gab es seit dem letzten Gespräch Gedanken, sich etwas anzutun oder nicht mehr leben zu wollen?","Gibt es konkrete Vorstellungen, Vorbereitungen oder aktuell verfügbare Mittel?","Was hat Sie bisher davon abgehalten zu handeln?","Wer kann heute unmittelbar unterstützen?","Was braucht es, damit die nächsten Stunden sicher gestaltet werden können?"],"VT":["Aktuelle Gedanken, Impulse, Planung, Mittel und Schutzfaktoren strukturiert explorieren.","Einen konkreten Sicherheitsplan und erreichbare Unterstützung vereinbaren; bei akuter Gefahr Notfallversorgung veranlassen."],"TP":["Akute Sicherheit hat Vorrang; danach Auslöser, Affekte, Beziehungskonflikte und Bedeutung der Krise explorieren."],"Systemisch":["Verfügbare Bezugspersonen und professionelle Hilfen konkret aktivieren.","Verantwortlichkeiten und nächste Schritte für die unmittelbare Sicherheit eindeutig klären."]},
          "PTBS / Trauma":{"Fragen":["Welche Erinnerungen, Bilder, Albträume oder Körperreaktionen drängen sich ungewollt auf?","Welche inneren oder äußeren Auslöser bemerken Sie?","Welche Situationen, Orte, Gedanken oder Gefühle vermeiden Sie seit dem Ereignis?","Gibt es Phasen von starker Wachsamkeit, Schreckhaftigkeit, Reizbarkeit oder Schlafproblemen?","Was hilft Ihnen, sich im Hier und Jetzt wieder sicher und orientiert zu fühlen?","Welche Auswirkungen haben die Beschwerden auf Beziehungen, Arbeit und Alltag?","Welche Ressourcen und sicheren Bezugspersonen stehen Ihnen zur Verfügung?"],"VT":["Traumabezogene Symptome, Trigger, Vermeidung, Sicherheitsverhalten und funktionale Beeinträchtigung strukturiert erfassen.","Psychoedukation und individuelle Stabilisierung passend zur Belastbarkeit einsetzen.","Bei entsprechender Indikation traumafokussierte Verfahren bzw. Expositionsarbeit fachgerecht planen; nicht automatisch auslösen.","Dysfunktionale traumabezogene Bewertungen, Schuld- und Schamgedanken sowie Vermeidung bearbeiten.","Rückfallprophylaxe, Selbstwirksamkeit und Wiederaufnahme wichtiger Lebensbereiche fördern."],"TP":["Aktuelle Sicherheit und psychische Stabilität vor vertiefender Bearbeitung berücksichtigen.","Traumatische Erfahrung, Affekte und deren subjektive Bedeutung im biografischen und Beziehungskontext explorieren.","Abwehr, Scham, Schuld, Ohnmacht, Aggression und Beziehungserwartungen behutsam verstehen.","Übertragung und Gegenübertragung sowie mögliche traumabezogene Beziehungsmuster reflektieren.","Tempo und Nähe der Bearbeitung so gestalten, dass Überflutung und Retraumatisierung vermieden werden."],"Systemisch":["Traumafolgen im sozialen und familiären Kontext betrachten, ohne Verantwortung für das Trauma zu verschieben.","Sichere Beziehungen, Ressourcen, Ausnahmen und bereits gelingende Bewältigung aktivieren.","Wechselwirkungen zwischen Symptomen, Partnerschaft, Familie, Arbeit und Unterstützungssystemen sichtbar machen.","Zirkuläre und ressourcenorientierte Fragen nutzen, wenn sie Stabilität und Handlungsspielraum fördern.","Gemeinsam konkrete Veränderungen im Umfeld entwickeln, die Sicherheit, Selbstbestimmung und Teilhabe stärken."],"SIT":["Aktuelle Muster, Beziehungsgestaltung, innere Positionen und problemaufrechterhaltende Interaktionen konkret erfassen.","Ressourcen und bereits funktionierende Lösungsansätze konsequent sichtbar und nutzbar machen.","Handlungsorientierte, nachvollziehbare nächste Schritte gemeinsam entwickeln und im Alltag überprüfen.","Bei Traumafolgen Stabilität und Sicherheit priorisieren; traumafokussierte Bearbeitung nur im fachlich passenden Rahmen."]},
          "ADHS / Aufmerksamkeit":{"Fragen":["In welchen Alltagssituationen fallen Aufmerksamkeit oder Organisation besonders schwer?","Was wird häufig begonnen, aber nicht beendet?","Welche Strategien funktionieren bereits?","Wie wirken Zeitdruck, Schlaf und Stress auf die Symptome?","Welche konkrete Veränderung würde den Alltag diese Woche erleichtern?"],"VT":["Aufgaben in kleine sichtbare Schritte zerlegen und externe Strukturhilfen erproben.","Ablenkungsquellen, Zeitplanung und Verstärkung hilfreichen Verhaltens untersuchen."],"TP":["Selbstwert, Beschämung und Beziehungserfahrungen im Zusammenhang mit wiederholtem Scheitern explorieren."],"Systemisch":["Anforderungen und Unterstützung in Familie, Arbeit oder Ausbildung sichtbar machen.","Umgebung so gestalten, dass hilfreiches Verhalten leichter wird."]},
          "Zwänge":{"Fragen":["Welche Gedanken, Bilder oder Impulse lösen den stärksten Druck aus?","Welche Handlungen oder mentalen Rituale folgen darauf?","Wie lange beschäftigen Sie die Zwänge täglich?","Was befürchten Sie, wenn Sie das Ritual nicht ausführen?","Welche Bereiche Ihres Lebens werden dadurch eingeschränkt?"],"VT":["Zwangskreislauf, kurzfristige Entlastung und langfristige Aufrechterhaltung transparent machen.","Expositionsbasierte Schritte nur nach individueller Indikations- und Belastungsprüfung planen."],"TP":["Bedeutung von Kontrolle, Schuld, Aggression und Verantwortung explorieren."],"Systemisch":["Reaktionen und mögliche Einbindung naher Bezugspersonen in Zwangsrituale betrachten.","Unterstützende Veränderungen ohne zusätzliche Rückversicherung entwickeln."]},
          "Selbstfürsorge / Grenzen":{"Fragen":["Woran merken Sie, dass Sie über Ihre Grenze gehen?","Bei wem fällt Nein-Sagen besonders schwer?","Welche Befürchtung steht hinter dem Setzen einer Grenze?","Was würden Sie einer nahestehenden Person in derselben Situation raten?","Welche kleine Grenze können Sie diese Woche konkret erproben?"],"VT":["Auslöser, automatische Gedanken und Konsequenzen fehlender Abgrenzung analysieren.","Konkrete Formulierungen und Verhaltensübungen vorbereiten."],"TP":["Konflikte zwischen Autonomie, Zugehörigkeit, Schuld und Anerkennung explorieren."],"Systemisch":["Rollen und Erwartungen im Umfeld sichtbar machen.","Veränderungen als Wechselwirkung im Beziehungssystem betrachten."]}
        }
        # F-Code-Schnellzugriff als Arbeitshilfe (keine automatische Diagnose)
        fcodes={
          "F32.0":"Leichte depressive Episode","F32.1":"Mittelgradige depressive Episode","F32.2":"Schwere depressive Episode ohne psychotische Symptome","F33.0":"Rezidivierende depressive Störung, gegenwärtig leichte Episode","F33.1":"Rezidivierende depressive Störung, gegenwärtig mittelgradige Episode","F40.0":"Agoraphobie","F40.1":"Soziale Phobien","F41.0":"Panikstörung","F41.1":"Generalisierte Angststörung","F43.0":"Akute Belastungsreaktion","F43.1":"Posttraumatische Belastungsstörung","F43.2":"Anpassungsstörungen","F45.0":"Somatisierungsstörung","F50.0":"Anorexia nervosa","F50.2":"Bulimia nervosa","F51.0":"Nichtorganische Insomnie","F60.3":"Emotional instabile Persönlichkeitsstörung","F90.0":"Einfache Aktivitäts- und Aufmerksamkeitsstörung"
        }
        icd_info={
          "F32.0":("Leichte depressive Episode","Gedrückte Stimmung, Interessen-/Freudverlust und verminderter Antrieb; häufig zusätzlich Müdigkeit, Konzentrations-, Schlaf- oder Appetitprobleme.","Eine Depression beeinflusst Stimmung, Energie, Denken und Alltag. Bei einer leichten Episode bestehen Beschwerden, Alltagsaufgaben sind meist noch teilweise möglich."),
          "F32.1":("Mittelgradige depressive Episode","Gedrückte Stimmung, Interessenverlust, Antriebsmangel; oft Erschöpfung, Konzentrationsprobleme, Schuld-/Wertlosigkeitsgefühle sowie Schlaf-/Appetitveränderungen.","Mehrere depressive Beschwerden sind deutlich ausgeprägt und erschweren Alltag, Arbeit und Beziehungen."),
          "F32.2":("Schwere depressive Episode","Starke Niedergeschlagenheit, Interessenverlust und Antriebsmangel; häufig ausgeprägte Erschöpfung, Schuld-/Wertlosigkeitsgefühle, Schlaf-/Appetitstörungen und mögliche Suizidgedanken.","Die Beschwerden sind stark und beeinträchtigen den Alltag erheblich. Suizidgedanken erfordern eine unmittelbare fachliche Risikoabklärung."),
          "F33.0":("Rezidivierende depressive Störung – leichte Episode","Aktuell leichte depressive Symptome bei bereits früher aufgetretenen depressiven Episoden.","Depressive Phasen sind wiederholt aufgetreten; aktuell ist die Symptomatik leicht ausgeprägt."),
          "F33.1":("Rezidivierende depressive Störung – mittelgradige Episode","Aktuell mittelgradige depressive Symptome bei wiederholten depressiven Episoden.","Es gab bereits frühere depressive Phasen; aktuell beeinträchtigen mehrere Symptome den Alltag deutlich."),
          "F40.0":("Agoraphobie","Angst und Vermeidung z. B. bei Menschenmengen, öffentlichen Orten, Reisen oder Situationen, aus denen Flucht schwierig erscheint.","Bestimmte Orte oder Situationen lösen starke Angst aus und werden deshalb gemieden oder nur mit großer Anspannung bewältigt."),
          "F40.1":("Soziale Phobien","Deutliche Angst vor prüfender Betrachtung, negativer Bewertung oder peinlichem Verhalten in sozialen Situationen.","Soziale Situationen können starke Angst auslösen, besonders wenn man sich beobachtet oder bewertet fühlt."),
          "F41.0":("Panikstörung","Wiederkehrende Panikattacken mit z. B. Herzrasen, Atemnot, Enge, Zittern, Schwindel und Angst vor Kontrollverlust oder Tod.","Plötzlich auftretende starke Angst erreicht rasch einen Höhepunkt und geht oft mit intensiven Körperreaktionen einher."),
          "F41.1":("Generalisierte Angststörung","Anhaltende schwer kontrollierbare Sorgen, innere Unruhe, Anspannung, Reizbarkeit sowie Konzentrations- und Schlafprobleme.","Sorgen und Anspannung betreffen viele Lebensbereiche und lassen sich nur schwer abschalten."),
          "F43.0":("Akute Belastungsreaktion","Unmittelbare psychische Reaktion auf außergewöhnliche Belastung; möglich sind Benommenheit, Unruhe, Angst, Rückzug und vegetative Symptome.","Nach einer extremen Belastung kann die Psyche kurzfristig mit starker Überforderung reagieren."),
          "F43.1":("Posttraumatische Belastungsstörung","Wiedererleben/Intrusionen, Albträume, Vermeidung und erhöhte Wachsamkeit; oft Schlaf-, Konzentrations- und Schreckhaftigkeitsprobleme.","Nach traumatischen Erfahrungen können Erinnerungen ungewollt wiederkehren; Betroffene vermeiden Auslöser und bleiben häufig innerlich in Alarmbereitschaft."),
          "F43.2":("Anpassungsstörungen","Niedergeschlagenheit, Angst/Sorge, Überforderung und Beeinträchtigung nach belastender Lebensveränderung.","Eine konkrete Belastung oder Veränderung führt zu psychischen Beschwerden, mit denen die Person aktuell nur schwer zurechtkommt."),
          "F45.0":("Somatisierungsstörung","Wiederkehrende vielfältige körperliche Beschwerden mit erheblicher Belastung und wiederholter medizinischer Inanspruchnahme.","Körperliche Beschwerden sind real belastend; psychische und körperliche Faktoren werden gemeinsam betrachtet."),
          "F50.0":("Anorexia nervosa","Deutlich eingeschränkte Nahrungsaufnahme, niedriges Körpergewicht, ausgeprägte Angst vor Gewichtszunahme und verzerrte Körperwahrnehmung.","Essen, Gewicht und Körperbild bestimmen zunehmend Denken und Verhalten; körperliche Risiken müssen ärztlich mitbeurteilt werden."),
          "F50.2":("Bulimia nervosa","Wiederkehrende Essanfälle mit Kontrollverlust und kompensatorischem Verhalten, starke Beschäftigung mit Gewicht und Figur.","Essanfälle und anschließende Gegenmaßnahmen bilden einen belastenden Kreislauf; medizinische Risiken müssen berücksichtigt werden."),
          "F51.0":("Nichtorganische Insomnie","Ein-/Durchschlafprobleme, frühes Erwachen oder nicht erholsamer Schlaf mit Beeinträchtigung am Tag.","Schlaf gelingt über längere Zeit nicht ausreichend, obwohl Gelegenheit zum Schlafen besteht."),
          "F60.3":("Emotional instabile Persönlichkeitsstörung","Ausgeprägte Schwierigkeiten bei Emotionsregulation und Impulskontrolle; je nach Ausprägung instabile Beziehungen/Selbstbild und Selbstschädigung möglich.","Gefühle können sehr intensiv und schnell wechselnd erlebt werden; Impulse und Beziehungen können schwer zu regulieren sein."),
          "F90.0":("Aktivitäts- und Aufmerksamkeitsstörung","Unaufmerksamkeit, Ablenkbarkeit, Organisationsprobleme, Impulsivität und ausgeprägte Aktivitäts-/Unruhesymptome.","Aufmerksamkeit, Impulssteuerung und Aktivitätsregulation sind überdauernd erschwert und beeinträchtigen mehrere Lebensbereiche.")
        }
        psychopharmaka_info={
          "SSRI – z. B. Sertralin, Escitalopram":("Antidepressiva","Depressionen und verschiedene Angststörungen.","Einfach: Sie verändern die Verfügbarkeit des Botenstoffs Serotonin. Die gewünschte Wirkung entwickelt sich meist nicht sofort.","Fachlich: selektive Hemmung des Serotonin-Transporters (SERT); klinische Wirkung typischerweise verzögert.","Mögliche Beschwerden u. a. Übelkeit, Unruhe, Schlaf- oder Sexualfunktionsstörungen. Absetzen und Wechselwirkungen ärztlich begleiten."),
          "SNRI – z. B. Venlafaxin, Duloxetin":("Antidepressiva","Depressionen; je nach Wirkstoff auch Angststörungen bzw. bestimmte Schmerzsyndrome.","Einfach: Sie beeinflussen vor allem Serotonin und Noradrenalin und können Stimmung und Antrieb stabilisieren.","Fachlich: Hemmung der Wiederaufnahme von Serotonin und Noradrenalin über SERT/NET.","Mögliche Beschwerden u. a. Übelkeit, Unruhe, Schlafprobleme; Blutdruck kann relevant sein. Nicht abrupt ohne ärztliche Rücksprache absetzen."),
          "Mirtazapin":("Antidepressivum","Depressive Störungen; sedierende Wirkung kann klinisch mitberücksichtigt werden.","Einfach: Es beeinflusst mehrere Botenstoffsysteme und kann neben der Stimmung auch Schlaf und Appetit beeinflussen.","Fachlich: u. a. alpha-2-antagonistische sowie serotonerge und histaminerge Rezeptorwirkungen.","Häufig Müdigkeit/Sedierung und Gewichtszunahme/Appetitsteigerung; individuelle Risiken ärztlich prüfen."),
          "Benzodiazepine – z. B. Lorazepam":("Anxiolytika/Sedativa","Kurzfristige Behandlung bestimmter akuter Angst-, Unruhe- oder Krisenzustände nach ärztlicher Indikation.","Einfach: Sie verstärken ein beruhigendes Signal im Gehirn und können Angst und Anspannung rasch dämpfen.","Fachlich: positive allosterische Modulation am GABA-A-Rezeptor.","Sedierung, Reaktionsbeeinträchtigung sowie Toleranz- und Abhängigkeitsrisiko; Kombinationen mit anderen dämpfenden Substanzen können gefährlich sein."),
          "Atypische Antipsychotika – z. B. Quetiapin, Risperidon":("Antipsychotika","Je nach Wirkstoff u. a. psychotische und bipolare Störungen; Einsatzgebiete unterscheiden sich.","Einfach: Sie beeinflussen Botenstoffsysteme, die Wahrnehmung, Denken, Stimmung und Erregung mitsteuern.","Fachlich: je nach Wirkstoff unterschiedliche dopaminerge/serotonerge Rezeptorprofile.","Mögliche metabolische, neurologische, hormonelle und sedierende Nebenwirkungen; ärztliche Verlaufskontrollen sind wichtig."),
          "Stimulanzien – z. B. Methylphenidat":("ADHS-Medikation","ADHS nach entsprechender ärztlicher Diagnostik und Indikation.","Einfach: Sie können helfen, Aufmerksamkeit und Impulssteuerung zu verbessern.","Fachlich: Methylphenidat hemmt vor allem Dopamin- und Noradrenalin-Wiederaufnahme.","Appetit, Schlaf, Puls und Blutdruck können beeinflusst werden; Verordnung und Verlaufskontrolle gehören in ärztliche Hand.")
        }
        codebox=QFrame(); codebox.setObjectName("formCard"); cg=QHBoxLayout(codebox); self.help_fcode=QComboBox(); self.help_fcode.setEditable(True); self.help_fcode.addItem("F-Code auswählen / suchen …");
        for code,name in fcodes.items(): self.help_fcode.addItem(f"{code} – {name}")
        cg.addWidget(QLabel("ICD-10-GM / F-Code")); cg.addWidget(self.help_fcode,1); v.addWidget(codebox)
        info_tabs=QTabWidget()
        self.icd_info_text=QTextEdit(); self.icd_info_text.setReadOnly(True); info_tabs.addTab(self.icd_info_text,"Krankheitsbild")
        medpage=QWidget(); medv=QVBoxLayout(medpage); self.med_pick=QComboBox(); self.med_pick.addItems(["Psychopharmakon auswählen …"]+list(psychopharmaka_info.keys())); self.med_info_text=QTextEdit(); self.med_info_text.setReadOnly(True); medv.addWidget(self.med_pick); medv.addWidget(self.med_info_text); info_tabs.addTab(medpage,"Psychopharmaka")
        info_tabs.setMinimumHeight(230); v.addWidget(info_tabs)
        def show_icd_info(text):
            code=text.split(" – ",1)[0].strip() if " – " in text else ""
            x=icd_info.get(code)
            if x: self.icd_info_text.setPlainText(f"{code} – {x[0]}\n\nEinfach erklärt\n{x[2]}\n\nHauptsymptome / Merkmale\n{x[1]}\n\nHinweis: Arbeitshilfe, keine automatische Diagnosestellung.")
            else: self.icd_info_text.setPlainText("F-Code auswählen.")
        def show_med_info(text):
            x=psychopharmaka_info.get(text)
            if x: self.med_info_text.setPlainText(f"{text}\nGruppe: {x[0]}\n\nTypische Einsatzgebiete\n{x[1]}\n\nWie wirkt es? – einfach erklärt\n{x[2]}\n\nWirkungsweise – fachlich\n{x[3]}\n\nWichtige Hinweise\n{x[4]}\n\nInformationshilfe – keine Verordnungs- oder Dosierungsempfehlung.")
            else: self.med_info_text.setPlainText("Psychopharmakon auswählen.")
        self.help_fcode.currentTextChanged.connect(show_icd_info); self.med_pick.currentTextChanged.connect(show_med_info); show_icd_info(self.help_fcode.currentText()); show_med_info(self.med_pick.currentText())
        row=QHBoxLayout(); self.help_topic=QComboBox(); self.help_topic.addItems(topics.keys()); row.addWidget(QLabel("Thema")); row.addWidget(self.help_topic,1)
        self.school_filter=QComboBox(); self.school_filter.addItems(["Alle Schulen","VT","TP","Systemisch","SIT","EFT"]); row.addWidget(QLabel("Ansatz")); row.addWidget(self.school_filter); v.addLayout(row)
        symptom_catalog={
          "PTBS / Trauma":["Intrusionen / belastende Erinnerungen","Albträume","Flashbacks / Wiedererleben","Vermeidung von Erinnerungen oder Situationen","Übermäßige Wachsamkeit","Schreckhaftigkeit","Reizbarkeit / Ärger","Schlafstörungen","Konzentrationsprobleme","Schuld- oder Schamgefühle","Emotionale Taubheit / Distanz","Sozialer Rückzug","Körperliche Stressreaktionen"],
          "Depressive Beschwerden":["Gedrückte Stimmung","Interessen- / Freudverlust","Antriebsmangel","Erschöpfung","Schlafstörungen","Konzentrationsprobleme","Vermindertes Selbstwertgefühl","Schuldgefühle","Appetitveränderung","Psychomotorische Unruhe / Hemmung","Suizidgedanken"],
          "Angst / Panik":["Plötzliche Angstspitzen","Herzklopfen / Herzrasen","Atemnot / Engegefühl","Schwindel","Zittern","Schwitzen","Angst vor Kontrollverlust","Angst zu sterben","Erwartungsangst","Vermeidungsverhalten","Sicherheitsverhalten"],
          "Schlafprobleme":["Einschlafprobleme","Durchschlafprobleme","Frühes Erwachen","Nicht erholsamer Schlaf","Nächtliches Grübeln","Tagesmüdigkeit","Unregelmäßiger Schlafrhythmus"],
          "ADHS / Aufmerksamkeit":["Unaufmerksamkeit","Leichte Ablenkbarkeit","Vergesslichkeit","Organisationsprobleme","Aufschieben","Impulsivität","Innere / motorische Unruhe","Probleme mit Zeitmanagement"],
          "Zwänge":["Aufdringliche Gedanken / Bilder / Impulse","Kontrollzwänge","Wasch- / Reinigungszwänge","Ordnungs- / Symmetriezwänge","Mentale Rituale","Rückversicherung","Vermeidung","Hoher Zeitaufwand"],
          "Stress / Überlastung":["Anspannung","Erschöpfung","Reizbarkeit","Konzentrationsprobleme","Schlafprobleme","Grübeln","Körperliche Stresssymptome","Gefühl von Kontrollverlust"],
          "Trauer / Verlust":["Intensive Traurigkeit","Sehnsucht","Gedankliche Beschäftigung mit Verlust","Schuldgefühle","Rückzug","Schlafprobleme","Funktionsbeeinträchtigung","Schwierigkeit, Alltag wieder aufzunehmen"],
          "Eifersucht / Vertrauen":["Misstrauen","Kontrollverhalten","Rückversicherung","Grübeln","Verlustangst","Konflikteskalation","Rückzug","Wut / Kränkung"],
          "Selbstwert / Selbstbewusstsein":["Selbstkritik","Scham","Versagensangst","Sozialer Vergleich","Unsicherheit","Schwierigkeit Grenzen zu setzen","Vermeidung","Starkes Bedürfnis nach Bestätigung"],
          "Paar – Kommunikation / Konflikte":["Häufige Eskalationen","Kritik / Vorwürfe","Rückzug / Schweigen","Gefühl nicht verstanden zu werden","Vertrauensverlust","Nähe-Distanz-Konflikte","Unterschiedliche Erwartungen","Wiederkehrende ungelöste Konflikte"],
          "Trennung / Beziehungskrise":["Akute Traurigkeit","Verlustangst","Grübeln","Wut / Kränkung","Schlafprobleme","Kontaktzwang / Rückversicherung","Unsicherheit über Entscheidung","Belastung gemeinsamer Kinder"],
          "Soziale Angst":["Angst vor Bewertung","Vermeidung sozialer Situationen","Erröten / Zittern / Schwitzen","Starkes Nachgrübeln","Sicherheitsverhalten","Angst zu sprechen","Blickkontakt vermeiden","Beeinträchtigung in Arbeit / Ausbildung"],
          "Somatische Beschwerden":["Schmerzen","Magen-Darm-Beschwerden","Herz-/Kreislaufempfindungen","Schwindel","Erschöpfung","Häufige Gesundheitsängste","Starke Körperbeobachtung","Wiederholte Rückversicherung"],
          "Essverhalten / Körperbild":["Restriktives Essen","Essanfälle","Kompensatorisches Verhalten","Starke Gewichtssorgen","Körperunzufriedenheit","Kontrollverlust beim Essen","Vermeidung gemeinsamer Mahlzeiten","Ausgeprägte Beschäftigung mit Figur / Gewicht"],
          "Generalisierte Angst / Sorgen":["Anhaltende Sorgen","Schwer kontrollierbares Grübeln","Innere Unruhe","Muskelanspannung","Reizbarkeit","Konzentrationsprobleme","Schlafprobleme","Erschöpfung"],
          "Agoraphobie":["Angst in Menschenmengen","Angst in öffentlichen Verkehrsmitteln","Angst allein außer Haus","Fluchtgedanken","Begleitperson erforderlich","Vermeidung","Panikähnliche Symptome","Einschränkung des Bewegungsradius"],
          "Spezifische Phobie":["Ausgeprägte Angst vor bestimmtem Reiz","Unmittelbare Angstreaktion","Vermeidung","Erwartungsangst","Körperliche Angstsymptome","Alltagsbeeinträchtigung"],
          "Anpassungsreaktion / Lebenskrise":["Belastendes Ereignis","Traurigkeit","Sorgen / Grübeln","Anspannung","Überforderung","Rückzug","Leistungseinbruch","Beziehungsbelastung"],
          "Ärger / Aggression":["Schnelle Gereiztheit","Wutausbrüche","Verbale Aggression","Impulsives Verhalten","Körperliche Anspannung","Nachträgliche Schuld","Konflikteskalation","Schwierige Impulskontrolle"],
          "Sucht / problematischer Konsum":["Starkes Verlangen","Kontrollverlust","Toleranzentwicklung","Entzugssymptome","Konsum trotz Folgen","Vernachlässigung anderer Bereiche","Verheimlichung","Rückfälle"],
          "Dissoziative Symptome":["Gefühl von Unwirklichkeit","Depersonalisation","Derealisation","Erinnerungslücken","Zeitverlust","Emotionale Taubheit","Automatisches Funktionieren","Stressbezogene Auslöser"],
          "Bipolare Symptomatik – Exploration":["Phasen deutlich gehobener Stimmung","Vermindertes Schlafbedürfnis","Gesteigerter Antrieb","Beschleunigtes Denken / Sprechen","Impulsives Geldausgeben / Risikoverhalten","Reizbarkeit","Depressive Phasen","Deutliche Funktionsveränderung"],
          "Psychotische Symptome – Exploration":["Ungewöhnliche Wahrnehmungen","Stimmenhören","Starke Überzeugungen mit Realitätskonflikt","Verwirrtheit","Desorganisiertes Denken","Misstrauen","Sozialer Rückzug","Funktionsverlust"],
          "Sexualität / Intimität":["Verminderte Lust","Leistungsdruck","Schmerzen / körperliche Beschwerden","Vermeidung von Nähe","Scham","Unterschiedliche Bedürfnisse","Kommunikationsprobleme","Belastung der Partnerschaft"]
        }
        # Verdachtsfall-Screening: eigene strukturierte Explorationsfragen, keine automatische Diagnose.
        # Paartherapie: zwei getrennte Perspektiven, gemeinsame Ziele und Sicherheitsklärung.
        couple=QFrame(); couple.setObjectName("formCard"); cv=QVBoxLayout(couple); cv.setContentsMargins(14,12,14,12); cv.setSpacing(10)
        ch=QHBoxLayout(); pair_title=QLabel("Paartherapie"); pair_title.setProperty("class","sectionTitle"); ch.addWidget(pair_title); ch.addStretch()
        self.couple_mode=QCheckBox("Paarmodus aktiv"); ch.addWidget(self.couple_mode); cv.addLayout(ch)
        pair_intro=QLabel("Getrennte Perspektiven nur bei Bedarf einblenden."); pair_intro.setObjectName("pageSub"); cv.addWidget(pair_intro)
        pair_body=QWidget(); pair_body.setVisible(False); pair_body_layout=QVBoxLayout(pair_body); pair_body_layout.setContentsMargins(0,0,0,0); pair_body_layout.setSpacing(10)
        names=QHBoxLayout(); self.partner_a=QLineEdit(); self.partner_a.setPlaceholderText("Partner A / Name"); self.partner_b=QLineEdit(); self.partner_b.setPlaceholderText("Partner B / Name"); names.addWidget(self.partner_a); names.addWidget(self.partner_b); pair_body_layout.addLayout(names)
        cols=QHBoxLayout(); self.partner_a_view=QTextEdit(); self.partner_a_view.setPlaceholderText("Sicht Partner A: Anliegen, Wünsche, Verletzungen, Ressourcen …"); self.partner_b_view=QTextEdit(); self.partner_b_view.setPlaceholderText("Sicht Partner B: Anliegen, Wünsche, Verletzungen, Ressourcen …"); self.partner_a_view.setMaximumHeight(115); self.partner_b_view.setMaximumHeight(115); cols.addWidget(self.partner_a_view); cols.addWidget(self.partner_b_view); pair_body_layout.addLayout(cols)
        ratings=QGridLayout(); ratings.addWidget(QLabel("Getrennte Einschätzung (0–10)"),0,0,1,5)
        self.couple_a_distress=QSpinBox(); self.couple_a_distress.setRange(0,10); self.couple_b_distress=QSpinBox(); self.couple_b_distress.setRange(0,10)
        self.couple_a_hope=QSpinBox(); self.couple_a_hope.setRange(0,10); self.couple_b_hope=QSpinBox(); self.couple_b_hope.setRange(0,10)
        ratings.addWidget(QLabel("Belastung"),1,0); ratings.addWidget(QLabel("A"),1,1); ratings.addWidget(self.couple_a_distress,1,2); ratings.addWidget(QLabel("B"),1,3); ratings.addWidget(self.couple_b_distress,1,4)
        ratings.addWidget(QLabel("Zuversicht"),2,0); ratings.addWidget(QLabel("A"),2,1); ratings.addWidget(self.couple_a_hope,2,2); ratings.addWidget(QLabel("B"),2,3); ratings.addWidget(self.couple_b_hope,2,4); pair_body_layout.addLayout(ratings)
        # Getrennte A/B-Paarfragebögen: dieselben Dimensionen unabhängig einschätzen.
        self.couple_question_rows=[]
        pair_questions=["Ich fühle mich von meinem Partner verstanden.","Wir können Konflikte beenden, ohne uns gegenseitig abzuwerten.","Ich kann Bedürfnisse und Grenzen offen ansprechen.","Ich erlebe ausreichend emotionale Nähe und Verbundenheit.","Vertrauen ist in unserer Beziehung vorhanden.","Wir finden nach Verletzungen wieder zueinander.","Wir können als Eltern / Bezugspersonen kooperieren, sofern relevant."]
        pq=QGridLayout(); pq.addWidget(QLabel("Getrennter Paarfragebogen · 0 = trifft gar nicht zu · 10 = trifft völlig zu"),0,0,1,3); pq.addWidget(QLabel("A"),1,1); pq.addWidget(QLabel("B"),1,2)
        for n,q in enumerate(pair_questions,2):
            a=QSpinBox(); b=QSpinBox(); a.setRange(-1,10); b.setRange(-1,10); a.setSpecialValueText("–"); b.setSpecialValueText("–"); a.setValue(-1); b.setValue(-1); self.couple_question_rows.append((q,a,b)); pq.addWidget(QLabel(q),n,0); pq.addWidget(a,n,1); pq.addWidget(b,n,2)
        pair_body_layout.addLayout(pq)
        self.couple_cycle=QLineEdit(); self.couple_cycle.setPlaceholderText("Wiederkehrender Interaktions-/Eskalationskreislauf …"); pair_body_layout.addWidget(self.couple_cycle)
        self.couple_goal=QLineEdit(); self.couple_goal.setPlaceholderText("Gemeinsames Ziel / Auftrag des Paares …"); pair_body_layout.addWidget(self.couple_goal)
        self.couple_resources=QLineEdit(); self.couple_resources.setPlaceholderText("Gemeinsame Ressourcen / positive Ausnahmen …"); pair_body_layout.addWidget(self.couple_resources)
        cr=QHBoxLayout(); self.couple_violence=QCheckBox("Hinweis auf Gewalt / Drohung / Zwang / Kontrolle"); self.couple_children=QCheckBox("Kinder / Elternebene betroffen"); cr.addWidget(self.couple_violence); cr.addWidget(self.couple_children); cr.addStretch(); pair_body_layout.addLayout(cr)
        couplehint=QLabel("Bei Gewalt, Zwang oder akuter Gefährdung: Sicherheit und getrennte Risikoabklärung vor üblichen Paarinterventionen priorisieren."); couplehint.setWordWrap(True); pair_body_layout.addWidget(couplehint); cv.addWidget(pair_body); self.couple_mode.toggled.connect(pair_body.setVisible); v.addWidget(couple)
        screening_catalog={
          "Depressive Beschwerden":["Besteht seit mindestens zwei Wochen an den meisten Tagen eine deutlich gedrückte Stimmung?","Besteht deutlich weniger Interesse oder Freude an sonst wichtigen Aktivitäten?","Sind Antrieb oder Energie deutlich vermindert?","Bestehen Schlaf-, Appetit- oder Konzentrationsveränderungen?","Bestehen Hoffnungslosigkeit, starke Schuldgefühle oder Gedanken, nicht mehr leben zu wollen?"],
          "Angst / Panik":["Treten wiederholt plötzlich starke Angstspitzen auf?","Bestehen dabei deutliche körperliche Symptome wie Herzrasen, Atemnot, Zittern oder Schwindel?","Besteht anhaltende Sorge vor weiteren Anfällen?","Werden Situationen aus Angst vermieden?","Wie stark beeinträchtigt dies Alltag, Arbeit oder Beziehungen?"],
          "PTBS / Trauma":["Gab es ein stark belastendes oder traumatisches Ereignis?","Treten ungewollte Erinnerungen, Albträume oder Wiedererleben auf?","Werden Erinnerungen, Gedanken, Gefühle oder Situationen vermieden?","Bestehen anhaltende Übererregung, Schreckhaftigkeit oder Schlafprobleme?","Beeinträchtigen die Beschwerden Alltag oder Beziehungen deutlich?"],
          "ADHS / Aufmerksamkeit":["Bestanden Aufmerksamkeits- oder Organisationsprobleme bereits in Kindheit/Jugend?","Treten die Schwierigkeiten in mehr als einem Lebensbereich auf?","Bestehen deutliche Ablenkbarkeit, Vergesslichkeit oder Probleme beim Abschließen von Aufgaben?","Bestehen Impulsivität oder ausgeprägte innere/motorische Unruhe?","Führen die Beschwerden zu relevanter Beeinträchtigung?"],
          "Zwänge":["Treten wiederholt aufdringliche Gedanken, Bilder oder Impulse auf?","Werden wiederholte Handlungen oder mentale Rituale ausgeführt, um Anspannung zu reduzieren?","Werden die Gedanken oder Rituale als schwer kontrollierbar erlebt?","Beanspruchen sie viel Zeit?","Führen sie zu Vermeidung oder deutlicher Alltagsbeeinträchtigung?"],
          "Schlafprobleme":["Bestehen Ein-, Durchschlafprobleme oder frühes Erwachen?","Treten die Probleme wiederholt auf?","Besteht tagsüber Müdigkeit oder Leistungseinbuße?","Gibt es erkennbare körperliche, medikamentöse oder substanzbezogene Ursachen?","Welche Schlafgewohnheiten und Belastungsfaktoren könnten die Beschwerden beeinflussen?"],
          "Soziale Angst":["Besteht ausgeprägte Angst vor negativer Bewertung durch andere?","Werden soziale oder Leistungssituationen vermieden oder nur unter starker Angst ausgehalten?","Besteht ausgeprägtes Nachgrübeln nach sozialen Situationen?","Werden Sicherheitsstrategien eingesetzt?","Entsteht dadurch eine relevante Einschränkung?"],
          "Somatische Beschwerden":["Bestehen wiederkehrende oder anhaltende körperliche Beschwerden?","Wie stark sind Sorgen und gedankliche Beschäftigung mit den Beschwerden?","Wie häufig wird Rückversicherung oder medizinische Abklärung gesucht?","Welche Belastungs- oder Beziehungssituationen verändern die Beschwerden?","Welche medizinischen Befunde bzw. Ausschlussdiagnostik liegen vor?"],
          "Paar – Kommunikation / Konflikte":["Wie häufig eskalieren Konflikte und wie enden sie typischerweise?","Gibt es ein wiederkehrendes Muster aus Kritik, Verteidigung, Rückzug oder Schweigen?","Wie erleben beide Partner Nähe, Distanz, Vertrauen und Verbindlichkeit?","Welche gemeinsamen Ressourcen und positiven Ausnahmen gibt es?","Gibt es Angst, Drohungen, Kontrolle, Zwang oder körperliche/sexualisierte Gewalt?"],
          "Trennung / Beziehungskrise":["Wollen beide an der Beziehung arbeiten oder steht Klärung/Trennung im Vordergrund?","Welche Ereignisse haben die Krise verschärft?","Wie werden Vertrauen, Bindung und Verletzungen von beiden erlebt?","Sind Kinder betroffen und wie wird die Elternebene geschützt?","Gibt es Sicherheitsrisiken, Gewalt, Stalking oder Zwang?"],
          "Essverhalten / Körperbild":["Besteht deutliche Einschränkung der Nahrungsaufnahme oder starke Angst vor Gewichtszunahme?","Treten Essanfälle mit Kontrollverlust auf?","Gibt es Erbrechen, exzessive Bewegung oder andere kompensatorische Verhaltensweisen?","Wie stark bestimmen Gewicht und Figur den Selbstwert?","Bestehen körperliche Warnzeichen oder rasche Gewichtsveränderungen?"],
          "Sucht / problematischer Konsum":["Welche Substanz bzw. welches Verhalten steht im Vordergrund?","Besteht Kontrollverlust über Beginn, Menge oder Ende?","Wird trotz körperlicher, psychischer oder sozialer Folgen fortgesetzt?","Bestehen Toleranz, Entzug oder starkes Verlangen?","Gab es riskante Situationen, Mischkonsum oder frühere Entzüge?"],
          "Bipolare Symptomatik – Exploration":["Gab es klar abgrenzbare Phasen ungewöhnlich gehobener oder stark gereizter Stimmung?","War das Schlafbedürfnis deutlich vermindert, ohne sich müde zu fühlen?","Bestanden deutlich gesteigerter Antrieb, Rededrang oder beschleunigtes Denken?","Kam es zu ungewöhnlichem Risiko-, Kauf- oder Sexualverhalten?","Wie lange dauerten diese Phasen und welche Folgen hatten sie?"],
          "Psychotische Symptome – Exploration":["Bestehen aktuell Wahrnehmungen, die andere nicht teilen?","Gibt es Überzeugungen, die zu deutlichen Konflikten mit der gemeinsamen Realität führen?","Bestehen Verwirrtheit oder deutlich desorganisiertes Denken/Verhalten?","Wie sind Orientierung, Selbstversorgung und aktuelle Sicherheit?","Bestehen Substanzkonsum, Medikamentenänderungen oder körperliche Auffälligkeiten?"]
        }
        intervention_library={
          "Depressive Beschwerden":{"VT":["Verhaltensaktivierung und Tagesstruktur schrittweise planen.","Automatische negative Gedanken und Rückzugskreisläufe prüfen."],"TP":["Verlust-, Selbstwert- und Beziehungskonflikte sowie Affekte explorieren."],"Systemisch":["Ressourcen, hilfreiche Beziehungen und Ausnahmen aktivieren."],"SIT":["Problemaufrechterhaltende Interaktionen erfassen und konkrete nächste Schritte vereinbaren."]},
          "Angst / Panik":{"VT":["Panik-/Angstkreislauf und Sicherheitsverhalten transparent machen.","Expositionsschritte nach Indikations- und Belastungsprüfung planen."],"TP":["Bedeutung der Angst, Konflikte und Beziehungserwartungen explorieren."],"Systemisch":["Kontext, Rückversicherung und Reaktionen wichtiger Bezugspersonen einbeziehen."],"SIT":["Auslöser, Muster und wirksame Bewältigung in konkrete Alltagsschritte übersetzen."]},
          "Soziale Angst":{"VT":["Bewertungsängste, Sicherheitsverhalten und Vermeidung analysieren.","Verhaltensexperimente schrittweise planen."],"TP":["Scham, Selbstwert und Beziehungserwartungen explorieren."],"Systemisch":["Soziale Kontexte, Rollen und unterstützende Rückmeldungen nutzen."],"SIT":["Konkrete soziale Situationen analysieren und neue Handlungsoptionen erproben."]},
          "PTBS / Trauma":{"VT":["Stabilisierung, Psychoedukation und traumabezogene Vermeidung erfassen.","Traumafokussierte Verfahren nur fachgerecht und bei ausreichender Stabilität einsetzen."],"TP":["Affekte, Ohnmacht, Schuld/Scham und Beziehungsmuster behutsam bearbeiten."],"Systemisch":["Sicherheit, Ressourcen und tragfähige Beziehungen im Umfeld stärken."],"SIT":["Stabilität priorisieren, Muster erfassen und handlungsorientierte sichere Schritte entwickeln."]},
          "ADHS / Aufmerksamkeit":{"VT":["Externe Struktur, Aufgabenzerlegung, Zeitmanagement und Verstärker nutzen."],"TP":["Selbstwert, Beschämung und wiederkehrende Scheiternserfahrungen explorieren."],"Systemisch":["Umgebung und Anforderungen so verändern, dass hilfreiches Verhalten leichter wird."],"SIT":["Alltagsprobleme konkretisieren, funktionierende Ausnahmen nutzen und umsetzbare Routinen entwickeln."]},
          "Zwänge":{"VT":["Zwangskreislauf erklären und Exposition mit Reaktionsmanagement fachgerecht planen."],"TP":["Kontrolle, Verantwortung, Schuld und aggressive/ambivalente Affekte explorieren."],"Systemisch":["Rückversicherung und Einbindung von Angehörigen in Rituale betrachten."],"SIT":["Ritualauslöser und Interaktionsmuster erfassen und alternative Handlungen entwickeln."]},
          "Schlafprobleme":{"VT":["Schlafverhalten, Bettzeiten, Wachzeiten und schlafbezogene Bewertungen erfassen.","Evidenzbasierte verhaltensorientierte Schlafmaßnahmen passend zur Situation planen."],"TP":["Nächtliche Affekte, Konflikte und Grübelthemen explorieren."],"Systemisch":["Alltagsrhythmus, Familie/Partnerschaft und Umgebungsfaktoren einbeziehen."],"SIT":["Konkrete Schlafmuster und beeinflussbare Abend-/Morgenroutinen bearbeiten."]},
          "Sucht / problematischer Konsum":{"VT":["Auslöser, Craving, Konsequenzen und Rückfallketten analysieren.","Motivation und konkrete Alternativ-/Notfallstrategien entwickeln."],"TP":["Affektregulation, Beziehungsmuster und Funktion des Konsums explorieren."],"Systemisch":["Unterstützungssystem, Grenzen und konsumfördernde Interaktionen betrachten."],"SIT":["Funktion des Konsums und konkrete Veränderungsschritte im Alltag bearbeiten."]},
          "Paar – Kommunikation / Konflikte":{"VT":["Konfliktsequenzen analysieren, Kommunikationsfertigkeiten und positive gemeinsame Aktivitäten fördern."],"TP":["Bindungswünsche, Verletzungen und wiederkehrende unbewusste Beziehungserwartungen explorieren."],"Systemisch":["Zirkuläre Muster, Perspektivwechsel, Ressourcen und Ausnahmen sichtbar machen."],"SIT":["Interaktionskreisläufe konkret erfassen und gemeinsam überprüfbare Veränderungen vereinbaren."],"EFT":["Primäre Emotionen und Bindungsbedürfnisse unter Kritik, Rückzug oder Ärger zugänglich machen."]},
          "Trennung / Beziehungskrise":{"VT":["Entscheidungsdruck strukturieren und konkrete hilfreiche Verhaltensschritte planen."],"TP":["Ambivalenzen, Verlustangst, Kränkung und Bindungsmuster explorieren."],"Systemisch":["Paar- und Elternebene unterscheiden und Folgen möglicher Entscheidungen multiperspektivisch betrachten."],"SIT":["Auftrag klären und nächste Schritte für Beziehungsklärung oder respektvolle Trennung entwickeln."],"EFT":["Verletzlichkeit, Bindungsangst und unerfüllte emotionale Bedürfnisse bearbeiten."]}
        }
        clinical_map={
          "Depressive Beschwerden":{"codes":["F32.- Depressive Episode","F33.- Rezidivierende depressive Störung"],"diff":["Bipolare Symptomatik / frühere Phasen gehobener Stimmung?","Substanz-/Medikamenteneinfluss?","Somatische Ursachen, Trauer oder Anpassungsreaktion?"]},
          "Angst / Panik":{"codes":["F41.0 Panikstörung","F41.1 Generalisierte Angststörung"],"diff":["Körperliche Ursachen der Symptome ausreichend abgeklärt?","Substanz-/Medikamenteneinfluss?","Agoraphobie, soziale oder spezifische Phobie im Vordergrund?"]},
          "Soziale Angst":{"codes":["F40.1 Soziale Phobien"],"diff":["Angst primär vor Bewertung oder breitere soziale/kommunikative Problematik?","Depression, Autismus-Spektrum oder traumabezogene Vermeidung mitprüfen."]},
          "PTBS / Trauma":{"codes":["F43.1 Posttraumatische Belastungsstörung","F43.2 Anpassungsstörungen"],"diff":["Art und Zeitpunkt des Ereignisses klären.","Dissoziation, Depression, Angst und Substanzkonsum mitprüfen.","Aktuelle Sicherheit und Stabilität vor traumafokussierter Arbeit prüfen."]},
          "ADHS / Aufmerksamkeit":{"codes":["F90.0 Aktivitäts- und Aufmerksamkeitsstörung"],"diff":["Beginn in Kindheit/Jugend und mehrere Lebensbereiche prüfen.","Schlaf, Depression, Angst, Trauma, Substanzen und körperliche Ursachen mitprüfen."]},
          "Zwänge":{"codes":["F42.- Zwangsstörung"],"diff":["Zwangsgedanken/-handlungen von Sorgen, Psychose und zwanghafter Persönlichkeit abgrenzen.","Zeitaufwand, Einsicht, Vermeidung und Einbezug Angehöriger klären."]},
          "Schlafprobleme":{"codes":["F51.0 Nichtorganische Insomnie"],"diff":["Organische Schlafstörung, Medikamente/Substanzen, Schmerz und Schichtarbeit prüfen.","Depression, Angst, Trauma oder manische Symptomatik mitprüfen."]},
          "Somatische Beschwerden":{"codes":["F45.- Somatoforme Störungen"],"diff":["Medizinische Abklärung und Warnzeichen berücksichtigen.","Angst, Depression, Stress, Medikamente und körperliche Erkrankungen mitprüfen."]},
          "Agoraphobie":{"codes":["F40.0 Agoraphobie"],"diff":["Panikattacken mit oder ohne Agoraphobie klären.","Körperliche Ursachen, Substanzen und andere Angststörungen mitprüfen."]},
          "Spezifische Phobie":{"codes":["F40.2 Spezifische (isolierte) Phobien"],"diff":["Konkreten Auslöser, Vermeidung und Beeinträchtigung klären.","Traumabezogene Reaktion, Zwang oder andere Angststörung abgrenzen."]},
          "Anpassungsreaktion / Lebenskrise":{"codes":["F43.2 Anpassungsstörungen"],"diff":["Zeitlicher Zusammenhang mit identifizierbarer Belastung klären.","Depressive Episode, Angststörung, Trauerreaktion und PTBS mitprüfen."]},
          "Essverhalten / Körperbild":{"codes":["F50.- Essstörungen"],"diff":["Gewichtsentwicklung, Restriktion, Essanfälle und kompensatorisches Verhalten klären.","Körperliche Risiken und medizinische Mitbehandlung berücksichtigen."]},
          "Sucht / problematischer Konsum":{"codes":["F10–F19 Psychische und Verhaltensstörungen durch psychotrope Substanzen"],"diff":["Substanz, Menge, Häufigkeit, Kontrollverlust und Folgen klären.","Entzugsrisiko, Mischkonsum, körperliche Risiken und komorbide Störungen prüfen."]},
          "Dissoziative Symptome":{"codes":["F44.- Dissoziative Störungen"],"diff":["Neurologische/körperliche Ursachen und Substanzeinflüsse berücksichtigen.","Trauma, Panik, Psychose und andere Bewusstseinsveränderungen abgrenzen."]},
          "Bipolare Symptomatik – Exploration":{"codes":["F31.- Bipolare affektive Störung"],"diff":["Dauer und Ausmaß gehobener/gereizter Stimmung und verminderten Schlafbedarfs klären.","Substanzen, Medikamente, ADHS und andere Ursachen erhöhter Aktivität mitprüfen."]},
          "Psychotische Symptome – Exploration":{"codes":["F20–F29 Schizophrenie, schizotype und wahnhafte Störungen"],"diff":["Akuität, Realitätsprüfung, Orientierung und Sicherheitslage unmittelbar klären.","Substanzen, Medikamente, organische Ursachen und affektive Störungen mitprüfen."]},
          "Trauer / Verlust":{"codes":["Keine schematische F-Code-Zuordnung"],"diff":["Normale Trauer nicht vorschnell pathologisieren.","Dauer, Funktionsbeeinträchtigung, Depression, Trauma und Sicherheitsaspekte individuell prüfen."]}
        }
        clinicalbox=QFrame(); clinicalbox.setObjectName("formCard"); clv=QVBoxLayout(clinicalbox); clv.addWidget(QLabel("Verdachtsfall → F-Code-Hinweise → Differenzialfragen"))
        self.clinical_hint=QTextEdit(); self.clinical_hint.setReadOnly(True); self.clinical_hint.setMaximumHeight(155); clv.addWidget(self.clinical_hint); v.addWidget(clinicalbox)
        def update_clinical_hint():
            m=clinical_map.get(self.help_topic.currentText())
            if not m: self.clinical_hint.setPlainText("Für dieses Thema steht keine automatische F-Code-Zuordnung bereit. Klinische Exploration und eigenständige diagnostische Entscheidung erforderlich."); return
            txt=["Mögliche Dokumentations-/Prüfrichtung (keine Diagnose):"]+["• "+x for x in m["codes"]]+["","Differenzialfragen:"]+["• "+x for x in m["diff"]]
            self.clinical_hint.setPlainText("\n".join(txt))
        screenbox=QFrame(); screenbox.setObjectName("formCard"); scv=QVBoxLayout(screenbox); sch=QHBoxLayout(); sch.addWidget(QLabel("Fragebogen bei Verdachtsfall")); sch.addStretch(); self.screening_btn=QPushButton("Fragebogen zum Thema laden"); sch.addWidget(self.screening_btn); scv.addLayout(sch)
        self.screening_checks=[]; self.screening_area=QWidget(); self.screening_layout=QVBoxLayout(self.screening_area); self.screening_layout.setContentsMargins(0,0,0,0); scv.addWidget(self.screening_area)
        screenhint=QLabel("Strukturierte Exploration als Arbeitshilfe. Das Ergebnis ist kein Testwert und keine automatische Diagnose."); screenhint.setWordWrap(True); scv.addWidget(screenhint); v.addWidget(screenbox)
        def load_screening():
            while self.screening_layout.count():
                it=self.screening_layout.takeAt(0); w=it.widget()
                if w: w.deleteLater()
            self.screening_checks=[]
            questions=screening_catalog.get(self.help_topic.currentText(),[])
            if not questions:
                questions=["Bestehen die Beschwerden wiederholt oder anhaltend?","Führen sie zu relevanter Beeinträchtigung im Alltag?","Welche Auslöser, Schutzfaktoren und Differenzialerklärungen sind zu prüfen?"]
            for q in questions:
                cb=QCheckBox(q); cb.setToolTip(q); cb.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred); self.screening_checks.append(cb); self.screening_layout.addWidget(cb)
                cb.toggled.connect(lambda _:render())
            render()
        self.screening_btn.clicked.connect(load_screening)
        symptom_box=QFrame(); symptom_box.setObjectName("formCard"); symptom_box.setMinimumWidth(0); sb=QVBoxLayout(symptom_box); sh=QHBoxLayout(); sh.addWidget(QLabel("Symptomabfrage – Mehrfachauswahl")); sh.addStretch(); clear_sym=QPushButton("Auswahl löschen"); sh.addWidget(clear_sym); sb.addLayout(sh)
        self.symptom_list=QListWidget(); self.symptom_list.setSelectionMode(QListWidget.MultiSelection); self.symptom_list.setMinimumHeight(105); self.symptom_list.setMaximumHeight(170); self.symptom_list.setAlternatingRowColors(True); self.symptom_list.setToolTip("Mehrere Symptome mit Strg/Klick oder durch Ziehen auswählen. Doppelklick übernimmt ein einzelnes Symptom direkt in die Therapienotiz."); sb.addWidget(self.symptom_list)
        sr=QHBoxLayout(); self.sym_custom=QLineEdit(); self.sym_custom.setPlaceholderText("Weiteres Symptom ergänzen …"); add_sym=QPushButton("＋ Symptom"); transfer_sym=QPushButton("✓ Auswahl in Therapienotiz übernehmen"); transfer_all=QPushButton("↗ Zusammenfassung übernehmen"); sr.addWidget(self.sym_custom,1); sr.addWidget(add_sym); sr.addWidget(transfer_sym); sr.addWidget(transfer_all); sb.addLayout(sr)
        def add_custom_symptom():
            t=self.sym_custom.text().strip()
            if t: self.symptom_list.addItem(t); self.symptom_list.item(self.symptom_list.count()-1).setSelected(True); self.sym_custom.clear()
        add_sym.clicked.connect(add_custom_symptom); self.sym_custom.returnPressed.connect(add_custom_symptom)
        def transfer_selected_symptoms():
            selected=[x.text() for x in self.symptom_list.selectedItems()]
            if not selected: return QMessageBox.information(self,"Symptome","Bitte mindestens ein Symptom auswählen.")
            code=self.help_fcode.currentText()
            block=("Symptome"+((" – "+code) if " – " in code else "")+":\n"+"\n".join("• "+x for x in selected))
            if hasattr(self,"notes"):
                existing=self.notes.toPlainText().rstrip(); self.notes.setPlainText((existing+"\n\n" if existing else "")+block)
                QMessageBox.information(self,"Therapienotiz","Die ausgewählten Symptome wurden in die Therapienotiz übernommen.")
        transfer_sym.clicked.connect(transfer_selected_symptoms)
        def transfer_assistant_summary():
            if not hasattr(self,"notes") or not hasattr(self,"help_text"): return
            summary=self.help_text.toPlainText().strip()
            if not summary: return QMessageBox.information(self,"Sitzungsassistent","Noch keine Zusammenfassung vorhanden.")
            existing=self.notes.toPlainText().rstrip()
            self.notes.setPlainText((existing+"\n\n" if existing else "")+"--- Sitzungsassistent ---\n"+summary)
            self.notes.moveCursor(self.notes.textCursor().End)
            QMessageBox.information(self,"Therapienotiz","Die Zusammenfassung wurde an die Therapienotiz angehängt.")
        transfer_all.clicked.connect(transfer_assistant_summary); v.addWidget(symptom_box)
        def load_symptoms():
            self.symptom_list.clear(); vals=symptom_catalog.get(self.help_topic.currentText(),[])
            if not vals: vals=["Aktuelle Belastung","Beeinträchtigung im Alltag","Schlaf / Erholung","Körperliche Beschwerden","Rückzug / Vermeidung","Beziehungsbelastung","Ressourcen / Schutzfaktoren"]
            for s in vals:
                item=QListWidgetItem(s); item.setToolTip("Auswählen und anschließend in die Therapienotiz übernehmen"); self.symptom_list.addItem(item)
            self.symptom_list.scrollToTop()
        clear_sym.clicked.connect(self.symptom_list.clearSelection)
        # F-Code steuert Thema, Symptome und Fragen automatisch.
        fcode_topic={"F32.0":"Depressive Beschwerden","F32.1":"Depressive Beschwerden","F32.2":"Depressive Beschwerden","F33.0":"Depressive Beschwerden","F33.1":"Depressive Beschwerden","F40.0":"Agoraphobie","F40.1":"Soziale Angst","F41.0":"Angst / Panik","F41.1":"Angst / Panik","F43.0":"Anpassungsreaktion / Lebenskrise","F43.1":"PTBS / Trauma","F43.2":"Anpassungsreaktion / Lebenskrise","F45.0":"Somatische Beschwerden","F50.0":"Essverhalten / Körperbild","F50.2":"Essverhalten / Körperbild","F51.0":"Schlafprobleme","F60.3":"Stress / Überlastung","F90.0":"ADHS / Aufmerksamkeit"}
        def apply_fcode_context(text):
            code=text.split(" – ",1)[0].strip()
            topic=fcode_topic.get(code)
            if topic:
                idx=self.help_topic.findText(topic)
                if idx>=0 and idx!=self.help_topic.currentIndex():
                    self.help_topic.setCurrentIndex(idx)
                else:
                    load_symptoms()
            else:
                load_symptoms()
            load_screening(); render()
        self.help_topic.currentTextChanged.connect(lambda _: (load_symptoms(), load_screening(), render()))
        self.help_fcode.currentTextChanged.connect(apply_fcode_context)
        load_symptoms()
        severity=QFrame(); severity.setObjectName("formCard"); severity.setMinimumWidth(0); sf=QGridLayout(severity); sf.addWidget(QLabel("Vertiefung der Symptomabfrage"),0,0,1,4)
        self.sym_duration=QComboBox(); self.sym_duration.addItems(["Dauer nicht angegeben","< 2 Wochen","2–4 Wochen","1–3 Monate","3–6 Monate","> 6 Monate","> 1 Jahr"])
        self.sym_intensity=QComboBox(); self.sym_intensity.addItems(["Intensität nicht angegeben","Leicht","Mittel","Stark","Sehr stark"])
        self.sym_impairment=QComboBox(); self.sym_impairment.addItems(["Alltagsbeeinträchtigung nicht angegeben","Gering","Mittel","Deutlich","Sehr deutlich"])
        self.sym_frequency=QComboBox(); self.sym_frequency.addItems(["Häufigkeit nicht angegeben","Selten","Mehrmals monatlich","Mehrmals wöchentlich","Täglich","Mehrmals täglich"])
        sf.addWidget(QLabel("Dauer"),1,0); sf.addWidget(self.sym_duration,1,1); sf.addWidget(QLabel("Intensität"),1,2); sf.addWidget(self.sym_intensity,1,3)
        sf.addWidget(QLabel("Häufigkeit"),2,0); sf.addWidget(self.sym_frequency,2,1); sf.addWidget(QLabel("Alltag"),2,2); sf.addWidget(self.sym_impairment,2,3)
        self.sym_scale=QSpinBox(); self.sym_scale.setRange(0,10); self.sym_scale.setSuffix(" / 10"); self.sym_scale.setToolTip("Subjektive aktuelle Belastung: 0 = keine, 10 = maximal")
        sf.addWidget(QLabel("Aktuelle Belastung"),3,0); sf.addWidget(self.sym_scale,3,1)
        self.goal_scale=QSpinBox(); self.goal_scale.setRange(0,10); self.goal_scale.setSuffix(" / 10"); self.goal_scale.setToolTip("Subjektive Einschätzung: Wie nah ist die Person aktuell am gewünschten Zustand?")
        sf.addWidget(QLabel("Zielerreichung"),3,2); sf.addWidget(self.goal_scale,3,3); v.addWidget(severity)
        risk=QFrame(); risk.setObjectName("formCard"); risk.setMinimumWidth(0); rv=QVBoxLayout(risk); rv.addWidget(QLabel("Sicherheitsrelevante Hinweise"))
        self.risk_checks=[]
        for txt in ["Suizidgedanken","Selbstverletzung","Fremdgefährdung","Akute Desorientierung / psychotische Symptome","Kein aktueller Sicherheitshinweis"]:
            cb=QCheckBox(txt); self.risk_checks.append(cb); rv.addWidget(cb)
        self.help_goal=QLineEdit(); self.help_goal.setPlaceholderText("Sitzungsziel / Anliegen heute …"); rv.addWidget(self.help_goal)
        self.help_resources=QLineEdit(); self.help_resources.setPlaceholderText("Ressourcen / Schutzfaktoren …"); rv.addWidget(self.help_resources)
        self.help_trigger=QLineEdit(); self.help_trigger.setPlaceholderText("Auslöser / typische Situationen …"); rv.addWidget(self.help_trigger)
        self.help_maintain=QLineEdit(); self.help_maintain.setPlaceholderText("Aufrechterhaltende Faktoren / Muster …"); rv.addWidget(self.help_maintain)
        self.help_strength=QLineEdit(); self.help_strength.setPlaceholderText("Was funktioniert bereits / Ausnahmen …"); rv.addWidget(self.help_strength)
        self.help_support=QLineEdit(); self.help_support.setPlaceholderText("Unterstützungssystem / wichtige Bezugspersonen …"); rv.addWidget(self.help_support)
        self.help_next=QLineEdit(); self.help_next.setPlaceholderText("Vereinbarter nächster Schritt / Hausaufgabe …"); rv.addWidget(self.help_next)
        self.help_note=QLineEdit(); self.help_note.setPlaceholderText("Eigene Beobachtung / ergänzende Notiz …"); rv.addWidget(self.help_note); v.addWidget(risk)
        self.help_text=QTextEdit(); self.help_text.setReadOnly(True); self.help_text.setStyleSheet("font-size:17px;padding:10px"); v.addWidget(self.help_text,1)
        def render(selected_override=None):
            d=topics[self.help_topic.currentText()]; parts=["THEMA: "+self.help_topic.currentText(),"","GESPRÄCHSFRAGEN"]+["• "+x for x in d["Fragen"]]
            lib=intervention_library.get(self.help_topic.currentText(),{})
            if lib:
                chosen_school=self.school_filter.currentText() if hasattr(self,"school_filter") else "Alle Schulen"
                school_keys=["VT","TP","Systemisch","SIT","EFT"] if chosen_school=="Alle Schulen" else [chosen_school]
                for sk in school_keys:
                    if sk in lib: parts+=["","INTERVENTIONEN "+sk]+["• "+x for x in lib[sk]]
            # Basisimpulse nur ergänzen, wenn für das Thema keine spezifische
            # Interventionsbibliothek derselben Schule vorhanden ist. So entstehen
            # keine doppelten VT/TP/Systemisch/SIT-Blöcke in der Zusammenfassung.
            labels={"VT":"VERHALTENSTHERAPEUTISCHE IMPULSE","TP":"TIEFENPSYCHOLOGISCHE IMPULSE","Systemisch":"SYSTEMISCHE IMPULSE","SIT":"SYSTEMISCH-INTEGRATIVE / SIT-IMPULSE","EFT":"EMOTIONSFOKUSSIERTE IMPULSE"}
            chosen=self.school_filter.currentText() if hasattr(self,"school_filter") else "Alle Schulen"
            keys=["VT","TP","Systemisch","SIT","EFT"] if chosen=="Alle Schulen" else [chosen]
            for key in keys:
                if key in d and key not in lib: parts+=["",labels[key]]+["• "+x for x in d[key]]
            selected=selected_override
            if selected is None:
                selected=[]
                if hasattr(self,"symptom_list"):
                    selected=[self.symptom_list.item(i).text() for i in range(self.symptom_list.count()) if self.symptom_list.item(i).isSelected()]
            if selected: parts+=["","AUSGEWÄHLTE SYMPTOME ("+str(len(selected))+")"]+["☑ "+x for x in selected]
            screening=[x.text() for x in getattr(self,"screening_checks",[]) if x.isChecked()]
            if screening: parts+=["","VERDACHTSFALL – BEJAHETE EXPLORATIONSFRAGEN"]+["☑ "+x for x in screening]+["Hinweis: strukturierte Exploration; keine automatische Diagnose."]
            if getattr(self,"couple_mode",None) is not None and self.couple_mode.isChecked():
                parts+=["","PAARTHERAPIE – GETRENNTE PERSPEKTIVEN"]
                if self.partner_a.text().strip() or self.partner_a_view.toPlainText().strip(): parts+=["Partner A: "+(self.partner_a.text().strip() or "A"),self.partner_a_view.toPlainText().strip()]
                if self.partner_b.text().strip() or self.partner_b_view.toPlainText().strip(): parts+=["Partner B: "+(self.partner_b.text().strip() or "B"),self.partner_b_view.toPlainText().strip()]
                if self.couple_cycle.text().strip(): parts+=["Interaktionskreislauf: "+self.couple_cycle.text().strip()]
                if self.couple_goal.text().strip(): parts+=["Gemeinsames Ziel: "+self.couple_goal.text().strip()]
                if self.couple_resources.text().strip(): parts+=["Ressourcen / positive Ausnahmen: "+self.couple_resources.text().strip()]
                parts+=["Getrennte Einschätzung: Belastung A "+str(self.couple_a_distress.value())+"/10 · B "+str(self.couple_b_distress.value())+"/10","Zuversicht A "+str(self.couple_a_hope.value())+"/10 · B "+str(self.couple_b_hope.value())+"/10"]
                pair_answers=[(q,a.value(),b.value()) for q,a,b in self.couple_question_rows if a.value()>=0 or b.value()>=0]
                if pair_answers:
                    parts+=["","PAARFRAGEBOGEN – A/B-VERGLEICH"]
                    parts += ["• "+q+" | A: "+("–" if av<0 else str(av)+"/10")+" · B: "+("–" if bv<0 else str(bv)+"/10")+(" · Differenz: "+str(abs(av-bv)) if av>=0 and bv>=0 else "") for q,av,bv in pair_answers]
                if self.couple_children.isChecked(): parts+=["☑ Kinder / Elternebene betroffen"]
                if self.couple_violence.isChecked(): parts+=["⚠ Hinweis auf Gewalt / Drohung / Zwang / Kontrolle","Sicherheit und individuelle Risikoabklärung priorisieren; übliche Paarinterventionen nicht schematisch fortsetzen."]
            details=[]
            if hasattr(self,"sym_duration"):
                for label,box in [("Dauer",self.sym_duration),("Intensität",self.sym_intensity),("Häufigkeit",self.sym_frequency),("Alltagsbeeinträchtigung",self.sym_impairment)]:
                    if box.currentIndex()>0: details.append(label+": "+box.currentText())
            if hasattr(self,"sym_scale") and self.sym_scale.value()>0: details.append("Subjektive aktuelle Belastung: "+str(self.sym_scale.value())+"/10")
            if hasattr(self,"goal_scale") and self.goal_scale.value()>0: details.append("Subjektive Zielerreichung: "+str(self.goal_scale.value())+"/10")
            if details: parts+=["","SYMPTOMVERTIEFUNG"]+["• "+x for x in details]
            if hasattr(self,"help_goal") and self.help_goal.text().strip(): parts+=["","SITZUNGSZIEL",self.help_goal.text().strip()]
            if hasattr(self,"help_resources") and self.help_resources.text().strip(): parts+=["","RESSOURCEN / SCHUTZFAKTOREN",self.help_resources.text().strip()]
            risks=[x.text() for x in getattr(self,"risk_checks",[]) if x.isChecked()]
            if risks: parts+=["","SICHERHEITSRELEVANTE HINWEISE"]+["• "+x for x in risks]
            active_risks=[x for x in risks if x!="Kein aktueller Sicherheitshinweis"]
            if active_risks: parts+=["⚠ Sicherheitsabklärung erforderlich: Akuität, Absicht/Plan, Mittel/Zugang, Schutzfaktoren und notwendige Schutzmaßnahmen eigenständig prüfen und dokumentieren."]
            if hasattr(self,"help_trigger") and self.help_trigger.text().strip(): parts+=["","AUSLÖSER / SITUATIONEN",self.help_trigger.text().strip()]
            if hasattr(self,"help_maintain") and self.help_maintain.text().strip(): parts+=["","AUFRECHTERHALTENDE FAKTOREN",self.help_maintain.text().strip()]
            if hasattr(self,"help_strength") and self.help_strength.text().strip(): parts+=["","AUSNAHMEN / BEREITS HILFREICH",self.help_strength.text().strip()]
            if hasattr(self,"help_support") and self.help_support.text().strip(): parts+=["","UNTERSTÜTZUNGSSYSTEM",self.help_support.text().strip()]
            if hasattr(self,"help_next") and self.help_next.text().strip(): parts+=["","NÄCHSTER SCHRITT / VEREINBARUNG",self.help_next.text().strip()]
            if hasattr(self,"help_note") and self.help_note.text().strip(): parts+=["","EIGENE NOTIZ",self.help_note.text().strip()]
            m=clinical_map.get(self.help_topic.currentText())
            if m: parts+=["","F-CODE-PRÜFRICHTUNG (KEINE AUTOMATISCHE DIAGNOSE)"]+["• "+x for x in m["codes"]]+["Differenzialfragen:"]+["• "+x for x in m["diff"]]
            code=self.help_fcode.currentText() if hasattr(self,"help_fcode") else ""
            if " – " in code: parts+=["","AUSGEWÄHLTER F-CODE",code,"Hinweis: Der Code dient als Dokumentations- und Gesprächshilfe; keine automatische Diagnosestellung."]
            parts+=["","FACHLICHER HINWEIS","Arbeitshilfe zur strukturierten Exploration. Sie ersetzt keine eigenständige Diagnostik, Risikoabwägung oder Behandlungsentscheidung."]
            self.help_text.setPlainText("\n".join(parts))
        for field in (self.partner_a,self.partner_b,self.couple_cycle,self.couple_goal,self.couple_resources): field.textChanged.connect(lambda _:render())
        for box in (self.couple_a_distress,self.couple_b_distress,self.couple_a_hope,self.couple_b_hope): box.valueChanged.connect(lambda _:render())
        for _,a,b in self.couple_question_rows: a.valueChanged.connect(lambda _:render()); b.valueChanged.connect(lambda _:render())
        self.partner_a_view.textChanged.connect(render); self.partner_b_view.textChanged.connect(render); self.couple_mode.toggled.connect(lambda _:render()); self.couple_violence.toggled.connect(lambda _:render()); self.couple_children.toggled.connect(lambda _:render())
        self.help_topic.currentTextChanged.connect(lambda _:update_clinical_hint()); update_clinical_hint()
        self.help_topic.currentTextChanged.connect(render); self.help_fcode.currentTextChanged.connect(lambda _:render())
        def refresh_symptom_summary(*_):
            # selectedItems() ist die kanonische Qt-Auswahl und funktioniert sowohl
            # bei Maus-/Tastaturauswahl als auch bei programmgesteuerter Auswahl.
            selected=[item.text() for item in self.symptom_list.selectedItems()]
            render(selected)
        self.symptom_list.itemSelectionChanged.connect(refresh_symptom_summary)
        # Auswahl der Symptome aktualisiert die Arbeitshilfe sofort; Doppelklick übernimmt
        # das einzelne Symptom zusätzlich direkt in die Therapienotiz.
        def transfer_one_symptom(item):
            if not hasattr(self,"notes"): return
            code=self.help_fcode.currentText()
            line="• "+item.text()+((" ["+code.split(" – ",1)[0]+"]") if " – " in code else "")
            existing=self.notes.toPlainText().rstrip()
            self.notes.setPlainText((existing+"\n" if existing else "")+line)
        self.symptom_list.itemDoubleClicked.connect(transfer_one_symptom)
        for box in (self.sym_duration,self.sym_intensity,self.sym_frequency,self.sym_impairment): box.currentTextChanged.connect(lambda _:render())
        def risk_changed(changed):
            if changed.text()=="Kein aktueller Sicherheitshinweis" and changed.isChecked():
                for cb in self.risk_checks[:-1]: cb.blockSignals(True); cb.setChecked(False); cb.blockSignals(False)
            elif changed.isChecked() and changed is not self.risk_checks[-1]:
                self.risk_checks[-1].blockSignals(True); self.risk_checks[-1].setChecked(False); self.risk_checks[-1].blockSignals(False)
            render()
        for cb in self.risk_checks: cb.toggled.connect(lambda _,x=cb:risk_changed(x))
        self.help_goal.textChanged.connect(lambda _:render()); self.help_resources.textChanged.connect(lambda _:render()); self.help_trigger.textChanged.connect(lambda _:render()); self.help_maintain.textChanged.connect(lambda _:render()); self.help_strength.textChanged.connect(lambda _:render()); self.help_support.textChanged.connect(lambda _:render()); self.help_next.textChanged.connect(lambda _:render()); self.help_note.textChanged.connect(lambda _:render()); self.sym_scale.valueChanged.connect(lambda _:render()); self.goal_scale.valueChanged.connect(lambda _:render())
        couple_actions=QHBoxLayout(); savecouple=QPushButton("Paarverlauf speichern"); historycouple=QPushButton("Paarverlauf anzeigen"); couple_actions.addWidget(savecouple); couple_actions.addWidget(historycouple); couple_actions.addStretch(); v.addLayout(couple_actions)
        def save_couple_assessment():
            if not self.couple_mode.isChecked(): return QMessageBox.information(self,"Paartherapie","Bitte zuerst den Paarmodus aktivieren.")
            a=self.partner_a.text().strip(); b=self.partner_b.text().strip()
            if not a or not b: return QMessageBox.warning(self,"Paartherapie","Bitte Partner A und Partner B eintragen, bevor der Paarverlauf gespeichert wird.")
            if a.casefold()==b.casefold(): return QMessageBox.warning(self,"Paartherapie","Partner A und Partner B dürfen nicht identisch sein.")
            if self.couple_violence.isChecked():
                answer=QMessageBox.question(self,"Sicherheitsmarkierung","Es ist Gewalt, Drohung, Zwang oder Kontrolle markiert. Wurde die individuelle Sicherheits-/Risikoabklärung dokumentiert?\n\nMit „Ja“ wird der Paarverlauf gespeichert.")
                if answer!=QMessageBox.Yes: return
            con=sqlite3.connect(DBFILE); couple_id=None
            for cid,ea,eb in con.execute("SELECT id,partner_a_name,partner_b_name FROM couples WHERE status='aktiv'").fetchall():
                na=decrypt_text(ea).strip().casefold(); nb=decrypt_text(eb).strip().casefold()
                if (na==a.casefold() and nb==b.casefold()) or (na==b.casefold() and nb==a.casefold()):
                    couple_id=cid; break
            con.execute("""INSERT INTO couple_assessments(created_at,client_label,partner_a,partner_b,topic,perspective_a,perspective_b,interaction_cycle,shared_goal,resources,children_involved,safety_flag,answers_a,answers_b,username,couple_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(datetime.now().isoformat(timespec="seconds"),"",encrypt_text(a),encrypt_text(b),self.help_topic.currentText(),encrypt_text(self.partner_a_view.toPlainText()),encrypt_text(self.partner_b_view.toPlainText()),encrypt_text(self.couple_cycle.text()),encrypt_text(self.couple_goal.text()),encrypt_text(self.couple_resources.text()),1 if self.couple_children.isChecked() else 0,1 if self.couple_violence.isChecked() else 0,encrypt_text("Belastung "+str(self.couple_a_distress.value())+"/10; Zuversicht "+str(self.couple_a_hope.value())+"/10; "+"; ".join(q+"="+("nicht beantwortet" if a.value()<0 else str(a.value())) for q,a,b in self.couple_question_rows)),encrypt_text("Belastung "+str(self.couple_b_distress.value())+"/10; Zuversicht "+str(self.couple_b_hope.value())+"/10; "+"; ".join(q+"="+("nicht beantwortet" if b.value()<0 else str(b.value())) for q,a,b in self.couple_question_rows)),(self.current_user or {}).get("username",""),couple_id)); con.commit(); con.close(); audit("COUPLE_ASSESSMENT_SAVED","Paarverlauf gespeichert",(self.current_user or {}).get("username","")); QMessageBox.information(self,"Paartherapie","Paarverlauf verschlüsselt gespeichert.")
        def show_couple_history():
            a=self.partner_a.text().strip(); b=self.partner_b.text().strip()
            con=sqlite3.connect(DBFILE); rows=con.execute("SELECT created_at,partner_a,partner_b,topic,interaction_cycle,shared_goal,answers_a,answers_b,safety_flag FROM couple_assessments ORDER BY id DESC LIMIT 100").fetchall(); con.close()
            # Standardmäßig nur den aktuell geöffneten Paarfall zeigen. Ohne Namen
            # wird bewusst kein praxisweiter Verlauf mit fremden Paaren angezeigt.
            if not a and not b:
                return QMessageBox.information(self,"Paartherapie","Bitte Partner A oder Partner B eintragen, damit der passende Paarverlauf gefiltert werden kann.")
            def same_case(r):
                ra=decrypt_text(r[1]).strip().casefold(); rb=decrypt_text(r[2]).strip().casefold()
                aa=a.casefold(); bb=b.casefold()
                direct=(not aa or ra==aa) and (not bb or rb==bb)
                swapped=(not aa or rb==aa) and (not bb or ra==bb)
                return direct or swapped
            rows=[r for r in rows if same_case(r)][:20]
            dlg=QDialog(self); dlg.setWindowTitle("Paartherapie – Verlauf"); dlg.resize(900,620); vv=QVBoxLayout(dlg); out=QTextEdit(); out.setReadOnly(True); chunks=[]
            for r in rows: chunks.append(r[0].replace("T"," ")+" · "+decrypt_text(r[1])+" / "+decrypt_text(r[2])+"\nThema: "+r[3]+"\nKreislauf: "+decrypt_text(r[4])+"\nZiel: "+decrypt_text(r[5])+"\nA: "+decrypt_text(r[6])+" | B: "+decrypt_text(r[7])+("\n⚠ Sicherheitsmarkierung" if r[8] else "")+"\n")
            out.setPlainText("\n".join(chunks) if chunks else "Für dieses Paar ist noch kein Verlauf gespeichert."); vv.addWidget(out); close=QPushButton("Schließen"); close.clicked.connect(dlg.accept); vv.addWidget(close); dlg.exec()
        savecouple.clicked.connect(save_couple_assessment); historycouple.clicked.connect(show_couple_history)
        actions=QHBoxLayout(); copybtn=QPushButton("Zusammenfassung kopieren"); copybtn.clicked.connect(lambda: QApplication.clipboard().setText(self.help_text.toPlainText())); actions.addWidget(copybtn)
        resetbtn=QPushButton("Abfrage zurücksetzen")
        def reset_assessment():
            self.symptom_list.clearSelection()
            for box in (self.sym_duration,self.sym_intensity,self.sym_frequency,self.sym_impairment): box.setCurrentIndex(0)
            for cb in self.risk_checks: cb.setChecked(False)
            for cb in getattr(self,"screening_checks",[]): cb.setChecked(False)
            self.couple_mode.setChecked(False); self.partner_a.clear(); self.partner_b.clear(); self.partner_a_view.clear(); self.partner_b_view.clear()
            self.couple_cycle.clear(); self.couple_goal.clear(); self.couple_resources.clear(); self.couple_children.setChecked(False); self.couple_violence.setChecked(False)
            for box in (self.couple_a_distress,self.couple_b_distress,self.couple_a_hope,self.couple_b_hope): box.setValue(0)
            for _,a,b in self.couple_question_rows: a.setValue(-1); b.setValue(-1)
            self.help_goal.clear(); self.help_resources.clear(); self.help_trigger.clear(); self.help_maintain.clear(); self.help_strength.clear(); self.help_support.clear(); self.help_next.clear(); self.help_note.clear(); self.sym_scale.setValue(0); self.goal_scale.setValue(0); self.school_filter.setCurrentIndex(0); render()
        resetbtn.clicked.connect(reset_assessment); actions.addWidget(resetbtn)
        tosession=QPushButton("In Sitzungsnotiz übernehmen")
        def copy_to_session():
            txt=self.help_text.toPlainText()
            if hasattr(self,"typed_notes"):
                cur=self.typed_notes.toPlainText().strip(); self.typed_notes.setPlainText((cur+"\n\n"+txt).strip()); QMessageBox.information(self,"Übernommen","Die strukturierte Zusammenfassung wurde in die Sitzungsnotiz übernommen.")
            else: QApplication.clipboard().setText(txt)
        tosession.clicked.connect(copy_to_session); actions.addWidget(tosession)
        shortcopy=QPushButton("Kurzbefund kopieren")
        def copy_short():
            selected=[x.text() for x in self.symptom_list.selectedItems()]; bits=["Thema: "+self.help_topic.currentText()]
            if selected: bits.append("Symptome: "+", ".join(selected))
            if self.sym_scale.value()>0: bits.append("Belastung: "+str(self.sym_scale.value())+"/10")
            if self.help_goal.text().strip(): bits.append("Ziel: "+self.help_goal.text().strip())
            if self.help_next.text().strip(): bits.append("Nächster Schritt: "+self.help_next.text().strip())
            QApplication.clipboard().setText("\n".join(bits))
        shortcopy.clicked.connect(copy_short); actions.addWidget(shortcopy); v.addLayout(actions)
        render()
        add=QPushButton("Ausgewählten Text in Sitzungsnotiz übernehmen"); add.setMinimumHeight(55)
        def add_note():
            x=self.help_text.textCursor().selectedText().strip()
            if not x:return QMessageBox.information(self,"Auswahl","Bitte zuerst eine Frage oder einen Hinweis markieren.")
            self.notes.append(x)
        add.clicked.connect(add_note); v.addWidget(add)
        scroll.setWidget(body); outer.addWidget(scroll)
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
                self.s_type.setCurrentText(d.get("type","Einzeltherapie")); self.s_red.setChecked(bool(d.get("reduced",False))); self.notes.setPlainText(d.get("notes","")); self.session_homework.setPlainText(d.get("homework",""))
                inkfile=d.get("ink_file","")
                if inkfile and Path(inkfile).exists(): self.ink.load_png(inkfile)
                self.acc=int(d.get("seconds",0)); self.running=False; self.started=None
                self.nav.setCurrentRow(1)
        except Exception: pass
    def autosave_session(self):
        if not self.running and not self.notes.toPlainText().strip() and not self.s_last.text().strip() and not self.s_first.text().strip(): return
        draft={"last":self.s_last.text(),"first":self.s_first.text(),"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"seconds":self.elapsed(),"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"homework":self.session_homework.toPlainText().strip(),"running":self.running}
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
        # Seitenwechsel können das Qt-Label bereits zerstört haben, während der Timer noch feuert.
        # In diesem Fall den verwaisten Timer sauber stoppen statt auf ein gelöschtes C++-Objekt zuzugreifen.
        s=self.elapsed()
        try:
            clock=getattr(self,"clock",None)
            if clock is None: return
            clock.setText(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}")
        except RuntimeError:
            timer=getattr(self,"timer",None)
            if timer is not None:
                try: timer.stop()
                except RuntimeError: pass
            self.clock=None
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
        partner=None
        if self.s_type.currentText()=="Paargespräch":
            partner=self.partner_pick.currentData()
            if not isinstance(partner,dict): return QMessageBox.warning(self,"Paargespräch","Bitte den zweiten Partner auswählen.")
            primary=self.client_pick.currentData()
            if partner is primary or (isinstance(primary,dict) and partner.get("last")==primary.get("last") and partner.get("first")==primary.get("first") and partner.get("dob")==primary.get("dob")):
                return QMessageBox.warning(self,"Paargespräch","Bitte zwei unterschiedliche Klienten auswählen.")
        if not self.s_start.time().isValid() or not self.s_end.time().isValid(): return QMessageBox.warning(self,"Zeitangabe","Bitte Beginn und Ende prüfen.")
        if self.s_start.time()==self.s_end.time(): return QMessageBox.warning(self,"Zeitangabe","Beginn und Ende dürfen nicht identisch sein. Die Zeiten können vor dem Speichern manuell korrigiert werden.")
        if self.s_start.time().secsTo(self.s_end.time())<=0: return QMessageBox.warning(self,"Zeitangabe","Die Endzeit muss nach der Beginnzeit liegen.")
        c=next((x for x in DB["clients"] if x["last"].lower()==last.lower() and x["first"].lower()==first.lower()),None)
        if not c:c={"last":last,"first":first,"dob":self.s_dob.text().strip(),"address":"","diagnosis":""}; DB["clients"].append(c)
        else: c["dob"]=self.s_dob.text().strip() or c.get("dob","")
        # Abrechnungsdauer folgt den manuell dokumentierten Beginn-/Endzeiten.
        # Der Live-Timer bleibt eine unabhängige Kontrollanzeige.
        start_t=self.s_start.time(); end_t=self.s_end.time()
        mins=start_t.secsTo(end_t)//60 if start_t.isValid() and end_t.isValid() else 0
        if mins <= 0: mins=max(1,round(self.elapsed()/60))
        rec={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"last":last,"first":first,"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"minutes":mins,"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"suspected_diagnosis":self.session_diag.text().strip(),"notes":self.notes.toPlainText(),"homework":self.session_homework.toPlainText().strip(),"billed":False}
        if partner: rec["partner"]={"last":partner.get("last",""),"first":partner.get("first",""),"dob":partner.get("dob","")}
        d=client_dir(c)/"Sitzungen"; inkfile=d/f"{rec['date']}_{rec['id']}_Handschrift.png"; self.ink.save_png(inkfile); rec["ink_file"]=encrypt_file(inkfile)
        rec["ocr_text"]=self.current_ocr_text.strip()
        if rec["ocr_text"]:
            ocrfile=d/(rec["date"]+"_"+rec["id"]+"_OCR.txt.enc")
            ocrfile.write_text(encrypt_text(rec["ocr_text"]),encoding="utf-8")
            rec["ocr_file"]=str(ocrfile)
        DB["sessions"].append(rec)
        save_data()
        session_json=d/(rec["date"]+"_Sitzung.json.enc")
        session_json.write_text(encrypt_text(json.dumps(rec,ensure_ascii=False,indent=2)),encoding="utf-8")
        self.current_ocr_text=""
        for auto in (ROOT/"Sitzung_Autosave.json.enc",ROOT/"Sitzung_Autosave.json",ROOT/"Sitzung_Autosave_Handschrift.png",ROOT/"Sitzung_Autosave_Handschrift.png.enc"):
            if auto.exists():
                try:auto.unlink()
                except Exception:pass
        answer=QMessageBox.question(self,"Sitzung gespeichert",f"Sitzung gespeichert: {mins} Minuten.\n\nJetzt direkt eine Rechnung aus dieser Sitzung erstellen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if answer==QMessageBox.Yes:
            self.nav.setCurrentRow(7); QApplication.processEvents()
            self.i_last.setText(last); self.i_first.setText(first); self.fill_invoice_client()
            self.pending_sessions=[rec]; self.manual_items=[]
            self.i_date.setDate(QDate.fromString(rec["date"],"yyyy-MM-dd")); self.i_start.setTime(QTime.fromString(rec["start"],"HH:mm")); self.i_end.setTime(QTime.fromString(rec["end"],"HH:mm")); self.i_min.setValue(rec["minutes"]); self.i_type.setCurrentText(rec["type"]); self.i_red.setChecked(bool(rec["reduced"]))
            if hasattr(self,"iteminfo"): self.iteminfo.setText(f'1 Sitzung ausgewählt · {amount_for(rec["minutes"],rec["type"],rec["reduced"]):.2f} €')
        appt=QMessageBox.question(self,"Folgetermin", "Möchten Sie direkt einen neuen Termin für diesen Klienten eintragen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if appt==QMessageBox.Yes:
            self.nav.setCurrentRow(0); QApplication.processEvents()
            refresh=getattr(self,"refresh_calendar_people",None)
            if callable(refresh): refresh()
            if hasattr(self,"appt_client"):
                target=None
                for n in range(self.appt_client.count()):
                    name=self.appt_client.itemText(n).strip().lower()
                    if first.lower() in name and last.lower() in name: target=n; break
                if target is not None: self.appt_client.setCurrentIndex(target)
            if hasattr(self,"appt_type"): self.appt_type.setCurrentText(rec["type"] if rec["type"] in [self.appt_type.itemText(i) for i in range(self.appt_type.count())] else "Einzeltherapie")
            if hasattr(self,"appt_minutes"): self.appt_minutes.setValue(rec["minutes"] if rec["minutes"]<=300 else 45)
    def invoice_ui(self):
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(28,24,28,34); v.setSpacing(16)
        title=QLabel("Neue Rechnung"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Klient auswählen oder Namen eingeben - passende Klienten werden automatisch vorgeschlagen."); sub.setObjectName("pageSub"); v.addWidget(sub)
        card=QFrame(); card.setObjectName("formCard"); f=QFormLayout(card); f.setSpacing(12)
        self.i_no=QLineEdit(next_no()); self.i_last=QLineEdit(); self.i_first=QLineEdit(); self.i_addr=QLineEdit(); self.i_diag=QLineEdit(); self.pending_sessions=None; self.manual_items=[]
        self.i_client=QComboBox(); self.i_client.setEditable(True); self.i_client.setInsertPolicy(QComboBox.NoInsert); self.i_client.setMinimumHeight(44)
        self.i_client.lineEdit().setPlaceholderText("Klient suchen: Vorname oder Nachname eingeben")
        self.refresh_invoice_clients()
        comp=self.i_client.completer()
        if comp:
            comp.setCompletionMode(QCompleter.PopupCompletion); comp.setFilterMode(Qt.MatchContains); comp.setCaseSensitivity(Qt.CaseInsensitive)
        def pick_invoice_client(_=None):
            data=self.i_client.currentData()
            if not isinstance(data,dict):
                typed=self.i_client.currentText().strip().lower()
                data=next((cc for cc in DB["clients"] if typed in f'{cc.get("first","")} {cc.get("last","")}'.lower() or typed in f'{cc.get("last","")}, {cc.get("first","")}'.lower()),None)
            if isinstance(data,dict):
                self.i_first.setText(data.get("first","")); self.i_last.setText(data.get("last","")); self.i_addr.setText(data.get("address","")); self.i_diag.setText(data.get("diagnosis",""))
        self.i_client.activated.connect(pick_invoice_client)
        self.i_client.lineEdit().editingFinished.connect(pick_invoice_client)
        for ed in (self.i_no,self.i_last,self.i_first,self.i_addr,self.i_diag): ed.setMinimumHeight(40)
        self.i_date=QDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_date.setDisplayFormat("dd.MM.yyyy"); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Sonstige"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigter Satz")
        self.i_start=QTimeEdit(QTime.currentTime()); self.i_start.setDisplayFormat("HH:mm"); self.i_end=QTimeEdit(QTime.currentTime().addSecs(45*60)); self.i_end.setDisplayFormat("HH:mm")
        for te in (self.i_start,self.i_end):
            te.setKeyboardTracking(False); te.setAccelerated(True); te.setWrapping(True); te.setToolTip("Zeit direkt eingeben, z. B. 1430 für 14:30")
            te.lineEdit().setInputMask("99:99;_"); te.lineEdit().setPlaceholderText("HH:MM"); te.lineEdit().installEventFilter(self)
        for ed in (self.i_date,self.i_type,self.i_min,self.i_start,self.i_end): ed.setMinimumHeight(40)
        f.addRow("Klient auswählen / suchen",self.i_client)
        for a,b in [("Rechnungsnummer",self.i_no),("Nachname",self.i_last),("Vorname",self.i_first),("Adresse",self.i_addr),("Diagnose (optional)",self.i_diag),("Leistungsdatum",self.i_date),("Beginn",self.i_start),("Ende",self.i_end),("Leistung",self.i_type),("Dauer Minuten",self.i_min)]: f.addRow(a,b)
        def invoice_times():
            secs=self.i_start.time().secsTo(self.i_end.time())
            if secs>0:self.i_min.setValue(max(1,secs//60))
        self.i_start.timeChanged.connect(invoice_times); self.i_end.timeChanged.connect(invoice_times)
        self.i_last.editingFinished.connect(self.fill_invoice_client); self.i_first.editingFinished.connect(self.fill_invoice_client)
        f.addRow("",self.i_red); v.addWidget(card)
        itemrow=QHBoxLayout(); additem=QPushButton("＋ Leistung zur Rechnung hinzufügen"); additem.setMinimumHeight(46)
        self.iteminfo=QLabel("Noch keine zusätzlichen Leistungen"); self.iteminfo.setObjectName("pageSub")
        def add_manual_item():
            typ=self.i_type.currentText(); mins=self.i_min.value()
            if typ=="Sonstige":
                val,ok=QInputDialog.getDouble(self,"Sonstige Leistung","Betrag in €",0,0,100000,2)
                if not ok:return
                amount=round(val,2)
            else: amount=round(amount_for(mins,typ,self.i_red.isChecked()),2)
            self.manual_items.append({"date":self.i_date.date().toString("yyyy-MM-dd"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amount})
            self.pending_sessions=None; refresh_items()
        itemrow.addWidget(additem); itemrow.addWidget(self.iteminfo,1); v.addLayout(itemrow)
        self.itemtable=QTableWidget(0,6); self.itemtable.setHorizontalHeaderLabels(["Datum","Zeit","Min.","Leistung","Satz","Betrag"]); self.itemtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.itemtable.setSelectionBehavior(QTableWidget.SelectRows); self.itemtable.setEditTriggers(QTableWidget.NoEditTriggers); self.itemtable.setMinimumHeight(170); self.itemtable.setMaximumHeight(260); v.addWidget(self.itemtable)
        def refresh_items():
            self.itemtable.setRowCount(0)
            for it in self.manual_items:
                r=self.itemtable.rowCount(); self.itemtable.insertRow(r)
                vals=[it.get("date",""),f'{it.get("start","")}–{it.get("end","")}',str(it.get("minutes",0)),it.get("type",""),"ermäßigt" if it.get("reduced") else "regulär",f'{float(it.get("amount",0)):.2f} €']
                for j,val in enumerate(vals): self.itemtable.setItem(r,j,QTableWidgetItem(str(val)))
            self.iteminfo.setText("Noch keine zusätzlichen Leistungen" if not self.manual_items else f"{len(self.manual_items)} Leistungen · {sum(float(x.get('amount',0)) for x in self.manual_items):.2f} €")
        additem.clicked.connect(add_manual_item)
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
            no=self.i_no.text().strip(); last=self.i_last.text().strip(); first=self.i_first.text().strip(); rows=self.pending_sessions or self.manual_items
            if rows:
                lines="\n".join(f'{s.get("date","")}  {s.get("start","")}–{s.get("end","")}  {s.get("minutes",0)} Min.  {s.get("type","")}  {float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))):.2f} €' for s in rows)
                total=sum(float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))) for s in rows)
            else:
                total=amount_for(self.i_min.value(),self.i_type.currentText(),self.i_red.isChecked()); lines=f'{self.i_date.date().toString("dd.MM.yyyy")}  {self.i_min.value()} Min.  {self.i_type.currentText()}  {total:.2f} €'
            QMessageBox.information(self,"Rechnung prüfen",f"Rechnung {no}\n{first} {last}\n\n{lines}\n\nGesamt: {total:.2f} €")
        preview.clicked.connect(preview_invoice); v.addWidget(preview)
        b=QPushButton("PDF-Rechnung erstellen"); b.setMinimumHeight(60); b.clicked.connect(self.make_invoice); v.addWidget(b); v.addSpacing(20); scroll.setWidget(page); outer.addWidget(scroll); return w

    def refresh_invoice_clients(self):
        if not hasattr(self,"i_client"): return
        current=self.i_client.currentText(); self.i_client.blockSignals(True); self.i_client.clear()
        self.i_client.addItem("",None)
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
            self.i_client.addItem(f'{cc.get("last","")}, {cc.get("first","")}',cc)
        self.i_client.setCurrentText(current); self.i_client.blockSignals(False)

    def fill_invoice_client(self):
        last,first=self.i_last.text().strip().lower(),self.i_first.text().strip().lower()
        x=next((c for c in DB["clients"] if c.get("last","").lower()==last and (not first or c.get("first","").lower()==first)),None)
        if x:
            self.i_first.setText(x.get("first","")); self.i_last.setText(x.get("last","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis",""))
            if hasattr(self,"i_client"): self.i_client.setCurrentText(f'{x.get("last","")}, {x.get("first","")}')

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
    def make_invoice_html(self):
        if not self.require_edit(): return
        audit("INVOICE_ENGINE", "html", self.current_user.get("username","") if self.current_user else "")
        for label, te in (("Beginn", self.i_start), ("Ende", self.i_end)):
            raw = te.lineEdit().text().strip().replace("_", "")
            parsed = QTime.fromString(raw, "HH:mm")
            if not parsed.isValid():
                return QMessageBox.warning(self, "Zeitangabe", f"{label}: Bitte eine gültige Uhrzeit im Format HH:MM eingeben.")
            te.setTime(parsed)

        no = self.i_no.text().strip()
        if not no:
            return QMessageBox.warning(self, "Fehlt", "Eine Rechnungsnummer ist erforderlich.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", no):
            return QMessageBox.warning(self, "Rechnungsnummer", "Bitte nur Buchstaben, Zahlen, Punkt, Bindestrich oder Unterstrich verwenden.")
        if any(x["number"] == no for x in DB["invoices"]):
            return QMessageBox.warning(self, "Doppelt", "Diese Rechnungsnummer existiert bereits.")

        last, first = self.i_last.text().strip(), self.i_first.text().strip()
        if not last or not first:
            return QMessageBox.warning(self, "Fehlt", "Vorname und Nachname sind erforderlich.")

        rows = getattr(self, "pending_sessions", None) or self.manual_items
        if rows:
            mins = sum(int(x.get("minutes", 0)) for x in rows)
            typ = "Sammelrechnung"
            amt = round(sum(float(x.get("amount", amount_for(int(x.get("minutes", 0)), x.get("type", "Einzeltherapie"), bool(x.get("reduced", False))))) for x in rows), 2)
        else:
            mins = self.i_min.value()
            typ = self.i_type.currentText()
            amt = round(amount_for(mins, typ, self.i_red.isChecked()), 2)

        c = next((x for x in DB["clients"] if x.get("last", "").lower() == last.lower() and x.get("first", "").lower() == first.lower()), None)
        if not c:
            c = {"last": last, "first": first, "dob": "", "address": self.i_addr.text().strip(), "diagnosis": self.i_diag.text().strip()}
            DB["clients"].append(c)
        else:
            if self.i_addr.text().strip(): c["address"] = self.i_addr.text().strip()
            if self.i_diag.text().strip(): c["diagnosis"] = self.i_diag.text().strip()

        items = []
        if rows:
            for x in rows:
                items.append({
                    "id": x.get("id"), "date": x.get("date", ""), "start": x.get("start", ""),
                    "end": x.get("end", ""), "minutes": int(x.get("minutes", 0)), "type": x.get("type", ""),
                    "reduced": bool(x.get("reduced", False)),
                    "amount": round(float(x.get("amount", amount_for(int(x.get("minutes", 0)), x.get("type", "Einzeltherapie"), bool(x.get("reduced", False))))), 2)
                })
        else:
            items = [{
                "id": None, "date": self.i_date.date().toString("yyyy-MM-dd"),
                "start": self.i_start.time().toString("HH:mm"), "end": self.i_end.time().toString("HH:mm"),
                "minutes": mins, "type": typ, "reduced": self.i_red.isChecked(), "amount": amt
            }]

        def parse_service_date(value):
            value = str(value).strip()
            for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                try: return datetime.strptime(value, fmt).date()
                except ValueError: pass
            return None

        parsed_dates = [parse_service_date(x.get("date", "")) for x in items]
        parsed_dates = [d for d in parsed_dates if d is not None]
        if not parsed_dates:
            period = datetime.now().strftime("%d.%m.%Y")
        elif len(parsed_dates) == 1:
            period = parsed_dates[0].strftime("%d.%m.%Y")
        else:
            period = f"{min(parsed_dates).strftime('%d.%m.%Y')} - {max(parsed_dates).strftime('%d.%m.%Y')}"

        owner = get_setting("owner_name", "")
        practice_name = get_setting("practice_name", "Psychologische Privatpraxis")
        qualifications = get_setting("qualifications", "")
        address = get_setting("address", "")
        phone = get_setting("phone", "")
        landline = get_setting("landline", "")
        fax = get_setting("fax", "")
        email = get_setting("email", "")
        website = get_setting("website", "")
        tax = get_setting("tax_number", "")
        iban = get_setting("iban", "")
        bic = get_setting("bic", "")
        paypal = get_setting("paypal", "")

        logo_path = effective_practice_logo()

        logo_html = ""
        if logo_path:
            try:
                mime = "image/jpeg" if logo_path.suffix.lower() in (".jpg", ".jpeg") else ("image/bmp" if logo_path.suffix.lower() == ".bmp" else "image/png")
                data = base64.b64encode(Path(logo_path).read_bytes()).decode("ascii")
                logo_html = f'<img class="logo" src="data:{mime};base64,{data}" alt="Praxislogo">'
            except Exception as e:
                audit("INVOICE_HTML_LOGO_ERROR", str(e)[:200])

        def fmt_eur(value):
            return f"{float(value):.2f} €".replace(".", ",")

        item_rows = []
        for x in items:
            d = parse_service_date(x.get("date", ""))
            ds = d.strftime("%d.%m.%Y") if d else escape(str(x.get("date", "")))
            price = fmt_eur(x.get("amount", 0))
            item_rows.append(
                "<tr>"
                f"<td>{ds}</td><td>{escape(str(x.get('type','')))}</td>"
                f"<td>{int(x.get('minutes',0))} Min.</td>"
                f"<td class=\"num\">{price}</td><td class=\"num\">{price}</td>"
                "</tr>"
            )

        sepa_qr_uri = _sepa_qr_data_uri(owner, iban, bic, amt, no)
        paypal_logo_uri = ""
        paypal_logo = bundled_asset("paypal.png")
        if paypal_logo is not None and paypal_logo.is_file():
            try:
                paypal_logo_uri = '<img style="max-width:28mm;max-height:8mm" src="data:image/png;base64,' + base64.b64encode(paypal_logo.read_bytes()).decode("ascii") + '" alt="PayPal">'
            except Exception as e:
                audit("INVOICE_PAYPAL_LOGO_ERROR", str(e)[:200])

        payment_block = (
            f"<b>SEPA-Überweisung</b><br>Empfänger: {escape(owner)}<br>"
            f"IBAN: {escape(iban)}<br>BIC: {escape(bic)}<br>"
            f"Verwendungszweck: {escape(no)}<br>Betrag: {fmt_eur(amt)}<br><br>"
            f"<b>PayPal</b><br>{paypal_logo_uri}<br>{escape(paypal)}"
        )
        contact = "<br>".join(escape(x) for x in [address, phone, ("Festnetz " + landline) if landline else "", ("Fax " + fax) if fax else "", email, website] if x)
        footer = " · ".join(escape(x) for x in [address, email, website, ("Steuernummer " + tax) if tax else ""] if x)
        values = {
            "LOGO": logo_html,
            "HEADER_CENTER": f"<b>{escape(practice_name)}</b><br>{escape(owner)}<br>{escape(qualifications)}",
            "HEADER_RIGHT": contact,
            "SENDER": f"{escape(owner)} · {escape(address)}",
            "RECIPIENT": f"{escape(first)} {escape(last)}<br>{escape(self.i_addr.text().strip()).replace(chr(10), '<br>')}",
            "INVOICE_NO": escape(no),
            "DATE": datetime.now().strftime("%d.%m.%Y"),
            "PERIOD": period,
            "DIAGNOSIS": escape(self.i_diag.text().strip()),
            "ITEMS": "".join(item_rows),
            "TOTAL": fmt_eur(amt),
            "PAYMENT": payment_block,
            "SEPA_QR": f'<img class="qr" src="{sepa_qr_uri}" alt="SEPA QR-Code">' if sepa_qr_uri else "",
            "PAYPAL_QR": "",
            "FOOTER": footer,
        }
        html = render_invoice_html(values)
        pdf = client_dir(c) / "Rechnungen" / f"Rechnung_{no}.pdf"
        ok = render_invoice_pdf(html, pdf)
        if not ok or not pdf.is_file() or pdf.stat().st_size < 1000:
            audit("INVOICE_HTML_RENDER_FAIL", str(pdf))
            try:
                self._invoice_engine_override = "reportlab"
                return self.make_invoice()
            except Exception as e:
                audit("INVOICE_HTML_FALLBACK_FAIL", str(e)[:300])
                return QMessageBox.warning(self, "PDF-Fehler", "Weder HTML- noch ReportLab-Rechnung konnte erzeugt werden.")
            finally:
                if hasattr(self, "_invoice_engine_override"):
                    del self._invoice_engine_override

        DB["invoices"].append({
            "number": no, "date": datetime.now().strftime("%Y-%m-%d"), "client": f"{last}, {first}",
            "address": self.i_addr.text().strip(), "diagnosis": self.i_diag.text().strip(),
            "amount": amt, "status": "offen", "paid_date": "", "pdf": str(pdf), "items": items
        })
        if rows:
            ids = {x.get("id") for x in rows}
            for x in DB["sessions"]:
                if x.get("id") in ids:
                    x["billed"] = True
                    x["invoice_number"] = no
            self.pending_sessions = None
        self.manual_items = []
        self.iteminfo.setText("Noch keine zusätzlichen Leistungen")
        if hasattr(self, "itemtable"): self.itemtable.setRowCount(0)
        save_data(); update_excel(); self.i_no.setText(next_no())
        done = QMessageBox(self)
        done.setIcon(QMessageBox.Information); done.setWindowTitle("Rechnung erstellt")
        done.setText("Die PDF-Rechnung wurde erfolgreich erstellt.")
        done.setInformativeText(str(pdf))
        open_folder = done.addButton("Ordner öffnen", QMessageBox.ActionRole)
        open_pdf = done.addButton("PDF öffnen", QMessageBox.ActionRole)
        done.addButton("Schließen", QMessageBox.RejectRole); done.exec()
        if done.clickedButton() == open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(pdf).parent)))
        elif done.clickedButton() == open_pdf:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))

    def make_invoice(self):
        if not self.require_edit(): return

        if (get_setting("invoice_engine", "reportlab").lower() == "html"
            and getattr(self, "_invoice_engine_override", None) != "reportlab"):
            return self.make_invoice_html()
        audit("INVOICE_ENGINE", "reportlab", self.current_user.get("username","") if self.current_user else "")
        # Eingaben zuerst sauber übernehmen; ungültige Zeiten verständlich melden.
        for label,te in (("Beginn",self.i_start),("Ende",self.i_end)):
            raw=te.lineEdit().text().strip().replace("_","")
            parsed=QTime.fromString(raw,"HH:mm")
            if not parsed.isValid():
                return QMessageBox.warning(self,"Zeitangabe",f"{label}: Bitte eine gültige Uhrzeit im Format HH:MM eingeben.")
            te.setTime(parsed)
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
        # Finale A4-Rechnung: feste Markenfarben und Proportionen der freigegebenen Vorlage.
        # Markenfarben direkt aus dem eingebundenen Praxislogo.
        NAVY=HexColor("#000000"); TEAL=HexColor("#000000"); GOLD=HexColor("#A62908")
        BROWN=HexColor("#684643"); CREAM=HexColor("#FFFFFF"); BORDER=BROWN; WHITE=HexColor("#FFFFFF")
        regular,bold="Helvetica","Helvetica-Bold"
        try:
            arial=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/"arial.ttf"; arial_b=Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/"arialbd.ttf"
            if arial.exists():
                if "PraxisArial" not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont("PraxisArial",str(arial)))
                regular="PraxisArial"
            if arial_b.exists():
                if "PraxisArialBold" not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont("PraxisArialBold",str(arial_b)))
                bold="PraxisArialBold"
        except Exception: pass
        owner=get_setting("owner_name",""); practice_name=get_setting("practice_name","")
        qualifications=get_setting("qualifications",""); practice_subtitle=get_setting("practice_subtitle","")
        address=get_setting("address",""); phone=get_setting("phone",""); landline=get_setting("landline",""); fax=get_setting("fax","")
        email=get_setting("email","info@psychologe-spandau.de"); website=get_setting("website","www.psychologe-spandau.de")
        tax=get_setting("tax_number","19/405/00254"); iban=get_setting("iban","DE13 5001 0517 5404 0811 30")
        bic=get_setting("bic","INGDDEFFXXX"); paypal=get_setting("paypal","erdogankulanoglu@hotmail.com")
        items=[]
        if rows:
            for ss in rows:
                items.append({"date":ss.get("date",""),"start":ss.get("start",""),"end":ss.get("end",""),"minutes":int(ss.get("minutes",0)),"type":ss.get("type",""),"reduced":bool(ss.get("reduced",False)),"amount":float(ss.get("amount",amount_for(int(ss.get("minutes",0)),ss.get("type","Einzeltherapie"),bool(ss.get("reduced",False)))))})
        else:
            items=[{"date":self.i_date.date().toString("dd.MM.yyyy"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amt}]
        def dd(value):
            try:return datetime.strptime(str(value),"%Y-%m-%d").strftime("%d.%m.%Y")
            except:return str(value)
        service_dates=[dd(it["date"]) for it in items if it.get("date")]
        period=(service_dates[0] if len(service_dates)==1 else ((dd(min(str(it["date"]) for it in items if it.get("date")))+" - "+dd(max(str(it["date"]) for it in items if it.get("date")))) if service_dates else datetime.now().strftime("%d.%m.%Y")))
        # Kopfbereich bewusst vollständig entfernt. Neuer Kopf wird separat neu aufgebaut.
        audit("INVOICE_HEADER", "cleared", self.current_user.get("username","") if self.current_user else "")
        # Empfänger und Rechnungsmetadaten
        y=H-70*mm; can.setFillColor(NAVY); can.setFont(regular,10)
        can.drawString(18*mm,y,f"{first} {last}"); y-=5*mm
        for line in (self.i_addr.text().strip().splitlines() or [""]): can.drawString(18*mm,y,line); y-=5*mm
        mx=128*mm; my=H-70*mm
        can.setFont(bold,9.5)
        for lab,val in (("Rechnungs-Nr.:",no),("Rechnungsdatum:",datetime.now().strftime("%d.%m.%Y")),("Leistungszeitraum:",period)):
            can.drawRightString(mx+24*mm,my,lab); can.setFont(regular,9.5); can.drawRightString(W-18*mm,my,val); my-=5*mm; can.setFont(bold,9.5)
        can.setFillColor(NAVY); can.setFont(bold,24); can.drawString(18*mm,H-96*mm,"Rechnung")
        can.setFillColor(NAVY); can.setFont(regular,10)
        sal="Sehr geehrte Frau" if str(c.get("gender","")).lower().startswith("w") else "Sehr geehrter Herr"
        can.drawString(18*mm,H-107*mm,f"{sal} {last},")
        can.drawString(18*mm,H-114*mm,"hiermit stelle ich Ihnen folgende Leistungen in Rechnung:")
        # Leistungstabelle
        top=H-122*mm; x=[18*mm,48*mm,120*mm,145*mm,173*mm,W-18*mm]; rh=7.5*mm
        can.setFillColor(CREAM); can.setStrokeColor(BORDER); can.rect(x[0],top-rh,x[-1]-x[0],rh,stroke=1,fill=1)
        headers=["Datum","Leistung","Dauer","Einzelpreis","Betrag"]; can.setFillColor(TEAL); can.setFont(bold,8.2)
        for j,h in enumerate(headers): can.drawString(x[j]+1.5*mm,top-5*mm,h)
        for xx in x: can.line(xx,top,xx,top-rh*(len(items)+1))
        cy=top-rh; can.setFillColor(NAVY); can.setFont(regular,8.4)
        for it in items:
            unit=float(it["amount"])
            vals=[dd(it["date"]),it["type"],f'{it["minutes"]} Min.',f'{unit:.2f} €'.replace(".",","),f'{unit:.2f} €'.replace(".",",")]
            for j,val in enumerate(vals):
                if j>=3: can.drawRightString(x[j+1]-1.5*mm,cy-5*mm,val)
                else: can.drawString(x[j]+1.5*mm,cy-5*mm,val)
            cy-=rh; can.line(x[0],cy,x[-1],cy)
        # Summenblock rechts
        sy=cy-1*mm; sx=104*mm
        can.setFillColor(WHITE); can.rect(sx,sy-rh,W-18*mm-sx,rh,stroke=1,fill=1)
        can.setFillColor(NAVY); can.setFont(regular,8.5); can.drawString(sx+2*mm,sy-5*mm,"Zwischensumme:"); can.drawRightString(W-20*mm,sy-5*mm,f'{amt:.2f} €'.replace(".",","))
        sy-=rh; can.setFillColor(WHITE); can.rect(sx,sy-rh,W-18*mm-sx,rh,stroke=1,fill=1)
        can.setFillColor(NAVY); can.setFont(regular,8.1); can.drawString(sx+2*mm,sy-5*mm,"Umsatzsteuerbefreit nach § 4 Nr. 14 UStG:"); can.drawRightString(W-20*mm,sy-5*mm,"0,00 €")
        sy-=rh; can.setFillColor(WHITE); can.rect(sx,sy-rh,W-18*mm-sx,rh,stroke=1,fill=1)
        can.setFillColor(NAVY); can.setFont(bold,10); can.drawString(sx+2*mm,sy-5*mm,"Rechnungssumme:"); can.drawRightString(W-20*mm,sy-5*mm,f'{amt:.2f} €'.replace(".",","))
        can.setFillColor(NAVY); can.setFont(regular,8.2)
        can.drawString(18*mm,sy-13*mm,"Gemäß § 4 Nr. 14 UStG wird keine Umsatzsteuer erhoben.")
        can.setFont(bold,8.8); can.drawRightString(W-18*mm,sy-19*mm,"Zahlungsziel: 14 Tage nach Rechnungsdatum.")
        can.setFont(regular,8.2); can.drawRightString(W-18*mm,sy-25*mm,"Bitte Rechnungsnummer als Verwendungszweck angeben.")
        # Zahlungsboxen mit QR-Codes
        by=sy-72*mm; bh=42*mm; gap=4*mm; bw=(W-36*mm-gap)/2
        def paybox(xb,title):
            can.setStrokeColor(BORDER); can.setFillColor(WHITE); can.roundRect(xb,by,bw,bh,2*mm,stroke=1,fill=1)
            can.setFillColor(CREAM); can.roundRect(xb,by+bh-8*mm,bw,8*mm,2*mm,stroke=0,fill=1)
            can.setFillColor(TEAL); can.setFont(bold,10); can.drawString(xb+2*mm,by+bh-5.5*mm,title)
        paybox(18*mm,"SEPA-Überweisung"); paybox(18*mm+bw+gap,"Zahlung per PayPal")
        can.setFillColor(NAVY); can.setFont(bold,6.8); lx=20*mm; ly=by+bh-13*mm
        for lab,val in (("Empfänger:",owner),("IBAN:",iban),("BIC:",bic),("Verwendungszweck:",no),("Betrag:",f'{amt:.2f} €'.replace(".",","))):
            can.drawString(lx,ly,lab); can.setFont(regular,6.8); can.drawString(lx+29*mm,ly,val); ly-=4.2*mm; can.setFont(bold,6.8)
        px=18*mm+bw+gap+2*mm; py=by+bh-13*mm
        # Offizielles PayPal-Asset verwenden, falls es unverändert mitgeliefert wird; sonst neutrale Textkennzeichnung.
        paypal_logo=bundled_asset("paypal.png")
        paypal_logo_drawn=False
        if paypal_logo is not None and paypal_logo.is_file():
            try:
                from reportlab.lib.utils import ImageReader
                pim=ImageReader(str(paypal_logo)); piw,pih=pim.getSize(); pmw,pmh=28*mm,8*mm
                psc=min(pmw/piw,pmh/pih)
                can.drawImage(str(paypal_logo),px,py-1*mm,width=piw*psc,height=pih*psc,preserveAspectRatio=True,mask="auto")
                paypal_logo_drawn=True
            except Exception as e: audit("PAYPAL_LOGO_ERROR",str(e)[:300],self.current_user.get("username","") if self.current_user else "")
        if not paypal_logo_drawn:
            can.setFillColor(NAVY); can.setFont(bold,11); can.drawString(px,py+1*mm,"PayPal")
        can.setFont(regular,7); can.drawString(px,py-4*mm,"PayPal-Konto:")
        can.setFont(bold,7); can.setFillColor(TEAL); can.drawString(px,py-9*mm,paypal); can.setFillColor(NAVY); can.setFont(regular,7); can.drawString(px,py-14*mm,f"Verwendungszweck: {no}")
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics import renderPDF
            def qr(data,xq,yq,size=21*mm):
                q=QrCodeWidget(data); b=q.getBounds(); d=Drawing(size,size,transform=[size/(b[2]-b[0]),0,0,size/(b[3]-b[1]),0,0]); d.add(q); renderPDF.draw(d,can,xq,yq)
            epc="\\n".join(["BCD","002","1","SCT",bic,owner,iban.replace(" ",""),"EUR"+f"{amt:.2f}","","",no])
            qr(epc,18*mm+bw-24*mm,by+4*mm)
            qr("mailto:"+paypal+"?subject=Rechnung%20"+no,18*mm+bw+gap+bw-24*mm,by+4*mm)
        except Exception as e: audit("INVOICE_QR_ERROR",str(e)[:300],self.current_user.get("username","") if self.current_user else "")
        # Abschluss
        can.setFillColor(NAVY); can.setFont(regular,8.5); yy=by-8*mm
        can.drawString(18*mm,yy,"Vielen Dank für Ihr Vertrauen."); can.drawString(18*mm,yy-6*mm,"Mit freundlichen Grüßen")
        can.setFillColor(TEAL); can.setFont(bold,9.5); can.drawString(18*mm,yy-18*mm,owner)
        can.setFillColor(NAVY); can.setFont(regular,7.2); can.drawString(18*mm,yy-23*mm,qualifications)
        can.setFont(regular,6.7)
        can.drawRightString(W-18*mm,yy-18*mm,"Elektronisch erstellte Rechnung – ohne Unterschrift gültig.")
        can.drawRightString(W-18*mm,yy-22*mm,"Bitte bewahren Sie dieses Dokument für Ihre Unterlagen auf.")
        # Fußzeile
        fy=15*mm; can.setStrokeColor(GOLD); can.line(18*mm,fy+10*mm,W-18*mm,fy+10*mm)
        can.setFillColor(TEAL); can.setFont(bold,6.5)
        for xx,title in ((18*mm,"Praxis"),(75*mm,"Kontakt"),(132*mm,"Zahlung / Steuer")): can.drawString(xx,fy+5*mm,title)
        can.setFillColor(NAVY); can.setFont(regular,5.8)
        can.drawString(18*mm,fy+1*mm,address); can.drawString(18*mm,fy-2.5*mm,website)
        contact_footer=" · ".join(x for x in (phone,("Festnetz "+landline) if landline else "") if x)
        can.drawString(75*mm,fy+1*mm,contact_footer)
        if fax: can.drawString(75*mm,fy-2.5*mm,"Fax "+fax)
        can.drawString(75*mm,fy-6*mm,email)
        can.drawString(132*mm,fy+1*mm,"IBAN "+iban); can.drawString(132*mm,fy-2.5*mm,"BIC "+bic)
        if tax: can.drawString(132*mm,fy-6*mm,"Steuernummer "+tax)
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
        done=QMessageBox(self); done.setIcon(QMessageBox.Information); done.setWindowTitle("Rechnung erstellt")
        done.setText("Die PDF-Rechnung wurde erfolgreich erstellt.")
        done.setInformativeText(str(pdf))
        open_folder=done.addButton("Ordner öffnen",QMessageBox.ActionRole)
        open_pdf=done.addButton("PDF öffnen",QMessageBox.ActionRole)
        done.addButton("Schließen",QMessageBox.RejectRole); done.exec()
        if done.clickedButton()==open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(pdf).parent)))
        elif done.clickedButton()==open_pdf:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))
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
            def selected_session():
                rr=st.currentRow()
                if rr<0: return None,None
                date=st.item(rr,0).text(); start=st.item(rr,1).text()
                return rr,next((x for x in rows if x.get("date")==date and x.get("start")==start),None)
            edit=QPushButton("Ausgewählte Sitzung korrigieren")
            def edit_selected():
                rr,s=selected_session()
                if s is None: return QMessageBox.information(dlg,"Sitzung","Bitte zuerst eine Sitzung auswählen.")
                ed=QDialog(dlg); ed.setWindowTitle("Sitzung korrigieren"); form=QFormLayout(ed)
                start_time=QTimeEdit(); start_time.setDisplayFormat("HH:mm"); start_time.setTime(QTime.fromString(s.get("start","09:00"),"HH:mm"))
                end_time=QTimeEdit(); end_time.setDisplayFormat("HH:mm"); end_time.setTime(QTime.fromString(s.get("end","09:45"),"HH:mm"))
                mins=QSpinBox(); mins.setRange(0,1439); mins.setReadOnly(True); mins.setButtonSymbols(QSpinBox.NoButtons)
                def calculate_minutes():
                    duration=start_time.time().secsTo(end_time.time())//60
                    mins.setValue(max(0,duration))
                start_time.timeChanged.connect(calculate_minutes); end_time.timeChanged.connect(calculate_minutes); calculate_minutes()
                typ=QComboBox(); typ.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"]); typ.setCurrentText(s.get("type","Einzeltherapie"))
                note=QTextEdit(); note.setPlainText(s.get("notes",""))
                homework=QTextEdit(); homework.setPlainText(s.get("homework",""))
                invoice_option=QCheckBox("Nach dem Speichern Rechnung aus dieser Sitzung vorbereiten")
                invoice_option.setEnabled(not s.get("billed",False))
                if s.get("billed"): invoice_option.setToolTip("Diese Sitzung ist bereits abgerechnet.")
                for label,field in (("Beginn",start_time),("Ende",end_time),("Dauer (automatisch)",mins),("Art",typ),("Therapienotiz",note),("Hausaufgaben",homework)): form.addRow(label,field)
                form.addRow(invoice_option)
                buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); form.addRow(buttons)
                def save_edit():
                    if mins.value()<=0: return QMessageBox.warning(ed,"Zeitangabe","Ende muss nach Beginn liegen.")
                    if s.get("billed") and (s.get("start")!=start_time.time().toString("HH:mm") or s.get("end")!=end_time.time().toString("HH:mm") or s.get("type")!=typ.currentText()):
                        return QMessageBox.warning(ed,"Abgerechnete Sitzung","Diese Sitzung wurde bereits abgerechnet. Bitte zuerst die Rechnung prüfen bzw. stornieren, bevor abrechnungsrelevante Angaben geändert werden.")
                    s["start"]=start_time.time().toString("HH:mm"); s["end"]=end_time.time().toString("HH:mm"); s["minutes"]=mins.value(); s["type"]=typ.currentText(); s["notes"]=note.toPlainText(); s["homework"]=homework.toPlainText(); s["corrected_at"]=datetime.now().isoformat(timespec="seconds")
                    save_data()
                    d=client_dir({"last":last,"first":first})/"Sitzungen"; d.mkdir(parents=True,exist_ok=True)
                    jf=d/f'{s.get("date","")}_{s.get("id","Sitzung")}_Sitzung.json.enc'; jf.write_text(encrypt_text(json.dumps(s,ensure_ascii=False,indent=2)),encoding="utf-8")
                    st.item(rr,1).setText(s["start"]); st.item(rr,2).setText(s["end"]); st.item(rr,3).setText(str(s["minutes"])); st.item(rr,4).setText(s["type"])
                    do_invoice=invoice_option.isChecked(); ed.accept()
                    if do_invoice:
                        dlg.accept(); self.nav.setCurrentRow(7); QApplication.processEvents()
                        self.i_last.setText(last); self.i_first.setText(first); self.i_addr.setText(cc.get("address","")); self.i_diag.setText(cc.get("diagnosis","")); self.pending_sessions=[s]; self.manual_items=[]
                        self.i_date.setDate(QDate.fromString(s["date"],"yyyy-MM-dd")); self.i_start.setTime(QTime.fromString(s["start"],"HH:mm")); self.i_end.setTime(QTime.fromString(s["end"],"HH:mm")); self.i_min.setValue(s["minutes"]); self.i_type.setCurrentText(s["type"]); self.i_red.setChecked(bool(s.get("reduced",False)))
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
                tabs=QTabWidget()
                tx=QTextEdit()
                tx.setReadOnly(True)
                tx.setPlainText(s.get("notes",""))
                tabs.addTab(tx,"Therapienotiz")
                ocr=QTextEdit()
                ocr.setReadOnly(True)
                ocr_text=s.get("ocr_text","")
                if not ocr_text and s.get("ocr_file") and Path(s.get("ocr_file")).exists():
                    try:
                        ocr_text=decrypt_text(Path(s.get("ocr_file")).read_text(encoding="utf-8"))
                    except Exception:
                        ocr_text=""
                ocr.setPlainText(ocr_text or "Für diese Sitzung ist kein geprüfter OCR-Text gespeichert.")
                tabs.addTab(ocr,"OCR-Text")
                nv.addWidget(tabs,1)
                ink=s.get("ink_file","")
                if ink and Path(ink).exists():
                    lab=QLabel(); pix=QPixmap(); pix.loadFromData(decrypt_file_bytes(ink)); lab.setPixmap(pix.scaled(820,380,Qt.KeepAspectRatio,Qt.SmoothTransformation)); lab.setAlignment(Qt.AlignCenter); nv.addWidget(lab)
                buttons=QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(nd.reject); nv.addWidget(buttons); nd.exec()
            view.clicked.connect(open_selected)
            invoice=QPushButton("Neue Rechnung für diesen Klienten")
            def invoice_from_record():
                self.i_last.setText(last); self.i_first.setText(first); self.i_addr.setText(cc.get("address","")); self.i_diag.setText(cc.get("diagnosis","")); dlg.accept(); self.nav.setCurrentRow(7)
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
            self.i_last.setText(x.get("last","")); self.i_first.setText(x.get("first","")); self.i_addr.setText(x.get("address","")); self.i_diag.setText(x.get("diagnosis","")); self.nav.setCurrentRow(7)
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
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,24,28,28); v.setSpacing(12)
        title=QLabel("Hilfe · FAQ · Info"); title.setObjectName("pageTitle"); v.addWidget(title)
        tabs=QTabWidget(); tabs.setDocumentMode(True); v.addWidget(tabs,1)
        manual=QTextEdit(); manual.setReadOnly(True); manual.setPlainText("""PRAXISPRO – BENUTZERHANDBUCH

PraxisPro unterstützt die lokale Organisation einer psychologischen bzw. therapeutischen Privatpraxis: Klienten, Sitzungen, Tastatur- und Stiftnotizen, Rechnungen, Einnahmen und Sicherungen.

SITZUNGEN
Beginn und Ende bleiben manuell veränderbar. Der Timer ist eine zusätzliche Hilfe. Therapienotizen und Freihandnotizen gehören zur Sitzungsdokumentation und werden nicht automatisch auf Rechnungen übernommen.

RECHNUNGEN
Mehrere Leistungen können gesammelt abgerechnet werden. Rechnungsnummern werden vorgeschlagen und vor Erstellung geprüft. Rechnungen können bezahlt, erinnert oder storniert werden.

SITZUNGSASSISTENT / F-CODES
Fragen, Interventionen und F-Codes sind fachliche Arbeitshilfen. Sie ersetzen keine Diagnostik, Indikationsstellung oder therapeutische Entscheidung.

DATENSICHERUNG
Regelmäßige Sicherungen sind wichtig. Testversionen sollten nicht ohne eigene Prüfung der Schutzmaßnahmen für echte Patientendaten eingesetzt werden."""); tabs.addTab(manual,"Handbuch")
        faq=QTextEdit(); faq.setReadOnly(True); faq.setPlainText("""HÄUFIGE FRAGEN

Wo werden meine Daten gespeichert?
Lokal im Ordner Dokumente/Praxisverwaltung.

Kann ich Beginn und Ende einer Sitzung selbst ändern?
Ja. Beide Zeiten bleiben manuell editierbar.

Kann ich das Notebook mit Stift verwenden?
Ja. Die Freihandfläche unterstützt Schreiben, Radierer, Rückgängig, Zoom, Fenster-/Vollbildmodus und verschlüsseltes Speichern.

Werden Therapienotizen auf die Rechnung übernommen?
Nein. Nur ausdrücklich als Rechnungsleistung erfasste Angaben erscheinen dort.

Kann ich das Aussehen ändern?
Ja. In Praxiseinstellungen stehen Farbschema, Schriftgröße und Darstellungsdichte zur Verfügung.

Kann PraxisPro direkt mit Krankenkassen abrechnen?
Nein. Es gibt derzeit keine direkte Schnittstelle zu Krankenkassen, KVen oder Abrechnungsstellen.

Wie deinstalliere ich PraxisPro?
Unter Info & Programmverwaltung kann die Windows-Deinstallation gestartet werden. Vorher sollte eine aktuelle Datensicherung erstellt werden. Persönliche Praxisdaten werden aus Sicherheitsgründen nicht ungefragt gelöscht."""); tabs.addTab(faq,"FAQ")
        info=QWidget(); iv=QVBoxLayout(info); card=QFrame(); card.setObjectName("formCard"); f=QFormLayout(card)
        f.addRow("Programm",QLabel("PraxisPro")); f.addRow("Version",QLabel(APP_VERSION)); f.addRow("Hersteller",QLabel(get_setting("manufacturer","Erdoğan Kulanoğlu"))); f.addRow("Praxis",QLabel(get_setting("practice_name","Psychologische Privatpraxis"))); f.addRow("Copyright",QLabel(get_setting("copyright","© 2026 Erdoğan Kulanoğlu. Alle Rechte vorbehalten."))); iv.addWidget(card)
        warn=QLabel("Vor einer Deinstallation bitte eine aktuelle Datensicherung erstellen. Die Deinstallation entfernt das Programm; Praxisdaten werden nicht automatisch gelöscht."); warn.setWordWrap(True); warn.setObjectName("infoBox"); iv.addWidget(warn)
        uninstall=QPushButton("PraxisPro deinstallieren …"); uninstall.setMinimumHeight(48)
        def run_uninstall():
            if QMessageBox.question(self,"PraxisPro deinstallieren","Windows-Deinstallation starten?\n\nBitte vorher eine Datensicherung erstellen. Praxisdaten werden nicht automatisch gelöscht.",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
            candidates=[Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"PraxisPro"/"unins000.exe",Path(os.environ.get("ProgramFiles","C:/Program Files"))/"PraxisPro"/"unins000.exe",Path(sys.executable).resolve().parent/"unins000.exe"]
            exe=next((p for p in candidates if p.exists()),None)
            if not exe:return QMessageBox.information(self,"Deinstallation","Der Windows-Deinstaller wurde nicht gefunden. Bitte PraxisPro über Windows Einstellungen → Apps → Installierte Apps deinstallieren.")
            try: subprocess.Popen([str(exe)]); QApplication.quit()
            except Exception as e: QMessageBox.warning(self,"Deinstallation","Deinstaller konnte nicht gestartet werden:\n"+str(e))
        uninstall.clicked.connect(run_uninstall); iv.addWidget(uninstall); iv.addStretch(); tabs.addTab(info,"Info & Programmverwaltung")
        return w

    def settings_ui(self):
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded); body=QWidget(); body.setMinimumWidth(0); v=QVBoxLayout(body); v.setContentsMargins(18,12,18,18); v.setSpacing(9)
        title=QLabel("Praxiseinstellungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Praxisdaten, Abrechnung, Honorare und Benutzer übersichtlich verwalten."); sub.setObjectName("pageSub"); v.addWidget(sub)
        tabs=QTabWidget(); tabs.setDocumentMode(True); tabs.setMinimumHeight(440)
        tabs.setStyleSheet("QTabBar::tab { min-width: 105px; padding-left: 10px; padding-right: 10px; }")
        v.addWidget(tabs); scroll.setWidget(body); outer.addWidget(scroll)
        general=QWidget(); gv=QVBoxLayout(general); gv.setContentsMargins(16,14,16,20); gv.setSpacing(10)
        form=QFormLayout(); form.setHorizontalSpacing(18); form.setVerticalSpacing(10); form.setLabelAlignment(Qt.AlignLeft|Qt.AlignTop)
        # Praxisdaten bewusst kompakt halten: jede Zeile bekommt feste Höhe und Abstand.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setFormAlignment(Qt.AlignTop)
        fields={}
        labels=[("practice_name","Praxisname"),("owner_name","Inhaber / Praxisleitung"),("qualifications","Qualifikationen"),("practice_subtitle","Zusatz / Spezialisierung"),("address","Anschrift"),("phone","Mobil / Telefon"),("landline","Festnetz"),("fax","Fax"),("email","E-Mail"),("website","Website"),("manufacturer","Herstellername"),("copyright","Copyright")]
        for key,label in labels:
            ed=QLineEdit(get_setting(key)); ed.setFixedHeight(34); ed.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed); fields[key]=ed; form.addRow(label,ed)
        # Das mitgelieferte Praxislogo ist der Standard. logo_path bleibt nur
        # eine optionale Überschreibung durch den Benutzer.
        custom_logo_value = (get_setting("logo_path", "") or "").strip()
        logo=QLineEdit(custom_logo_value)
        logo.setFixedHeight(34); logo.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        logo.setPlaceholderText("Standardlogo (mitgeliefert)")
        fields["logo_path"]=logo
        choose=QPushButton("Logo ersetzen …"); choose.setFixedHeight(34)
        reset_logo=QPushButton("Standardlogo"); reset_logo.setFixedHeight(34)
        def pick_logo():
            p,_=QFileDialog.getOpenFileName(self,"Praxislogo auswählen","","Bilder (*.png *.jpg *.jpeg)")
            if p: logo.setText(p)
        def use_default_logo():
            logo.clear()
        choose.clicked.connect(pick_logo)
        reset_logo.clicked.connect(use_default_logo)
        lr=QHBoxLayout(); lr.addWidget(logo,1); lr.addWidget(choose); lr.addWidget(reset_logo)
        form.addRow("Praxislogo",lr)
        logo_x=QDoubleSpinBox(); logo_x.setRange(0,180); logo_x.setValue(float(get_setting("logo_x_mm","18"))); logo_x.setSuffix(" mm")
        logo_y=QDoubleSpinBox(); logo_y.setRange(0,80); logo_y.setValue(float(get_setting("logo_y_mm","7"))); logo_y.setSuffix(" mm")
        logo_w=QDoubleSpinBox(); logo_w.setRange(15,120); logo_w.setValue(float(get_setting("logo_width_mm","72"))); logo_w.setSuffix(" mm")
        logo_h=QDoubleSpinBox(); logo_h.setRange(8,45); logo_h.setValue(float(get_setting("logo_height_mm","22"))); logo_h.setSuffix(" mm")
        lpos=QHBoxLayout(); lpos.addWidget(QLabel("Links")); lpos.addWidget(logo_x); lpos.addWidget(QLabel("Oben")); lpos.addWidget(logo_y); lpos.addWidget(QLabel("Breite")); lpos.addWidget(logo_w); lpos.addWidget(QLabel("Höhe")); lpos.addWidget(logo_h)
        form.addRow("Logo auf Rechnung",lpos)
        logo_zone=QComboBox(); logo_zone.addItems(["Links","Mitte","Rechts"]); logo_zone.setCurrentText(get_setting("invoice_header_logo_zone","Links")); form.addRow("Logo-Bereich im Rechnungskopf",logo_zone)
        header_middle=QComboBox(); header_middle.addItems(["Praxisdaten","Kontaktdaten","Leer"]); header_middle.setCurrentText(get_setting("invoice_header_middle","Praxisdaten")); form.addRow("Kopfbereich Mitte",header_middle)
        header_right=QComboBox(); header_right.addItems(["Kontaktdaten","Praxisdaten","Leer"]); header_right.setCurrentText(get_setting("invoice_header_right","Kontaktdaten")); form.addRow("Kopfbereich Rechts",header_right)
        gv.addLayout(form)
        appearance=QFrame(); appearance.setObjectName("formCard"); appearance.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        # Darstellungsoptionen kompakt in einer Zeile: sie dürfen die Praxisdaten nicht überdecken.
        ar=QHBoxLayout(appearance); ar.setContentsMargins(14,10,14,10); ar.setSpacing(10)
        theme=QComboBox(); theme.addItems(["PraxisPro Blau","Petrol","Grün","Gold","Violett"]); theme.setCurrentText(get_setting("ui_theme","PraxisPro Blau")); theme.setMinimumWidth(180); theme.setMaximumWidth(260)
        fontsize=QSpinBox(); fontsize.setRange(9,16); fontsize.setValue(int(get_setting("ui_font_size","12"))); fontsize.setSuffix(" px"); fontsize.setFixedWidth(105)
        density=QComboBox(); density.addItems(["Kompakt","Normal","Groß"]); density.setCurrentText(get_setting("ui_density","Kompakt")); density.setMinimumWidth(140); density.setMaximumWidth(200)
        ar.addWidget(QLabel("Farbschema")); ar.addWidget(theme); ar.addSpacing(8); ar.addWidget(QLabel("Schriftgröße")); ar.addWidget(fontsize); ar.addSpacing(8); ar.addWidget(QLabel("Darstellung")); ar.addWidget(density); ar.addStretch()
        gv.addWidget(appearance)
        save=QPushButton("Praxiseinstellungen speichern"); save.setMinimumHeight(42)
        def save_settings():
            for k,ed in fields.items(): set_setting(k,ed.text().strip())
            set_setting("logo_x_mm",logo_x.value()); set_setting("logo_y_mm",logo_y.value()); set_setting("logo_width_mm",logo_w.value()); set_setting("logo_height_mm",logo_h.value()); set_setting("invoice_header_logo_zone",logo_zone.currentText()); set_setting("invoice_header_middle",header_middle.currentText()); set_setting("invoice_header_right",header_right.currentText()); set_setting("auto_lock_minutes",lock.value()); set_setting("travel_surcharge",travel.value()); set_setting("ui_theme",theme.currentText()); set_setting("ui_font_size",fontsize.value()); set_setting("ui_density",density.currentText())
            self.apply_appearance()
            QMessageBox.information(self,"Gespeichert","Praxiseinstellungen gespeichert. Farbschema, Schriftgröße und Darstellungsdichte wurden sofort angewendet.")
        save.clicked.connect(save_settings); gv.addSpacing(8); gv.addWidget(save); gv.addStretch(); tabs.addTab(general,"Praxisdaten")
        billing=QWidget(); bv=QVBoxLayout(billing); bv.setContentsMargins(16,14,16,18); bv.setSpacing(10)
        bf=QFormLayout(); bf.setHorizontalSpacing(18); bf.setVerticalSpacing(8)
        for key,label in [("tax_number","Steuernummer"),("iban","IBAN"),("bic","BIC"),("paypal","PayPal")]:
            ed=QLineEdit(get_setting(key)); ed.setMinimumHeight(32); fields[key]=ed; bf.addRow(label,ed)
        lockrow=QHBoxLayout(); lock=QSpinBox(); lock.setRange(1,120); lock.setValue(int(get_setting("auto_lock_minutes","15"))); lock.setSuffix(" Minuten"); lockrow.addWidget(lock); lockrow.addStretch(); bf.addRow("Automatische Sperre",lockrow)
        travel=QDoubleSpinBox(); travel.setRange(0,500); travel.setDecimals(2); travel.setValue(float(get_setting("travel_surcharge","25"))); travel.setSuffix(" €"); bf.addRow("Hausbesuch Anfahrt",travel)
        bv.addLayout(bf); save2=QPushButton("Abrechnung & Sicherheit speichern"); save2.setMinimumHeight(38); save2.clicked.connect(save_settings); bv.addWidget(save2); bv.addStretch(); tabs.addTab(billing,"Abrechnung & Bank")
        ratespage=QWidget(); rv=QVBoxLayout(ratespage); rv.setContentsMargins(12,10,12,12); rv.setSpacing(7)
        rates=QLabel("Honorarsätze"); rates.setObjectName("sectionTitle"); rv.addWidget(rates)
        rt=QTableWidget(0,5); rt.setHorizontalHeaderLabels(["Leistung","Min.","Regulär €","Ermäßigt €","Abrechnung"]); rt.verticalHeader().setDefaultSectionSize(28); rt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
        userspage=QWidget(); uv=QVBoxLayout(userspage); uv.setContentsMargins(12,10,12,12); uv.setSpacing(7)
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
        ut=QTableWidget(0,4); ut.setHorizontalHeaderLabels(["Benutzername","Anzeigename","Rolle","Aktiv"]); ut.verticalHeader().setDefaultSectionSize(28); ut.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
