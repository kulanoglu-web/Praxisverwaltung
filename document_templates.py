"""Standardvorlagen für Praxisdokumente.

Die Texte sind Muster und ersetzen keine Rechtsberatung. In PraxisPro kann jede Vorlage
bearbeitet und als eigene Standardvorlage gespeichert werden (Einstellung "doc_tpl_<schlüssel>").

Platzhalter in geschweiften Klammern werden beim Befüllen ersetzt (siehe PLACEHOLDERS).
Unbekannte Platzhalter bleiben stehen, damit nichts unbemerkt verschwindet.
"""

PLACEHOLDERS = {
    "klient_name": "Vor- und Nachname",
    "klient_vorname": "Vorname",
    "klient_nachname": "Nachname",
    "klient_geburtsdatum": "Geburtsdatum",
    "klient_adresse": "Anschrift",
    "klient_telefon": "Telefon",
    "klient_email": "E-Mail",
    "anrede": "z. B. Sehr geehrte Frau Muster",
    "diagnose": "hinterlegte Diagnose (Klientenakte)",
    "therapeut": "Name Therapeut/in (Praxiseinstellungen)",
    "qualifikation": "Qualifikation (Praxiseinstellungen)",
    "praxis_name": "Praxisname",
    "praxis_adresse": "Praxisanschrift",
    "praxis_telefon": "Praxistelefon",
    "praxis_email": "Praxis-E-Mail",
    "ort": "Ort (aus Praxisanschrift)",
    "datum": "heutiges Datum",
    "empfaenger": "Empfänger (Feld „Empfänger“)",
    "honorar_tabelle": "Honorare aus den Einstellungen als Tabelle",
    "absagefrist": "Absagefrist (Standard 24 Stunden)",
    "erste_sitzung": "Datum der ersten Sitzung",
    "letzte_sitzung": "Datum der letzten Sitzung",
    "anzahl_sitzungen": "Anzahl dokumentierter Sitzungen",
    "sitzungsliste": "Tabelle aller Sitzungen (Datum, Art, Dauer)",
}

# signatures: wer unterschreibt. "client" = Klient/in, "therapist" = Therapeut/in
# recipient: True, wenn ein Empfänger (Arzt, Versicherung, Person) angegeben werden soll
TEMPLATES = {
    "vertrag": {
        "title": "Behandlungsvertrag und Honorarvereinbarung",
        "signatures": ["client", "therapist"],
        "recipient": False,
        "text": """Zwischen {klient_name}, geb. {klient_geburtsdatum}, wohnhaft {klient_adresse}
(nachfolgend „Klient/in“)
und {therapeut}, {qualifikation}, {praxis_name}, {praxis_adresse}
(nachfolgend „Praxis“) wird folgende Vereinbarung geschlossen:

## 1. Gegenstand
Die Praxis erbringt psychologische Beratung bzw. Therapie im Rahmen der vereinbarten Termine. Inhalt, Ziele und Methoden werden gemeinsam besprochen und im Verlauf angepasst. Ein bestimmter Erfolg kann nicht zugesichert werden.

## 2. Honorar
Die Leistungen werden privat in Rechnung gestellt. Es gelten folgende Honorare:

{honorar_tabelle}

Die Rechnungsstellung erfolgt nach der Sitzung bzw. gesammelt. Der Rechnungsbetrag ist innerhalb von 14 Tagen zu begleichen. Gemäß § 4 Nr. 14 UStG wird keine Umsatzsteuer erhoben.

## 3. Kostenerstattung
Die Praxis rechnet nicht direkt mit gesetzlichen Krankenkassen ab. Ob eine private Krankenversicherung, Beihilfe oder Zusatzversicherung Kosten erstattet, klärt die Klientin bzw. der Klient selbst. Die Zahlungspflicht besteht unabhängig von einer Erstattung.

## 4. Terminabsagen und Ausfallhonorar
Vereinbarte Termine sind verbindlich für die Klientin bzw. den Klienten reserviert. Termine, die nicht mindestens {absagefrist} vorher abgesagt werden, können in Höhe des vereinbarten Honorars in Rechnung gestellt werden, sofern der Termin nicht anderweitig vergeben werden kann. Dies gilt nicht, wenn die Absage unverschuldet und unvermeidbar war.

## 5. Schweigepflicht und Datenschutz
Alle Inhalte der Sitzungen unterliegen der Schweigepflicht. Informationen werden nur mit ausdrücklicher, schriftlicher Einwilligung an Dritte weitergegeben, sofern keine gesetzliche Offenbarungspflicht besteht. Die Dokumentation wird verschlüsselt gespeichert und nach Ablauf der Aufbewahrungsfrist (in der Regel 10 Jahre) gelöscht. Einzelheiten regelt die gesonderte Einwilligung zur Datenverarbeitung.

## 6. Notfälle
Die Praxis bietet keine Notfallversorgung an. In akuten Krisen wenden Sie sich bitte an den ärztlichen Bereitschaftsdienst (116 117), die Telefonseelsorge (0800 111 0 111) oder den Notruf 112.

## 7. Beendigung
Die Zusammenarbeit kann von beiden Seiten jederzeit ohne Angabe von Gründen beendet werden. Bereits erbrachte Leistungen sind zu vergüten.

Mit meiner Unterschrift bestätige ich, diese Vereinbarung gelesen und verstanden zu haben und ein Exemplar erhalten zu haben.""",
    },
    "schweigepflicht": {
        "title": "Entbindung von der Schweigepflicht",
        "signatures": ["client"],
        "recipient": True,
        "text": """Ich, {klient_name}, geb. {klient_geburtsdatum}, wohnhaft {klient_adresse},

entbinde hiermit {therapeut}, {praxis_name}, gegenüber

{empfaenger}

von der Schweigepflicht.

## Umfang der Entbindung (bitte ankreuzen)
[ ] Tatsache der Behandlung / Beratung und Behandlungszeitraum
[ ] Diagnosen und Befunde
[ ] Behandlungsverlauf und Behandlungsplanung
[ ] Übersendung schriftlicher Berichte
[ ] Mündlicher bzw. telefonischer Austausch

## Zweck
______________________________________________________________

## Gültigkeit
Die Entbindung gilt bis auf Widerruf, längstens bis zum ____________________. Ich kann sie jederzeit ganz oder teilweise mit Wirkung für die Zukunft widerrufen. Ich wurde darauf hingewiesen, dass die Entbindung freiwillig ist und mir aus einer Verweigerung keine Nachteile in der Behandlung entstehen.""",
    },
    "datenschutz": {
        "title": "Einwilligung in die Verarbeitung personenbezogener Daten",
        "signatures": ["client"],
        "recipient": False,
        "text": """Klient/in: {klient_name}, geb. {klient_geburtsdatum}

## Verantwortliche Stelle
{therapeut}, {praxis_name}, {praxis_adresse}, Telefon {praxis_telefon}, E-Mail {praxis_email}

## Welche Daten verarbeitet werden
Für die Beratung bzw. Therapie und die Abrechnung werden Kontaktdaten (Name, Anschrift, Geburtsdatum, Telefon, E-Mail), Termin- und Abrechnungsdaten sowie Gesundheitsdaten (z. B. Anliegen, Befunde, Diagnosen, Sitzungsdokumentation) verarbeitet.

## Zweck und Rechtsgrundlage
Die Daten werden ausschließlich zur Durchführung und Dokumentation der Behandlung sowie zur Abrechnung verarbeitet (Art. 6 Abs. 1 lit. b und Art. 9 Abs. 2 lit. a und h DSGVO). Die Dokumentation wird in der Regel 10 Jahre nach Abschluss der Behandlung aufbewahrt und danach gelöscht.

## Speicherung und Sicherheit
Die Daten werden lokal auf dem Praxisrechner verschlüsselt gespeichert und nicht an Cloud-Dienste übertragen. Eine Weitergabe an Dritte erfolgt nur mit gesonderter Schweigepflichtentbindung oder aufgrund gesetzlicher Pflichten.

## Kommunikation (bitte ankreuzen)
[ ] Terminabsprachen per E-Mail sind einverstanden
[ ] Terminabsprachen per SMS / Messenger sind einverstanden
[ ] Rechnungen dürfen per E-Mail versendet werden
Hinweis: Unverschlüsselte E-Mails können von Dritten gelesen werden. Inhalte der Sitzungen werden nicht per E-Mail besprochen.

## Ihre Rechte
Sie haben das Recht auf Auskunft, Berichtigung, Löschung (soweit keine Aufbewahrungspflicht besteht), Einschränkung der Verarbeitung, Datenübertragbarkeit sowie Beschwerde bei einer Datenschutz-Aufsichtsbehörde. Diese Einwilligung ist freiwillig und kann jederzeit mit Wirkung für die Zukunft widerrufen werden.

Ich habe diese Informationen gelesen und willige in die beschriebene Verarbeitung meiner Daten ein.""",
    },
    "teilnahme": {
        "title": "Teilnahmebestätigung",
        "signatures": ["therapist"],
        "recipient": False,
        "text": """Hiermit wird bestätigt, dass {klient_name}, geb. {klient_geburtsdatum}, im Zeitraum vom {erste_sitzung} bis {letzte_sitzung} an insgesamt {anzahl_sitzungen} Sitzungen in meiner Praxis teilgenommen hat.

{sitzungsliste}

Die Bestätigung wird auf Wunsch der Klientin bzw. des Klienten ausgestellt. Sie enthält keine Angaben zu Inhalten oder Diagnosen.""",
    },
    "bericht": {
        "title": "Bericht zur Vorlage beim Kostenträger",
        "signatures": ["therapist"],
        "recipient": True,
        "text": """Betreff: {klient_name}, geb. {klient_geburtsdatum}
Eine Schweigepflichtentbindung gegenüber dem Empfänger liegt vor.

## Anlass der Behandlung
______________________________________________________________

## Diagnose(n)
{diagnose}

## Behandlungsverlauf
Behandlungszeitraum: {erste_sitzung} bis {letzte_sitzung}, {anzahl_sitzungen} Sitzungen.
______________________________________________________________

## Aktueller Stand und Prognose
______________________________________________________________

## Empfehlung / weiterer Behandlungsbedarf
______________________________________________________________

Für Rückfragen stehe ich gern zur Verfügung.""",
    },
    "arztbrief": {
        "title": "Konsiliarbericht / Arztbrief",
        "signatures": ["therapist"],
        "recipient": True,
        "text": """{anrede},

ich berichte Ihnen über {klient_name}, geb. {klient_geburtsdatum}, die/der sich seit dem {erste_sitzung} in meiner Praxis in Behandlung befindet. Eine Schweigepflichtentbindung liegt vor.

## Fragestellung
______________________________________________________________

## Psychischer Befund
______________________________________________________________

## Diagnose(n) / Verdachtsdiagnose(n)
{diagnose}

## Bitte um ärztliche Abklärung
[ ] Ausschluss körperlicher Ursachen
[ ] Prüfung einer medikamentösen Mitbehandlung
[ ] Sonstiges: ______________________________

Mit freundlichen kollegialen Grüßen""",
    },
}

ORDER = ["vertrag", "datenschutz", "schweigepflicht", "teilnahme", "bericht", "arztbrief"]


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(text, values):
    """Platzhalter ersetzen; unbekannte bleiben sichtbar stehen."""
    try:
        return str(text).format_map(_Keep(values))
    except (ValueError, IndexError):
        # einzelne geschweifte Klammern im Text: Platzhalter einzeln ersetzen
        out = str(text)
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
        return out
