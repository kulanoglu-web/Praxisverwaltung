"""PDF-Erzeugung für Rechnung, beglichene Rechnung (mit Dank) und Zahlungserinnerung.

Reines ReportLab, ohne Qt: dadurch einzeln testbar. Alle Praxisdaten kommen über das
Dictionary ``s`` (Einstellungen), alle Rechnungsdaten über ``d``.
"""
from pathlib import Path
import os

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm

# Farben aus dem freigegebenen Muster-PDF
NAVY = HexColor("#163A59")     # Fließtext
TEAL = HexColor("#006C73")     # Überschriften
GOLD = HexColor("#D9A93A")     # Trennlinien
CREAM = HexColor("#F5F0E5")    # Tabellenkopf / Summe
BORDER = HexColor("#DCC9A0")   # Rahmen
WHITE = HexColor("#FFFFFF")
GREEN = HexColor("#2E7D4F")    # nur für den Status "beglichen"

MODES = ("invoice", "paid", "reminder")


def eur(value):
    return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _fonts():
    """Arial (Windows) bevorzugen, sonst DejaVu, sonst Helvetica. Wichtig für Zeichen wie ğ, ş, ı."""
    win = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = [
        (win / "arial.ttf", win / "arialbd.ttf", "PraxisArial", "PraxisArialBold"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), "PraxisDejaVu", "PraxisDejaVuBold"),
    ]
    for reg, bld, rn, bn in candidates:
        try:
            if reg.is_file() and bld.is_file():
                if rn not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(rn, str(reg)))
                if bn not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(bn, str(bld)))
                return rn, bn
        except Exception:
            continue
    return "Helvetica", "Helvetica-Bold"


def _wrap(can, text, font, size, maxw):
    lines, cur = [], ""
    for word in str(text).split():
        trial = (cur + " " + word).strip()
        if cur and can.stringWidth(trial, font, size) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def paypal_link(me, account, amount):
    """Zahlungslink fuer den QR-Code. Eine E-Mail-Adresse allein kann keine Zahlung oeffnen,
    dafuer wird ein PayPal.Me-Name oder -Link gebraucht."""
    import re
    me = (me or "").strip() or ((account or "").strip() if not "@" in (account or "") else "")
    if not me:
        return ""
    m = re.search(r"paypal\.me/([^/?#\s]+)", me, re.I)
    name = m.group(1) if m else (me if re.fullmatch(r"[A-Za-z0-9._-]+", me) else "")
    if not name:
        return ""
    return f"https://www.paypal.me/{name}/{amount:.2f}EUR"


def render_invoice_pdf(pdf_path, d, s, logo_path=None, paypal_logo_path=None, log=None):
    """Erzeugt das PDF. ``log(code, text)`` meldet Probleme (z. B. defektes Logo)."""
    log = log or (lambda code, text: None)
    mode = d.get("mode", "invoice")
    if mode not in MODES:
        mode = "invoice"
    regular, bold = _fonts()
    W, H = A4
    L, R = 18 * mm, W - 18 * mm
    can = canvas.Canvas(str(pdf_path), pagesize=A4)
    can.setTitle(f"Rechnung {d['number']}")

    owner = s.get("owner_name", ""); practice_name = s.get("practice_name", "")
    qualifications = s.get("qualifications", ""); subtitle = s.get("practice_subtitle", "")
    address = s.get("address", ""); phone = s.get("phone", ""); landline = s.get("landline", ""); fax = s.get("fax", "")
    email = s.get("email", ""); website = s.get("website", "")
    tax = s.get("tax_number", ""); iban = s.get("iban", ""); bic = s.get("bic", ""); paypal = s.get("paypal", "")
    amt = float(d["amount"]); no = d["number"]

    # ---------------------------------------------------------------- Kopf
    drawn = False
    if logo_path:
        try:
            from reportlab.lib.utils import ImageReader
            im = ImageReader(str(logo_path)); iw, ih = im.getSize(); im.getRGBData()
            mw = float(s.get("logo_width_mm", "72")) * mm; mh = float(s.get("logo_height_mm", "22")) * mm
            sc = min(mw / iw, mh / ih); lw, lh = iw * sc, ih * sc
            zone_base = {"Links": 18.0, "Mitte": 74.0, "Rechts": 132.0}.get(s.get("invoice_header_logo_zone", "Links"), 18.0)
            lx = (zone_base + max(0.0, float(s.get("logo_x_mm", "18")) - 18.0)) * mm
            top = float(s.get("logo_y_mm", "7")) * mm
            can.drawImage(im, lx, H - top - lh, width=lw, height=lh, preserveAspectRatio=True, mask="auto")
            drawn = True
        except Exception as e:
            log("INVOICE_LOGO_ERROR", str(e)[:500])
    if not drawn:
        log("INVOICE_LOGO_MISSING", "Praxislogo konnte nicht geladen werden")

    can.setFillColor(NAVY); can.setFont(regular, 7.7)
    qy = H - 29 * mm
    for line in (owner, practice_name, qualifications):
        if line:
            can.drawString(L, qy, line); qy -= 4.2 * mm
    for line in _wrap(can, subtitle, regular, 7.7, 100 * mm):
        can.drawString(L, qy, line); qy -= 4.2 * mm

    can.setFont(regular, 8.2); tx = 132 * mm; ty = H - 14 * mm
    contact = [x.strip() for x in address.replace(",", "\n", 1).splitlines() if x.strip()]
    if phone: contact.append("Handy " + phone)
    if landline: contact.append("Festnetz " + landline)
    if fax: contact.append("Fax " + fax)
    contact += [x for x in (email, website) if x]
    for line in contact:
        can.drawString(tx, ty, line); ty -= 4.3 * mm

    can.setStrokeColor(GOLD); can.setLineWidth(1)
    can.line(L, H - 52 * mm, R, H - 52 * mm)

    # ---------------------------------------------------------------- Empfänger / Metadaten
    y = H - 64 * mm; can.setFillColor(NAVY); can.setFont(regular, 10)
    can.drawString(L, y, f"{d['first']} {d['last']}"); y -= 5 * mm
    for line in (d.get("address", "").splitlines() or [""]):
        can.drawString(L, y, line); y -= 5 * mm

    meta = [("Rechnungs-Nr.:", no), ("Rechnungsdatum:", d["date"]), ("Leistungsdatum:", d["period"])]
    if mode == "paid":
        meta.append(("Bezahlt am:", d.get("paid_date", "")))
    my = H - 64 * mm
    for lab, val in meta:
        can.setFont(bold, 9.5); can.drawRightString(152 * mm, my, lab)
        can.setFont(regular, 9.5); can.drawRightString(R, my, val); my -= 5 * mm

    # ---------------------------------------------------------------- Titel und Anrede
    titles = {"invoice": "Rechnung", "paid": "Rechnung", "reminder": {1: "Zahlungserinnerung", 2: "2. Zahlungserinnerung"}.get(int(d.get("reminder_level", 1)), "Letzte Zahlungserinnerung")}
    can.setFillColor(TEAL); can.setFont(bold, 24); can.drawString(L, H - 94 * mm, titles[mode])
    if mode == "paid":
        # Statusmarke "BEGLICHEN" rechts neben dem Titel
        can.setStrokeColor(GREEN); can.setFillColor(GREEN); can.setLineWidth(1.4)
        can.roundRect(R - 46 * mm, H - 96.5 * mm, 46 * mm, 10 * mm, 2 * mm, stroke=1, fill=0)
        can.setFont(bold, 13); can.drawCentredString(R - 23 * mm, H - 93.2 * mm, "BEGLICHEN")
    can.setFillColor(NAVY); can.setFont(regular, 10)
    can.drawString(L, H - 105 * mm, f"{d['salutation']} {d['last']},")
    intro = {
        "invoice": ["hiermit stelle ich Ihnen folgende Leistung in Rechnung:"],
        "paid": ["vielen Dank, Ihre Zahlung ist bei mir eingegangen. Die folgende Rechnung ist damit beglichen:"],
        "reminder": ["zu der unten aufgeführten Rechnung konnte ich bisher keinen Zahlungseingang feststellen.",
                     "Falls Sie bereits überwiesen haben, betrachten Sie dieses Schreiben bitte als gegenstandslos."],
    }[mode]
    iy = H - 112 * mm
    for line in intro:
        can.drawString(L, iy, line); iy -= 5.2 * mm

    # ---------------------------------------------------------------- Tabelle
    top = iy - 4 * mm
    x = [L, 48 * mm, 120 * mm, 145 * mm, 173 * mm, R]; rh = 7.5 * mm
    can.setFillColor(CREAM); can.setStrokeColor(BORDER); can.setLineWidth(.6)
    can.rect(x[0], top - rh, x[-1] - x[0], rh, stroke=1, fill=1)
    can.setFillColor(TEAL); can.setFont(bold, 8.2)
    for j, h in enumerate(["Datum", "Leistung", "Dauer", "Einzelpreis", "Betrag"]):
        can.drawString(x[j] + 1.5 * mm, top - 5 * mm, h)
    cy = top - rh
    can.setFillColor(NAVY); can.setFont(regular, 8.4)
    for it in d["items"]:
        unit = float(it["amount"])
        vals = [it["date"], it["type"], f'{int(it["minutes"])} Min.', eur(unit), eur(unit)]
        for j, val in enumerate(vals):
            if j >= 3:
                can.drawRightString(x[j + 1] - 1.5 * mm, cy - 5 * mm, val)
            else:
                can.drawString(x[j] + 1.5 * mm, cy - 5 * mm, val)
        cy -= rh; can.setStrokeColor(BORDER); can.line(x[0], cy, x[-1], cy)
    n = len(d["items"]) + 1
    for xx in x:
        can.line(xx, top, xx, top - rh * n)
    can.line(x[0], top, x[-1], top)

    # Summenblock
    sx = 104 * mm; sy = cy - 1 * mm; rows = [("Rechnungssumme:", eur(amt), True)]
    if mode == "paid":
        rows = [("Rechnungssumme:", eur(amt), False), ("Bereits bezahlt:", "– " + eur(amt), False), ("Offener Betrag:", eur(0), True)]
    for lab, val, strong in rows:
        can.setFillColor(CREAM if strong else WHITE); can.setStrokeColor(BORDER)
        can.rect(sx, sy - rh, R - sx, rh, stroke=0 if strong else 1, fill=1)
        can.setFillColor(TEAL if strong else NAVY); can.setFont(bold if strong else regular, 10 if strong else 8.8)
        can.drawString(sx + 2 * mm, sy - 5 * mm, lab); can.drawRightString(R - 2 * mm, sy - 5 * mm, val)
        sy -= rh
    can.setFillColor(NAVY); can.setFont(regular, 8.2)
    can.drawRightString(R, sy - 5 * mm, "Gemäß § 4 Nr. 14 UStG wird keine Umsatzsteuer erhoben.")
    cursor = sy - 12 * mm

    # ---------------------------------------------------------------- Zahlungsteil
    if mode in ("invoice", "reminder"):
        can.setFont(bold, 8.8)
        due_text = d.get("due_text") or ("Zahlungsziel: 14 Tage nach Rechnungsdatum." if mode == "invoice" else "Bitte begleichen Sie den Betrag innerhalb von 7 Tagen.")
        can.drawRightString(R, cursor, due_text)
        can.setFont(regular, 8.2); can.drawRightString(R, cursor - 5 * mm, "Bitte Rechnungsnummer als Verwendungszweck angeben.")
        by = cursor - 5 * mm - 8 * mm - 42 * mm; bh = 42 * mm; gap = 4 * mm; bw = (R - L - gap) / 2

        def paybox(xb, title):
            can.setStrokeColor(BORDER); can.setFillColor(WHITE); can.roundRect(xb, by, bw, bh, 2 * mm, stroke=1, fill=1)
            can.setFillColor(CREAM); can.roundRect(xb, by + bh - 8 * mm, bw, 8 * mm, 2 * mm, stroke=0, fill=1)
            can.rect(xb, by + bh - 8 * mm, bw, 3 * mm, stroke=0, fill=1)
            can.setFillColor(TEAL); can.setFont(bold, 10); can.drawString(xb + 2.5 * mm, by + bh - 5.6 * mm, title)

        paybox(L, "SEPA-Überweisung"); paybox(L + bw + gap, "Zahlung per PayPal")
        can.setFillColor(NAVY); lx = L + 2.5 * mm; ly = by + bh - 13.5 * mm
        for lab, val in (("Empfänger:", owner), ("IBAN:", iban), ("BIC:", bic), ("Verwendungszweck:", no), ("Betrag:", eur(amt))):
            can.setFont(bold, 6.8); can.drawString(lx, ly, lab); can.setFont(regular, 6.8); can.drawString(lx + 29 * mm, ly, val); ly -= 4.2 * mm
        px = L + bw + gap + 2.5 * mm; py = by + bh - 13.5 * mm
        if paypal_logo_path:
            try:
                from reportlab.lib.utils import ImageReader
                pim = ImageReader(str(paypal_logo_path)); piw, pih = pim.getSize(); pim.getRGBData()
                psc = min(24 * mm / piw, 5.6 * mm / pih); pw_, ph_ = piw * psc, pih * psc
                can.drawImage(pim, L + bw + gap + bw - 2.5 * mm - pw_, by + bh - 4 * mm - ph_ / 2, width=pw_, height=ph_, preserveAspectRatio=True, mask="auto")
            except Exception as e:
                log("PAYPAL_LOGO_ERROR", str(e)[:300])
        else:
            log("PAYPAL_LOGO_MISSING", "paypal.png nicht gefunden")
        can.setFillColor(NAVY); can.setFont(regular, 7); can.drawString(px, py - 4 * mm, "PayPal-Konto:")
        can.setFont(bold, 7); can.setFillColor(TEAL); can.drawString(px, py - 9 * mm, paypal)
        can.setFillColor(NAVY); can.setFont(regular, 7); can.drawString(px, py - 14 * mm, f"Verwendungszweck: {no}")
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing
            from reportlab.graphics import renderPDF

            def qr(data, xq, yq, size=21 * mm, level="M"):
                q = QrCodeWidget(data, barLevel=level); b = q.getBounds()
                dr = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0]); dr.add(q); renderPDF.draw(dr, can, xq, yq)

            epc = "\n".join(["BCD", "002", "1", "SCT", bic, owner, iban.replace(" ", ""), "EUR" + f"{amt:.2f}", "", "", no])
            qr(epc, L + bw - 24 * mm, by + 4 * mm)
            link = paypal_link(s.get("paypal_me", ""), paypal, amt)
            if link:
                qr(link, L + bw + gap + bw - 24 * mm, by + 4 * mm)
                can.setFont(regular, 5.6); can.setFillColor(NAVY)
                can.drawCentredString(L + bw + gap + bw - 13.5 * mm, by + 1.8 * mm, "QR scannen: PayPal öffnet mit Betrag")
        except Exception as e:
            log("INVOICE_QR_ERROR", str(e)[:300])
        yy = by - 9 * mm
    else:
        # beglichen: Dankesbox statt Zahlungsdaten
        bh = 30 * mm; by = cursor - 4 * mm - bh
        can.setStrokeColor(GREEN); can.setFillColor(HexColor("#F1F8F3")); can.setLineWidth(1)
        can.roundRect(L, by, R - L, bh, 2.5 * mm, stroke=1, fill=1)
        can.setFillColor(GREEN); can.setFont(bold, 13); can.drawString(L + 6 * mm, by + bh - 9 * mm, "Vielen Dank für Ihre Zahlung!")
        can.setFillColor(NAVY); can.setFont(regular, 9.2)
        msg = (f"Der Rechnungsbetrag von {eur(amt)} ist am {d.get('paid_date', '')} bei mir eingegangen. "
               "Die Rechnung ist damit vollständig beglichen, es besteht kein offener Betrag mehr.")
        ty2 = by + bh - 16 * mm
        for line in _wrap(can, msg, regular, 9.2, R - L - 12 * mm):
            can.drawString(L + 6 * mm, ty2, line); ty2 -= 4.8 * mm
        yy = by - 9 * mm

    # ---------------------------------------------------------------- Abschluss
    can.setFillColor(NAVY); can.setFont(regular, 9)
    closing = {
        "invoice": "Vielen Dank für Ihr Vertrauen.",
        "paid": "Ich danke Ihnen für Ihr Vertrauen und die zuverlässige Zahlung.",
        "reminder": "Bei Rückfragen erreichen Sie mich gern telefonisch oder per E-Mail.",
    }[mode]
    can.drawString(L, yy, closing); can.drawString(L, yy - 6 * mm, "Mit freundlichen Grüßen")
    can.setFillColor(TEAL); can.setFont(bold, 10); can.drawString(L, yy - 18 * mm, owner)
    can.setFillColor(NAVY); can.setFont(regular, 7.5); can.drawString(L, yy - 23 * mm, practice_name or "Psychologische Privatpraxis")
    can.setFont(regular, 6.8)
    can.drawRightString(R, yy - 18 * mm, "Dieses Dokument wurde elektronisch erstellt und ist auch ohne Unterschrift gültig.")

    # ---------------------------------------------------------------- Fußzeile
    fy = 15 * mm
    can.setStrokeColor(GOLD); can.setLineWidth(.8); can.line(L, fy + 10 * mm, R, fy + 10 * mm)
    can.setFillColor(TEAL); can.setFont(bold, 6.8)
    for xx, title in ((L, "Praxis"), (75 * mm, "Kontakt"), (132 * mm, "Zahlung")):
        can.drawString(xx, fy + 5.5 * mm, title)
    can.setFillColor(NAVY); can.setFont(regular, 6)
    can.drawString(L, fy + 1 * mm, address); can.drawString(L, fy - 2.5 * mm, website)
    can.drawString(75 * mm, fy + 1 * mm, " · ".join(x for x in (phone, landline) if x))
    if fax: can.drawString(75 * mm, fy - 2.5 * mm, "Fax " + fax)
    can.drawString(75 * mm, fy - 6 * mm, email)
    can.drawString(132 * mm, fy + 1 * mm, "IBAN " + iban); can.drawString(132 * mm, fy - 2.5 * mm, "BIC " + bic)
    if tax: can.drawString(132 * mm, fy - 6 * mm, "Steuernummer " + tax)
    can.save()
    return str(pdf_path)
