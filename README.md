# PraxisPro – Praxisverwaltung

Windows-Desktopprogramm für Sitzungsdokumentation, Handschriftnotizen, Rechnungen und Einnahmenübersicht
einer psychologischen Privatpraxis. Alle Daten bleiben lokal unter `Dokumente/Praxisverwaltung`.

## Setup erzeugen (Windows)
1. Auf GitHub: **Actions → „Windows EXE" → Run workflow**.
2. Warten, bis der Lauf grün ist (Rechnungs-Selbsttest, Oberflächentest, Build, Setup, Installationstest).
3. Im Release bzw. unter Artifacts liegt `PraxisPro_Setup_v<Version>.exe` – mit Praxislogo im Installationsassistenten.

Der Build bricht absichtlich ab, wenn Logo, PayPal-Logo, Programm-Icon oder Setup-Bilder fehlen oder beschädigt sind.
**Bilder bitte nie über Chat-Programme hin- und herkopieren**, sondern direkt als Datei hochladen (GitHub: *Add file → Upload files*).

## Rechnungen
Drei PDF-Varianten aus demselben Modul (`invoice_pdf.py`):
- **Rechnung** mit SEPA- und PayPal-Zahlungsdaten samt QR-Codes
- **Beglichene Rechnung** mit „BEGLICHEN"-Stempel und Dankestext – direkt beim Erstellen wählbar
  („Rechnung ist bereits beglichen") oder später über **Rechnungen → Als bezahlt markieren**
- **Zahlungserinnerung** (Stufen 1–3) über **Rechnungen → Zahlungserinnerung**

Die ursprüngliche Rechnung wird nie überschrieben; Dankes- und Erinnerungs-PDFs liegen als eigene Dateien daneben.

## Datenschutz
- Therapienotizen, Datenbankinhalte und Handschriftnotizen werden verschlüsselt gespeichert.
- Der Datenschlüssel kann an das Windows-Benutzerkonto gebunden werden (Angebot beim Start bzw.
  unter *Rechnungen → Schlüssel mit Windows-Konto schützen*). Vorher wird ein **Wiederherstellungsschlüssel**
  auf einem USB-Stick gespeichert. Ohne ihn sind die Daten nach Windows-Neuinstallation oder auf einem anderen PC nicht lesbar.
- Datensicherung: Ziel wählbar (z. B. USB-Stick).

## Handschrift → Text
Lokale Windows-Texterkennung (kein Internet nötig). Sprache wählbar (Deutsch/Türkisch/Englisch); die jeweilige
Sprache muss in Windows mit Texterkennung installiert sein. Funktioniert am besten mit klarer Druckschrift.

## Dateien
- `main.py` – Programm, `invoice_pdf.py` – Rechnungs-PDFs, `invoice_selftest.py` – Selbsttest
- `assets/` – Logo, PayPal-Logo, Programm-Icon; `installer/` – Setup-Bilder
- `PraxisPro.iss` – Setup-Skript (Inno Setup), `.github/workflows/build-windows.yml` – Build
