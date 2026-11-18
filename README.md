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

## Ausgaben & EÜR (Menü Abrechnung)
- **Ausgaben** mit Kategorie, Zahlart und **verschlüsseltem Beleg** (Scan/PDF), Ablage unter `Ausgaben/Belege/<Jahr>`
- **Kassenbuch (bar)** mit Anfangsbestand und laufendem Bestand; Bareinnahme mit Rechnungsnummer markiert die Rechnung als bezahlt
- **EÜR-Auswertung** nach Zuflussprinzip (Monate, Kategorien, Ergebnis) und **Export für den Steuerberater**:
  `Einnahmen/EUER_<Jahr>.xlsx` (Übersicht, Einnahmen, Ausgaben, Kassenbuch) und `Buchungen_<Jahr>.csv` –
  standardmäßig ohne Klientennamen. Berechnung in `finance.py`. Arbeitshilfe, keine Steuerberatung.
- **Ausfallhonorar**: im Kalender Termin wählen → „€ Ausfallhonorar abrechnen“ bereitet die Rechnung vor
  (Betrag unter Praxiseinstellungen → Honorare → „Ausfallhonorar“)

## Startseite & Kalender
- **Startseite** (aktualisiert sich bei jedem Aufruf): heutige Termine mit „Sitzung starten“, automatische
  Aufgaben (überfällige Rechnungen, nicht abgerechnete Sitzungen, Termine ohne Status, fehlender
  Behandlungsvertrag/Einwilligung, Kontingent, Warteliste), eigene Erinnerungen zum Abhaken,
  frei gewordene Termine mit passenden Wartelisteneinträgen, Finanzen inkl. Monatsumsatz
- **Kalender**: Tag/Woche/Monat; Serientermine wöchentlich, 14-tägig oder 4-wöchentlich (Überschneidungen werden
  übersprungen und gemeldet); Löschen „nur diesen“ oder „diesen und alle folgenden“
- **Sitzungskontingent** je Klient (Klientenakte → Kostenträger): Zähler bisher/geplant/frei im Kalender,
  im Therapieverlauf und als Aufgabe auf der Startseite, wenn nur noch wenige Sitzungen frei sind

## Therapieverlauf (Menü Therapie)
- **Anamnese**: strukturiert (Anlass, Beschwerden, Biografie, Gesundheit/Medikation, Ressourcen,
  Risikoeinschätzung inkl. Suizidalität, Befund/Hypothese/Plan); Export als PDF – verschlüsselt in der Akte
- **Therapieziele** mit Methoden, Status und Fortschrittsbewertung 0–10 samt Verlaufskurve
- **Fragebögen PHQ-9 und GAD-7** (`questionnaires.py`): automatische Summe und Einstufung, Großansicht zum
  Ausfüllen durch Klient/in, Verlaufskurve mit Schweregrad-Bereichen. Lizenzpflichtige Tests (BDI-II, SCL-90-R)
  sind bewusst nicht enthalten.
- **Risikohinweis** oben auf der Seite bei Suizidalitätsangaben in der Anamnese oder positivem PHQ-9-Item 9

## Klientenakte & Warteliste
- Stammdaten in Bereichen: Person (inkl. Geschlecht für die Anrede), Kostenträger (Selbstzahler, PKV, Beihilfe,
  Zusatzversicherung), Notfallkontakt, ärztliche Versorgung/Vorbehandlung, Klinisches
- Klientenakte mit Reitern *Sitzungen & Rechnungen*, *Stammdaten & Kostenträger*, *Dokumente*
- Dokumentenablage: Arztbriefe, Befunde, unterschriebene Scans usw. werden **verschlüsselt** in der Akte gespeichert
  und nur zum Ansehen kurz entschlüsselt; erstellte Formulare erscheinen in derselben Liste
- **Warteliste** (Menü Klienten): Interessenten mit Anliegen, Erreichbarkeit, Dringlichkeit und Status;
  Übernahme als Klient mit einem Klick; Zahl offener Einträge im Menü

## Formulare & Briefe
Menü **Klienten → Formulare & Briefe** (`document_pdf.py`, Vorlagen in `document_templates.py`):
- Behandlungsvertrag mit Honorarvereinbarung, DSGVO-Einwilligung, Schweigepflichtentbindung,
  Teilnahmebestätigung, Bericht für Kostenträger, Konsiliarbericht/Arztbrief
- Automatisch befüllt mit Klienten-, Praxis-, Honorar- und Sitzungsdaten; Text vor dem Erstellen frei änderbar
- Unterschrift per Finger/Stift/Maus direkt im Programm oder leere Linie zum Ausdrucken
- PDF im gleichen Briefkopf wie die Rechnungen, abgelegt unter `Klienten/<Name>/Dokumente`
- Eigene Vorlagentexte über den Reiter *Vorlage bearbeiten*; Platzhalter in `{geschweiften Klammern}`

Die mitgelieferten Texte sind Muster und ersetzen keine Rechtsberatung.

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
