# backend/routes/admin_invites_routes.py
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import and_

from backend.extensions import db
from backend.models import User, Invitation

# Flask-Mail is optional at runtime; we detect it cleanly.
try:
    from flask_mail import Message  # type: ignore
except Exception:  # pragma: no cover
    Message = None  # type: ignore

admin_invites_bp = Blueprint("admin_invites", __name__, url_prefix="/api/admin")


# ---------------- helpers ----------------
def _now() -> datetime:
    return datetime.utcnow()


def _is_admin_user() -> bool:
    if not getattr(current_user, "is_authenticated", False):
        return False
    return (current_user.user_type or "").strip().lower() == "admin"


def _invite_expiry_days() -> int:
    return int(getattr(current_app.config, "ADMIN_INVITE_EXPIRY_DAYS", 7))


def _frontend_accept_url(token: str) -> str:
    base = (
        getattr(current_app.config, "FRONTEND_BASE_URL", "")
        or getattr(current_app.config, "FRONTEND_URL", "")
    ).rstrip("/")
    if base:
        return f"{base}/invite/admin/{token}"
    return request.host_url.rstrip("/") + f"/invite/admin/{token}"


def _mail_ext():
    """
    Return the Flask-Mail extension instance if configured, else None.
    """
    return current_app.extensions.get("mail")


def _send_invite_email(
    name: str, email: str, accept_url: str
) -> tuple[bool, str | None]:
    """
    Try to send the invite email. Returns (emailed, error_msg).
    Never raises to the client; we log instead and tell the caller what happened.
    """
    mail = _mail_ext()
    if not (mail and Message):
        current_app.logger.warning(
            "Mail extension not configured; skipping email send."
        )
        return False, "Mail extension not configured"

    try:
        subject = "You're invited to be an Admin"
        display_name = (name or "").strip() or "there"
        html = (
            f"<p>Hello {display_name},</p>"
            f"<p>You’ve been invited to join as an <strong>Admin</strong>.</p>"
            f'<p><a href="{accept_url}">Click here to accept the invitation</a>.</p>'
            f"<p>This link will expire in {_invite_expiry_days()} days.</p>"
        )
        msg = Message(subject=subject, recipients=[email], html=html)
        mail.send(msg)
        return True, None
    except Exception as e:  # pragma: no cover
        current_app.logger.exception("Failed to send admin invite email")
        return False, str(e)


# ---------------- routes ----------------
@admin_invites_bp.post("/invite-admin")
@login_required
def invite_admin():
    """
    Create an admin invitation and (attempt to) email the accept link.
    Body: { name, email }
    """
    if not _is_admin_user():
        return (
            jsonify({"ok": False, "error": "Only admins can invite admins."}),
            403,
        )

    inviter_id = getattr(current_user, "id", None)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not name or not email:
        return (
            jsonify({"ok": False, "error": "Name and email are required."}),
            400,
        )

    if User.query.filter(User.email == email).first():
        return (
            jsonify({"ok": False, "error": "A user with this email already exists."}),
            409,
        )

    # Reuse an existing pending invite, else create a fresh one.
    inv = Invitation.query.filter(
        and_(Invitation.email == email, Invitation.status == "pending")
    ).first()
    reused = False

    if inv:
        token = inv.token
        reused = True
    else:
        token = secrets.token_urlsafe(32)
        inv_kwargs = dict(
            email=email,
            name=name or None,
            token=token,
            status="pending",
            invited_by=int(inviter_id) if inviter_id else None,
        )
        if hasattr(Invitation, "expires_at"):
            inv_kwargs["expires_at"] = _now() + timedelta(
                days=_invite_expiry_days()
            )

        inv = Invitation(**inv_kwargs)
        db.session.add(inv)
        db.session.commit()

    accept_url = _frontend_accept_url(token)
    emailed, mail_error = _send_invite_email(name, email, accept_url)

    # If we didn't email, include the accept_url so you can test locally without SMTP.
    return (
        jsonify(
            {
                "ok": True,
                "token": token,
                "reused": reused,
                "emailed": emailed,
                "mail_error": mail_error,
                "accept_url": None if emailed else accept_url,
            }
        ),
        200 if reused else 201,
    )


@admin_invites_bp.get("/invitations/<token>")
def get_invitation(token: str):
    inv: Invitation | None = Invitation.query.filter(
        Invitation.token == token
    ).first()
    if not inv:
        return jsonify({"ok": False, "error": "Invalid invitation."}), 404
    if inv.status != "pending":
        return (
            jsonify({"ok": False, "error": f"Invitation already {inv.status}."}),
            410,
        )
    if getattr(inv, "expires_at", None) and inv.expires_at < _now():
        return jsonify({"ok": False, "error": "Invitation expired."}), 410

    return jsonify(
        {
            "ok": True,
            "email": inv.email,
            "name": inv.name or "",
            "status": inv.status,
        }
    )


@admin_invites_bp.post("/invitations/<token>/accept")
def accept_invitation(token: str):
    """
    Accept an admin invitation and create the user account.

    Request body (JSON):
      first_name, last_name, password   (required)
      phone, address, company, country, state, city, tax_id (optional)
    """
    inv: Invitation | None = Invitation.query.filter(
        Invitation.token == token
    ).first()
    if not inv:
        return jsonify({"ok": False, "error": "Invalid invitation."}), 404
    if inv.status != "pending":
        return (
            jsonify({"ok": False, "error": f"Invitation already {inv.status}."}),
            410,
        )
    if getattr(inv, "expires_at", None) and inv.expires_at < _now():
        return jsonify({"ok": False, "error": "Invitation expired."}), 410

    body = request.get_json(silent=True) or {}
    first_name = (body.get("first_name") or "").strip()
    last_name = (body.get("last_name") or "").strip()
    password = (body.get("password") or "").strip()

    # New optional fields
    phone = (body.get("phone") or "").strip() or None
    address = (body.get("address") or "").strip() or None
    company = (body.get("company") or "").strip() or None  # -> organization_name
    country = (body.get("country") or "").strip() or None
    state = (body.get("state") or "").strip() or None
    city = (body.get("city") or "").strip() or None
    tax_id = (body.get("tax_id") or "").strip() or None

    if not first_name or not last_name or not password:
        return (
            jsonify(
                {"ok": False, "error": "All required fields must be provided."}
            ),
            400,
        )

    if User.query.filter(User.email == inv.email).first():
        return (
            jsonify({"ok": False, "error": "A user with this email already exists."}),
            409,
        )

    from werkzeug.security import generate_password_hash

    user = User(
        first_name=first_name,
        last_name=last_name,
        email=inv.email,
        user_type="admin",
        password=generate_password_hash(password),
        status="Active",
        permission="Viewer",
        # map new info
        phone=phone,
        address=address,
        organization_name=company,
        country=country,
        state=state,
        city=city,
        tax_id=tax_id,
    )
    db.session.add(user)

    inv.status = "accepted"
    if hasattr(inv, "used_at"):
        inv.used_at = _now()
    if hasattr(inv, "accepted_at"):
        inv.accepted_at = _now()

    db.session.commit()
    return jsonify({"ok": True})


# Simple diagnostics endpoint to verify mail config at runtime.
@admin_invites_bp.get("/invite-admin/mail-status")
def mail_status():
    m = _mail_ext()
    cfg = current_app.config
    return jsonify(
        {
            "has_mail_extension": bool(m),
            "MAIL_SERVER": cfg.get("MAIL_SERVER"),
            "MAIL_PORT": cfg.get("MAIL_PORT"),
            "MAIL_USE_TLS": cfg.get("MAIL_USE_TLS"),
            "MAIL_USE_SSL": cfg.get("MAIL_USE_SSL"),
            "MAIL_USERNAME": bool(cfg.get("MAIL_USERNAME")),
            "MAIL_DEFAULT_SENDER": cfg.get("MAIL_DEFAULT_SENDER"),
            "MAIL_SUPPRESS_SEND": cfg.get("MAIL_SUPPRESS_SEND"),
        }
    )



