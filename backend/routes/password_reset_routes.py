# backend/routes/password_reset_routes.py
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets

from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash

from backend.extensions import db
from backend.models import User, PasswordReset

from backend.utils.emailing import send_password_reset

bp = Blueprint("password_reset", __name__, url_prefix="/api/auth/password")


# ---------- helpers ----------
def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _build_reset_url(token: str) -> str:
    base = current_app.config.get("APP_BASE_URL", "https://clarus.elpiscapital.com")
    return f"{base}/reset-password?token={token}"


def _set_user_password(user: User, new_password: str) -> None:
    """
    Works whether your User model has set_password(), password, or password_hash.
    """
    if hasattr(user, "set_password"):
        user.set_password(new_password)  # type: ignore[attr-defined]
    elif hasattr(user, "password"):
        # Your merged User model stores hashed passwords in `password`
        user.password = generate_password_hash(new_password)
    elif hasattr(user, "password_hash"):
        user.password_hash = generate_password_hash(new_password)
    else:
        raise RuntimeError("User model must support setting a password")


# ---------- public endpoints ----------

@bp.post("/forgot")
def forgot():
    """
    Request a password reset email. Always returns ok=True (no account enumeration).
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify(ok=True)

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify(ok=True)

    now = datetime.utcnow()
    # Reuse a valid token or create a new one
    pr = (
        PasswordReset.query.filter_by(user_id=user.id, used=False)
        .filter(PasswordReset.expires_at > now)
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if not pr:
        token = secrets.token_urlsafe(32)
        pr = PasswordReset(
            user_id=user.id,
            email=email,
            token=token,
            expires_at=now + timedelta(minutes=30),
            used=False,
        )
        db.session.add(pr)
        db.session.commit()

    reset_url = _build_reset_url(pr.token)
    send_password_reset(email, reset_url)

    return jsonify(ok=True)


@bp.post("/resend")
def resend():
    """
    Re-send the reset email for an existing unexpired token.
    Throttled to once per 60 seconds using pr.code_sent_at (if present).
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify(ok=True)

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify(ok=True)

    now = datetime.utcnow()
    pr = (
        PasswordReset.query.filter_by(user_id=user.id, used=False)
        .filter(PasswordReset.expires_at > now)
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if not pr:
        return jsonify(ok=False, error="No active reset to resend."), 400

    if getattr(pr, "code_sent_at", None) and (now - pr.code_sent_at).total_seconds() < 60:
        return jsonify(ok=False, error="Please wait a minute before resending."), 429

    reset_url = _build_reset_url(pr.token)
    send_password_reset(email, reset_url)

    # Update throttle timestamp if the column exists
    if hasattr(pr, "code_sent_at"):
        pr.code_sent_at = now

    db.session.commit()
    return jsonify(ok=True)


@bp.post("/set")
def set_new_password():
    """
    Reset password (NO SMS OTP).
    Accept token + new password (+ optional confirm), validate token, update password,
    mark reset as used, and finish in one step.
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("password") or ""
    confirm = data.get("confirm")

    if not token or not new_password:
        return jsonify(ok=False, error="Missing token or password."), 400
    if len(new_password) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters."), 400
    if confirm is not None and new_password != confirm:
        return jsonify(ok=False, error="Passwords do not match."), 400

    now = datetime.utcnow()
    pr = (
        PasswordReset.query.filter_by(token=token, used=False)
        .filter(PasswordReset.expires_at > now)
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if not pr:
        return jsonify(ok=False, error="Invalid or expired link."), 400

    user = User.query.get(pr.user_id)
    if not user:
        return jsonify(ok=False, error="Account not found."), 404

    # Update user password
    _set_user_password(user, new_password)

    # Mark reset consumed
    pr.used = True
    if hasattr(pr, "used_at"):
        pr.used_at = now

    # Clean up any OTP/pending fields if they exist (safe no-ops)
    for field in ("pending_password_hash", "otp_hash", "otp_expires_at"):
        if hasattr(pr, field):
            setattr(pr, field, None)

    db.session.commit()
    return jsonify(ok=True)


@bp.post("/verify")
def verify_disabled():
    """
    Old SMS-OTP step is disabled.
    Keeping endpoint to avoid breaking old clients, but it will not work anymore.
    """
    return jsonify(ok=False, error="SMS OTP verification is disabled."), 410
