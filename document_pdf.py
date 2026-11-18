"""PDF-Erzeugung für Praxisdokumente (Verträge, Einwilligungen, Bescheinigungen, Berichte).

Reines ReportLab, ohne Qt. Gleicher Briefkopf und gleiche Fußzeile wie die Rechnungen.

Einfache Textauszeichnung im Dokumenttext:
  ## Überschrift          -> Zwischenüberschrift
  • Text  oder  - Text    -> Aufzählung
  [ ] Text / [x] Text     -> Ankreuzfeld (leer / angekreuzt)
  A | B | C               -> Tabellenzeile (Spalten durch " | " getrennt)
  Leerzeile               -> Absatz
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from invoice_pdf import NAVY, TEAL, GOLD, BORDER, CREAM, WHITE, _fonts, _wrap, draw_letterhead, draw_footer

BOTTOM = 40 * mm          # darunter beginnt die Fußzeile
BODY_SIZE = 9.6
LINE = 4.9 * mm


class _Writer:
    def __init__(self, can, s, logo_path, log):
        self.can, self.s, self.logo_path, self.log = can, s, logo_path, log
        self.regular, self.bold = _fonts()
        W, H = A4
        self.W, self.H = W, H
        self.L, self.R = 22 * mm, W - 20 * mm
        self.page = 1
        self.y = 0

    def first_page(self):
        draw_letterhead(self.can, self.s, self.logo_path, self.log)
        self.y = self.H - 62 * mm

    def new_page(self):
        draw_footer(self.can, self.s, payment=False)
        self.can.setFont(self.regular, 7.5); self.can.setFillColor(NAVY)
        self.can.drawRightString(self.R, 12 * mm, f"Seite {self.page}")
        self.can.showPage(); self.page += 1
        # Folgeseiten: schmale Kopfzeile statt vollem Briefkopf
        self.can.setFillColor(NAVY); self.can.setFont(self.regular, 8)
        owner = self.s.get("owner_name", "") or self.s.get("practice_name", "")
        self.can.drawString(self.L, self.H - 15 * mm, owner)
        self.can.drawRightString(self.R, self.H - 15 * mm, self.title)
        self.can.setStrokeColor(GOLD); self.can.setLineWidth(.8)
        self.can.line(self.L, self.H - 18 * mm, self.R, self.H - 18 * mm)
        self.y = self.H - 28 * mm

    def need(self, height):
        if self.y - height < BOTTOM:
            self.new_page()

    def text_lines(self, text, font=None, size=BODY_SIZE, indent=0, color=NAVY):
        font = font or self.regular
        maxw = self.R - self.L - indent
        lines = _wrap(self.can, text, font, size, maxw) or [""]
        for ln in lines:
            self.need(LINE)
            self.can.setFillColor(color); self.can.setFont(font, size)
            self.can.drawString(self.L + indent, self.y, ln); self.y -= LINE

    def heading(self, text):
        self.need(LINE * 2.4)
        self.y -= 1.5 * mm
        self.text_lines(text, self.bold, 11, color=TEAL)
        self.y -= 0.8 * mm

    def bullet(self, text):
        self.need(LINE)
        self.can.setFillColor(NAVY); self.can.setFont(self.regular, BODY_SIZE)
        self.can.drawString(self.L + 2 * mm, self.y, "•")
        self.text_lines(text, indent=7 * mm)

    def checkbox(self, text, checked):
        self.need(LINE)
        b = 3.4 * mm; bx = self.L + 1 * mm; by = self.y - 0.8 * mm
        self.can.setStrokeColor(NAVY); self.can.setLineWidth(.7); self.can.rect(bx, by, b, b, stroke=1, fill=0)
        if checked:
            self.can.setLineWidth(1.1)
            self.can.line(bx + .6 * mm, by + 1.7 * mm, bx + 1.4 * mm, by + .6 * mm)
            self.can.line(bx + 1.4 * mm, by + .6 * mm, bx + 2.9 * mm, by + 2.9 * mm)
        self.text_lines(text, indent=7 * mm)

    def table_row(self, cells, header=False):
        n = len(cells); width = self.R - self.L
        # erste Spalte breiter
        ws = [width * (0.5 if n > 1 else 1)] + [width * 0.5 / max(1, n - 1)] * (n - 1)
        font = self.bold if header else self.regular
        wrapped = [(_wrap(self.can, c, font, 8.8, w - 3 * mm) or [""]) for c, w in zip(cells, ws)]
        h = max(len(w) for w in wrapped) * 4.4 * mm + 2.6 * mm
        self.need(h)
        top = self.y + 3.6 * mm
        self.can.setStrokeColor(BORDER); self.can.setLineWidth(.6)
        self.can.setFillColor(CREAM if header else WHITE)
        self.can.rect(self.L, top - h, width, h, stroke=1, fill=1)
        x = self.L
        for lines, w in zip(wrapped, ws):
            self.can.setFillColor(TEAL if header else NAVY); self.can.setFont(font, 8.8)
            yy = top - 4.4 * mm
            for ln in lines:
                self.can.drawString(x + 1.6 * mm, yy, ln); yy -= 4.4 * mm
            x += w
            if x < self.R - 1:
                self.can.line(x, top, x, top - h)
        self.y = top - h - 3.6 * mm + 0.0
        self.y -= 0.5 * mm

    def body(self, text):
        in_table = False
        for raw in str(text).replace("\r\n", "\n").split("\n"):
            line = raw.rstrip()
            st = line.strip()
            if " | " in st:
                cells = [c.strip() for c in st.strip("|").split(" | ")]
                self.table_row(cells, header=not in_table)
                in_table = True
                continue
            if in_table:
                self.y -= 1.5 * mm
            in_table = False
            if not st:
                self.y -= LINE * 0.55
            elif st.startswith("## "):
                self.heading(st[3:].strip())
            elif st.startswith(("• ", "- ", "* ")):
                self.bullet(st[2:].strip())
            elif st[:3].lower() in ("[ ]", "[x]"):
                self.checkbox(st[3:].strip(), st[1].lower() == "x")
            else:
                self.text_lines(st)

    def signatures(self, sigs, place_date):
        """sigs: Liste von (Beschriftung, PNG-Pfad oder None, Name)."""
        if not sigs:
            return
        self.need(42 * mm)
        self.y -= 10 * mm
        cols = max(2, len(sigs)); gap = 10 * mm   # einzelne Unterschrift nur halbe Breite
        w = (self.R - self.L - gap * (cols - 1)) / cols
        base = self.y - 18 * mm
        for i, (label, png, name) in enumerate(sigs):
            x = self.L + i * (w + gap)
            if png:
                try:
                    from reportlab.lib.utils import ImageReader
                    im = ImageReader(str(png)); iw, ih = im.getSize()
                    sc = min((w - 4 * mm) / iw, 20 * mm / ih)
                    self.can.drawImage(im, x + 2 * mm, base + 1 * mm, width=iw * sc, height=ih * sc, mask="auto")
                except Exception as e:
                    self.log("DOC_SIGNATURE_ERROR", str(e)[:300])
            self.can.setStrokeColor(NAVY); self.can.setLineWidth(.7); self.can.line(x, base, x + w, base)
            self.can.setFillColor(NAVY); self.can.setFont(self.regular, 8)
            self.can.drawString(x, base - 4.2 * mm, f"{place_date}  ·  {label}")
            if name:
                self.can.setFont(self.bold, 8.4); self.can.drawString(x, base - 8.6 * mm, name)
        self.y = base - 14 * mm


def render_document_pdf(pdf_path, title, body, s, logo_path=None, recipient=None, signatures=None,
                        place_date="", reference="", log=None):
    """Erzeugt ein Praxisdokument als PDF.

    recipient:  Zeilen der Empfängeranschrift (Liste) oder None
    signatures: Liste (Beschriftung, PNG-Pfad|None, Name) – leere Unterschriftslinie, wenn PNG fehlt
    reference:  kurzer Bezug rechts oben unter dem Briefkopf (z. B. "Klient/in: Max Mustermann, geb. 12.03.1978")
    """
    log = log or (lambda code, text: None)
    can = canvas.Canvas(str(pdf_path), pagesize=A4)
    can.setTitle(title); can.setAuthor(s.get("owner_name", "") or "PraxisPro")
    w = _Writer(can, s, logo_path, log); w.title = title
    w.first_page()
    if recipient:
        can.setFillColor(NAVY); can.setFont(w.regular, 10)
        y = w.y
        for ln in [x for x in recipient if x.strip()][:6]:
            can.drawString(w.L, y, ln.strip()); y -= 5 * mm
        w.y = min(w.y - 30 * mm, y - 6 * mm)
    if place_date:
        can.setFont(w.regular, 9.5); can.setFillColor(NAVY)
        can.drawRightString(w.R, (w.H - 62 * mm) if recipient else w.y, place_date)
        if not recipient:
            w.y -= 7 * mm
    can.setFillColor(TEAL); can.setFont(w.bold, 17)
    w.need(14 * mm)
    for ln in _wrap(can, title, w.bold, 17, w.R - w.L):
        can.drawString(w.L, w.y, ln); w.y -= 7.5 * mm
    if reference:
        can.setFillColor(NAVY); can.setFont(w.regular, 9)
        can.drawString(w.L, w.y, reference); w.y -= 6 * mm
    w.y -= 3 * mm
    w.body(body)
    w.signatures(signatures or [], place_date)
    draw_footer(can, s, payment=False)
    if w.page > 1:
        can.setFont(w.regular, 7.5); can.setFillColor(NAVY)
        can.drawRightString(w.R, 12 * mm, f"Seite {w.page}")
    can.save()
    return str(pdf_path)
