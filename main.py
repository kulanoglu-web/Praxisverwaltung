import sys, json, os, re, math, shutil
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog)
from PySide6.QtCore import QDate,QTime
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

class InkCanvas(QWidget):
    def __init__(self):
        super().__init__(); self.setMinimumHeight(300); self.setAttribute(Qt.WA_StaticContents); self.image=QImage(1200,700,QImage.Format_ARGB32); self.image.fill(Qt.white); self.last=QPoint(); self.drawing=False; self.pen_width=3; self.eraser=False; self.history=[]
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
        self.started=None; self.acc=0; self.running=False; self.restore_draft_pending=True
        tabs=QTabWidget(); self.setCentralWidget(tabs)
        tabs.addTab(self.session_ui(),"Sitzungsnotiz"); tabs.addTab(self.invoice_ui(),"Rechnung"); tabs.addTab(self.clients_ui(),"Klienten"); tabs.addTab(self.invoices_ui(),"Rechnungen"); tabs.addTab(self.dashboard_ui(),"Übersicht")
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.wallclock=QLabel()
        self.statusBar().addPermanentWidget(self.wallclock)
        self.walltimer=QTimer(self); self.walltimer.timeout.connect(self.update_wallclock); self.walltimer.start(1000); self.update_wallclock()
        self.autosave=QTimer(self); self.autosave.timeout.connect(self.autosave_session); self.autosave.start(15000)
        QTimer.singleShot(500,self.restore_draft)
    def update_wallclock(self):
        self.wallclock.setText("Aktuelle Uhrzeit  "+datetime.now().strftime("%H:%M:%S"))
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
        self.s_last.editingFinished.connect(self.fill_session_client); self.s_first.editingFinished.connect(self.fill_session_client)
        f.addRow("",self.s_red); v.addLayout(f)
        self.notes=QTextEdit(); self.notes.setPlaceholderText("Therapienotizen per Tastatur …"); self.notes.setMinimumHeight(180); self.notes.setStyleSheet("font-size:18px;padding:10px"); v.addWidget(self.notes)
        inkhead=QHBoxLayout(); inkhead.addWidget(QLabel("Handschrift / Touch / Stift"))
        self.ink=InkCanvas()
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo)
        eraser=QCheckBox("Radierer"); eraser.toggled.connect(self.ink.set_eraser)
        width=QSpinBox(); width.setRange(1,10); width.setValue(3); width.setSuffix(" px"); width.valueChanged.connect(self.ink.set_width)
        clearink=QPushButton("Zeichenfläche löschen"); clearink.clicked.connect(self.ink.clear)
        inkhead.addStretch(); inkhead.addWidget(QLabel("Stärke")); inkhead.addWidget(width); inkhead.addWidget(eraser); inkhead.addWidget(undo); inkhead.addWidget(clearink); v.addLayout(inkhead)
        v.addWidget(self.ink)
        h=QHBoxLayout()
        for text,fn in [("▶ Sitzung starten",self.start_session),("⏸ Pause/Fortsetzen",self.pause),("■ Sitzung beenden",self.end_session),("💾 Speichern",self.save_session)]: 
            b=QPushButton(text); b.setMinimumHeight(55); b.clicked.connect(fn); h.addWidget(b)
        v.addLayout(h); return w
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
        if not c:c={"last":last,"first":first,"dob":self.s_dob.text().strip(),"address":"","diagnosis":""}; DB["clients"].append(c)
        else: c["dob"]=self.s_dob.text().strip() or c.get("dob","")
        mins=max(1,round(self.elapsed()/60))
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
        total=sum(amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))) for s in rows)
        QMessageBox.information(self,"Quartals-/Sammelrechnung",f"{len(rows)} unberechnete Sitzungen gefunden.\nGesamt: {total:.2f} €\nBeim Erstellen der Rechnung werden alle Positionen übernommen.")
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
            for x in (ROOT/"Einnahmen").glob("*.xlsx"): shutil.copy2(x,dest/x.name)
            QMessageBox.information(self,"Sicherung",f"Sicherung erstellt:\n{dest}")
        backup.clicked.connect(do_backup); h.addWidget(backup); v.addLayout(h); return w
    def dashboard_ui(self):
        w=QWidget(); v=QVBoxLayout(w); y=str(datetime.now().year); billed=sum(float(i["amount"]) for i in DB["invoices"] if str(i["number"]).startswith(y) and i.get("status")!="storniert"); paid=sum(float(i["amount"]) for i in DB["invoices"] if str(i["number"]).startswith(y) and i.get("status")=="bezahlt")
        l=QLabel(f"Jahr {y}\n\nAbgerechnet: {billed:.2f} €\nBezahlt: {paid:.2f} €\nOffen: {billed-paid:.2f} €\n\nDatenordner:\n{ROOT}"); l.setStyleSheet("font-size:22px;padding:25px"); v.addWidget(l); return w
app=QApplication(sys.argv); app.setStyleSheet("QPushButton{font-size:16px;padding:8px} QLineEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox{font-size:16px;padding:7px}"); win=Main();win.show();sys.exit(app.exec())
