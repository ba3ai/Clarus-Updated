# backend/routes/chat_routes.py
from __future__ import annotations

import os, re, json, uuid, difflib, math
from datetime import datetime, date
from typing import Any, Dict, Optional, List, Tuple

from flask import Blueprint, request, jsonify, url_for
from flask_login import current_user, login_required
from flask import send_file, redirect  # make sure these are imported at the top

from backend.extensions import db
from backend.services.openai_client import LLMClient
from backend.services.nlp_router import parse_intent as nlp_parse_intent
from urllib.parse import quote
import os, re, json, uuid, difflib, math
import smtplib                      # <-- email support
from email.mime.text import MIMEText
from email.utils import formataddr
from backend.models import User
from backend.services.emailer import send_email  # ✅ use shared email helper
from flask import current_app
import logging

log = logging.getLogger(__name__)


# ---------------- Core models ----------------
from backend.models import (
    Investor,
    Investment,
    PortfolioInvestmentValue,
    Document,
    DocumentShare,
    Statement,
    User as AppUser,
    Notification,
    AdminMessage,  # <-- NEW: mailbox table
)

# ---------------- Snapshot models (string investor fields) ----------------
# - InvestorPeriodBalance: investor, period_date, beginning_balance, ending_balance, management_fees
# - InvestorBalance:       investor, initial_date, current_date, initial_value, current_value, moic, roi_pct, irr_pct
try:
    from backend.models_snapshot import InvestorPeriodBalance
except Exception:
    InvestorPeriodBalance = None  # type: ignore
try:
    from backend.models_snapshot import InvestorBalance
except Exception:
    InvestorBalance = None        # type: ignore

# -----------------------------------------------------------------------------
# Blueprint / client / config
# -----------------------------------------------------------------------------
chat_bp = Blueprint("chat", __name__, url_prefix="/api")

llm = LLMClient()


# ---------------- Email / SMTP config for chatbot ----------------
ADMIN_EMAIL_FALLBACK = os.getenv("ADMIN_EMAIL") or "admin@email.com"

def _get_admin_email() -> str:
    """
    Fetch the first admin user's email from the database.
    """
    try:
        admin_user = User.query.filter(User.user_type == "admin").first()
        if admin_user and admin_user.email:
            return admin_user.email
    except Exception as exc:
        _dprint("Error loading admin email from DB:", exc)

    return ADMIN_EMAIL_FALLBACK


# Ethereal support (same idea as backend/services/emailer.py)
ETHEREAL_USER = os.getenv("ETHEREAL_USER") or ""
ETHEREAL_PASS = os.getenv("ETHEREAL_PASS") or ""
USE_ETHEREAL = bool(ETHEREAL_USER and ETHEREAL_PASS)

EMAIL_FROM = (
    os.getenv("EMAIL_FROM")
    or os.getenv("FROM_EMAIL")
    or os.getenv("MAIL_DEFAULT_SENDER")
    or (ETHEREAL_USER if USE_ETHEREAL else None)
    or ADMIN_EMAIL_FALLBACK
)

SMTP_HOST = (
    os.getenv("SMTP_HOST")
    or os.getenv("MAIL_SERVER")
    or ("smtp.ethereal.email" if USE_ETHEREAL else None)
)

SMTP_PORT = int(
    os.getenv("SMTP_PORT")
    or os.getenv("MAIL_PORT")
    or (587 if USE_ETHEREAL else 25)
)

SMTP_USER = (
    os.getenv("SMTP_USER")
    or os.getenv("MAIL_USERNAME")
    or (ETHEREAL_USER if USE_ETHEREAL else "")
)

SMTP_PASSWORD = (
    os.getenv("SMTP_PASSWORD")
    or os.getenv("SMTP_PASS")
    or os.getenv("MAIL_PASSWORD")
    or (ETHEREAL_PASS if USE_ETHEREAL else "")
)

_tls_raw = os.getenv("SMTP_USE_TLS") or os.getenv("MAIL_USE_TLS") or (
    "1" if USE_ETHEREAL else "0"
)
SMTP_USE_TLS = _tls_raw.strip().lower() not in {"0", "false", ""}

# Optional debug print
print(
    "[CHAT SMTP]",
    "ADMIN_EMAIL_FALLBACK=", ADMIN_EMAIL_FALLBACK,
    "EMAIL_FROM=", EMAIL_FROM,
    "HOST=", SMTP_HOST,
    "PORT=", SMTP_PORT,
    "USER_SET=", bool(SMTP_USER),
    "TLS=", SMTP_USE_TLS,
)
# ---------------------------------------------------------------



CHAT_HISTORY_DIR = os.getenv("CHAT_HISTORY_DIR", "./chat_history")
MAX_TURNS        = int(os.getenv("CHAT_HISTORY_MAX_TURNS", "2"))
GEN_MODEL        = os.getenv("CHAT_GEN_MODEL", "gpt-4o-mini")
CHAT_DEBUG       = os.getenv("CHAT_DEBUG", "0") not in {"0", "false", "False", ""}


UPLOAD_ROOTS     = [p for p in (os.getenv("UPLOAD_ROOTS") or "").split(",") if p.strip()]
if not UPLOAD_ROOTS:
    UPLOAD_ROOTS = [
        os.path.abspath("./uploads"),
        os.path.abspath("./storage/uploads"),
        os.path.abspath("./backend/uploads"),
    ]


def _dprint(*args: Any) -> None:
    """Debug printing when CHAT_DEBUG is enabled."""
    if CHAT_DEBUG:
        print("[CHAT]", *args)


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def _parse_group_members_freeform(text: str) -> List[Dict[str, str]]:
    """
    Accept free-text like:
      Alice Smith, alice@example.com
      Bob <bob@example.com>

    Returns a list of {"name": name, "email": email}
    """
    members: List[Dict[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = EMAIL_RE.search(line)
        if not m:
            continue

        email = m.group(0).strip()
        # Name = everything except the email
        name_part = (line.replace(email, "") or "").strip(" ,<>-")
        members.append({
            "name": name_part or email,
            "email": email,
        })
    return members

def _create_group_request_notification(
    parent_inv: Investor,
    members: List[Dict[str, str]]
) -> Notification:
    """
    parent_inv: the investor who is asking for the group account.
    members: list of {"name": str, "email": str}.
    """
    from backend.extensions import db

    # Use name if available, otherwise email, otherwise a generic label
    display_name = (
        getattr(parent_inv, "name", None)
        or getattr(parent_inv, "email", None)
        or f"Investor #{getattr(parent_inv, 'id', '?')}"
    )

    # Build human-readable message for the admin + UI
    lines = [f"Group account request from {display_name}."]
    lines.append("")
    lines.append("Requested group members:")
    for m in members:
        nm = (m.get("name") or "").strip() or "(no name given)"
        em = (m.get("email") or "").strip()
        if em:
            lines.append(f" - {nm} <{em}>")
    message = "\n".join(lines)

    notif = Notification(
        investor_id=parent_inv.id,
        title="New group account request",
        message=message,
        kind="group_request",
        link_url=None,
    )
    db.session.add(notif)
    db.session.commit()
    return notif


def _get_pending_investor_email_state(tenant: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Look back through recent assistant turns for an email_investors state.
    Used to keep the multi-step admin→investors email flow going across messages.
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        email_state = meta.get("email_investors")
        if email_state:
            return email_state
    return None


def _send_investor_emails(
    subject: str,
    body: str,
    investors: List[Investor],
    user: Dict[str, Any],
) -> bool:
    """
    Send an email from the admin (via chatbot) to one or more investors.
    Returns True if at least one email was sent successfully.

    This still uses raw smtplib for broadcast investor emails.
    """
    if not SMTP_HOST:
        _dprint("Email not sent: SMTP_HOST not configured")
        return False

    # Collect recipient emails
    recipients: List[str] = []
    for inv in investors:
        email = getattr(inv, "email", None)
        if email:
            recipients.append(email)

    if not recipients:
        _dprint("Email not sent: no investor recipients with email")
        return False

    sender = EMAIL_FROM or _get_admin_email()

    # Add a small header so investors know this came via the chatbot/admin
    admin_info = [
        "Message sent via Clarus AI chatbot (from admin)",
        f"- Admin user id: {user.get('id')}",
        f"- Admin email: {user.get('email')}",
        "",
    ]
    full_body = "\n".join(admin_info) + body

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)

            # Send individually so addresses are not exposed
            for rcpt in recipients:
                msg = MIMEText(full_body)
                msg["Subject"] = subject
                msg["From"] = formataddr(("Clarus Admin", sender))
                msg["To"] = rcpt
                server.sendmail(sender, [rcpt], msg.as_string())

        return True
    except Exception as exc:
        _dprint("Error sending investor emails:", exc)
        return False


def _send_admin_email(subject: str, body: str, user: Dict[str, Any]) -> bool:
    """
    Send an email to the fund admin using the shared emailer.send_email().
    Returns True only if SMTP accepted the message.
    """
    admin_email = _get_admin_email()
    if not admin_email:
        _dprint("Email not sent: no admin_email configured or found in DB")
        return False

    try:
        from backend.services.emailer import send_email
    except Exception as exc:
        _dprint(
            "Email not sent: could not import backend.services.emailer.send_email:",
            exc,
        )
        return False

    lines = [
        "<p>Message sent via Clarus AI chatbot.</p>",
        "<p><strong>Investor / user details:</strong><br>",
        f"- User ID: {user.get('id')}<br>",
        f"- Investor ID: {user.get('id')}<br>",
        f"- Name: {user.get('first_name')}<br>",
        f"- Email: {user.get('email')}<br>",
        "</p>",
        "<p><strong>Message:</strong></p>",
        "<pre style='font-family: monospace; white-space: pre-wrap;'>",
        body,
        "</pre>",
    ]
    html_body = "\n".join(line for line in lines if line is not None)

    try:
        accepted, result = send_email(admin_email, subject, html_body, text=None)
        if not accepted:
            _dprint("Emailer.send_email rejected message:", result)
        return bool(accepted)
    except Exception as exc:
        _dprint("Error sending admin email via shared emailer:", exc)
        return False



def _get_pending_email_state(tenant: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Look back through recent assistant turns for an email_admin state.
    Used to keep the multi-step email flow going across messages.
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        email_state = meta.get("email_admin")
        if email_state:
            return email_state
    return None


def _create_dependent_request_notification(
    parent_inv: Investor,
    dep_name: str,
    dep_email: str,
    account_exists: bool,
) -> None:
    """
    Create a Notification row so:
      - the *investor* sees it in their own notification dropdown
      - the *admin* sees it in the Admin Dashboard (via new admin endpoints).
    """
    if not parent_inv or not getattr(parent_inv, "id", None):
        return

    try:
        if account_exists:
            msg = (
                f"Dependent account request for {dep_name} ({dep_email}). "
                "Existing account detected – waiting for admin to link it as a dependent."
            )
        else:
            msg = (
                f"Dependent account request for {dep_name} ({dep_email}). "
                "A new dependent account will be created after admin approval."
            )

        notif = Notification(
            investor_id=parent_inv.id,
            title="Dependent account request submitted",
            message=msg,
            link_url="/admin",          # admin can click and manually handle it
            kind="dependent_request",   # used in the admin notifications API
        )
        db.session.add(notif)
        db.session.commit()
    except Exception as exc:
        _dprint("Error creating dependent_request Notification:", exc)
        db.session.rollback()



def _get_pending_dependent_request_state(
    tenant: str,
    conversation_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Look back through recent assistant turns for a dependent_request state.

    Used to keep the multi-step 'create dependent account' flow going across
    messages (e.g. asking for name/email, then confirming).
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        state = meta.get("dependent_request")
        if state:
            return state
    return None


def handle_email_investors_intent(
    user: Dict[str, Any],
    message: str,
    body: Dict[str, Any],
    tenant: str,
    conversation_id: str,
) -> Dict[str, Any]:
    """
    Admin-only multi-step flow:

      1) Admin: "I want to send email" → ask: all investors or specific investor? (stage = choose_scope)
      2) Admin chooses:
         - all → ask for message body (stage = await_body_all)
         - specific → resolve investor or ask which one (stage = await_investor / await_body_single)
      3) Admin provides message → generate subject & show preview (stage = confirm_send)
      4) Admin confirms Yes/No → send or cancel.
    """
    # Only admins are allowed to use this flow
    if not _user_is_admin(user):
        ctx = {"ok": False, "issue": "not_admin"}
        sys = (
            "Explain that only administrators are allowed to send broadcast emails to investors. "
            "Suggest contacting support if they believe this is an error."
        )
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    state = _get_pending_investor_email_state(tenant, conversation_id) or {}
    stage = state.get("stage") or "start"

    # 1) First time: admin has just said "I want to send email"
    if stage == "start":
        answer = (
            f"{_prefix()}sure, I can help you email investors. "
            "Do you want to send this email to all investors, or just one specific investor?"
        )
        ctx = {"ok": True, "stage": "choose_scope"}
        meta = {"email_investors": {"stage": "choose_scope"}}
        return {"answer": answer, "context": ctx, "meta": meta}

    msg_low = (message or "").strip().lower()

    # 2) Decide scope: all vs specific investor
    if stage == "choose_scope":
        # If admin clearly says "all" or "everyone"
        if any(w in msg_low for w in ["all", "everyone", "every investor", "all investors"]):
            answer = (
                f"{_prefix()}got it. I’ll prepare an email to all investors. "
                "What message would you like to send them?"
            )
            ctx = {"ok": True, "stage": "await_body_all", "scope": "all"}
            meta = {"email_investors": {"stage": "await_body_all", "scope": "all"}}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Otherwise we treat it as a specific investor flow
        # Try to infer an investor directly from this message
        target_inv = _admin_pick_investor_from_text(message)
        if target_inv:
            answer = (
                f"{_prefix()}great, I’ll email {target_inv.name}. "
                "What message would you like to send them?"
            )
            ctx = {
                "ok": True,
                "stage": "await_body_single",
                "scope": "single",
                "investor_ids": [target_inv.id],
            }
            meta = {
                "email_investors": {
                    "stage": "await_body_single",
                    "scope": "single",
                    "investor_ids": [target_inv.id],
                }
            }
            return {"answer": answer, "context": ctx, "meta": meta}

        # We know it's a specific investor, but not which one yet
        answer = (
            f"{_prefix()}no problem. Which investor should I email? "
            "You can give me their name, email address, or investor ID."
        )
        ctx = {"ok": True, "stage": "await_investor", "scope": "single"}
        meta = {"email_investors": {"stage": "await_investor", "scope": "single"}}
        return {"answer": answer, "context": ctx, "meta": meta}

    # 3) Waiting for a specific investor identification
    if stage == "await_investor":
        target_inv = _admin_pick_investor_from_text(message)
        if not target_inv:
            answer = (
                f"{_prefix()}I couldn’t match that to an investor. "
                "Please provide the investor’s full name, email address, or an ID like 'id 12'."
            )
            ctx = {"ok": False, "stage": "await_investor", "scope": "single"}
            meta = {"email_investors": state}
            return {"answer": answer, "context": ctx, "meta": meta}

        answer = (
            f"{_prefix()}great, I’ll email {target_inv.name}. "
            "What message would you like to send them?"
        )
        ctx = {
            "ok": True,
            "stage": "await_body_single",
            "scope": "single",
            "investor_ids": [target_inv.id],
        }
        meta = {
            "email_investors": {
                "stage": "await_body_single",
                "scope": "single",
                "investor_ids": [target_inv.id],
            }
        }
        return {"answer": answer, "context": ctx, "meta": meta}

    # 4) Waiting for the email body (all investors)
    if stage == "await_body_all":
        email_body = (message or "").strip()
        if not email_body:
            answer = "Please type the message you’d like me to send to all investors."
            ctx = {"ok": False, "stage": "await_body_all", "scope": "all"}
            meta = {"email_investors": state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Generate a professional subject line with the LLM
        ctx_subj = {
            "scope": "all",
            "message": email_body,
        }
        sys_subj = (
            "You are helping a fund admin send an email to all investors.\n"
            "Using CONTEXT.message, create a short, professional email subject line "
            "(max 10 words). Return ONLY the subject text, with no quotes or extra text."
        )
        subject = _ask_llm(sys_subj, ctx_subj, message).strip()
        subject = subject.splitlines()[0].strip().rstrip(".")

        preview = (
            "Here’s what I’ll send to all investors:\n\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{email_body}\n\n"
            "Do you want me to send this email now? (Yes/No)"
        )
        ctx = {
            "ok": True,
            "stage": "confirm_send",
            "scope": "all",
            "subject": subject,
            "body": email_body,
        }
        meta = {
            "email_investors": {
                "stage": "confirm_send",
                "scope": "all",
                "subject": subject,
                "body": email_body,
            }
        }
        return {"answer": preview, "context": ctx, "meta": meta}

    # 5) Waiting for the email body (single investor)
    if stage == "await_body_single":
        email_body = (message or "").strip()
        if not email_body:
            answer = "Please type the message you’d like me to send to this investor."
            ctx = {"ok": False, "stage": "await_body_single", "scope": "single"}
            meta = {"email_investors": state}
            return {"answer": answer, "context": ctx, "meta": meta}

        inv_ids = state.get("investor_ids") or []
        ctx_subj = {
            "scope": "single",
            "investor_ids": inv_ids,
            "message": email_body,
        }
        sys_subj = (
            "You are helping a fund admin send an email to a specific investor.\n"
            "Using CONTEXT.message, create a short, professional email subject line "
            "(max 10 words). Return ONLY the subject text, with no quotes or extra text."
        )
        subject = _ask_llm(sys_subj, ctx_subj, message).strip()
        subject = subject.splitlines()[0].strip().rstrip(".")

        preview = (
            "Here’s what I’ll send to the investor:\n\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{email_body}\n\n"
            "Do you want me to send this email now? (Yes/No)"
        )
        ctx = {
            "ok": True,
            "stage": "confirm_send",
            "scope": "single",
            "subject": subject,
            "body": email_body,
            "investor_ids": inv_ids,
        }
        meta = {
            "email_investors": {
                "stage": "confirm_send",
                "scope": "single",
                "subject": subject,
                "body": email_body,
                "investor_ids": inv_ids,
            }
        }
        return {"answer": preview, "context": ctx, "meta": meta}

    # 6) Confirmation: Yes/No
    if stage == "confirm_send":
        msg_low = (message or "").strip().lower()
        scope = state.get("scope") or "all"
        subject = state.get("subject") or "Message from admin"
        body_text = state.get("body") or ""

        # Positive confirmation → send
        if any(w in msg_low for w in ["yes", "send", "sure", "ok", "okay", "yep", "go ahead"]):
            investors: List[Investor] = []

            if scope == "all":
                try:
                    investors = Investor.query.filter(
                        Investor.email.isnot(None),
                        Investor.email != "",
                    ).all()
                except Exception:
                    investors = []
            else:
                inv_ids = state.get("investor_ids") or []
                if inv_ids:
                    try:
                        investors = list(
                            Investor.query.filter(Investor.id.in_(inv_ids)).all()
                        )
                    except Exception:
                        investors = []

            if not investors:
                answer = (
                    f"{_prefix()}I couldn’t find any investors with an email address to send this to. "
                    "Please check that investor emails are set in the system."
                )
                ctx = {"ok": False, "stage": "done", "scope": scope}
                meta = {"email_investors": {"stage": "done", "scope": scope, "sent": False}}
                return {"answer": answer, "context": ctx, "meta": meta}

            sent = _send_investor_emails(subject, body_text, investors, user)
            if sent:
                if scope == "all":
                    answer = (
                        f"{_prefix()}done. I’ve emailed all investors with your message."
                    )
                else:
                    answer = (
                        f"{_prefix()}done. I’ve emailed the selected investor with your message."
                    )
            else:
                answer = (
                    f"{_prefix()}I tried to send your message, but something went wrong "
                    "with the email service. Please try again later or contact support directly."
                )

            ctx = {"ok": sent, "stage": "done", "scope": scope}
            meta = {"email_investors": {"stage": "done", "scope": scope, "sent": bool(sent)}}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Negative confirmation → cancel
        if any(w in msg_low for w in ["no", "don't", "do not", "cancel", "stop"]):
            answer = (
                f"{_prefix()}okay, I won’t send that email. "
                "If you’d like to send a different message, just tell me again."
            )
            ctx = {"ok": True, "stage": "cancelled"}
            meta = {"email_investors": {"stage": "cancelled"}}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Any other reply → ask for clear Yes/No
        answer = (
            "Just to confirm, should I send this email now? "
            "Please reply with 'Yes' or 'No'."
        )
        ctx = {"ok": False, "stage": "confirm_send", "scope": state.get("scope")}
        meta = {"email_investors": state}
        return {"answer": answer, "context": ctx, "meta": meta}

    # Fallback (shouldn't happen)
    answer = (
        "Something went wrong with the admin email flow. "
        "Please say again that you want to email investors."
    )
    ctx = {"ok": False, "stage": "error"}
    meta = {"email_investors": {"stage": "start"}}
    return {"answer": answer, "context": ctx, "meta": meta}


# Group Account Request

def _get_pending_group_request_state(
    tenant: str,
    conversation_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Look back through recent assistant turns for a group_request state.
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        state = meta.get("group_request")
        if state:
            return state
    return None


def handle_group_request_intent(
    user: Dict[str, Any],
    message: str,
    body: Dict[str, Any],
    tenant: str,
    conversation_id: str,
) -> Dict[str, Any]:
    """
    Multi-step flow for investors to request a group account via the chatbot.
    """

    # Use the same robust resolver as other flows (uses body["investor_id"] too)
    parent_inv = _resolve_investor_for_request(user, body)
    if not parent_inv:
        new_state = {"stage": "error"}
        answer = (
            "I couldn’t find your investor profile in the system, "
            "so I can’t send a group request right now. "
            "Please reload the dashboard and try again, or contact support."
        )
        ctx = {"group_request": new_state}
        meta = {"group_request": new_state}
        return {"answer": answer, "context": ctx, "meta": meta}

    state = _get_pending_group_request_state(tenant, conversation_id) or {}
    stage = state.get("stage") or "start"

    # --- Stage 1: user first says "I want to create a group account" ---
    if stage == "start":
        new_state = {
            "stage": "await_members",
            "parent_investor_id": parent_inv.id,
        }
        answer = (
            "Great, let's set up a group account.\n\n"
            "Please send the list of people you want to add, one per line, in this format:\n"
            "• Alice Smith, alice@example.com\n"
            "• Bob Lee, bob@example.com\n\n"
            "You can include as many people as you like."
        )
        ctx = {"group_request": new_state}
        meta = {"group_request": new_state}
        return {"answer": answer, "context": ctx, "meta": meta}

    # --- Stage 2: they send the list of names + emails ---
    if stage == "await_members":
        members = _parse_group_members_freeform(message)
        if not members:
            new_state = {
                "stage": "await_members",
                "parent_investor_id": parent_inv.id,
            }
            answer = (
                "I couldn't detect any valid email addresses.\n\n"
                "Please send each person on a separate line, for example:\n"
                "• Jane Doe, jane@example.com"
            )
            ctx = {"group_request": new_state}
            meta = {"group_request": new_state}
            return {"answer": answer, "context": ctx, "meta": meta}

        bullets = "\n".join(f"• {m['name']} <{m['email']}>" for m in members)
        new_state = {
            "stage": "confirm",
            "members": members,
            "parent_investor_id": parent_inv.id,
        }
        answer = (
            "Here's who I understood you want to add to your group account:\n\n"
            f"{bullets}\n\n"
            "Do you want me to send this group request to the admin now? (yes / no)"
        )
        ctx = {"group_request": new_state}
        meta = {"group_request": new_state}
        return {"answer": answer, "context": ctx, "meta": meta}

    # --- Stage 3: confirm and actually create the request ---
    if stage == "confirm":
        lower = (message or "").strip().lower()

        # Cancel
        if lower in {"no", "cancel", "stop"}:
            new_state = {"stage": "done", "parent_investor_id": parent_inv.id}
            answer = (
                "Okay, I’ve cancelled the group account request. "
                "You can start again anytime."
            )
            ctx = {"group_request": new_state}
            meta = {"group_request": new_state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Not a clear yes/no → stay in confirm
        if lower not in {"yes", "y", "ok", "okay", "sure"}:
            answer = (
                "Please reply with **yes** to send the request, "
                "or **no** to cancel."
            )
            ctx = {"group_request": state}
            meta = {"group_request": state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Confirmed → create notification + email
        members = state.get("members") or []
        notif = _create_group_request_notification(parent_inv, members)

        if os.getenv("ADMIN_EMAIL"):
            from backend.services.emailer import send_email

            display_name = (
                getattr(parent_inv, "name", None)
                or getattr(parent_inv, "email", None)
                or f"Investor #{parent_inv.id}"
            )

            html_lines = [
                "<p>New group account request from "
                f"<b>{display_name}</b>.</p>",
                "<p>Requested group members:</p>",
                "<ul>",
            ]
            for m in members:
                nm = (m.get("name") or "").strip() or "(no name given)"
                em = (m.get("email") or "").strip()
                html_lines.append(f"<li>{nm} &lt;{em}&gt;</li>")
            html_lines.append("</ul>")

            send_email(
                to=os.getenv("ADMIN_EMAIL"),
                subject="New group account request",
                html="\n".join(html_lines),
            )


        new_state = {
            "stage": "done",
            "members": members,
            "parent_investor_id": parent_inv.id,
            "notification_id": getattr(notif, "id", None),
        }
        answer = (
            "Thanks! I’ve sent your group account request to the admin.\n\n"
            "They will review the list. Existing investors will be added "
            "directly to your group, and anyone new will receive an invitation email."
        )
        ctx = {"group_request": new_state}
        meta = {"group_request": new_state}
        return {"answer": answer, "context": ctx, "meta": meta}

    # Fallback – restart the flow
    new_state = {"stage": "await_members", "parent_investor_id": parent_inv.id}
    answer = (
        "I’m not sure where we left off with your group request. "
        "Let’s start again.\n\n"
        "Please send the list of people you want to add, one per line, "
        "in the format: Name, email@example.com."
    )
    ctx = {"group_request": new_state}
    meta = {"group_request": new_state}
    return {"answer": answer, "context": ctx, "meta": meta}



def handle_email_admin_intent(
    user: Dict[str, Any],
    message: str,
    body: Dict[str, Any],
    tenant: str,
    conversation_id: str,
) -> Dict[str, Any]:
    """
    Multi-step flow:

      1) User asks to email admin → ask for message (stage = await_body).
      2) User provides message → generate subject & ask for confirmation (stage = confirm_send).
      3) User says yes/no → send or cancel.
    """
    state = _get_pending_email_state(tenant, conversation_id) or {}
    stage = state.get("stage") or "start"

    # 1) First time: user said "email the admin"
    if stage == "start":
        inv = _resolve_investor_for_request(user, body)
        if not inv:
            ctx = {"ok": False, "issue": "no_investor_identity"}
            sys = (
                "Explain that you can't send an email because the investor identity "
                "couldn't be verified, and ask them to reload the dashboard."
            )
            return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

        answer = (
            f"{_prefix()}sure, I can email the admin for you. "
            "What message would you like me to send?"
        )
        ctx = {
            "ok": True,
            "stage": "await_body",
            "investor": {"id": inv.id, "name": inv.name, "email": getattr(inv, "email", None)},
        }
        meta = {"email_admin": {"stage": "await_body", "investor_id": inv.id}}
        return {"answer": answer, "context": ctx, "meta": meta}

    # 2) We are waiting for the message body
    if stage == "await_body":
        email_body = (message or "").strip()
        if not email_body:
            answer = "Please type the message you’d like me to send to the admin."
            ctx = {"ok": False, "stage": "await_body"}
            meta = {"email_admin": state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # Generate a professional subject line with the LLM
        inv = _strict_self_investor(user)
        ctx_subj = {
            "investor": {
                "id": inv.id if inv else user.get("investor_id"),
                "name": getattr(inv, "name", None) if inv else None,
            },
            "message": email_body,
        }
        sys_subj = (
            "You are helping route an investor's message to the fund admin.\n"
            "Using CONTEXT.message, create a short, professional email subject line "
            "(max 10 words). Return ONLY the subject text, with no quotes or extra text."
        )
        subject = _ask_llm(sys_subj, ctx_subj, message).strip()
        subject = subject.splitlines()[0].strip().rstrip(".")

        preview = (
            f"Here’s what I’ll send to the admin:\n\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{email_body}\n\n"
            "Do you want me to send this email now? (Yes/No)"
        )
        ctx = {
            "ok": True,
            "stage": "confirm_send",
            "subject": subject,
            "body": email_body,
        }
        meta = {"email_admin": {"stage": "confirm_send", "subject": subject, "body": email_body}}
        return {"answer": preview, "context": ctx, "meta": meta}

    # 3) We are waiting for Yes/No confirmation
    if stage == "confirm_send":
        msg_low = (message or "").strip().lower()

        # Positive confirmation → send
        if any(w in msg_low for w in ["yes", "send", "sure", "ok", "okay", "yep", "go ahead"]):
            subject = state.get("subject") or "Message from investor"
            body_text = state.get("body") or ""

            # NEW: also store this message in the Admin Mailbox table
            # so it appears in the Admin dashboard mailbox UI.
            try:
                investor = None
                if user.get("investor_id"):
                    investor = Investor.query.get(user["investor_id"])

                msg_row = AdminMessage(
                    investor_id=investor.id if investor else None,
                    investor_name=getattr(investor, "name", None) or user.get("email"),
                    subject=subject,
                    body=body_text,
                )
                db.session.add(msg_row)
                db.session.commit()
            except Exception as exc:
                current_app.logger.error(
                    f"Failed to save admin mailbox message: {exc}"
                )

            # Existing behaviour: actually send the email to the admin
            sent = _send_admin_email(subject, body_text, user)

            if sent:
                answer = (
                    f"{_prefix()}done. I’ve emailed the admin with your message. "
                    "They’ll follow up with you soon."
                )
            else:
                answer = (
                    f"{_prefix()}I tried to send your message, but something went wrong "
                    "with the email service. Please try again later or contact support directly."
                )
            ctx = {"ok": sent, "stage": "done"}
            meta = {"email_admin": {"stage": "done", "sent": bool(sent)}}
            return {"answer": answer, "context": ctx, "meta": meta}



def handle_dependent_request_intent(
    user: Dict[str, Any],
    message: str,
    body: Dict[str, Any],
    tenant: str,
    conversation_id: str,
) -> Dict[str, Any]:
    """
    Multi-step flow for investors to request creation/linking of a 'Depends'
    (dependent / child) investor account via the chatbot.

    Flow:
      1) Investor: "I want to create a dependent account" → ask for name+email.
      2) Investor gives details → chatbot checks whether the email already exists.
         - If exists: email admin to approve linking as dependent.
         - If not:   email admin to create a new dependent investor and send invite.
      3) In both cases, a Notification row is created and visible to admin.
    """

    state = _get_pending_dependent_request_state(tenant, conversation_id) or {}
    stage = state.get("stage") or "start"

    # Resolve which investor is making the request (works with investor_id from frontend)
    parent_inv = _resolve_investor_for_request(user, body)
    if not parent_inv:
        ctx = {"ok": False, "issue": "no_investor_identity"}
        sys = (
            "Explain that you can't process the dependent account request because "
            "the investor identity could not be verified, and suggest reloading "
            "the dashboard or contacting support."
        )
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    parent_email = getattr(parent_inv, "email", None)

    # ---------------- 1) First time: ask for dependent's name + email ----------------
    if stage == "start":
        answer = (
            f"{_prefix()}sure, I can help you request a dependent (child) account. "
            "Please provide the dependent investor’s full name and email address, "
            "for example: 'Jane Doe, jane@example.com'."
        )
        ctx = {
            "ok": True,
            "stage": "await_details",
            "parent_investor": {
                "id": parent_inv.id,
                "name": parent_inv.name,
                "email": parent_email,
            },
        }
        meta = {
            "dependent_request": {
                "stage": "await_details",
                "parent_investor_id": parent_inv.id,
            }
        }
        return {"answer": answer, "context": ctx, "meta": meta}

    # ---------------- 2) Waiting for dependent details (name/email) ------------------
    if stage == "await_details":
        msg = (message or "").strip()

        # Start with whatever we already stored
        dep_name = state.get("name") or ""
        dep_email = state.get("email") or ""

        # Try to extract an email address from this message
        email_match = re.search(
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", msg
        )

        if email_match:
            dep_email = email_match.group(1).strip()
        elif "@" in msg:
            # very simple fallback: treat the whole message (first token)
            # as an email if it contains '@'
            dep_email = msg.split()[0].strip(" ,;")

        # Try to extract a name from the part before the email, or the whole message
        if not dep_name:
            before_email = msg[: email_match.start()] if email_match else msg
            mname = re.search(
                r"(name is|named)\\s+(.+)", before_email, flags=re.IGNORECASE
            )
            raw_name = mname.group(2) if mname else before_email
            dep_name = raw_name.strip(" ,.-")

        # Prevent using the same email as the parent investor
        if dep_email and parent_email and dep_email.lower() == parent_email.lower():
            answer = (
                f"{_prefix()}the dependent’s email can’t be the same as your own. "
                "Please provide a different email address for the dependent investor."
            )
            new_state = {
                "stage": "await_details",
                "parent_investor_id": parent_inv.id,
                "name": dep_name,
            }
            ctx = {"ok": False, "stage": "await_details"}
            meta = {"dependent_request": new_state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # If we still don't have an email, ask explicitly
        if not dep_email:
            answer = (
                f"{_prefix()}got it. Now please share the dependent investor’s "
                "email address."
            )
            new_state = {
                "stage": "await_details",
                "parent_investor_id": parent_inv.id,
                "name": dep_name,
            }
            ctx = {"ok": False, "stage": "await_details"}
            meta = {"dependent_request": new_state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # If we still don't have a name, ask explicitly
        if not dep_name:
            answer = (
                f"{_prefix()}thanks. Please also tell me the dependent investor’s "
                "full name."
            )
            new_state = {
                "stage": "await_details",
                "parent_investor_id": parent_inv.id,
                "email": dep_email,
            }
            ctx = {"ok": False, "stage": "await_details"}
            meta = {"dependent_request": new_state}
            return {"answer": answer, "context": ctx, "meta": meta}

        # ---------------- 3) We have both name and email: check if account exists ----
        dep_email_lower = dep_email.lower()
        existing_user = None
        existing_inv = None
        try:
            existing_user = (
                AppUser.query.filter(AppUser.email.ilike(dep_email_lower)).first()
            )
        except Exception:
            existing_user = None
        try:
            existing_inv = (
                Investor.query.filter(Investor.email.ilike(dep_email_lower)).first()
            )
        except Exception:
            existing_inv = None

        account_exists = bool(existing_user or existing_inv)

        # Build admin email text
        if account_exists:
            subject = f"Dependent account link request for {dep_name} ({dep_email})"
            lines = [
                "An investor has requested to link an existing account as a dependent.",
                "",
                "Parent investor:",
                f"- Investor ID: {parent_inv.id}",
                f"- Name: {parent_inv.name}",
                f"- Email: {parent_email}",
                "",
                "Requested dependent:",
                f"- Name: {dep_name}",
                f"- Email: {dep_email}",
                "",
                "Existing records found:",
            ]
            if existing_inv:
                lines.append(
                    f"- Investor record: id={existing_inv.id}, name={existing_inv.name}"
                )
            if existing_user:
                lines.append(
                    f"- User record: id={existing_user.id}, email={existing_user.email}"
                )
            if not existing_inv and not existing_user:
                lines.append("- (Detected as existing by email lookup, but no details)")

            lines.extend(
                [
                    "",
                    "Admin action:",
                    f"- If you approve, please link this account as a dependent "
                    f"of investor_id={parent_inv.id} (e.g. investor_type='Depends' "
                    "and parent_investor_id set appropriately).",
                    "- If you reject, no changes are required.",
                ]
            )
        else:
            subject = f"New dependent investor creation request for {dep_name} ({dep_email})"
            lines = [
                "An investor has requested creation of a new dependent (child) account.",
                "",
                "Parent investor:",
                f"- Investor ID: {parent_inv.id}",
                f"- Name: {parent_inv.name}",
                f"- Email: {parent_email}",
                "",
                "Requested dependent:",
                f"- Name: {dep_name}",
                f"- Email: {dep_email}",
                "",
                "Admin action:",
                f"- If you approve, please create a new user/investor as a dependent "
                f"of investor_id={parent_inv.id} (e.g. investor_type='Depends' and "
                "parent_investor_id set appropriately), and send an invitation email "
                "to the dependent’s address.",
                "- If you reject, no changes are required.",
            ]

        # ✅ Create Notification row so it appears in both investor & admin views
        _create_dependent_request_notification(
            parent_inv=parent_inv,
            dep_name=dep_name,
            dep_email=dep_email,
            account_exists=account_exists,
        )

        body_text = "\n".join(lines)
        sent = _send_admin_email(subject, body_text, user)

        if account_exists:
            if sent:
                answer = (
                    f"{_prefix()}thanks. I’ve sent a request to the fund admin to "
                    f"link {dep_name} ({dep_email}) as a dependent account under "
                    "your profile. They’ll review it and update the account once approved."
                )
            else:
                answer = (
                    f"{_prefix()}your request has been recorded, but I couldn’t "
                    "send the notification email to the admin right now. "
                    "They can still see the request in their dashboard notifications."
                )
        else:
            if sent:
                answer = (
                    f"{_prefix()}thanks. I’ve sent a request to the fund admin to "
                    f"create a new dependent account for {dep_name} ({dep_email}). "
                    "Once they approve it, an invitation email will be sent to that "
                    "address."
                )
            else:
                answer = (
                    f"{_prefix()}your request has been recorded, but I couldn’t "
                    "send the notification email to the admin right now. "
                    "They can still see the request in their dashboard notifications."
                )

        ctx = {
            "ok": True,
            "stage": "done",
            "parent_investor": {"id": parent_inv.id, "name": parent_inv.name},
            "dependent": {"name": dep_name, "email": dep_email},
            "account_exists": account_exists,
        }
        meta = {
            "dependent_request": {
                "stage": "done",
                "sent": bool(sent),
                "account_exists": account_exists,
                "parent_investor_id": parent_inv.id,
                "dependent": {"name": dep_name, "email": dep_email},
            }
        }
        return {"answer": answer, "context": ctx, "meta": meta}

    # Fallback (should not happen often)
    answer = (
        f"{_prefix()}something went wrong with the dependent account request flow. "
        "Please say again that you want to create a dependent account."
    )
    ctx = {"ok": False, "stage": "error"}
    meta = {"dependent_request": {"stage": "start"}}
    return {"answer": answer, "context": ctx, "meta": meta}




# ---------------------------------------------------------------------------
# Chat history helpers
# ---------------------------------------------------------------------------
def _safe_tenant(raw: str) -> str:
    raw = (raw or "").strip() or "default"
    raw = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)
    return raw[:80]

def _hist_path(tenant: str, conv_id: str) -> str:
    root = os.path.join(CHAT_HISTORY_DIR, _safe_tenant(tenant))
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"{conv_id}.jsonl")

def _append_turn(
    tenant: str,
    conv_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append a turn to the conversation history.

    meta is optional; we use it for things like "selected_document"/"selected_statement"
    so that follow-up questions (e.g. 'summarize this file') can find context.
    """
    p = _hist_path(tenant, conv_id)
    lines: List[Dict[str, Any]] = []
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            lines = [json.loads(x) for x in f.readlines()]
    lines.append({"role": role, "content": content, "meta": meta or {}})
    lines = lines[-MAX_TURNS:]
    with open(p, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _load_recent_turns(tenant: str, conv_id: str, max_turns: int) -> List[Dict[str, Any]]:
    p = _hist_path(tenant, conv_id)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        lines = [json.loads(x) for x in f.readlines()]
    return lines[-max_turns:]



def _get_turns(tenant: str, conversation_id: str) -> List[Dict[str, Any]]:
    return _load_recent_turns(tenant, conversation_id, max_turns=20)

# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------
def _get_user_safe() -> Dict[str, Any]:
    """Return a dict with user fields used by the chat logic."""
    if not current_user or current_user.is_anonymous:
        return {}
    try:
        return {
            "id": current_user.id,
            "email": getattr(current_user, "email", None),
            "first_name": getattr(current_user, "first_name", None),
            "user_type": getattr(current_user, "user_type", None),
            "investor_id": getattr(current_user, "investor_id", None),
            "tenant": getattr(current_user, "tenant", None),
        }
    except Exception:
        return {}

def _user_is_admin(user: Dict[str, Any]) -> bool:
    return str(user.get("user_type", "")).lower() == "admin"

def _strict_self_investor(user: Dict[str, Any]) -> Optional[Investor]:
    """Return the Investor row strictly tied to the logged-in user (if any).

    First use the investor_id on the user record. If that is not set, fall back
    to searching for an Investor linked to this user_id (via investor.user_id)
    when that relationship exists in the schema.
    """
    inv_id = user.get("investor_id")
    if inv_id:
        try:
            return Investor.query.get(inv_id)
        except Exception:
            return None

    # Fallback: if user_id is known, try to resolve via investor.user_id
    uid = user.get("id")
    if uid:
        try:
            return Investor.query.filter_by(user_id=uid).first()
        except Exception:
            return None

    return None

def _is_dependent_investor(inv: Optional[Investor]) -> bool:
    if not inv:
        return False
    t = (inv.investor_type or "").strip().lower()
    if t in {"depends", "dependent"}:
        return True
    if getattr(inv, "parent_investor_id", None):
        return True
    return False

def _resolve_user_id_from_profile(user: Dict[str, Any]) -> Optional[int]:
    """Return the AppUser.id for the current profile if we can locate it."""
    uid = user.get("id")
    if uid:
        return uid
    email = user.get("email")
    if email:
        try:
            u = AppUser.query.filter(AppUser.email.ilike(email)).first()
            if u:
                return u.id
        except Exception:
            pass
    return None

def _resolve_investor_for_request(user: Dict[str, Any], body: Dict[str, Any]) -> Optional[Investor]:
    """
    Resolve the target investor for this chat message.

    Priority:
      1) If an investor_id is provided in the request body:
         - Admins may use any investor_id.
         - Non-admins may use it only if it belongs to their own account.
      2) Fallback to the investor tied to the logged-in user (current_user.investor_id
         or, if unset, investor.user_id).
    """
    admin = _user_is_admin(user)
    body_inv_id = body.get("investor_id")

    if body_inv_id:
        try:
            inv = Investor.query.get(int(body_inv_id))
        except Exception:
            inv = None

        if inv:
            if admin:
                # Admins are allowed to see any investor
                return inv
            else:
                # For normal investors, only accept if this investor belongs to the same user
                uid = user.get("id")
                owner_id = getattr(inv, "user_id", None)
                if owner_id is None or owner_id == uid:
                    return inv
                # If there is a mismatch, ignore the body_inv_id and fall back below

    # Fallback: investor linked to the authenticated user (if any)
    return _strict_self_investor(user)

def _admin_pick_investor_from_text(message: str) -> Optional[Investor]:
    """
    Admin-only: try to infer an investor from the message (id/email/name fragments).
    """
    msg = (message or "").strip()
    if not msg:
        return None

    # 1) 'id 123'
    m = re.search(r"\bid\s+(\d+)\b", msg, flags=re.IGNORECASE)
    if m:
        try:
            inv = Investor.query.get(int(m.group(1)))
            if inv:
                return inv
        except Exception:
            pass

    # 2) email
    m = re.search(r"([\w\.-]+@[\w\.-]+)", msg)
    if m:
        email = m.group(1)
        try:
            inv = Investor.query.filter(Investor.email.ilike(email)).first()
            if inv:
                return inv
        except Exception:
            pass

    # 3) fuzzy name
    try:
        all_invs: List[Investor] = Investor.query.all()
    except Exception:
        return None

    names = [inv.name for inv in all_invs if inv.name]
    if not names:
        return None

    best = difflib.get_close_matches(msg, names, n=1, cutoff=0.6)
    if not best:
        return None
    best_name = best[0]
    for inv in all_invs:
        if inv.name == best_name:
            return inv
    return None

# ---------------------------------------------------------------------------
# Utility formatting helpers
# ---------------------------------------------------------------------------
EPS = 1e-9

def _fmt_money(v: float) -> str:
    try:
        return f"${v:,.2f}"
    except Exception:
        return "$0.00"

def _fmt_pct(v: Optional[float]) -> str:
    if v is None or not math.isfinite(v):
        return "n/a"
    return f"{v:.2f}%"

def _fmt_x(v: Optional[float]) -> str:
    if v is None or not math.isfinite(v):
        return "n/a"
    return f"{v:.2f}x"

def _month_label(dt: date) -> str:
    return dt.strftime("%B %Y")

def _prefix() -> str:
    """Friendly prefix using current user's first name when available."""
    if current_user and not current_user.is_anonymous:
        fn = getattr(current_user, "first_name", None)
        if fn:
            return f"{fn}, "
    return ""

# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
def _ask_llm(system: str, context_obj: Dict[str, Any], question: str) -> str:
    ctx_json = json.dumps(context_obj, ensure_ascii=False)
    prompt = f"""{system}

CONTEXT (JSON):
{ctx_json}

USER MESSAGE:
{question}

RESPONSE RULES:
- Friendly, professional, and succinct (1–2 sentences).
- Speak like a personal assistant. Avoid robotic phrasing and boilerplate.
- Use only information in CONTEXT when citing numbers/dates.
"""
    return llm.chat(prompt, model=GEN_MODEL)

# ---------------------------------------------------------------------------
# File helpers (used by file intent)
# ---------------------------------------------------------------------------
def _norm_name(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\.(pdf|xlsx|xls|csv|docx?)$", "", s)
    s = re.sub(r"[_\s]+", " ", s)
    return s

def _keywords(s: str) -> List[str]:
    s = _norm_name(s)
    return [w for w in re.split(r"[^a-z0-9]+", s) if w]

def _score(a: str, b: str) -> float:
    """
    Flexible similarity score between a user query (a) and a document name (b).

    - Uses keyword overlap so partial matches still score.
    - Rewards covering more of the query keywords.
    - Uses fuzzy matching as a secondary signal.
    """
    qk = set(_keywords(a))
    dk = set(_keywords(b))
    if not qk or not dk:
        return 0.0
    inter = qk & dk
    if not inter:
        return 0.0
    jacc = len(inter) / len(qk | dk)
    coverage = len(inter) / len(qk)
    base = 0.5 * jacc + 0.5 * coverage
    fuzzy = difflib.SequenceMatcher(None, _norm_name(a), _norm_name(b)).ratio()
    return 0.6 * base + 0.4 * fuzzy

def _build_download_url(doc_id: int, fname: str) -> str:
    safe_name = quote(fname or f"doc-{doc_id}.pdf")
    # Use the parameter name expected by the route: doc_id
    return url_for(
        "documents.download_document",
        doc_id=doc_id,
        filename=safe_name,
        _external=True,
    )

def _build_statement_preview_url(stmt: Statement) -> str:
    """
    URL used for inline preview of a statement PDF (no forced download).
    """
    path = (getattr(stmt, "pdf_path", None) or "").strip()
    import os
    base_name = os.path.basename(path) if path else f"statement-{stmt.id}.pdf"
    safe_name = quote(base_name or f"statement-{stmt.id}.pdf")

    return url_for(
        "chat.preview_statement_file",
        statement_id=stmt.id,
        filename=safe_name,
        _external=True,
    )



def _build_document_preview_url(doc: Document) -> str:
    """
    Build an inline-preview URL for a shared Document.
    Used by the chat file search so the frontend can open the PDF in a tab.
    """
    fname = doc.original_name or doc.title or f"doc-{doc.id}.pdf"
    safe_name = quote(fname or f"doc-{doc.id}.pdf")
    return url_for(
        "chat.preview_document_file",   # 👈 new route below
        doc_id=doc.id,
        filename=safe_name,
        _external=True,
    )


def _build_statement_download_url(stmt: Statement) -> str:
    """
    Build a URL that the frontend can use to download the statement PDF.

    We expose a dedicated chat download route that:
      - looks up Statement.pdf_path
      - finds the file on disk (using UPLOAD_ROOTS)
      - streams it with a proper filename.
    """
    path = (getattr(stmt, "pdf_path", None) or "").strip()
    import os
    base_name = os.path.basename(path) if path else f"statement-{stmt.id}.pdf"
    safe_name = quote(base_name or f"statement-{stmt.id}.pdf")

    return url_for(
        "chat.download_statement_file",
        statement_id=stmt.id,
        filename=safe_name,
        _external=True,
    )

def _find_on_disk(path: str) -> Optional[str]:
    """Try to locate a file under configured upload roots."""
    for root in UPLOAD_ROOTS:
        candidate = os.path.join(root, path)
        if os.path.exists(candidate):
            return candidate
    return None

def _fetch_shared_docs_for_user_id(user_id: int) -> List[Document]:
    """Return all Document rows from the *shared documents* section for this investor user."""
    try:
        docs = (
            db.session.query(Document)
            .join(DocumentShare, DocumentShare.document_id == Document.id)
            .filter(DocumentShare.investor_user_id == user_id)
            .order_by(Document.uploaded_at.desc())
            .all()
        )
    except Exception:
        docs = []
    return docs

def _extract_file_query(text: str) -> str:
    """
    Very small heuristic to pull a filename-ish phrase from the user message.
    """
    low = (text or "").strip()
    if not low:
        return ""
    low = re.sub(r"\b(my|the|a|an|this|that|these|those|latest|last|recent)\b", "", low, flags=re.IGNORECASE)
    low = re.sub(r"\b(file|document|statement|report)s?\b", "", low, flags=re.IGNORECASE)
    low = re.sub(r"\b(show|open|view|see|download|upload|share)\b", "", low, flags=re.IGNORECASE)
    low = re.sub(r"\b(please)\b", "", low, flags=re.IGNORECASE)
    low = re.sub(r"\s+", " ", low).strip()
    return low

# ---------------------------------------------------------------------------
# Monthly balance helpers (used by balance + calc)
# ---------------------------------------------------------------------------
MonthRow = Dict[str, Any]

def _as_date(x) -> Optional[date]:
    if not x:
        return None
    if isinstance(x, date):
        return x
    if isinstance(x, datetime):
        return x.date()
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        return None

def _ym_key(d: date) -> str:
    return f"{d.year}-{str(d.month).zfill(2)}"

def _parse_month_from_text(text: str) -> Optional[date]:
    """Accept '2025-06', '2025/06', 'June 2025', 'Jun 2025'."""
    t = (text or "").strip()
    m = re.search(r"(20\d{2})[-/](0[1-9]|1[0-2])", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5,
        "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12
    }
    m2 = re.search(r"\b([A-Za-z]{3,9})\s+(20\d{2})\b", t)
    if m2 and m2.group(1).lower() in months:
        return date(int(m2.group(2)), months[m2.group(1).lower()], 1)
    return None

def _extract_target_date(message: str) -> Optional[date]:
    """
    Prefer a parsed date from nlp_router.parse_intent(message)["date"], falling back to
    the legacy _parse_month_from_text() heuristic. This lets balance/performance queries
    share a single, consistent month/year resolver.
    """
    try:
        info = nlp_parse_intent(message)
        iso = info.get("date")
        if iso:
            dt = _as_date(iso)
            if dt:
                return dt
    except Exception:
        pass
    return _parse_month_from_text(message)

def _extract_target_year(message: str) -> Optional[int]:
    """
    Extract a bare year like '2024' from the message.
    Used when the user asks for '2024 growth' without a specific month.
    """
    if not message:
        return None
    m = re.search(r"\b(20\d{2})\b", message)
    if not m:
        return None
    try:
        year = int(m.group(1))
        if 1900 <= year <= 2100:
            return year
    except Exception:
        return None
    return None

def _extract_target_quarter(message: str) -> Optional[Tuple[int, int]]:
    """
    Parse things like 'Q3 2024' or '2024 Q3' and return (year, quarter).
    """
    m = re.search(r"\bq([1-4])\s*(20\d{2})\b", message, flags=re.IGNORECASE)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.search(r"\b(20\d{2})\s*q([1-4])\b", message, flags=re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None

# ---------------------------------------------------------------------------
# Series loaders
# ---------------------------------------------------------------------------
def _load_monthly_series_for_investor(investor_name: str) -> List[MonthRow]:
    """
    Prefer InvestorPeriodBalance rows (new excel-upload schema) and fall back
    to InvestorBalance summary rows as pseudo-months.
    """
    series: List[MonthRow] = []

    # 1) Monthly snapshots from InvestorPeriodBalance (new schema)
    try:
        if InvestorPeriodBalance is not None:
            rows = (
                InvestorPeriodBalance.query
                .filter(InvestorPeriodBalance.name.ilike(f"%{investor_name}%"))
                .order_by(InvestorPeriodBalance.as_of_date.asc())
                .all()
            )
            for r in rows:
                dt = _as_date(getattr(r, "as_of_date", None))
                if not dt:
                    continue

                beginning = float(getattr(r, "beginning_balance", 0.0) or 0.0)
                ending = float(getattr(r, "ending_balance", 0.0) or 0.0)

                additions = float(getattr(r, "additions", 0.0) or 0.0)
                withdrawals = float(getattr(r, "withdrawals", 0.0) or 0.0)

                mgmt_fees = float(getattr(r, "management_fees", 0.0) or 0.0)
                opex = float(getattr(r, "operating_expenses", 0.0) or 0.0)
                allocated = float(getattr(r, "allocated_fees", 0.0) or 0.0)
                total_fees = mgmt_fees + opex + allocated

                series.append(
                    {
                        "dt": dt,
                        "beginning": beginning,
                        "ending": ending,
                        "contributions": additions,
                        "distributions": withdrawals,
                        "fees": total_fees,
                    }
                )
    except Exception:
        pass

    # 2) Fallback: summary rows as pseudo-months
    if not series:
        try:
            if InvestorBalance is not None:
                rows = (
                    InvestorBalance.query
                    .filter(InvestorBalance.investor.ilike(f"%{investor_name}%"))
                    .order_by(InvestorBalance.current_date.asc())
                    .all()
                )
                for r in rows:
                    dt = _as_date(getattr(r, "current_date", None))
                    if not dt:
                        continue
                    series.append(
                        {
                            "dt": dt,
                            "beginning": float(getattr(r, "initial_value", 0.0) or 0.0),
                            "ending": float(getattr(r, "current_value", 0.0) or 0.0),
                            "contributions": None,
                            "distributions": None,
                            "fees": None,
                        }
                    )
        except Exception:
            pass

    return series

def _load_monthly_series_from_statements(investor_id: int) -> List[MonthRow]:
    """
    Build a monthly balance series from Statement rows for this investor.
    Used as a fallback when snapshot tables don't have data.
    """
    series: List[MonthRow] = []
    try:
        rows = (
            Statement.query
            .filter(Statement.investor_id == investor_id)
            .order_by(Statement.period_end.asc())
            .all()
        )
    except Exception:
        rows = []

    for r in rows:
        dt = _as_date(getattr(r, "period_end", None))
        if not dt:
            continue

        def _f(v: Any) -> float:
            try:
                return float(v or 0.0)
            except Exception:
                return 0.0

        series.append({
            "dt": dt,
            "beginning": _f(getattr(r, "beginning_balance", None)),
            "ending": _f(getattr(r, "ending_balance", None)),
            "contributions": _f(getattr(r, "contributions", None)),
            "distributions": _f(getattr(r, "distributions", None)),
            "fees": _f(getattr(r, "management_fees", None))
                    + _f(getattr(r, "incentive_fees", None))
                    + _f(getattr(r, "operating_expenses", None)),
        })

    return series

def _pick_row(series: List[MonthRow], target: Optional[date]) -> MonthRow:
    """Return the row matching the target date (or last row if no target)."""
    if not series:
        return {}
    if not target:
        return series[-1]
    tkey = _ym_key(target)
    best: Optional[MonthRow] = None
    for row in series:
        rk = _ym_key(row["dt"])
        if rk <= tkey:
            best = row
    return best or series[-1]

def _which_balance_kind(message: str) -> str:
    """Decide whether the user is asking for beginning vs ending balance."""
    msg = (message or "").lower()
    if any(k in msg for k in ["beginning", "initial", "start"]):
        return "beginning"
    return "ending"

# -----------------------------------------------------------------------------
# INTENT 1: Balance data (deterministic)
# -----------------------------------------------------------------------------
def handle_balance_intent(user: Dict[str, Any], message: str, body: Dict[str, Any]) -> Dict[str, Any]:
    inv = _resolve_investor_for_request(user, body)

    # Admins can target an investor by id/email/name in the message.
    is_admin = str(user.get("user_type", "")).lower() == "admin"
    if is_admin:
        pick = _admin_pick_investor_from_text(message)
        if pick:
            inv = pick

    if not inv:
        ctx = {"ok": False, "issue": "no_investor_identity"}
        sys = "Investor identity could not be determined. Ask the user to reload the dashboard."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # First, try snapshot tables; if empty, fall back to Statement data.
    series = _load_monthly_series_for_investor(inv.name)
    if not series:
        series = _load_monthly_series_from_statements(inv.id)
    if not series:
        ctx = {
            "ok": False,
            "reason": "no_series",
            "investor": {"id": inv.id, "name": inv.name},
        }
        sys = "Explain that there is no balance data available for this investor."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    kind = _which_balance_kind(message)  # 'ending' (== current) or 'beginning' (== initial)
    target = _extract_target_date(message)
    row = _pick_row(series, target)
    idx = series.index(row)
    prev = series[idx - 1] if idx > 0 else None

    val = row["ending"] if kind == "ending" else row["beginning"]
    label = "current" if kind == "ending" else "beginning"
    month = _month_label(row["dt"])
    answer = f"{_prefix()}as of {month}, your {label} balance is {_fmt_money(val)}"

    # Add MoM delta for current balance when possible
    if kind == "ending" and prev:
        chg = (row["ending"] or 0.0) - (prev["ending"] or 0.0)
        pct = (
            (chg / max(EPS, (prev["ending"] or 0.0))) * 100.0
            if (prev["ending"] or 0.0)
            else None
        )
        sign = "up" if chg >= 0 else "down"
        prev_label = _month_label(prev["dt"])
        if pct is not None and math.isfinite(pct):
            answer += f" — {sign} {_fmt_money(abs(chg))} ({_fmt_pct(abs(pct))}) vs {prev_label}."
        else:
            answer += f" — {sign} {_fmt_money(abs(chg))} vs {prev_label}."
    else:
        answer += "."

    ctx = {
        "ok": True,
        "investor": {"id": inv.id, "name": inv.name},
        "period": row["dt"].isoformat(),
        "kind": kind,
        "value": val,
    }
    return {"answer": answer, "context": ctx}


def _build_statement_matches(
    statements: List[Statement],
    base_query: str,
    message: str,
    quarter: Optional[Tuple[int, int]] = None,
) -> List[Dict[str, Any]]:
    """
    Build ranked matches for Statement rows.

    If `quarter` is provided, only statements for that year+quarter are returned.
    """
    target_dt = _extract_target_date(message)
    q_year = q_quarter = q_month = None
    if quarter:
        q_year, q_quarter = quarter
        q_month = q_quarter * 3  # Q1→3, Q2→6, Q3→9, Q4→12

    results: List[Dict[str, Any]] = []

    for st in statements:
        when = st.period_end or st.period_start
        if not when:
            continue

        # If the user asked for a specific quarter, filter other quarters out.
        if q_year and q_month:
            if when.year != q_year or when.month != q_month:
                continue

        month_label = _month_label(when)
        title = f"{month_label} statement".strip()

        # Base similarity on the title (month+year+word 'statement')
        s = _score(base_query, title) if title else 0.0

        # If the user gave a concrete month (e.g. 'September 2024'), boost that match
        if s <= 0 and target_dt:
            if target_dt.year == when.year and target_dt.month == when.month:
                s = 1.0

        if s <= 0:
            continue

        results.append(
            {
                "id": st.id,
                "title": title or f"Statement {st.id}",
                "download_url": _build_statement_download_url(st),
                "preview_url": _build_statement_preview_url(st),   # 👈 NEW
                "score": float(s),
                "source": "statement",
                "period_start": st.period_start.isoformat() if st.period_start else None,
                "period_end": st.period_end.isoformat() if st.period_end else None,
            }
        )

    return results

# -----------------------------------------------------------------------------
# INTENT 2: File retrieval (friendly LLM voice — ranking can be expanded)
# -----------------------------------------------------------------------------
def handle_file_intent(user: Dict[str, Any], message: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    File search now does TWO things:

    1) Pulls all documents shared with this investor (DocumentShare).
    2) Pulls all Statement rows for this investor (their quarterly PDFs).

    Then it ranks ALL candidates together and picks the best match.

    This version is quarter-aware: queries like "2024 Q3 statement"
    will prefer the September-2024 statement, and follow-up summary
    requests will target that statement.
    """

    # Small local helper: parse "Q3 2024" / "2024 Q3" → (year, quarter)
    def _extract_target_quarter_local(text: str) -> Optional[Tuple[int, int]]:
        if not text:
            return None
        m = re.search(r"\bq([1-4])\s*(20\d{2})\b", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(2)), int(m.group(1))
        m = re.search(r"\b(20\d{2})\s*q([1-4])\b", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    # ----- 1. Shared documents (like before) -----
    target_uid = _resolve_user_id_from_profile(user)

    docs: List[Document] = []
    if target_uid:
        try:
            docs = _fetch_shared_docs_for_user_id(target_uid)
        except Exception:
            docs = []

    # ----- 2. Statements for this investor -----
    inv = _resolve_investor_for_request(user, body)
    is_admin = _user_is_admin(user)
    if is_admin:
        pick = _admin_pick_investor_from_text(message)
        if pick:
            inv = pick

    statements: List[Statement] = []
    if inv:
        try:
            statements = (
                Statement.query
                .filter(Statement.investor_id == inv.id)
                .order_by(Statement.period_end.asc())
                .all()
            )
        except Exception:
            statements = []

    # If we truly have no way to see docs or statements, bail out nicely
    if not docs and not statements:
        ctx = {
            "ok": False,
            "issue": "no_files_visible",
            "details": "no_shared_docs_and_no_statements",
        }
        sys = (
            "Explain that you couldn't find any shared files or statements for this account. "
            "Suggest reloading the dashboard or contacting support."
        )
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # ----- 3. Rank candidates against the user's query -----
    query = _extract_file_query(message)
    base_query = query or message
    matches: List[Dict[str, Any]] = []
    doc_matches: List[Dict[str, Any]] = []
    stmt_matches: List[Dict[str, Any]] = []

    # 3a) Shared docs
    if docs and base_query:
        scored_docs: List[Tuple[float, Document]] = []
        for d in docs:
            name = d.title or d.original_name or ""
            if not name:
                continue
            s = _score(base_query, name)
            # Only keep docs that share at least one keyword with the query
            if s <= 0:
                continue
            scored_docs.append((s, d))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        for score, d in scored_docs[:10]:
            doc_matches.append(
                {
                    "id": d.id,
                    "title": d.title or d.original_name,
                    "download_url": _build_download_url(
                        d.id,
                        d.original_name or d.title or f"doc-{d.id}.pdf",
                    ),
                    "preview_url": _build_document_preview_url(d),  # 👈 NEW
                    "score": float(score),
                    "source": "document",
                }
            )


    # 3b) Statements for this investor (quarter-aware)
    if statements and base_query:
        target_dt = _extract_target_date(message)
        qinfo = _extract_target_quarter_local(message)
        q_year = q_quarter = q_month = None
        if qinfo:
            q_year, q_quarter = qinfo
            q_month = q_quarter * 3  # Q1→3, Q2→6, Q3→9, Q4→12

        all_stmt_matches: List[Dict[str, Any]] = []
        quarter_stmt_matches: List[Dict[str, Any]] = []

        for st in statements:
            # Label: e.g. "September 2024 statement" or similar
            when = st.period_end or st.period_start
            if not when:
                continue

            month_label = _month_label(when)
            title = f"{month_label} statement".strip()

            # Base similarity on the title (month+year+word 'statement')
            s = _score(base_query, title) if title else 0.0

            # If user gave a specific month and match is same month/year, force a decent score
            if s <= 0 and target_dt and when:
                if target_dt.year == when.year and target_dt.month == target_dt.month:
                    s = 1.0  # baseline match

            if s <= 0:
                continue

            rec = {
                "id": st.id,
                "title": title or f"Statement {st.id}",
                "download_url": _build_statement_download_url(st),
                "preview_url": _build_statement_preview_url(st),   # 👈 NEW
                "score": float(s),
                "source": "statement",
                "period_start": st.period_start.isoformat() if st.period_start else None,
                "period_end": st.period_end.isoformat() if st.period_end else None,
            }


            all_stmt_matches.append(rec)

            # If a specific quarter/year was requested, also record matches for that quarter
            if q_year and q_month and when.year == q_year and when.month == q_month:
                quarter_stmt_matches.append(rec)

        # If the user asked for a quarter and we found matches for that quarter,
        # use ONLY those; otherwise fall back to all statement matches.
        if quarter_stmt_matches:
            stmt_matches = quarter_stmt_matches
        else:
            stmt_matches = all_stmt_matches

    # Combine & pick best
    matches = sorted(doc_matches + stmt_matches, key=lambda x: x["score"], reverse=True)
    selected: Optional[Dict[str, Any]] = matches[0] if matches else None

    out_ctx = {
        "query": message,
        "matches": matches,
        "selected": selected,
    }

    sys = (
        "Friendly and concise. If CONTEXT.matches has items, start with "
        "'Here are the files I found'. For each item, mention whether it is a "
        "statement or a document and its title.\n\n"
        "If a match has preview_url, provide a markdown link labelled 'Preview' "
        "pointing to preview_url. Always provide a markdown link labelled "
        "'Download' pointing to download_url.\n"
        "Example: 'You can preview it [Preview](PREVIEW_URL) or download it "
        "[Download](DOWNLOAD_URL).'\n\n"
        "If there are no matches, clearly say that you couldn’t find a matching "
        "shared file or statement."
    )


    answer = _ask_llm(sys, out_ctx, message)

    # Track which file was selected so a follow-up 'summarize/explain this file'
    # can find it again.
    meta: Dict[str, Any] = {}
    if selected:
        if selected.get("source") == "document":
            meta = {"selected_document": selected}
        elif selected.get("source") == "statement":
            meta = {"selected_statement": selected}

    return {"answer": answer, "context": out_ctx, "meta": meta}

# -----------------------------------------------------------------------------
# File summarization helpers + intent
# -----------------------------------------------------------------------------
def _get_document_text(doc: Document) -> Optional[str]:
    """
    Try to pull a plain-text field from the Document record so we can summarize it.
    This is schema-agnostic and will work if your model has any of these attributes.
    """
    candidates = ["text_content", "extracted_text", "content", "text"]
    for attr in candidates:
        if hasattr(doc, attr):
            value = getattr(doc, attr)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _get_last_selected_document(tenant: str, conversation_id: str) -> Optional[Document]:
    """
    Look back through recent assistant turns in this conversation for a selected_document
    meta entry, and return the corresponding Document row.
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        sel = meta.get("selected_document") or {}
        doc_id = sel.get("id")
        if not doc_id:
            continue
        try:
            doc = Document.query.get(doc_id)
            if doc:
                return doc
        except Exception:
            continue
    return None


def _extract_date_from_string(text: str) -> Optional[date]:
    """
    Try to pull a YYYY-MM-DD or YYYY_MM_DD style date from a filename, e.g.
    'Alan Stockmeister_2025-06-30 (1).pdf'.
    """
    if not text:
        return None
    m = re.search(r"(20\d{2}|19\d{2})[-_](0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])", text)
    if not m:
        return None
    try:
        year, month, day = map(int, m.groups())
        return date(year, month, day)
    except Exception:
        return None


def _summarize_statement_row(stmt: Statement, message: str) -> Dict[str, Any]:
    """
    Build a numeric context for a Statement row and let the LLM summarize it.
    """

    def _f(v: Any) -> float:
        try:
            return float(v or 0.0)
        except Exception:
            return 0.0

    beginning = _f(getattr(stmt, "beginning_balance", None))
    ending = _f(getattr(stmt, "ending_balance", None))
    contributions = _f(getattr(stmt, "contributions", None))
    distributions = _f(getattr(stmt, "distributions", None))
    mgmt = _f(getattr(stmt, "management_fees", None))
    incent = _f(getattr(stmt, "incentive_fees", None))
    opex = _f(getattr(stmt, "operating_expenses", None))
    net_income = _f(getattr(stmt, "net_income_loss", None))
    total_fees = mgmt + incent + opex

    when = stmt.period_end or stmt.period_start
    period_label = _month_label(when) if when else None

    inv_info = None
    try:
        inv_rec = Investor.query.get(stmt.investor_id)
        if inv_rec:
            inv_info = {"id": inv_rec.id, "name": inv_rec.name}
    except Exception:
        inv_info = None

    ctx = {
        "ok": True,
        "kind": "statement",
        "investor": inv_info,
        "statement": {
            "id": stmt.id,
            "period_start": stmt.period_start.isoformat() if stmt.period_start else None,
            "period_end": stmt.period_end.isoformat() if stmt.period_end else None,
            "period_label": period_label,
            "beginning_balance": beginning,
            "ending_balance": ending,
            "contributions": contributions,
            "distributions": distributions,
            "management_fees": mgmt,
            "incentive_fees": incent,
            "operating_expenses": opex,
            "total_fees": total_fees,
            "net_income_loss": net_income,
        },
    }

    sys = (
        "You are summarizing or explaining an investor's quarterly statement using the numeric fields "
        "in CONTEXT.statement. Provide a clear 3–5 bullet summary that covers: the period, "
        "how the balance changed, total contributions and distributions, total fees "
        "(and main types), and net income or loss. Use the numbers from CONTEXT only; "
        "do not invent any new values."
    )
    answer = _ask_llm(sys, ctx, message)
    return {"answer": answer, "context": ctx}


def _get_last_selected_statement(tenant: str, conversation_id: str) -> Optional[Statement]:
    """
    Look back through recent assistant turns in this conversation for a selected_statement
    meta entry, and return the corresponding Statement row.
    """
    turns = _load_recent_turns(tenant, conversation_id, max_turns=20)
    for entry in reversed(turns):
        if entry.get("role") != "assistant":
            continue
        meta = entry.get("meta") or {}
        sel = meta.get("selected_statement") or {}
        stmt_id = sel.get("id")
        if not stmt_id:
            continue
        try:
            stmt = Statement.query.get(stmt_id)
            if stmt:
                return stmt
        except Exception:
            continue
    return None

def handle_file_summary_intent(
    user: Dict[str, Any],
    message: str,
    body: Dict[str, Any],
    tenant: str,
    conversation_id: str,
) -> Dict[str, Any]:
    """
    Summarize the most recently selected file in this conversation.

    Behaviour:
      1) If the last file was a Document and we have stored text -> summarize that text.
      2) If the last file was a Document but we have NO text:
         - Try to treat it as a quarterly Statement PDF by matching the date in the
           filename to a Statement row for the logged-in investor, and summarize
           that Statement from the database.
      3) If no document was selected, fall back to the last selected Statement (if any).
      4) Otherwise, explain that there is nothing to summarize.
    """

    # Who is the current investor (for matching statements by date)?
    inv = _resolve_investor_for_request(user, body)

    # ------------------------------------------------------------------
    # 1) Try to summarize the last selected Document
    # ------------------------------------------------------------------
    doc = _get_last_selected_document(tenant, conversation_id)
    if doc:
        text = _get_document_text(doc)

        if text:
            # We have actual text stored for this document -> summarize that.
            snippet = text[:8000]  # keep prompt size safe
            ctx = {
                "ok": True,
                "kind": "document",
                "document": {
                    "id": doc.id,
                    "title": getattr(doc, "title", None),
                    "original_name": getattr(doc, "original_name", None),
                },
                "text": snippet,
            }
            sys = (
                "You are summarizing an investor document. Using CONTEXT.text, give a clear, "
                "concise summary in 3–5 bullet points. Focus on: time period, portfolio "
                "performance, contributions/distributions, fees, and any notable changes or "
                "risks. Do not invent any numbers or facts that are not in the text."
            )
            answer = _ask_llm(sys, ctx, message)
            return {"answer": answer, "context": ctx}

        # No stored text for the document – try to map it to a Statement instead.
        stmt: Optional[Statement] = None

        # First, if we already have a selected_statement in the history, reuse it.
        try:
            stmt = _get_last_selected_statement(tenant, conversation_id)
        except Exception:
            stmt = None

        # If that didn't work, guess the period from the filename + current investor.
        if not stmt and inv:
            name_bits = " ".join(
                [
                    str(getattr(doc, "title", "") or ""),
                    str(getattr(doc, "original_name", "") or ""),
                ]
            )
            when = _extract_date_from_string(name_bits)
            if when:
                try:
                    stmt = (
                        Statement.query.filter(Statement.investor_id == inv.id)
                        .filter(Statement.period_end == when)
                        .order_by(Statement.id.desc())
                        .first()
                    )
                except Exception:
                    stmt = None

        if stmt:
            # We successfully mapped the file to a Statement row -> summarize numerically.
            return _summarize_statement_row(stmt, message)

        # Still nothing: fall back to the "can't read file" explanation.
        ctx = {
            "ok": False,
            "kind": "document",
            "document": {
                "id": doc.id,
                "title": getattr(doc, "title", None),
                "original_name": getattr(doc, "original_name", None),
            },
            "issue": "no_text_available",
        }
        sys = (
            "Explain that you cannot directly read the contents of this file from here, "
            "only its name and basic metadata, so you cannot provide a detailed summary. "
            "Offer to help interpret it if the user pastes key parts of the document."
        )
        answer = _ask_llm(sys, ctx, message)
        return {"answer": answer, "context": ctx}

    # ------------------------------------------------------------------
    # 2) If no document was selected, try last selected Statement
    # ------------------------------------------------------------------
    stmt = None
    try:
        stmt = _get_last_selected_statement(tenant, conversation_id)
    except Exception:
        stmt = None

    if stmt:
        return _summarize_statement_row(stmt, message)

    # ------------------------------------------------------------------
    # 3) Nothing found to summarize
    # ------------------------------------------------------------------
    ctx = {"ok": False, "issue": "no_recent_file"}
    sys = (
        "Explain that there is no previously selected file or statement in this "
        "conversation to summarize. Ask the user to first request a specific document "
        "or statement (for example: 'show my June 2024 statement') and then ask "
        "for a summary."
    )
    return {"answer": _ask_llm(sys, ctx, message), "context": ctx}


# -----------------------------------------------------------------------------
# INTENT 3: Calculations (ROI/MOIC/IRR) — deterministic math + PA voice
# -----------------------------------------------------------------------------
def _compute_roi(
    begin: float,
    end: float,
    contributions: Optional[float],
    distributions: Optional[float],
) -> Optional[float]:
    """Simple ROI approximation."""
    try:
        c = contributions or 0.0
        d = distributions or 0.0
        net_contrib = c - d
        num = end - begin - net_contrib
        denom = max(EPS, begin + net_contrib)
        return (num / denom) * 100.0
    except Exception:
        return None

def _compute_moic(begin: float, end: float) -> Optional[float]:
    try:
        if begin <= 0:
            return None
        return end / begin
    except Exception:
        return None

def _compute_irr_approx(series: List[MonthRow]) -> Optional[float]:
    """
    Very rough IRR proxy using only beginning/ending and dates.
    """
    if not series:
        return None
    try:
        first = series[0]
        last = series[-1]
        years = max(EPS, (last["dt"] - first["dt"]).days / 365.25)
        begin = first["beginning"]
        end = last["ending"]
        irr = (end / max(EPS, begin)) ** (1.0 / max(EPS, years)) - 1.0
        return irr * 100.0
    except Exception:
        return None

def handle_calc_intent(user: Dict[str, Any], message: str, body: Dict[str, Any]) -> Dict[str, Any]:
    inv = _resolve_investor_for_request(user, body)

    # Admin can target anyone by free text
    is_admin = str(user.get("user_type", "")).lower() == "admin"
    if is_admin:
        pick = _admin_pick_investor_from_text(message)
        if pick:
            inv = pick

    if not inv:
        ctx = {"ok": False, "issue": "no_investor_identity"}
        sys = "Explain the investor couldn't be identified and suggest reloading the dashboard."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # Same fallback logic as balances: snapshot table first, then Statements
    series = _load_monthly_series_for_investor(inv.name)
    if not series:
        series = _load_monthly_series_from_statements(inv.id)
    if not series:
        ctx = {
            "ok": False,
            "reason": "no_series",
            "investor": {"id": inv.id, "name": inv.name},
        }
        sys = "Explain that there is no balance/performance data available for this investor."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # ---------- Decide which period the user is asking about ----------
    target_dt = _extract_target_date(message)          # specific month/date if present
    year_hint = _extract_target_year(message)          # bare year, e.g. '2024'
    month_hint = _parse_month_from_text(message)       # month name like 'June 2024' → date

    period_label: str
    period_start: Optional[date]
    period_end: Optional[date]
    begin_val: float
    end_val: float
    contrib_total: Optional[float] = None
    distr_total: Optional[float] = None
    irr_series: List[MonthRow]

    # Case 1: user gave a month (e.g. "June 2024 growth")
    if month_hint:
        row = _pick_row(series, target_dt or month_hint)
        period_label = _month_label(row["dt"])
        period_start = row["dt"]
        period_end = row["dt"]
        begin_val = row["beginning"]
        end_val = row["ending"]
        contrib_total = row.get("contributions")
        distr_total = row.get("distributions")
        # Use data from start up to this month for the IRR proxy
        irr_series = [r for r in series if r["dt"] <= row["dt"]]

    # Case 2: user gave a bare year (e.g. "2024 growth")
    elif year_hint:
        year_rows = [r for r in series if r["dt"].year == year_hint]
        if not year_rows:
            ctx = {
                "ok": False,
                "reason": "no_year_data",
                "investor": {"id": inv.id, "name": inv.name},
                "year": year_hint,
            }
            sys = (
                "Explain that there is no performance data for the requested year in the system. "
                "Suggest checking a different year or the latest period instead."
            )
            return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

        period_label = str(year_hint)
        period_start = year_rows[0]["dt"]
        period_end = year_rows[-1]["dt"]
        begin_val = year_rows[0]["beginning"]
        end_val = year_rows[-1]["ending"]
        contrib_total = sum(_to_float(r.get("contributions")) for r in year_rows)
        distr_total = sum(_to_float(r.get("distributions")) for r in year_rows)
        irr_series = year_rows

    # Case 3: no explicit time hint → use the latest period (current behaviour)
    else:
        row = series[-1]
        period_label = _month_label(row["dt"])
        period_start = series[0]["dt"]
        period_end = row["dt"]
        begin_val = row["beginning"]
        end_val = row["ending"]
        contrib_total = row.get("contributions")
        distr_total = row.get("distributions")
        irr_series = series

    # ---------- Compute metrics ----------
    roi = _compute_roi(begin_val, end_val, contrib_total, distr_total)
    moic = _compute_moic(begin_val, end_val)
    irr = _compute_irr_approx(irr_series)

    ctx = {
        "ok": True,
        "investor": {"id": inv.id, "name": inv.name},
        "period": {
            "label": period_label,
            "start": period_start.isoformat() if period_start else None,
            "end": period_end.isoformat() if period_end else None,
        },
        "metrics": {
            "roi_pct": roi,
            "moic": moic,
            "irr_pct": irr,
            "roi_str": _fmt_pct(roi),
            "moic_str": _fmt_x(moic),
            "irr_str": _fmt_pct(irr),
        },
        "balances": {
            "beginning_balance": begin_val,
            "ending_balance": end_val,
            "beginning_str": _fmt_money(begin_val),
            "ending_str": _fmt_money(end_val),
        },
        "cashflows": {
            "contributions": contrib_total,
            "distributions": distr_total,
        },
        "prefix": _prefix(),
    }

    sys = (
        "You are a professional fund reporting assistant. Using CONTEXT, explain the investor's growth "
        "for the period. Start your answer with CONTEXT.prefix (if it is not empty). Mention ROI, MOIC, "
        "and IRR, and how the balance changed from beginning to ending. When you quote numbers, use the "
        "pre-formatted strings CONTEXT.metrics.*_str and CONTEXT.balances.*_str; do not invent or "
        "recompute any figures. Keep the explanation to 2–3 short sentences."
    )

    answer = _ask_llm(sys, ctx, message)
    return {"answer": answer, "context": ctx}


# -----------------------------------------------------------------------------
# Investment helpers + intent
# -----------------------------------------------------------------------------
def _to_float(x: Any) -> float:
    try:
        return float(x or 0.0)
    except Exception:
        return 0.0

def _extract_investment_name(message: str) -> str:
    msg = (message or "").strip()
    msg = re.sub(r"\b(my|the|this|that|latest|last|recent)\b", "", msg, flags=re.IGNORECASE)
    msg = re.sub(
        r"\b(invest(ment|ed)?|position|holding|nav|valuation|value|in)\b",
        "",
        msg,
        flags=re.IGNORECASE,
    )
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg

def _find_investment_by_name(query: str) -> Optional[Investment]:
    if not query:
        return None
    try:
        all_invs: List[Investment] = Investment.query.all()
    except Exception:
        return None
    names = [inv.name for inv in all_invs if inv.name]
    if not names:
        return None
    best = difflib.get_close_matches(query.lower(), [n.lower() for n in names], n=1, cutoff=0.6)
    if not best:
        return None
    match_lower = best[0]
    for inv in all_invs:
        if inv.name and inv.name.lower() == match_lower:
            return inv
    return None

def _pick_investment_point(rows: List[PortfolioInvestmentValue], target: Optional[date]):
    if not rows:
        return None, None
    if not target:
        sel = rows[-1]
        prev = rows[-2] if len(rows) > 1 else None
        return sel, prev
    tkey = _ym_key(_as_date(target))
    sel = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None
    for r in rows:
        dt = _as_date(getattr(r, "as_of_date", None))
        if not dt:
            continue
        rk = _ym_key(dt)
        if rk <= tkey:
            prev = sel
            sel = r
    return sel, prev

def handle_investment_intent(user: Dict[str, Any], message: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Answer: value of a specific investment for a month (or latest)."""
    name_q = _extract_investment_name(message)
    invt = _find_investment_by_name(name_q)
    if not invt:
        ctx = {"ok": False, "reason": "no_investment_match", "query": name_q}
        sys = (
            "Kindly explain that no investment matched the request and suggest the closest portfolio "
            "names if available."
        )
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    try:
        rows = (
            PortfolioInvestmentValue.query
            .filter(PortfolioInvestmentValue.investment_id == invt.id)
            .order_by(PortfolioInvestmentValue.as_of_date.asc())
            .all()
        )
    except Exception:
        rows = []

    if not rows:
        ctx = {
            "ok": False,
            "reason": "no_investment_points",
            "investment": {"id": invt.id, "name": invt.name},
        }
        sys = "Explain that there are no valuation points stored for this investment."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    target = _extract_target_date(message)
    sel, prev = _pick_investment_point(rows, target)

    val = _to_float(getattr(sel, "value", None))
    as_of = getattr(sel, "as_of_date", None)
    month_label = as_of.strftime("%B %Y") if as_of else "the latest period"
    answer = f"{_prefix()}as of {month_label}, {invt.name} is valued at {_fmt_money(val)}"

    if prev:
        prev_val = _to_float(getattr(prev, "value", None))
        chg = val - prev_val
        sign = "up" if chg >= 0 else "down"
        pct = None
        if prev_val and prev_val != 0.0:
            pct = (chg / prev_val) * 100.0
        prev_label = prev.as_of_date.strftime("%B %Y") if prev.as_of_date else "the prior period"
        if pct is not None and math.isfinite(pct):
            answer += (
                f" — {sign} {_fmt_money(abs(chg))} ({_fmt_pct(abs(pct))}) vs {prev_label}."
            )
        else:
            answer += f" — {sign} {_fmt_money(abs(chg))} vs {prev_label}."
    else:
        answer += "."

    ctx = {
        "ok": True,
        "investment": {"id": invt.id, "name": invt.name},
        "as_of": str(as_of) if as_of else None,
        "value": val,
    }
    return {"answer": answer, "context": ctx}

# -----------------------------------------------------------------------------
# INTENT 4: Fee breakdown (uses Statement rows)
# -----------------------------------------------------------------------------
def handle_fee_breakdown_intent(user: Dict[str, Any], message: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Explain management, incentive, and operating fees for a given period (or latest statement).
    """
    inv = _resolve_investor_for_request(user, body)

    # Admin can target anyone by free text
    is_admin = str(user.get("user_type", "")).lower() == "admin"
    if is_admin:
        pick = _admin_pick_investor_from_text(message)
        if pick:
            inv = pick

    if not inv:
        ctx = {"ok": False, "issue": "no_investor_identity"}
        sys = "Explain that the investor could not be identified and suggest reloading the dashboard."
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # Fetch all statements for this investor
    try:
        rows = (
            Statement.query
            .filter(Statement.investor_id == inv.id)
            .order_by(Statement.period_end.asc())
            .all()
        )
    except Exception:
        rows = []

    if not rows:
        ctx = {
            "ok": False,
            "issue": "no_statement_rows",
            "investor": {"id": inv.id, "name": inv.name},
        }
        sys = (
            "Explain that there are no statements (and therefore no fee details) available yet "
            "for this investor."
        )
        return {"answer": _ask_llm(sys, ctx, message), "context": ctx}

    # Choose period using unified date resolver
    target_dt = _extract_target_date(message)
    chosen = rows[-1]
    if target_dt:
        same_month = [
            r
            for r in rows
            if r.period_end
            and r.period_end.year == target_dt.year
            and r.period_end.month == target_dt.month
        ]
        if same_month:
            chosen = same_month[-1]
        else:
            before = [r for r in rows if r.period_end and r.period_end <= target_dt]
            if before:
                chosen = before[-1]

    def _f(v: Any) -> float:
        try:
            return float(v or 0.0)
        except Exception:
            return 0.0

    mgmt = _f(chosen.management_fees)
    incent = _f(chosen.incentive_fees)
    opex = _f(chosen.operating_expenses)
    total_fees = mgmt + incent + opex

    beginning = _f(chosen.beginning_balance)
    ending = _f(chosen.ending_balance)
    net_income = _f(chosen.net_income_loss)

    fee_vs_income = (total_fees / net_income * 100.0) if net_income not in (0.0, 0, None) else None
    fee_vs_begin = (total_fees / beginning * 100.0) if beginning not in (0.0, 0, None) else None

    ctx = {
        "ok": True,
        "investor": {"id": inv.id, "name": inv.name},
        "period": {
            "start": chosen.period_start.isoformat() if chosen.period_start else None,
            "end": chosen.period_end.isoformat() if chosen.period_end else None,
        },
        "fees": {
            "management_fees": mgmt,
            "incentive_fees": incent,
            "operating_expenses": opex,
            "total_fees": total_fees,
        },
        "balances": {
            "beginning_balance": beginning,
            "ending_balance": ending,
        },
        "net_income_loss": net_income,
        "ratios": {
            "fees_as_pct_of_net_income": fee_vs_income,
            "fees_as_pct_of_beginning_balance": fee_vs_begin,
        },
    }

    sys = (
        "You are a professional fund reporting assistant. Using CONTEXT, explain the investor's fees "
        "for the period. Start with the total dollar amount of fees, then break it into management, "
        "incentive, and operating expenses, and briefly comment on how large that is relative to net "
        "income and (if available) beginning balance. Keep it to 2–3 sentences and do not invent "
        "any numbers not present in CONTEXT."
    )
    answer = _ask_llm(sys, ctx, message)
    return {"answer": answer, "context": ctx}

# -----------------------------------------------------------------------------
# INTENT 5: General (friendly LLM voice)
# -----------------------------------------------------------------------------
def handle_general_intent(message: str) -> Dict[str, Any]:
    sys = (
        "You are a warm, concise personal assistant for investors. Be helpful, upbeat, "
        "and keep replies to 1–2 sentences unless the user asks for more detail."
    )
    return {"answer": _ask_llm(sys, {"flow": "general"}, message), "context": {"flow": "general"}}

# Intent detection
# ---------------------------------------------------------------------------
def detect_intent(message: str) -> Dict[str, Any]:
    m = (message or "").lower()

    # 0) Explicit file-summary / explanation requests
    if (
        re.search(r"\b(summarise|summarize|summary|summaries|explain|explanation)\b", m)
        and re.search(r"\b(document|file|report|statement|pdf)\b", m)
    ):
        return {"type": "file_summary"}

    if re.fullmatch(
        r"(please )?(give me )?(a )?(summary|short summary|brief summary|explanation)( please)?",
        m,
    ) or re.fullmatch(
        r"(please )?(summarize|explain) (it|this|that|file|document|statement|pdf)", m
    ):
        return {"type": "file_summary"}

    # 1) File-oriented requests
    if re.search(r"\b(document|file|pdf|upload|download|share)\b", m):
        return {"type": "file_retrieval"}

    # 1b) Dependent / child account creation requests
    if (
        ("dependent account" in m)
        or ("child account" in m)
        or (
            re.search(r"\b(dependent|depends|child)\b", m)
            and re.search(r"\b(account|investor|profile)\b", m)
        )
    ):
        return {"type": "dependent_request"}

    # 1c) Group account creation requests
    if (
        "group account" in m
        or (
            "group" in m
            and re.search(r"\b(account|investor|profile)\b", m)
        )
    ):
        return {"type": "group_request"}

    # Admin email to investors
    if re.search(r"\b(email|e-mail|mail|message|contact|reach out|send)\b", m) and re.search(
        r"\b(investor|investors|client|clients)\b", m
    ):
        return {"type": "email_investors"}

    # Investors to Admin email
    if re.search(r"\b(email|e-mail|mail|message|contact|reach out|send)\b", m) and re.search(
        r"\b(admin|administrator|support|manager)\b", m
    ):
        return {"type": "email_admin"}

    # 2) Use lightweight NLP router for financial vs non-financial classification
    try:
        info = nlp_parse_intent(message)
    except Exception:
        info = {}

    domain = str(info.get("domain", "unknown") or "unknown").lower()
    kind = info.get("kind")

    if domain == "financial":
        if re.search(r"\bfee|fees|management fee|incentive fee|performance fee|carry\b", m):
            return {"type": "fee_breakdown"}

        if kind == "balance":
            return {"type": "balance_data"}

        if kind in {"growth", "gain_loss"}:
            return {"type": "calculation_data"}

        if kind == "investments":
            return {"type": "investment_data"}

        return {"type": "calculation_data"}

    # 3) Fallback heuristics
    if "balance" in m and re.search(r"\b(ending|current|beginning|initial|start|end)\b", m):
        return {"type": "balance_data"}
    if "balance" in m and re.search(
        r"(20\d{2}[-/](0[1-9]|1[0-2])|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)",
        m,
    ):
        return {"type": "balance_data"}

    if re.search(r"\b(invest(ment|ed)?|position|holding|nav|valuation|value)\b", m):
        return {"type": "investment_data"}

    # 4) Non-financial fallback
    system = (
        "Classify message into: balance_data, file_retrieval, file_summary, calculation_data, "
        "investment_data, email_admin, email_investors, general. "
        'Return ONLY JSON like {"type":"calculation_data"}'
    )
    raw = llm.chat(f"{system}\n\nMessage: {message}\n\nJSON:", model=GEN_MODEL)
    try:
        obj = json.loads(re.search(r"\{.*\}", raw, flags=re.DOTALL).group(0))
        t = str(obj.get("type", "general")).strip().lower()
    except Exception:
        t = "general"
    if t not in {
        "balance_data",
        "file_retrieval",
        "file_summary",
        "calculation_data",
        "investment_data",
        "email_admin",
        "email_investors",
        "general",
    }:
        t = "general"
    return {"type": t}
# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@chat_bp.route("/chat", methods=["POST"])
@login_required
def chat():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    message: str = (data.get("message") or "").strip()
    tenant = data.get("tenant") or "default"
    conversation_id = data.get("conversation_id") or uuid.uuid4().hex

    user = _get_user_safe()

    # --------- SECURITY: block dependent investors from the chat endpoint ---------
    if not _user_is_admin(user):
        self_inv = _strict_self_investor(user)
        if _is_dependent_investor(self_inv):
            return jsonify({"error": "Chat is disabled for dependent accounts."}), 403
    # ------------------------------------------------------------------------------

    # Log the user turn first
    _append_turn(tenant, conversation_id, "user", message, meta=None)

    # Load any multi-step states from recent assistant messages
    pending_email = _get_pending_email_state(tenant, conversation_id)
    pending_inv_email = _get_pending_investor_email_state(tenant, conversation_id)
    pending_dep_req = _get_pending_dependent_request_state(tenant, conversation_id)
    pending_group_req = _get_pending_group_request_state(tenant, conversation_id)

    msg_low = (message or "").lower()

    # ------------------------------------------------------------------
    # 1) Base intent detection for THIS message
    # ------------------------------------------------------------------
    detected = detect_intent(message)
    itype = detected.get("type", "general")

    # Admin-specific override for email vs investors/admin
    if _user_is_admin(user):
        ml = msg_low
        mentions_email = any(
            k in ml
            for k in [
                "email",
                "e-mail",
                "send email",
                "send a mail",
                "send a message",
            ]
        )
        mentions_admin = re.search(r"\b(admin|administrator|support|manager)\b", ml)
        mentions_investor = re.search(
            r"\b(investor|investors|client|clients)\b", ml
        )
        mentions_file = re.search(
            r"\b(document|file|pdf|statement|report)\b", ml
        )

        # Only re-route to email intents when they’re clearly talking about email
        # and NOT talking about files at the same time.
        if mentions_email and not mentions_file:
            if mentions_admin and not mentions_investor:
                itype = "email_admin"
            else:
                itype = "email_investors"

    # ------------------------------------------------------------------
    # 2) Determine whether any multi-step flows are currently active
    #    and should keep control of this message.
    #
    #    RULE: a flow only keeps control if:
    #      - it has an active pending state, AND
    #      - the new message is classified as either:
    #          * that same intent type, or
    #          * "general" (ambiguous, e.g. "yes", "please send it", etc.)
    #
    #    This means that if the user clearly asks about something else
    #    (file, balance, ROI, investments, etc.), we IGNORE the pending
    #    flow and honor the new intent instead.
    # ------------------------------------------------------------------
    email_flow_active = bool(
        pending_email
        and pending_email.get("stage") in {"await_body", "confirm_send"}
    )
    inv_email_flow_active = bool(
        pending_inv_email
        and pending_inv_email.get("stage")
        in {
            "choose_scope",
            "await_investor",
            "await_body_all",
            "await_body_single",
            "confirm_send",
        }
    )
    dep_flow_active = bool(
        pending_dep_req
        and pending_dep_req.get("stage") in {"await_details"}
    )
    group_flow_active = bool(
        pending_group_req
        and pending_group_req.get("stage") in {"await_members", "confirm"}
    )

    # Let active flows "win" only when the new message is ambiguous
    # (general) or explicitly the same flow type.
    if email_flow_active and itype in {"email_admin", "general"}:
        itype = "email_admin"
    elif inv_email_flow_active and itype in {"email_investors", "general"}:
        itype = "email_investors"
    elif dep_flow_active and itype in {"dependent_request", "general"}:
        itype = "dependent_request"
    elif group_flow_active and itype in {"group_request", "general"}:
        itype = "group_request"
    # Otherwise, if the new message clearly belongs to another intent
    # (file_retrieval, balance_data, calculation_data, investment_data,
    # fee_breakdown, file_summary, general, etc.), we DO NOT override
    # itype — the user is switching topic and that should be respected.

    # ------------------------------------------------------------------
    # 3) Dispatch to the chosen intent handler
    # ------------------------------------------------------------------
    if itype == "balance_data":
        result = handle_balance_intent(user, message, data)
    elif itype == "file_retrieval":
        result = handle_file_intent(user, message, data)
    elif itype == "file_summary":
        result = handle_file_summary_intent(
            user, message, data, tenant, conversation_id
        )
    elif itype == "calculation_data":
        result = handle_calc_intent(user, message, data)
    elif itype == "investment_data":
        result = handle_investment_intent(user, message, data)
    elif itype == "fee_breakdown":
        result = handle_fee_breakdown_intent(user, message, data)
    elif itype == "email_admin":
        result = handle_email_admin_intent(
            user, message, data, tenant, conversation_id
        )
    elif itype == "email_investors":
        result = handle_email_investors_intent(
            user, message, data, tenant, conversation_id
        )
    elif itype == "dependent_request":
        result = handle_dependent_request_intent(
            user, message, data, tenant, conversation_id
        )
    elif itype == "group_request":
        result = handle_group_request_intent(
            user, message, data, tenant, conversation_id
        )
    else:
        result = handle_general_intent(message)

    assistant_meta = result.get("meta")
    _append_turn(
        tenant, conversation_id, "assistant", result["answer"], meta=assistant_meta
    )

    return (
        jsonify(
            {
                "type": itype,
                "answer": result["answer"],
                "context": result.get("context"),
                "conversation_id": conversation_id,
                "tenant": tenant,
            }
        ),
        200,
    )

@chat_bp.route("/statement-file/<int:statement_id>", methods=["GET"])
@login_required
def download_statement_file(statement_id: int):
    """
    Download a Statement PDF by id for the logged-in user/admin.

    Uses Statement.pdf_path and UPLOAD_ROOTS to locate the file.
    """
    stmt = Statement.query.get_or_404(statement_id)

    path = (getattr(stmt, "pdf_path", None) or "").strip()
    if not path:
        return jsonify({"error": "No file is attached to this statement."}), 404

    lower = path.lower()

    # If pdf_path is an external URL, just redirect the browser there.
    if lower.startswith(("http://", "https://")):
        return redirect(path)

    # Try to locate on disk under configured upload roots
    full = _find_on_disk(path)
    if not full and os.path.isabs(path) and os.path.exists(path):
        full = path

    if not full:
        return jsonify({"error": "Statement file not found on server."}), 404

    # Pick a nice filename for the browser
    import os
    download_name = request.args.get("filename") or os.path.basename(path) or f"statement-{statement_id}.pdf"

    return send_file(full, as_attachment=True, download_name=download_name)


@chat_bp.route("/statement-preview/<int:statement_id>", methods=["GET"])
@login_required
def preview_statement_file(statement_id: int):
    """
    Inline preview of a Statement PDF by id.
    Uses Statement.pdf_path and UPLOAD_ROOTS. Does NOT force download.
    """
    stmt = Statement.query.get_or_404(statement_id)

    path = (getattr(stmt, "pdf_path", None) or "").strip()
    if not path:
        return jsonify({"error": "No file is attached to this statement."}), 404

    lower = path.lower()

    # External URL? Just redirect.
    if lower.startswith(("http://", "https://")):
        return redirect(path)

    # Locate on disk
    full = _find_on_disk(path)
    if not full and os.path.isabs(path) and os.path.exists(path):
        full = path

    if not full:
        return jsonify({"error": "Statement file not found on server."}), 404

    import os
    download_name = (
        request.args.get("filename")
        or os.path.basename(path)
        or f"statement-{statement_id}.pdf"
    )

    # 👇 as_attachment=False lets browser open PDF viewer instead of Save dialog
    return send_file(full, as_attachment=False, download_name=download_name)



@chat_bp.route("/document-preview/<int:doc_id>", methods=["GET"])
@login_required
def preview_document_file(doc_id: int):
    """
    Inline preview of a shared Document PDF.

    Security:
      - Admins can preview any document.
      - Investors can only preview documents that have been shared with them
        (via DocumentShare.investor_user_id).
    """
    user = _get_user_safe()
    doc = Document.query.get_or_404(doc_id)

    # Permission check: admin OR shared with this user
    if not _user_is_admin(user):
        shared = (
            DocumentShare.query.filter_by(
                document_id=doc.id,
                investor_user_id=user.id,
            ).first()
        )
        if not shared:
            return (
                jsonify(
                    {"error": "You do not have access to this document."}
                ),
                403,
            )

    # Locate file on disk using the stored_name + UPLOAD_ROOTS
    stored = (getattr(doc, "stored_name", None) or "").strip()
    if not stored:
        return jsonify({"error": "No file is attached to this document."}), 404

    full = _find_on_disk(stored)
    if not full and os.path.isabs(stored) and os.path.exists(stored):
        full = stored

    if not full:
        return jsonify({"error": "Document file not found on server."}), 404

    download_name = (
        request.args.get("filename")
        or doc.original_name
        or doc.title
        or f"doc-{doc.id}.pdf"
    )

    # 👇 as_attachment=False ⇒ browser opens PDF viewer (preview) instead of Save dialog
    return send_file(full, as_attachment=False, download_name=download_name)
