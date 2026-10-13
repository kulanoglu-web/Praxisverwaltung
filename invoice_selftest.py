"""Selbsttest für die Rechnungs-PDFs. Läuft im Build (GitHub Actions) und lokal.
Bricht mit Fehler ab, wenn Logo/PayPal-Logo fehlen oder die drei PDF-Varianten nicht stimmen."""
import sys, tempfile, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import invoice_pdf

ROOT = Path(__file__).resolve().parent
SETTINGS = {"owner_name": "Erdoğan Kulanoğlu", "practice_name": "Psychologische Privatpraxis", "qualifications": "Psychologe M.Sc. · Sozialarbeiter B.A.",
            "practice_subtitle": "Ehe-, Familien- und Lebensberatung", "address": "Schönwalder Str. 59, 13585 Berlin", "phone": "0176 43605753",
            "landline": "030 12127420", "fax": "030 43205928", "email": "info@psychologe-spandau.de", "website": "www.psychologe-spandau.de",
            "tax_number": "19/405/00254", "iban": "DE13 5001 0517 5404 0811 30", "bic": "INGDDEFFXXX", "paypal": "erdogankulanoglu@hotmail.com", "paypal_me": "erdogankulanoglu"}
DATA = {"number": "TEST-001", "date": "28.09.2026", "period": "28.09.2026", "first": "Anna", "last": "Mustermann", "address": "Musterstraße 12\n13597 Berlin",
        "salutation": "Sehr geehrte Frau", "amount": 70.0, "items": [{"date": "28.09.2026", "type": "Einzeltherapie", "minutes": 45, "amount": 70.0}],
        "paid_date": "13.10.2026", "reminder_level": 1}

def text_of(pdf):
    try:
        import fitz
        with fitz.open(str(pdf)) as doc:
            return "\n".join(page.get_text() for page in doc), len(doc)
    except ImportError:
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        return out, out.count("\f") or 1

def main():
    problems = []
    logo, paypal = ROOT / "assets" / "logo.png", ROOT / "assets" / "paypal.png"
    expect = {"invoice": ["Rechnung", "SEPA", "PayPal", "70,00"], "paid": ["BEGLICHEN", "Vielen Dank für Ihre Zahlung", "Offener Betrag", "13.10.2026"],
              "reminder": ["Zahlungserinnerung", "keinen Zahlungseingang", "SEPA"]}
    with tempfile.TemporaryDirectory() as tmp:
        for mode, words in expect.items():
            logs = []
            pdf = Path(tmp) / f"{mode}.pdf"
            invoice_pdf.render_invoice_pdf(pdf, dict(DATA, mode=mode), SETTINGS, logo, paypal, lambda c, t: logs.append(f"{c}: {t}"))
            if logs: problems.append(f"{mode}: Meldungen beim Erzeugen: {logs}")
            if not pdf.exists() or pdf.stat().st_size < 20000: problems.append(f"{mode}: PDF fehlt oder ist zu klein (Logo nicht eingebettet?)")
            text, pages = text_of(pdf)
            if pages != 1: problems.append(f"{mode}: {pages} Seiten statt 1")
            for w in words:
                if w not in text: problems.append(f"{mode}: Text '{w}' fehlt")
            if mode == "paid" and "Zahlungsziel" in text: problems.append("paid: enthält noch 'Zahlungsziel'")
            if mode == "invoice":
                try:
                    import cv2
                    png = Path(tmp) / "qr"
                    subprocess.run(["pdftoppm", "-r", "300", "-png", str(pdf), str(png)], check=True)
                    img = cv2.imread(str(next(Path(tmp).glob("qr*.png"))))
                    _, found, _, _ = cv2.QRCodeDetector().detectAndDecodeMulti(img)
                    if not any(f.startswith("BCD\n002\n1\nSCT\n") and "DE13500105175404081130" in f for f in found): problems.append("SEPA-QR-Code nicht lesbar/ungültig")
                    if not any(f.startswith("https://www.paypal.me/") for f in found): problems.append("PayPal-QR-Code nicht lesbar")
                except ImportError:
                    print("QR-Lesetest übersprungen (opencv fehlt)")
            print(f"{mode}: {pdf.stat().st_size} Bytes, {pages} Seite(n)")
    if problems:
        print("\nFEHLER:\n- " + "\n- ".join(problems)); sys.exit(1)
    print("Rechnungs-Selbsttest bestanden.")

if __name__ == "__main__":
    main()
