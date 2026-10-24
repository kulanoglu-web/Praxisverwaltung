"""Glossar psychotherapierelevanter Störungsbilder (fachlich + patientenverständlich).

Klassifikation: ICD-10-GM, ICD-11 (WHO) und DSM-5-TR. Alle Inhalte sind eine kompakte Orientierungs-
und Gesprächshilfe, KEINE Diagnosestellung und kein Ersatz für Leitlinien, Diagnostik und ärztliche
Abklärung. Therapieansätze sind schulenspezifische Herangehensweisen, keine Behandlungsanweisung.
"""

SCHULEN = {
    "VT": "Verhaltenstherapie (KVT)",
    "TP": "Tiefenpsychologisch fundiert / psychodynamisch",
    "SYS": "Systemische Therapie",
    "HUM": "Humanistisch / Gesprächs- & emotionsfokussiert",
}


def E(name, gruppe, icd10, icd11, dsm5, kurz, symptome, etio, etio_einfach, einfach, vt, tp, sys, hum, hinweis=""):
    return {"name": name, "gruppe": gruppe, "icd10": icd10, "icd11": icd11, "dsm5": dsm5, "kurz": kurz,
            "symptome": symptome, "etio": etio, "etio_einfach": etio_einfach, "einfach": einfach,
            "therapie": {"VT": vt, "TP": tp, "SYS": sys, "HUM": hum}, "hinweis": hinweis}


def alle():
    from glossar_teil1 import LISTE as a
    from glossar_teil2 import LISTE as b
    from glossar_teil3 import LISTE as c
    from glossar_teil4 import LISTE as d
    from glossar_teil5 import LISTE as e
    return sorted(a + b + c + d + e, key=lambda x: (x["gruppe"], x["name"]))
