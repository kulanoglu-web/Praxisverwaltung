import sys, json, os, re, math
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView)
from PySide6.QtCore import QDate,QTime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from openpyxl import Workbook, load_workbook

ROOT=Path.home()/"Documents"/"Praxisverwaltung"
DATA=ROOT/"praxisdaten.json"
for p in [ROOT/"Klienten",ROOT/"Einnahmen",ROOT/"Backups"]: p.mkdir(parents=True,exist_ok=True)

def load_data():
    if DATA.exists():
        try:return json.loads(DATA.read_text(encoding="utf-8"))
        except:return {}
    return {}
DB=load_data(); DB.setdefault("clients",[]); DB.setdefault("sessions",[]); DB.setdefault("invoices",[])

def save_data():
    DATA.write_text(json.dumps(DB,ensure_ascii=False,indent=2),encoding="utf-8")

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
        super().__init__(); self.setWindowTitle("Praxisverwaltung"); self.resize(1180,780)
        self.started=None; self.acc=0; self.running=False
        tabs=QTabWidget(); self.setCentralWidget(tabs)
        tabs.addTab(self.session_ui(),"Sitzungsnotiz"); tabs.addTab(self.invoice_ui(),"Rechnung"); tabs.addTab(self.clients_ui(),"Klienten"); tabs.addTab(self.dashboard_ui(),"Übersicht")
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
    def session_ui(self):
        w=QWidget(); v=QVBoxLayout(w); top=QHBoxLayout()
        title=QLabel("Sitzungsnotiz"); title.setStyleSheet("font-size:26px;font-weight:700")
        self.clock=QLabel("00:00:00"); self.clock.setAlignment(Qt.AlignCenter); self.clock.setStyleSheet("font-size:32px;font-weight:800;padding:12px;border:2px solid #777;border-radius:10px")
        top.addWidget(title); top.addStretch(); top.addWidget(self.clock); v.addLayout(top)
        f=QFormLayout(); self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit()
        self.s_date=QDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_start=QTimeEdit(); self.s_end=QTimeEdit()
        self.s_type=QComboBox(); self.s_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"])
        self.s_red=QCheckBox("Ermäßigter Satz")
        for a,b in [("Nachname",self.s_last),("Vorname",self.s_first),("Geburtsdatum",self.s_dob),("Datum",self.s_date),("Beginn",self.s_start),("Ende",self.s_end),("Art",self.s_type)]:f.addRow(a,b)
        f.addRow("",self.s_red); v.addLayout(f)
        self.notes=QTextEdit(); self.notes.setPlaceholderText("Therapienotizen …"); self.notes.setMinimumHeight(280); self.notes.setStyleSheet("font-size:18px;padding:10px"); v.addWidget(self.notes)
        h=QHBoxLayout()
        for text,fn in [("▶ Sitzung starten",self.start_session),("⏸ Pause/Fortsetzen",self.pause),("■ Sitzung beenden",self.end_session),("💾 Speichern",self.save_session)]: 
            b=QPushButton(text); b.setMinimumHeight(55); b.clicked.connect(fn); h.addWidget(b)
        v.addLayout(h); return w
    def start_session(self):
        now=datetime.now(); self.s_date.setDate(QDate.currentDate()); self.s_start.setTime(QTime.currentTime()); self.started=now; self.acc=0; self.running=True
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
        self.running=False; self.s_end.setTime(QTime.currentTime())
    def save_session(self):
        last=self.s_last.text().strip(); first=self.s_first.text().strip()
        if not last or not first:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
        c=next((x for x in DB["clients"] if x["last"].lower()==last.lower() and x["first"].lower()==first.lower()),None)
        if not c:c={"last":last,"first":first,"dob":self.s_dob.text().strip()}; DB["clients"].append(c)
        mins=max(1,round(self.elapsed()/60))
        rec={"id":datetime.now().strftime("%Y%m%d%H%M%S"),"last":last,"first":first,"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"minutes":mins,"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"billed":False}
        DB["sessions"].append(rec); save_data(); d=client_dir(c)/"Sitzungen"; (d/f"{rec['date']}_Sitzung.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
        QMessageBox.information(self,"Gespeichert",f"Sitzung gespeichert: {mins} Minuten.")
    def invoice_ui(self):
        w=QWidget(); v=QVBoxLayout(w); f=QFormLayout()
        self.i_no=QLineEdit(next_no()); self.i_last=QLineEdit(); self.i_first=QLineEdit(); self.i_addr=QLineEdit(); self.i_diag=QLineEdit()
        self.i_date=QDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigt")
        for a,b in [("Rechnungsnummer",self.i_no),("Nachname",self.i_last),("Vorname",self.i_first),("Adresse (optional)",self.i_addr),("Diagnose (optional)",self.i_diag),("Leistungsdatum",self.i_date),("Leistung",self.i_type),("Dauer Minuten",self.i_min)]:f.addRow(a,b)
        f.addRow("",self.i_red); v.addLayout(f); b=QPushButton("PDF-Rechnung erstellen"); b.setMinimumHeight(60); b.clicked.connect(self.make_invoice); v.addWidget(b); return w
    def make_invoice(self):
        no=self.i_no.text().strip()
        if any(x["number"]==no for x in DB["invoices"]):return QMessageBox.warning(self,"Doppelt","Diese Rechnungsnummer existiert bereits.")
        last,first=self.i_last.text().strip(),self.i_first.text().strip()
        if not last or not first:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
        mins=self.i_min.value(); typ=self.i_type.currentText(); amt=round(amount_for(mins,typ,self.i_red.isChecked()),2)
        c={"last":last,"first":first}; d=client_dir(c)/"Rechnungen"; pdf=d/f"Rechnung_{no}.pdf"
        can=canvas.Canvas(str(pdf),pagesize=A4); W,H=A4
        can.setFont("Helvetica-Bold",13); can.drawString(50,H-55,"Erdoğan Kulanoğlu – Psychologische Privatpraxis")
        can.setFont("Helvetica",9); can.drawString(50,H-72,"Psychologe M. Sc. · Sozialarbeiter B.A. · Heilpraktiker für Psychotherapie")
        can.drawString(50,H-87,"Schönwalder Str. 59, 13585 Berlin · Steuernummer: 19/405/00254")
        can.setFont("Helvetica-Bold",16); can.drawString(50,H-135,f"Rechnung {no}")
        can.setFont("Helvetica",11); y=H-170; can.drawString(50,y,f"{first} {last}"); y-=16
        if self.i_addr.text().strip():can.drawString(50,y,self.i_addr.text().strip()); y-=16
        if self.i_diag.text().strip():can.drawString(50,y,"Diagnose: "+self.i_diag.text().strip()); y-=22
        can.drawString(50,y,f"{self.i_date.date().toString('dd.MM.yyyy')}   {mins} Min.   {typ}"); can.drawRightString(W-50,y,f"{amt:.2f} EUR"); y-=35
        can.setFont("Helvetica-Bold",12); can.drawRightString(W-50,y,f"Gesamt: {amt:.2f} EUR"); y-=35
        can.setFont("Helvetica",9); can.drawString(50,y,"Zahlbar innerhalb von 14 Tagen. Verwendungszweck: "+no); y-=14
        can.drawString(50,y,"IBAN DE13 5001 0517 5404 0811 30 · BIC INGDDEFFXXX"); y-=14
        can.drawString(50,y,"Leistungen als Heilpraktiker sind nach § 4 Nr. 14 Buchstabe a UStG umsatzsteuerbefreit.")
        can.drawString(50,55,"Elektronisch erstellt und ohne Unterschrift/Stempel gültig."); can.save()
        DB["invoices"].append({"number":no,"date":datetime.now().strftime("%Y-%m-%d"),"client":f"{last}, {first}","amount":amt,"status":"offen","paid_date":""}); save_data(); update_excel(); self.i_no.setText(next_no())
        QMessageBox.information(self,"Fertig",f"PDF gespeichert:\n{pdf}")
    def clients_ui(self):
        w=QWidget(); v=QVBoxLayout(w); t=QTableWidget(0,3); t.setHorizontalHeaderLabels(["Nachname","Vorname","Geburtsdatum"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for c in DB["clients"]: r=t.rowCount();t.insertRow(r);[t.setItem(r,j,QTableWidgetItem(str(c.get(k,"")))) for j,k in enumerate(["last","first","dob"])]
        v.addWidget(t); return w
    def dashboard_ui(self):
        w=QWidget(); v=QVBoxLayout(w); y=str(datetime.now().year); billed=sum(float(i["amount"]) for i in DB["invoices"] if str(i["number"]).startswith(y) and i.get("status")!="storniert"); paid=sum(float(i["amount"]) for i in DB["invoices"] if str(i["number"]).startswith(y) and i.get("status")=="bezahlt")
        l=QLabel(f"Jahr {y}\n\nAbgerechnet: {billed:.2f} €\nBezahlt: {paid:.2f} €\nOffen: {billed-paid:.2f} €\n\nDatenordner:\n{ROOT}"); l.setStyleSheet("font-size:22px;padding:25px"); v.addWidget(l); return w
app=QApplication(sys.argv); app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}"); win=Main();win.show();sys.exit(app.exec())
