import sys
import subprocess, json, os, re, math, shutil, sqlite3, base64, hashlib, tempfile, time
from pathlib import Path
from datetime import datetime, date, timedelta
from PySide6.QtCore import QSize, QRect, QObject, Qt, QTimer, QPoint, QUrl, QEvent, Signal, QThread
from PySide6.QtWidgets import (QColorDialog,QGroupBox,QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QTextEdit,QComboBox,QCheckBox,QPushButton,QLabel,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox,QHeaderView,QDialog,QDialogButtonBox,QFileDialog,QSplitter,QListWidget,QListWidgetItem,QStackedWidget,QFrame,QGridLayout,QInputDialog,QScrollArea,QSlider,QSizePolicy,QCalendarWidget,QCompleter)
from PySide6.QtCore import QDate,QTime
from PySide6.QtWidgets import QTextBrowser
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QTextCharFormat, QImage, QPainter, QPen, QPixmap, QDesktopServices, QFont, QColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from cryptography.fernet import Fernet, InvalidToken

APP_VERSION = "0.21.0"
ROOT=Path.home()/"Documents"/"Praxisverwaltung"
DBDIR=ROOT/"Datenbank"; DBFILE=DBDIR/"Praxisverwaltung.db"
KEYFILE=DBDIR/"praxis.key"

KEYFILE_PROT=DBDIR/"praxis.key.dpapi"
_KEY_CACHE=None

def _dpapi(data,protect):
    """Windows-DPAPI: bindet Daten an das angemeldete Windows-Benutzerkonto."""
    if os.name!="nt": raise OSError("DPAPI ist nur unter Windows verfügbar")
    import ctypes
    from ctypes import wintypes
    class BLOB(ctypes.Structure): _fields_=[("cbData",wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_char))]
    buf=ctypes.create_string_buffer(data,len(data)); inb=BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_char))); out=BLOB()
    crypt32=ctypes.windll.crypt32; kernel32=ctypes.windll.kernel32; kernel32.LocalFree.argtypes=[ctypes.c_void_p]
    fn=crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inb),None,None,None,None,0,ctypes.byref(out)): raise OSError("Windows-Schlüsselschutz meldet einen Fehler")
    try: return ctypes.string_at(out.pbData,out.cbData)
    finally: kernel32.LocalFree(out.pbData)

def key_is_protected(): return KEYFILE_PROT.exists()

def encryption_key():
    global _KEY_CACHE
    if _KEY_CACHE is not None: return _KEY_CACHE
    DBDIR.mkdir(parents=True,exist_ok=True)
    if KEYFILE_PROT.exists():
        try: _KEY_CACHE=_dpapi(KEYFILE_PROT.read_bytes(),False); return _KEY_CACHE
        except Exception as e:
            raise RuntimeError("Der Datenschlüssel konnte nicht entschlüsselt werden. Er ist an ein anderes Windows-Konto oder einen anderen PC gebunden. Bitte den Wiederherstellungsschlüssel (.key) über 'Datensicherung wiederherstellen' einspielen.") from e
    if KEYFILE.exists(): _KEY_CACHE=KEYFILE.read_bytes(); return _KEY_CACHE
    key=Fernet.generate_key(); KEYFILE.write_bytes(key)
    try: os.chmod(KEYFILE,0o600)
    except Exception: pass
    _KEY_CACHE=key; return key

def protect_key_file():
    """Klartext-Schlüsseldatei durch eine an das Windows-Konto gebundene Datei ersetzen. Gibt (ok, Meldung) zurück.
    Der Klartextschlüssel wird erst gelöscht, nachdem die geschützte Datei nachweislich wieder entschlüsselt werden kann."""
    try:
        if os.name!="nt": return False,"Der Schlüsselschutz ist nur unter Windows verfügbar."
        if KEYFILE_PROT.exists(): return True,"Der Schlüssel ist bereits geschützt."
        if not KEYFILE.exists(): return False,"Es wurde keine Schlüsseldatei gefunden."
        raw=KEYFILE.read_bytes(); blob=_dpapi(raw,True); tmp=KEYFILE_PROT.with_suffix(".tmp"); tmp.write_bytes(blob)
        if _dpapi(tmp.read_bytes(),False)!=raw:
            tmp.unlink(missing_ok=True); return False,"Die Prüfung des geschützten Schlüssels ist fehlgeschlagen. Es wurde nichts verändert."
        tmp.replace(KEYFILE_PROT)
        try: KEYFILE.write_bytes(b"0"*len(raw))
        except Exception: pass
        KEYFILE.unlink(missing_ok=True)
        global _KEY_CACHE; _KEY_CACHE=raw
        return True,"Der Schlüssel ist jetzt an Ihr Windows-Benutzerkonto gebunden."
    except Exception as e:
        return False,"Der Schlüssel konnte nicht geschützt werden (unverändert gelassen): "+str(e)[:300]

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
    stroke_started=Signal()
    stroke_finished=Signal()
    def __init__(self):
        super().__init__(); self.rev=0; self.setMinimumHeight(220); self.setAttribute(Qt.WA_StaticContents); self.image=QImage(1200,700,QImage.Format_ARGB32); self.image.fill(Qt.white); self.last=QPoint(); self.drawing=False; self.pen_width=3; self.pen_color=QColor('#000000'); self.eraser=False; self.history=[]; self.strokes=[]; self._cur=None; self.strokes_ok=True
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
        if e.button()==Qt.LeftButton:self.history.append(self.image.copy()); self.history=self.history[-30:]; self.last=self.pointer(e);self.drawing=True; self.rev+=1; self._cur=[(e.position().x(),e.position().y())]; self.stroke_started.emit()
    def mouseMoveEvent(self,e):
        if self.drawing:
            p=self.pointer(e); q=QPainter(self.image); q.setRenderHint(QPainter.Antialiasing); q.setPen(QPen(Qt.white if self.eraser else self.pen_color,self.pen_width if not self.eraser else max(12,self.pen_width*4),Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin)); q.drawLine(self.last,p); q.end(); self.last=p; self.update()
            if self.eraser: self.strokes_ok=False
            elif self._cur is not None: self._cur.append((e.position().x(),e.position().y()))
    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton:
            self.drawing=False
            if self._cur and not self.eraser and len(self._cur)>=1:
                if len(self._cur)==1: self._cur.append((self._cur[0][0]+0.5,self._cur[0][1]+0.5))
                self.strokes.append(self._cur)
            self._cur=None; self.stroke_finished.emit()
    def clear(self): self.history.append(self.image.copy()); self.image.fill(Qt.white); self.strokes=[]; self.strokes_ok=True; self.rev+=1; self.update()
    def set_stroke_data(self,data):
        try:
            self.strokes=[[(float(x),float(y)) for x,y in st] for st in data["strokes"]]; self.strokes_ok=bool(self.strokes)
        except Exception: self.strokes=[]; self.strokes_ok=False
    def stroke_data(self):
        """Striche für die Windows-Handschrifterkennung (Rohkoordinaten) oder None, wenn nicht verfügbar."""
        return {"w":self.width(),"h":self.height(),"strokes":[[ [round(x,1),round(y,1)] for x,y in st] for st in self.strokes]} if self.strokes and self.strokes_ok else None
    def undo(self):
        if self.history:
            self.image=self.history.pop(); self.rev+=1; self.update()
            if self.strokes: self.strokes.pop()
    def set_eraser(self,on): self.eraser=on
    def set_width(self,w): self.pen_width=w
    def set_color(self,c): self.pen_color=QColor(c); self.eraser=False
    def save_png(self,path,stamp=None):
        """Speichert die Handschrift. Mit stamp wird oben eine Kopfzeile (z. B. Klient, Datum, Uhrzeit) eingefügt."""
        if not stamp: return self.image.save(str(path),"PNG")
        head=64; img=QImage(self.image.width(),self.image.height()+head,QImage.Format_ARGB32); img.fill(Qt.white)
        q=QPainter(img); q.drawImage(0,head,self.image); q.setPen(QColor("#17324d")); f=QFont(); f.setPointSize(16); f.setBold(True); q.setFont(f)
        q.drawText(QRect(16,0,img.width()-32,head),Qt.AlignVCenter|Qt.AlignLeft,stamp); q.setPen(QColor("#b8c7d4")); q.drawLine(0,head-1,img.width(),head-1); q.end()
        return img.save(str(path),"PNG")
    def load_png(self,path):
        p=Path(path); img=QImage()
        if p.suffix==".enc":
            raw=decrypt_file_bytes(p); img.loadFromData(raw,"PNG")
        else: img=QImage(str(path))
        if not img.isNull(): self.image=img.convertToFormat(QImage.Format_ARGB32).scaled(1200,700,Qt.IgnoreAspectRatio,Qt.SmoothTransformation); self.history=[]; self.strokes=[]; self.strokes_ok=False; self.update(); return True
        return False

OCR_PS_COMMON = r"""$ErrorActionPreference='Stop'
try{ [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false) }catch{}
try{ [Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false) }catch{}
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
# Die richtige AsTask-Überladung (IAsyncOperation) gezielt wählen, nicht einfach die erste generische.
$asTask=([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op,$type){ $t=$asTask.MakeGenericMethod($type).Invoke($null,@($op)); [void]$t.Wait(-1); return $t.Result }

# Handschrift-Erkennung als Text einlesen: ein Fehler darin darf die normale Texterkennung nicht lahmlegen.
$inkSrc=@'
function Recognize-Ink($path,$pref){
  $null=[Windows.UI.Input.Inking.InkStrokeBuilder,Windows.UI.Input.Inking,ContentType=WindowsRuntime]
  $null=[Windows.UI.Input.Inking.InkStrokeContainer,Windows.UI.Input.Inking,ContentType=WindowsRuntime]
  $null=[Windows.UI.Input.Inking.InkRecognizerContainer,Windows.UI.Input.Inking,ContentType=WindowsRuntime]
  $null=[Windows.UI.Input.Inking.InkRecognitionResult,Windows.UI.Input.Inking,ContentType=WindowsRuntime]
  # Windows.Foundation.Point ist in System.Runtime.WindowsRuntime enthalten und braucht kein Vorladen.
  $data=[IO.File]::ReadAllText($path,[Text.Encoding]::UTF8) | ConvertFrom-Json
  $container=New-Object Windows.UI.Input.Inking.InkStrokeContainer
  $builder=New-Object Windows.UI.Input.Inking.InkStrokeBuilder
  $n=0
  foreach($st in $data.strokes){
    $pts=New-Object 'System.Collections.Generic.List[Windows.Foundation.Point]'
    foreach($pt in $st){ $pts.Add((New-Object Windows.Foundation.Point([single]$pt[0],[single]$pt[1]))) }
    if($pts.Count -lt 2){ continue }
    $container.AddStroke($builder.CreateStroke($pts)); $n++
  }
  if($n -eq 0){ throw 'KEINE_STRICHE' }
  $rc=New-Object Windows.UI.Input.Inking.InkRecognizerContainer
  $recs=@($rc.GetRecognizers())
  if($recs.Count -eq 0){ throw 'KEIN_HANDSCHRIFT_ERKENNER' }
  $want=@{'de-DE'='German|Deutsch|de-DE';'tr-TR'='Turk|Türk|tr-TR';'en-US'='English|Englisch|en-US'}
  $rx=$want[$pref]; if(-not $rx){ $rx='German|Deutsch|de-DE' }
  $pick=$recs | Where-Object { $_.Name -match $rx } | Select-Object -First 1
  if($pick){ $rc.SetDefaultRecognizer($pick) }
  $listType=[System.Collections.Generic.IReadOnlyList[Windows.UI.Input.Inking.InkRecognitionResult]]
  $res=Await ($rc.RecognizeAsync($container,[Windows.UI.Input.Inking.InkRecognitionTarget]::All)) $listType
  $out=@(); $line=''; $lastY=$null
  foreach($r in $res){
    $c=@($r.GetTextCandidates()); if($c.Count -eq 0){ continue }
    $t=[string]$c[0]; $best=-1000
    foreach($cand in $c){
      $cs=[string]$cand; $letters=([regex]::Matches($cs,'[\p{L}]')).Count; $odd=([regex]::Matches($cs,'[^\p{L}\p{N}\s\.,\-:;!\?\(\)/]')).Count
      $sc=$letters-(3*$odd); if($sc -gt $best){ $best=$sc; $t=$cs }
    }
    $b=$r.BoundingRect
    if($null -ne $lastY -and ([math]::Abs($b.Y-$lastY) -gt [math]::Max(25,$b.Height*0.8))){ $out+=$line; $line=$t } else { $line=($line+' '+$t).Trim() }
    $lastY=$b.Y
  }
  if($line){ $out+=$line }
  return $out
}
'@
try{ Invoke-Expression $inkSrc }catch{}
$engines=@{}
function Get-Engine($pref){
  $order=@(); if($pref){ $order+=$pref }; $order+=@('de-DE','tr-TR','en-US')
  foreach($tag in $order){
    if($engines.ContainsKey($tag)){ if($engines[$tag]){ return $engines[$tag] }; continue }
    $eng=$null
    try{ $lang=New-Object Windows.Globalization.Language($tag); if([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)){ $eng=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang) } }catch{}
    $engines[$tag]=$eng
    if($eng){ return $eng }
  }
  return [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
function Recognize($path,$pref){
  if($path.EndsWith('.json')){ if(-not (Get-Command Recognize-Ink -ErrorAction SilentlyContinue)){ throw 'HANDSCHRIFTMODUL_FEHLT' }; return (Recognize-Ink $path $pref) }
  # Datei als .NET-Stream öffnen und ohne asynchronen Aufruf in einen WinRT-Stream wandeln (zuverlässiger als StorageFile.OpenAsync).
  $fs=$null
  try{
    $fs=[System.IO.File]::Open($path,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
    $stream=[System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
  }catch{
    if($fs){ try{$fs.Dispose()}catch{} }; $fs=$null
    $file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  }
  try{
    $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  } finally { try{ $stream.Dispose() }catch{}; if($fs){ try{$fs.Dispose()}catch{} } }
  $engine=Get-Engine $pref
  if(-not $engine){ throw 'KEINE_OCR_SPRACHE' }
  $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $out=@(); foreach($l in $result.Lines){ $out+=$l.Text }
  return $out
}
"""

# Einmaliger Aufruf (Rückfallebene)
OCR_PS_ONESHOT = OCR_PS_COMMON + r"""
try{
  $lines=Recognize $env:PRAXISPRO_OCR_PATH $env:PRAXISPRO_OCR_LANG
  [Console]::Out.Write(($lines -join "`n"))
}catch{ [Console]::Error.Write($_.Exception.Message); exit 1 }
"""

# Dauerhaft laufender Dienst: PowerShell wird nur einmal gestartet, jede Erkennung dauert danach nur Sekundenbruchteile.
OCR_PS_SERVER = OCR_PS_COMMON + r"""
[Console]::Out.WriteLine('<<READY>>'); [Console]::Out.Flush()
while($true){
  $line=[Console]::In.ReadLine()
  if($null -eq $line -or $line -eq 'QUIT'){ break }
  try{
    $parts=$line.Split('|',2)
    $path=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($parts[1]))
    $lines=Recognize $path $parts[0]
    foreach($l in $lines){ [Console]::Out.WriteLine('L:'+$l) }
    [Console]::Out.WriteLine('<<END>>')
  }catch{ [Console]::Out.WriteLine('<<ERR>>'+(($_.Exception.Message) -replace '[\r\n]+',' ')) }
  [Console]::Out.Flush()
}
"""

OCR_LANGS = {"Deutsch":"de-DE","Türkisch":"tr-TR","Englisch":"en-US"}

def prepare_ink_for_ocr(image):
    """Handschrift für die Windows-Texterkennung aufbereiten: auf die Schrift zuschneiden, Zeilenhöhe auf eine
    für die Erkennung günstige Größe bringen, schwarz auf weiß mit Rand. Gibt None zurück, wenn nichts geschrieben wurde."""
    if image is None or image.isNull(): return None
    q=4
    small=image.convertToFormat(QImage.Format_Grayscale8).scaled(max(1,image.width()//q),max(1,image.height()//q),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
    rows=[0]*small.height(); x0=10**9; x1=-1
    for y in range(small.height()):
        for x in range(small.width()):
            if small.pixelColor(x,y).red()<235:
                rows[y]+=1
                if x<x0:x0=x
                if x>x1:x1=x
    ys=[y for y,c in enumerate(rows) if c>0]
    if not ys or x1<0: return None
    y0,y1=ys[0],ys[-1]
    # Textzeilen als zusammenhängende Bänder erkennen (Lücken bis 2 Zeilen werden überbrückt)
    bands=[]; start=ys[0]; prev=ys[0]
    for y in ys[1:]:
        if y-prev>3: bands.append((start,prev)); start=y
        prev=y
    bands.append((start,prev))
    heights=sorted((b-a+1)*q for a,b in bands); med=heights[len(heights)//2]
    m=12
    cx0=max(0,(x0-m)*q); cy0=max(0,(y0-m)*q); cx1=min(image.width(),(x1+m+1)*q); cy1=min(image.height(),(y1+m+1)*q)
    crop=image.copy(cx0,cy0,max(8,cx1-cx0),max(8,cy1-cy0)).convertToFormat(QImage.Format_RGB32)
    # dünne Stiftstriche leicht verstärken (Windows-OCR erkennt dünne Linien schlecht)
    th=QImage(crop.size(),QImage.Format_RGB32); th.fill(Qt.white); pt0=QPainter(th); pt0.setCompositionMode(QPainter.CompositionMode_Darken)
    for dx,dy in ((0,0),(1,0),(0,1),(1,1),(-1,0),(0,-1)): pt0.drawImage(dx,dy,crop)
    pt0.end(); crop=th
    scale=max(0.5,min(2.5,64.0/max(8,med)))
    out=QImage(crop.width()+120,crop.height()+120,QImage.Format_RGB32); out.fill(Qt.white)
    pt=QPainter(out); pt.drawImage(60,60,crop); pt.end()
    if abs(scale-1)>0.08: out=out.scaled(max(16,int(out.width()*scale)),max(16,int(out.height()*scale)),Qt.KeepAspectRatio,Qt.SmoothTransformation)
    # Mindestgröße, damit Windows nicht an sehr kleinen Bildern scheitert
    if out.width()<260 or out.height()<90:
        big=QImage(max(260,out.width()),max(90,out.height()),QImage.Format_RGB32); big.fill(Qt.white)
        pt=QPainter(big); pt.drawImage(0,0,out); pt.end(); out=big
    return out

import threading, queue

class OcrServer:
    """Dauerhaft laufender PowerShell-Prozess für die Windows-Texerkennung (startet nur einmal)."""
    def __init__(self,command=None):
        self.command=command; self.proc=None; self.q=queue.Queue(); self.lock=threading.Lock(); self.script=None
    def _start(self):
        tmpdir=Path(tempfile.gettempdir())
        if self.command is None:
            self.script=tmpdir/f"PraxisPro_OCR_server_{os.getpid()}.ps1"; self.script.write_text(OCR_PS_SERVER,encoding="utf-8-sig")
            cmd=["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(self.script)]
        else: cmd=list(self.command)
        flags=0x08000000 if os.name=="nt" else 0
        self.proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=flags)
        self.q=queue.Queue(); proc=self.proc; q=self.q
        def reader():
            try:
                for raw in iter(proc.stdout.readline,b""): q.put(raw.decode("utf-8-sig",errors="replace").rstrip("\r\n"))
            finally: q.put(None)
        threading.Thread(target=reader,daemon=True).start()
        first=self.q.get(timeout=45)
        if first!="<<READY>>": raise RuntimeError("OCR-Dienst nicht gestartet")
    def stop(self):
        try:
            if self.proc and self.proc.poll() is None: self.proc.kill()
        except Exception: pass
        self.proc=None
    def recognize(self,png_path,lang,timeout=40):
        """Gibt den erkannten Text zurück oder löst RuntimeError aus (Meldung z. B. 'KEINE_OCR_SPRACHE')."""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None: self._start()
            while not self.q.empty(): self.q.get_nowait()
            b64=base64.b64encode(str(Path(png_path).resolve()).encode("utf-8")).decode("ascii")
            try:
                self.proc.stdin.write((lang+"|"+b64+"\n").encode("ascii")); self.proc.stdin.flush()
                lines=[]
                while True:
                    item=self.q.get(timeout=timeout)
                    if item is None: raise RuntimeError("OCR-Dienst wurde beendet")
                    if item=="<<END>>": return "\n".join(lines).strip()
                    if item.startswith("<<ERR>>"): raise RuntimeError(item[7:] or "Unbekannter Fehler")
                    if item.startswith("L:"): lines.append(item[2:])
            except queue.Empty:
                self.stop(); raise RuntimeError("Zeitüberschreitung der Texterkennung")
            except (BrokenPipeError,OSError):
                self.stop(); raise RuntimeError("OCR-Dienst nicht erreichbar")

_OCR_SERVER=None
OCR_LAST_INK_NOTE=""

def run_windows_ocr(image,lang="de-DE",strokes=None):
    """Gibt (text, fehlermeldung) zurück. Läuft komplett lokal über die Windows-Texterkennung."""
    global _OCR_SERVER, OCR_LAST_INK_NOTE
    OCR_LAST_INK_NOTE=""
    if os.name!="nt": return "", "Die Handschrift-Erkennung ist nur unter Windows verfügbar."
    prepared=prepare_ink_for_ocr(image)
    if prepared is None: return "", "LEER"
    tmpdir=Path(tempfile.gettempdir()); stamp=f"{os.getpid()}_{int(time.time()*1000)}"
    # 1) echte Handschrifterkennung anhand der Striche (erkennt auch Schreibschrift); 2) sonst Texterkennung auf dem Bild
    if strokes:
        js=tmpdir/f"PraxisPro_INK_{stamp}.json"
        try:
            js.write_text(json.dumps(strokes),encoding="utf-8")
            if _OCR_SERVER is None: _OCR_SERVER=OcrServer()
            txt=_OCR_SERVER.recognize(js,lang)
            if txt.strip(): return txt.strip(),""
            audit("INK_RECOGNIZER_EMPTY","leer"); OCR_LAST_INK_NOTE="Der Handschrift-Erkenner hat nichts geliefert."
        except Exception as e:
            audit("INK_RECOGNIZER_FALLBACK",str(e)[:300]); OCR_LAST_INK_NOTE=str(e)[:300]
        finally:
            try: js.unlink(missing_ok=True)
            except Exception: pass
    png=tmpdir/f"PraxisPro_OCR_{stamp}.png"
    try:
        if not prepared.save(str(png),"PNG"): return "", "Die Zeichenfläche konnte nicht vorbereitet werden."
        def lang_msg(): return "Windows hat keine Texterkennungs-Sprache installiert.\n\nBitte unter Einstellungen → Zeit & Sprache → Sprache & Region die Sprache Deutsch hinzufügen (bei den Sprachoptionen Texterkennung/OCR mit installieren) und PraxisPro neu starten."
        # 1) schneller Dauerdienst
        try:
            if _OCR_SERVER is None: _OCR_SERVER=OcrServer()
            out=_OCR_SERVER.recognize(png,lang)
            return (out,"") if out else ("","KEIN_TEXT")
        except RuntimeError as e:
            if "KEINE_OCR_SPRACHE" in str(e): return "", lang_msg()
            server_error=str(e)
        except Exception as e: server_error=str(e)
        # 2) Rückfallebene: einmaliger Aufruf
        ps1=tmpdir/f"PraxisPro_OCR_{stamp}.ps1"
        try:
            ps1.write_text(OCR_PS_ONESHOT,encoding="utf-8-sig")
            env=os.environ.copy(); env["PRAXISPRO_OCR_PATH"]=str(png.resolve()); env["PRAXISPRO_OCR_LANG"]=lang
            run=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(ps1)],env=env,capture_output=True,timeout=60,creationflags=0x08000000)
            out=run.stdout.decode("utf-8-sig",errors="replace").strip(); err=run.stderr.decode("utf-8",errors="replace").strip()
            if run.returncode!=0:
                if "KEINE_OCR_SPRACHE" in err: return "", lang_msg()
                return "", (err or server_error or "Unbekannter Fehler der Windows-Texterkennung.")[:900]
            return (out,"") if out else ("","KEIN_TEXT")
        finally:
            try: ps1.unlink(missing_ok=True)
            except Exception: pass
    except subprocess.TimeoutExpired:
        return "", "Die Texterkennung hat zu lange gebraucht (Zeitüberschreitung)."
    except Exception as e:
        return "", str(e)[:900]
    finally:
        try: png.unlink(missing_ok=True)
        except Exception: pass

class OcrWorker(QThread):
    done=Signal(str,str,int,bool)
    def __init__(self,image,rev,manual,lang="de-DE",strokes=None):
        super().__init__(); self.image=image; self.rev=rev; self.manual=manual; self.lang=lang; self.strokes=strokes
    def run(self):
        text,err=run_windows_ocr(self.image,self.lang,self.strokes); self.done.emit(text,err,self.rev,self.manual)

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
        # Der Resolver entscheidet nur, ob die Bilddatei vorhanden ist.
        # Das tatsächliche Decodieren/Zeichnen erfolgt erst im PDF-Renderer,
        # damit ein CI-/ReportLab-Decoderfehler nicht ein vorhandenes Standardlogo
        # fälschlich zu "nicht vorhanden" macht.
        try:
            p = Path(path)
            if p.is_file() and p.stat().st_size > 0:
                return p
        except Exception as e:
            audit("INVOICE_LOGO_PATH_ERROR", f"{path} :: {str(e)[:200]}")
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
    # Das mitgelieferte Standardlogo muss vom PDF-Renderer wirklich lesbar sein.
    # Beschädigte Altdateien werden übersprungen, statt die Rechnung abzubrechen.
    for logo_name in ("logo.jpg", "logo.jpeg", "logo.png"):
        bundled = bundled_asset(logo_name)
        if bundled is not None:
            candidates.append(bundled)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for logo_name in ("logo.jpg", "logo.jpeg", "logo.png"):
            candidates += [
                exe_dir / "_internal" / "assets" / logo_name,
                exe_dir / "assets" / logo_name,
            ]
    for logo_name in ("logo.jpg", "logo.jpeg", "logo.png"):
        candidates.append(Path(__file__).resolve().parent / "assets" / logo_name)

    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ok = usable(candidate)
        if ok is None:
            continue
        try:
            probe = ImageReader(str(ok))
            probe.getSize()
            probe.getRGBData()
            audit("INVOICE_LOGO_SOURCE", f"bundled:{ok}")
            return ok
        except Exception as e:
            audit("INVOICE_LOGO_INVALID", f"{ok} :: {str(e)[:200]}")

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
    if "pin_hash" not in ucols: con.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
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
    apcols=[r[1] for r in con.execute("PRAGMA table_info(appointments)").fetchall()]
    if "series_id" not in apcols: con.execute("ALTER TABLE appointments ADD COLUMN series_id TEXT")
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
    for name,mins,amount,reduced,mode in [("Einzeltherapie",45,70,60,"proportional"),("Paargespräch",45,70,60,"proportional"),("Onlinegespräch",45,70,60,"proportional"),("Notfalltelefonat",30,45,45,"started_unit"),("Hausbesuch",45,70,60,"proportional_plus_travel"),("Ausfallhonorar",45,70,70,"fixed")]:
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

def user_pin_set(username):
    try:
        con=sqlite3.connect(DBFILE); r=con.execute("SELECT pin_hash FROM users WHERE username=?",(username,)).fetchone(); con.close(); return bool(r and r[0])
    except Exception: return False

def set_user_pin(username,pin):
    con=sqlite3.connect(DBFILE); con.execute("UPDATE users SET pin_hash=? WHERE username=?",(password_hash("pin:"+pin) if pin else None,username)); con.commit(); con.close()

def check_user_pin(username,pin):
    try:
        con=sqlite3.connect(DBFILE); r=con.execute("SELECT pin_hash FROM users WHERE username=?",(username,)).fetchone(); con.close()
        if r is None: return False
        if not r[0]: return pin=="0000"   # Standard-PIN, solange keine eigene gesetzt ist
        return verify_password("pin:"+pin,r[0])
    except Exception: return False

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
DB=load_data(); DB.setdefault("clients",[]); DB.setdefault("sessions",[]); DB.setdefault("invoices",[]); DB.setdefault("waitlist",[]); DB.setdefault("todos",[]); DB.setdefault("expenses",[]); DB.setdefault("cash",[])
init_sqlite(); sync_sqlite()

def save_data():
    DATA.write_text(encrypt_text(json.dumps(DB,ensure_ascii=False)),encoding="utf-8")
    sync_sqlite()

def safe(s): return re.sub(r'[<>:"/\\|?*]','_',s).strip()

import invoice_pdf
from flexwidgets import FlexTimeEdit, FlexDateEdit, FlowLayout

INVOICE_SETTING_DEFAULTS={"owner_name":"","practice_name":"","qualifications":"","practice_subtitle":"","address":"","phone":"","landline":"","fax":"",
    "email":"info@psychologe-spandau.de","website":"www.psychologe-spandau.de","tax_number":"19/405/00254","iban":"DE13 5001 0517 5404 0811 30",
    "bic":"INGDDEFFXXX","paypal":"erdogankulanoglu@hotmail.com","paypal_me":"","logo_width_mm":"72","logo_height_mm":"22","logo_x_mm":"18","logo_y_mm":"7","invoice_header_logo_zone":"Links"}

def invoice_settings():
    return {k:str(get_setting(k,v)) for k,v in INVOICE_SETTING_DEFAULTS.items()}

def _de_date(value):
    try: return datetime.strptime(str(value),"%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception: return str(value)

def write_invoice_pdf(inv,mode,out_path,reminder_level=1,paid_date="",due_text="",user=""):
    """Erzeugt Rechnung (invoice), beglichene Rechnung mit Dank (paid) oder Zahlungserinnerung (reminder) aus einem Rechnungsdatensatz."""
    last,_,first=str(inv.get("client","")).partition(", ")
    client=next((x for x in DB["clients"] if x.get("last","").lower()==last.lower() and x.get("first","").lower()==first.lower()),{})
    items=[]
    for it in inv.get("items") or []:
        items.append({"date":_de_date(it.get("date","")),"iso":str(it.get("date","")),"type":it.get("type","") or "Leistung","minutes":int(it.get("minutes",0)),"amount":float(it.get("amount",0))})
    if not items: items=[{"date":_de_date(inv.get("date","")),"iso":str(inv.get("date","")),"type":"Leistung","minutes":0,"amount":float(inv.get("amount",0))}]
    isos=sorted(x["iso"] for x in items if x["iso"])
    period=(_de_date(isos[0]) if len(set(isos))<=1 and isos else (_de_date(isos[0])+" - "+_de_date(isos[-1]) if isos else _de_date(inv.get("date",""))))
    d={"number":inv.get("number",""),"date":_de_date(inv.get("date","")),"period":period,"first":first,"last":last,"address":inv.get("address",""),
       "salutation":salutation_for(client),
       "amount":float(inv.get("amount",0)),"items":items,"mode":mode,"reminder_level":reminder_level,"paid_date":paid_date,"due_text":due_text}
    return invoice_pdf.render_invoice_pdf(out_path,d,invoice_settings(),practice_logo_path(),bundled_asset("paypal.png"),lambda code,text: audit(code,text,user))

import document_pdf, document_templates

def practice_city():
    m=re.search(r"\b\d{5}\s+([^,\n]+)",get_setting("address",""))
    return m.group(1).strip() if m else ""

def fee_table_text():
    rows=["Leistung | Dauer | Honorar"]
    for name,minutes,amount,reduced,_mode in get_fee_rates():
        price=invoice_pdf.eur(amount)+(f" (ermäßigt {invoice_pdf.eur(reduced)})" if reduced and float(reduced)>0 and float(reduced)!=float(amount) else "")
        rows.append(f"{name} | {int(minutes)} Min. | {price}" if minutes else f"{name} | – | {price}")
    return "\n".join(rows) if len(rows)>1 else "Honorar nach gesonderter Absprache."

def client_sessions(c):
    return sorted([x for x in DB["sessions"] if x.get("last","").lower()==c.get("last","").lower() and x.get("first","").lower()==c.get("first","").lower()],key=lambda x:(x.get("date",""),x.get("start","")))

def document_values(c,recipient=""):
    """Werte für die Platzhalter der Dokumentvorlagen (document_templates.PLACEHOLDERS)."""
    c=c or {}; s=invoice_settings(); sess=client_sessions(c) if c else []
    dates=[_de_date(x.get("date","")) for x in sess if x.get("date")]
    sesslist="\n".join(["Datum | Art | Dauer"]+[f"{_de_date(x.get('date',''))} | {x.get('type','') or 'Sitzung'} | {int(x.get('minutes',0) or 0)} Min." for x in sess]) if sess else "(noch keine Sitzungen dokumentiert)"
    anrede=(salutation_for(c)+" "+c.get("last","")).strip() if c else "Sehr geehrte Damen und Herren"
    rec_first=(recipient or "").strip().splitlines()[0] if (recipient or "").strip() else ""
    return {"klient_name":(c.get("first","")+" "+c.get("last","")).strip() or "____________________",
        "klient_vorname":c.get("first",""),"klient_nachname":c.get("last",""),
        "klient_geburtsdatum":c.get("dob","") or "__________","klient_adresse":c.get("address","") or "______________________________",
        "klient_telefon":c.get("phone",""),"klient_email":c.get("email",""),"anrede":"Sehr geehrte Kollegin, sehr geehrter Kollege" if rec_first.lower().startswith(("dr","praxis","herr dr","frau dr")) else "Sehr geehrte Damen und Herren",
        "klient_anrede":anrede,"kostentraeger":" – ".join(x for x in (c.get("payer",""),c.get("insurer","")) if x) or "__________",
        "versicherungsnummer":c.get("insurance_no","") or "__________","diagnose":c.get("diagnosis","") or "______________________________",
        "therapeut":s.get("owner_name","") or "____________________","qualifikation":s.get("qualifications",""),
        "praxis_name":s.get("practice_name","") or "Psychologische Privatpraxis","praxis_adresse":s.get("address",""),
        "praxis_telefon":s.get("phone","") or s.get("landline",""),"praxis_email":s.get("email",""),
        "ort":practice_city(),"datum":datetime.now().strftime("%d.%m.%Y"),
        "empfaenger":", ".join(x.strip() for x in (recipient or "").splitlines() if x.strip()) or "______________________________",
        "honorar_tabelle":fee_table_text(),"absagefrist":get_setting("doc_cancel_notice","24 Stunden"),
        "erste_sitzung":dates[0] if dates else "__________","letzte_sitzung":dates[-1] if dates else "__________",
        "anzahl_sitzungen":str(len(sess)),"sitzungsliste":sesslist}

def document_template_text(key):
    return get_setting("doc_tpl_"+key,"") or document_templates.TEMPLATES[key]["text"]

def write_document_pdf(c,key,body,recipient="",place_date="",signatures=None,user=""):
    """Erzeugt ein Praxisdokument im Klientenordner unter „Dokumente“. signatures: {"client":png,"therapist":png}."""
    tpl=document_templates.TEMPLATES[key]; s=invoice_settings(); signatures=signatures or {}
    folder=client_dir(c)/"Dokumente"; stamp=datetime.now()
    out=folder/f"{stamp.strftime('%Y-%m-%d')}_{safe(tpl['title'])}.pdf"
    if out.exists(): out=folder/f"{stamp.strftime('%Y-%m-%d_%H%M%S')}_{safe(tpl['title'])}.pdf"
    name=(c.get("first","")+" "+c.get("last","")).strip()
    sigs=[("Unterschrift Klient/in" if who=="client" else "Unterschrift Therapeut/in",signatures.get(who),name if who=="client" else s.get("owner_name","")) for who in tpl["signatures"]]
    ref=""  # Klientenname steht in jeder Vorlage bereits im Text
    recipient_lines=[x for x in (recipient or "").splitlines() if x.strip()] if tpl["recipient"] else None
    document_pdf.render_document_pdf(out,tpl["title"],body,s,practice_logo_path(),recipient_lines,sigs,place_date,ref,lambda code,text: audit(code,text,user))
    audit("DOCUMENT_CREATED",f"{tpl['title']}: {c.get('last','')}, {c.get('first','')}",user)
    return out

# Stammdaten einer Klientenakte, nach Bereichen gegliedert. Gespeichert im verschlüsselten Datenbestand (DB["clients"]).
# Art: "text" (einzeilig), "multi" (mehrzeilig), oder eine Liste = Auswahlfeld.
PAYERS=["Selbstzahler","Private Krankenversicherung","Beihilfe + PKV","Heilpraktiker-Zusatzversicherung","Sonstiger Kostenträger"]
CLIENT_FIELDS=[
    ("Person",[("last","Nachname *","text"),("first","Vorname *","text"),("gender","Geschlecht (für die Anrede)",["","weiblich","männlich","divers"]),("dob","Geburtsdatum","text"),
               ("phone","Telefon","text"),("email","E-Mail","text"),("address","Anschrift","text")]),
    ("Kostenträger",[("payer","Abrechnung",PAYERS),("insurer","Versicherung / Kostenträger","text"),("insurance_no","Versicherungs-/Mitgliedsnummer","text"),("session_quota","Bewilligte Sitzungen (Kontingent, optional)","text")]),
    ("Notfallkontakt",[("emergency_name","Name","text"),("emergency_relation","Beziehung","text"),("emergency_phone","Telefon","text")]),
    ("Ärztliche Versorgung",[("physician","Hausarzt / überweisende Ärztin","multi"),("prior_treatment","Vorbehandlung / Vorbehandler","multi")]),
    ("Klinisch",[("diagnosis","Diagnose (optional)","text"),("referral_source","Wie auf die Praxis aufmerksam geworden","text")]),
]
CLIENT_KEYS=[k for _,fields in CLIENT_FIELDS for k,_,_ in fields]

def resolve_client(d):
    """Auswahllisten (QComboBox.itemData) liefern nur eine KOPIE des Klienten-Datensatzes.
    Vor jeder Änderung muss deshalb das Original aus DB["clients"] verwendet werden."""
    if not isinstance(d,dict): return None
    for c in DB["clients"]:
        if c is d: return c
    key=lambda x:(str(x.get("last","")).strip().lower(),str(x.get("first","")).strip().lower(),str(x.get("dob","")).strip())
    return next((c for c in DB["clients"] if key(c)==key(d)),None)

ACTIVE_APPT_STATUS=("geplant","erschienen")   # abgesagte/ausgefallene Termine geben den Platz frei

def appointment_conflict(day,start,minutes,exclude_id=None,con=None):
    """Prüft, ob sich ein Termin mit einem bestehenden (geplant/erschienen) überschneidet. Liefert die Startzeit des belegten Termins oder None."""
    own=con is None; con=con or sqlite3.connect(DBFILE)
    try:
        s=datetime.strptime(start,"%H:%M"); e=s+timedelta(minutes=int(minutes))
        for eid,estart,emin in con.execute("SELECT id,start_time,minutes FROM appointments WHERE appointment_date=? AND status IN (?,?)",(day,)+ACTIVE_APPT_STATUS).fetchall():
            if exclude_id is not None and eid==exclude_id: continue
            es=datetime.strptime(estart,"%H:%M"); ee=es+timedelta(minutes=int(emin))
            if s<ee and e>es: return estart
        return None
    finally:
        if own: con.close()

def client_key(c):
    return hashlib.sha256((str(c.get("first","")).strip().lower()+"|"+str(c.get("last","")).strip().lower()+"|"+str(c.get("dob","")).strip()).encode("utf-8")).hexdigest()

def sqlite_client_id(c):
    """ID des Klienten in der SQLite-Tabelle (für Termine). None, wenn noch nicht synchronisiert."""
    if not c: return None
    con=sqlite3.connect(DBFILE); row=con.execute("SELECT id FROM clients WHERE client_key=? ORDER BY id DESC LIMIT 1",(client_key(c),)).fetchone(); con.close()
    return row[0] if row else None

def client_for_sqlite_id(cid):
    if not cid: return None
    con=sqlite3.connect(DBFILE); row=con.execute("SELECT client_key FROM clients WHERE id=?",(cid,)).fetchone(); con.close()
    return next((c for c in DB["clients"] if row and client_key(c)==row[0]),None)

def client_session_stats(c):
    """Sitzungszähler: dokumentierte Sitzungen, künftig geplante Termine, Kontingent und Rest."""
    done=len(client_sessions(c)) if c else 0; planned=0
    cid=sqlite_client_id(c)
    if cid:
        con=sqlite3.connect(DBFILE); planned=con.execute("SELECT COUNT(*) FROM appointments WHERE client_id=? AND status='geplant' AND appointment_date>=?",(cid,date.today().isoformat())).fetchone()[0]; con.close()
    try: quota=int(str((c or {}).get("session_quota","")).strip() or 0)
    except ValueError: quota=0
    return {"done":done,"planned":planned,"quota":quota,"left":(quota-done) if quota else None}

def session_stats_text(c):
    st=client_session_stats(c)
    t=f"Sitzungen bisher: {st['done']}  ·  geplant: {st['planned']}"
    if st["quota"]:
        t+=f"  ·  Kontingent: {st['done']} von {st['quota']}"
        if st["left"]<=0: t+="  ⚠ ausgeschöpft"
        elif st["done"]+st["planned"]>st["quota"]: t+=f"  ⚠ geplante Termine übersteigen das Kontingent (noch {st['left']} frei)"
        elif st["left"]<=2: t+=f"  ⚠ nur noch {st['left']} frei"
        else: t+=f"  (noch {st['left']} frei)"
    return t

def salutation_for(c):
    g=str((c or {}).get("gender","")).lower()
    if g.startswith("w"): return "Sehr geehrte Frau"
    if g.startswith("m"): return "Sehr geehrter Herr"
    return ("Guten Tag "+str((c or {}).get("first","")).strip()).strip()   # wird mit dem Nachnamen ergänzt

class ClientForm(QWidget):
    """Alle Stammdatenfelder einer Klientenakte, in Karten gruppiert. Für Anlegen und Bearbeiten."""
    def __init__(self,cc=None,columns=2):
        super().__init__(); self.fields={}
        grid=QGridLayout(self); grid.setContentsMargins(0,0,0,0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        for i,(group,items) in enumerate(CLIENT_FIELDS):
            box=QFrame(); box.setObjectName("formCard"); bv=QVBoxLayout(box); bv.setContentsMargins(14,10,14,12)
            gt=QLabel(group); gt.setObjectName("sectionTitle"); bv.addWidget(gt)
            form=QFormLayout(); form.setVerticalSpacing(8); form.setLabelAlignment(Qt.AlignLeft); form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for key,label,kind in items:
                if isinstance(kind,list): ed=QComboBox(); ed.addItems(kind); ed.setEditable(key=="payer")
                elif kind=="multi": ed=QTextEdit(); ed.setAcceptRichText(False); ed.setFixedHeight(64)
                else: ed=QLineEdit()
                if key=="dob": ed.setPlaceholderText("TT.MM.JJJJ")
                if key=="emergency_phone": ed.setPlaceholderText("im Notfall erreichbar")
                ed.setMinimumHeight(32) if not isinstance(ed,QTextEdit) else None
                self.fields[key]=ed; form.addRow(label,ed)
            bv.addLayout(form)
            # zweispaltig: Person links (zwei Zeilen hoch), Kostenträger und Notfallkontakt rechts, darunter Ärztliches und Klinisches
            pos={0:(0,0,2,1),1:(0,1,1,1),2:(1,1,1,1),3:(2,0,1,1),4:(2,1,1,1)}[i] if columns==2 else (i,0,1,1)
            grid.addWidget(box,*pos)
        if columns==2: grid.setColumnStretch(0,1); grid.setColumnStretch(1,1)
        self.set_values(cc or {})
    def value(self,key):
        ed=self.fields[key]
        if isinstance(ed,QComboBox): return ed.currentText().strip()
        if isinstance(ed,QTextEdit): return ed.toPlainText().strip()
        return ed.text().strip()
    def values(self): return {k:self.value(k) for k in CLIENT_KEYS}
    def set_values(self,cc):
        for k,ed in self.fields.items():
            val=str(cc.get(k,"") or "")
            if isinstance(ed,QComboBox):
                if k=="payer" and not val: val="Selbstzahler"
                i=ed.findText(val)
                if i>=0: ed.setCurrentIndex(i)
                elif ed.isEditable(): ed.setEditText(val)
            elif isinstance(ed,QTextEdit): ed.setPlainText(val)
            else: ed.setText(val)
    def clear(self): self.set_values({})

def client_form_dialog(parent,title,cc=None):
    """Dialog mit allen Stammdaten. Liefert die eingegebenen Werte oder None (abgebrochen)."""
    dlg=QDialog(parent); dlg.setWindowTitle(title); v=QVBoxLayout(dlg)
    ag=QApplication.primaryScreen().availableGeometry(); dlg.resize(min(1000,int(ag.width()*0.9)),min(760,int(ag.height()*0.88)))
    form=ClientForm(cc); sc=QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(form); v.addWidget(sc,1)
    buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); v.addWidget(buttons); result={}
    def ok():
        vals=form.values()
        if not vals["last"] or not vals["first"]: return QMessageBox.warning(dlg,"Fehlt","Vorname und Nachname sind erforderlich.")
        result.update(vals); dlg.accept()
    buttons.accepted.connect(ok); buttons.rejected.connect(dlg.reject)
    return result if dlg.exec()==QDialog.Accepted else None

# ---------------------------------------------------------------- Dokumentenablage der Klientenakte
DOC_CATEGORIES=["Arztbrief / Befund","Vertrag / Einwilligung (unterschrieben)","Bescheinigung","Korrespondenz","Sonstiges"]
VIEW_DIR=Path(tempfile.gettempdir())/"PraxisPro_Ansicht"

def clear_view_dir():
    """Entschlüsselte Ansichtskopien entfernen (beim Start und vor jedem Öffnen). Geöffnete Dateien bleiben bis zum nächsten Mal."""
    if VIEW_DIR.exists():
        for f in VIEW_DIR.iterdir():
            try: f.unlink()
            except Exception: pass

def client_documents(c):
    """Alle Dateien im Ordner Dokumente: erstellte PDFs (unverschlüsselt) und importierte Dateien (.enc)."""
    folder=client_dir(c)/"Dokumente"; out=[]
    for f in folder.iterdir():
        if not f.is_file() or f.name.startswith("."): continue
        shown=f.name[:-4] if f.suffix==".enc" else f.name
        out.append({"path":str(f),"name":shown,"encrypted":f.suffix==".enc","mtime":f.stat().st_mtime})
    return sorted(out,key=lambda d:d["mtime"],reverse=True)

def import_client_document(c,src,category):
    """Kopiert eine Datei verschlüsselt in die Klientenakte. Das Original bleibt unverändert."""
    src=Path(src); folder=client_dir(c)/"Dokumente"
    base=f"{datetime.now().strftime('%Y-%m-%d')}_{safe(category.split(' /')[0].split(' (')[0])}_{safe(src.stem)}{src.suffix.lower()}"
    target=folder/base; n=2
    while target.exists() or Path(str(target)+".enc").exists(): target=folder/f"{Path(base).stem}_{n}{Path(base).suffix}"; n+=1
    data=src.read_bytes(); Path(str(target)+".enc").write_bytes(Fernet(encryption_key()).encrypt(data))
    return str(target)+".enc"

def open_client_document(path):
    """Öffnet ein Dokument; verschlüsselte Dateien werden in einen temporären Ansichtsordner entschlüsselt."""
    p=Path(path)
    if p.suffix!=".enc": QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))); return str(p)
    VIEW_DIR.mkdir(parents=True,exist_ok=True); clear_view_dir()
    out=VIEW_DIR/p.name[:-4]; out.write_bytes(decrypt_file_bytes(p)); QDesktopServices.openUrl(QUrl.fromLocalFile(str(out))); return str(out)

def client_dir(c):
    p=ROOT/"Klienten"/safe(f"{c.get('last','')}, {c.get('first','')}")
    for x in ["Stammdaten","Sitzungen","Rechnungen","Dokumente"]:(p/x).mkdir(parents=True,exist_ok=True)
    return p

def client_folder(last,first):
    """Ordner eines Klienten (wird bei Bedarf angelegt)."""
    return client_dir({"last":last,"first":first})

def strip_ink_header(img):
    """Gespeicherte Handschriften haben oben eine 64-px-Kopfzeile (Name, Datum). Für die Texterkennung abschneiden."""
    try:
        if img.height()>80 and img.width()>20:
            c=img.pixelColor(10,63)
            if abs(c.red()-184)<14 and abs(c.green()-199)<14 and abs(c.blue()-212)<14: return img.copy(0,64,img.width(),img.height()-64)
    except Exception: pass
    return img


def image_to_strokes(image):
    """Aus einem gespeicherten Handschrift-Bild näherungsweise Striche rekonstruieren (Mittellinien), damit auch ältere
    Notizen ohne gespeicherte Strichdaten mit dem Windows-Handschrifterkenner gelesen werden können."""
    try:
        if image is None or image.isNull(): return None
        k=2; W=image.width(); H=image.height()
        g=image.convertToFormat(QImage.Format_Grayscale8).scaled(max(1,W//k),max(1,H//k),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
        fg=set()
        for y in range(g.height()):
            for x in range(g.width()):
                if g.pixelColor(x,y).red()<170: fg.add((x,y))
        if len(fg)<8 or len(fg)>250000: return None
        nb=[(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1)]
        def neigh(pt,S): return [(pt[0]+dx,pt[1]+dy) in S for dx,dy in nb]
        for _ in range(60):
            changed=False
            for step in (0,1):
                rem=[]
                for pt in fg:
                    p=neigh(pt,fg); n=sum(p)
                    if n<2 or n>6: continue
                    a=sum(1 for i in range(8) if (not p[i]) and p[(i+1)%8])
                    if a!=1: continue
                    if step==0:
                        if p[0] and p[2] and p[4]: continue
                        if p[2] and p[4] and p[6]: continue
                    else:
                        if p[0] and p[2] and p[6]: continue
                        if p[0] and p[4] and p[6]: continue
                    rem.append(pt)
                if rem:
                    changed=True
                    for pt in rem: fg.discard(pt)
            if not changed: break
        if len(fg)<4: return None
        def build_adj(): return {pt:[(pt[0]+dx,pt[1]+dy) for dx,dy in nb if (pt[0]+dx,pt[1]+dy) in fg] for pt in fg}
        adj=build_adj()
        # kurze Seitenäste (Skelett-Stacheln) entfernen
        for e0 in [pt for pt,a in adj.items() if len(a)==1]:
            path=[e0]; prev=None; cur=e0; hit=False
            for _ in range(5):
                nx=[q for q in adj.get(cur,[]) if q!=prev and q not in path]
                if len(nx)!=1:
                    hit=len(nx)>=2; break
                prev=cur; cur=nx[0]
                if len(adj.get(cur,[]))>=3: hit=True; break
                path.append(cur)
            if hit and len(path)<=4:
                for q in path: fg.discard(q)
        adj=build_adj()
        ends=sorted([pt for pt,a in adj.items() if len(a)==1])
        visited=set(); strokes=[]
        def walk(start):
            path=[start]; visited.add(start); cur=start
            while True:
                nxt=[q for q in adj[cur] if q not in visited]
                if not nxt: break
                if len(path)>=2:
                    dx=cur[0]-path[-2][0]; dy=cur[1]-path[-2][1]
                    nxt.sort(key=lambda q:-((q[0]-cur[0])*dx+(q[1]-cur[1])*dy))
                cur=nxt[0]; path.append(cur); visited.add(cur)
            return path
        for st in ends+sorted(fg):
            if st in visited: continue
            path=walk(st)
            strokes.append(path if len(path)>=2 else [path[0],(path[0][0]+1,path[0][1]+1)])
        if not strokes: return None
        # Zeilen bestimmen (Zeilenprofil der Mittellinien), je Zeile von links nach rechts sortieren
        hist={}
        for (x,y) in set(q for pth in strokes for q in pth): hist[y]=hist.get(y,0)+1
        ymax=max(hist); sm=[sum(hist.get(y+d,0) for d in (-1,0,1))/3.0 for y in range(ymax+2)]
        thr=0.12*max(sm); bands=[]; cur=None
        for y,v in enumerate(sm):
            if v>=thr:
                if cur is None: cur=[y,y]
                else: cur[1]=y
            elif cur is not None:
                if bands and cur[0]-bands[-1][1]<=3: bands[-1][1]=cur[1]
                else: bands.append(cur)
                cur=None
        if cur is not None: bands.append(cur)
        bands=[b for b in bands if b[1]-b[0]>=3] or [[0,ymax]]
        groups=[[] for _ in bands]
        for pth in strokes:
            ym=sorted(q[1] for q in pth)[len(pth)//2]
            idx=min(range(len(bands)),key=lambda i:0 if bands[i][0]<=ym<=bands[i][1] else min(abs(ym-bands[i][0]),abs(ym-bands[i][1])))
            groups[idx].append(pth)
        def smooth(p):
            if len(p)<5: return p
            o=[p[0]]
            for i in range(1,len(p)-1): o.append((sum(p[j][0] for j in range(i-1,i+2))/3.0,sum(p[j][1] for j in range(i-1,i+2))/3.0))
            o.append(p[-1]); return o
        def conv(p):
            p=smooth(p); q2=p[::2]+([p[-1]] if len(p)%2==0 else [])
            return [[round(q[0]*k,1),round(q[1]*k,1)] for q in q2]
        lines=[]; allst=[]
        for b,gr in zip(bands,groups):
            gr.sort(key=lambda p:min(q[0] for q in p)); cs=[c for c in (conv(p) for p in gr) if len(c)>=2]
            if cs: lines.append({"y0":b[0]*k,"y1":(b[1]+1)*k,"strokes":cs}); allst+=cs
        if not allst: return None
        return {"w":W,"h":H,"strokes":allst,"lines":lines}
    except Exception:
        return None

def recognize_saved_handwriting(image,lang,strokes=None):
    """Gespeicherte Handschrift in Text umwandeln: mit gespeicherten Strichen, sonst aus dem Bild rekonstruierten Strichen,
    zuletzt reine Bild-Texterkennung. Gibt (text, fehler) zurück."""
    img=strip_ink_header(image)
    if strokes:
        text,err=run_windows_ocr(img,lang,strokes)
        if text and text.strip(): return text,err
    rec=image_to_strokes(img)
    if rec:
        texts=[]
        for ln in rec.get("lines") or []:
            y0=max(0,int(ln["y0"])-12); y1=min(img.height(),int(ln["y1"])+12)
            if y1-y0<8: continue
            sub={"w":rec["w"],"h":y1-y0,"strokes":ln["strokes"]}
            t,e=run_windows_ocr(img.copy(0,y0,img.width(),y1-y0),lang,sub)
            if t and t.strip(): texts.append(t.strip())
        if texts: return "\n".join(texts),""
        text,err=run_windows_ocr(img,lang,{"w":rec["w"],"h":rec["h"],"strokes":rec["strokes"]})
        if text and text.strip(): return text,""
    return run_windows_ocr(img,lang,None)

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

class PinPad(QDialog):
    """Großes Zahlenfeld für eine 4-stellige PIN (touch-tauglich). check(pin) -> Fehlertext oder '' (= ok)."""
    def __init__(self,parent,title,prompt,check=None,cancel=True,alt_text=None):
        super().__init__(parent); self.setWindowTitle(title); self.setModal(True); self.pin=""; self.check=check; self.alt_used=False; self._cancel=cancel; self.setMinimumWidth(340)
        v=QVBoxLayout(self); v.setSpacing(10); v.setContentsMargins(24,20,24,20)
        t=QLabel(title); t.setAlignment(Qt.AlignCenter); t.setStyleSheet("font-size:22px;font-weight:800;color:#17324d"); v.addWidget(t)
        self.prompt=QLabel(prompt); self.prompt.setAlignment(Qt.AlignCenter); self.prompt.setWordWrap(True); v.addWidget(self.prompt)
        self.dots=QLabel("○ ○ ○ ○"); self.dots.setAlignment(Qt.AlignCenter); self.dots.setStyleSheet("font-size:34px;letter-spacing:4px;color:#17324d"); v.addWidget(self.dots)
        self.msg=QLabel(""); self.msg.setAlignment(Qt.AlignCenter); self.msg.setWordWrap(True); self.msg.setStyleSheet("color:#b3261e;font-weight:600"); v.addWidget(self.msg)
        g=QGridLayout(); g.setSpacing(8)
        def mk(txt,fn):
            b=QPushButton(txt); b.setMinimumSize(86,60); b.setStyleSheet("font-size:24px;font-weight:700"); b.setFocusPolicy(Qt.NoFocus); b.clicked.connect(fn); return b
        for i in range(1,10): g.addWidget(mk(str(i),lambda _=False,d=str(i):self.press(d)),(i-1)//3,(i-1)%3)
        self.back=mk("⌫",lambda _=False:self.erase()); g.addWidget(self.back,3,0); g.addWidget(mk("0",lambda _=False:self.press("0")),3,1)
        if cancel: g.addWidget(mk("✕",lambda _=False:self.reject()),3,2)
        v.addLayout(g)
        if alt_text:
            alt=QPushButton(alt_text); alt.setFlat(True); alt.setFocusPolicy(Qt.NoFocus); alt.clicked.connect(self.use_alt); v.addWidget(alt)
    def use_alt(self): self.alt_used=True; self.done(2)
    def refresh(self): self.dots.setText(" ".join("●" if i<len(self.pin) else "○" for i in range(4)))
    def erase(self): self.pin=self.pin[:-1]; self.refresh()
    def disable_pad(self):
        for b in self.findChildren(QPushButton):
            if b.text()!="✕" and not b.isFlat(): b.setEnabled(False)
    def press(self,d):
        if len(self.pin)>=4: return
        self.pin+=d; self.refresh(); self.msg.setText("")
        if len(self.pin)==4: QTimer.singleShot(120,self.finish)
    def finish(self):
        err=self.check(self.pin) if self.check else ""
        if err: self.msg.setText(err); self.pin=""; self.refresh(); return
        self.accept()
    def keyPressEvent(self,e):
        if e.text().isdigit() and len(e.text())==1: self.press(e.text()); return
        if e.key() in (Qt.Key_Backspace,Qt.Key_Delete): self.erase(); return
        if e.key()==Qt.Key_Escape and not self._cancel: return
        super().keyPressEvent(e)
    def reject(self):
        if self._cancel: super().reject()

class NavList(QListWidget):
    """Seitenmenü mit Bereichsüberschriften. Nach außen arbeitet es mit Seitennummern
    (Index im QStackedWidget): setCurrentRow(seite), currentRowChanged -> seite, count() = Anzahl Seiten.
    Überschriften sind nicht auswählbar; die Reihenfolge im Menü ist unabhängig von den Seitennummern."""
    pageChanged=Signal(int)
    def __init__(self):
        super().__init__(); self._page_of_row={}; self._row_of_page={}; self.entries=[]
        super().currentRowChanged.connect(self._row_changed)
    def add_section(self,title):
        it=QListWidgetItem(title.upper()); it.setFlags(Qt.NoItemFlags); it.setData(Qt.UserRole,"section")
        f=it.font(); f.setBold(True); f.setLetterSpacing(QFont.PercentageSpacing,108); it.setFont(f)
        it.setSizeHint(QSize(10,23)); self.addItem(it)
    def add_page(self,icon,label,page):
        it=QListWidgetItem(f"{icon}   {label}"); it.setData(Qt.UserRole,page); it.setSizeHint(QSize(10,29)); self.addItem(it)
        row=super().count()-1; self._page_of_row[row]=page; self._row_of_page[page]=row; self.entries.append((row,icon,label))
    def count(self): return len(self._row_of_page)
    def page_label(self,page):
        row=self._row_of_page.get(page)
        return next((lab for r,_,lab in self.entries if r==row),"")
    def setCurrentRow(self,page):
        row=self._row_of_page.get(page)
        if row is not None: super().setCurrentRow(row)
    def currentPage(self): return self._page_of_row.get(super().currentRow(),-1)
    def _row_changed(self,row):
        if row in self._page_of_row: self.pageChanged.emit(self._page_of_row[row])
    def set_compact(self,compact):
        for i in range(super().count()):
            it=self.item(i)
            if it.data(Qt.UserRole)=="section": it.setHidden(compact); continue
        for row,icon,label in self.entries:
            it=self.item(row); it.setToolTip(label)
            it.setText(icon if compact else f"{icon}   {label}"); it.setTextAlignment(Qt.AlignCenter if compact else Qt.AlignLeft|Qt.AlignVCenter)

class SignaturePad(QWidget):
    """Unterschriftsfeld für Maus, Finger oder Stift. Speichert als PNG mit transparentem Hintergrund."""
    changed=Signal()
    def __init__(self,placeholder="Hier unterschreiben"):
        super().__init__(); self.placeholder=placeholder; self.setMinimumHeight(110); self.setMinimumWidth(200)
        self.strokes=[]; self._cur=None; self.setCursor(Qt.CrossCursor); self.setAttribute(Qt.WA_StaticContents)
    def is_empty(self): return not any(len(s)>1 for s in self.strokes)
    def clear(self): self.strokes=[]; self._cur=None; self.update(); self.changed.emit()
    def _pt(self,e): return (e.position().x()/max(1,self.width()),e.position().y()/max(1,self.height()))
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton: self._cur=[self._pt(e)]; self.strokes.append(self._cur); self.update()
    def mouseMoveEvent(self,e):
        if self._cur is not None: self._cur.append(self._pt(e)); self.update()
    def mouseReleaseEvent(self,e):
        if self._cur is not None:
            if len(self._cur)==1: self._cur.append((self._cur[0][0]+0.002,self._cur[0][1]+0.002))
            self._cur=None; self.changed.emit()
    def _draw(self,p,w,h,width):
        p.setRenderHint(QPainter.Antialiasing); p.setPen(QPen(QColor("#0b2a4a"),width,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        for s in self.strokes:
            for a,b in zip(s,s[1:]): p.drawLine(QPoint(int(a[0]*w),int(a[1]*h)),QPoint(int(b[0]*w),int(b[1]*h)))
    def paintEvent(self,e):
        p=QPainter(self); p.fillRect(self.rect(),QColor("white"))
        p.setPen(QPen(QColor("#c5d0c9"),1,Qt.DashLine)); p.drawRect(self.rect().adjusted(0,0,-1,-1))
        base=int(self.height()*0.78); p.setPen(QPen(QColor("#9fb3a6"),1)); p.drawLine(14,base,self.width()-14,base)
        if self.is_empty():
            p.setPen(QColor("#9aa8a0")); p.drawText(self.rect().adjusted(0,0,0,-int(self.height()*0.3)),Qt.AlignCenter,self.placeholder)
        self._draw(p,self.width(),self.height(),2.2); p.end()
    def save_png(self,path):
        w,h=900,300; img=QImage(w,h,QImage.Format_ARGB32); img.fill(Qt.transparent)
        p=QPainter(img); self._draw(p,w,h,5); p.end(); return img.save(str(path),"PNG")

class ScoreChart(QWidget):
    """Verlaufskurve (eine Reihe): Werte über die Zeit, optional mit beschrifteten Bereichen (z. B. Schweregrade).
    points: [(Datumstext, Wert, Tooltip)], bands: [(Obergrenze, Bezeichnung)]."""
    def __init__(self,title=""):
        super().__init__(); self.title=title; self.points=[]; self.bands=[]; self.vmax=10; self._xy=[]
        self.setMinimumHeight(230); self.setMouseTracking(True)
    def set_data(self,points,vmax,bands=None,title=None):
        self.points=list(points); self.vmax=max(1,vmax); self.bands=bands or []
        if title is not None: self.title=title
        self.update()
    def paintEvent(self,e):
        p=QPainter(self); p.setRenderHint(QPainter.Antialiasing); r=self.rect()
        p.fillRect(r,QColor("white"))
        ink=QColor("#26322c"); muted=QColor("#6b7a72"); grid=QColor("#e3e9e5"); line=QColor("#4c735d")
        f=QFont(self.font()); f.setPointSizeF(max(8.0,f.pointSizeF()-1)); p.setFont(f); fm=p.fontMetrics()
        L,R,T,B=44,(110 if self.bands else 18),28 if self.title else 12,30
        w=max(10,r.width()-L-R); h=max(10,r.height()-T-B)
        if self.title:
            tf=QFont(f); tf.setBold(True); p.setFont(tf); p.setPen(ink); p.drawText(L,18,self.title); p.setFont(f)
        y_of=lambda v: T+h-(v/self.vmax)*h
        # Bereiche: eine Farbe, von hell (gering) nach etwas kräftiger (schwer), mit Text rechts
        lo=0
        tints=["#f6f8f6","#eef3ef","#e3ebe5","#d6e2da","#c9d9cf","#bccfc3"]
        for i,(upper,label) in enumerate(self.bands):
            top=y_of(min(upper+1,self.vmax)) if i<len(self.bands)-1 else y_of(self.vmax); bot=y_of(lo)
            p.fillRect(QRect(L,int(top),w,int(bot-top)),QColor(tints[min(i,len(tints)-1)]))
            p.setPen(muted); p.drawText(QRect(L+w+8,int(top),R-10,int(bot-top)),Qt.AlignVCenter|Qt.AlignLeft,f"{label} ({lo}–{upper})")
            lo=upper+1
        # Raster und y-Achse (zurückhaltend)
        steps=[x for x in range(0,int(self.vmax)+1) if x%(5 if self.vmax>12 else 2)==0]
        for v in steps:
            y=int(y_of(v)); p.setPen(QPen(grid,1)); p.drawLine(L,y,L+w,y)
            p.setPen(muted); p.drawText(QRect(0,y-9,L-8,18),Qt.AlignRight|Qt.AlignVCenter,str(v))
        self._xy=[]
        if not self.points:
            p.setPen(muted); p.drawText(QRect(L,T,w,h),Qt.AlignCenter,"Noch keine Werte"); p.end(); return
        n=len(self.points)
        xs=[L+w/2] if n==1 else [L+12+i*(w-24)/(n-1) for i in range(n)]
        pts=[(xs[i],y_of(v)) for i,(_,v,_) in enumerate(self.points)]
        p.setPen(QPen(line,2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        for a,b in zip(pts,pts[1:]): p.drawLine(QPoint(int(a[0]),int(a[1])),QPoint(int(b[0]),int(b[1])))
        every=max(1,int(n/max(1,w//70)))
        for i,((x,y),(lab,v,tip)) in enumerate(zip(pts,self.points)):
            p.setPen(QPen(QColor("white"),2)); p.setBrush(line); p.drawEllipse(QPoint(int(x),int(y)),5,5)
            if i%every==0 or i==n-1:
                p.setPen(muted); p.drawText(QRect(int(x)-40,T+h+6,80,18),Qt.AlignHCenter|Qt.AlignTop,lab)
            self._xy.append((x,y,tip))
        # letzter Wert direkt beschriftet
        x,y,_=self._xy[-1]; p.setPen(ink); bf=QFont(f); bf.setBold(True); p.setFont(bf)
        p.drawText(QRect(int(x)-30,int(y)-26,60,18),Qt.AlignCenter,str(self.points[-1][1]))
        p.end()
    def mouseMoveEvent(self,e):
        from PySide6.QtWidgets import QToolTip
        pos=e.position()
        best=min(self._xy,key=lambda t:(t[0]-pos.x())**2+(t[1]-pos.y())**2,default=None)
        if best and (best[0]-pos.x())**2+(best[1]-pos.y())**2<26**2: QToolTip.showText(e.globalPosition().toPoint(),best[2],self)
        else: QToolTip.hideText()

class QuestionnaireForm(QWidget):
    """Fragebogen mit Antwortknöpfen 0–3 je Item. large=True: große Ansicht zum Ausfüllen durch Klient/in am Tablet."""
    changed=Signal()
    def __init__(self,kind,large=False):
        super().__init__(); import questionnaires as Q
        from PySide6.QtWidgets import QButtonGroup, QRadioButton
        self.kind=kind; q=Q.QUESTIONNAIRES[kind]; self.groups=[]
        v=QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(10 if large else 6)
        stem=QLabel(q["stem"]); stem.setWordWrap(True); stem.setStyleSheet(f"font-weight:700;font-size:{22 if large else 14}px"); v.addWidget(stem)
        for i,text in enumerate(q["items"]):
            box=QFrame(); box.setObjectName("formCard"); bv=QVBoxLayout(box); bv.setContentsMargins(12,8,12,8); bv.setSpacing(6)
            lab=QLabel(f"{i+1}. {text}"); lab.setWordWrap(True); lab.setStyleSheet(f"font-size:{20 if large else 13}px"); bv.addWidget(lab)
            row=QWidget(); rl=FlowLayout(row,hspacing=14,vspacing=6); rl.setContentsMargins(0,0,0,0); grp=QButtonGroup(self)
            for val,ans in enumerate(Q.ANSWERS):
                rb=QRadioButton(f"{ans} ({val})" if not large else ans); rb.setStyleSheet(f"font-size:{19 if large else 13}px;padding:{8 if large else 2}px")
                grp.addButton(rb,val); rl.addWidget(rb)
            grp.idClicked.connect(lambda *_: self.changed.emit()); bv.addWidget(row); v.addWidget(box); self.groups.append(grp)
    def answers(self): return [g.checkedId() if g.checkedId()>=0 else None for g in self.groups]
    def set_answers(self,ans):
        for g,a in zip(self.groups,ans):
            g.setExclusive(False)
            for b in g.buttons(): b.setChecked(False)
            g.setExclusive(True)
            if a is not None and g.button(int(a)): g.button(int(a)).setChecked(True)
        self.changed.emit()

ANAMNESIS_FIELDS=[
    ("Anlass & Anliegen",[("first_contact","Datum Erstgespräch","line"),("reason","Vorstellungsanlass","multi"),("goal","Anliegen / Auftrag","multi"),("onset","Beginn und Verlauf der Beschwerden","multi")]),
    ("Aktuelle Beschwerden",[("symptoms","Beschwerdebild / Symptomatik","multi"),("impact","Beeinträchtigung in Alltag, Arbeit, Beziehungen","multi")]),
    ("Biografie & Lebenssituation",[("family_origin","Herkunftsfamilie","multi"),("childhood","Kindheit und Jugend","multi"),("education","Schule, Ausbildung, Beruf","multi"),("relationships","Partnerschaft, Kinder, Familie","multi"),("living","Aktuelle Lebenssituation (Wohnen, Finanzen, Belastungen)","multi")]),
    ("Gesundheit",[("somatic","Körperliche Erkrankungen","multi"),("medication","Medikation (Präparat, Dosis, verordnet von)","multi"),("substances","Alkohol, Nikotin, Drogen, Medikamentenmissbrauch","multi"),("prior_psych","Psychiatrische / psychotherapeutische Vorbehandlung","multi")]),
    ("Ressourcen",[("resources","Stärken, Ressourcen, Interessen","multi"),("network","Soziales Netz / Unterstützung","multi")]),
    ("Risikoeinschätzung",[("suicidality","Suizidalität",["nicht erfragt","kein Hinweis","passive Todeswünsche","Suizidgedanken ohne Plan","Suizidgedanken mit Plan oder Absicht"]),
                           ("suicide_attempts","Frühere Suizidversuche",["nicht erfragt","nein","ja"]),
                           ("harm_others","Fremdgefährdung",["nicht erfragt","kein Hinweis","Hinweise vorhanden"]),
                           ("safety_plan","Absprachen / Krisenplan","multi")]),
    ("Befund & Einschätzung",[("findings","Psychischer Befund (Kurzform)","multi"),("hypothesis","Arbeitshypothese / Fallverständnis","multi"),("diagnosis","Diagnose(n) ICD-10 (Verdacht/gesichert)","line"),("plan","Vorgehen / nächste Schritte","multi")]),
]
RISK_LEVELS={"passive Todeswünsche","Suizidgedanken ohne Plan","Suizidgedanken mit Plan oder Absicht"}

# Farbschemata: Seitenleiste, Seitenleistentext, Auswahl, Auswahltext, Hover, Schaltfläche,
# Schaltfläche-Hover, Akzent (Überschriften), Hintergrund, Kopfleiste, Rahmen
THEMES={
    "Salbei":dict(side="#eef2ef",side_text="#33443b",sel="#7d9a88",sel_text="#ffffff",hover="#dde6e0",button="#5f8a72",button_hover="#4c735d",accent="#2c3b33",bg="#f6f8f6",top="#e3ebe5",border="#dbe3dd",section="#8a9a90"),
    "PraxisPro Blau":dict(side="#132f47",side_text="#e5edf3",sel="#2f7de1",sel_text="#ffffff",hover="#244d70",button="#1f6fb2",button_hover="#17324d",accent="#17324d",bg="#f4f6f8",top="#ffffff",border="#d4e0ea",section="#8fa6ba"),
    "Petrol":dict(side="#123c3d",side_text="#e3efef",sel="#22999b",sel_text="#ffffff",hover="#174b4d",button="#177b7d",button_hover="#174b4d",accent="#174b4d",bg="#f2f7f7",top="#ffffff",border="#d2e2e2",section="#86aeae"),
    "Grün":dict(side="#183d2b",side_text="#e3efe7",sel="#3f9b65",sel_text="#ffffff",hover="#205b39",button="#2e7d4f",button_hover="#205b39",accent="#205b39",bg="#f3f7f4",top="#ffffff",border="#d3e2d8",section="#8db39b"),
    "Gold":dict(side="#493b18",side_text="#f3ecd9",sel="#c59a2c",sel_text="#ffffff",hover="#6f5314",button="#9a7417",button_hover="#6f5314",accent="#6f5314",bg="#faf8f2",top="#ffffff",border="#e6dcc4",section="#b9a36f"),
    "Violett":dict(side="#34234d",side_text="#ece5f5",sel="#8b5fc1",sel_text="#ffffff",hover="#513373",button="#7048a3",button_hover="#513373",accent="#513373",bg="#f7f4fa",top="#ffffff",border="#e0d6ec",section="#a58fc2"),
}

class Main(QMainWindow):
    def __init__(self):
        super().__init__(); self.current_user={}; self.last_activity=datetime.now(); self.setWindowTitle(f"PraxisPro v{APP_VERSION} – Erdoğan Kulanoğlu"); self.resize(1280,820); self.setMinimumSize(480,520)
        self.started=None; self.acc=0; self.running=False; self.restore_draft_pending=True
        if get_setting("auto_lock_v2","")!="1": set_setting("auto_lock_minutes","0"); set_setting("auto_lock_v2","1")
        shell=QWidget(); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(235); self.sidebar=sidebar; sv=QVBoxLayout(sidebar); sv.setContentsMargins(12,14,12,14)
        brand=QLabel("PraxisPro"); brand.setObjectName("brand"); sv.addWidget(brand); self.brand_label=brand
        brandsub=QLabel("Version "+APP_VERSION); brandsub.setObjectName("brandSub"); sv.addWidget(brandsub); self.brand_sub=brandsub
        self.nav=NavList(); self.nav.setObjectName("nav"); self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Menü nach Arbeitsbereichen geordnet. Zahl = Seite im Seitenstapel (Reihenfolge unten bei self.pages).
        menu=[("Praxisalltag",[("⌂","Tagesübersicht",0),("▦","Terminkalender",6)]),
              ("Therapie",[("✎","Sitzung dokumentieren",1),("◔","Therapieverlauf",14),("✦","Sitzungsassistent",2)]),
              ("Klienten",[("♙","Klientenakten",3),("＋","Neuer Klient",4),("♥","Paarakte",5),("⏳","Warteliste",13),("✉","Formulare & Briefe",12)]),
              ("Abrechnung",[("€","Neue Rechnung",7),("▤","Rechnungen",8),("▥","Ausgaben & EÜR",15)]),
              ("Wissen & Hilfe",[("📖","Glossar",10),("?","Hilfe · FAQ · Info",11)]),
              ("System",[("⚙","Praxiseinstellungen",9)])]
        for section,items in menu:
            self.nav.add_section(section)
            for icon,label,page in items: self.nav.add_page(icon,label,page)
        sv.addWidget(self.nav,1)
        # Copyright steht unten in der Statusleiste, damit das Menü auch auf kleinen Bildschirmen ganz sichtbar bleibt.
        foot=QLabel(get_setting("copyright","© 2026 Erdoğan Kulanoğlu")); foot.setObjectName("sidefoot"); self.side_foot=foot; self.nav_full=True
        content=QWidget(); contentv=QVBoxLayout(content); contentv.setContentsMargins(0,0,0,0); contentv.setSpacing(0)
        topbar=QFrame(); topbar.setObjectName("topBrandBar"); topbar.setFixedHeight(58); tb=QHBoxLayout(topbar); tb.setContentsMargins(22,5,18,5); tb.setSpacing(12)
        self.top_title=QLabel("Praxisverwaltung · "+get_setting("practice_name","Psychologische Privatpraxis")); self.top_title.setObjectName("topTitle"); tb.addWidget(self.top_title); tb.addStretch()
        self.top_logo=QLabel(); self.top_logo.setAlignment(Qt.AlignRight|Qt.AlignVCenter); self.top_logo.setMinimumWidth(0)
        logo_path=practice_logo_path()
        if logo_path:
            px=QPixmap(str(logo_path))
            if not px.isNull(): self.top_logo.setPixmap(px.scaled(200,40,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        tb.addWidget(self.top_logo)
        infobtn=QPushButton("ℹ Info"); infobtn.setObjectName("lockBtn"); infobtn.setMinimumHeight(34); infobtn.setToolTip("Version, Datenordner, Datenschutz und Hilfe"); infobtn.clicked.connect(self.show_info); tb.addWidget(infobtn); self.infobtn=infobtn
        uninstbtn=QPushButton("Deinstallieren"); uninstbtn.setObjectName("lockBtn"); uninstbtn.setMinimumHeight(34); uninstbtn.setToolTip("PraxisPro von diesem PC entfernen – Sie entscheiden, ob die Praxisdaten erhalten bleiben"); uninstbtn.clicked.connect(self.start_uninstall); tb.addWidget(uninstbtn); self.uninstbtn=uninstbtn
        lockbtn=QPushButton("🔒 Sperren"); lockbtn.setObjectName("lockBtn"); lockbtn.setMinimumHeight(34); lockbtn.setToolTip("PraxisPro sofort sperren (Strg+L)"); lockbtn.clicked.connect(self.lock_clicked); tb.addWidget(lockbtn); self.lockbtn=lockbtn
        contentv.addWidget(topbar)
        self.pages=QStackedWidget(); self.pages.addWidget(self.dashboard_ui()); self.pages.addWidget(self.session_ui()); self.pages.addWidget(self.helper_ui()); self.pages.addWidget(self.clients_ui()); self.pages.addWidget(self.new_client_page()); self.pages.addWidget(self.couples_ui()); self.pages.addWidget(self.calendar_ui()); self.pages.addWidget(self.invoice_ui()); self.pages.addWidget(self.invoices_ui()); self.pages.addWidget(self.settings_ui()); self.pages.addWidget(self.glossary_ui()); self.pages.addWidget(self.manual_ui()); self.pages.addWidget(self.documents_ui()); self.pages.addWidget(self.waitlist_ui()); self.pages.addWidget(self.therapy_ui()); self.pages.addWidget(self.finance_ui()); self.wrap_pages(); contentv.addWidget(self.pages,1)
        self.nav.pageChanged.connect(self.navigate); self.nav.setCurrentRow(0)
        root.addWidget(sidebar); root.addWidget(content,1); self.setCentralWidget(shell)
        self.timer=QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(250)
        self.wallclock=QLabel(); self.userbadge=QLabel()
        self.statusBar().addWidget(self.userbadge); self.statusBar().addPermanentWidget(self.side_foot); self.statusBar().addPermanentWidget(self.wallclock)
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
        QShortcut(QKeySequence("Ctrl+L"),self,activated=self.lock_clicked)
        self.autosave=QTimer(self); self.autosave.timeout.connect(self.autosave_session); self.autosave.start(10000); clear_view_dir()
    def apply_appearance(self):
        if get_setting("ui_migrated_v15","0")!="1":
            # Einmalig: neues ruhiges Standard-Farbschema „Salbei“ (in den Einstellungen umstellbar).
            set_setting("ui_theme","Salbei"); set_setting("ui_migrated_v15","1")
        theme=get_setting("ui_theme","Salbei")
        if get_setting("ui_migrated_v13","0")!="1":
            # Einmalig: zu kleine Schrift / zu enge Darstellung aus früheren Versionen anheben.
            try: set_setting("ui_font_size",max(14,int(get_setting("ui_font_size","14") or 14)))
            except Exception: set_setting("ui_font_size",14)
            if get_setting("ui_density","Kompakt")=="Kompakt": set_setting("ui_density","Normal")
            set_setting("ui_migrated_v13","1")
        font_size=max(12,min(20,int(get_setting("ui_font_size","14") or 14)))
        density=get_setting("ui_density","Normal")
        t=THEMES.get(theme,THEMES["Salbei"])
        if density=="Groß": pad,minh,navpad=8,26,8
        elif density=="Normal": pad,minh,navpad=6,20,4
        else: pad,minh,navpad=4,18,3
        nav_font=max(12,font_size-1)
        self.setStyleSheet(f"""
        QMainWindow {{ background:{t['bg']}; }}
        #sidebar {{ background:{t['side']}; border:0; border-right:1px solid {t['border']}; }}
        #brand {{ color:{t['side_text']}; font-size:{font_size+6}px; font-weight:800; padding:4px 10px 0 10px; }}
        #brandSub {{ color:{t['section']}; font-size:{max(11,font_size-2)}px; padding:0 10px 10px 10px; }}
        #sidefoot {{ color:{t['section']}; font-size:{max(10,font_size-3)}px; padding:8px 10px; }}
        #nav {{ background:transparent; border:0; outline:0; color:{t['side_text']}; font-size:{nav_font}px; }}
        #nav::item {{ padding:0 10px; margin:1px 0; border-radius:8px; }}
        #nav::item:disabled {{ color:{t['section']}; background:transparent; padding:8px 10px 0 10px; }}
        #nav::item:selected {{ background:{t['sel']}; color:{t['sel_text']}; font-weight:700; }}
        #nav::item:hover:!selected:enabled {{ background:{t['hover']}; }}
        QStackedWidget,#sessionScroll,#sessionScroll > QWidget > QWidget {{ background:{t['bg']}; }}
        QScrollArea {{ background:{t['bg']}; }}
        #topBrandBar {{ background:{t['top']}; border-bottom:1px solid {t['border']}; }}
        #topTitle {{ color:{t['accent']}; font-size:{font_size+6}px; font-weight:700; }}
        #lockBtn {{ background:white; color:{t['accent']}; border:1px solid {t['border']}; }}
        #lockBtn:hover {{ background:{t['hover']}; }}
        #pageTitle {{ font-size:{font_size+10}px; font-weight:800; color:{t['accent']}; }}
        #pageSub {{ font-size:{font_size}px; color:#6b7a72; padding-bottom:8px; }}
        #statCard,#formCard,#clientHeader {{ background:white; border:1px solid {t['border']}; border-radius:12px; padding:{pad+2}px; }}
        #cardCaption {{ color:#6b7a72; font-size:{max(11,font_size-2)}px; font-weight:700; letter-spacing:.5px; }}
        #cardValue {{ color:{t['accent']}; font-size:{font_size+12}px; font-weight:800; }}
        #infoBox {{ background:white; border:1px solid {t['border']}; border-radius:12px; padding:12px; color:#6b7a72; font-size:{max(11,font_size-1)}px; }}
        #sectionTitle {{ color:{t['accent']}; font-size:{font_size+2}px; font-weight:800; }}
        #clientName {{ color:{t['accent']}; }}
        QLabel,QCheckBox {{ color:#26322c; font-size:{font_size}px; }}
        QLineEdit,QTextEdit,QComboBox,QDateEdit,QTimeEdit,QSpinBox,QDoubleSpinBox {{
          background:white; border:1px solid #c5d0c9; border-radius:8px; padding:{pad}px 8px; min-height:{minh}px; font-size:{font_size}px; selection-background-color:{t['sel']};
        }}
        QLineEdit:focus,QTextEdit:focus,QComboBox:focus,QDateEdit:focus,QTimeEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus {{ border:2px solid {t['sel']}; }}
        QLineEdit[readOnly="true"] {{ background:#f3f6f4; color:#5d6b63; }}
        QPushButton {{ background:{t['button']}; color:white; border:0; border-radius:8px; padding:{pad+2}px 12px; font-size:{font_size}px; font-weight:600; }}
        QPushButton:hover {{ background:{t['button_hover']}; }} QPushButton:pressed {{ background:{t['accent']}; }}
        QPushButton:disabled {{ background:#d3dbd6; color:#7d8a83; }}
        QTabWidget::pane {{ border:0; background:white; border-radius:12px; }}
        QTabBar::tab {{ background:{t['hover']}; color:{t['accent']}; padding:{pad+5}px 16px; margin:2px; border-radius:8px; font-size:{font_size}px; }}
        QTabBar::tab:selected {{ background:{t['sel']}; color:{t['sel_text']}; font-weight:700; }}
        QTableWidget,QListWidget {{ background:white; alternate-background-color:{t['bg']}; border:1px solid {t['border']}; border-radius:10px; gridline-color:{t['border']}; font-size:{font_size}px; }}
        QHeaderView::section {{ background:{t['top']}; color:{t['accent']}; padding:{pad+2}px; border:0; border-bottom:1px solid {t['border']}; font-weight:700; }}
        QGroupBox {{ background:white; border:1px solid {t['border']}; border-radius:12px; margin-top:14px; padding-top:10px; font-weight:700; color:{t['accent']}; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 4px; }}
        QScrollBar:vertical {{ background:transparent; width:11px; margin:2px; }}
        QScrollBar::handle:vertical {{ background:#c3cec7; min-height:38px; border-radius:5px; }}
        QScrollBar:horizontal {{ background:transparent; height:11px; margin:2px; }}
        QScrollBar::handle:horizontal {{ background:#c3cec7; min-width:38px; border-radius:5px; }}
        QScrollBar::add-line,QScrollBar::sub-line {{ width:0; height:0; }}
        QSplitter::handle {{ background:{t['border']}; }}
        QSlider::groove:horizontal {{ height:6px; background:{t['border']}; border-radius:3px; }}
        QSlider::sub-page:horizontal {{ background:{t['sel']}; border-radius:3px; }}
        QSlider::handle:horizontal {{ background:{t['button']}; width:18px; height:18px; margin:-7px 0; border-radius:9px; border:2px solid white; }}
        QStatusBar {{ background:{t['top']}; color:{t['accent']}; border-top:1px solid {t['border']}; }} QStatusBar QLabel {{ color:{t['accent']}; font-weight:600; padding:3px 10px; }}
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
    def lock_clicked(self):
        """Manuell sperren. Ohne PIN wird zuerst eine 4-stellige PIN angeboten."""
        self.lock_screen()
    def set_pin_flow(self):
        user=(self.current_user or {}).get("username","")
        pw,ok=QInputDialog.getText(self,"PIN festlegen","Zum Ändern der PIN bitte Ihr Anmelde-Passwort eingeben:",QLineEdit.Password)
        if not ok: return False
        con=sqlite3.connect(DBFILE); row=con.execute("SELECT password_hash FROM users WHERE username=?",(user,)).fetchone(); con.close()
        if not row or not verify_password(pw,row[0]): QMessageBox.warning(self,"PIN","Das Passwort ist nicht korrekt."); return False
        first=PinPad(self,"Neue PIN","Bitte die neue 4-stellige PIN eingeben.")
        if first.exec()!=QDialog.Accepted: return False
        pin=first.pin
        again=PinPad(self,"PIN bestätigen","Bitte dieselbe PIN noch einmal eingeben.",check=lambda p:"" if p==pin else "Die PINs stimmen nicht überein.")
        if again.exec()!=QDialog.Accepted: return False
        set_user_pin(user,pin); audit("PIN_SET","PIN festgelegt/geändert",user); QMessageBox.information(self,"PIN","Die PIN wurde gespeichert."); return True
    def lock_screen(self):
        """PraxisPro sofort verdecken; Entsperren per PIN (oder alternativ Passwort)."""
        if getattr(self,"_screen_locked",False): return
        self._screen_locked=True
        self.locktimer.stop()
        user=(self.current_user or {}).get("username","")
        audit("LOCK","Bildschirm gesperrt",user)
        central=self.centralWidget(); old_title=self.windowTitle()
        if central: central.setVisible(False)
        self.setWindowTitle("PraxisPro – gesperrt")
        unlocked=False
        if user:
            fails=[0]; display=(self.current_user or {}).get("display_name",user)
            def check(pin):
                if fails[0]>=5: return "Zu viele Fehlversuche – bitte mit Passwort entsperren."
                if check_user_pin(user,pin): return ""
                fails[0]+=1; audit("UNLOCK_FAILED","Falsche PIN",user)
                return "PIN nicht korrekt." if fails[0]<5 else "Zu viele Fehlversuche – bitte mit Passwort entsperren."
            while not unlocked:
                pad=PinPad(self,"Gesperrt","PIN eingeben – "+display,check=check,cancel=False,alt_text="Mit Passwort entsperren")
                if fails[0]>=5: pad.disable_pad()
                r=pad.exec()
                if r==QDialog.Accepted: unlocked=True; break
                if r==2 or pad.alt_used: unlocked=self._unlock_with_password(user)
        else:
            unlocked=self._unlock_with_password(user,must=True)
        if not unlocked: QApplication.quit(); return
        if central: central.setVisible(True)
        self.setWindowTitle(old_title); self.update_user_badge(); self.last_activity=datetime.now(); self._screen_locked=False; self.locktimer.start(30000)
        audit("UNLOCK","Bildschirm entsperrt",user)
    def _unlock_with_password(self,user,must=False):
        while True:
            dlg=LoginDialog(); dlg.setWindowTitle("PraxisPro – Bildschirm gesperrt"); dlg.setModal(True)
            if dlg.exec()!=QDialog.Accepted:
                if must: return False
                return False if False else self._cancel_pw()
            if user and (dlg.user or {}).get("username","")!=user:
                QMessageBox.warning(self,"Bildschirm gesperrt","Bitte mit demselben Benutzer entsperren."); continue
            self.current_user=dlg.user; return True
    def _cancel_pw(self): return False

    def check_autolock(self):
        try: mins=int(get_setting("auto_lock_minutes","0") or 0)
        except ValueError: mins=0
        if self.running or getattr(self,"_screen_locked",False) or QApplication.activeModalWidget() is not None: self.last_activity=datetime.now(); return
        if mins>0 and (datetime.now()-self.last_activity).total_seconds()>=mins*60:
            self.lock_screen()

    def role(self):
        return (self.current_user or {}).get("role","Therapeut")
    def can_edit(self): return self.role() in ("Administrator","Therapeut")
    def is_admin(self): return self.role()=="Administrator"
    def responsive_split(self,split,threshold):
        """Splitter wechselt bei schmaler Breite (Hochformat) von nebeneinander auf untereinander."""
        class _F(QObject):
            def eventFilter(s_,o,ev):
                if ev.type()==QEvent.Resize:
                    want=Qt.Vertical if o.width()<threshold else Qt.Horizontal
                    if o.orientation()!=want: o.setOrientation(want)
                return False
        split._rf=_F(split); split.installEventFilter(split._rf)
    def wrap_pages(self):
        """Jede Seite in eine Scroll-Fläche setzen: bei schmalem Hochformat wird gescrollt statt abgeschnitten."""
        for i in range(self.pages.count()):
            page=self.pages.widget(i)
            if isinstance(page,QScrollArea): continue
            self.pages.removeWidget(page)
            sc=QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded); sc.setWidget(page)
            self.pages.insertWidget(i,sc)
    def resizeEvent(self,e):
        super().resizeEvent(e); self.apply_responsive()
    def apply_responsive(self):
        """Passt Seitenleiste, Kopfzeile und Seiten an die Fensterbreite an (Hoch-/Querformat, Drehen des Geräts)."""
        if not hasattr(self,"sidebar") or not hasattr(self,"nav_full"): return
        w=self.width(); compact=w<900; tiny=w<640
        if getattr(self,"_compact",None)!=compact:
            self._compact=compact
            self.sidebar.setFixedWidth(66 if compact else 250)
            self.brand_label.setVisible(not compact); self.brand_sub.setVisible(not compact); self.side_foot.setVisible(not compact)
            self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.nav.set_compact(compact)
        if getattr(self,"_tiny",None)!=tiny:
            self._tiny=tiny; self.top_logo.setVisible(not tiny); self.lockbtn.setText("🔒" if tiny else "🔒 Sperren")
            self.infobtn.setText("ℹ" if tiny else "ℹ Info"); self.uninstbtn.setVisible(not tiny)
        if hasattr(self,"top_logo"): self.top_logo.setVisible(not tiny and w>=1100)
    def navigate(self,index):
        # Einstellungen mit Benutzer-/Sicherheitsverwaltung nur für Administratoren.
        if index==9 and not self.is_admin():
            QMessageBox.warning(self,"Keine Berechtigung","Praxiseinstellungen und Benutzerverwaltung sind Administratoren vorbehalten.")
            self.nav.blockSignals(True); self.nav.setCurrentRow(self.pages.currentIndex()); self.nav.blockSignals(False); return
        self.pages.setCurrentIndex(index)
        if index==12 and hasattr(self,"refresh_document_clients"): self.refresh_document_clients()
        if index==3 and hasattr(self,"refresh_clients_table"): self.refresh_clients_table()
        if index==0 and hasattr(self,"dash_scroll"): self.refresh_dashboard()
        if index==15 and hasattr(self,"refresh_finance"): self.refresh_finance()
        if index==13 and hasattr(self,"refresh_waitlist"): self.refresh_waitlist()
        if index==14 and hasattr(self,"refresh_therapy"): self.refresh_therapy()
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
        self.appt_date=FlexDateEdit(QDate.currentDate()); self.appt_date.setCalendarPopup(True); self.appt_date.setDisplayFormat("dd.MM.yyyy")
        self.appt_time=FlexTimeEdit(QTime.currentTime()); self.appt_time.setDisplayFormat("HH:mm")
        self.appt_minutes=QSpinBox(); self.appt_minutes.setRange(5,300); self.appt_minutes.setValue(45); self.appt_minutes.setSuffix(" Min.")
        self.appt_type=QComboBox(); self.appt_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Sonstiger Termin"])
        rv.addWidget(QLabel("<b style='font-size:17px'>Termin anlegen / ändern</b>")); form=QFormLayout(); form.setVerticalSpacing(10); form.addRow("Datum",self.appt_date); form.addRow("Beginn",self.appt_time); form.addRow("Dauer",self.appt_minutes); form.addRow("Terminart",self.appt_type)
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
        self.appt_note=QLineEdit(); self.appt_note.setPlaceholderText("Interne Terminnotiz – verschlüsselt"); form.addRow("Notiz",self.appt_note)
        # Serientermine: gleiche Uhrzeit wöchentlich / 14-tägig / 4-wöchentlich
        rep=QHBoxLayout(); self.appt_repeat=QComboBox(); self.appt_repeat.addItems(["einmalig","wöchentlich","alle 2 Wochen","alle 4 Wochen"])
        self.appt_count=QSpinBox(); self.appt_count.setRange(2,52); self.appt_count.setValue(10); self.appt_count.setSuffix(" Termine"); self.appt_count.setVisible(False)
        self.appt_repeat.currentIndexChanged.connect(lambda i: self.appt_count.setVisible(i>0)); rep.addWidget(self.appt_repeat,1); rep.addWidget(self.appt_count); form.addRow("Wiederholung",rep)
        rv.addLayout(form)
        self.appt_stats=QLabel(""); self.appt_stats.setObjectName("pageSub"); self.appt_stats.setWordWrap(True); rv.addWidget(self.appt_stats)
        def show_stats(*_):
            c=client_for_sqlite_id(self.appt_client.currentData()); self.appt_stats.setText(session_stats_text(c) if c else "")
        self.appt_client.currentIndexChanged.connect(show_stats)
        actions=FlowLayout(hspacing=8,vspacing=8); save=QPushButton("＋ Neuen Termin anlegen"); edit=QPushButton("✎ Termin ändern"); delete=QPushButton("Termin löschen"); start=QPushButton("▶ Sitzung starten"); feebtn=QPushButton("€ Ausfallhonorar abrechnen"); feebtn.setToolTip("Für einen abgesagten oder nicht wahrgenommenen Termin eine Rechnung mit Ausfallhonorar vorbereiten"); save.setToolTip("Legt mit den Angaben oben einen neuen Termin an."); edit.setToolTip("Erst einen Termin in der Liste unten markieren, dann hier klicken. Danach Angaben ändern und erneut klicken."); actions.addWidget(save); actions.addWidget(edit); actions.addWidget(delete); actions.addWidget(start); actions.addWidget(feebtn); rv.addLayout(actions)
        self.responsive_split(split,880); split.addWidget(left); split.addWidget(right); split.setStretchFactor(0,1); split.setStretchFactor(1,1); split.setChildrenCollapsible(False); left.setMinimumWidth(380); right.setMinimumWidth(430); v.addWidget(split,0)
        viewrow=QHBoxLayout(); self.appt_view=QComboBox(); self.appt_view.addItems(["Tag","Woche","Monat"]); viewrow.addWidget(QLabel("Ansicht")); viewrow.addWidget(self.appt_view); viewrow.addStretch(); v.addLayout(viewrow)
        self.appt_day_title=QLabel(); self.appt_day_title.setProperty("class","sectionTitle"); v.addWidget(self.appt_day_title)
        self.appt_list=QTableWidget(0,6); self.appt_list.setHorizontalHeaderLabels(["Zeit","Dauer","Art","Klient / Paar","Status","Notiz"]); self.appt_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.appt_list.setSelectionBehavior(QTableWidget.SelectRows); self.appt_list.setAlternatingRowColors(True); self.appt_list.setMinimumHeight(190); v.addWidget(self.appt_list,1)
        def refresh():
            refresh_calendar_people()
            selected=self.appt_calendar.selectedDate(); d=selected.toString("yyyy-MM-dd"); self.appt_date.setDate(selected)
            con=sqlite3.connect(DBFILE)
            series_ids={r[0] for r in con.execute("SELECT id FROM appointments WHERE series_id IS NOT NULL AND series_id!=''").fetchall()}
            if self.appt_view.currentText() in ("Woche","Monat"):
                if self.appt_view.currentText()=="Woche":
                    monday=selected.addDays(1-selected.dayOfWeek()); sunday=monday.addDays(6); self.appt_day_title.setText("Woche "+monday.toString("dd.MM.")+" – "+sunday.toString("dd.MM.yyyy"))
                else:
                    monday=QDate(selected.year(),selected.month(),1); sunday=monday.addMonths(1).addDays(-1); self.appt_day_title.setText("Monat "+selected.toString("MMMM yyyy"))
                rows=con.execute("SELECT a.id,a.start_time,a.minutes,a.appointment_type,c.first,c.last,a.couple_id,a.status,a.note,a.appointment_date FROM appointments a LEFT JOIN clients c ON c.id=a.client_id WHERE a.appointment_date BETWEEN ? AND ? ORDER BY a.appointment_date,a.start_time",(monday.toString("yyyy-MM-dd"),sunday.toString("yyyy-MM-dd"))).fetchall()
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
                shown_time=(QDate.fromString(rowdate,"yyyy-MM-dd").toString("ddd dd.MM. ") if self.appt_view.currentText()!="Tag" else "")+t; vals=[shown_time,str(m)+" Min.",(typ or "")+("  ⟳" if aid in series_ids else ""),name,status,decrypt_text(note)]
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
            requested_start=QTime.fromString(t,"HH:mm"); requested_end=requested_start.addSecs(self.appt_minutes.value()*60)
            def conflict_on(day): return appointment_conflict(day,t,self.appt_minutes.value(),con=con)
            step={"wöchentlich":7,"alle 2 Wochen":14,"alle 4 Wochen":28}.get(self.appt_repeat.currentText(),0)
            count=self.appt_count.value() if step else 1
            dates=[self.appt_date.date().addDays(i*step) for i in range(count)]
            first_conflict=conflict_on(d)
            if first_conflict and not step: con.close(); QMessageBox.warning(self,"Terminkonflikt","Der Termin überschneidet sich mit einem bestehenden Termin um "+str(first_conflict)+" Uhr."); return
            series_id=datetime.now().strftime("S%Y%m%d%H%M%S%f") if step else None
            created=[]; skipped=[]
            for qd in dates:
                day=qd.toString("yyyy-MM-dd"); c_=conflict_on(day)
                if c_: skipped.append(qd.toString("dd.MM.yyyy")+f" ({c_} Uhr belegt)"); continue
                con.execute("INSERT INTO appointments(appointment_date,start_time,minutes,client_id,couple_id,appointment_type,status,note,created_at,username,series_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(day,t,self.appt_minutes.value(),cid,couple,self.appt_type.currentText(),self.appt_status.currentText(),encrypt_text(self.appt_note.text().strip()),datetime.now().isoformat(timespec="seconds"),self.current_user.get("username",""),series_id))
                created.append(qd.toString("dd.MM.yyyy"))
            con.commit(); con.close()
            audit("APPOINTMENT_CREATE",d+" "+t+(f" Serie {len(created)} Termine" if step else ""),self.current_user.get("username",""))
            self.appt_note.clear(); self.appt_calendar.setSelectedDate(self.appt_date.date()); refresh(); show_stats()
            if step:
                msg=f"{len(created)} Serientermine angelegt ({self.appt_repeat.currentText()}, {t} Uhr), vom {created[0] if created else '–'} bis {created[-1] if created else '–'}."
                if skipped: msg+="\n\nWegen Überschneidung NICHT angelegt:\n• "+"\n• ".join(skipped)
                c=client_for_sqlite_id(cid)
                if c: msg+="\n\n"+session_stats_text(c)
                (QMessageBox.warning if skipped else QMessageBox.information)(self,"Serientermine",msg)
                self.appt_repeat.setCurrentIndex(0)
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
            QMessageBox.information(self,"Termin bearbeiten","Der Termin wurde in die Eingabefelder geladen.\n\nKlient oder Paarakte sowie Datum, Uhrzeit, Dauer, Terminart, Status und Notiz können jetzt geändert werden. Anschließend auf „Änderungen speichern“ klicken, um die Änderungen zu speichern.")
            edit.setText("✔ Änderungen speichern")
            edit.setProperty("editingAppointmentId",aid)
            return
        def save_edit_if_active():
            aid=edit.property("editingAppointmentId")
            if not aid: return False
            cid=self.appt_client.currentData(); couple=self.appt_couple.currentData()
            if cid and couple:
                QMessageBox.warning(self,"Termin","Bitte entweder Klient oder Paarakte zuordnen, nicht beides."); return True
            if self.appt_status.currentText() in ACTIVE_APPT_STATUS:
                busy=appointment_conflict(self.appt_date.date().toString("yyyy-MM-dd"),self.appt_time.time().toString("HH:mm"),self.appt_minutes.value(),exclude_id=aid)
                if busy:
                    QMessageBox.warning(self,"Terminkonflikt",f"Die geänderte Zeit überschneidet sich mit einem bestehenden Termin um {busy} Uhr. Bitte eine andere Zeit wählen."); return True
            con=sqlite3.connect(DBFILE)
            con.execute("UPDATE appointments SET appointment_date=?,start_time=?,minutes=?,client_id=?,couple_id=?,appointment_type=?,status=?,note=? WHERE id=?",(self.appt_date.date().toString("yyyy-MM-dd"),self.appt_time.time().toString("HH:mm"),self.appt_minutes.value(),cid,couple,self.appt_type.currentText(),self.appt_status.currentText(),encrypt_text(self.appt_note.text().strip()),aid))
            con.commit(); con.close(); audit("APPOINTMENT_UPDATE",str(aid),self.current_user.get("username",""))
            edit.setProperty("editingAppointmentId",None); edit.setText("✎ Termin ändern"); refresh(); return True
        original_edit_selected=edit_selected
        def edit_selected():
            if save_edit_if_active(): return
            original_edit_selected()
        def start_session():
            aid=selected_id()
            if aid: self.start_session_from_appointment(aid)
        def remove():
            if not self.require_edit(): return
            row=self.appt_list.currentRow()
            if row<0: return
            aid=self.appt_list.item(row,0).data(Qt.UserRole)
            con=sqlite3.connect(DBFILE); srow=con.execute("SELECT series_id,appointment_date FROM appointments WHERE id=?",(aid,)).fetchone()
            sid,adate=(srow or (None,""))
            later=con.execute("SELECT COUNT(*) FROM appointments WHERE series_id=? AND appointment_date>=?",(sid,adate)).fetchone()[0] if sid else 0
            if sid and later>1:
                box=QMessageBox(self); box.setWindowTitle("Serientermin löschen"); box.setText(f"Dieser Termin gehört zu einer Serie ({later} Termine ab diesem Datum).")
                only=box.addButton("Nur diesen Termin",QMessageBox.AcceptRole); allf=box.addButton(f"Diesen und alle folgenden ({later})",QMessageBox.DestructiveRole); box.addButton("Abbrechen",QMessageBox.RejectRole); box.exec()
                if box.clickedButton()==allf:
                    con.execute("DELETE FROM appointments WHERE series_id=? AND appointment_date>=?",(sid,adate)); con.commit(); con.close(); audit("APPOINTMENT_DELETE",f"Serie {sid} ab {adate}: {later}",self.current_user.get("username","")); refresh(); return
                if box.clickedButton()!=only: con.close(); return
            elif QMessageBox.question(self,"Termin löschen","Ausgewählten Termin wirklich löschen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: con.close(); return
            con.execute("DELETE FROM appointments WHERE id=?",(aid,)); con.commit(); con.close(); audit("APPOINTMENT_DELETE",str(aid),self.current_user.get("username","")); refresh()
        save.clicked.connect(store); edit.clicked.connect(edit_selected); delete.clicked.connect(remove); start.clicked.connect(start_session); feebtn.clicked.connect(lambda: (self.bill_cancellation_fee(selected_id()) if selected_id() else QMessageBox.information(self,"Ausfallhonorar","Bitte zuerst den Termin in der Liste auswählen."))); self.appt_calendar.selectionChanged.connect(refresh); self.appt_view.currentTextChanged.connect(lambda *_: refresh())
        today.clicked.connect(lambda: self.appt_calendar.setSelectedDate(QDate.currentDate())); prev.clicked.connect(lambda: self.appt_calendar.setSelectedDate(self.appt_calendar.selectedDate().addDays(-1))); nxt.clicked.connect(lambda: self.appt_calendar.setSelectedDate(self.appt_calendar.selectedDate().addDays(1)))
        refresh()
        for _w in (self.appt_date,self.appt_time,self.appt_minutes,self.appt_type,self.appt_client,self.appt_couple,self.appt_status,self.appt_note): _w.setMinimumHeight(38)
        sa=QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sa.setWidget(page); return sa

    def start_session_from_appointment(self,aid):
        """Sitzungsseite mit Datum, Zeit, Art und Klient eines Termins vorbelegen."""
        con=sqlite3.connect(DBFILE); row=con.execute("SELECT appointment_date,start_time,minutes,client_id,appointment_type FROM appointments WHERE id=?",(aid,)).fetchone(); con.close()
        if not row: return
        d,t,m,cid,typ=row
        self.nav.setCurrentRow(1); QApplication.processEvents()
        if hasattr(self,"s_date"): self.s_date.setDate(QDate.fromString(d,"yyyy-MM-dd")); self.s_start.setTime(QTime.fromString(t,"HH:mm")); self.s_end.setTime(QTime.fromString(t,"HH:mm").addSecs(int(m)*60)); self.s_type.setCurrentText(typ if typ in ["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch"] else "Einzeltherapie")
        # Früher wurde hier nach einem Feld "id" im Klientendatensatz gesucht, das es nicht gibt – der Klient blieb leer.
        c=client_for_sqlite_id(cid)
        if c and hasattr(self,"client_pick"):
            for n in range(self.client_pick.count()):
                if resolve_client(self.client_pick.itemData(n)) is c: self.client_pick.setCurrentIndex(n); break

    def show_info(self):
        """Info-Fenster: Version, Praxis, Datenordner, Schutzstatus, Hilfe."""
        dlg=QDialog(self); dlg.setWindowTitle("Info – PraxisPro"); dlg.setMinimumWidth(560); v=QVBoxLayout(dlg); v.setSpacing(10)
        t=QLabel(f"PraxisPro  ·  Version {APP_VERSION}"); t.setObjectName("pageTitle"); v.addWidget(t)
        s=invoice_settings(); u=self.current_user or {}
        rows=[("Praxis",get_setting("practice_name","")),("Inhaber",s.get("owner_name","")),("Angemeldet",f"{u.get('display_name',u.get('username',''))} · {u.get('role','')}"),
              ("Datenordner",str(ROOT)),("Datenschlüssel","an Windows-Konto gebunden (DPAPI)" if key_is_protected() else "Schlüsseldatei im Datenordner – Schutz unter Praxiseinstellungen möglich"),
              ("Datensicherung",get_setting("backup_dir","") or str(ROOT/"Backups")+"  (im Datenordner – besser USB-Stick wählen)"),
              ("Klienten / Sitzungen / Rechnungen",f"{len(DB['clients'])} / {len(DB['sessions'])} / {len(DB['invoices'])}"),
              ("Programmdatei",str(Path(sys.executable).resolve()) if getattr(sys,"frozen",False) else "Entwicklungsversion (Python)")]
        g=QGridLayout(); g.setHorizontalSpacing(16); g.setVerticalSpacing(6)
        for r,(k,val) in enumerate(rows):
            a=QLabel(k); a.setStyleSheet("color:#6b7a72"); b=QLabel(val); b.setWordWrap(True); b.setTextInteractionFlags(Qt.TextSelectableByMouse); g.addWidget(a,r,0,Qt.AlignTop); g.addWidget(b,r,1)
        g.setColumnStretch(1,1); v.addLayout(g)
        note=QLabel("Alle Praxisdaten bleiben lokal auf diesem PC und werden verschlüsselt gespeichert. "+get_setting("copyright","© 2026 Erdoğan Kulanoğlu")); note.setWordWrap(True); note.setObjectName("pageSub"); v.addWidget(note)
        row=QHBoxLayout()
        b1=QPushButton("📂 Datenordner öffnen"); b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT))))
        b2=QPushButton("? Hilfe · FAQ"); b2.clicked.connect(lambda: (dlg.accept(),self.nav.setCurrentRow(11)))
        b3=QPushButton("Schließen"); b3.clicked.connect(dlg.accept)
        for b in (b1,b2): row.addWidget(b)
        row.addStretch(); row.addWidget(b3); v.addLayout(row); dlg.exec()

    def find_uninstaller(self):
        candidates=[Path(sys.executable).resolve().parent/"unins000.exe",Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"PraxisPro"/"unins000.exe",Path(os.environ.get("ProgramFiles","C:/Program Files"))/"PraxisPro"/"unins000.exe"]
        return next((p for p in candidates if p.exists()),None)

    def start_uninstall(self):
        """Deinstallation vorbereiten. Die Frage „Daten behalten oder alles löschen“ stellt der Windows-Deinstaller
        (so erscheint sie auch bei Deinstallation über die Windows-Einstellungen)."""
        if not self.is_admin(): return QMessageBox.warning(self,"Keine Berechtigung","Deinstallieren ist Administratoren vorbehalten.")
        backup_in_root=not get_setting("backup_dir","")
        box=QMessageBox(self); box.setWindowTitle("PraxisPro deinstallieren"); box.setIcon(QMessageBox.Question)
        box.setText("PraxisPro von diesem PC entfernen?")
        box.setInformativeText("Im nächsten Schritt fragt der Windows-Deinstaller, ob Ihre Praxisdaten erhalten bleiben (empfohlen) oder vollständig gelöscht werden sollen.\n\n"
            f"Datenordner: {ROOT}\n\n"+("Achtung: Ihre Datensicherungen liegen im Datenordner (Unterordner „Backups“). Wenn Sie alles löschen, sind auch diese weg – erstellen Sie vorher eine Sicherung auf einem USB-Stick." if backup_in_root else "Vor dem Deinstallieren wird eine aktuelle Datensicherung empfohlen."))
        go=box.addButton("Deinstallation starten",QMessageBox.DestructiveRole); bk=box.addButton("Zuerst Datensicherung",QMessageBox.ActionRole); box.addButton("Abbrechen",QMessageBox.RejectRole); box.setDefaultButton(bk); box.exec()
        if box.clickedButton()==bk:
            self.nav.setCurrentRow(9); QMessageBox.information(self,"Datensicherung","Unter „Abrechnung & Bank“ finden Sie „Datensicherung erstellen“. Wählen Sie als Ziel am besten einen USB-Stick.\n\nDanach erneut oben auf „Deinstallieren“ klicken."); return
        if box.clickedButton()!=go: return
        exe=self.find_uninstaller()
        if not exe: return QMessageBox.information(self,"Deinstallation","Der Windows-Deinstaller wurde nicht gefunden (Entwicklungsversion?). Bitte PraxisPro über Windows-Einstellungen → Apps → Installierte Apps deinstallieren.")
        try:
            audit("UNINSTALL_STARTED","Deinstallation über PraxisPro gestartet",(self.current_user or {}).get("username",""))
            subprocess.Popen([str(exe)]); QApplication.quit()
        except Exception as e: QMessageBox.warning(self,"Deinstallation","Deinstaller konnte nicht gestartet werden:\n"+str(e))

    def bill_cancellation_fee(self,aid):
        """Rechnung mit Ausfallhonorar für einen abgesagten / nicht wahrgenommenen Termin vorbereiten."""
        if not self.require_edit(): return False
        con=sqlite3.connect(DBFILE); row=con.execute("SELECT appointment_date,start_time,minutes,client_id,status FROM appointments WHERE id=?",(aid,)).fetchone(); con.close()
        if not row: return False
        d,t,m,cid,status=row; c=client_for_sqlite_id(cid)
        if not c: QMessageBox.warning(self,"Ausfallhonorar","Dem Termin ist kein Klient zugeordnet."); return False
        if status not in ("abgesagt","ausgefallen"):
            if QMessageBox.question(self,"Ausfallhonorar",f"Der Termin ist als „{status}“ markiert.\n\nAls „ausgefallen“ markieren und Ausfallhonorar abrechnen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return False
            con=sqlite3.connect(DBFILE); con.execute("UPDATE appointments SET status='ausgefallen' WHERE id=?",(aid,)); con.commit(); con.close()
        amount=round(amount_for(int(m),"Ausfallhonorar",False),2)
        end=(datetime.strptime(t,"%H:%M")+timedelta(minutes=int(m))).strftime("%H:%M")
        self.nav.setCurrentRow(7); QApplication.processEvents()
        self.i_first.setText(c.get("first","")); self.i_last.setText(c.get("last","")); self.i_addr.setText(c.get("address","")); self.i_diag.setText(c.get("diagnosis",""))
        self.i_date.setDate(QDate.fromString(d,"yyyy-MM-dd")); self.i_type.setCurrentText("Ausfallhonorar")
        self.pending_sessions=None; self.manual_items=[{"date":d,"start":t,"end":end,"minutes":int(m),"type":"Ausfallhonorar","reduced":False,"amount":amount}]
        if hasattr(self,"refresh_invoice_items"): self.refresh_invoice_items()
        audit("CANCELLATION_FEE_PREPARED",f"Termin {d} {t}: {amount:.2f}",(self.current_user or {}).get("username",""))
        QMessageBox.information(self,"Ausfallhonorar",f"Die Rechnung ist vorbereitet: Ausfallhonorar für den Termin am {_de_date(d)} um {t} Uhr über {amount:.2f} €.\n\nBitte prüfen und dann wie gewohnt „Rechnung erstellen“. Den Betrag des Ausfallhonorars ändern Sie unter Praxiseinstellungen → Honorare.")
        return True

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

    def therapy_ui(self):
        """Therapieverlauf je Klient: Anamnese, Therapieziele mit Fortschritt, Fragebögen (PHQ-9, GAD-7) mit Verlauf."""
        import questionnaires as Q
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Therapieverlauf"); title.setObjectName("pageTitle"); v.addWidget(title)
        top=QHBoxLayout(); top.addWidget(QLabel("Klient"))
        pick=QComboBox(); pick.setEditable(True); pick.setInsertPolicy(QComboBox.NoInsert); pick.setMinimumHeight(34); pick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); pick.setMinimumContentsLength(24)
        pick.completer().setCompletionMode(QCompleter.PopupCompletion); pick.completer().setFilterMode(Qt.MatchContains); pick.completer().setCaseSensitivity(Qt.CaseInsensitive)
        top.addWidget(pick,1); self.therapy_pick=pick
        self.therapy_alert=QLabel(""); self.therapy_alert.setWordWrap(True); self.therapy_alert.setStyleSheet("background:#fbecea;color:#8a2f28;border:1px solid #e3b4ae;border-radius:8px;padding:6px 10px;font-weight:600"); self.therapy_alert.setVisible(False)
        self.therapy_stats=QLabel(""); self.therapy_stats.setObjectName("pageSub")
        self.therapy_hint=QLabel("Bitte oben zuerst einen Klienten auswählen – erst dann werden Anamnese, Ziele und Fragebögen gespeichert.")
        self.therapy_hint.setWordWrap(True); self.therapy_hint.setStyleSheet("background:#fff6e0;color:#6b4e00;border:1px solid #ecd9a6;border-radius:8px;padding:6px 10px;font-weight:600")
        v.addLayout(top); v.addWidget(self.therapy_hint); v.addWidget(self.therapy_stats); v.addWidget(self.therapy_alert)
        tabs=QTabWidget(); tabs.setDocumentMode(True); v.addWidget(tabs,1); self.therapy_tabs=tabs
        state={"cc":None,"loading":False}
        user=lambda: (self.current_user or {}).get("username","")

        # ------------------------------------------------------------ Anamnese
        an_page=QWidget(); av=QVBoxLayout(an_page); av.setContentsMargins(0,8,0,0)
        an_body=QWidget(); ag=QGridLayout(an_body); ag.setContentsMargins(0,0,0,0); ag.setHorizontalSpacing(12); ag.setVerticalSpacing(12); an_fields={}
        for i,(section,items) in enumerate(ANAMNESIS_FIELDS):
            box=QFrame(); box.setObjectName("formCard"); bv=QVBoxLayout(box); bv.setContentsMargins(14,10,14,12); bv.setSpacing(6)
            st=QLabel(section); st.setObjectName("sectionTitle"); bv.addWidget(st)
            for key,label,kind in items:
                bv.addWidget(QLabel(label))
                if isinstance(kind,list): ed=QComboBox(); ed.addItems(kind)
                elif kind=="multi": ed=QTextEdit(); ed.setAcceptRichText(False); ed.setMinimumHeight(64); ed.setMaximumHeight(110)
                else: ed=QLineEdit()
                if key=="first_contact": ed.setPlaceholderText("TT.MM.JJJJ")
                an_fields[key]=ed; bv.addWidget(ed)
            ag.addWidget(box,i//2,i%2)
        ag.setColumnStretch(0,1); ag.setColumnStretch(1,1)
        sc=QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(an_body); av.addWidget(sc,1)
        an_bar=QHBoxLayout(); an_info=QLabel(""); an_info.setObjectName("pageSub"); an_bar.addWidget(an_info,1)
        an_pdf=QPushButton("📄 Als PDF (verschlüsselt in der Akte)"); an_save=QPushButton("💾 Anamnese speichern")
        for b in (an_pdf,an_save): b.setMinimumHeight(38); an_bar.addWidget(b)
        av.addLayout(an_bar); tabs.addTab(an_page,"Anamnese")
        def an_value(ed):
            if isinstance(ed,QComboBox): return ed.currentText()
            if isinstance(ed,QTextEdit): return ed.toPlainText().strip()
            return ed.text().strip()
        def an_load(cc):
            data=(cc or {}).get("anamnesis",{})
            for k,ed in an_fields.items():
                val=str(data.get(k,"") or "")
                if k=="diagnosis" and not val: val=(cc or {}).get("diagnosis","")
                if isinstance(ed,QComboBox): ed.setCurrentIndex(max(0,ed.findText(val)))
                elif isinstance(ed,QTextEdit): ed.setPlainText(val)
                else: ed.setText(val)
            an_info.setText(("Zuletzt gespeichert: "+datetime.fromisoformat(data["updated"]).strftime("%d.%m.%Y %H:%M")) if data.get("updated") else "Noch nicht ausgefüllt.")
        def an_save_fn(quiet=False):
            cc=state["cc"]
            if not cc: QMessageBox.information(self,"Anamnese","Bitte zuerst einen Klienten auswählen."); return False
            if not self.require_edit(): return False
            data={k:an_value(ed) for k,ed in an_fields.items()}; data["updated"]=datetime.now().isoformat(timespec="seconds")
            cc["anamnesis"]=data
            if data.get("diagnosis") and not cc.get("diagnosis"): cc["diagnosis"]=data["diagnosis"]
            save_data(); audit("ANAMNESIS_SAVED",f"{cc.get('last','')}, {cc.get('first','')}",user()); an_load(cc); update_alert()
            if not quiet: QMessageBox.information(self,"Anamnese","Die Anamnese wurde gespeichert.")
            return True
        def an_pdf_fn():
            if not an_save_fn(quiet=True): return
            cc=state["cc"]; data=cc["anamnesis"]; lines=[f"Klient/in: {cc.get('first','')} {cc.get('last','')}"+(f", geb. {cc.get('dob')}" if cc.get("dob") else ""),""]
            for section,items in ANAMNESIS_FIELDS:
                filled=[(label,data.get(k,"")) for k,label,_ in items if data.get(k,"") and data.get(k,"")!="nicht erfragt"]
                if not filled: continue
                lines.append("## "+section)
                for label,val in filled:
                    vals=str(val).splitlines()
                    lines.append(f"{label}: {vals[0]}"); lines+=vals[1:]
                lines.append("")
            folder=client_dir(cc)/"Dokumente"; stamp=datetime.now()
            tmp=Path(tempfile.mkdtemp(prefix="praxispro_an_"))/"Anamnese.pdf"
            try:
                document_pdf.render_document_pdf(tmp,"Anamnese",("\n".join(lines)),invoice_settings(),practice_logo_path(),None,[("Unterschrift Therapeut/in",None,invoice_settings().get("owner_name",""))],", ".join(x for x in (practice_city(),stamp.strftime("%d.%m.%Y")) if x),"",lambda c,t: audit(c,t,user()))
                target=folder/f"{stamp.strftime('%Y-%m-%d_%H%M%S')}_Anamnese.pdf.enc"; target.write_bytes(Fernet(encryption_key()).encrypt(tmp.read_bytes()))
            finally: shutil.rmtree(tmp.parent,ignore_errors=True)
            audit("ANAMNESIS_PDF",f"{cc.get('last','')}, {cc.get('first','')}",user()); open_client_document(target)
        an_save.clicked.connect(lambda: an_save_fn()); an_pdf.clicked.connect(an_pdf_fn)

        # ------------------------------------------------------------ Therapieziele
        go_page=QWidget(); gv=QVBoxLayout(go_page); gv.setContentsMargins(0,8,0,0)
        gsplit=QSplitter(); gsplit.setChildrenCollapsible(False); self.responsive_split(gsplit,900)
        gleft=QWidget(); glv=QVBoxLayout(gleft); glv.setContentsMargins(0,0,0,0)
        gtable=QTableWidget(0,4); gtable.setHorizontalHeaderLabels(["Ziel","Status","Fortschritt","Zuletzt"]); gtable.verticalHeader().setVisible(False)
        for col,mode in enumerate((QHeaderView.Stretch,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents)): gtable.horizontalHeader().setSectionResizeMode(col,mode)
        gtable.setSelectionBehavior(QTableWidget.SelectRows); gtable.setSelectionMode(QTableWidget.SingleSelection); gtable.setEditTriggers(QTableWidget.NoEditTriggers); gtable.setMinimumHeight(120); gtable.setMaximumHeight(240); glv.addWidget(gtable)
        gchart=ScoreChart("Fortschritt des gewählten Ziels (0 = noch gar nicht, 10 = vollständig erreicht)"); gchart.setMaximumHeight(300); glv.addWidget(gchart); glv.addStretch()
        gcard=QFrame(); gcard.setObjectName("formCard"); gcv=QVBoxLayout(gcard); gcv.setContentsMargins(14,10,14,12); gcv.setSpacing(6)
        gtitle=QLabel("Neues Ziel"); gtitle.setObjectName("sectionTitle"); gcv.addWidget(gtitle)
        g_text=QTextEdit(); g_text.setAcceptRichText(False); g_text.setFixedHeight(70); g_text.setPlaceholderText("Ziel konkret und beobachtbar formulieren, z. B. „wieder zweimal pro Woche Freunde treffen“")
        g_method=QTextEdit(); g_method.setAcceptRichText(False); g_method.setFixedHeight(60); g_method.setPlaceholderText("Methoden / Interventionen")
        g_status=QComboBox(); g_status.addItems(["offen","in Arbeit","erreicht","verworfen"])
        for lab,w_ in (("Ziel *",g_text),("Methoden / Interventionen",g_method),("Status",g_status)): gcv.addWidget(QLabel(lab)); gcv.addWidget(w_)
        gb=QWidget(); gbl=FlowLayout(gb,hspacing=8,vspacing=8); gbl.setContentsMargins(0,2,0,6)
        g_new=QPushButton("＋ Neues Ziel"); g_save=QPushButton("💾 Ziel speichern"); g_del=QPushButton("Löschen"); g_del.setStyleSheet("background:white;color:#b5534b;border:1px solid #d9a9a4")
        for b in (g_new,g_save,g_del): b.setMinimumHeight(34); gbl.addWidget(b)
        gcv.addWidget(gb)
        rt=QLabel("Fortschritt bewerten"); rt.setObjectName("sectionTitle"); gcv.addWidget(rt)
        rrow=QHBoxLayout(); g_slider=QSlider(Qt.Horizontal); g_slider.setRange(0,10); g_slider.setValue(5); g_slider.setTickPosition(QSlider.TicksBelow); g_slider.setTickInterval(1)
        g_val=QLabel("5 / 10"); g_val.setMinimumWidth(56); g_slider.valueChanged.connect(lambda x: g_val.setText(f"{x} / 10")); rrow.addWidget(g_slider,1); rrow.addWidget(g_val); gcv.addLayout(rrow)
        g_rnote=QLineEdit(); g_rnote.setPlaceholderText("Kurze Notiz zur Einschätzung (optional)"); gcv.addWidget(g_rnote)
        g_rate=QPushButton("✓ Bewertung für heute hinzufügen"); g_rate.setMinimumHeight(34); gcv.addWidget(g_rate); gcv.addStretch()
        gsplit.addWidget(gleft); gsplit.addWidget(gcard); gsplit.setStretchFactor(0,3); gsplit.setStretchFactor(1,2); gv.addWidget(gsplit,1)
        tabs.addTab(go_page,"Therapieziele")
        gstate={"id":None}
        def goals(): return (state["cc"] or {}).setdefault("goals",[]) if state["cc"] else []
        def g_current(): return next((g for g in goals() if g.get("id")==gstate["id"]),None)
        def g_refresh():
            gtable.setRowCount(0)
            order={"in Arbeit":0,"offen":1,"erreicht":2,"verworfen":3}
            for g in sorted(goals(),key=lambda g:(order.get(g.get("status"),9),g.get("created",""))):
                r=gtable.rowCount(); gtable.insertRow(r); last=(g.get("ratings") or [{}])[-1]
                vals=[g.get("text","").replace("\n"," "),g.get("status",""),(f"{last['value']} / 10" if "value" in last else "–"),(_de_date(last.get("date","")) if last.get("date") else "–")]
                for j,val in enumerate(vals):
                    it=QTableWidgetItem(val); it.setData(Qt.UserRole,g.get("id"))
                    if g.get("status") in ("erreicht","verworfen"): it.setForeground(QColor("#7d8a83"))
                    gtable.setItem(r,j,it)
            g_chart()
        def g_chart():
            g=g_current()
            pts=[(_de_date(x["date"])[:6],x["value"],f"{_de_date(x['date'])}: {x['value']} / 10"+(f"\n{x['note']}" if x.get("note") else "")) for x in (g or {}).get("ratings",[])]
            gchart.set_data(pts,10)
        def g_load(g):
            gstate["id"]=g.get("id") if g else None
            g_text.setPlainText(g.get("text","") if g else ""); g_method.setPlainText(g.get("methods","") if g else ""); g_status.setCurrentText(g.get("status","offen") if g else "offen")
            gtitle.setText("Ziel bearbeiten" if g else "Neues Ziel"); g_rate.setEnabled(bool(g)); g_del.setEnabled(bool(g)); g_chart()
        def g_select():
            r=gtable.currentRow()
            if r>=0: gid=gtable.item(r,0).data(Qt.UserRole); g_load(next((g for g in goals() if g.get("id")==gid),None))
        def g_save_fn():
            if not state["cc"]: return QMessageBox.information(self,"Therapieziele","Bitte zuerst einen Klienten auswählen.")
            if not self.require_edit(): return
            if not g_text.toPlainText().strip(): return QMessageBox.warning(self,"Therapieziele","Bitte das Ziel beschreiben.")
            g=g_current()
            if g is None:
                g={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"created":date.today().isoformat(),"ratings":[]}; goals().append(g); gstate["id"]=g["id"]
            g.update({"text":g_text.toPlainText().strip(),"methods":g_method.toPlainText().strip(),"status":g_status.currentText()})
            save_data(); audit("GOAL_SAVED",f"{state['cc'].get('last','')}, {state['cc'].get('first','')}",user()); g_refresh(); g_load(g)
        def g_rate_fn():
            g=g_current()
            if not g or not self.require_edit(): return
            today=date.today().isoformat(); entry={"date":today,"value":g_slider.value(),"note":g_rnote.text().strip()}
            g["ratings"]=[x for x in g.get("ratings",[]) if x.get("date")!=today]+[entry]   # pro Tag eine Bewertung
            if g.get("status")=="offen": g["status"]="in Arbeit"
            save_data(); g_rnote.clear(); g_refresh(); g_load(g)
        def g_del_fn():
            g=g_current()
            if not g or not self.require_edit(): return
            if QMessageBox.question(self,"Ziel löschen",f"Ziel „{g.get('text','')[:60]}“ mit allen Bewertungen löschen?\n\nTipp: Statt zu löschen kann der Status auf „verworfen“ gesetzt werden – dann bleibt der Verlauf dokumentiert.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            goals().remove(g); save_data(); audit("GOAL_DELETED",f"{state['cc'].get('last','')}, {state['cc'].get('first','')}",user()); g_load(None); g_refresh()
        gtable.itemSelectionChanged.connect(g_select); g_new.clicked.connect(lambda: (gtable.clearSelection(),g_load(None),g_text.setFocus())); g_save.clicked.connect(g_save_fn); g_rate.clicked.connect(g_rate_fn); g_del.clicked.connect(g_del_fn)

        # ------------------------------------------------------------ Fragebögen
        qu_page=QWidget(); qv=QVBoxLayout(qu_page); qv.setContentsMargins(0,8,0,0)
        qsplit=QSplitter(); qsplit.setChildrenCollapsible(False); self.responsive_split(qsplit,820)
        qleft=QWidget(); qlv=QVBoxLayout(qleft); qlv.setContentsMargins(0,0,0,0)
        qtop=QHBoxLayout(); q_kind=QComboBox(); q_kind.addItems(list(Q.QUESTIONNAIRES.keys())); q_date=FlexDateEdit(QDate.currentDate()); q_date.setCalendarPopup(True); q_date.setDisplayFormat("dd.MM.yyyy")
        qtop.addWidget(QLabel("Fragebogen")); qtop.addWidget(q_kind); qtop.addWidget(QLabel("Datum")); qtop.addWidget(q_date); qtop.addStretch(); qlv.addLayout(qtop)
        q_stack=QStackedWidget(); q_stack.setMinimumHeight(320); q_forms={}
        for kind in Q.QUESTIONNAIRES:
            fw=QuestionnaireForm(kind); q_forms[kind]=fw; s2=QScrollArea(); s2.setWidgetResizable(True); s2.setFrameShape(QFrame.NoFrame); s2.setWidget(fw); q_stack.addWidget(s2)
        qlv.addWidget(q_stack,1)
        q_result=QLabel(""); q_result.setWordWrap(True); q_result.setStyleSheet("font-weight:700;padding:6px 0"); qlv.addWidget(q_result)
        qbar=QWidget(); qbl=FlowLayout(qbar,hspacing=8,vspacing=8); qbl.setContentsMargins(0,0,0,0)
        q_big=QPushButton("⛶ Großansicht für Klient/in"); q_save=QPushButton("💾 Ergebnis speichern"); q_clear=QPushButton("Leeren")
        for b in (q_big,q_save,q_clear): b.setMinimumHeight(36); qbl.addWidget(b)
        qlv.addWidget(qbar)
        qright=QWidget(); qrv=QVBoxLayout(qright); qrv.setContentsMargins(0,0,0,0)
        qchart=ScoreChart(); qrv.addWidget(qchart)
        qhist=QTableWidget(0,4); qhist.setHorizontalHeaderLabels(["Datum","Fragebogen","Summe","Einstufung"]); qhist.verticalHeader().setVisible(False); qhist.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        qhist.setSelectionBehavior(QTableWidget.SelectRows); qhist.setEditTriggers(QTableWidget.NoEditTriggers); qrv.addWidget(qhist,1)
        q_hdel=QPushButton("Ausgewähltes Ergebnis löschen"); q_hdel.setMinimumHeight(32); q_hdel.setStyleSheet("background:white;color:#b5534b;border:1px solid #d9a9a4"); qrv.addWidget(q_hdel)
        note=QLabel("PHQ-9 und GAD-7 sind frei verwendbare Screening-Instrumente. Ergebnisse ersetzen keine Diagnose."); note.setWordWrap(True); note.setObjectName("pageSub"); qrv.addWidget(note)
        qsplit.addWidget(qleft); qsplit.addWidget(qright); qsplit.setStretchFactor(0,3); qsplit.setStretchFactor(1,2); qv.addWidget(qsplit,1)
        tabs.addTab(qu_page,"Fragebögen")
        def q_results(): return (state["cc"] or {}).setdefault("questionnaires",[]) if state["cc"] else []
        def q_live():
            kind=q_kind.currentText(); res=Q.score(kind,q_forms[kind].answers()); answered=len(Q.QUESTIONNAIRES[kind]["items"])-len(res["missing"])
            q_result.setText(f"{kind}: {res['score']} von {res['max']} Punkten – {res['severity']}  ·  {answered}/{len(Q.QUESTIONNAIRES[kind]['items'])} beantwortet"+("".join("\n⚠ "+n for n in res["notes"] if "Item 9" in n)))
            q_result.setStyleSheet("font-weight:700;padding:6px 0;"+("color:#8a2f28" if any("Item 9" in n for n in res["notes"]) else ""))
        def q_hist_refresh():
            kind=q_kind.currentText(); qhist.setRowCount(0)
            for x in sorted(q_results(),key=lambda x:(x.get("date",""),x.get("saved","")),reverse=True):
                r=qhist.rowCount(); qhist.insertRow(r)
                for j,val in enumerate((_de_date(x.get("date","")),x.get("kind",""),f"{x.get('score')} / {Q.QUESTIONNAIRES.get(x.get('kind'),{}).get('max','')}",x.get("severity",""))):
                    it=QTableWidgetItem(str(val)); it.setData(Qt.UserRole,x.get("id")); qhist.setItem(r,j,it)
            series=sorted([x for x in q_results() if x.get("kind")==kind],key=lambda x:x.get("date",""))
            pts=[(_de_date(x["date"])[:6]+_de_date(x["date"])[8:10],x["score"],f"{_de_date(x['date'])}: {x['score']} Punkte – {x.get('severity','')}") for x in series]
            qchart.set_data(pts,Q.QUESTIONNAIRES[kind]["max"],Q.QUESTIONNAIRES[kind]["bands"],f"{Q.QUESTIONNAIRES[kind]['name']} – Verlauf")
        def q_kind_changed():
            q_stack.setCurrentIndex(q_kind.currentIndex()); q_live(); q_hist_refresh()
        def q_save_fn():
            if not state["cc"]: return QMessageBox.information(self,"Fragebogen","Bitte zuerst einen Klienten auswählen.")
            if not self.require_edit(): return
            kind=q_kind.currentText(); ans=q_forms[kind].answers(); res=Q.score(kind,ans)
            if res["missing"] and QMessageBox.question(self,"Fragebogen",f"Nicht alle Fragen sind beantwortet (Item {', '.join(map(str,res['missing']))}). Trotzdem speichern?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            entry={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"kind":kind,"date":q_date.date().toString("yyyy-MM-dd"),"answers":ans,"score":res["score"],"severity":res["severity"],"notes":res["notes"],"saved":datetime.now().isoformat(timespec="seconds")}
            q_results().append(entry); save_data(); audit("QUESTIONNAIRE_SAVED",f"{kind} {res['score']}: {state['cc'].get('last','')}, {state['cc'].get('first','')}",user())
            q_forms[kind].set_answers([None]*len(ans)); q_hist_refresh(); update_alert()
            msg=f"{kind} gespeichert: {res['score']} von {res['max']} Punkten ({res['severity']})."+("".join("\n\n"+n for n in res["notes"]))
            (QMessageBox.warning if any("Item 9" in n for n in res["notes"]) else QMessageBox.information)(self,"Fragebogen",msg)
        def q_big_fn():
            kind=q_kind.currentText(); dlg=QDialog(self); dlg.setWindowTitle(Q.QUESTIONNAIRES[kind]["name"]); dv=QVBoxLayout(dlg)
            big=QuestionnaireForm(kind,large=True); big.set_answers(q_forms[kind].answers()); s3=QScrollArea(); s3.setWidgetResizable(True); s3.setFrameShape(QFrame.NoFrame); s3.setWidget(big); dv.addWidget(s3,1)
            done=QPushButton("Fertig – zurück an die Praxis"); done.setMinimumHeight(56); done.setStyleSheet("font-size:20px;font-weight:700"); done.clicked.connect(dlg.accept); dv.addWidget(done)
            # Ergebnis wird der Klientin/dem Klienten nicht angezeigt; Übernahme erst nach „Fertig“.
            dlg.setWindowState(Qt.WindowMaximized)
            if dlg.exec()==QDialog.Accepted: q_forms[kind].set_answers(big.answers())
        def q_hdel_fn():
            r=qhist.currentRow()
            if r<0 or not self.require_edit(): return
            xid=qhist.item(r,0).data(Qt.UserRole); x=next((y for y in q_results() if y.get("id")==xid),None)
            if not x: return
            if QMessageBox.question(self,"Ergebnis löschen",f"{x.get('kind')} vom {_de_date(x.get('date',''))} ({x.get('score')} Punkte) löschen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            q_results().remove(x); save_data(); audit("QUESTIONNAIRE_DELETED",f"{x.get('kind')} {x.get('date')}",user()); q_hist_refresh()
        for fw in q_forms.values(): fw.changed.connect(q_live)
        q_kind.currentIndexChanged.connect(lambda *_: q_kind_changed()); q_save.clicked.connect(q_save_fn); q_big.clicked.connect(q_big_fn); q_hdel.clicked.connect(q_hdel_fn)
        q_clear.clicked.connect(lambda: q_forms[q_kind.currentText()].set_answers([None]*len(Q.QUESTIONNAIRES[q_kind.currentText()]["items"])))

        # ------------------------------------------------------------ Klientenwahl und Warnhinweis
        def update_alert():
            cc=state["cc"] or {}; msgs=[]
            s=(cc.get("anamnesis") or {}).get("suicidality","")
            if s in RISK_LEVELS: msgs.append(f"Anamnese: {s}")
            last_phq=sorted([x for x in cc.get("questionnaires",[]) if x.get("kind")=="PHQ-9"],key=lambda x:x.get("date",""))
            if last_phq and (last_phq[-1].get("answers") or [0]*9)[8] not in (None,0): msgs.append(f"PHQ-9 vom {_de_date(last_phq[-1]['date'])}: Item 9 (Suizidgedanken) positiv")
            self.therapy_alert.setText("⚠ Risikohinweis – "+" · ".join(msgs)+". Bitte im Gespräch aktiv abklären und Absprachen dokumentieren." if msgs else "")
            self.therapy_alert.setVisible(bool(msgs))
        def select_client():
            state["cc"]=resolve_client(pick.currentData())   # Original, nicht die Kopie aus der Auswahlliste
            # Reiter NICHT deaktivieren: deaktivierte Bereiche nehmen kein Mausrad an (Scrollen ging nicht).
            # Stattdessen Hinweis; Speichern ohne Klient wird in den Funktionen selbst abgefangen.
            self.therapy_hint.setVisible(state["cc"] is None)
            an_load(state["cc"]); g_load(None); g_refresh(); q_hist_refresh(); q_live(); update_alert()
            self.therapy_stats.setText(session_stats_text(state["cc"]) if state["cc"] else "")
        def refresh_clients():
            old=pick.currentData(); pick.blockSignals(True); pick.clear(); pick.addItem("Klient auswählen …",None)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                pick.addItem(f"{cc.get('last','')}, {cc.get('first','')}"+(f"  (geb. {cc.get('dob')})" if cc.get("dob") else ""),cc)
            i=next((k for k in range(pick.count()) if resolve_client(pick.itemData(k)) is resolve_client(old)),-1) if isinstance(old,dict) else -1
            pick.setCurrentIndex(max(0,i)); pick.blockSignals(False)
            if not (state["cc"] is not None and resolve_client(pick.currentData()) is state["cc"]): select_client()   # ungespeicherte Eingaben beim Zurückkehren behalten
        self.refresh_therapy=refresh_clients
        def open_for(cc):
            refresh_clients(); same=lambda d: isinstance(d,dict) and all(d.get(x,"")==cc.get(x,"") for x in ("last","first","dob"))
            i=next((k for k in range(pick.count()) if same(pick.itemData(k))),-1)
            if i>=0: pick.setCurrentIndex(i)
        self.open_therapy_for=open_for
        pick.currentIndexChanged.connect(lambda *_: select_client())
        refresh_clients(); q_kind_changed()
        return page

    def finance_ui(self):
        """Ausgaben mit Belegen, Kassenbuch (bar) und EÜR-Auswertung mit Export für den Steuerberater."""
        import finance as F
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Ausgaben & EÜR"); title.setObjectName("pageTitle"); v.addWidget(title)
        top=QHBoxLayout(); top.addWidget(QLabel("Jahr")); year=QComboBox(); this=date.today().year
        years=sorted({this}|{int(str(x.get("date",""))[:4]) for x in DB["expenses"]+DB["cash"] if str(x.get("date",""))[:4].isdigit()}|{int(str(i.get("paid_date",""))[:4]) for i in DB["invoices"] if str(i.get("paid_date",""))[:4].isdigit()},reverse=True)
        year.addItems([str(y_) for y_ in years]); top.addWidget(year); top.addStretch(); v.addLayout(top)
        tabs=QTabWidget(); tabs.setDocumentMode(True); v.addWidget(tabs,1); self.finance_tabs=tabs
        user=lambda: (self.current_user or {}).get("username","")
        Y=lambda: int(year.currentText())
        eur=lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")
        def money_item(x):
            it=QTableWidgetItem(eur(x) if x else ""); it.setTextAlignment(Qt.AlignRight|Qt.AlignVCenter); return it

        # ------------------------------------------------------------ Ausgaben
        ex_page=QWidget(); ev=QVBoxLayout(ex_page); ev.setContentsMargins(0,8,0,0)
        esplit=QSplitter(); esplit.setChildrenCollapsible(False); self.responsive_split(esplit,900)
        etable=QTableWidget(0,6); etable.setHorizontalHeaderLabels(["Datum","Kategorie","Beschreibung","Zahlart","Beleg","Betrag"]); etable.verticalHeader().setVisible(False)
        for col,mode in enumerate((QHeaderView.ResizeToContents,QHeaderView.ResizeToContents,QHeaderView.Stretch,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents)): etable.horizontalHeader().setSectionResizeMode(col,mode)
        etable.setSelectionBehavior(QTableWidget.SelectRows); etable.setSelectionMode(QTableWidget.SingleSelection); etable.setEditTriggers(QTableWidget.NoEditTriggers)
        eleft=QWidget(); elv=QVBoxLayout(eleft); elv.setContentsMargins(0,0,0,0); elv.addWidget(etable,1); esum=QLabel(""); esum.setStyleSheet("font-weight:700"); elv.addWidget(esum)
        ecard=QFrame(); ecard.setObjectName("formCard"); ecv=QVBoxLayout(ecard); ecv.setContentsMargins(14,10,14,12)
        etitle=QLabel("Neue Ausgabe"); etitle.setObjectName("sectionTitle"); ecv.addWidget(etitle)
        ef=QFormLayout(); ef.setVerticalSpacing(8)
        e_date=FlexDateEdit(QDate.currentDate()); e_date.setCalendarPopup(True); e_date.setDisplayFormat("dd.MM.yyyy")
        e_cat=QComboBox(); e_cat.addItems(F.EXPENSE_CATEGORIES); e_desc=QLineEdit(); e_desc.setPlaceholderText("z. B. Miete Praxisraum November")
        e_amt=QDoubleSpinBox(); e_amt.setRange(0,1000000); e_amt.setDecimals(2); e_amt.setSuffix(" €"); e_amt.setGroupSeparatorShown(True)
        e_pay=QComboBox(); e_pay.addItems(F.PAYMENT_METHODS); e_rec=QLabel("kein Beleg"); e_rec.setObjectName("pageSub")
        for lab,w_ in (("Datum",e_date),("Kategorie",e_cat),("Beschreibung",e_desc),("Betrag (brutto)",e_amt),("Zahlart",e_pay),("Beleg",e_rec)): ef.addRow(lab,w_)
        ecv.addLayout(ef)
        eb=QWidget(); ebl=FlowLayout(eb,hspacing=8,vspacing=8); ebl.setContentsMargins(0,4,0,0)
        b_enew=QPushButton("＋ Neue Ausgabe"); b_esave=QPushButton("💾 Speichern"); b_erec=QPushButton("📎 Beleg anhängen"); b_eopen=QPushButton("Beleg öffnen"); b_edel=QPushButton("Löschen")
        b_edel.setStyleSheet("background:white;color:#b5534b;border:1px solid #d9a9a4")
        for b in (b_enew,b_esave,b_erec,b_eopen,b_edel): b.setMinimumHeight(34); ebl.addWidget(b)
        ecv.addWidget(eb)
        hint=QLabel("Beträge brutto erfassen – die Praxis ist nach § 4 Nr. 14 UStG umsatzsteuerfrei, ein Vorsteuerabzug entfällt. Barzahlungen erscheinen automatisch im Kassenbuch. Belege werden verschlüsselt gespeichert."); hint.setWordWrap(True); hint.setObjectName("pageSub"); ecv.addWidget(hint); ecv.addStretch()
        esplit.addWidget(eleft); esplit.addWidget(ecard); esplit.setStretchFactor(0,3); esplit.setStretchFactor(1,2); ev.addWidget(esplit,1)
        tabs.addTab(ex_page,"Ausgaben")
        est={"id":None,"pending_receipt":None}
        def e_current(): return next((e for e in DB["expenses"] if e.get("id")==est["id"]),None)
        def e_refresh():
            etable.setRowCount(0); rows=F.expense_entries(DB["expenses"],Y())
            for e in reversed(rows):
                r=etable.rowCount(); etable.insertRow(r)
                for j,val in enumerate((_de_date(e.get("date","")),e.get("category",""),e.get("description",""),e.get("payment",""),"📎" if e.get("receipt") else "")):
                    it=QTableWidgetItem(val); it.setData(Qt.UserRole,e.get("id")); etable.setItem(r,j,it)
                etable.setItem(r,5,money_item(float(e.get("amount",0) or 0)))
            esum.setText(f"{len(rows)} Ausgaben {Y()}  ·  Summe {eur(sum(float(e.get('amount',0) or 0) for e in rows))}")
        def e_load(e):
            est["id"]=e.get("id") if e else None; est["pending_receipt"]=None
            if e: e_date.setDate(QDate.fromString(e.get("date",""),"yyyy-MM-dd"))
            else: e_date.setDate(QDate.currentDate())
            e_cat.setCurrentText(e.get("category",F.EXPENSE_CATEGORIES[0]) if e else F.EXPENSE_CATEGORIES[0]); e_desc.setText(e.get("description","") if e else "")
            e_amt.setValue(float(e.get("amount",0) or 0) if e else 0); e_pay.setCurrentText(e.get("payment","Überweisung") if e else "Überweisung")
            e_rec.setText(Path(e["receipt"]).name[:-4] if e and e.get("receipt") else "kein Beleg"); b_eopen.setEnabled(bool(e and e.get("receipt"))); b_edel.setEnabled(bool(e))
            etitle.setText("Ausgabe bearbeiten" if e else "Neue Ausgabe")
        def e_select():
            r=etable.currentRow()
            if r>=0: eid=etable.item(r,0).data(Qt.UserRole); e_load(next((x for x in DB["expenses"] if x.get("id")==eid),None))
        def store_receipt(src,e):
            folder=ROOT/"Ausgaben"/"Belege"/e["date"][:4]; folder.mkdir(parents=True,exist_ok=True)
            src=Path(src); target=folder/f"{e['date']}_{safe(e.get('category','').split(' /')[0])}_{safe(src.stem)}{src.suffix.lower()}.enc"; n=2
            while target.exists(): target=folder/f"{e['date']}_{safe(src.stem)}_{n}{src.suffix.lower()}.enc"; n+=1
            target.write_bytes(Fernet(encryption_key()).encrypt(src.read_bytes())); return str(target)
        def e_save():
            if not self.require_edit(): return None
            if e_amt.value()<=0: QMessageBox.warning(self,"Ausgabe","Bitte einen Betrag eingeben."); return None
            if not e_desc.text().strip(): QMessageBox.warning(self,"Ausgabe","Bitte eine kurze Beschreibung eingeben."); return None
            e=e_current()
            if e is None:
                e={"id":datetime.now().strftime("A%Y%m%d%H%M%S%f"),"created":datetime.now().isoformat(timespec="seconds")}; DB["expenses"].append(e); est["id"]=e["id"]
            e.update({"date":e_date.date().toString("yyyy-MM-dd"),"category":e_cat.currentText(),"description":e_desc.text().strip(),"amount":round(e_amt.value(),2),"payment":e_pay.currentText()})
            if est["pending_receipt"]: e["receipt"]=store_receipt(est["pending_receipt"],e)
            save_data(); audit("EXPENSE_SAVED",f"{e['date']} {e['category']} {e['amount']:.2f}",user()); e_refresh(); cash_refresh(); euer_refresh(); e_load(e); return e
        def e_receipt():
            f,_=QFileDialog.getOpenFileName(self,"Beleg auswählen",str(Path.home()),"Belege (*.pdf *.jpg *.jpeg *.png *.tif *.tiff);;Alle Dateien (*.*)")
            if not f: return
            est["pending_receipt"]=f; e_rec.setText(Path(f).name+"  (wird beim Speichern verschlüsselt übernommen)")
            if e_current() is not None: e_save()
        def e_open():
            e=e_current()
            if e and e.get("receipt") and Path(e["receipt"]).exists(): open_client_document(e["receipt"])
        def e_del():
            e=e_current()
            if not e or not self.require_edit(): return
            if QMessageBox.question(self,"Ausgabe löschen",f"Ausgabe vom {_de_date(e.get('date',''))} über {eur(float(e.get('amount',0)))} löschen?"+("\n\nDer verschlüsselte Beleg bleibt im Ordner „Ausgaben/Belege“ erhalten (Aufbewahrungspflicht)." if e.get("receipt") else ""),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            DB["expenses"].remove(e); save_data(); audit("EXPENSE_DELETED",f"{e.get('date')} {e.get('amount')}",user()); e_load(None); e_refresh(); cash_refresh(); euer_refresh()
        etable.itemSelectionChanged.connect(e_select); b_enew.clicked.connect(lambda: (etable.clearSelection(),e_load(None),e_desc.setFocus())); b_esave.clicked.connect(e_save); b_erec.clicked.connect(e_receipt); b_eopen.clicked.connect(e_open); b_edel.clicked.connect(e_del)

        # ------------------------------------------------------------ Kassenbuch
        ca_page=QWidget(); cv=QVBoxLayout(ca_page); cv.setContentsMargins(0,8,0,0)
        crow=QHBoxLayout(); crow.addWidget(QLabel("Anfangsbestand zum 1.1.")); c_open=QDoubleSpinBox(); c_open.setRange(0,1000000); c_open.setDecimals(2); c_open.setSuffix(" €"); crow.addWidget(c_open); crow.addStretch(); c_bal=QLabel(""); c_bal.setStyleSheet("font-weight:700"); crow.addWidget(c_bal); cv.addLayout(crow)
        ctable=QTableWidget(0,5); ctable.setHorizontalHeaderLabels(["Datum","Text","Einnahme","Ausgabe","Bestand"]); ctable.verticalHeader().setVisible(False)
        for col,mode in enumerate((QHeaderView.ResizeToContents,QHeaderView.Stretch,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents)): ctable.horizontalHeader().setSectionResizeMode(col,mode)
        ctable.setSelectionBehavior(QTableWidget.SelectRows); ctable.setEditTriggers(QTableWidget.NoEditTriggers); cv.addWidget(ctable,1)
        cform=QFrame(); cform.setObjectName("formCard"); cfl=QHBoxLayout(cform); cfl.setContentsMargins(12,8,12,8)
        c_kind=QComboBox(); c_kind.addItems(["Einnahme","Entnahme / Einzahlung Bank"]); c_date=FlexDateEdit(QDate.currentDate()); c_date.setCalendarPopup(True); c_date.setDisplayFormat("dd.MM.yyyy")
        c_text=QLineEdit(); c_text.setPlaceholderText("Text, z. B. Barzahlung Sitzung"); c_inv=QComboBox(); c_inv.setEditable(True); c_inv.setMinimumContentsLength(10); c_inv.lineEdit().setPlaceholderText("Rechnungs-Nr. (optional)")
        c_amt=QDoubleSpinBox(); c_amt.setRange(0,100000); c_amt.setDecimals(2); c_amt.setSuffix(" €")
        c_add=QPushButton("＋ Buchen"); c_del=QPushButton("Ausgewählte Buchung löschen"); c_del.setStyleSheet("background:white;color:#b5534b;border:1px solid #d9a9a4")
        for w_ in (c_kind,c_date,c_text,c_inv,c_amt,c_add): cfl.addWidget(w_,1 if w_ is c_text else 0)
        cv.addWidget(cform); cdel_row=QHBoxLayout(); cdel_row.addStretch(); cdel_row.addWidget(c_del); cv.addLayout(cdel_row)
        chint=QLabel("Barausgaben werden im Reiter „Ausgaben“ mit Zahlart „Bar“ erfasst und erscheinen hier automatisch. Eine Bareinnahme mit Rechnungsnummer markiert die Rechnung als bezahlt."); chint.setWordWrap(True); chint.setObjectName("pageSub"); cv.addWidget(chint)
        tabs.addTab(ca_page,"Kassenbuch (bar)")
        def cash_refresh():
            c_open.blockSignals(True); c_open.setValue(float(get_setting(f"cash_opening_{Y()}","0") or 0)); c_open.blockSignals(False)
            rows,bal=F.cash_book(DB["expenses"],DB["cash"],Y(),c_open.value()); ctable.setRowCount(0)
            for row_ in rows:
                r=ctable.rowCount(); ctable.insertRow(r)
                it=QTableWidgetItem(_de_date(row_["date"])); it.setData(Qt.UserRole,row_["id"]); it.setData(Qt.UserRole+1,row_["kind"]); ctable.setItem(r,0,it); ctable.setItem(r,1,QTableWidgetItem(row_["text"]))
                ctable.setItem(r,2,money_item(row_["in"])); ctable.setItem(r,3,money_item(row_["out"])); b_=money_item(row_["balance"]) if row_["balance"] else QTableWidgetItem("0,00 €")
                if row_["balance"]<0: b_.setForeground(QColor("#b5534b"))
                ctable.setItem(r,4,b_)
            c_bal.setText(f"Kassenbestand: {eur(bal)}"+("   ⚠ negativ – Buchungen prüfen" if bal<0 else ""))
            c_inv.clear(); c_inv.addItem("")
            for inv in DB["invoices"]:
                if inv.get("status","offen")=="offen": c_inv.addItem(f"{inv.get('number','')}",inv.get("number",""))
        def c_book():
            if not self.require_edit(): return
            if c_amt.value()<=0: return QMessageBox.warning(self,"Kassenbuch","Bitte einen Betrag eingeben.")
            kind="Einnahme" if c_kind.currentIndex()==0 else "Entnahme"
            no=c_inv.currentText().strip() if kind=="Einnahme" else ""
            entry={"id":datetime.now().strftime("K%Y%m%d%H%M%S%f"),"kind":kind,"date":c_date.date().toString("yyyy-MM-dd"),"text":c_text.text().strip() or ("Bareinnahme" if kind=="Einnahme" else "Einzahlung auf Bankkonto"),"amount":round(c_amt.value(),2),"invoice":no}
            inv=next((i for i in DB["invoices"] if i.get("number")==no),None) if no else None
            if inv is not None and inv.get("status","offen")=="offen":
                if abs(float(inv.get("amount",0) or 0)-entry["amount"])>0.009 and QMessageBox.question(self,"Kassenbuch",f"Rechnung {no} lautet über {eur(float(inv.get('amount',0)))}, gebucht werden {eur(entry['amount'])}. Trotzdem als bezahlt markieren?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: inv=None
                if inv is not None:
                    inv["status"]="bezahlt"; inv["paid_date"]=entry["date"]; inv["reminder_closed"]=True; inv["paid_method"]="Bar"; audit("INVOICE_PAID",f"Rechnung {no} bar bezahlt",user())
            DB["cash"].append(entry); save_data(); update_excel(); audit("CASH_BOOKED",f"{entry['kind']} {entry['amount']:.2f}",user())
            c_text.clear(); c_amt.setValue(0); cash_refresh(); euer_refresh()
        def c_delete():
            r=ctable.currentRow()
            if r<0 or not self.require_edit(): return
            cid_,kind=ctable.item(r,0).data(Qt.UserRole),ctable.item(r,0).data(Qt.UserRole+1)
            if kind=="Ausgabe": return QMessageBox.information(self,"Kassenbuch","Barausgaben bitte im Reiter „Ausgaben“ ändern oder löschen.")
            entry=next((c for c in DB["cash"] if c.get("id")==cid_),None)
            if not entry or QMessageBox.question(self,"Buchung löschen",f"Buchung „{entry.get('text','')}“ über {eur(float(entry.get('amount',0)))} löschen?"+("\n\nDie Rechnung bleibt als bezahlt markiert." if entry.get("invoice") else ""),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            DB["cash"].remove(entry); save_data(); audit("CASH_DELETED",entry.get("text",""),user()); cash_refresh(); euer_refresh()
        c_open.valueChanged.connect(lambda val: (set_setting(f"cash_opening_{Y()}",f"{val:.2f}"),cash_refresh()))
        c_kind.currentIndexChanged.connect(lambda i: c_inv.setVisible(i==0)); c_add.clicked.connect(c_book); c_del.clicked.connect(c_delete)

        # ------------------------------------------------------------ EÜR
        eu_page=QWidget(); uv=QVBoxLayout(eu_page); uv.setContentsMargins(0,8,0,0)
        kpis=QHBoxLayout(); kpi_labels={}
        for key,cap in (("income_total","EINNAHMEN (ZUFLUSS)"),("expense_total","AUSGABEN"),("result","ERGEBNIS")):
            box=QFrame(); box.setObjectName("statCard"); box.setMinimumHeight(90); q=QVBoxLayout(box); a=QLabel(cap); a.setObjectName("cardCaption"); b=QLabel(""); b.setObjectName("cardValue"); q.addWidget(a); q.addWidget(b); kpi_labels[key]=b; kpis.addWidget(box)
        uv.addLayout(kpis)
        usplit=QSplitter(); usplit.setChildrenCollapsible(False); self.responsive_split(usplit,900)
        mtable=QTableWidget(13,4); mtable.setHorizontalHeaderLabels(["Monat","Einnahmen","Ausgaben","Ergebnis"]); mtable.verticalHeader().setVisible(False); mtable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); mtable.setEditTriggers(QTableWidget.NoEditTriggers)
        ctab=QTableWidget(0,2); ctab.setHorizontalHeaderLabels(["Ausgaben nach Kategorie","Betrag"]); ctab.verticalHeader().setVisible(False); ctab.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch); ctab.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents); ctab.setEditTriggers(QTableWidget.NoEditTriggers)
        usplit.addWidget(mtable); usplit.addWidget(ctab); usplit.setStretchFactor(0,3); usplit.setStretchFactor(1,2); uv.addWidget(usplit,1)
        xrow=QHBoxLayout(); x_names=QCheckBox("Klientennamen in der Einnahmenliste mit ausgeben (sonst nur Rechnungsnummern)"); xrow.addWidget(x_names,1)
        x_btn=QPushButton("⇩ Export für Steuerberater (Excel + CSV)"); x_btn.setMinimumHeight(40); xrow.addWidget(x_btn); uv.addLayout(xrow)
        unote=QLabel("Einnahmen nach Zahlungseingang (Zuflussprinzip), Ausgaben brutto. Die Auswertung ist eine Arbeitshilfe und ersetzt keine Steuerberatung."); unote.setWordWrap(True); unote.setObjectName("pageSub"); uv.addWidget(unote)
        tabs.addTab(eu_page,"EÜR / Steuerberater")
        def euer_refresh():
            s=F.euer_summary(DB["invoices"],DB["expenses"],DB["cash"],Y())
            for key,lab in kpi_labels.items(): lab.setText(eur(s[key])); lab.setStyleSheet("color:#b5534b" if key=="result" and s[key]<0 else "")
            for r,m in enumerate(s["months"]+[{"month":"Summe","income":s["income_total"],"expenses":s["expense_total"],"result":s["result"]}]):
                mtable.setItem(r,0,QTableWidgetItem(m["month"])); mtable.setItem(r,1,money_item(m["income"])); mtable.setItem(r,2,money_item(m["expenses"])); it=money_item(m["result"]) if m["result"] else QTableWidgetItem("–"); mtable.setItem(r,3,it)
                if r==12:
                    for c_ in range(4):
                        f_=mtable.item(r,c_).font(); f_.setBold(True); mtable.item(r,c_).setFont(f_)
            ctab.setRowCount(0)
            for k,val in s["categories"].items():
                r=ctab.rowCount(); ctab.insertRow(r); ctab.setItem(r,0,QTableWidgetItem(k)); ctab.setItem(r,1,money_item(val))
            return s
        def export():
            s=euer_refresh(); folder=ROOT/"Einnahmen"; folder.mkdir(parents=True,exist_ok=True)
            rows,_=F.cash_book(DB["expenses"],DB["cash"],Y(),float(get_setting(f"cash_opening_{Y()}","0") or 0))
            try:
                x=F.export_xlsx(folder/f"EUER_{Y()}.xlsx",s,x_names.isChecked(),rows,float(get_setting(f"cash_opening_{Y()}","0") or 0)); c=F.export_csv(folder/f"Buchungen_{Y()}.csv",s)
            except PermissionError:
                return QMessageBox.warning(self,"Export","Die Datei ist noch in Excel geöffnet. Bitte Excel schließen und erneut exportieren.")
            audit("EUER_EXPORT",f"{Y()} Namen={'ja' if x_names.isChecked() else 'nein'}",user())
            QMessageBox.information(self,"Export",f"Erstellt im Ordner „Einnahmen“:\n• {Path(x).name}\n• {Path(c).name}\n\nDer Ordner wird jetzt geöffnet.")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        x_btn.clicked.connect(export)
        def all_refresh(): e_refresh(); cash_refresh(); euer_refresh()
        year.currentIndexChanged.connect(lambda *_: all_refresh()); self.refresh_finance=all_refresh
        e_load(None); all_refresh()
        return page

    def documents_ui(self):
        """Formulare & Briefe: Vorlagen mit Klientendaten befüllen, bearbeiten, unterschreiben lassen, als PDF ablegen."""
        T=document_templates.TEMPLATES
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Formulare & Briefe"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("① Vorlage und Klient wählen  ·  ② Text prüfen  ·  ③ unterschreiben  ·  ④ PDF erstellen – abgelegt in der Klientenakte unter „Dokumente“"); sub.setObjectName("pageSub"); sub.setWordWrap(True); v.addWidget(sub)
        split=QSplitter(); split.setChildrenCollapsible(False); self.responsive_split(split,860)
        left=QFrame(); left.setObjectName("formCard"); lv=QVBoxLayout(left); lv.setContentsMargins(14,12,14,14); lv.setSpacing(8)
        lt=QLabel("Vorlage"); lt.setObjectName("sectionTitle"); lv.addWidget(lt)
        self.doc_list=QListWidget(); self.doc_list.setMinimumHeight(190)
        for key in document_templates.ORDER:
            it=QListWidgetItem(T[key]["title"]); it.setData(Qt.UserRole,key); self.doc_list.addItem(it)
        lv.addWidget(self.doc_list)
        ct=QLabel("Klient"); ct.setObjectName("sectionTitle"); lv.addWidget(ct)
        self.doc_client=QComboBox(); self.doc_client.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); self.doc_client.setMinimumContentsLength(16); self.doc_client.setEditable(True); self.doc_client.setInsertPolicy(QComboBox.NoInsert); self.doc_client.setMinimumHeight(34)
        self.doc_client.completer().setCompletionMode(QCompleter.PopupCompletion); self.doc_client.completer().setFilterMode(Qt.MatchContains); self.doc_client.completer().setCaseSensitivity(Qt.CaseInsensitive)
        lv.addWidget(self.doc_client)
        self.doc_rec_label=QLabel("Empfänger (Arzt, Versicherung, Person – eine Angabe pro Zeile)"); self.doc_rec_label.setWordWrap(True); lv.addWidget(self.doc_rec_label)
        self.doc_recipient=QTextEdit(); self.doc_recipient.setPlaceholderText("z. B.\nDr. med. Erika Beispiel\nHauptstraße 1\n10115 Berlin"); self.doc_recipient.setFixedHeight(96); lv.addWidget(self.doc_recipient)
        lv.addWidget(QLabel("Ort, Datum"))
        self.doc_place=QLineEdit(); self.doc_place.setMinimumHeight(34); lv.addWidget(self.doc_place)
        refill=QPushButton("↻ Text neu befüllen"); refill.setToolTip("Dokumenttext mit Klient, Empfänger und Vorlage neu erzeugen"); refill.setMinimumHeight(36); lv.addWidget(refill)
        ht=QLabel("Bisherige Dokumente"); ht.setObjectName("sectionTitle"); lv.addWidget(ht)
        self.doc_history=QListWidget(); self.doc_history.setMinimumHeight(110); self.doc_history.setToolTip("Doppelklick öffnet das PDF"); lv.addWidget(self.doc_history,1)
        openfolder=QPushButton("📂 Dokumente-Ordner öffnen"); openfolder.setMinimumHeight(34); lv.addWidget(openfolder)
        left.setMinimumWidth(290); left.setMaximumWidth(420); self.doc_list.setWordWrap(True)

        right=QFrame(); right.setObjectName("formCard"); rv=QVBoxLayout(right); rv.setContentsMargins(14,12,14,14); rv.setSpacing(8)
        self.doc_title=QLabel(""); self.doc_title.setObjectName("sectionTitle"); rv.addWidget(self.doc_title)
        tabs=QTabWidget(); tabs.setDocumentMode(True)
        self.doc_body=QTextEdit(); self.doc_body.setAcceptRichText(False); self.doc_body.setMinimumHeight(360)
        tabs.addTab(self.doc_body,"Dokument für diesen Klienten")
        tplpage=QWidget(); tv=QVBoxLayout(tplpage); tv.setContentsMargins(0,8,0,0)
        tip=QLabel("Hier ändern Sie die Vorlage selbst – für alle künftigen Dokumente. Platzhalter in {geschweiften Klammern} werden automatisch ersetzt. "
                   "Zeilen mit „## “ werden Überschriften, „• “ Aufzählungen, „[ ] “ Ankreuzfelder, „A | B“ Tabellenzeilen."); tip.setWordWrap(True); tip.setObjectName("pageSub"); tv.addWidget(tip)
        self.doc_tpl_edit=QTextEdit(); self.doc_tpl_edit.setAcceptRichText(False); tv.addWidget(self.doc_tpl_edit,1)
        ph=QComboBox(); ph.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); ph.setMinimumContentsLength(18); ph.addItem("Platzhalter einfügen …",None)
        for k,desc in document_templates.PLACEHOLDERS.items(): ph.addItem("{"+k+"}  –  "+desc,k)
        tb=QHBoxLayout(); tb.addWidget(ph,1); tplsave=QPushButton("💾 Als meine Vorlage speichern"); tplreset=QPushButton("Original wiederherstellen"); tb.addWidget(tplsave); tb.addWidget(tplreset); tv.addLayout(tb)
        tabs.addTab(tplpage,"Vorlage bearbeiten"); rv.addWidget(tabs,1)

        sigbox=QFrame(); sg=QGridLayout(sigbox); sg.setContentsMargins(0,4,0,0); sg.setHorizontalSpacing(12)
        self.doc_sig={}; self.doc_sig_boxes={}
        for col,(who,label) in enumerate((("client","Unterschrift Klient/in"),("therapist","Unterschrift Therapeut/in"))):
            box=QWidget(); bl=QVBoxLayout(box); bl.setContentsMargins(0,0,0,0); bl.setSpacing(4)
            head=QHBoxLayout(); head.addWidget(QLabel("<b>"+label+"</b>")); head.addStretch(); clr=QPushButton("Löschen"); clr.setMinimumHeight(28); head.addWidget(clr); bl.addLayout(head)
            pad=SignaturePad("Hier mit Finger, Stift oder Maus unterschreiben"); bl.addWidget(pad); clr.clicked.connect(pad.clear)
            self.doc_sig[who]=pad; self.doc_sig_boxes[who]=box; sg.addWidget(box,0,col)
        sighint=QLabel("Ohne Unterschrift im Feld entsteht eine leere Unterschriftslinie – dann einfach ausdrucken und auf Papier unterschreiben."); sighint.setWordWrap(True); sighint.setObjectName("pageSub"); sg.addWidget(sighint,1,0,1,2)
        rv.addWidget(sigbox)
        actions=QHBoxLayout(); actions.addStretch(); make=QPushButton("📄 PDF erstellen und öffnen"); make.setMinimumHeight(42); make.setMinimumWidth(240); make.setStyleSheet("font-weight:700"); actions.addWidget(make); rv.addLayout(actions)
        split.addWidget(left); split.addWidget(right); split.setStretchFactor(0,2); split.setStretchFactor(1,5); v.addWidget(split,1)

        def current_key():
            it=self.doc_list.currentItem(); return it.data(Qt.UserRole) if it else document_templates.ORDER[0]
        def current_client():
            c=self.doc_client.currentData()
            if isinstance(c,dict) and self.doc_client.currentText().strip()==self.doc_client.itemText(self.doc_client.currentIndex()): return resolve_client(c) or c
            return None
        def refill_body(ask=True):
            if ask and self.doc_body.document().isModified() and self.doc_body.toPlainText().strip():
                if QMessageBox.question(self,"Text neu befüllen","Ihre Änderungen im Dokumenttext gehen dabei verloren. Fortfahren?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            key=current_key(); vals=document_values(current_client(),self.doc_recipient.toPlainText())
            self.doc_body.setPlainText(document_templates.fill(document_template_text(key),vals)); self.doc_body.document().setModified(False)
        def refresh_history():
            self.doc_history.clear(); c=current_client()
            if not c: return
            folder=ROOT/"Klienten"/safe(f"{c.get('last','')}, {c.get('first','')}")/"Dokumente"
            if folder.exists():
                for f in sorted(folder.glob("*.pdf"),key=lambda p:p.stat().st_mtime,reverse=True):
                    it=QListWidgetItem(f.stem.replace("_"," ",1)); it.setData(Qt.UserRole,str(f)); self.doc_history.addItem(it)
            if not self.doc_history.count(): self.doc_history.addItem("– noch keine Dokumente –")
        def template_changed():
            key=current_key(); tpl=T[key]; self.doc_title.setText(tpl["title"])
            self.doc_rec_label.setVisible(tpl["recipient"]); self.doc_recipient.setVisible(tpl["recipient"])
            for who,box in self.doc_sig_boxes.items(): box.setVisible(who in tpl["signatures"])
            self.doc_tpl_edit.setPlainText(document_template_text(key)); self.doc_tpl_edit.document().setModified(False)
            for pad in self.doc_sig.values(): pad.clear()
            refill_body(ask=False)
        def client_changed():
            refresh_history(); refill_body(ask=False)
        def refresh_clients():
            old=self.doc_client.currentData(); self.doc_client.blockSignals(True); self.doc_client.clear(); self.doc_client.addItem("Klient auswählen …",None)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                self.doc_client.addItem(f"{cc.get('last','')}, {cc.get('first','')}"+(f"  (geb. {cc.get('dob')})" if cc.get("dob") else ""),cc)
            idx=self.doc_client.findData(old) if isinstance(old,dict) else -1
            self.doc_client.setCurrentIndex(idx if idx>=0 else 0); self.doc_client.blockSignals(False)
            if not self.doc_place.text().strip(): self.doc_place.setText(", ".join(x for x in (practice_city(),datetime.now().strftime("%d.%m.%Y")) if x))
        self.refresh_document_clients=lambda: (refresh_clients(),refresh_history())
        def insert_placeholder(i):
            k=ph.itemData(i)
            if k: self.doc_tpl_edit.insertPlainText("{"+k+"}"); self.doc_tpl_edit.setFocus()
            ph.blockSignals(True); ph.setCurrentIndex(0); ph.blockSignals(False)
        def save_template():
            if not self.require_edit(): return
            key=current_key(); set_setting("doc_tpl_"+key,self.doc_tpl_edit.toPlainText()); audit("DOC_TEMPLATE_SAVED",T[key]["title"],self.current_user.get("username",""))
            refill_body(ask=True); QMessageBox.information(self,"Vorlage","Die Vorlage wurde gespeichert und wird ab jetzt verwendet.")
        def reset_template():
            key=current_key()
            if QMessageBox.question(self,"Original wiederherstellen","Eigene Änderungen an dieser Vorlage verwerfen und den Originaltext wiederherstellen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            set_setting("doc_tpl_"+key,""); self.doc_tpl_edit.setPlainText(T[key]["text"]); refill_body(ask=True)
        def make_pdf():
            if not self.require_edit(): return
            c=current_client()
            if not c: return QMessageBox.warning(self,"Formular","Bitte zuerst einen Klienten auswählen.")
            key=current_key(); body=self.doc_body.toPlainText().strip()
            if not body: return QMessageBox.warning(self,"Formular","Der Dokumenttext ist leer.")
            if T[key]["recipient"] and not self.doc_recipient.toPlainText().strip():
                if QMessageBox.question(self,"Empfänger fehlt","Es ist kein Empfänger angegeben. Trotzdem erstellen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            open_left=re.findall(r"\{[a-z_]+\}",body)
            if open_left and QMessageBox.question(self,"Platzhalter","Im Text stehen noch unbekannte Platzhalter: "+", ".join(sorted(set(open_left)))+"\n\nTrotzdem erstellen?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            tmpdir=Path(tempfile.mkdtemp(prefix="praxispro_sig_")); sigs={}
            try:
                for who in T[key]["signatures"]:
                    pad=self.doc_sig[who]
                    if not pad.is_empty():
                        p=tmpdir/f"{who}.png"
                        if pad.save_png(p): sigs[who]=str(p)
                out=write_document_pdf(c,key,body,self.doc_recipient.toPlainText(),self.doc_place.text().strip(),sigs,self.current_user.get("username",""))
            except Exception as e:
                audit("DOCUMENT_ERROR",str(e)[:300],self.current_user.get("username","")); return QMessageBox.critical(self,"Formular","Das PDF konnte nicht erstellt werden:\n"+str(e))
            finally:
                shutil.rmtree(tmpdir,ignore_errors=True)
            for pad in self.doc_sig.values(): pad.clear()
            refresh_history(); self.doc_body.document().setModified(False)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        def open_history(item):
            p=item.data(Qt.UserRole)
            if p and Path(p).exists(): QDesktopServices.openUrl(QUrl.fromLocalFile(p))
        def open_folder():
            c=current_client()
            if not c: return QMessageBox.information(self,"Dokumente","Bitte zuerst einen Klienten auswählen.")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(client_dir(c)/"Dokumente")))
        self.doc_list.currentRowChanged.connect(lambda *_: template_changed()); self.doc_client.currentIndexChanged.connect(lambda *_: client_changed())
        refill.clicked.connect(lambda: refill_body(ask=True)); ph.currentIndexChanged.connect(insert_placeholder)
        tplsave.clicked.connect(save_template); tplreset.clicked.connect(reset_template); make.clicked.connect(make_pdf)
        self.doc_history.itemDoubleClicked.connect(open_history); openfolder.clicked.connect(open_folder)
        refresh_clients(); self.doc_list.setCurrentRow(0)
        return page

    def session_ui(self):
        self.session_live_clock=None
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea(); scroll.setObjectName("sessionScroll"); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body=QWidget(); body.setMinimumWidth(0); v=QVBoxLayout(body); v.setContentsMargins(16,10,16,12); v.setSpacing(8)
        head=QVBoxLayout(); head.setSpacing(0); title=QLabel("Sitzung dokumentieren"); title.setObjectName("pageTitle"); subtitle=QLabel("① Klient & Sitzungsdaten  ·  ② Notizen & Hausaufgaben  ·  ③ Handschrift  ·  ④ Speichern"); subtitle.setObjectName("pageSub"); head.addWidget(title); head.addWidget(subtitle); v.addLayout(head)
        # Steuerleiste: Uhr, Sitzungsdauer und alle Sitzungsaktionen an einer Stelle (früher oben UND unten verteilt).
        control=QFrame(); control.setObjectName("formCard"); control_l=FlowLayout(control,hspacing=8,vspacing=8); control_l.setContentsMargins(12,8,12,8)
        self.session_live_clock=QLabel(QTime.currentTime().toString("HH:mm:ss")); self.session_live_clock.setAlignment(Qt.AlignCenter); self.session_live_clock.setMinimumWidth(90); self.session_live_clock.setFixedHeight(38); self.session_live_clock.setToolTip("Aktuelle Uhrzeit – live"); self.session_live_clock.setStyleSheet("font-size:15px;font-weight:700;color:#4b5b52")
        self.clock=QLabel("00:00:00"); self.clock.setAlignment(Qt.AlignCenter); self.clock.setMinimumWidth(110); self.clock.setFixedHeight(38); self.clock.setToolTip("Sitzungsdauer"); self.clock.setStyleSheet("font-size:20px;font-weight:800;color:#2c3b33;border:1px solid #c5d0c9;border-radius:8px;background:#f6f8f6")
        for caption,widget in (("Uhrzeit",self.session_live_clock),("Dauer",self.clock)):
            lab=QLabel(caption); lab.setFixedHeight(38); lab.setAlignment(Qt.AlignVCenter|Qt.AlignLeft); lab.setStyleSheet("color:#6b7a72"); control_l.addWidget(lab); control_l.addWidget(widget)
        gap=QWidget(); gap.setFixedWidth(16); control_l.addWidget(gap)
        for text_,fn,style in [("▶ Start",self.start_session,"background:#5f8a72"),("⏸ Pause",self.pause,"background:#6f8796"),("■ Beenden",self.end_session,"background:#b5534b"),("💾 Sitzung speichern",self.save_session,"background:white;color:#2c3b33;border:1px solid #9fb3a6")]:
            b=QPushButton(text_); b.setMinimumHeight(38); b.setStyleSheet(style+";font-weight:700"); b.clicked.connect(fn); control_l.addWidget(b)
        v.addWidget(control)

        row=QSplitter(); row.setChildrenCollapsible(False); row.setHandleWidth(8); self.responsive_split(row,1000)
        session=QFrame(); session.setObjectName("formCard"); sg=QGridLayout(session); sg.setContentsMargins(10,8,10,10); sg.setHorizontalSpacing(7); sg.setVerticalSpacing(6)
        st=QLabel("▤  Sitzungsdaten"); st.setObjectName("sectionTitle"); sg.addWidget(st,0,0,1,3)
        self.client_pick=QComboBox(); self.client_pick.setEditable(True); self.client_pick.setInsertPolicy(QComboBox.NoInsert); self.client_pick.setPlaceholderText("Klient auswählen …"); self.client_pick.addItem("Klient auswählen …",None)
        for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())): self.client_pick.addItem(f"{cc.get('last','')}, {cc.get('first','')}",cc)
        newclient=QPushButton("＋ Neu"); newclient.setMinimumHeight(28); newclient.setMaximumWidth(72); newclient.clicked.connect(lambda: self.open_new_client_dialog())
        self.s_date=FlexDateEdit(QDate.currentDate()); self.s_date.setCalendarPopup(True); self.s_date.setDisplayFormat("dd.MM.yyyy")
        self.s_start=FlexTimeEdit(QTime.currentTime()); self.s_end=FlexTimeEdit(QTime.currentTime().addSecs(45*60)); self.s_start.setDisplayFormat("HH:mm"); self.s_end.setDisplayFormat("HH:mm")
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
        sg.addWidget(self.s_red,7,1,1,2); sg.setColumnStretch(1,2); sg.setColumnStretch(2,1); session.setMinimumWidth(0); session.setMaximumWidth(410); session.setMinimumHeight(270); row.addWidget(session)

        details=QFrame(); details.setObjectName("formCard"); dg=QGridLayout(details); dg.setContentsMargins(10,8,10,10); dg.setHorizontalSpacing(7); dg.setVerticalSpacing(6)
        dt=QLabel("●  Klientendaten"); dt.setObjectName("sectionTitle"); dg.addWidget(dt,0,0,1,2)
        self.s_last=QLineEdit(); self.s_first=QLineEdit(); self.s_dob=QLineEdit()
        for x in (self.s_last,self.s_first,self.s_dob): x.setMinimumHeight(30); x.setReadOnly(True); x.setPlaceholderText("–")
        self.s_phone=QLineEdit(); self.s_email=QLineEdit()
        for x in (self.s_phone,self.s_email): x.setMinimumHeight(30); x.setReadOnly(True); x.setPlaceholderText("–")
        for rr,(lab,field) in enumerate([("Nachname",self.s_last),("Vorname",self.s_first),("Geburtsdatum",self.s_dob),("Telefon",self.s_phone),("E-Mail",self.s_email)],1): dg.addWidget(QLabel(lab),rr,0); dg.addWidget(field,rr,1)
        details.setMinimumWidth(0); details.setMaximumWidth(330); details.setMinimumHeight(270); editclient=QPushButton("♙ Klientendaten bearbeiten"); editclient.setFixedHeight(30); dg.addWidget(editclient,6,0,1,2); row.addWidget(details)

        quick=QFrame(); quick.setObjectName("formCard"); qg=QGridLayout(quick); qg.setContentsMargins(10,8,10,10); qg.setHorizontalSpacing(7); qg.setVerticalSpacing(6)
        qt=QLabel("♙＋  Klient schnell anlegen"); qt.setObjectName("sectionTitle"); qg.addWidget(qt,0,0,1,2)
        qlast=QLineEdit(); qfirst=QLineEdit(); qdob=QLineEdit(); qdob.setPlaceholderText("TT.MM.JJJJ"); qphone=QLineEdit(); qmail=QLineEdit()
        for x in (qlast,qfirst,qdob,qphone,qmail): x.setMinimumHeight(30)
        qg.addWidget(QLabel("Nachname *"),1,0); qg.addWidget(QLabel("Vorname *"),1,1); qg.addWidget(qlast,2,0); qg.addWidget(qfirst,2,1)
        qg.addWidget(QLabel("Geburtsdatum"),3,0,1,2); qg.addWidget(qdob,4,0,1,2); qg.addWidget(QLabel("Telefon"),5,0); qg.addWidget(QLabel("E-Mail"),5,1); qg.addWidget(qphone,6,0); qg.addWidget(qmail,6,1)
        qsave=QPushButton("Klient anlegen"); qsave.setFixedHeight(30); qg.addWidget(qsave,7,0,1,2); quick.setMinimumWidth(0); quick.setMaximumWidth(330); quick.setMinimumHeight(270); row.addWidget(quick); row.setStretchFactor(0,4); row.setStretchFactor(1,3); v.addWidget(row)
        # Schnellanlage ausgeblendet: „＋ Neu“ öffnet denselben Vorgang als Dialog (mit Adresse und Diagnose).
        quick.setVisible(False); newclient.setToolTip("Neuen Klienten anlegen")
        details.setMaximumWidth(16777215); session.setMaximumWidth(16777215)

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
        # Lange F-Code-Texte dürfen das Diagnosefeld nicht zusammendrücken.
        fquick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon); fquick.setMinimumContentsLength(16); self.session_diag.setMinimumWidth(180)
        cg.addWidget(QLabel("Verdachtsdiagnose / ICD"),1,0); cg.addWidget(self.session_diag,1,1,1,2); cg.addWidget(fquick,1,3); cg.setColumnStretch(1,1); cg.setColumnStretch(3,1)
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
        self.notes.setMinimumHeight(180); self.notes.setMaximumHeight(320); nv.addWidget(self.notes)
        # Therapienotiz und Hausaufgaben nebeneinander (bei schmalem Fenster untereinander).
        textrow=QSplitter(); textrow.setChildrenCollapsible(False); textrow.addWidget(notesbox); self.responsive_split(textrow,1000); v.addWidget(textrow)
        homeworkbox=QFrame(); homeworkbox.setObjectName("formCard"); hv=QVBoxLayout(homeworkbox); hv.setContentsMargins(16,12,16,14); hv.setSpacing(10); hh=QLabel("✓  Hausaufgaben / Vereinbarungen"); hh.setObjectName("sectionTitle"); hh.setToolTip("Bis zur nächsten Sitzung"); hv.addWidget(hh)
        self.session_homework=QTextEdit(); self.session_homework.setPlaceholderText("Hausaufgaben, Übungen, Beobachtungsaufträge oder konkrete Vereinbarungen bis zur nächsten Sitzung …"); self.session_homework.setMinimumHeight(180); self.session_homework.setMaximumHeight(320)
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
        hv.addWidget(self.session_homework); textrow.addWidget(homeworkbox); textrow.setStretchFactor(0,3); textrow.setStretchFactor(1,2)

        self.ink=InkCanvas(); self.current_ink_file=""; self.current_ocr_text=""; inkhead=QHBoxLayout(); inklabel=QLabel("✎  Handschrift / Touch / Stift"); inklabel.setObjectName("sectionTitle"); inkhead.addWidget(inklabel); inkhead.addStretch(); self.ink_clock=QLabel(QTime.currentTime().toString("HH:mm:ss")); self.ink_clock.setStyleSheet("font-size:18px;font-weight:800"); inkhead.addWidget(self.ink_clock); self.ink_clock_timer=QTimer(self); self.ink_clock_timer.timeout.connect(lambda: (self.ink_clock.setText(QTime.currentTime().toString("HH:mm:ss")), self.ink.update())); self.ink_clock_timer.start(1000)
        eraser=QCheckBox("Radierer"); eraser.toggled.connect(self.ink.set_eraser)
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); clearink=QPushButton("Zeichenfläche löschen"); clearink.clicked.connect(lambda: (self.ink.clear(),(setattr(self,'_last_ink_text',''),setattr(self,'_last_ink_stamp','')))); saveink=QPushButton("💾 Notiz speichern"); saveink.clicked.connect(self.save_ink_note); ocrink=QPushButton("⌨ Handschrift → Text"); ocrink.setToolTip("Lokale Windows-Handschrifterkennung; erkannter Text wird vor Übernahme angezeigt."); ocrink.clicked.connect(self.ink_to_text); ocrtest=QPushButton("OCR-Test"); ocrtest.setToolTip("Prüft Windows-OCR und installierte Erkennungssprachen."); ocrtest.clicked.connect(self.ocr_system_test); fullscreen=QPushButton("⛶ Notizbuch"); fullscreen.clicked.connect(self.open_ink_fullscreen)
        inktools=FlowLayout(hspacing=8,vspacing=6)
        for x in self.make_pen_tools(eraser)+[eraser,undo,saveink,ocrink,ocrtest,clearink,fullscreen]:
            if isinstance(x,QPushButton) and x.maximumHeight()>1000: x.setMinimumHeight(40)
            inktools.addWidget(x)
        self.inkbox=QFrame(); self.inkbox.setObjectName("formCard"); self.inkv=QVBoxLayout(self.inkbox); self.inkv.setContentsMargins(16,12,16,14); self.inkv.setSpacing(10); self.inkv.addLayout(inkhead); self.inkv.addLayout(inktools); self.ink.setMinimumHeight(235); self.ink.setStyleSheet("background:white;border:1px dashed #b8c7d4;border-radius:8px"); self.inkv.addWidget(self.ink)
        # Sofort-Texterkennung: nach kurzer Schreibpause wird die Handschrift automatisch in Text umgewandelt.
        self._ocr_busy=False; self._ocr_timer=QTimer(self); self._ocr_timer.setSingleShot(True); self._ocr_timer.timeout.connect(lambda: self.ink_ocr_start(manual=False))
        self.ink.stroke_started.connect(self._ocr_timer.stop); self.ink.stroke_finished.connect(self.ink_schedule_ocr)
        ocrrow=QHBoxLayout(); self.ink_auto=QCheckBox("Sofort in Text umwandeln"); self.ink_auto.setChecked(get_setting("ink_auto_ocr","1")=="1"); self.ink_auto.toggled.connect(lambda on: set_setting("ink_auto_ocr","1" if on else "0"))
        self.ink_direct=QCheckBox("Direkt in Therapienotiz schreiben"); self.ink_direct.setChecked(get_setting("ink_direct_notes","1")=="1"); self.ink_direct.toggled.connect(lambda on: set_setting("ink_direct_notes","1" if on else "0"))
        self.ink_lang=QComboBox(); self.ink_lang.addItems(list(OCR_LANGS.keys())); self.ink_lang.setCurrentText(get_setting("ocr_lang","Deutsch")); self.ink_lang.setToolTip("Sprache der Handschrift-Erkennung"); self.ink_lang.currentTextChanged.connect(lambda t: set_setting("ocr_lang",t))
        self.ink_status=QLabel(""); ocrrow.addWidget(self.ink_auto); ocrrow.addWidget(self.ink_direct); ocrrow.addWidget(QLabel("Sprache:")); ocrrow.addWidget(self.ink_lang); ocrrow.addWidget(self.ink_status,1); self.inkv.addLayout(ocrrow)
        self.ink_live=QTextEdit(); self.ink_live.setPlaceholderText("Erkannter Text erscheint hier …"); self.ink_live.setFixedHeight(80); self.inkv.addWidget(self.ink_live)
        takebtn=QPushButton("↳ Erkannten Text in Therapienotiz übernehmen"); takebtn.clicked.connect(lambda: self.ink_commit_text(self.ink_live.toPlainText().strip(),clear_ink=False)); self.inkv.addWidget(takebtn)
        v.addWidget(self.inkbox,1)
        # Speichern auch am Seitenende, damit man nach dem Schreiben nicht nach oben scrollen muss.
        h=QHBoxLayout(); h.addStretch(); endsave=QPushButton("💾 Sitzung speichern"); endsave.setMinimumHeight(42); endsave.setMinimumWidth(220); endsave.setStyleSheet("font-weight:700"); endsave.clicked.connect(self.save_session); h.addWidget(endsave); v.addLayout(h)
        body.setMinimumWidth(0); body.setMaximumWidth(1500); scroll.setWidget(body); outer.addWidget(scroll); return page

    def client_master_tab(self,cc,name_label=None,contact_label=None):
        """Reiter „Stammdaten & Kostenträger“ in der Klientenakte: Übersicht aller Felder + Bearbeiten."""
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(0,8,0,0)
        view=QLabel(); view.setWordWrap(True); view.setTextFormat(Qt.RichText); view.setAlignment(Qt.AlignTop|Qt.AlignLeft)
        sc=QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(view); v.addWidget(sc,1)
        import html as _html
        def render():
            parts=[]
            for group,items in CLIENT_FIELDS:
                rows="".join(f"<tr><td style='color:#6b7a72;padding:3px 18px 3px 0;vertical-align:top'>{_html.escape(label.rstrip(' *'))}</td>"
                             f"<td style='padding:3px 0'>{_html.escape(str(cc.get(key,'') or ('Selbstzahler' if key=='payer' else '–'))).replace(chr(10),'<br>')}</td></tr>" for key,label,_ in items)
                parts.append(f"<h3 style='color:#2c3b33;margin:12px 0 4px 0'>{_html.escape(group)}</h3><table>{rows}</table>")
            view.setText("".join(parts))
        render()
        row=QHBoxLayout(); row.addStretch(); edit=QPushButton("✎ Stammdaten bearbeiten"); edit.setMinimumHeight(38); row.addWidget(edit); v.addLayout(row)
        def do_edit():
            if self.edit_client_record(cc):
                render()
                if name_label is not None: name_label.setText(f"{cc.get('first','')} {cc.get('last','')}")
                if contact_label is not None: contact_label.setText(" · ".join(x for x in [cc.get("phone",""),cc.get("email",""),cc.get("address",""),cc.get("payer","")] if x))
        edit.clicked.connect(do_edit)
        return page

    def client_documents_tab(self,cc,dlg=None):
        """Reiter „Dokumente“: erstellte Formulare und importierte Dateien (Arztbriefe, Befunde, Scans …)."""
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(0,8,0,0)
        hint=QLabel("Importierte Dateien werden verschlüsselt in der Klientenakte gespeichert (🔒) und nur zum Ansehen kurz entschlüsselt. Das Original auf dem PC bleibt unverändert – löschen Sie es danach bei Bedarf selbst."); hint.setWordWrap(True); hint.setObjectName("pageSub"); v.addWidget(hint)
        table=QTableWidget(0,3); table.setHorizontalHeaderLabels(["Datum","Dokument",""]); table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents); table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectRows); table.setEditTriggers(QTableWidget.NoEditTriggers); table.verticalHeader().setVisible(False); v.addWidget(table,1)
        def refresh():
            table.setRowCount(0)
            for d in client_documents(cc):
                r=table.rowCount(); table.insertRow(r)
                stamp=datetime.fromtimestamp(d["mtime"]).strftime("%d.%m.%Y")
                name=re.sub(r"^\d{4}-\d{2}-\d{2}(_\d{6})?_","",d["name"]).replace("_"," ")
                for j,val in enumerate((stamp,name,"🔒 importiert" if d["encrypted"] else "erstellt")):
                    it=QTableWidgetItem(val); it.setData(Qt.UserRole,d["path"]); table.setItem(r,j,it)
        def add():
            if not self.require_edit(): return
            files,_=QFileDialog.getOpenFileNames(self,"Dokumente zur Klientenakte hinzufügen",str(Path.home()),"Dokumente (*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.docx *.doc *.odt *.txt);;Alle Dateien (*.*)")
            if not files: return
            cat,ok=QInputDialog.getItem(self,"Art des Dokuments","Welche Art von Dokument ist das?",DOC_CATEGORIES,0,False)
            if not ok: return
            done=0
            for f in files:
                try: import_client_document(cc,f,cat); done+=1
                except Exception as e: QMessageBox.warning(self,"Dokument",f"{Path(f).name} konnte nicht übernommen werden:\n{e}")
            audit("CLIENT_DOC_IMPORTED",f"{done} Dokument(e) ({cat}): {cc.get('last','')}, {cc.get('first','')}",self.current_user.get("username","")); refresh()
        def open_selected():
            r=table.currentRow()
            if r<0: return QMessageBox.information(self,"Dokument","Bitte zuerst ein Dokument auswählen.")
            p=table.item(r,0).data(Qt.UserRole)
            try: open_client_document(p); audit("CLIENT_DOC_OPENED",Path(p).name,self.current_user.get("username",""))
            except Exception as e: QMessageBox.warning(self,"Dokument","Das Dokument konnte nicht geöffnet werden:\n"+str(e))
        def new_form():
            if dlg is not None: dlg.accept()
            self.nav.setCurrentRow(12); QApplication.processEvents()
            same=lambda d: isinstance(d,dict) and all(d.get(x,"")==cc.get(x,"") for x in ("last","first","dob"))
            i=next((k for k in range(self.doc_client.count()) if same(self.doc_client.itemData(k))),-1)
            if i>=0: self.doc_client.setCurrentIndex(i)
        row=QHBoxLayout()
        for text,fn in (("＋ Dokument hinzufügen (Scan, Arztbrief …)",add),("Öffnen",open_selected),("✉ Neues Formular / Brief",new_form),("📂 Ordner öffnen",lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(client_dir(cc)/"Dokumente"))))):
            b=QPushButton(text); b.setMinimumHeight(38); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row); table.cellDoubleClicked.connect(lambda *_: open_selected()); refresh()
        return page

    def waitlist_ui(self):
        """Warteliste: Interessenten erfassen, bevor eine Klientenakte angelegt wird."""
        DB.setdefault("waitlist",[])
        page=QWidget(); v=QVBoxLayout(page); v.setContentsMargins(18,14,18,14); v.setSpacing(10)
        title=QLabel("Warteliste"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Interessenten mit Anliegen, Erreichbarkeit und Dringlichkeit erfassen. Bei freiem Platz mit einem Klick als Klient übernehmen."); sub.setObjectName("pageSub"); sub.setWordWrap(True); v.addWidget(sub)
        tools=QHBoxLayout(); flt=QComboBox(); flt.addItems(["Offene Einträge","Alle Einträge","Übernommen / abgesagt"]); search=QLineEdit(); search.setPlaceholderText("Suchen …"); search.setClearButtonEnabled(True)
        tools.addWidget(flt); tools.addWidget(search,1); v.addLayout(tools)
        split=QSplitter(); split.setChildrenCollapsible(False); self.responsive_split(split,900)
        table=QTableWidget(0,6); table.setHorizontalHeaderLabels(["Eingang","Name","Dringlichkeit","Erreichbar","Anliegen","Status"])
        for col,mode in enumerate((QHeaderView.ResizeToContents,QHeaderView.Stretch,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents,QHeaderView.Stretch,QHeaderView.ResizeToContents)): table.horizontalHeader().setSectionResizeMode(col,mode)
        table.setSelectionBehavior(QTableWidget.SelectRows); table.setSelectionMode(QTableWidget.SingleSelection); table.setEditTriggers(QTableWidget.NoEditTriggers); table.verticalHeader().setVisible(False); table.setMinimumWidth(420)
        card=QFrame(); card.setObjectName("formCard"); cv=QVBoxLayout(card); cv.setContentsMargins(14,10,14,12)
        ft=QLabel("Eintrag"); ft.setObjectName("sectionTitle"); cv.addWidget(ft)
        form=QFormLayout(); form.setVerticalSpacing(8)
        f_name=QLineEdit(); f_name.setPlaceholderText("Vor- und Nachname"); f_phone=QLineEdit(); f_email=QLineEdit()
        f_urg=QComboBox(); f_urg.addItems(["normal","hoch","dringend"]); f_payer=QComboBox(); f_payer.addItems(PAYERS); f_payer.setEditable(True)
        f_status=QComboBox(); f_status.addItems(["wartend","kontaktiert","Erstgespräch vereinbart","übernommen","abgesagt"])
        days=QWidget(); dl=FlowLayout(days,hspacing=6,vspacing=4); dl.setContentsMargins(0,0,0,0); day_boxes={}
        for d in ("Mo","Di","Mi","Do","Fr","Sa","vormittags","nachmittags","abends","online"):
            cb=QCheckBox(d); day_boxes[d]=cb; dl.addWidget(cb)
        f_concern=QTextEdit(); f_concern.setAcceptRichText(False); f_concern.setFixedHeight(80); f_concern.setPlaceholderText("Anliegen in Stichworten")
        f_note=QTextEdit(); f_note.setAcceptRichText(False); f_note.setFixedHeight(60); f_note.setPlaceholderText("Notiz, z. B. Rückruf vereinbart am …")
        for lab,w_ in (("Name *",f_name),("Telefon",f_phone),("E-Mail",f_email),("Dringlichkeit",f_urg),("Kostenträger",f_payer),("Erreichbar",days),("Anliegen",f_concern),("Notiz",f_note),("Status",f_status)): form.addRow(lab,w_)
        cv.addLayout(form)
        btns=QWidget(); bl=FlowLayout(btns,hspacing=8,vspacing=8); bl.setContentsMargins(0,4,0,0)
        b_new=QPushButton("＋ Neuer Eintrag"); b_save=QPushButton("💾 Speichern"); b_take=QPushButton("♙ Als Klient übernehmen"); b_del=QPushButton("Löschen")
        b_del.setStyleSheet("background:white;color:#b5534b;border:1px solid #d9a9a4")
        for b in (b_new,b_save,b_take,b_del): b.setMinimumHeight(36); bl.addWidget(b)
        cv.addWidget(btns); cv.addStretch()
        split.addWidget(table); split.addWidget(card); split.setStretchFactor(0,3); split.setStretchFactor(1,2); v.addWidget(split,1)
        state={"id":None}
        URG={"dringend":0,"hoch":1,"normal":2}
        def entries():
            q=search.text().strip().lower(); mode=flt.currentIndex(); out=[]
            for e in DB["waitlist"]:
                done=e.get("status") in ("übernommen","abgesagt")
                if mode==0 and done or mode==2 and not done: continue
                if q and q not in " ".join(str(x) for x in e.values()).lower(): continue
                out.append(e)
            return sorted(out,key=lambda e:(URG.get(e.get("urgency","normal"),3),e.get("created","")))
        def refresh():
            table.setRowCount(0)
            for e in entries():
                r=table.rowCount(); table.insertRow(r)
                vals=[_de_date(e.get("created","")[:10]),e.get("name",""),e.get("urgency",""),", ".join(e.get("availability",[])),e.get("concern","").replace("\n"," ")[:80],e.get("status","")]
                for j,val in enumerate(vals):
                    it=QTableWidgetItem(val); it.setData(Qt.UserRole,e.get("id"))
                    if e.get("urgency")=="dringend": it.setForeground(QColor("#b5534b"))
                    table.setItem(r,j,it)
            self.nav_badge(13,sum(1 for e in DB["waitlist"] if e.get("status") not in ("übernommen","abgesagt")))
        self.refresh_waitlist=refresh
        def load(e):
            state["id"]=e.get("id") if e else None
            f_name.setText(e.get("name","") if e else ""); f_phone.setText(e.get("phone","") if e else ""); f_email.setText(e.get("email","") if e else "")
            f_urg.setCurrentText(e.get("urgency","normal") if e else "normal"); f_payer.setCurrentText(e.get("payer","Selbstzahler") if e else "Selbstzahler")
            f_status.setCurrentText(e.get("status","wartend") if e else "wartend")
            av=set(e.get("availability",[])) if e else set()
            for d,cb in day_boxes.items(): cb.setChecked(d in av)
            f_concern.setPlainText(e.get("concern","") if e else ""); f_note.setPlainText(e.get("note","") if e else "")
            ft.setText("Eintrag bearbeiten" if e else "Neuer Eintrag")
        def current():
            return next((e for e in DB["waitlist"] if e.get("id")==state["id"]),None)
        def on_select():
            r=table.currentRow()
            if r<0: return
            eid=table.item(r,0).data(Qt.UserRole); load(next((e for e in DB["waitlist"] if e.get("id")==eid),None))
        def save():
            if not self.require_edit(): return None
            if not f_name.text().strip(): QMessageBox.warning(self,"Warteliste","Bitte einen Namen eingeben."); return None
            e=current()
            if e is None:
                e={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"created":datetime.now().isoformat(timespec="seconds")}; DB["waitlist"].append(e); state["id"]=e["id"]
            e.update({"name":f_name.text().strip(),"phone":f_phone.text().strip(),"email":f_email.text().strip(),"urgency":f_urg.currentText(),"payer":f_payer.currentText().strip(),
                      "availability":[d for d,cb in day_boxes.items() if cb.isChecked()],"concern":f_concern.toPlainText().strip(),"note":f_note.toPlainText().strip(),"status":f_status.currentText(),"updated":datetime.now().isoformat(timespec="seconds")})
            save_data(); audit("WAITLIST_SAVED","Wartelisteneintrag gespeichert",self.current_user.get("username","")); refresh(); ft.setText("Eintrag bearbeiten"); return e
        def take_over():
            e=save()
            if not e: return
            parts=e["name"].split(); first=" ".join(parts[:-1]) if len(parts)>1 else ""; last=parts[-1] if parts else ""
            cc=self.open_new_client_dialog({"first":first,"last":last,"phone":e.get("phone",""),"email":e.get("email",""),"payer":e.get("payer","")})
            if cc:
                e["status"]="übernommen"; e["note"]=(e.get("note","")+"\n" if e.get("note") else "")+f"Als Klient übernommen am {datetime.now().strftime('%d.%m.%Y')}."; save_data(); load(e); refresh()
                QMessageBox.information(self,"Warteliste",f"{cc['first']} {cc['last']} wurde als Klient angelegt.")
        def delete():
            if not self.require_edit(): return
            e=current()
            if not e: return
            if QMessageBox.question(self,"Eintrag löschen",f"Wartelisteneintrag „{e.get('name','')}“ endgültig löschen?\n\nDas kann nicht rückgängig gemacht werden.",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes: return
            DB["waitlist"].remove(e); save_data(); audit("WAITLIST_DELETED","Wartelisteneintrag gelöscht",self.current_user.get("username","")); load(None); refresh()
        table.itemSelectionChanged.connect(on_select); b_new.clicked.connect(lambda: (table.clearSelection(),load(None),f_name.setFocus())); b_save.clicked.connect(save); b_take.clicked.connect(take_over); b_del.clicked.connect(delete)
        flt.currentIndexChanged.connect(lambda *_: refresh()); search.textChanged.connect(lambda *_: refresh())
        load(None); refresh()
        return page

    def nav_badge(self,page,count):
        """Zahl hinter einem Menüpunkt anzeigen, z. B. offene Wartelisteneinträge."""
        if not hasattr(self,"nav"): return
        row=self.nav._row_of_page.get(page)
        if row is None: return
        for r,icon,label in self.nav.entries:
            if r==row:
                base=label.split("  (")[0]; new=base+(f"  ({count})" if count else "")
                self.nav.entries[self.nav.entries.index((r,icon,label))]=(r,icon,new)
                it=self.nav.item(row)
                if it.textAlignment()&Qt.AlignHCenter: it.setToolTip(new)
                else: it.setText(f"{icon}   {new}")
                break

    def open_new_client_dialog(self,prefill=None):
        """Neuen Klienten mit allen Stammdaten anlegen. Liefert den neuen Datensatz oder None."""
        if not self.require_edit(): return None
        while True:
            vals=client_form_dialog(self,"Neuen Klienten anlegen",prefill)
            if vals is None: return None
            exists=next((x for x in DB["clients"] if x.get("last","").lower()==vals["last"].lower() and x.get("first","").lower()==vals["first"].lower() and x.get("dob","")==vals["dob"]),None)
            if not exists: break
            QMessageBox.warning(self,"Klient","Dieser Klient ist bereits vorhanden."); prefill=vals
        cc=dict(vals); cc["created_at"]=datetime.now().isoformat(timespec="seconds"); DB["clients"].append(cc); save_data()
        if hasattr(self,"client_pick"): self.client_pick.addItem(f"{cc['last']}, {cc['first']}",cc); self.client_pick.setCurrentIndex(self.client_pick.count()-1)
        audit("CLIENT_CREATED","Klient angelegt",self.current_user.get("username","") if self.current_user else "")
        return cc

    def edit_client_record(self,cc):
        """Stammdaten bearbeiten (alle Felder). Bei Namensänderung werden Sitzungen und Rechnungen mitgeführt. True = gespeichert."""
        if not self.require_edit(): return False
        while True:
            vals=client_form_dialog(self,f"Klientendaten bearbeiten – {cc.get('first','')} {cc.get('last','')}",cc)
            if vals is None: return False
            new_last,new_first=vals["last"],vals["first"]; old_last,old_first=cc.get("last",""),cc.get("first","")
            name_changed=(old_last!=new_last or old_first!=new_first)
            if name_changed:
                duplicate=next((x for x in DB["clients"] if x is not cc and x.get("last","").lower()==new_last.lower() and x.get("first","").lower()==new_first.lower() and x.get("dob","")==vals["dob"]),None)
                if duplicate: QMessageBox.warning(self,"Klient","Ein Klient mit diesem Namen und Geburtsdatum existiert bereits."); continue
                if QMessageBox.question(self,"Name ändern",f"Name von {old_first} {old_last} in {new_first} {new_last} ändern?\n\nZugehörige Sitzungen und Rechnungen werden mit aktualisiert.")!=QMessageBox.Yes: continue
                for sess in DB["sessions"]:
                    if sess.get("last")==old_last and sess.get("first")==old_first: sess["last"]=new_last; sess["first"]=new_first
                old_keys={f"{old_last}, {old_first}",f"{old_first} {old_last}"}
                for inv in DB["invoices"]:
                    if str(inv.get("client","")).strip() in old_keys: inv["client"]=f"{new_last}, {new_first}"
            break
        cc.update(vals); cc["updated_at"]=datetime.now().isoformat(timespec="seconds"); save_data()
        audit("CLIENT_UPDATED",("Klientenname und Verknüpfungen aktualisiert" if name_changed else "Klientenstammdaten bearbeitet"),self.current_user.get("username","") if self.current_user else "")
        return True

    def edit_session_client(self):
        cc=resolve_client(self.client_pick.currentData()) if hasattr(self,"client_pick") else None
        if not isinstance(cc,dict): return QMessageBox.information(self,"Klient","Bitte zuerst einen Klienten auswählen.")
        if self.edit_client_record(cc):
            self.client_pick.setItemData(self.client_pick.currentIndex(),cc)
            self.s_last.setText(cc.get("last","")); self.s_first.setText(cc.get("first","")); self.s_dob.setText(cc.get("dob","")); self.s_phone.setText(cc.get("phone","")); self.s_email.setText(cc.get("email",""))
            idx=self.client_pick.currentIndex(); self.client_pick.setItemText(idx,f'{cc.get("last","")}, {cc.get("first","")}')

    def save_ink_note(self):
        last=self.s_last.text().strip() if hasattr(self,"s_last") else ""
        first=self.s_first.text().strip() if hasattr(self,"s_first") else ""
        if not last or not first: return QMessageBox.warning(self,"Freihand-Notiz","Bitte zuerst einen Klienten auswählen.")
        folder=client_folder(last,first)/"Sitzungen"; folder.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); tmp=folder/f"Freihand_{stamp}.png"
        now_=datetime.now(); if_stamp=f"{last}, {first}  –  {now_.strftime('%d.%m.%Y')}, {now_.strftime('%H:%M')} Uhr"
        if not self.ink.save_png(tmp,if_stamp): return QMessageBox.warning(self,"Freihand-Notiz","Die Notiz konnte nicht gespeichert werden.")
        enc=encrypt_file(tmp); self.current_ink_file=enc
        try:
            sd=self.ink.stroke_data()
            if sd: Path(enc+".strokes.enc").write_text(encrypt_text(json.dumps(sd)),encoding="utf-8")
        except Exception: pass
        audit("INK_NOTE_SAVED",f"Freihand-Notiz gespeichert: {last}, {first}",self.current_user.get("username","") if self.current_user else "")
        QMessageBox.information(self,"Freihand-Notiz","Die Freihand-Notiz wurde verschlüsselt beim Klienten gespeichert.\n\n"+str(Path(enc).name))

    def ocr_system_test(self):
        """Prüft lokal, ob Windows OCR und passende Sprachpakete verfügbar sind."""
        ps=r'''$ErrorActionPreference="Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$langs=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
if($langs.Count -eq 0){throw 'Keine Windows-OCR-Sprache installiert.'}
Write-Output ('Windows OCR: bereit')
Write-Output ('Sprachen: '+(($langs | ForEach-Object {$_.LanguageTag}) -join ', '))
$de=$langs | Where-Object {$_.LanguageTag -match '^de(-|$)'} | Select-Object -First 1
$tr=$langs | Where-Object {$_.LanguageTag -match '^tr(-|$)'} | Select-Object -First 1
if($null -ne $de){Write-Output ('Deutsch: '+$de.LanguageTag)}else{Write-Output 'Deutsch: NICHT installiert'}
if($null -ne $tr){Write-Output ('Türkisch: '+$tr.LanguageTag)}else{Write-Output 'Türkisch: NICHT installiert'}
'''
        try:
            run=subprocess.run(["powershell.exe","-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-Command",ps],
                               capture_output=True,text=True,encoding="utf-8-sig",errors="replace",timeout=20,
                               creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            out=(run.stdout or "").strip(); err=(run.stderr or "").strip()
            if run.returncode:
                detail=(err or out or "Windows OCR konnte nicht initialisiert werden.")[:1500]
                audit("INK_OCR_SYSTEMTEST_ERROR",detail,self.current_user.get("username","") if self.current_user else "")
                return QMessageBox.warning(self,"OCR-Systemtest","OCR ist nicht einsatzbereit.\n\n"+detail)
            audit("INK_OCR_SYSTEMTEST_OK",out[:1500],self.current_user.get("username","") if self.current_user else "")
            QMessageBox.information(self,"OCR-Systemtest",out+"\n\nFür die beste Erkennung Deutsch und Türkisch als Windows-Sprachfunktionen installieren.")
        except Exception as e:
            audit("INK_OCR_SYSTEMTEST_EXCEPTION",str(e)[:1200],self.current_user.get("username","") if self.current_user else "")
            QMessageBox.warning(self,"OCR-Systemtest","OCR-Systemtest fehlgeschlagen:\n\n"+str(e)[:1200])

    def ocr_end_to_end_test(self):
        """Testet denselben OCR-Pfad mit einem lokal erzeugten, klaren Testbild."""
        tmp=Path(tempfile.gettempdir())/f"PraxisPro_OCR_Selbsttest_{os.getpid()}_{int(time.time()*1000)}.png"
        img=QImage(1400,320,QImage.Format_ARGB32); img.fill(Qt.white)
        p=QPainter(img); p.setPen(Qt.black); font=QFont("Arial",48); font.setBold(True); p.setFont(font)
        p.drawText(img.rect().adjusted(40,20,-40,-20),Qt.AlignCenter,"PraxisPro Test 123"); p.end()
        if not img.save(str(tmp),"PNG"):
            return QMessageBox.warning(self,"OCR-Selbsttest","Testbild konnte nicht erzeugt werden.")
        # Derselbe Erkennungscode wie bei der echten Handschrifterkennung (OCR_PS_COMMON), damit der Test aussagekräftig ist.
        ps=OCR_PS_COMMON+r'''
$lines=Recognize $env:PRAXISPRO_OCR_PATH 'de-DE'
$langs=@([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
Write-Output ('__LANG__=de-DE')
Write-Output ('__LANGS__='+((@($langs | ForEach-Object {$_.LanguageTag})) -join ', '))
try{ $null=[Windows.UI.Input.Inking.InkRecognizerContainer,Windows.UI.Input.Inking,ContentType=WindowsRuntime]; $rcx=New-Object Windows.UI.Input.Inking.InkRecognizerContainer; Write-Output ('__INK__='+((@($rcx.GetRecognizers() | ForEach-Object {$_.Name})) -join ', ')) }catch{ Write-Output ('__INK__=FEHLER: '+$_.Exception.Message) }
Write-Output ($lines -join "`n")
'''
        try:
            env=os.environ.copy(); env["PRAXISPRO_OCR_PATH"]=str(tmp.resolve())
            psfile=tmp.with_suffix(".ps1"); psfile.write_text(ps,encoding="utf-8-sig")
            run=subprocess.run(["powershell.exe","-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(psfile)],
                env=env,capture_output=True,text=True,encoding="utf-8-sig",errors="replace",timeout=30,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            out=(run.stdout or "").strip(); err=(run.stderr or "").strip()
            if run.returncode:
                detail=(err or out or "Unbekannter OCR-Fehler")[:1500]
                audit("INK_OCR_E2E_ERROR",detail,self.current_user.get("username","") if self.current_user else "")
                return QMessageBox.warning(self,"OCR-Selbsttest","Windows OCR ist vorhanden, aber die Texterkennung ist fehlgeschlagen.\n\n"+detail)
            info={k:"" for k in ("__LANG__=","__LANGS__=","__INK__=")}
            for x in out.splitlines():
                for k in info:
                    if x.startswith(k): info[k]=x[len(k):].strip()
            recognized="\n".join(x for x in out.splitlines() if not x.startswith(("__LANG__=","__LANGS__=","__INK__="))).strip()
            diag="\n\nDiagnose:\n• Texterkennung (OCR) Sprachen: "+(info["__LANGS__="] or "keine")+"\n• Handschrift-Erkenner: "+(info["__INK__="] or "KEINER installiert")+("\n\n→ Für Schreibschrift fehlt das Handschrift-Paket: Einstellungen → Zeit & Sprache → Sprache & Region → Deutsch → Sprachoptionen → Handschrift hinzufügen. Danach PraxisPro neu starten." if not info["__INK__="] or info["__INK__="].startswith("FEHLER") else "")
            ok=("praxispro" in recognized.lower() and "123" in recognized)
            audit("INK_OCR_E2E_OK" if ok else "INK_OCR_E2E_BAD",recognized[:1000],self.current_user.get("username","") if self.current_user else "")
            if ok:
                QMessageBox.information(self,"OCR-Selbsttest","OCR funktioniert technisch.\n\nErkannt: "+recognized+"\n\nWenn Handschrift trotzdem nicht erkannt wird, liegt es an der Handschrifterkennung – nicht an der OCR-Installation."+diag)
            else:
                QMessageBox.warning(self,"OCR-Selbsttest","OCR wurde ausgeführt, hat das klare Testbild aber nicht zuverlässig erkannt.\n\nErkannt: "+(recognized or "(leer)")+diag)
        except Exception as e:
            audit("INK_OCR_E2E_EXCEPTION",str(e)[:1200],self.current_user.get("username","") if self.current_user else "")
            QMessageBox.warning(self,"OCR-Selbsttest","OCR-Selbsttest fehlgeschlagen:\n\n"+str(e)[:1200])
        finally:
            try: tmp.unlink(missing_ok=True); tmp.with_suffix(".ps1").unlink(missing_ok=True)
            except Exception: pass

    def ink_schedule_ocr(self):
        """Nach kurzer Schreibpause automatisch erkennen (wenn 'Sofort in Text umwandeln' aktiv ist)."""
        if hasattr(self,"ink_auto") and self.ink_auto.isChecked(): self._ocr_timer.start(900)

    def ink_to_text(self,checked=False):
        """Button 'Handschrift → Text': sofort erkennen und zur Kontrolle anzeigen."""
        self._ocr_timer.stop(); self.ink_ocr_start(manual=True)

    def ink_ocr_start(self,manual=False):
        if not hasattr(self,"ink"): return
        if getattr(self,"_ocr_busy",False):
            if not manual: self._ocr_timer.start(800)
            return
        if prepare_ink_for_ocr(self.ink.image) is None:
            if manual: QMessageBox.warning(self,"Handschrift erkennen","Keine Handschrift vorhanden.")
            return
        self._ocr_busy=True; self.ink_status.setText("⏳ Handschrift wird erkannt …")
        w=OcrWorker(self.ink.image.copy(),self.ink.rev,manual,OCR_LANGS.get(self.ink_lang.currentText() if hasattr(self,"ink_lang") else "Deutsch","de-DE"),self.ink.stroke_data()); w.done.connect(self.ink_ocr_done); w.finished.connect(w.deleteLater); self._ocr_worker=w; w.start()

    def ink_ocr_done(self,text,err,rev,manual):
        self._ocr_busy=False
        user=self.current_user.get("username","") if self.current_user else ""
        if err in ("LEER","KEIN_TEXT"):
            self.ink_status.setText("Keine Schrift erkannt – bitte deutlicher/größer schreiben." if err=="KEIN_TEXT" else "")
            if manual and err=="KEIN_TEXT": QMessageBox.information(self,"Handschrift erkennen","Es wurde keine Schrift erkannt. Bitte etwas größer und deutlicher schreiben (Stärke 4–6 px).\n\nTechnischer Hinweis: "+(OCR_LAST_INK_NOTE or "Handschrift-Erkenner nicht verwendet: Das Bild stammt aus einer wiederhergestellten/gespeicherten Notiz und enthält keine Strichdaten. Bitte „Zeichenfläche löschen“ und das Wort neu schreiben.")+"\n\nTipp: Mit „OCR-Test“ sehen Sie, ob das Handschrift-Paket installiert ist.")
            return
        if err:
            audit("INK_OCR_ERROR",err[:900],user); self.ink_status.setText("⚠ Erkennung nicht möglich")
            if manual or not getattr(self,"_ocr_error_shown",False):
                self._ocr_error_shown=True; QMessageBox.warning(self,"Handschrift erkennen","Die Handschrift konnte nicht erkannt werden.\n\n"+err)
            return
        if rev!=self.ink.rev:
            # Es wurde inzwischen weitergeschrieben: Ergebnis verwerfen und neu erkennen.
            self.ink_status.setText("⏳ Handschrift wird erkannt …"); self._ocr_timer.start(400); return
        self.ink_live.setPlainText(text)
        if manual:
            dlg=QDialog(self); dlg.setWindowTitle("Handschrift → Text prüfen"); dlg.resize(720,500); v=QVBoxLayout(dlg)
            v.addWidget(QLabel("Erkannten Text prüfen und bei Bedarf korrigieren:"))
            edit=QTextEdit(); edit.setPlainText(text); v.addWidget(edit,1)
            buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.button(QDialogButtonBox.Save).setText("In Therapienotiz übernehmen"); v.addWidget(buttons)
            def accept_text():
                self.ink_commit_text(edit.toPlainText().strip(),clear_ink=False); dlg.accept()
            buttons.accepted.connect(accept_text); buttons.rejected.connect(dlg.reject); dlg.exec()
        elif hasattr(self,"ink_direct") and self.ink_direct.isChecked():
            self.ink_commit_text(text.strip())
        else:
            self.ink_status.setText("✓ Erkannt – bitte prüfen und übernehmen")

    def ink_commit_text(self,cleaned,clear_ink=False):
        """Erkannten Text in die Therapienotiz übernehmen. Die Handschrift bleibt IMMER erhalten.
        Wird dieselbe Handschrift erneut erkannt (weitergeschrieben), ersetzt der neue Text den zuvor
        übernommenen Block, statt doppelt angehängt zu werden."""
        if not cleaned: return
        if not getattr(self,"_last_ink_stamp",""): self._last_ink_stamp=datetime.now().strftime("%d.%m.%Y %H:%M")
        cleaned=f"[{self._last_ink_stamp} Uhr] "+cleaned
        prev=getattr(self,"_last_ink_text","")
        existing=self.notes.toPlainText().rstrip()
        if prev and existing.endswith(prev): existing=existing[:-len(prev)].rstrip()
        self.notes.setPlainText((existing+"\n\n" if existing else "")+cleaned)
        ocr_prev=self.current_ocr_text.rstrip()
        if prev and ocr_prev.endswith(prev): ocr_prev=ocr_prev[:-len(prev)].rstrip()
        self.current_ocr_text=(ocr_prev+"\n" if ocr_prev else "")+cleaned
        self._last_ink_text=cleaned
        self.ink_status.setText("✓ In Therapienotiz übernommen – Handschrift bleibt erhalten")
        self.ink_live.clear()

    def make_pen_tools(self,eraser_cb=None):
        """Stiftstärke (Regler + Zahl) und Farbauswahl für den Notizblock. Gibt Widgets zurück."""
        wl=QLabel("Stärke"); sl=QSlider(Qt.Horizontal); sl.setRange(1,24); sl.setValue(self.ink.pen_width); sl.setMinimumWidth(110); sl.setMaximumWidth(180)
        sp=QSpinBox(); sp.setRange(1,24); sp.setValue(self.ink.pen_width); sp.setSuffix(" px"); sp.setMinimumWidth(100)
        sl.valueChanged.connect(sp.setValue); sp.valueChanged.connect(sl.setValue); sp.valueChanged.connect(self.ink.set_width)
        widgets=[wl,sl,sp,QLabel("Farbe")]
        def pick(color,apply=True):
            if apply:
                self.ink.set_color(color)
                if eraser_cb is not None and eraser_cb.isChecked(): eraser_cb.setChecked(False)
            for b,c in swatches: b.setStyleSheet(f"background:{c};border:3px solid {'#e0b030' if QColor(c)==self.ink.pen_color else '#9fb3c4'};border-radius:15px;")
        swatches=[]
        for c,name in (("#000000","Schwarz"),("#1f4fd8","Blau"),("#c62828","Rot"),("#2e7d32","Grün"),("#ef6c00","Orange"),("#6a1b9a","Violett")):
            b=QPushButton(""); b.setFixedSize(30,30); b.setToolTip(name); b.setCursor(Qt.PointingHandCursor); b.clicked.connect(lambda _=False,col=c: pick(col)); swatches.append((b,c)); widgets.append(b)
        more=QPushButton("🎨"); more.setToolTip("Eigene Farbe wählen …"); more.setFixedSize(34,30)
        def custom():
            col=QColorDialog.getColor(self.ink.pen_color,self,"Stiftfarbe wählen")
            if col.isValid(): pick(col.name())
        more.clicked.connect(custom); widgets.append(more); pick(self.ink.pen_color.name(),apply=False)
        return widgets

    def open_ink_fullscreen(self):
        dlg=QDialog(self); dlg.setWindowTitle("Freihand-Notizbuch"); dlg.resize(1280,800); dlg.setMinimumSize(460,420); dlg.setWindowFlag(Qt.WindowMaximizeButtonHint,True)
        v=QVBoxLayout(dlg); bar=QHBoxLayout(); title=QLabel("Handschrift / Stift"); title.setStyleSheet("font-size:22px;font-weight:700"); bar.addWidget(title); bar.addStretch(); clock=QLabel(QTime.currentTime().toString("HH:mm:ss")); clock.setStyleSheet("font-size:20px;font-weight:800"); bar.addWidget(clock); clocktimer=QTimer(dlg); clocktimer.timeout.connect(lambda: clock.setText(QTime.currentTime().toString("HH:mm:ss"))); clocktimer.start(1000)
        undo=QPushButton("↶ Rückgängig"); undo.clicked.connect(self.ink.undo); erase=QCheckBox("Radierer"); erase.setChecked(self.ink.eraser); erase.toggled.connect(self.ink.set_eraser)
        zoom=QSlider(Qt.Horizontal); zoom.setRange(60,180); zoom.setValue(100); zoom.setFixedWidth(170); zoomlabel=QLabel("100 %")
        save=QPushButton("💾 Notiz speichern"); save.clicked.connect(self.save_ink_note); ocr=QPushButton("⌨ Handschrift → Text"); ocr.clicked.connect(self.ink_to_text); ocrtest=QPushButton("OCR-Selbsttest"); ocrtest.clicked.connect(self.ocr_end_to_end_test); clear=QPushButton("Löschen"); clear.clicked.connect(self.ink.clear); full=QPushButton("⛶ Vollbild"); full.setCheckable(True); full.toggled.connect(lambda on: dlg.showFullScreen() if on else dlg.showNormal()); close=QPushButton("✓ Zur Sitzung"); close.clicked.connect(dlg.accept)
        clear.clicked.disconnect(); clear.clicked.connect(lambda: (self.ink.clear(),(setattr(self,'_last_ink_text',''),setattr(self,'_last_ink_stamp',''))))
        tools=FlowLayout(hspacing=8,vspacing=6); allbtns=[]
        for x in [undo,erase]+self.make_pen_tools(erase)+[QLabel("Ansicht"),zoom,zoomlabel,save,ocr,ocrtest,clear,full,close]:
            tools.addWidget(x)
            if isinstance(x,QPushButton) and x.maximumHeight()>1000: allbtns.append(x)
        bar.setContentsMargins(0,0,0,0); v.addLayout(bar); v.addLayout(tools)
        # Beim Drehen/Verkleinern des Fensters Schaltflächen in Höhe und Schrift mitskalieren (Touch-tauglich).
        class _Rescale(QObject):
            def eventFilter(_s,o,ev):
                if ev.type()==QEvent.Resize:
                    k=max(0.78,min(1.15,min(dlg.width()/1280,dlg.height()/720+0.25)))
                    for b in allbtns:
                        f=b.font(); f.setPointSizeF(max(9.0,12.5*k)); b.setFont(f); b.setMinimumHeight(int(max(34,46*k)))
                return False
        _rs=_Rescale(dlg); dlg.installEventFilter(_rs); dlg._rescale=_rs
        holder=QScrollArea(); holder.setWidgetResizable(True); holder.setAlignment(Qt.AlignCenter); self.ink.setMinimumSize(360,240); self.ink.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding); self.ink.setParent(holder); holder.setWidget(self.ink)
        basew,baseh=max(360,holder.viewport().width()),max(240,holder.viewport().height())
        def scale_ink(value):
            zoomlabel.setText(f"{value} %"); self.ink.setMinimumSize(max(360,int(basew*value/100)),max(240,int(baseh*value/100)))
        zoom.valueChanged.connect(scale_ink); scale_ink(100); v.addWidget(holder,1)
        dlg.exec()
        self.ink.setMinimumSize(0,235); self.ink.setMaximumSize(16777215,16777215); self.ink.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.ink.setParent(self.inkbox); self.inkv.addWidget(self.ink); self.ink.show(); self.inkbox.updateGeometry()

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
        # Therapieplan-Assistent: Vorschläge aus Verdachtsdiagnose und Paaranamnese.
        planbox=QFrame(); planbox.setObjectName("formCard"); pv=QVBoxLayout(planbox)
        ph=QHBoxLayout(); ptitle=QLabel("Therapieplan / Behandlungsvorschläge"); ptitle.setObjectName("sectionTitle"); ph.addWidget(ptitle); ph.addStretch()
        planbtn=QPushButton("✦ Therapieplan vorschlagen"); ph.addWidget(planbtn); pv.addLayout(ph)
        self.therapy_plan=QTextEdit(); self.therapy_plan.setPlaceholderText("Vorschläge werden aus Verdachtsdiagnose, Anliegen und Paarmodus abgeleitet und können frei bearbeitet werden."); self.therapy_plan.setMinimumHeight(150); pv.addWidget(self.therapy_plan)
        planhint=QLabel("Entscheidungshilfe, keine automatische Indikations- oder Diagnoseentscheidung. Verfahren, Kontraindikationen, Komorbidität, Medikation und Behandlungssetting klinisch prüfen."); planhint.setWordWrap(True); pv.addWidget(planhint); v.addWidget(planbox)

        def suggest_therapy_plan():
            d=(self.session_diag.text().strip().upper() if hasattr(self,"session_diag") else "")
            catalog=[
              (("F32","F33"),"Depressive Störung",
               ["Symptomreduktion und Stabilisierung","Aktivitätsniveau und Tagesstruktur aufbauen","Selbstwert und soziale Teilhabe stärken","Rückfallprophylaxe entwickeln"],
               ["KVT/VT: Verhaltensaktivierung, Aktivitätsaufbau, Problemlösetraining, kognitive Umstrukturierung, Arbeit an automatischen Gedanken und dysfunktionalen Grundannahmen.",
                "TP/psychodynamisch: Beziehungsmuster, Selbstwertregulation, Verlust-/Bindungsthemen, zentrale Konflikte und wiederkehrende interpersonelle Muster bearbeiten.",
                "Systemisch: Ressourcen und Ausnahmen aktivieren, Beziehungskontext und Wechselwirkungen einbeziehen, hilfreiche Unterstützungsstrukturen stärken."],
               ["Aktivitäts- und Stimmungstagebuch","kleine angenehme/sinnvolle Aktivität planen","automatische Gedanken und alternative Bewertungen notieren"]),
              (("F40","F41"),"Angst / Panik",
               ["Angstverständnis verbessern","Vermeidung und Sicherheitsverhalten reduzieren","Selbstwirksamkeit erhöhen","Rückfallprophylaxe"],
               ["KVT/VT: individuelles Angstmodell, Psychoedukation, Exposition/Verhaltensexperimente, Abbau von Sicherheitsverhalten, kognitive Neubewertung.",
                "TP/psychodynamisch: Funktion der Angst, Affektwahrnehmung, Beziehungsmuster und zugrunde liegende Konflikte explorieren.",
                "Systemisch: Kontextbedingungen, Interaktionsmuster, Ressourcen und mögliche symptomstabilisierende Rückkopplungen bearbeiten."],
               ["Angstprotokoll","vereinbarte graduierte Annäherungsübung","Sicherheitsverhalten beobachten und reduzieren"]),
              (("F42",),"Zwang",
               ["Zwangskreislauf verstehen","Rituale und Vermeidung reduzieren","Unsicherheitstoleranz erhöhen","Alltagsfunktion verbessern"],
               ["KVT/VT: funktionale Analyse, Exposition mit Reaktionsmanagement, Arbeit an Zwangsbewertungen, Rückfallprophylaxe.",
                "TP/psychodynamisch: Konflikte, Affekte, Kontrolle, Beziehungsmuster und Funktion der Symptomatik explorieren.",
                "Systemisch: familiäre/partnerschaftliche Anpassungen an Zwänge und Rückversicherung identifizieren und verändern."],
               ["Zwangsauslöser und Rituale protokollieren","vereinbarte ERP-Übung","Rückversicherung beobachten"]),
              (("F43.1",),"PTBS / Trauma",
               ["Sicherheit und Stabilität herstellen","Traumasymptome und Vermeidung reduzieren","Affektregulation stärken","Alltagsfunktion und Beziehungen stabilisieren"],
               ["Traumafokussierte KVT: Psychoedukation, Stabilisierung nach Bedarf, qualifizierte traumafokussierte Bearbeitung, Trigger- und Vermeidungsarbeit.",
                "TP/psychodynamisch: Affektregulation, Beziehungssicherheit, traumabezogene Konflikte und Selbst-/Beziehungsrepräsentationen bearbeiten.",
                "Systemisch: Ressourcen, sichere Beziehungen, Kontext und Auswirkungen auf Partnerschaft/Familie einbeziehen."],
               ["Trigger/Belastungsniveau beobachten","Grounding-/Stabilisierungsübung","Ressourcen und sichere Situationen dokumentieren"]),
              (("F43.2",),"Anpassungsstörung / Belastungsreaktion",
               ["aktuelle Belastung bewältigen","Ressourcen mobilisieren","Problemlösefähigkeit stärken","neue Perspektiven und Handlungsschritte entwickeln"],
               ["KVT/VT: Stressmodell, Problemlösen, Aktivierung, kognitive Neubewertung und Coping.",
                "TP/psychodynamisch: Bedeutung des Auslösers, Verluste, Konflikte und Beziehungsmuster bearbeiten.",
                "Systemisch: Kontext, Rollen, Ressourcen, Netzwerk und lösungsorientierte nächste Schritte bearbeiten."],
               ["Belastungssituationen protokollieren","konkreten nächsten Schritt planen","Unterstützungsnetz aktivieren"]),
              (("F50",),"Essstörung / problematisches Essverhalten",
               ["Essverhalten stabilisieren","körperliche Risiken reduzieren","Körperbild und Selbstwert bearbeiten","aufrechterhaltende Muster verändern"],
               ["Störungsspezifische KVT: Essstruktur, Selbstbeobachtung, Körperbild, dysfunktionale Regeln und aufrechterhaltende Verhaltensmuster.",
                "TP/psychodynamisch: Selbstwert, Affekte, Autonomie/Abhängigkeit und Beziehungskonflikte bearbeiten.",
                "Systemisch: familiäre/partnerschaftliche Muster und Ressourcen einbeziehen; medizinische und ernährungstherapeutische Kooperation prüfen."],
               ["Ess-/Situationsprotokoll nach therapeutischer Vereinbarung","Auslöser und Bewertungen beobachten","ressourcenorientierte Aufgabe"]),
              (("F51","G47"),"Schlafprobleme",
               ["Schlafdruck und Rhythmus stabilisieren","schlafstörende Gewohnheiten reduzieren","Grübeln/Aktivierung senken"],
               ["KVT/VT: Schlafprotokoll, Psychoedukation, Stimulus-Kontrolle, Schlafrhythmus und kognitive Arbeit an schlafbezogenen Sorgen.",
                "TP/psychodynamisch: Belastungen, Affekte und Konflikte mit Bezug zu nächtlicher Aktivierung explorieren."],
               ["Schlafprotokoll","konstante Aufstehzeit erproben","abendliche Aktivierung/Grübeln beobachten"]),
              (("F90",),"ADHS / Aufmerksamkeitsprobleme",
               ["Alltagsorganisation verbessern","Aufgabensteuerung stärken","Impulsivität und Überforderung reduzieren","Selbstwert stabilisieren"],
               ["KVT/VT: Psychoedukation, Strukturierung, Aufgabenzerlegung, Reizkontrolle, Zeitmanagement und Problemlösen.",
                "TP/psychodynamisch: Selbstwert, Beziehungserfahrungen und emotionale Regulation bearbeiten.",
                "Systemisch: Umweltanpassung, Rollen, Kommunikations- und Unterstützungsstrukturen einbeziehen."],
               ["Aufgabe in kleine Schritte zerlegen","sichtbare Checkliste nutzen","Ablenkungen und Konzentrationsphasen protokollieren"]),
            ]
            label="Allgemeiner Behandlungsplan"
            goals=["Anliegen und Auftrag präzisieren","Ressourcen und Belastungsfaktoren erfassen","konkrete und überprüfbare Therapieziele vereinbaren","Verlauf regelmäßig evaluieren"]
            methods=["KVT/VT: Problem- und Bedingungsanalyse, konkrete Ziele, aufrechterhaltende Gedanken/Verhaltensmuster und alltagsnahe Übungen.",
                     "TP/psychodynamisch: biografische und aktuelle Konflikte, Beziehungsmuster, Affekte, Abwehr und interpersonelle Themen explorieren.",
                     "Systemisch: Kontext, Beziehungen, Ressourcen, Ausnahmen, zirkuläre Muster und Veränderungsaufträge einbeziehen."]
            homework=["Beobachtungsaufgabe passend zum Therapieziel","Auslöser, Gedanken, Gefühle und Verhalten protokollieren"]
            for prefixes,name,g,m,h in catalog:
                if d.startswith(prefixes): label,goals,methods,homework=name,g,m,h; break

            lines=[f"ARBEITSHYPOTHESE / SCHWERPUNKT: {label}"]
            if d: lines.append(f"Verdachtsdiagnose / Code: {d}")
            lines+=["\nTHERAPIEZIELE"]+["• "+x for x in goals]
            lines+=["\nMETHODEN / INTERVENTIONEN"]+["• "+x for x in methods]

            if hasattr(self,"couple_mode") and self.couple_mode.isChecked():
                pair=[
                  "Auftrag klären: gemeinsame und individuelle Ziele beider Partner sowie Ergebnisoffenheit festhalten.",
                  "Systemisch: Eskalationskreislauf externalisieren; Trigger, Positionen, wechselseitige Verstärkung, Ressourcen und positive Ausnahmen sichtbar machen.",
                  "Kommunikationsorientiert: aktives Zuhören, Validierung, Ich-Botschaften, Bedürfnis-/Grenzklärung, Time-out und Reparaturgespräche üben.",
                  "Emotions-/bindungsfokussiert: Primäremotionen und Bindungsbedürfnisse hinter Angriff/Rückzug herausarbeiten; sichere Responsivität fördern.",
                  "Verhaltensorientiert: positive Interaktionen erhöhen, Problemlösetraining, konkrete Vereinbarungen und Transferaufgaben.",
                  "Vertrauen/Verletzungen: Stabilisierung, Verantwortungsübernahme, Transparenz, Bedeutung der Verletzung und schrittweise Wiederannäherung bearbeiten.",
                  "Intimität/Sexualität: Bedürfnisse, Grenzen, Druck/Vermeidung und Kommunikation behutsam explorieren; somatische Faktoren bei Bedarf abklären.",
                  "Elternebene: Paar- und Elternebene differenzieren, kindzentrierte Kooperation und verlässliche Absprachen fördern.",
                  "Trennungs-/Klärungsarbeit: bei ambivalentem Auftrag Entscheidung nicht vorwegnehmen; Bedürfnisse, Optionen und Folgen strukturiert klären."
                ]
                lines+=["\nPAARTHERAPIE – MÖGLICHE INTERVENTIONEN"]+["• "+x for x in pair]
                if getattr(self,"couple_violence",None) and self.couple_violence.isChecked():
                    lines+=["\nSICHERHEIT / KONTRAINDIKATION","• Bei Gewalt, Drohung, Zwang oder Kontrolle zunächst getrennte Risiko- und Sicherheitsklärung; übliche gemeinsame Paarinterventionen nicht automatisch fortführen."]

            lines+=["\nMÖGLICHE TRANSFERAUFGABEN"]+["• "+x for x in homework]
            lines+=["\nVERLAUFSPLAN",
                    "• Startphase: Diagnostik/Exploration, Auftrag, Ziele, Ressourcen, Risiko- und Kontextklärung.",
                    "• Arbeitsphase: ausgewählte Interventionen schrittweise durchführen und Wirkung/Belastung regelmäßig evaluieren.",
                    "• Transferphase: Veränderungen in Alltag und Beziehungen erproben, Hindernisse bearbeiten.",
                    "• Abschluss/Rückfallprophylaxe: Fortschritte bilanzieren, Warnzeichen und hilfreiche Strategien festhalten."]
            self.therapy_plan.setPlainText("\n".join(lines))
        planbtn.clicked.connect(suggest_therapy_plan)

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
            selected=selected_override if isinstance(selected_override,list) else None  # Signale (z. B. currentTextChanged) liefern Text -> ignorieren
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

    def restore_draft(self,ask=True):
        p=ROOT/"Sitzung_Autosave.json.enc"
        legacy=ROOT/"Sitzung_Autosave.json"
        if not p.exists() and not legacy.exists(): return
        try:
            if p.exists(): d=json.loads(decrypt_text(p.read_text(encoding="utf-8")))
            else:
                d=json.loads(legacy.read_text(encoding="utf-8")); p.write_text(encrypt_text(json.dumps(d,ensure_ascii=False)),encoding="utf-8"); legacy.unlink()
            if (not ask) or QMessageBox.question(self,"Sitzung wiederherstellen","Es gibt eine automatisch gespeicherte Sitzung. Wiederherstellen?")==QMessageBox.Yes:
                self.s_last.setText(d.get("last","")); self.s_first.setText(d.get("first","")); self.s_dob.setText(d.get("dob",""))
                qd=QDate.fromString(d.get("date",""),"yyyy-MM-dd")
                if qd.isValid(): self.s_date.setDate(qd)
                qs=QTime.fromString(d.get("start",""),"HH:mm")
                if qs.isValid(): self.s_start.setTime(qs)
                qe=QTime.fromString(d.get("end",""),"HH:mm")
                if qe.isValid(): self.s_end.setTime(qe)
                self.s_type.setCurrentText(d.get("type","Einzeltherapie")); self.s_red.setChecked(bool(d.get("reduced",False))); self.notes.setPlainText(d.get("notes","")); self.session_homework.setPlainText(d.get("homework",""))
                inkfile=d.get("ink_file","")
                if inkfile and Path(inkfile).exists():
                    self.ink.load_png(inkfile)
                    if d.get("ink_strokes"): self.ink.set_stroke_data(d["ink_strokes"])
                self.acc=int(d.get("seconds",0)); self.running=False; self.started=None
                self.nav.setCurrentRow(1)
        except Exception: pass
    def autosave_session(self):
        if not self.running and not self.notes.toPlainText().strip() and not self.s_last.text().strip() and not self.s_first.text().strip(): return
        draft={"last":self.s_last.text(),"first":self.s_first.text(),"dob":self.s_dob.text(),"date":self.s_date.date().toString("yyyy-MM-dd"),"note_date":self.s_date.date().toString("yyyy-MM-dd"),"autosaved_at":datetime.now().isoformat(timespec="seconds"),"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"seconds":self.elapsed(),"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"notes":self.notes.toPlainText(),"homework":self.session_homework.toPlainText().strip(),"running":self.running}
        inkdraft=ROOT/"Sitzung_Autosave_Handschrift.png"; self.ink.save_png(inkdraft); encrypted_ink=encrypt_file(inkdraft); draft["ink_file"]=encrypted_ink; draft["ink_strokes"]=self.ink.stroke_data()
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
        # Den aktuellen Stand sofort zusätzlich als verschlüsselten Entwurf sichern.
        self.autosave_session()
        choice=QMessageBox.question(
            self,"Sitzung beenden",
            "Die Sitzung wurde beendet.\n\nSoll sie jetzt als Sitzungsnotiz dauerhaft gespeichert werden?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if choice==QMessageBox.Yes:
            self.save_session()
        else:
            QMessageBox.information(self,"Sitzung zwischengespeichert",
                "Die Sitzung bleibt automatisch verschlüsselt zwischengespeichert und kann später weiterbearbeitet werden.")
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
        note_date=self.s_date.date().toString("yyyy-MM-dd")
        note_timestamp=datetime.now().isoformat(timespec="seconds")
        rec={"id":datetime.now().strftime("%Y%m%d%H%M%S%f"),"last":last,"first":first,"dob":self.s_dob.text(),"date":note_date,"note_date":note_date,"saved_at":note_timestamp,"start":self.s_start.time().toString("HH:mm"),"end":self.s_end.time().toString("HH:mm"),"minutes":mins,"type":self.s_type.currentText(),"reduced":self.s_red.isChecked(),"suspected_diagnosis":self.session_diag.text().strip(),"notes":self.notes.toPlainText(),"homework":self.session_homework.toPlainText().strip(),"billed":False}
        if partner: rec["partner"]={"last":partner.get("last",""),"first":partner.get("first",""),"dob":partner.get("dob","")}
        d=client_dir(c)/"Sitzungen"; inkfile=d/f"{rec['date']}_{rec['id']}_Handschrift.png"; self.ink.save_png(inkfile,f"{last}, {first}  –  {rec['date']} {datetime.now().strftime('%H:%M')} Uhr"); rec["ink_file"]=encrypt_file(inkfile)
        _sd=self.ink.stroke_data()
        if _sd: rec["ink_strokes"]=_sd
        rec["ocr_text"]=self.current_ocr_text.strip()
        if rec["ocr_text"]:
            ocrfile=d/(rec["date"]+"_"+rec["id"]+"_OCR.txt.enc")
            ocrfile.write_text(encrypt_text(rec["ocr_text"]),encoding="utf-8")
            rec["ocr_file"]=str(ocrfile)
        DB["sessions"].append(rec)
        save_data()
        # Jede Sitzungsnotiz wird datiert und eindeutig im Ordner des Klienten abgelegt.
        # Die ID verhindert, dass mehrere Sitzungen am selben Tag einander überschreiben.
        session_json=d/(rec["date"]+"_"+rec["id"]+"_Sitzungsnotiz.json.enc")
        session_json.write_text(encrypt_text(json.dumps(rec,ensure_ascii=False,indent=2)),encoding="utf-8")
        rec["note_file"]=str(session_json)
        save_data()
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
        self.i_date=FlexDateEdit(QDate.currentDate()); self.i_date.setCalendarPopup(True); self.i_date.setDisplayFormat("dd.MM.yyyy"); self.i_type=QComboBox(); self.i_type.addItems(["Einzeltherapie","Paargespräch","Onlinegespräch","Notfalltelefonat","Hausbesuch","Ausfallhonorar","Sonstige"])
        self.i_min=QSpinBox(); self.i_min.setRange(1,1000); self.i_min.setValue(45); self.i_red=QCheckBox("Ermäßigter Satz")
        self.i_start=FlexTimeEdit(QTime.currentTime()); self.i_start.setDisplayFormat("HH:mm"); self.i_end=FlexTimeEdit(QTime.currentTime().addSecs(45*60)); self.i_end.setDisplayFormat("HH:mm")
        for ed in (self.i_date,self.i_type,self.i_min,self.i_start,self.i_end): ed.setMinimumHeight(40)
        f.addRow("Klient auswählen / suchen",self.i_client)
        for a,b in [("Rechnungsnummer",self.i_no),("Nachname",self.i_last),("Vorname",self.i_first),("Adresse",self.i_addr),("Diagnose (optional)",self.i_diag),("Leistungsdatum",self.i_date),("Beginn",self.i_start),("Ende",self.i_end),("Leistung",self.i_type),("Dauer Minuten",self.i_min)]: f.addRow(a,b)
        def invoice_times():
            secs=self.i_start.time().secsTo(self.i_end.time())
            if secs>0:self.i_min.setValue(max(1,secs//60))
        self.i_start.timeChanged.connect(invoice_times); self.i_end.timeChanged.connect(invoice_times)
        self.i_last.editingFinished.connect(self.fill_invoice_client); self.i_first.editingFinished.connect(self.fill_invoice_client)
        f.addRow("",self.i_red)
        self.i_paid=QCheckBox("Rechnung ist bereits beglichen – zusätzlich PDF mit Dankeschön erstellen"); f.addRow("",self.i_paid); v.addWidget(card)
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
        additem.clicked.connect(add_manual_item); self.refresh_invoice_items=refresh_items
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
            te.normalize(); parsed=te.time()
            if not te.hasValidInput():
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
            "amount": amt, "status": "bezahlt" if (hasattr(self,"i_paid") and self.i_paid.isChecked()) else "offen", "paid_date": datetime.now().strftime("%Y-%m-%d") if (hasattr(self,"i_paid") and self.i_paid.isChecked()) else "", "pdf": str(pdf), "items": items
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
            te.normalize(); parsed=te.time()
            if not te.hasValidInput():
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
        user=self.current_user.get("username","") if self.current_user else ""
        if not practice_logo_path():
            QMessageBox.warning(self,"Logo fehlt","Es konnte kein gültiges Praxislogo geladen werden.\nDie Rechnung wird ohne Logo erzeugt.\nBitte prüfen Sie die Praxiseinstellungen.")
        invoice_items=[]
        if rows:
            for s in rows:
                invoice_items.append({"id":s.get("id"),"date":s.get("date",""),"start":s.get("start",""),"end":s.get("end",""),"minutes":int(s.get("minutes",0)),"type":s.get("type",""),"reduced":bool(s.get("reduced",False)),"amount":round(float(s.get("amount",amount_for(int(s.get("minutes",0)),s.get("type","Einzeltherapie"),bool(s.get("reduced",False))))),2)})
        else:
            invoice_items=[{"id":None,"date":self.i_date.date().toString("yyyy-MM-dd"),"start":self.i_start.time().toString("HH:mm"),"end":self.i_end.time().toString("HH:mm"),"minutes":mins,"type":typ,"reduced":self.i_red.isChecked(),"amount":amt}]
        paid_now=hasattr(self,"i_paid") and self.i_paid.isChecked()
        rec={"number":no,"date":datetime.now().strftime("%Y-%m-%d"),"client":f"{last}, {first}","address":self.i_addr.text().strip(),"diagnosis":self.i_diag.text().strip(),"amount":amt,"status":"offen","paid_date":"","pdf":str(pdf),"items":invoice_items}
        try:
            write_invoice_pdf(rec,"invoice",pdf,user=user)
            if paid_now:
                rec["status"]="bezahlt"; rec["paid_date"]=datetime.now().strftime("%Y-%m-%d"); rec["reminder_closed"]=True
                paid_pdf=d/f"Rechnung_{no}_beglichen.pdf"; write_invoice_pdf(rec,"paid",paid_pdf,paid_date=_de_date(rec["paid_date"]),user=user); rec["pdf_paid"]=str(paid_pdf)
        except Exception as e:
            audit("INVOICE_PDF_ERROR",str(e)[:500],user); return QMessageBox.warning(self,"Rechnung","Die PDF konnte nicht erstellt werden:\n\n"+str(e)[:500])
        if paid_now: pdf=Path(rec["pdf_paid"])
        DB["invoices"].append(rec)
        if rows:
            ids={s.get("id") for s in rows}
            for s in DB["sessions"]:
                if s.get("id") in ids: s["billed"]=True; s["invoice_number"]=no
            self.pending_sessions=None
        self.manual_items=[]; self.iteminfo.setText("Noch keine zusätzlichen Leistungen")
        if hasattr(self,"itemtable"): self.itemtable.setRowCount(0)
        save_data(); update_excel(); self.i_no.setText(next_no())
        if hasattr(self,"i_paid"): self.i_paid.setChecked(False)
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
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(18,14,18,14); v.setSpacing(12)
        title=QLabel("Neuen Klienten anlegen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Pflicht sind nur Vor- und Nachname. Alles andere kann jederzeit in der Klientenakte ergänzt werden."); sub.setObjectName("pageSub"); v.addWidget(sub)
        form=ClientForm(); self.new_client_form=form; v.addWidget(form)
        row=QHBoxLayout(); row.addStretch(); save=QPushButton("💾 Klient anlegen"); save.setMinimumHeight(44); session=QPushButton("＋ Anlegen und Sitzung öffnen"); session.setMinimumHeight(44)
        def create(go_session=False):
            if not self.require_edit():return
            cc=form.values()
            if not cc["last"] or not cc["first"]:return QMessageBox.warning(self,"Fehlt","Vorname und Nachname sind erforderlich.")
            cc["created_at"]=datetime.now().isoformat(timespec="seconds")
            if any(x.get("last","").lower()==cc["last"].lower() and x.get("first","").lower()==cc["first"].lower() and x.get("dob","")==cc["dob"] for x in DB["clients"]):return QMessageBox.warning(self,"Klient","Dieser Klient ist bereits vorhanden.")
            DB["clients"].append(cc); save_data(); audit("CLIENT_CREATED","Klient angelegt",self.current_user.get("username","") if self.current_user else "")
            if hasattr(self,"client_pick"): self.client_pick.addItem(f"{cc['last']}, {cc['first']}",cc)
            if go_session:
                self.s_last.setText(cc["last"]); self.s_first.setText(cc["first"]); self.s_dob.setText(cc["dob"]); self.s_phone.setText(cc.get("phone","")); self.s_email.setText(cc.get("email","")); self.client_pick.setCurrentIndex(self.client_pick.count()-1); self.nav.setCurrentRow(1)
            else:
                QMessageBox.information(self,"Klient","Klient wurde angelegt."); form.clear()
        save.clicked.connect(lambda:create(False)); session.clicked.connect(lambda:create(True)); row.addWidget(save); row.addWidget(session); v.addLayout(row); v.addStretch(); return w

    def clients_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Klienten"); title.setObjectName("pageTitle"); v.addWidget(title)
        tools=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Klient suchen …"); search.setClearButtonEnabled(True); tools.addWidget(search,1); v.addLayout(tools)
        TABLE_KEYS=["last","first","dob","phone","email","payer"]
        t=QTableWidget(0,len(TABLE_KEYS)); t.setHorizontalHeaderLabels(["Nachname","Vorname","Geburtsdatum","Telefon","E-Mail","Kostenträger"]); t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); t.setAlternatingRowColors(True); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers)
        self.clients_table=t
        def fill_table():
            t.setRowCount(0)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                r=t.rowCount(); t.insertRow(r)
                for j,k in enumerate(TABLE_KEYS): t.setItem(r,j,QTableWidgetItem(str(cc.get(k,"") or ("Selbstzahler" if k=="payer" else ""))))
            filter_clients(search.text())
        self.refresh_clients_table=lambda: fill_table()
        v.addWidget(t)
        def filter_clients(txt):
            q=txt.strip().lower()
            for row in range(t.rowCount()):
                hay=" ".join(t.item(row,col).text().lower() if t.item(row,col) else "" for col in range(t.columnCount()))
                t.setRowHidden(row,q not in hay)
        search.textChanged.connect(filter_clients); fill_table()
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
            contact=QLabel(" · ".join(x for x in [phone,email,cc.get("address",""),cc.get("payer","")] if x) or "Keine Kontaktdaten hinterlegt"); contact.setObjectName("pageSub"); contact.setWordWrap(True); person.addWidget(contact)
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
            # Akte in Reitern: Verlauf & Rechnungen · Stammdaten · Dokumente
            outer_lay=lay; akte_tabs=QTabWidget(); akte_tabs.setDocumentMode(True); outer_lay.addWidget(akte_tabs,1)
            p1=QWidget(); lay=QVBoxLayout(p1); lay.setContentsMargins(0,8,0,0); akte_tabs.addTab(p1,"Sitzungen & Rechnungen")
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
                start_time=FlexTimeEdit(); start_time.setDisplayFormat("HH:mm"); start_time.setTime(QTime.fromString(s.get("start","09:00"),"HH:mm"))
                end_time=FlexTimeEdit(); end_time.setDisplayFormat("HH:mm"); end_time.setTime(QTime.fromString(s.get("end","09:45"),"HH:mm"))
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
                nd=QDialog(dlg); nd.setWindowTitle(f"Sitzungsnotiz {date} {start}"); nv=QVBoxLayout(nd)
                _ag=QApplication.primaryScreen().availableGeometry(); nd.resize(min(940,int(_ag.width()*0.92)),min(780,int(_ag.height()*0.85))); nd.move(_ag.x()+max(0,(_ag.width()-nd.width())//2),_ag.y()+max(0,(_ag.height()-nd.height())//3))
                hint=QLabel("Alle Texte sind nachträglich bearbeitbar. Änderungen werden erst mit „Änderungen speichern“ übernommen."); hint.setWordWrap(True); nv.addWidget(hint)
                tabs=QTabWidget()
                tx=QTextEdit(); tx.setPlainText(s.get("notes","")); tabs.addTab(tx,"Therapienotiz")
                hw=QTextEdit(); hw.setPlainText(s.get("homework","")); tabs.addTab(hw,"Hausaufgaben")
                ocr=QTextEdit()
                ocr_text=s.get("ocr_text","")
                if not ocr_text and s.get("ocr_file") and Path(s.get("ocr_file")).exists():
                    try: ocr_text=decrypt_text(Path(s.get("ocr_file")).read_text(encoding="utf-8"))
                    except Exception: ocr_text=""
                ocr.setPlainText(ocr_text); ocr.setPlaceholderText("Hier steht der aus der Handschrift erkannte Text (bearbeitbar)."); tabs.addTab(ocr,"Erkannter Text")
                nv.addWidget(tabs,1)
                ink=s.get("ink_file",""); ink_img=None
                if ink and Path(ink).exists():
                    raw=decrypt_file_bytes(ink); pix=QPixmap(); pix.loadFromData(raw)
                    if not pix.isNull():
                        ink_img=pix.toImage(); lab=QLabel(); lab.setPixmap(pix.scaledToWidth(min(880,pix.width()),Qt.SmoothTransformation)); lab.setAlignment(Qt.AlignCenter)
                        sc=QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(lab); sc.setMinimumHeight(180); sc.setMaximumHeight(300); nv.addWidget(sc)
                bar=QWidget(); bl=FlowLayout(bar,8,8); bl.setContentsMargins(0,0,0,0)
                savebtn=QPushButton("💾 Änderungen speichern"); convbtn=QPushButton("⌨ Handschrift → Text"); convbtn.setEnabled(ink_img is not None); closebtn=QPushButton("Schließen")
                for bb_ in (savebtn,convbtn,closebtn): bb_.setMinimumHeight(40); bl.addWidget(bb_)
                nv.insertWidget(1,bar)
                def convert():
                    lang=OCR_LANGS.get(get_setting("ocr_lang","Deutsch"),"de-DE")
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                    try: text,err=recognize_saved_handwriting(ink_img,lang,s.get("ink_strokes"))
                    finally: QApplication.restoreOverrideCursor()
                    if err in ("LEER","KEIN_TEXT"): return QMessageBox.information(nd,"Handschrift → Text","Es wurde keine Schrift erkannt.")
                    if err: return QMessageBox.warning(nd,"Handschrift → Text","Die Handschrift konnte nicht erkannt werden.\n\n"+err)
                    stamp=datetime.now().strftime("%d.%m.%Y %H:%M")
                    ocr.setPlainText(text.strip()); tx.setPlainText((tx.toPlainText().rstrip()+"\n\n" if tx.toPlainText().strip() else "")+"[Handschrift, umgewandelt "+stamp+"]\n"+text.strip()); tabs.setCurrentIndex(0)
                    QMessageBox.information(nd,"Handschrift → Text","Der erkannte Text wurde in die Therapienotiz eingefügt. Bitte prüfen, ggf. korrigieren und speichern. Die Handschrift bleibt erhalten.")
                def save_changes():
                    s["notes"]=tx.toPlainText(); s["homework"]=hw.toPlainText(); s["ocr_text"]=ocr.toPlainText().strip(); s["corrected_at"]=datetime.now().isoformat(timespec="seconds")
                    try:
                        d_=client_dir({"last":last,"first":first})/"Sitzungen"; d_.mkdir(parents=True,exist_ok=True)
                        if s["ocr_text"]:
                            of=d_/(s.get("date","")+"_"+s.get("id","Sitzung")+"_OCR.txt.enc"); of.write_text(encrypt_text(s["ocr_text"]),encoding="utf-8"); s["ocr_file"]=str(of)
                        jf=d_/f'{s.get("date","")}_{s.get("id","Sitzung")}_Sitzung.json.enc'; jf.write_text(encrypt_text(json.dumps(s,ensure_ascii=False,indent=2)),encoding="utf-8")
                    except Exception: pass
                    save_data(); audit("SESSION_NOTE_EDITED",f"Sitzungsnotiz bearbeitet: {last}, {first} {date}",self.current_user.get("username","") if self.current_user else "")
                    QMessageBox.information(nd,"Gespeichert","Die Änderungen wurden gespeichert.")
                savebtn.clicked.connect(save_changes); convbtn.clicked.connect(convert); closebtn.clicked.connect(nd.reject); nd.exec()
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
            if cc:
                akte_tabs.addTab(self.client_master_tab(cc,nm,contact),"Stammdaten & Kostenträger")
                akte_tabs.addTab(self.client_documents_tab(cc,dlg),"Dokumente")
            close=QDialogButtonBox(QDialogButtonBox.Close); close.rejected.connect(dlg.reject); outer_lay.addWidget(close); dlg.exec()
            if hasattr(self,"refresh_clients_table"): self.refresh_clients_table()
        opensessions.clicked.connect(show_sessions); t.cellDoubleClicked.connect(lambda *_: show_sessions())
        def edit_client_master():
            r=t.currentRow()
            if r<0: return QMessageBox.information(self,"Klient","Bitte zuerst einen Klienten auswählen.")
            last=t.item(r,0).text(); first=t.item(r,1).text()
            cc=next((x for x in DB["clients"] if x.get("last")==last and x.get("first")==first),None)
            if not cc:return
            if self.edit_client_record(cc):
                for j,key in enumerate(TABLE_KEYS): t.setItem(r,j,QTableWidgetItem(str(cc.get(key,""))))
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
        openink=QPushButton("✎ Handschriften des Klienten ansehen / in Text umwandeln"); openink.setMinimumHeight(45)
        def show_ink():
            r=t.currentRow()
            if r<0: return QMessageBox.information(self,"Handschrift","Bitte zuerst einen Klienten auswählen.")
            self.handwriting_archive(t.item(r,0).text(),t.item(r,1).text())
        openink.clicked.connect(show_ink); v.addWidget(openink)
        b=QPushButton("Klientenliste aktualisieren"); b.setMinimumHeight(45)
        def refresh():
            t.setRowCount(0)
            for cc in sorted(DB["clients"],key=lambda z:(z.get("last","").lower(),z.get("first","").lower())):
                r=t.rowCount(); t.insertRow(r)
                for j,k in enumerate(["last","first","dob","phone","email"]): t.setItem(r,j,QTableWidgetItem(str(cc.get(k,""))))
        b.clicked.connect(refresh); v.addWidget(b); return w
    def backup_box(self):
        """Sicherung, Sicherungsziel und Schlüsselschutz (gehört in die Einstellungen, nicht in die Rechnungsliste)."""
        bkbox=QGroupBox("Datensicherung && Wiederherstellungsschlüssel"); bkflow=FlowLayout(bkbox); bkflow.setContentsMargins(12,20,12,12); v=bkflow
        backup=QPushButton("Datensicherung erstellen"); backup.setMinimumHeight(42)
        def do_backup():
            backup_root=Path(get_setting("backup_dir","") or ROOT/"Backups")
            try: backup_root.mkdir(parents=True,exist_ok=True)
            except Exception: return QMessageBox.warning(self,"Sicherung","Das Sicherungsziel ist nicht erreichbar:\n"+str(backup_root)+"\n\nBitte USB-Stick anschließen oder ein anderes Ziel wählen.")
            dest=backup_root/datetime.now().strftime("Backup_%Y-%m-%d_%H-%M-%S"); dest.mkdir(parents=True,exist_ok=True)
            if DATA.exists(): shutil.copy2(DATA,dest/DATA.name)
            if DBFILE.exists():
                con=sqlite3.connect(DBFILE); out=sqlite3.connect(dest/DBFILE.name); con.backup(out); out.close(); con.close()
            # Exporte (PDF/XLSX) bleiben bewusst außerhalb der verschlüsselten Datensicherung.
            # Der lokale Hauptschlüssel wird niemals zusammen mit dem Backup kopiert.
            for src in (ROOT/"Klienten").rglob("*.enc"):
                rel=src.relative_to(ROOT/"Klienten"); target=dest/"Klienten"/rel; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,target)
            # Separater Wiederherstellungsschlüssel: bewusst nicht im Backup-Ordner.
            key_export=backup_root/("Wiederherstellungsschluessel_"+datetime.now().strftime("%Y-%m-%d_%H-%M-%S")+".key")
            key_exported=KEYFILE.exists()
            if key_exported: shutil.copy2(KEYFILE,key_export)
            (dest/"Backup_Info.txt").write_text("Praxisverwaltung Sicherung\nErstellt: "+datetime.now().isoformat(timespec="seconds")+"\nKlienten: "+str(len(DB.get("clients",[])))+"\nSitzungen: "+str(len(DB.get("sessions",[])))+"\nRechnungen: "+str(len(DB.get("invoices",[])))+"\nDer Wiederherstellungsschlüssel wurde separat erstellt und darf nicht zusammen mit dem Backup aufbewahrt werden.",encoding="utf-8")
            if key_exported: QMessageBox.information(self,"Sicherung","Sicherung erstellt:\n"+str(dest)+"\n\nWiederherstellungsschlüssel separat erstellt:\n"+str(key_export)+"\n\nBitte Schlüssel und Backup getrennt aufbewahren (z. B. Schlüssel auf USB-Stick).")
            else: QMessageBox.information(self,"Sicherung","Sicherung erstellt:\n"+str(dest)+"\n\nDer Datenschlüssel ist an Ihr Windows-Konto gebunden und wird nicht mitgesichert. Bewahren Sie Ihren Wiederherstellungsschlüssel (.key) getrennt auf. Ohne ihn lässt sich die Sicherung auf einem anderen PC nicht öffnen.")
        backup.clicked.connect(lambda: do_backup() if self.require_edit() else None); v.addWidget(backup)
        restore=QPushButton("Datensicherung wiederherstellen …"); restore.setMinimumHeight(42)
        def do_restore():
            if not self.is_admin(): return QMessageBox.warning(self,"Keine Berechtigung","Wiederherstellung ist Administratoren vorbehalten.")
            folder=QFileDialog.getExistingDirectory(self,"Backup-Ordner auswählen",str(Path(get_setting("backup_dir","") or ROOT/"Backups")))
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
            if KEYFILE_PROT.exists():shutil.copy2(KEYFILE_PROT,safety/KEYFILE_PROT.name)
            KEYFILE_PROT.unlink(missing_ok=True)
            shutil.copy2(key,KEYFILE); shutil.copy2(src/DATA.name,DATA); shutil.copy2(src/DBFILE.name,DBFILE)
            if (src/"Klienten").exists(): shutil.copytree(src/"Klienten",ROOT/"Klienten",dirs_exist_ok=True)
            audit("BACKUP_RESTORE","Datensicherung wiederhergestellt",self.current_user.get("username","") if self.current_user else "")
            QMessageBox.information(self,"Wiederherstellung","Wiederherstellung abgeschlossen. PraxisPro wird jetzt beendet. Bitte anschließend neu starten."); QApplication.quit()
        restore.clicked.connect(do_restore); v.addWidget(restore)
        target=QPushButton("Sicherungsziel wählen (z. B. USB-Stick) …"); target.setMinimumHeight(42)
        target_label=QLabel("Aktuelles Ziel: "+str(Path(get_setting("backup_dir","") or ROOT/"Backups"))); target_label.setWordWrap(True); target_label.setMaximumWidth(620); target_label.setObjectName("pageSub")
        def choose_target():
            if not self.require_edit(): return
            folder=QFileDialog.getExistingDirectory(self,"Sicherungsziel auswählen",str(Path(get_setting("backup_dir","") or ROOT)))
            if folder: set_setting("backup_dir",folder); target_label.setText("Aktuelles Ziel: "+folder)
        target.clicked.connect(choose_target); v.addWidget(target); v.addWidget(target_label)
        keyexp=QPushButton("Wiederherstellungsschlüssel speichern …"); keyexp.setMinimumHeight(42)
        def export_key():
            if not self.is_admin(): return QMessageBox.warning(self,"Keine Berechtigung","Nur Administratoren dürfen den Wiederherstellungsschlüssel speichern.")
            path,_=QFileDialog.getSaveFileName(self,"Wiederherstellungsschlüssel speichern (am besten auf USB-Stick)",str(Path.home()/"Wiederherstellungsschluessel_PraxisPro.key"),"Schlüssel (*.key)")
            if not path: return
            try:
                Path(path).write_bytes(encryption_key())
                if Path(path).read_bytes()!=encryption_key(): raise OSError("Prüfung der gespeicherten Datei fehlgeschlagen")
            except Exception as e: return QMessageBox.warning(self,"Schlüssel","Der Schlüssel konnte nicht gespeichert werden:\n"+str(e)[:300])
            audit("KEY_EXPORT","Wiederherstellungsschlüssel gespeichert",self.current_user.get("username","") if self.current_user else "")
            QMessageBox.information(self,"Schlüssel","Der Wiederherstellungsschlüssel wurde gespeichert.\n\nBewahren Sie ihn getrennt von den Daten auf (z. B. USB-Stick im Safe). Wer diese Datei besitzt, kann die Praxisdaten entschlüsseln.")
        keyexp.clicked.connect(export_key); v.addWidget(keyexp)
        keyprot=QPushButton("Schlüssel mit Windows-Konto schützen …"); keyprot.setMinimumHeight(42); keyprot.clicked.connect(lambda: self.offer_key_protection(force=True)); v.addWidget(keyprot)
        return bkbox

    def invoices_ui(self):
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(28,28,28,28); v.setSpacing(14)
        title=QLabel("Rechnungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Offene, bezahlte und stornierte Rechnungen verwalten"); sub.setObjectName("pageSub"); v.addWidget(sub)
        filters=QHBoxLayout(); search=QLineEdit(); search.setPlaceholderText("Rechnung oder Klient suchen …"); search.setClearButtonEnabled(True)
        statusfilter=QComboBox(); statusfilter.addItems(["Alle Status","offen","überfällig","bezahlt","storniert"]); statusfilter.setMinimumWidth(150)
        filters.addWidget(search,1); filters.addWidget(statusfilter); v.addLayout(filters)
        t=QTableWidget(0,8); t.setHorizontalHeaderLabels(["Nr.","Datum","Klient","Status","Zahlungsdatum","Mahnstufe","Letzte Erinnerung","Betrag"]); hh=t.horizontalHeader(); hh.setSectionResizeMode(QHeaderView.ResizeToContents); hh.setSectionResizeMode(2,QHeaderView.Stretch); hh.setMinimumHeight(38); t.verticalHeader().setVisible(False); t.setWordWrap(False); t.setMinimumHeight(240); t.setSelectionMode(QTableWidget.ExtendedSelection); t.setSelectionBehavior(QTableWidget.SelectRows); t.setEditTriggers(QTableWidget.NoEditTriggers); t.setAlternatingRowColors(True); t.setToolTip("Doppelklick öffnet die Rechnungsdetails")
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
        search.textChanged.connect(filt); statusfilter.currentTextChanged.connect(filt); v.addWidget(t,1)
        summary=FlowLayout()
        overdue_count=0
        today=date.today()
        for inv in DB["invoices"]:
            if inv.get("status","offen")=="offen":
                try:
                    if (today-datetime.strptime(inv.get("date",""),"%Y-%m-%d").date()).days>14: overdue_count+=1
                except Exception: pass
        open_total=sum(float(x.get("amount",0)) for x in DB["invoices"] if x.get("status","offen")=="offen")
        paid_total=sum(float(x.get("amount",0)) for x in DB["invoices"] if x.get("status")=="bezahlt")
        summary_buttons=[]
        for txt,status_value in ((f"Offen: {open_total:.2f} €","offen"),(f"Bezahlt: {paid_total:.2f} €","bezahlt"),(f"Überfällig >14 Tage: {overdue_count}","überfällig"),(f"Rechnungen: {len(DB['invoices'])}","Alle Status")):
            lab=QPushButton(txt); lab.setObjectName("clientBadge"); lab.setCursor(Qt.PointingHandCursor); lab.setMinimumHeight(40); lab.setToolTip("Klicken, um diese Rechnungen in der Liste anzuzeigen.")
            lab.clicked.connect(lambda _=False,s=status_value: statusfilter.setCurrentText(s))
            summary.addWidget(lab); summary_buttons.append(lab)
        v.insertLayout(2,summary)
        h=FlowLayout()
        paid=QPushButton("✓ Als bezahlt markieren"); paid.setMinimumHeight(42)
        def selected_invoice():
            r=t.currentRow()
            if r<0:
                QMessageBox.information(self,"Rechnung","Bitte zuerst eine Rechnung auswählen."); return None,None
            no=t.item(r,0).text(); return r,next((x for x in DB["invoices"] if x.get("number")==no),None)
        def invoice_folder(inv):
            try:
                pp=Path(inv.get("pdf","")) if inv.get("pdf") else None
                if pp and pp.parent.exists(): return pp.parent
            except Exception: pass
            last,_,first=str(inv.get("client","")).partition(", ")
            return client_dir({"last":last,"first":first})/"Rechnungen"
        def make_paid_pdf(inv):
            """Rechnung mit 'beglichen'-Stempel und Dankestext erzeugen (Original bleibt unverändert)."""
            out=invoice_folder(inv)/f'Rechnung_{inv.get("number","")}_beglichen.pdf'
            write_invoice_pdf(inv,"paid",out,paid_date=_de_date(inv.get("paid_date","")),user=self.current_user.get("username","") if self.current_user else "")
            inv["pdf_paid"]=str(out); save_data(); return out
        def offer_pdf(title,text,out):
            box=QMessageBox(self); box.setIcon(QMessageBox.Information); box.setWindowTitle(title); box.setText(text); box.setInformativeText(str(out))
            of=box.addButton("Ordner öffnen",QMessageBox.ActionRole); op=box.addButton("PDF öffnen",QMessageBox.ActionRole); box.addButton("Schließen",QMessageBox.RejectRole); box.exec()
            if box.clickedButton()==of: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out).parent)))
            elif box.clickedButton()==op: QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        def mark_paid():
            r,inv=selected_invoice()
            if inv:
                if inv.get("status")=="storniert": return QMessageBox.warning(self,"Status","Eine stornierte Rechnung kann nicht als bezahlt markiert werden.")
                if inv.get("status")=="bezahlt":
                    # Bereits bezahlt: Dankes-PDF bei Bedarf (neu) erzeugen und anbieten.
                    try: out=make_paid_pdf(inv)
                    except Exception as e: return QMessageBox.warning(self,"PDF","Die PDF konnte nicht erstellt werden:\n\n"+str(e)[:500])
                    return offer_pdf("Rechnung beglichen","Diese Rechnung ist bereits als bezahlt markiert.\nDie Bestätigung mit Dank wurde (neu) erstellt.",out)
                if QMessageBox.question(self,"Zahlung","Rechnung "+str(inv.get("number",""))+" als bezahlt markieren?\n\nEs wird zusätzlich eine PDF mit Dankeschön erstellt.")!=QMessageBox.Yes:return
                inv["status"]="bezahlt"; inv["paid_date"]=datetime.now().strftime("%Y-%m-%d"); inv["reminder_closed"]=True; save_data(); update_excel(); audit("INVOICE_PAID","Rechnung "+str(inv.get("number",""))+" als bezahlt markiert",self.current_user.get("username","") if self.current_user else ""); t.item(r,3).setText("bezahlt"); t.item(r,4).setText(inv["paid_date"]); t.item(r,5).setText(str(inv.get("reminder_count",0))); t.item(r,6).setText(inv.get("reminder_date",""))
                try: out=make_paid_pdf(inv)
                except Exception as e: return QMessageBox.warning(self,"PDF","Die Rechnung wurde als bezahlt markiert, die Dankes-PDF konnte aber nicht erstellt werden:\n\n"+str(e)[:500])
                offer_pdf("Rechnung beglichen","Die Rechnung wurde als bezahlt markiert.\nDie PDF mit Dankeschön wurde erstellt.",out)
        paid.clicked.connect(mark_paid); h.addWidget(paid)
        cancel=QPushButton("Rechnung stornieren"); cancel.setMinimumHeight(42)
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
        delbtn=QPushButton("🗑 Rechnung löschen"); delbtn.setMinimumHeight(42); delbtn.setToolTip("Löscht markierte Rechnungen endgültig (z. B. Testrechnungen). Mehrere mit Strg/Umschalt markieren.")
        def delete_invoices():
            if not self.require_edit(): return
            if not self.is_admin(): return QMessageBox.warning(self,"Keine Berechtigung","Nur Administratoren dürfen Rechnungen löschen.")
            rows=sorted({i.row() for i in t.selectionModel().selectedRows()},reverse=True)
            if not rows and t.currentRow()>=0: rows=[t.currentRow()]
            if not rows: return QMessageBox.information(self,"Rechnung löschen","Bitte zuerst eine oder mehrere Rechnungen in der Liste markieren (mehrere mit Strg oder Umschalt).")
            numbers=[t.item(r,0).text() for r in rows]
            shown=", ".join(numbers[:8])+(" …" if len(numbers)>8 else "")
            warn=""
            if any(next((x for x in DB["invoices"] if x.get("number")==n),{}).get("status")=="bezahlt" for n in numbers): warn="\n\nAchtung: Darunter sind bereits als bezahlt markierte Rechnungen. Für echte Rechnungen ist Stornieren meist besser (Buchhaltung, Aufbewahrungspflicht)."
            if QMessageBox.question(self,"Rechnungen löschen",f"{len(numbers)} Rechnung(en) endgültig löschen?\n\n{shown}{warn}\n\nDas kann nicht rückgängig gemacht werden.")!=QMessageBox.Yes: return
            files=QMessageBox.question(self,"PDF-Dateien","Auch die zugehörigen PDF-Dateien (Rechnung, Dankes-PDF, Zahlungserinnerungen) vom Computer löschen?")==QMessageBox.Yes
            removed=0; released=0; deleted_files=0
            for n in numbers:
                inv=next((x for x in DB["invoices"] if x.get("number")==n),None)
                if not inv: continue
                for sess in DB["sessions"]:
                    if sess.get("invoice_number")==n: sess["billed"]=False; sess["invoice_number"]=""; released+=1
                if files:
                    for f in [inv.get("pdf"),inv.get("pdf_paid")]+list(inv.get("reminder_pdfs",[]) or []):
                        try:
                            if f and Path(f).exists(): Path(f).unlink(); deleted_files+=1
                        except Exception: pass
                DB["invoices"].remove(inv); removed+=1
            save_data(); update_excel()
            audit("INVOICE_DELETED",f"{removed} Rechnung(en) gelöscht: {', '.join(numbers)[:300]}",self.current_user.get("username","") if self.current_user else "")
            for r in rows: t.removeRow(r)
            QMessageBox.information(self,"Gelöscht",f"{removed} Rechnung(en) gelöscht."+(f"\n{deleted_files} PDF-Datei(en) entfernt." if files else "\nDie PDF-Dateien wurden behalten.")+(f"\n{released} verknüpfte Sitzung(en) sind wieder abrechenbar." if released else ""))
        delbtn.clicked.connect(delete_invoices); h.addWidget(delbtn)
        def fill_rows():
            t.setRowCount(0)
            for i in reversed(DB["invoices"]):
                r=t.rowCount(); t.insertRow(r); vals=[i.get("number",""),i.get("date",""),i.get("client",""),i.get("status","offen"),i.get("paid_date",""),str(i.get("reminder_count",0)),i.get("reminder_date",""),f'{float(i.get("amount",0)):.2f} €']
                for j,x in enumerate(vals): t.setItem(r,j,QTableWidgetItem(str(x)))
            filt()
        def invoice_form(inv=None):
            """Dialog zum Erfassen einer früheren Rechnung (inv=None) oder zum Ändern einer vorhandenen."""
            if not self.require_edit(): return
            dlg=QDialog(self); dlg.setWindowTitle("Rechnung bearbeiten" if inv else "Frühere Rechnung erfassen"); dlg.setMinimumWidth(560); lay=QVBoxLayout(dlg)
            lay.addWidget(QLabel("Für Rechnungen, die vor PraxisPro erstellt wurden, oder um Nummer und Angaben einer Rechnung zu korrigieren."))
            form=QFormLayout(); form.setVerticalSpacing(10)
            e_no=QLineEdit(inv.get("number","") if inv else next_no()); e_date=FlexDateEdit(QDate.fromString(inv.get("date",""),"yyyy-MM-dd") if inv and QDate.fromString(inv.get("date",""),"yyyy-MM-dd").isValid() else QDate.currentDate())
            e_client=QLineEdit(inv.get("client","") if inv else ""); e_client.setPlaceholderText("Nachname, Vorname")
            e_amt=QDoubleSpinBox(); e_amt.setRange(0,1000000); e_amt.setDecimals(2); e_amt.setSuffix(" €"); e_amt.setValue(float(inv.get("amount",0)) if inv else 0)
            e_status=QComboBox(); e_status.addItems(["offen","bezahlt","storniert"]); e_status.setCurrentText(inv.get("status","offen") if inv else "offen")
            pd=QDate.fromString(inv.get("paid_date",""),"yyyy-MM-dd") if inv else QDate()
            e_paid=FlexDateEdit(pd if pd.isValid() else QDate.currentDate())
            e_pdf=QLineEdit(inv.get("pdf","") if inv else ""); e_pdf.setPlaceholderText("Optional: PDF der Rechnung"); browse=QPushButton("Datei wählen …")
            def pick():
                f,_=QFileDialog.getOpenFileName(dlg,"PDF der Rechnung wählen",str(Path.home()),"PDF (*.pdf)")
                if f: e_pdf.setText(f)
            browse.clicked.connect(pick); pr=QHBoxLayout(); pr.addWidget(e_pdf,1); pr.addWidget(browse)
            for ed in (e_no,e_date,e_client,e_amt,e_status,e_paid,e_pdf): ed.setMinimumHeight(36)
            for lab,w_ in (("Rechnungsnummer",e_no),("Rechnungsdatum",e_date),("Klient",e_client),("Betrag",e_amt),("Status",e_status),("Bezahlt am",e_paid)): form.addRow(lab,w_)
            form.addRow("PDF",pr); lay.addLayout(form)
            e_paid.setEnabled(e_status.currentText()=="bezahlt"); e_status.currentTextChanged.connect(lambda v: e_paid.setEnabled(v=="bezahlt"))
            bb=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Save).setText("Speichern"); bb.button(QDialogButtonBox.Cancel).setText("Abbrechen"); lay.addWidget(bb)
            def save_form():
                no=e_no.text().strip()
                if not no or not re.fullmatch(r"[A-Za-z0-9._-]+",no): return QMessageBox.warning(dlg,"Rechnungsnummer","Bitte eine Rechnungsnummer eingeben (nur Buchstaben, Zahlen, Punkt, Bindestrich, Unterstrich).")
                if any(x.get("number")==no and x is not inv for x in DB["invoices"]): return QMessageBox.warning(dlg,"Doppelt","Diese Rechnungsnummer existiert bereits.")
                client=e_client.text().strip()
                if not client: return QMessageBox.warning(dlg,"Klient","Bitte den Klienten eintragen (Nachname, Vorname).")
                if not e_date.hasValidInput(): return QMessageBox.warning(dlg,"Datum","Bitte ein gültiges Rechnungsdatum eingeben.")
                pdf=e_pdf.text().strip()
                if pdf and not inv and Path(pdf).is_file():
                    try:
                        parts=[x.strip() for x in client.split(",",1)]; dest=client_folder(parts[0],parts[1] if len(parts)>1 else "")/"Rechnungen"; dest.mkdir(parents=True,exist_ok=True)
                        target=dest/Path(pdf).name
                        if not target.exists(): shutil.copy2(pdf,target)
                        pdf=str(target)
                    except Exception: pass
                status=e_status.currentText(); paid=e_paid.date().toString("yyyy-MM-dd") if status=="bezahlt" else ""
                if inv:
                    old=inv.get("number","")
                    if old!=no:
                        for sess in DB["sessions"]:
                            if sess.get("invoice_number")==old: sess["invoice_number"]=no
                    inv.update({"number":no,"date":e_date.date().toString("yyyy-MM-dd"),"client":client,"amount":e_amt.value(),"status":status,"paid_date":paid,"pdf":pdf})
                    audit("INVOICE_EDITED",f"{old} -> {no}",self.current_user.get("username","") if self.current_user else "")
                else:
                    DB["invoices"].append({"number":no,"date":e_date.date().toString("yyyy-MM-dd"),"client":client,"address":"","diagnosis":"","amount":e_amt.value(),"status":status,"paid_date":paid,"pdf":pdf,"items":[],"imported":True})
                    audit("INVOICE_IMPORTED",f"Frühere Rechnung {no} erfasst",self.current_user.get("username","") if self.current_user else "")
                save_data(); update_excel(); dlg.accept(); fill_rows()
                if hasattr(self,"i_no") and not inv: self.i_no.setText(next_no())
            bb.accepted.connect(save_form); bb.rejected.connect(dlg.reject); dlg.exec()
        addold=QPushButton("＋ Frühere Rechnung erfassen"); addold.setMinimumHeight(42); addold.setToolTip("Rechnungen, die vor PraxisPro erstellt wurden, in die Liste aufnehmen (mit Nummer, Datum, Betrag, Status, optional PDF)."); addold.clicked.connect(lambda: invoice_form()); h.addWidget(addold)
        editbtn=QPushButton("✎ Nummer/Angaben ändern"); editbtn.setMinimumHeight(42); editbtn.setToolTip("Rechnungsnummer, Datum, Klient, Betrag oder Status der markierten Rechnung ändern.")
        def edit_invoice():
            r,inv=selected_invoice()
            if inv: invoice_form(inv)
        editbtn.clicked.connect(edit_invoice); h.addWidget(editbtn)
        openpdf=QPushButton("PDF öffnen"); openpdf.setMinimumHeight(42)
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
        remind=QPushButton("Zahlungserinnerung"); remind.setMinimumHeight(42)
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
            try:
                lvl=min(3,int(inv["reminder_count"])); due=(date.today()+timedelta(days=7)).strftime("%d.%m.%Y")
                out=invoice_folder(inv)/f'Zahlungserinnerung_{inv.get("number","")}_{inv["reminder_count"]}.pdf'
                write_invoice_pdf(inv,"reminder",out,reminder_level=lvl,due_text=f"Bitte begleichen Sie den Betrag bis zum {due}.",user=self.current_user.get("username","") if self.current_user else "")
                inv.setdefault("reminder_pdfs",[]).append(str(out)); save_data()
                offer_pdf("Zahlungserinnerung",f'Zahlungserinnerung für Rechnung {inv.get("number","")} wurde erstellt und dokumentiert.\n\nOffener Betrag: {float(inv.get("amount",0)):.2f} €\nZahlungsziel: {due}\n\nDie ursprüngliche Rechnung wurde nicht verändert.',out)
            except Exception as e:
                QMessageBox.warning(self,"Zahlungserinnerung","Die Erinnerung wurde dokumentiert, die PDF konnte aber nicht erstellt werden:\n\n"+str(e)[:500])
        remind.clicked.connect(payment_reminder); h.addWidget(remind)
        details=QPushButton("Details"); details.setMinimumHeight(42)
        def invoice_details():
            _,inv=selected_invoice()
            if not inv:return
            items=inv.get("items",[])
            lines="\n".join(f'{x.get("date","")}  {x.get("start","")}–{x.get("end","")}  {x.get("minutes",0)} Min.  {x.get("type","")}  {float(x.get("amount",0)):.2f} €' for x in items) or "Keine Einzelpositionen gespeichert."
            QMessageBox.information(self,"Rechnungsdetails",f'Rechnung: {inv.get("number","")}\nKlient: {inv.get("client","")}\nStatus: {inv.get("status","offen")}\nZahlungsdatum: {inv.get("paid_date","") or "–"}\nLetzte Zahlungserinnerung: {inv.get("reminder_date","") or "–"}\nMahnstufe: {inv.get("reminder_count",0)}\nBetrag: {float(inv.get("amount",0)):.2f} €\n\n{lines}')
        details.clicked.connect(invoice_details); t.cellDoubleClicked.connect(lambda *_: invoice_details()); h.addWidget(details); v.addLayout(h)
        return w
    def offer_key_protection(self,force=False):
        """Bietet an, den Datenschlüssel an das Windows-Konto zu binden. Vorher wird ein Wiederherstellungsschlüssel gesichert."""
        if os.name!="nt":
            if force: QMessageBox.information(self,"Schlüsselschutz","Der Schlüsselschutz ist nur unter Windows verfügbar.")
            return
        if key_is_protected():
            if force: QMessageBox.information(self,"Schlüsselschutz","Der Datenschlüssel ist bereits an Ihr Windows-Konto gebunden.")
            return
        if not KEYFILE.exists(): return
        if not force and get_setting("key_protect_declined","0")=="1": return
        if not self.is_admin():
            if force: QMessageBox.warning(self,"Keine Berechtigung","Nur Administratoren können den Schlüsselschutz einrichten.")
            return
        box=QMessageBox(self); box.setIcon(QMessageBox.Question); box.setWindowTitle("Datenschlüssel schützen")
        box.setText("Der Schlüssel zu Ihren Patientendaten liegt derzeit als normale Datei neben den Daten.")
        box.setInformativeText("Empfohlen: an Ihr Windows-Benutzerkonto binden. Dann nützt eine kopierte Datenbank niemandem etwas.\n\nDazu speichern Sie zuerst einen Wiederherstellungsschlüssel auf einem USB-Stick. Ohne ihn sind die Daten nach einer Windows-Neuinstallation oder auf einem anderen PC nicht mehr lesbar.")
        yes=box.addButton("Jetzt einrichten",QMessageBox.AcceptRole); later=box.addButton("Später",QMessageBox.RejectRole); never=box.addButton("Nicht mehr fragen",QMessageBox.DestructiveRole); box.exec()
        if box.clickedButton()==never: set_setting("key_protect_declined","1"); return
        if box.clickedButton()!=yes: return
        path,_=QFileDialog.getSaveFileName(self,"Wiederherstellungsschlüssel speichern (am besten auf USB-Stick)",str(Path.home()/"Wiederherstellungsschluessel_PraxisPro.key"),"Schlüssel (*.key)")
        if not path: return
        try:
            Path(path).write_bytes(encryption_key())
            if Path(path).read_bytes()!=encryption_key(): raise OSError("Prüfung der gespeicherten Datei fehlgeschlagen")
        except Exception as e: return QMessageBox.warning(self,"Schlüsselschutz","Der Wiederherstellungsschlüssel konnte nicht gespeichert werden. Es wurde nichts verändert.\n\n"+str(e)[:300])
        ok,msg=protect_key_file(); audit("KEY_PROTECT" if ok else "KEY_PROTECT_FAILED",msg[:300],self.current_user.get("username","") if self.current_user else "")
        (QMessageBox.information if ok else QMessageBox.warning)(self,"Schlüsselschutz",msg+("\n\nBitte bewahren Sie den Wiederherstellungsschlüssel sicher und getrennt auf." if ok else ""))
    def glossary_ui(self):
        import glossar_data
        entries=glossar_data.alle(); schulen=glossar_data.SCHULEN
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(24,22,24,22); v.setSpacing(10)
        title=QLabel("Glossar der Störungsbilder"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("ICD-10-GM · ICD-11 · DSM-5-TR – fachlich und patientenverständlich, mit Herangehensweisen nach Therapieschulen. Orientierungshilfe, keine Diagnosestellung."); sub.setObjectName("pageSub"); sub.setWordWrap(True); v.addWidget(sub)
        bar=QWidget(); fl=FlowLayout(bar,8,8); fl.setContentsMargins(0,0,0,0)
        search=QLineEdit(); search.setPlaceholderText("Suchen: Name, Symptom, Code (z. B. F41, 6B00) …"); search.setClearButtonEnabled(True); search.setMinimumWidth(300); search.setMinimumHeight(38)
        grp=QComboBox(); grp.addItems(["Alle Bereiche"]+sorted({e["gruppe"] for e in entries})); grp.setMinimumHeight(38)
        mode=QComboBox(); mode.addItems(["Fachlich + einfach","Nur fachlich","Nur patientenverständlich"]); mode.setMinimumHeight(38)
        school=QComboBox(); school.addItems(["Alle Therapieschulen"]+[schulen[k] for k in schulen]); school.setMinimumHeight(38)
        for x in (search,grp,mode,school): fl.addWidget(x)
        v.addWidget(bar)
        split=QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)
        lst=QListWidget(); lst.setMinimumWidth(200); lst.setAlternatingRowColors(True)
        view=QTextBrowser(); view.setOpenExternalLinks(False); view.setMinimumHeight(240)
        split.addWidget(lst); split.addWidget(view); split.setStretchFactor(0,1); split.setStretchFactor(1,3); split.setMinimumHeight(420)
        v.addWidget(split,1)
        btnbar=QWidget(); bl=FlowLayout(btnbar,8,8); bl.setContentsMargins(0,0,0,0)
        b_note=QPushButton("In Sitzungsnotiz übernehmen"); b_copy=QPushButton("Text kopieren"); b_pdf=QPushButton("Patientenblatt als PDF")
        for b in (b_note,b_copy,b_pdf): b.setMinimumHeight(40); bl.addWidget(b)
        v.addWidget(btnbar)
        def esc(t): return (t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        def sel_schools(): 
            i=school.currentIndex(); keys=list(schulen)
            return keys if i<=0 else [keys[i-1]]
        def html_for(e,m,sc):
            h=["<h2 style='margin-bottom:2px'>"+esc(e["name"])+"</h2><p style='color:#555'>"+esc(e["gruppe"])+"</p>"]
            h.append("<table cellpadding='4' style='border:1px solid #c8d4e0'><tr><td><b>ICD-10-GM</b></td><td>"+esc(e["icd10"])+"</td></tr><tr><td><b>ICD-11</b></td><td>"+esc(e["icd11"])+"</td></tr><tr><td><b>DSM-5-TR</b></td><td>"+esc(e["dsm5"])+"</td></tr></table>")
            if m in (0,1):
                h.append("<h3>Fachliche Beschreibung</h3><p>"+esc(e["kurz"])+"</p><h3>Symptome</h3><ul>"+"".join("<li>"+esc(x)+"</li>" for x in e["symptome"])+"</ul><h3>Ätiologie (fachlich)</h3><p>"+esc(e["etio"])+"</p>")
            if m in (0,2):
                h.append("<div style='background:#eaf6f3;padding:8px;border-radius:6px'><h3>Einfach erklärt</h3><p>"+esc(e["einfach"])+"</p><p><b>Wie entsteht das?</b> "+esc(e["etio_einfach"])+"</p></div>")
            if m in (0,1):
                h.append("<h3>Herangehensweisen nach Therapieschulen</h3><ul>"+"".join("<li><b>"+esc(schulen[k])+":</b> "+esc(e["therapie"][k])+"</li>" for k in sc)+"</ul>")
                if e["hinweis"]: h.append("<p style='background:#fff6e0;padding:6px'><b>Hinweis:</b> "+esc(e["hinweis"])+"</p>")
            h.append("<p style='color:#777'><i>Orientierungshilfe, keine Diagnose und keine Behandlungsanweisung. Maßgeblich sind Leitlinien, eigene Diagnostik und ärztliche Abklärung.</i></p>")
            return "".join(h)
        def text_for(e,m,sc):
            t=[e["name"]+"  ("+e["icd10"]+" | ICD-11: "+e["icd11"]+" | DSM-5-TR: "+e["dsm5"]+")"]
            if m in (0,1): t+=["",e["kurz"],"Symptome:"]+["• "+x for x in e["symptome"]]+["Ätiologie: "+e["etio"]]
            if m in (0,2): t+=["","Einfach erklärt: "+e["einfach"],"Wie entsteht das? "+e["etio_einfach"]]
            if m in (0,1): t+=["","Herangehensweisen:"]+["• "+schulen[k]+": "+e["therapie"][k] for k in sc]
            return "\n".join(t)
        def current_entry():
            it=lst.currentItem(); return it.data(Qt.UserRole) if it else None
        def show_entry(*_):
            e=current_entry()
            if e is None: view.setHtml("<p>Bitte links ein Störungsbild wählen.</p>"); return
            view.setHtml(html_for(e,mode.currentIndex(),sel_schools()))
        def fill(*_):
            q=search.text().lower().strip(); g=grp.currentText(); keep=current_entry()["name"] if current_entry() else None
            lst.blockSignals(True); lst.clear(); sel=None
            for e in entries:
                if g!="Alle Bereiche" and e["gruppe"]!=g: continue
                hay=(e["name"]+" "+e["icd10"]+" "+e["icd11"]+" "+e["dsm5"]+" "+e["kurz"]+" "+" ".join(e["symptome"])+" "+e["einfach"]).lower()
                if q and q not in hay: continue
                it=QListWidgetItem(e["name"]+"\n"+e["icd10"].split(",")[0].split(" (")[0]); it.setData(Qt.UserRole,e); it.setToolTip(e["gruppe"]); lst.addItem(it)
                if e["name"]==keep: sel=it
            lst.blockSignals(False)
            if lst.count(): lst.setCurrentItem(sel or lst.item(0))
            show_entry()
        lst.currentItemChanged.connect(show_entry); search.textChanged.connect(fill); grp.currentIndexChanged.connect(fill); mode.currentIndexChanged.connect(show_entry); school.currentIndexChanged.connect(show_entry)
        def to_note():
            e=current_entry()
            if e is None: return QMessageBox.information(self,"Glossar","Bitte zuerst ein Störungsbild wählen.")
            if not hasattr(self,"notes"): return QMessageBox.information(self,"Sitzungsnotiz","Die Sitzungsnotiz ist nicht verfügbar.")
            block="Glossar – "+text_for(e,1,sel_schools())
            existing=self.notes.toPlainText().rstrip(); self.notes.setPlainText((existing+"\n\n" if existing else "")+block)
            QMessageBox.information(self,"Sitzungsnotiz","Der Glossar-Eintrag (fachliche Sicht) wurde in die Sitzungsnotiz übernommen.")
        def copy_text():
            e=current_entry()
            if e is not None: QApplication.clipboard().setText(text_for(e,mode.currentIndex(),sel_schools())); QMessageBox.information(self,"Glossar","Text in die Zwischenablage kopiert.")
        def patient_pdf():
            e=current_entry()
            if e is None: return QMessageBox.information(self,"Glossar","Bitte zuerst ein Störungsbild wählen.")
            f,_=QFileDialog.getSaveFileName(self,"Patientenblatt speichern",str(Path.home()/("Patientenblatt_"+re.sub(r"[^A-Za-z0-9]+","_",e["name"])[:40]+".pdf")),"PDF (*.pdf)")
            if not f: return
            from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize
            doc=QTextDocument(); doc.setHtml("<h1>"+esc(e["name"])+"</h1><h3>Einfach erklärt</h3><p>"+esc(e["einfach"])+"</p><h3>Wie entsteht das?</h3><p>"+esc(e["etio_einfach"])+"</p><h3>Typische Anzeichen</h3><ul>"+"".join("<li>"+esc(x)+"</li>" for x in e["symptome"][:6])+"</ul><p><i>Dieses Blatt ersetzt keine ärztliche oder psychotherapeutische Diagnose. "+esc(get_setting("practice_name",""))+"</i></p>")
            wr=QPdfWriter(f); wr.setPageSize(QPageSize(QPageSize.A4)); doc.print_(wr)
            QMessageBox.information(self,"Glossar","Patientenblatt gespeichert:\n"+f)
        b_note.clicked.connect(to_note); b_copy.clicked.connect(copy_text); b_pdf.clicked.connect(patient_pdf)
        def orient(): split.setOrientation(Qt.Vertical if w.width()<860 else Qt.Horizontal)
        class _Ev(QObject):
            def eventFilter(s_,o,ev):
                if ev.type()==QEvent.Resize: orient()
                return False
        w._ev=_Ev(w); w.installEventFilter(w._ev); orient(); fill()
        return w
    def handwriting_archive(self,last,first):
        """Alle gespeicherten Handschriften eines Klienten (Sitzungen + Freihand-Notizen): ansehen, in Text umwandeln, speichern."""
        items=[]
        for ss in DB["sessions"]:
            if ss.get("last")==last and ss.get("first")==first and ss.get("ink_file") and Path(ss["ink_file"]).exists():
                items.append({"path":Path(ss["ink_file"]),"session":ss,"label":f'{ss.get("date","")} {ss.get("start","")}  ·  Sitzung ({ss.get("type","")})',"key":ss.get("date","")+" "+ss.get("start","")})
        known={str(i["path"]) for i in items}
        try:
            folder=client_folder(last,first)/"Sitzungen"
            for f in sorted(folder.glob("Freihand_*.png.enc")):
                if str(f) in known: continue
                m=re.match(r"Freihand_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})",f.name)
                lab=f"{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}:{m.group(5)}  ·  Freihand-Notiz" if m else f.name
                items.append({"path":f,"session":None,"label":lab,"key":(m.group(1)+"-"+m.group(2)+"-"+m.group(3)+" "+m.group(4)+":"+m.group(5)) if m else f.name})
        except Exception: pass
        if not items: return QMessageBox.information(self,"Handschrift","Für diesen Klienten wurde keine gespeicherte Handschrift gefunden.")
        items.sort(key=lambda x:x["key"],reverse=True)
        def sidecar(it): return Path(str(it["path"])+".txt.enc")
        def load_text(it):
            if it.get("text") is not None: return it["text"]
            txt=""
            if it["session"] is not None: txt=it["session"].get("ocr_text","") or ""
            try:
                if not txt and sidecar(it).exists(): txt=decrypt_text(sidecar(it).read_text(encoding="utf-8"))
            except Exception: txt=""
            it["text"]=txt; return txt
        dlg=QDialog(self); dlg.setWindowTitle(f"Handschriften – {last}, {first}"); v=QVBoxLayout(dlg)
        _ag=QApplication.primaryScreen().availableGeometry(); dlg.resize(min(1000,int(_ag.width()*0.92)),min(760,int(_ag.height()*0.82))); dlg.move(_ag.x()+max(0,(_ag.width()-dlg.width())//2),_ag.y()+max(0,(_ag.height()-dlg.height())//3))
        info=QLabel("Links eine Handschrift wählen, dann „Handschrift → Text“. Der Text ist bearbeitbar; die Handschrift bleibt immer erhalten."); info.setWordWrap(True); v.addWidget(info)
        langrow=QHBoxLayout(); langrow.addWidget(QLabel("Sprache der Handschrift:")); langbox=QComboBox(); langbox.addItems(list(OCR_LANGS.keys())); langbox.setCurrentText(get_setting("ocr_lang","Deutsch")); langbox.setMinimumHeight(34); langrow.addWidget(langbox); langrow.addStretch(); v.addLayout(langrow)
        split=QSplitter(Qt.Horizontal); lst=QListWidget(); lst.setMinimumWidth(300)
        right=QWidget(); rv=QVBoxLayout(right); rv.setContentsMargins(0,0,0,0)
        lab=QLabel("Bitte links eine Handschrift wählen."); lab.setAlignment(Qt.AlignCenter); sc=QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(lab); sc.setMinimumHeight(200); rv.addWidget(sc,3)
        txt=QTextEdit(); txt.setPlaceholderText("Hier erscheint der erkannte Text (bearbeitbar)."); rv.addWidget(txt,2)
        split.addWidget(lst); split.addWidget(right); split.setStretchFactor(1,3); self.responsive_split(split,760); v.addWidget(split,1)
        for idx,it in enumerate(items):
            li=QListWidgetItem(("✓ " if load_text(it) else "")+it["label"]); li.setData(Qt.UserRole,idx); lst.addItem(li)
        def cur():
            q=lst.currentItem(); return items[q.data(Qt.UserRole)] if q else None
        def image_of(it):
            raw=decrypt_file_bytes(it["path"]); im=QImage(); im.loadFromData(raw); return im
        def show(*_):
            it=cur()
            if not it: return
            im=image_of(it)
            if im.isNull(): lab.setText("Die Handschrift konnte nicht gelesen werden."); txt.setPlainText(""); return
            pm=QPixmap.fromImage(im); lab.setPixmap(pm.scaledToWidth(min(860,pm.width()),Qt.SmoothTransformation)); txt.setPlainText(load_text(it))
        lst.currentItemChanged.connect(show)
        def convert_item(it):
            im=image_of(it)
            if im.isNull(): return "","Bild nicht lesbar"
            strokes=it["session"].get("ink_strokes") if it["session"] is not None else None
            if strokes is None:
                try: strokes=json.loads(decrypt_text(Path(str(it["path"])+".strokes.enc").read_text(encoding="utf-8")))
                except Exception: strokes=None
            return recognize_saved_handwriting(im,OCR_LANGS.get(langbox.currentText(),"de-DE"),strokes)
        def persist(it,text):
            it["text"]=text.strip()
            user=self.current_user.get("username","") if self.current_user else ""
            if it["session"] is not None:
                ss=it["session"]; ss["ocr_text"]=it["text"]; ss["corrected_at"]=datetime.now().isoformat(timespec="seconds")
                try:
                    ocrf=Path(str(it["path"])).parent/(ss.get("date","")+"_"+ss.get("id","Sitzung")+"_OCR.txt.enc"); ocrf.write_text(encrypt_text(it["text"]),encoding="utf-8"); ss["ocr_file"]=str(ocrf)
                except Exception: pass
                save_data()
            else:
                sidecar(it).write_text(encrypt_text(it["text"]),encoding="utf-8")
            audit("INK_TEXT_SAVED",f"Handschrift als Text gespeichert: {last}, {first}",user)
        def do_convert():
            it=cur()
            if not it: return QMessageBox.information(dlg,"Handschrift","Bitte zuerst eine Handschrift wählen.")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try: text,err=convert_item(it)
            finally: QApplication.restoreOverrideCursor()
            if err in ("LEER","KEIN_TEXT") or (not err and not text.strip()): return QMessageBox.information(dlg,"Handschrift → Text","Es wurde keine Schrift erkannt.\n\nHinweis: "+(OCR_LAST_INK_NOTE or "Bitte die richtige Sprache oben wählen. Für Türkisch muss in Windows das Türkische Handschrift-Paket installiert sein (Einstellungen → Zeit & Sprache → Sprache & Region → Türkisch → Sprachoptionen → Handschrift)."))
            if err: return QMessageBox.warning(dlg,"Handschrift → Text","Die Handschrift konnte nicht erkannt werden.\n\n"+err)
            txt.setPlainText(text.strip()); persist(it,text.strip()); q=lst.currentItem(); q.setText("✓ "+it["label"])
            QMessageBox.information(dlg,"Handschrift → Text","Text erkannt und gespeichert. Bitte prüfen, bei Bedarf korrigieren und erneut mit „Text speichern“ sichern.")
        def do_save():
            it=cur()
            if not it: return
            persist(it,txt.toPlainText()); q=lst.currentItem(); q.setText(("✓ " if it["text"] else "")+it["label"]); QMessageBox.information(dlg,"Gespeichert","Der Text wurde gespeichert.")
        def do_all():
            todo=[it for it in items if not load_text(it)]
            if not todo: return QMessageBox.information(dlg,"Alle umwandeln","Alle Handschriften haben bereits einen Text.")
            if QMessageBox.question(dlg,"Alle umwandeln",f"{len(todo)} Handschrift(en) ohne Text jetzt automatisch umwandeln und speichern? Die Handschrift bleibt erhalten; den Text können Sie danach einzeln prüfen.")!=QMessageBox.Yes: return
            ok=0; QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for it in todo:
                    text,err=convert_item(it); QApplication.processEvents()
                    if not err and text.strip(): persist(it,text); ok+=1
            finally: QApplication.restoreOverrideCursor()
            for i in range(lst.count()):
                q=lst.item(i); it=items[q.data(Qt.UserRole)]; q.setText(("✓ " if it.get("text") else "")+it["label"])
            show(); QMessageBox.information(dlg,"Alle umwandeln",f"{ok} von {len(todo)} Handschriften wurden in Text umgewandelt.")
        def to_note():
            if not txt.toPlainText().strip(): return QMessageBox.information(dlg,"Sitzungsnotiz","Es gibt noch keinen Text.")
            if not hasattr(self,"notes"): return
            ex=self.notes.toPlainText().rstrip(); self.notes.setPlainText((ex+"\n\n" if ex else "")+txt.toPlainText().strip()); QMessageBox.information(dlg,"Sitzungsnotiz","Der Text wurde in die aktuelle Sitzungsnotiz übernommen.")
        bar=QWidget(); bl=FlowLayout(bar,8,8); bl.setContentsMargins(0,0,0,0)
        b1=QPushButton("⌨ Handschrift → Text"); b2=QPushButton("💾 Text speichern"); b3=QPushButton("⌨ Alle ohne Text umwandeln"); b4=QPushButton("In aktuelle Sitzungsnotiz übernehmen"); b5=QPushButton("Schließen")
        for b_,fn in ((b1,do_convert),(b2,do_save),(b3,do_all),(b4,to_note),(b5,dlg.accept)): b_.setMinimumHeight(40); b_.clicked.connect(fn); bl.addWidget(b_)
        v.insertWidget(2,bar); lst.setCurrentRow(0); dlg.exec()
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
        run_uninstall=self.start_uninstall
        uninstall.clicked.connect(run_uninstall); iv.addWidget(uninstall); iv.addStretch(); tabs.addTab(info,"Info & Programmverwaltung")
        return w

    def settings_ui(self):
        w=QWidget(); outer=QVBoxLayout(w); outer.setContentsMargins(0,0,0,0); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded); body=QWidget(); body.setMinimumWidth(0); v=QVBoxLayout(body); v.setContentsMargins(18,12,18,18); v.setSpacing(9)
        title=QLabel("Praxiseinstellungen"); title.setObjectName("pageTitle"); v.addWidget(title)
        sub=QLabel("Praxisdaten, Abrechnung, Honorare und Benutzer übersichtlich verwalten."); sub.setObjectName("pageSub"); v.addWidget(sub)
        tabs=QTabWidget(); tabs.setDocumentMode(True)
        tabs.setStyleSheet("QTabBar::tab { min-width: 105px; padding-left: 10px; padding-right: 10px; }")
        # Jede Registerkarte bekommt eine eigene Scrollfläche: Inhalte werden nie mehr zusammengedrückt,
        # sondern bei kleinen Bildschirmen / hoher Windows-Skalierung einfach scrollbar.
        _orig_addtab=tabs.addTab
        def _addtab_scroll(page,label):
            sa=QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sa.setWidget(page)
            return _orig_addtab(sa,label)
        tabs.addTab=_addtab_scroll
        v.addWidget(tabs,1); scroll.setWidget(body); outer.addWidget(scroll)
        general=QWidget(); gv=QVBoxLayout(general); gv.setContentsMargins(16,14,16,20); gv.setSpacing(10)
        form=QFormLayout(); form.setHorizontalSpacing(18); form.setVerticalSpacing(10); form.setLabelAlignment(Qt.AlignLeft|Qt.AlignTop)
        # Praxisdaten bewusst kompakt halten: jede Zeile bekommt feste Höhe und Abstand.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFormAlignment(Qt.AlignTop)
        fields={}
        labels=[("practice_name","Praxisname"),("owner_name","Inhaber / Praxisleitung"),("qualifications","Qualifikationen"),("practice_subtitle","Zusatz / Spezialisierung"),("address","Anschrift"),("phone","Mobil / Telefon"),("landline","Festnetz"),("fax","Fax"),("email","E-Mail"),("website","Website"),("manufacturer","Herstellername"),("copyright","Copyright")]
        def section(text):
            lab=QLabel(text); lab.setObjectName("sectionTitle"); lab.setContentsMargins(0,10,0,2); form.addRow(lab)
        section("Praxis und Inhaber")
        for key,label in labels:
            if key=="address": section("Anschrift und Kontakt")
            if key=="manufacturer": section("Programmangaben")
            ed=QLineEdit(get_setting(key)); ed.setMinimumHeight(max(36,ed.fontMetrics().height()+22)); ed.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum); fields[key]=ed; form.addRow(label,ed)
        section("Logo und Rechnungskopf")
        # Rechnungskopf: eine sichtbare Bildflaeche mit dem mitgelieferten Praxislogo als Standard.
        custom_logo_value = (get_setting("logo_path", "") or "").strip()
        logo=QLineEdit(custom_logo_value)
        logo.setMinimumHeight(max(36,logo.fontMetrics().height()+22)); logo.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum)
        logo.setPlaceholderText("Standardlogo (mitgeliefert)")
        fields["logo_path"]=logo

        logo_preview=QLabel()
        logo_preview.setFixedSize(300,110)
        logo_preview.setAlignment(Qt.AlignCenter)
        logo_preview.setStyleSheet("QLabel { border: 1px solid #b8b8b8; background: white; padding: 6px; }")

        def refresh_logo_preview():
            p=effective_practice_logo()
            if p and Path(p).is_file():
                px=QPixmap(str(p))
                if not px.isNull():
                    logo_preview.setPixmap(px.scaled(286,96,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                    logo_preview.setText("")
                    return
            logo_preview.setPixmap(QPixmap())
            logo_preview.setText("Standardlogo nicht gefunden")

        choose=QPushButton("Logo ersetzen …"); choose.setMinimumHeight(max(36,logo.fontMetrics().height()+22))
        reset_logo=QPushButton("Standardlogo"); reset_logo.setMinimumHeight(max(36,logo.fontMetrics().height()+22))
        def pick_logo():
            p,_=QFileDialog.getOpenFileName(self,"Praxislogo auswählen","","Bilder (*.png *.jpg *.jpeg)")
            if p:
                logo.setText(p)
                set_setting("logo_path",p)
                refresh_logo_preview()
        def use_default_logo():
            logo.clear()
            set_setting("logo_path","")
            refresh_logo_preview()
        choose.clicked.connect(pick_logo)
        reset_logo.clicked.connect(use_default_logo)
        lr=QHBoxLayout(); lr.addWidget(logo,1); lr.addWidget(choose); lr.addWidget(reset_logo)
        form.addRow("Praxislogo",lr)
        form.addRow("Bildfläche Rechnungskopf",logo_preview)

        logo_zone=QComboBox()
        logo_zone.addItems(["Links","Mitte","Rechts"])
        logo_zone.setCurrentText(get_setting("invoice_header_logo_zone","Links") or "Links")
        form.addRow("Bildposition im Rechnungskopf",logo_zone)

        logo_w=QDoubleSpinBox(); logo_w.setRange(15,120); logo_w.setValue(float(get_setting("logo_width_mm","72"))); logo_w.setSuffix(" mm")
        logo_h=QDoubleSpinBox(); logo_h.setRange(8,45); logo_h.setValue(float(get_setting("logo_height_mm","22"))); logo_h.setSuffix(" mm")
        for sp in (logo_w,logo_h): sp.setMinimumWidth(130)
        size_row=QHBoxLayout(); size_row.addWidget(QLabel("Breite")); size_row.addWidget(logo_w); size_row.addWidget(QLabel("Höhe")); size_row.addWidget(logo_h); size_row.addStretch()
        form.addRow("Bildgröße",size_row)

        # Standardposition: links oben. X/Y bleiben intern fuer bestehende Installationen erhalten.
        logo_x=QDoubleSpinBox(); logo_x.setRange(0,180); logo_x.setValue(float(get_setting("logo_x_mm","18"))); logo_x.setSuffix(" mm"); logo_x.setVisible(False)
        logo_y=QDoubleSpinBox(); logo_y.setRange(0,80); logo_y.setValue(float(get_setting("logo_y_mm","7"))); logo_y.setSuffix(" mm"); logo_y.setVisible(False)
        header_middle=QComboBox(); header_middle.addItems(["Leer"]); header_middle.setCurrentText("Leer"); header_middle.setVisible(False)
        header_right=QComboBox(); header_right.addItems(["Leer"]); header_right.setCurrentText("Leer"); header_right.setVisible(False)
        refresh_logo_preview()
        gv.addLayout(form)
        appearance=QFrame(); appearance.setObjectName("formCard"); appearance.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed); appearance.setMinimumWidth(0)
        # Darstellungsoptionen kompakt in einer Zeile: sie dürfen die Praxisdaten nicht überdecken.
        ar=QHBoxLayout(appearance); ar.setContentsMargins(14,10,14,10); ar.setSpacing(10)
        theme=QComboBox(); theme.addItems(list(THEMES.keys())); theme.setCurrentText(get_setting("ui_theme","Salbei")); theme.setMinimumWidth(180); theme.setMaximumWidth(260)
        fontsize=QSpinBox(); fontsize.setRange(12,20); fontsize.setValue(max(12,int(get_setting("ui_font_size","14") or 14))); fontsize.setSuffix(" px"); fontsize.setMinimumWidth(110)
        density=QComboBox(); density.addItems(["Kompakt","Normal","Groß"]); density.setCurrentText(get_setting("ui_density","Normal")); density.setMinimumWidth(140); density.setMaximumWidth(200)
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
        for key,label in [("tax_number","Steuernummer"),("iban","IBAN"),("bic","BIC"),("paypal","PayPal (E-Mail)"),("paypal_me","PayPal.Me-Name oder -Link (für QR-Code)")]:
            ed=QLineEdit(get_setting(key)); ed.setMinimumHeight(32); fields[key]=ed; bf.addRow(label,ed)
        lockrow=QHBoxLayout(); lock=QSpinBox(); lock.setRange(0,120); lock.setSpecialValueText("Aus"); lock.setValue(int(get_setting("auto_lock_minutes","0") or 0)); lock.setSuffix(" Minuten"); lock.setToolTip("0 = aus. Während einer laufenden Sitzung wird nie automatisch gesperrt."); lockrow.addWidget(lock); pinbtn=QPushButton("PIN ändern … (Standard: 0000)"); pinbtn.setMinimumHeight(34); pinbtn.clicked.connect(self.set_pin_flow); lockrow.addWidget(pinbtn); lockrow.addStretch(); bf.addRow("Sperre (automatisch / PIN)",lockrow)
        travel=QDoubleSpinBox(); travel.setRange(0,500); travel.setDecimals(2); travel.setValue(float(get_setting("travel_surcharge","25"))); travel.setSuffix(" €"); bf.addRow("Hausbesuch Anfahrt",travel)
        bv.addLayout(bf); bv.addWidget(self.backup_box()); save2=QPushButton("Abrechnung & Sicherheit speichern"); save2.setMinimumHeight(38); save2.clicked.connect(save_settings); bv.addWidget(save2); bv.addStretch(); tabs.addTab(billing,"Abrechnung & Bank")
        ratespage=QWidget(); rv=QVBoxLayout(ratespage); rv.setContentsMargins(12,10,12,12); rv.setSpacing(7)
        rates=QLabel("Honorarsätze"); rates.setObjectName("sectionTitle"); rv.addWidget(rates)
        rt=QTableWidget(0,5); rt.setMinimumHeight(300); rt.setHorizontalHeaderLabels(["Leistung","Min.","Regulär €","Ermäßigt €","Abrechnung"]); rt.verticalHeader().setDefaultSectionSize(28); rt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
        ut=QTableWidget(0,4); ut.setMinimumHeight(260); ut.setHorizontalHeaderLabels(["Benutzername","Anzeigename","Rolle","Aktiv"]); ut.verticalHeader().setDefaultSectionSize(28); ut.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
        """Startseite. Wird bei jedem Aufruf neu aufgebaut (refresh_dashboard), damit Zahlen und Termine aktuell sind."""
        DB.setdefault("todos",[])
        sa=QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dash_scroll=sa; self.refresh_dashboard(); return sa

    def dashboard_tasks(self):
        """Automatische Aufgaben: (Symbol, Text, Seite oder None). Wird auch im Test geprüft."""
        tasks=[]; today=date.today(); y=today.year
        overdue=[]
        for inv in DB["invoices"]:
            if inv.get("status","offen")!="offen": continue
            try: days=(today-datetime.strptime(inv.get("date",""),"%Y-%m-%d").date()).days
            except Exception: continue
            if days>14: overdue.append(inv)
        if overdue: tasks.append(("€",f"{len(overdue)} Rechnung(en) seit über 14 Tagen offen – Zahlungserinnerung prüfen",8))
        unbilled=[s for s in DB["sessions"] if not s.get("billed")]
        if unbilled: tasks.append(("▤",f"{len(unbilled)} Sitzung(en) noch nicht abgerechnet",7))
        con=sqlite3.connect(DBFILE)
        past=con.execute("SELECT COUNT(*) FROM appointments WHERE status='geplant' AND appointment_date<? AND appointment_date>=?",(today.isoformat(),(today-timedelta(days=30)).isoformat())).fetchone()[0]
        con.close()
        if past: tasks.append(("▦",f"{past} vergangene(r) Termin(e) noch auf „geplant“ – Status nachtragen (erschienen / abgesagt / ausgefallen)",6))
        # Formulare (Behandlungsvertrag, Einwilligung) sind freiwillig – daher keine Erinnerung an fehlende Unterlagen.
        for c in DB["clients"]:
            st=client_session_stats(c)
            if st["quota"] and st["left"] is not None and st["left"]<=2:
                tasks.append(("◔",f"Kontingent {c.get('first','')} {c.get('last','')}: {st['done']} von {st['quota']} Sitzungen"+(" – ausgeschöpft" if st["left"]<=0 else f" – nur noch {st['left']} frei"),14))
        waiting=[e for e in DB.get("waitlist",[]) if e.get("status") not in ("übernommen","abgesagt")]
        urgent=[e for e in waiting if e.get("urgency")=="dringend"]
        if waiting: tasks.append(("⏳",f"Warteliste: {len(waiting)} offen"+(f", davon {len(urgent)} dringend" if urgent else ""),13))
        return tasks

    def waitlist_gaps(self,days_ahead=14):
        """Abgesagte/ausgefallene Termine der nächsten Tage + passende Wartelisteneinträge (Wochentag/Tageszeit)."""
        today=date.today(); wd=["Mo","Di","Mi","Do","Fr","Sa","So"]
        con=sqlite3.connect(DBFILE)
        rows=con.execute("SELECT appointment_date,start_time,minutes FROM appointments WHERE status IN ('abgesagt','ausgefallen') AND appointment_date>=? AND appointment_date<=? ORDER BY appointment_date,start_time",(today.isoformat(),(today+timedelta(days=days_ahead)).isoformat())).fetchall()
        out=[]
        for d,t,m in rows:
            # Lücke nur, wenn der Platz nicht schon neu vergeben ist
            start=QTime.fromString(t,"HH:mm"); end=start.addSecs(int(m)*60)
            taken=any(QTime.fromString(t2,"HH:mm")<end and QTime.fromString(t2,"HH:mm").addSecs(int(m2)*60)>start for t2,m2 in con.execute("SELECT start_time,minutes FROM appointments WHERE appointment_date=? AND status='geplant'",(d,)).fetchall())
            if taken: continue
            day=datetime.strptime(d,"%Y-%m-%d").date(); hour=int(t[:2]); part="vormittags" if hour<12 else ("nachmittags" if hour<17 else "abends")
            matches=[]
            for e in DB.get("waitlist",[]):
                if e.get("status") in ("übernommen","abgesagt"): continue
                av=set(e.get("availability",[])); days_=av & set(wd); parts=av & {"vormittags","nachmittags","abends"}
                if (not days_ or wd[day.weekday()] in days_) and (not parts or part in parts): matches.append(e)
            if matches:
                matches.sort(key=lambda e:({"dringend":0,"hoch":1}.get(e.get("urgency"),2),e.get("created","")))
                out.append((f"{wd[day.weekday()]} {day.strftime('%d.%m.')} {t} Uhr",matches))
        con.close()
        return out

    def refresh_dashboard(self):
        if not hasattr(self,"dash_scroll"): return
        w=QWidget(); v=QVBoxLayout(w); v.setContentsMargins(18,14,18,14); v.setSpacing(12)
        now=datetime.now(); today=date.today(); y=str(now.year)
        hello="Guten Morgen" if now.hour<11 else ("Guten Tag" if now.hour<18 else "Guten Abend")
        weekday=["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"][today.weekday()]
        title=QLabel(hello+"!"); title.setObjectName("pageTitle"); sub=QLabel(f"{weekday}, {today.strftime('%d.%m.%Y')}  ·  {get_setting('practice_name','Psychologische Privatpraxis')}"); sub.setObjectName("pageSub"); v.addWidget(title); v.addWidget(sub)
        eur=lambda x: f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X",".")

        # ---------------------------------------------------------------- Heute + Aufgaben nebeneinander
        row=QSplitter(); row.setChildrenCollapsible(False); self.responsive_split(row,900)
        todaycard=QFrame(); todaycard.setObjectName("formCard"); tv=QVBoxLayout(todaycard); tv.setContentsMargins(14,10,14,12)
        con=sqlite3.connect(DBFILE)
        appts=con.execute("SELECT a.id,a.start_time,a.minutes,a.appointment_type,a.status,c.first,c.last,a.couple_id FROM appointments a LEFT JOIN clients c ON c.id=a.client_id WHERE a.appointment_date=? ORDER BY a.start_time",(today.isoformat(),)).fetchall()
        nxt=con.execute("SELECT appointment_date,start_time FROM appointments WHERE appointment_date>? AND status='geplant' ORDER BY appointment_date,start_time LIMIT 1",(today.isoformat(),)).fetchone()
        con.close()
        tt=QLabel(f"Heute  ·  {len(appts)} Termin"+("" if len(appts)==1 else "e")); tt.setObjectName("sectionTitle"); tv.addWidget(tt)
        if appts:
            tbl=QTableWidget(len(appts),4); tbl.setHorizontalHeaderLabels(["Zeit","Klient / Paar","Art","Status"]); tbl.verticalHeader().setVisible(False)
            for col,mode in enumerate((QHeaderView.ResizeToContents,QHeaderView.Stretch,QHeaderView.ResizeToContents,QHeaderView.ResizeToContents)): tbl.horizontalHeader().setSectionResizeMode(col,mode)
            tbl.setSelectionBehavior(QTableWidget.SelectRows); tbl.setSelectionMode(QTableWidget.SingleSelection); tbl.setEditTriggers(QTableWidget.NoEditTriggers)
            nowt=now.strftime("%H:%M")
            for r,(aid,t,m,typ,status,first,last,couple) in enumerate(appts):   # Reihenfolge wie im SELECT
                name=((decrypt_text(first) if first else "")+" "+(decrypt_text(last) if last else "")).strip() or (f"Paarakte #{couple}" if couple else "–")
                end=(datetime.strptime(t,"%H:%M")+timedelta(minutes=int(m))).strftime("%H:%M")
                for j,val in enumerate((f"{t}–{end}",name,typ or "",status)):
                    it=QTableWidgetItem(val); it.setData(Qt.UserRole,aid)
                    if status in ("abgesagt","ausgefallen") or end<nowt: it.setForeground(QColor("#8a968f"))
                    if t<=nowt<end and status=="geplant": f_=it.font(); f_.setBold(True); it.setFont(f_)
                    tbl.setItem(r,j,it)
            tbl.setMaximumHeight(46+34*min(len(appts),8)); tv.addWidget(tbl)
            tb=QHBoxLayout(); go=QPushButton("▶ Sitzung zum gewählten Termin starten"); go.setMinimumHeight(36)
            def start_selected():
                r=tbl.currentRow()
                if r<0:
                    upcoming=[i for i,a in enumerate(appts) if a[4]=="geplant" and (datetime.strptime(a[1],"%H:%M")+timedelta(minutes=int(a[2]))).strftime("%H:%M")>=nowt]
                    if not upcoming: return QMessageBox.information(self,"Heute","Bitte einen Termin auswählen.")
                    r=upcoming[0]
                self.start_session_from_appointment(tbl.item(r,0).data(Qt.UserRole))
            go.clicked.connect(start_selected); tbl.cellDoubleClicked.connect(lambda *_: start_selected()); tb.addWidget(go); tb.addStretch(); tv.addLayout(tb)
        else:
            empty=QLabel("Heute sind keine Termine eingetragen."+(f"\nNächster Termin: {_de_date(nxt[0])} um {nxt[1]} Uhr." if nxt else "")); empty.setObjectName("pageSub"); tv.addWidget(empty)
        cal=QPushButton("▦ Kalender öffnen"); cal.setMinimumHeight(34); cal.clicked.connect(lambda: self.nav.setCurrentRow(6)); tv.addWidget(cal,0,Qt.AlignLeft); tv.addStretch()

        taskcard=QFrame(); taskcard.setObjectName("formCard"); kv=QVBoxLayout(taskcard); kv.setContentsMargins(14,10,14,12); kv.setSpacing(6)
        tasks=self.dashboard_tasks(); todos=[t_ for t_ in DB["todos"] if not t_.get("done")]
        kt=QLabel(f"Aufgaben & Erinnerungen  ·  {len(tasks)+len(todos)}"); kt.setObjectName("sectionTitle"); kv.addWidget(kt)
        if not tasks and not todos:
            ok=QLabel("✓ Alles erledigt – keine offenen Punkte."); ok.setObjectName("pageSub"); kv.addWidget(ok)
        for icon,text,page in tasks:
            # Jede Zeile als eigenes Widget: umbrochene Texte bekommen so die richtige Höhe und laufen nicht in Nachbarelemente.
            roww=QWidget(); line=QHBoxLayout(roww); line.setContentsMargins(0,2,0,2); line.setSpacing(10)
            lab=QLabel(f"{icon}  {text}"); lab.setWordWrap(True); lab.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.MinimumExpanding); line.addWidget(lab,1)
            if page is not None:
                b=QPushButton("Öffnen"); b.setFixedHeight(32); b.setSizePolicy(QSizePolicy.Fixed,QSizePolicy.Fixed); b.setStyleSheet("background:white;color:#2c3b33;border:1px solid #c5d0c9;padding:4px 14px"); b.clicked.connect(lambda _=False,p=page: self.nav.setCurrentRow(p)); line.addWidget(b,0,Qt.AlignVCenter)
            kv.addWidget(roww)
        if todos:
            sep=QLabel("Eigene Notizen"); sep.setStyleSheet("color:#6b7a72;font-weight:700;padding-top:6px"); kv.addWidget(sep)
        for t_ in todos:
            cb=QCheckBox(t_.get("text","")+(f"  (seit {_de_date(t_.get('created','')[:10])})" if t_.get("created") else ""))
            def done(_=False,item=t_):
                item["done"]=True; item["done_at"]=datetime.now().isoformat(timespec="seconds"); save_data(); QTimer.singleShot(0,self.refresh_dashboard)
            cb.toggled.connect(done); kv.addWidget(cb)
        kv.addSpacing(6); addrow=QHBoxLayout(); newtodo=QLineEdit(); newtodo.setPlaceholderText("Neue Erinnerung, z. B. Rückruf Frau M. wegen Termin"); addbtn=QPushButton("＋"); addbtn.setFixedWidth(44); addbtn.setMinimumHeight(32)
        def add_todo():
            txt=newtodo.text().strip()
            if not txt: return
            DB["todos"].append({"text":txt,"created":datetime.now().isoformat(timespec="seconds"),"done":False}); save_data(); QTimer.singleShot(0,self.refresh_dashboard)
        addbtn.clicked.connect(add_todo); newtodo.returnPressed.connect(add_todo); addrow.addWidget(newtodo,1); addrow.addWidget(addbtn); kv.addLayout(addrow); kv.addStretch()
        row.addWidget(todaycard); row.addWidget(taskcard); row.setStretchFactor(0,1); row.setStretchFactor(1,1); v.addWidget(row)

        # ---------------------------------------------------------------- Freie Lücken ↔ Warteliste
        gaps=self.waitlist_gaps()
        if gaps:
            gc=QFrame(); gc.setObjectName("formCard"); gv=QVBoxLayout(gc); gv.setContentsMargins(14,10,14,12)
            gt=QLabel("Frei gewordene Termine – passend aus der Warteliste"); gt.setObjectName("sectionTitle"); gv.addWidget(gt)
            for slot,matches in gaps[:5]:
                names=", ".join(e.get("name","")+(" (dringend)" if e.get("urgency")=="dringend" else "")+(f" · {e.get('phone')}" if e.get("phone") else "") for e in matches[:3])
                gv.addWidget(QLabel(f"⏳  {slot}:  {names}"+(" …" if len(matches)>3 else "")))
            wb=QPushButton("Warteliste öffnen"); wb.setMinimumHeight(32); wb.clicked.connect(lambda: self.nav.setCurrentRow(13)); gv.addWidget(wb,0,Qt.AlignLeft); v.addWidget(gc)

        # ---------------------------------------------------------------- Nicht abgeschlossene Sitzung
        if any((ROOT/n).exists() for n in ("Sitzung_Autosave.json.enc","Sitzung_Autosave.json")):
            dr=QFrame(); dr.setObjectName("formCard"); dh=QHBoxLayout(dr); dl=QLabel("Es gibt eine nicht abgeschlossene Sitzung (automatisch gespeichert)."); dl.setWordWrap(True); dh.addWidget(dl,1)
            b_res=QPushButton("Wiederherstellen"); b_dis=QPushButton("Verwerfen")
            for b_ in (b_res,b_dis): b_.setMinimumHeight(40); dh.addWidget(b_)
            def do_restore(): dr.hide(); self.restore_draft(ask=False)
            def do_discard():
                if QMessageBox.question(self,"Verwerfen","Die automatisch gespeicherte Sitzung wirklich verwerfen?")!=QMessageBox.Yes: return
                for n in ("Sitzung_Autosave.json.enc","Sitzung_Autosave.json","Sitzung_Autosave_Handschrift.png","Sitzung_Autosave_Handschrift.png.enc"):
                    try: (ROOT/n).unlink()
                    except Exception: pass
                dr.hide()
            b_res.clicked.connect(do_restore); b_dis.clicked.connect(do_discard); v.addWidget(dr)

        # ---------------------------------------------------------------- Finanzen
        ft=QLabel(f"Finanzen {y}"); ft.setObjectName("sectionTitle"); v.addWidget(ft)
        month=today.strftime("%Y-%m")
        yearinv=[i for i in DB["invoices"] if str(i.get("number","")).startswith(y) and i.get("status")!="storniert"]
        billed=sum(float(i.get("amount",0) or 0) for i in yearinv); paid=sum(float(i.get("amount",0) or 0) for i in yearinv if i.get("status")=="bezahlt")
        month_billed=sum(float(i.get("amount",0) or 0) for i in DB["invoices"] if str(i.get("date","")).startswith(month) and i.get("status")!="storniert")
        open_list=[i for i in DB["invoices"] if i.get("status","offen")=="offen"]; open_amt=sum(float(i.get("amount",0) or 0) for i in open_list)
        cards=QGridLayout(); cards.setSpacing(12)
        def card(caption,value,hint=""):
            box=QFrame(); box.setObjectName("statCard"); box.setMinimumHeight(96); q=QVBoxLayout(box); a=QLabel(caption); a.setObjectName("cardCaption"); b=QLabel(value); b.setObjectName("cardValue"); q.addWidget(a); q.addWidget(b)
            if hint: h_=QLabel(hint); h_.setObjectName("pageSub"); q.addWidget(h_)
            return box
        cards.addWidget(card("UMSATZ "+today.strftime("%m/%Y"),eur(month_billed),"abgerechnet in diesem Monat"),0,0)
        cards.addWidget(card("ABGERECHNET "+y,eur(billed),f"davon bezahlt {eur(paid)}"),0,1)
        cards.addWidget(card("OFFEN",eur(open_amt),f"{len(open_list)} Rechnung(en)"),0,2)
        cards.addWidget(card("KLIENTEN",str(len(DB["clients"]))),1,0)
        cards.addWidget(card("SITZUNGEN "+y,str(sum(1 for s in DB["sessions"] if str(s.get("date","")).startswith(y)))),1,1)
        cards.addWidget(card("WARTELISTE",str(sum(1 for e in DB.get("waitlist",[]) if e.get("status") not in ("übernommen","abgesagt"))),"offene Einträge"),1,2)
        v.addLayout(cards)

        # ---------------------------------------------------------------- Schnellzugriff
        quick=QLabel("Schnellzugriff"); quick.setObjectName("sectionTitle"); v.addWidget(quick)
        actions=QHBoxLayout()
        for text,page in (("＋  Neue Sitzung",1),("▤  Neue Rechnung",7),("♙  Klientenakten",3),("✉  Formulare & Briefe",12)):
            b=QPushButton(text); b.setMinimumHeight(46); b.clicked.connect(lambda _=False,p=page: self.nav.setCurrentRow(p)); actions.addWidget(b)
        v.addLayout(actions)
        info=QLabel(f"Datenordner: {ROOT}"); info.setObjectName("pageSub"); info.setWordWrap(True); info.setTextInteractionFlags(Qt.TextSelectableByMouse); v.addWidget(info); v.addStretch()
        old=self.dash_scroll.takeWidget()
        self.dash_scroll.setWidget(w)
        if old is not None: old.deleteLater()
if __name__ == "__main__":
    app=QApplication(sys.argv)
    _ico=bundled_asset("PraxisPro.ico")
    app_logo=_ico or effective_practice_logo()
    if app_logo:
        app.setWindowIcon(QIcon(str(app_logo)))
    try: encryption_key()
    except RuntimeError as _key_err:
        QMessageBox.critical(None,"PraxisPro – Datenschlüssel",str(_key_err)); sys.exit(1)
    if not ensure_first_user(): sys.exit(0)
    login=LoginDialog()
    if login.exec()!=QDialog.Accepted: sys.exit(0)
    win=Main(); win.current_user=login.user; win.setWindowTitle(f"PraxisPro v{APP_VERSION} – "+login.user.get("display_name","")); win.show(); QTimer.singleShot(2000,win.offer_key_protection); app.aboutToQuit.connect(lambda: _OCR_SERVER.stop() if _OCR_SERVER else None); sys.exit(app.exec())
