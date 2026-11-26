"""E-Mail-Versand (SMTP) für Rechnungen und Testmail.

Ohne Qt, dadurch einzeln testbar. Zugangsdaten kommen als Dictionary:
host, port, security ("SSL/TLS", "STARTTLS", "keine"), user, password, sender, sender_name.
"""
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from pathlib import Path

SECURITY = ("SSL/TLS", "STARTTLS", "keine")

# Häufige Anbieter: Server, Port, Verschlüsselung. Alles bleibt in den Einstellungen änderbar.
PRESETS = {
    "Eigener Server": ("", 465, "SSL/TLS"),
    "IONOS (1&1)": ("smtp.ionos.de", 465, "SSL/TLS"),
    "Strato": ("smtp.strato.de", 465, "SSL/TLS"),
    "GMX": ("mail.gmx.net", 587, "STARTTLS"),
    "WEB.DE": ("smtp.web.de", 587, "STARTTLS"),
    "T-Online": ("securesmtp.t-online.de", 465, "SSL/TLS"),
    "Gmail (App-Passwort nötig)": ("smtp.gmail.com", 465, "SSL/TLS"),
    "Outlook / Hotmail": ("smtp-mail.outlook.com", 587, "STARTTLS"),
}

DEFAULT_SUBJECT = "Ihre Rechnung {nummer}"
DEFAULT_BODY = (
    "{anrede} {nachname},\n\n"
    "anbei erhalten Sie Ihre Rechnung {nummer} vom {datum} über {betrag} als PDF.\n\n"
    "Bei Fragen erreichen Sie mich gern telefonisch oder per E-Mail.\n\n"
    "Mit freundlichen Grüßen\n{praxisinhaber}\n{praxisname}"
)


class MailError(Exception):
    """Verständliche Fehlermeldung für die Oberfläche."""


def config_key(cfg):
    """Kennung der Zugangsdaten. Ändert sich etwas, muss erneut eine Testmail gesendet werden."""
    return "|".join(str(cfg.get(k, "")).strip().lower() for k in ("host", "port", "security", "user", "sender"))


def build_message(cfg, to, subject, body, attachments=(), bcc_self=False):
    sender = (cfg.get("sender") or cfg.get("user") or "").strip()
    if not sender or "@" not in sender:
        raise MailError("Bitte in den Einstellungen eine gültige Absenderadresse eintragen.")
    recipients = [a.strip() for a in str(to).replace(";", ",").split(",") if a.strip()]
    if not recipients or any("@" not in a for a in recipients):
        raise MailError("Bitte eine gültige Empfängeradresse angeben.")
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("sender_name", "") or "", sender))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[1])
    msg.set_content(body)
    for path in attachments:
        p = Path(path)
        if not p.is_file():
            raise MailError(f"Anhang nicht gefunden:\n{p}")
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    envelope = list(recipients) + ([sender] if bcc_self and sender not in recipients else [])
    return msg, sender, envelope


def send(cfg, to, subject, body, attachments=(), bcc_self=False, timeout=25, _smtp_factory=None):
    """Sendet die Nachricht. Wirft MailError mit deutschem Hinweistext bei Problemen."""
    msg, sender, envelope = build_message(cfg, to, subject, body, attachments, bcc_self)
    host = (cfg.get("host") or "").strip()
    if not host:
        raise MailError("Bitte in den Einstellungen den Postausgangsserver (SMTP) eintragen.")
    try:
        port = int(cfg.get("port") or 0) or (465 if cfg.get("security") == "SSL/TLS" else 587)
    except ValueError:
        raise MailError("Der Port muss eine Zahl sein (meist 465 oder 587).")
    security = cfg.get("security", "SSL/TLS")
    context = ssl.create_default_context()
    try:
        if _smtp_factory:
            server = _smtp_factory(host, port, security)
        elif security == "SSL/TLS":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            server.ehlo()
            if security == "STARTTLS":
                server.starttls(context=context)
                server.ehlo()
            if cfg.get("user"):
                server.login(cfg.get("user", ""), cfg.get("password", ""))
            server.send_message(msg, from_addr=sender, to_addrs=envelope)
    except MailError:
        raise
    except smtplib.SMTPAuthenticationError:
        raise MailError("Anmeldung beim Mailserver fehlgeschlagen. Bitte Benutzername und Passwort prüfen.\n"
                        "Bei Gmail und manchen Anbietern ist ein eigenes App-Passwort nötig.")
    except smtplib.SMTPRecipientsRefused:
        raise MailError("Der Mailserver hat die Empfängeradresse abgelehnt. Bitte Adresse prüfen.")
    except smtplib.SMTPSenderRefused:
        raise MailError("Der Mailserver akzeptiert die Absenderadresse nicht. Sie muss zum Postfach passen.")
    except (ssl.SSLError, smtplib.SMTPNotSupportedError) as e:
        raise MailError(f"Verschlüsselung passt nicht zum Server ({e.__class__.__name__}). "
                        "Bitte SSL/TLS mit Port 465 oder STARTTLS mit Port 587 versuchen.")
    except (TimeoutError, OSError) as e:
        raise MailError(f"Keine Verbindung zum Mailserver {host}:{port}.\n"
                        f"Bitte Server, Port und Internetverbindung prüfen.\n\n({e})")
    except smtplib.SMTPException as e:
        raise MailError(f"Der Mailserver hat die Nachricht abgelehnt:\n{e}")


def fill(template, values):
    """Platzhalter {name} ersetzen; unbekannte Platzhalter bleiben stehen."""
    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    try:
        return str(template).format_map(_Safe(values))
    except (ValueError, IndexError):
        return str(template)
