"""Frei verwendbare Screening-Fragebögen mit Auswertung.

PHQ-9 und GAD-7 (Spitzer, Kroenke, Williams, Löwe; deutsche Version: Löwe et al.) dürfen laut
Urhebern ohne Genehmigung vervielfältigt und verwendet werden. Lizenzpflichtige Verfahren
(z. B. BDI-II, SCL-90-R) sind bewusst NICHT enthalten.

Screening-Ergebnisse ersetzen keine Diagnose.
"""

ANSWERS = ["Überhaupt nicht", "An einzelnen Tagen", "An mehr als der Hälfte der Tage", "Beinahe jeden Tag"]
STEM = "Wie oft fühlten Sie sich im Verlauf der letzten 2 Wochen durch die folgenden Beschwerden beeinträchtigt?"

QUESTIONNAIRES = {
    "PHQ-9": {
        "name": "PHQ-9 – Depressivität",
        "stem": STEM,
        "items": [
            "Wenig Interesse oder Freude an Ihren Tätigkeiten",
            "Niedergeschlagenheit, Schwermut oder Hoffnungslosigkeit",
            "Schwierigkeiten, ein- oder durchzuschlafen, oder vermehrter Schlaf",
            "Müdigkeit oder Gefühl, keine Energie zu haben",
            "Verminderter Appetit oder übermäßiges Bedürfnis zu essen",
            "Schlechte Meinung von sich selbst; Gefühl, ein Versager zu sein oder die Familie enttäuscht zu haben",
            "Schwierigkeiten, sich auf etwas zu konzentrieren, z. B. beim Zeitunglesen oder Fernsehen",
            "Waren Ihre Bewegungen oder Ihre Sprache so verlangsamt, dass es auch anderen auffallen würde? "
            "Oder waren Sie im Gegenteil „zappelig“ oder ruhelos und hatten dadurch einen stärkeren Bewegungsdrang als sonst?",
            "Gedanken, dass Sie lieber tot wären oder sich Leid zufügen möchten",
        ],
        # (Obergrenze inklusive, Bezeichnung)
        "bands": [(4, "minimal"), (9, "leicht"), (14, "mittelgradig"), (19, "ausgeprägt"), (27, "schwer")],
        "max": 27,
        "risk_item": 8,   # Index von Item 9: jeder Wert > 0 -> Suizidalität aktiv abklären
    },
    "GAD-7": {
        "name": "GAD-7 – Ängstlichkeit",
        "stem": STEM,
        "items": [
            "Nervosität, Ängstlichkeit oder Anspannung",
            "Nicht in der Lage sein, Sorgen zu stoppen oder zu kontrollieren",
            "Übermäßige Sorgen bezüglich verschiedener Angelegenheiten",
            "Schwierigkeiten zu entspannen",
            "Rastlosigkeit, sodass Stillsitzen schwerfällt",
            "Schnelle Verärgerung oder Gereiztheit",
            "Gefühl der Angst, so als würde etwas Schlimmes passieren",
        ],
        "bands": [(4, "minimal"), (9, "leicht"), (14, "mittelgradig"), (21, "schwer")],
        "max": 21,
        "risk_item": None,
    },
}


def score(kind, answers):
    """answers: Liste mit Werten 0..3 (None = nicht beantwortet). Liefert dict mit Summe, Schweregrad, Hinweisen."""
    q = QUESTIONNAIRES[kind]
    if len(answers) != len(q["items"]):
        raise ValueError(f"{kind}: {len(q['items'])} Antworten erwartet, {len(answers)} erhalten")
    missing = [i + 1 for i, a in enumerate(answers) if a is None]
    vals = [int(a) for a in answers if a is not None]
    if any(v < 0 or v > 3 for v in vals):
        raise ValueError("Antwortwerte müssen zwischen 0 und 3 liegen")
    total = sum(vals)
    level = severity(kind, total)
    notes = []
    if missing:
        notes.append(f"Nicht beantwortet: Item {', '.join(map(str, missing))} – Summe nur eingeschränkt verwertbar.")
    ri = q["risk_item"]
    if ri is not None and answers[ri] not in (None, 0):
        notes.append("Item 9 positiv: Suizidalität im Gespräch aktiv abklären und dokumentieren.")
    return {"score": total, "max": q["max"], "severity": level, "missing": missing, "notes": notes, "complete": not missing}


def severity(kind, total):
    for upper, label in QUESTIONNAIRES[kind]["bands"]:
        if total <= upper:
            return label
    return QUESTIONNAIRES[kind]["bands"][-1][1]
