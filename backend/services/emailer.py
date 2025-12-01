# backend/services/emailer.py
import os
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.utils import parseaddr

log = logging.getLogger(__name__)


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Environment-driven SMTP config (Mailtrap + optional Ethereal)
# ---------------------------------------------------------------------------

# Ethereal creds (only if you really use Ethereal – separate from Mailtrap)
ETHEREAL_USER = os.getenv("ETHEREAL_USER") or ""
ETHEREAL_PASS = os.getenv("ETHEREAL_PASS") or ""

# Only treat as Ethereal when USE_ETHEREAL=1 **and** ETHEREAL_* are set
USE_ETHEREAL = (
    _truthy(os.getenv("USE_ETHEREAL"))
    and bool(ETHEREAL_USER and ETHEREAL_PASS)
)

# SMTP username/password:
#   - Prefer explicit SMTP_* env
#   - Fall back to MAIL_* (Mailtrap)
#   - Finally Ethereal if enabled
SMTP_USER = (
    os.getenv("SMTP_USER")
    or os.getenv("MAIL_USERNAME")
    or (ETHEREAL_USER if USE_ETHEREAL else "")
)
SMTP_PASS = (
    os.getenv("SMTP_PASS")
    or os.getenv("MAIL_PASSWORD")
    or (ETHEREAL_PASS if USE_ETHEREAL else "")
)

# Host/port: explicit override → MAIL_* → Ethereal default → localhost
SMTP_HOST = (
    os.getenv("SMTP_HOST")
    or os.getenv("MAIL_SERVER")
    or ("smtp.ethereal.email" if USE_ETHEREAL else "localhost")
)
SMTP_PORT = int(
    os.getenv("SMTP_PORT")
    or os.getenv("MAIL_PORT")
    or (587 if USE_ETHEREAL else 25)
)

# From address:
#   1) EMAIL_FROM (your project-level setting)
#   2) FROM_EMAIL
#   3) MAIL_DEFAULT_SENDER
#   4) SMTP_USER / ETHEREAL_USER as last resort
FROM_EMAIL = (
    os.getenv("EMAIL_FROM")
    or os.getenv("FROM_EMAIL")
    or os.getenv("MAIL_DEFAULT_SENDER")
    or SMTP_USER
    or ETHEREAL_USER
    or ""
).strip()

# TLS / SSL flags: support both SMTP_* and MAIL_* env names
USE_TLS = _truthy(
    os.getenv("SMTP_USE_TLS")
    or os.getenv("MAIL_USE_TLS")
    or "false"
)
USE_SSL = _truthy(
    os.getenv("SMTP_USE_SSL")
    or os.getenv("MAIL_USE_SSL")
    or "false"
)

DEBUG_EMAIL = _truthy(os.getenv("DEBUG_EMAIL"))


def _ensure_addr(label: str, value: str) -> str:
    """
    Basic sanity-check on email addresses (must contain @).
    Raises RuntimeError if empty/invalid.
    """
    value = (value or "").strip()
    if not value:
        raise RuntimeError(f"{label} address is empty")
    name, addr = parseaddr(value)
    if "@" not in addr:
        raise RuntimeError(f"{label} address looks invalid: {value}")
    return addr


def get_smtp_config() -> dict:
    """
    Return current SMTP config (excluding password) for debugging / health checks.
    """
    return {
        "host": SMTP_HOST,
        "port": SMTP_PORT,
        "user_set": bool(SMTP_USER),
        "use_tls": USE_TLS,
        "use_ssl": USE_SSL,
        "from_email": FROM_EMAIL,
        "use_ethereal": USE_ETHEREAL,
        "debug_email": DEBUG_EMAIL,
    }


def send_email(to: str, subject: str, html: str, text: str | None = None):
    """
    Send a simple email via raw SMTP (no Flask-Mail).

    Args:
        to:     recipient email address
        subject:email subject
        html:   HTML body
        text:   optional plain-text version (if omitted, html is used as body)

    Returns:
        (accepted: bool, result)
        - accepted == True  → SMTP accepted the message (sendmail result == {})
        - accepted == False → result is either sendmail's non-empty dict
                              or an Exception instance if something failed
    """
    sender = _ensure_addr("FROM", FROM_EMAIL)
    rcpt = _ensure_addr("TO", to)
    print(f"Sending email from {sender} to {rcpt} via {SMTP_HOST}:{SMTP_PORT}")
    # For now we keep it simple: single-part HTML (or text if provided)
    body = text or html
    subtype = "plain" if text else "html"
    msg = MIMEText(body, subtype, "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = rcpt
    raw = msg.as_string()

    log.info(
        "SMTP config -> host=%s port=%s user=%s tls=%s ssl=%s from=%s to=%s",
        SMTP_HOST,
        SMTP_PORT,
        "set" if SMTP_USER else "empty",
        USE_TLS,
        USE_SSL,
        sender,
        rcpt,
    )

    server_cls = smtplib.SMTP_SSL if USE_SSL else smtplib.SMTP

    try:
        # context manager ensures quit() runs
        with server_cls(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if DEBUG_EMAIL:
                server.set_debuglevel(1)

            # EHLO + optional STARTTLS
            try:
                server.ehlo()
            except Exception:
                log.debug("EHLO before TLS failed (continuing)")

            if USE_TLS and not USE_SSL:
                context = ssl.create_default_context()
                server.starttls(context=context)
                try:
                    server.ehlo()
                except Exception:
                    log.debug("EHLO after STARTTLS failed (continuing)")

            # Auth if credentials provided
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)

            result = server.sendmail(sender, [rcpt], raw)
            log.info("SMTP sendmail result: %r", result)
            accepted = result == {}
            return accepted, result

    except Exception as exc:
        log.exception("Failed to send email")
        return False, exc
