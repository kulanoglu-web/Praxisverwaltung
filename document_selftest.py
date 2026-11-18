"""Selbsttest für die Praxisdokumente (Formulare & Briefe). Läuft im Build und lokal.
Erzeugt jede Vorlage als PDF mit Testdaten und Testunterschrift und prüft Inhalt und Platzhalter.
Aufruf mit Ordner als Argument speichert zusätzlich PNG-Vorschauen: python document_selftest.py vorschau/"""
import sys, tempfile
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import document_pdf, document_templates
from invoice_selftest import SETTINGS, text_of

ROOT = Path(__file__).resolve().parent
VALUES = {"klient_name": "Anna Mustermann", "klient_vorname": "Anna", "klient_nachname": "Mustermann", "klient_geburtsdatum": "14.05.1988",
          "klient_adresse": "Musterstraße 12, 13597 Berlin", "klient_telefon": "030 1234567", "klient_email": "anna@example.test",
          "anrede": "Sehr geehrte Kollegin, sehr geehrter Kollege", "klient_anrede": "Sehr geehrte Frau Mustermann",
          "kostentraeger": "Private Krankenversicherung – Muster PKV", "versicherungsnummer": "A123456789","diagnose": "F43.2 Anpassungsstörung", "therapeut": SETTINGS["owner_name"],
          "qualifikation": SETTINGS["qualifications"], "praxis_name": SETTINGS["practice_name"], "praxis_adresse": SETTINGS["address"],
          "praxis_telefon": SETTINGS["phone"], "praxis_email": SETTINGS["email"], "ort": "Berlin", "datum": "18.11.2026",
          "empfaenger": "Dr. med. Erika Beispiel, Hauptstraße 1, 10115 Berlin",
          "honorar_tabelle": "Leistung | Dauer | Honorar\nEinzeltherapie | 45 Min. | 70,00 €\nPaargespräch | 60 Min. | 90,00 €",
          "absagefrist": "24 Stunden", "erste_sitzung": "02.09.2026", "letzte_sitzung": "11.11.2026", "anzahl_sitzungen": "3",
          "sitzungsliste": "Datum | Art | Dauer\n02.09.2026 | Einzeltherapie | 45 Min.\n14.10.2026 | Einzeltherapie | 45 Min.\n11.11.2026 | Onlinegespräch | 45 Min."}


def test_signature(path):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (900, 300), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.line([(60, 200), (160, 90), (230, 210), (320, 100), (420, 190), (560, 120), (820, 170)], fill=(11, 42, 74, 255), width=6)
    im.save(path)


def main():
    problems = []
    preview = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if preview: preview.mkdir(parents=True, exist_ok=True)
    if set(document_templates.ORDER) != set(document_templates.TEMPLATES):
        problems.append("ORDER und TEMPLATES passen nicht zusammen")
    known = set(document_templates.PLACEHOLDERS)
    with tempfile.TemporaryDirectory() as tmp:
        sig = Path(tmp) / "sig.png"; test_signature(sig)
        for key in document_templates.ORDER:
            tpl = document_templates.TEMPLATES[key]
            import re
            unknown = set(re.findall(r"\{([a-z_]+)\}", tpl["text"])) - known
            if unknown: problems.append(f"{key}: unbekannte Platzhalter {sorted(unknown)}")
            body = document_templates.fill(tpl["text"], VALUES)
            if re.search(r"\{[a-z_]+\}", body): problems.append(f"{key}: Platzhalter nach dem Befüllen übrig")
            logs = []
            pdf = Path(tmp) / f"{key}.pdf"
            sigs = [("Unterschrift Klient/in" if w == "client" else "Unterschrift Therapeut/in", str(sig), "Anna Mustermann" if w == "client" else SETTINGS["owner_name"]) for w in tpl["signatures"]]
            recipient = ["Dr. med. Erika Beispiel", "Hauptstraße 1", "10115 Berlin"] if tpl["recipient"] else None
            document_pdf.render_document_pdf(pdf, tpl["title"], body, SETTINGS, ROOT / "assets" / "logo.png", recipient, sigs, "Berlin, 18.11.2026", "", lambda c, t: logs.append(f"{c}: {t}"))
            if logs: problems.append(f"{key}: Meldungen beim Erzeugen: {logs}")
            if not pdf.exists() or pdf.stat().st_size < 20000: problems.append(f"{key}: PDF fehlt oder ist zu klein (Logo nicht eingebettet?)")
            text, pages = text_of(pdf)
            flat = " ".join(text.split())
            for w in (tpl["title"].split()[0], "Mustermann", "Unterschrift", "Berlin, 18.11.2026"):
                if w not in flat: problems.append(f"{key}: Text '{w}' fehlt")
            if "##" in text or "[ ]" in text: problems.append(f"{key}: Auszeichnung (## oder [ ]) wurde nicht umgesetzt")
            if pages > 3: problems.append(f"{key}: {pages} Seiten – Umbruch prüfen")
            print(f"{key}: {pdf.stat().st_size} Bytes, {pages} Seite(n)")
            if preview:
                try:
                    import pymupdf
                except ImportError:
                    import fitz as pymupdf
                with pymupdf.open(str(pdf)) as doc:
                    for i, page in enumerate(doc):
                        page.get_pixmap(dpi=80).save(str(preview / f"{key}-{i + 1}.png"))
    if problems:
        print("\nFEHLER:\n- " + "\n- ".join(problems)); sys.exit(1)
    print("Dokumenten-Selbsttest bestanden.")


if __name__ == "__main__":
    main()
