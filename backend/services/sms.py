# backend/services/sms.py
import logging
import os
from twilio.rest import Client

log = logging.getLogger(__name__)

def send_sms(to: str, message: str) -> None:
    to = (to or "").strip()
    if not to:
        log.warning("SMS not sent: missing destination number. Message=%r", message)
        return

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
    from_num    = os.getenv("TWILIO_FROM")

    if not (account_sid and auth_token and from_num):
        log.warning("Twilio env vars missing; logging SMS instead. To=%s, msg=%r", to, message)
        log.info("📲 SMS to %s: %s", to, message)
        return

    client = Client(account_sid, auth_token)
    msg = client.messages.create(
        body=message,
        from_=from_num,
        to=to,
    )
    log.info("📲 Twilio SMS sent: sid=%s to=%s", msg.sid, to)
