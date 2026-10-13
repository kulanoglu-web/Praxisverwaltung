"""Flexible Eingabefelder und ein umbrechendes Layout für PraxisPro.

* FlexTimeEdit / FlexDateEdit: normale Textfelder, in denen Cursor, Löschen, Markieren und Einfügen
  ganz normal funktionieren. Eingaben wie "930", "9.30", "9:30", "0930" oder "9" werden beim
  Verlassen des Feldes zu 09:30 bzw. 09:00 – Datum entsprechend "5.10.26", "051026", "5.10." usw.
* FlowLayout: ordnet Schaltflächen nebeneinander an und bricht in die nächste Zeile um, wenn der
  Platz nicht reicht (Hochformat/Drehen des Bildschirms).
"""
import re
from PySide6.QtCore import Qt, QDate, QTime, QRect, QSize, QPoint, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit, QLayout, QCalendarWidget, QDialog, QVBoxLayout, QSizePolicy


def parse_time_text(text):
    """Gibt QTime zurück oder None, wenn der Text keine Uhrzeit ergibt."""
    t = (text or "").strip().lower().replace("uhr", "").strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,2})\s*[:.,;\-hH ]\s*(\d{1,2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    elif re.fullmatch(r"\d{1,2}", t):
        h, mi = int(t), 0
    elif re.fullmatch(r"\d{3,4}", t):
        h, mi = int(t[:-2]), int(t[-2:])
    else:
        return None
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return QTime(h, mi)
    return None


def parse_date_text(text, today=None):
    """Gibt QDate zurück oder None. Akzeptiert 5.10.2026, 5.10.26, 5.10., 05102026, 051026, 2026-10-05."""
    t = (text or "").strip()
    if not t:
        return None
    today = today or QDate.currentDate()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        d = QDate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d if d.isValid() else None
    m = re.fullmatch(r"(\d{1,2})\s*[./\-,\s]\s*(\d{1,2})\s*[./\-,\s]?\s*(\d{0,4})", t)
    if m:
        day, mon, yr = int(m.group(1)), int(m.group(2)), m.group(3)
    elif re.fullmatch(r"\d{8}", t):
        day, mon, yr = int(t[:2]), int(t[2:4]), t[4:]
    elif re.fullmatch(r"\d{6}", t):
        day, mon, yr = int(t[:2]), int(t[2:4]), t[4:]
    elif re.fullmatch(r"\d{4}", t):
        day, mon, yr = int(t[:2]), int(t[2:4]), ""
    else:
        return None
    if yr == "":
        year = today.year()
    elif len(yr) <= 2:
        year = 2000 + int(yr)
    elif len(yr) == 4:
        year = int(yr)
    else:
        return None
    d = QDate(year, mon, day)
    return d if d.isValid() else None


class FlexTimeEdit(QLineEdit):
    """Uhrzeit-Feld mit freier Eingabe. API ähnlich QTimeEdit (time, setTime, timeChanged)."""
    timeChanged = Signal(QTime)

    def __init__(self, time=None, parent=None):
        super().__init__(parent)
        self._time = time if isinstance(time, QTime) and time.isValid() else QTime(0, 0)
        self.setPlaceholderText("HH:MM")
        self.setMaximumWidth(16777215)
        self.setToolTip("Uhrzeit frei eingeben, z. B. 9, 930, 9.30 oder 14:30.\nPfeil hoch/runter: ±5 Minuten, Bild hoch/runter: ±1 Stunde.")
        self.setText(self._time.toString("HH:mm"))
        self.editingFinished.connect(self.normalize)

    # --- QTimeEdit-ähnliche Schnittstelle -------------------------------------
    def lineEdit(self):
        return self

    def setDisplayFormat(self, _fmt):
        pass

    def hasValidInput(self):
        return parse_time_text(self.text()) is not None

    def time(self):
        parsed = parse_time_text(self.text())
        return parsed if parsed is not None else self._time

    def setTime(self, t):
        if isinstance(t, QTime) and t.isValid():
            self._set(t, announce=True)

    # --- Verhalten ---------------------------------------------------------------
    def _set(self, t, announce):
        changed = (t != self._time)
        self._time = t
        self.setText(t.toString("HH:mm"))
        self.setStyleSheet("")
        if changed and announce:
            self.timeChanged.emit(t)

    def normalize(self):
        parsed = parse_time_text(self.text())
        if parsed is None:
            if self.text().strip():
                self.setStyleSheet("border:2px solid #c0392b;")
            return
        self._set(parsed, announce=True)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.selectAll()

    def keyPressEvent(self, e):
        step = {Qt.Key_Up: 5, Qt.Key_Down: -5, Qt.Key_PageUp: 60, Qt.Key_PageDown: -60}.get(e.key())
        if step is not None:
            self._set(self.time().addSecs(step * 60), announce=True)
            self.selectAll()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        e.ignore()   # versehentliches Verstellen beim Scrollen der Seite verhindern


class _CalendarPopup(QDialog):
    def __init__(self, date, parent):
        super().__init__(parent, Qt.Popup)
        v = QVBoxLayout(self); v.setContentsMargins(4, 4, 4, 4)
        self.cal = QCalendarWidget(); self.cal.setGridVisible(True); self.cal.setSelectedDate(date)
        self.cal.setFirstDayOfWeek(Qt.Monday); self.cal.setMinimumSize(360, 260)
        v.addWidget(self.cal)
        self.cal.activated.connect(self._pick); self.cal.clicked.connect(self._pick)
        self.chosen = None

    def _pick(self, d):
        self.chosen = d
        self.accept()


class FlexDateEdit(QLineEdit):
    """Datums-Feld mit freier Eingabe und Kalender-Knopf. API ähnlich QDateEdit."""
    dateChanged = Signal(QDate)

    def __init__(self, date=None, parent=None):
        super().__init__(parent)
        self._date = date if isinstance(date, QDate) and date.isValid() else QDate.currentDate()
        self.setPlaceholderText("TT.MM.JJJJ")
        self.setToolTip("Datum frei eingeben, z. B. 5.10.26, 05.10.2026 oder 0510 (aktuelles Jahr).\nPfeil hoch/runter: ±1 Tag. Kalender: Knopf rechts im Feld.")
        self.setText(self._date.toString("dd.MM.yyyy"))
        act = QAction("📅", self)
        self.addAction(act, QLineEdit.TrailingPosition)
        act.setToolTip("Kalender öffnen")
        act.triggered.connect(self.open_calendar)
        self.editingFinished.connect(self.normalize)

    def setCalendarPopup(self, _on):
        pass

    def setDisplayFormat(self, _fmt):
        pass

    def hasValidInput(self):
        return parse_date_text(self.text()) is not None

    def date(self):
        parsed = parse_date_text(self.text())
        return parsed if parsed is not None else self._date

    def setDate(self, d):
        if isinstance(d, QDate) and d.isValid():
            self._set(d, announce=True)

    def _set(self, d, announce):
        changed = (d != self._date)
        self._date = d
        self.setText(d.toString("dd.MM.yyyy"))
        self.setStyleSheet("")
        if changed and announce:
            self.dateChanged.emit(d)

    def normalize(self):
        parsed = parse_date_text(self.text())
        if parsed is None:
            if self.text().strip():
                self.setStyleSheet("border:2px solid #c0392b;")
            return
        self._set(parsed, announce=True)

    def open_calendar(self):
        dlg = _CalendarPopup(self.date(), self)
        dlg.move(self.mapToGlobal(QPoint(0, self.height())))
        dlg.exec()
        if dlg.chosen is not None:
            self._set(dlg.chosen, announce=True)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.selectAll()

    def keyPressEvent(self, e):
        step = {Qt.Key_Up: 1, Qt.Key_Down: -1, Qt.Key_PageUp: 30, Qt.Key_PageDown: -30}.get(e.key())
        if step is not None:
            self._set(self.date().addDays(step), announce=True)
            self.selectAll()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        e.ignore()


class FlowLayout(QLayout):
    """Ordnet Elemente von links nach rechts an und bricht bei Platzmangel um."""
    def __init__(self, parent=None, hspacing=8, vspacing=8):
        super().__init__(parent)
        self._items = []; self._h = hspacing; self._v = vspacing

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._layout(QRect(0, 0, w, 0), True)
    def minimumHeightForWidth(self, w): return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test_only):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisible() and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            nx = x + hint.width() + self._h
            if nx - self._h > r.right() + 1 and line_h > 0:
                x = r.x(); y += line_h + self._v; nx = x + hint.width() + self._h; line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx; line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()
