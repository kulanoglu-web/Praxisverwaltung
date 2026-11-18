"""Einnahmen-Überschuss-Rechnung (EÜR) und Kassenbuch – reine Berechnung ohne Qt, einzeln testbar.

Grundsätze (vereinfachte Darstellung, keine Steuerberatung):
- Zuflussprinzip: Einnahmen zählen im Jahr des Zahlungseingangs (paid_date), Ausgaben im Jahr der Zahlung.
- Heilberufliche Leistungen sind nach § 4 Nr. 14 UStG umsatzsteuerfrei; ein Vorsteuerabzug entfällt,
  daher werden Ausgaben mit dem Bruttobetrag erfasst.
- Bareinnahmen, die einer Rechnung zugeordnet und dort als bezahlt markiert sind, werden nicht doppelt gezählt.
"""
from datetime import date

EXPENSE_CATEGORIES = [
    "Miete / Raumkosten", "Nebenkosten / Energie", "Fortbildung / Supervision", "Fachliteratur",
    "Büromaterial / Porto", "Software / IT / Geräte", "Telefon / Internet", "Versicherungen / Beiträge",
    "Fahrtkosten", "Werbung / Website", "Bankgebühren", "Sonstiges",
]
PAYMENT_METHODS = ["Überweisung", "Lastschrift", "Karte", "Bar"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _year(iso):
    try:
        return int(str(iso)[:4])
    except ValueError:
        return None


def income_entries(invoices, cash, year):
    """Alle Zuflüsse eines Jahres: bezahlte Rechnungen (nach Zahlungsdatum) + freie Bareinnahmen."""
    out = []
    numbers_paid = set()
    for inv in invoices:
        if inv.get("status") == "bezahlt" and inv.get("paid_date") and _year(inv["paid_date"]) == year:
            out.append({"date": inv["paid_date"], "text": f"Rechnung {inv.get('number', '')}", "amount": float(inv.get("amount", 0) or 0),
                        "source": "Rechnung", "ref": inv.get("number", ""), "client": inv.get("client", "")})
            numbers_paid.add(inv.get("number", ""))
    for c in cash:
        if c.get("kind") != "Einnahme" or _year(c.get("date")) != year:
            continue
        if c.get("invoice") and c["invoice"] in numbers_paid:
            continue   # schon über die Rechnung gezählt
        out.append({"date": c["date"], "text": c.get("text", "Bareinnahme"), "amount": float(c.get("amount", 0) or 0),
                    "source": "Bareinnahme", "ref": c.get("invoice", ""), "client": ""})
    return sorted(out, key=lambda e: e["date"])


def expense_entries(expenses, year):
    return sorted([e for e in expenses if _year(e.get("date")) == year], key=lambda e: e.get("date", ""))


def euer_summary(invoices, expenses, cash, year):
    inc = income_entries(invoices, cash, year)
    exp = expense_entries(expenses, year)
    months = []
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        i = round(sum(e["amount"] for e in inc if e["date"].startswith(key)), 2)
        a = round(sum(float(e.get("amount", 0) or 0) for e in exp if e.get("date", "").startswith(key)), 2)
        months.append({"month": MONTHS[m - 1], "income": i, "expenses": a, "result": round(i - a, 2)})
    cats = {}
    for e in exp:
        cats[e.get("category") or "Sonstiges"] = round(cats.get(e.get("category") or "Sonstiges", 0) + float(e.get("amount", 0) or 0), 2)
    ti = round(sum(m["income"] for m in months), 2); ta = round(sum(m["expenses"] for m in months), 2)
    return {"year": year, "months": months, "categories": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
            "income_total": ti, "expense_total": ta, "result": round(ti - ta, 2), "income": inc, "expenses": exp}


def cash_book(expenses, cash, year, opening=0.0):
    """Kassenbuch: alle Barbewegungen eines Jahres mit laufendem Bestand."""
    rows = []
    for e in expenses:
        if e.get("payment") == "Bar" and _year(e.get("date")) == year:
            rows.append({"date": e["date"], "text": f"{e.get('category', '')}: {e.get('description', '')}".strip(": "), "in": 0.0, "out": float(e.get("amount", 0) or 0), "id": e.get("id"), "kind": "Ausgabe"})
    for c in cash:
        if _year(c.get("date")) == year:
            amt = float(c.get("amount", 0) or 0)
            rows.append({"date": c["date"], "text": c.get("text", ""), "in": amt if c.get("kind") == "Einnahme" else 0.0,
                         "out": amt if c.get("kind") != "Einnahme" else 0.0, "id": c.get("id"), "kind": c.get("kind", "Einnahme")})
    rows.sort(key=lambda r: (r["date"], r["id"] or ""))
    bal = float(opening or 0)
    for r in rows:
        bal = round(bal + r["in"] - r["out"], 2); r["balance"] = bal
    return rows, bal


def export_xlsx(path, summary, with_names=False, cash_rows=None, opening=0.0):
    """Export für den Steuerberater: Übersicht, Einnahmen, Ausgaben, Kassenbuch. Ohne Klientennamen (Standard)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    bold = Font(bold=True); head = PatternFill("solid", fgColor="E3EBE5"); money = '#,##0.00 "€"'
    wb = Workbook(); ws = wb.active; ws.title = "Übersicht"
    ws.append([f"Einnahmen-Überschuss-Rechnung {summary['year']}"]); ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Zuflussprinzip; umsatzsteuerfrei nach § 4 Nr. 14 UStG; Ausgaben brutto. Vorläufige Übersicht – keine Steuerberatung."]); ws.append([])
    ws.append(["Monat", "Einnahmen", "Ausgaben", "Ergebnis"])
    for c in ws[4]: c.font = bold; c.fill = head
    for m in summary["months"]:
        ws.append([m["month"], m["income"], m["expenses"], m["result"]])
    ws.append(["Summe", summary["income_total"], summary["expense_total"], summary["result"]])
    for c in ws[ws.max_row]: c.font = bold
    ws.append([]); ws.append(["Ausgaben nach Kategorie", "Betrag"])
    for c in ws[ws.max_row]: c.font = bold; c.fill = head
    for k, v in summary["categories"].items(): ws.append([k, v])
    for row in ws.iter_rows(min_row=5):
        for c in row[1:4]:
            if isinstance(c.value, (int, float)): c.number_format = money
    ws.column_dimensions["A"].width = 34
    for col in "BCD": ws.column_dimensions[col].width = 16

    wi = wb.create_sheet("Einnahmen")
    wi.append(["Zahlungsdatum", "Art", "Beleg / Rechnung", "Text"] + (["Klient"] if with_names else []) + ["Betrag"])
    for c in wi[1]: c.font = bold; c.fill = head
    for e in summary["income"]:
        wi.append([e["date"], e["source"], e["ref"], e["text"]] + ([e["client"]] if with_names else []) + [e["amount"]])
        wi.cell(wi.max_row, wi.max_column).number_format = money
    we = wb.create_sheet("Ausgaben")
    we.append(["Datum", "Kategorie", "Beschreibung", "Zahlart", "Beleg vorhanden", "Betrag"])
    for c in we[1]: c.font = bold; c.fill = head
    for e in summary["expenses"]:
        we.append([e.get("date", ""), e.get("category", ""), e.get("description", ""), e.get("payment", ""), "ja" if e.get("receipt") else "nein", float(e.get("amount", 0) or 0)])
        we.cell(we.max_row, 6).number_format = money
    if cash_rows is not None:
        wk = wb.create_sheet("Kassenbuch")
        wk.append(["Datum", "Text", "Einnahme", "Ausgabe", "Bestand"])
        for c in wk[1]: c.font = bold; c.fill = head
        wk.append(["", "Anfangsbestand", "", "", float(opening or 0)])
        for r in cash_rows:
            wk.append([r["date"], r["text"], r["in"] or None, r["out"] or None, r["balance"]])
        for row in wk.iter_rows(min_row=2):
            for c in row[2:5]: c.number_format = money
    for sh in (wi, we) + ((wk,) if cash_rows is not None else ()):
        sh.freeze_panes = "A2"; sh.column_dimensions["A"].width = 14
        for col in "BCDEFG": sh.column_dimensions[col].width = 22
    wb.save(path)
    return str(path)


def export_csv(path, summary):
    """Einfache Buchungsliste (Semikolon, deutsches Zahlenformat) – lässt sich in gängige Buchhaltungsprogramme importieren."""
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Datum", "Typ", "Kategorie/Art", "Beleg", "Text", "Betrag"])
        rows = [(e["date"], "Einnahme", e["source"], e["ref"], e["text"], e["amount"]) for e in summary["income"]]
        rows += [(e.get("date", ""), "Ausgabe", e.get("category", ""), e.get("id", ""), e.get("description", ""), -float(e.get("amount", 0) or 0)) for e in summary["expenses"]]
        for r in sorted(rows, key=lambda r: r[0]):
            w.writerow(list(r[:5]) + [f"{r[5]:.2f}".replace(".", ",")])
    return str(path)
