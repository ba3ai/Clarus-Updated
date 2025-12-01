# backend/routes/password_reset_routes.py
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import random
import secrets

from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash
from backend.extensions import db
from backend.models import User, PasswordReset

# Single, correct import for mail helper
from backend.utils.emailing import send_password_reset

bp = Blueprint("password_reset", __name__, url_prefix="/api/auth/password")


# ---------- helpers ----------
def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _build_reset_url(token: str) -> str:
    base = current_app.config.get("APP_BASE_URL", "https://clarus.azurewebsites.net")
    return f"{base}/reset-password?token={token}"


def _mask_phone(p: str) -> str:
    if not p or len(p) < 4:
        return "••••"
    return "••••••••" + p[-4:]


def _send_sms(phone: str, message: str) -> None:
    """
    Plug in your SMS provider (Twilio, etc.). For dev, we just log it.
    """
    current_app.logger.info(f"[SMS to {phone}] {message}")


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
            token=token,  # token stored plaintext here; if you store hash, change to token_hash
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
    Throttled to once per 60 seconds using pr.code_sent_at.
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
    pr.code_sent_at = now
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/set")
def start_set_password():
    """
    Step 1 (frontend: 'set'): Accept token + new password.
    - Validates token.
    - Saves pending password hash on PasswordReset.
    - Generates 6-digit OTP, stores hash and expiry.
    - Sends OTP to the user's phone.
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("password") or ""
    if not token or not new_password:
        return jsonify(ok=False, error="Missing token or password."), 400
    if len(new_password) < 8:
        return jsonify(ok=False, error="Password must be at least 8 characters."), 400

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

    phone = getattr(user, "phone", None)
    if not phone:
        return jsonify(ok=False, error="No phone on file for OTP."), 400

    # Save pending password hash on the reset record
    pr.pending_password_hash = generate_password_hash(new_password)

    # Create OTP (6 digits) and store HASH + expiry
    otp = f"{random.randint(100000, 999999)}"
    pr.otp_hash = _hash(otp)
    pr.otp_expires_at = now + timedelta(minutes=10)

    db.session.commit()

    # Send the OTP via SMS (replace with your SMS provider)
    _send_sms(phone, f"Your password reset code is {otp}")

    return jsonify(ok=True, phone_mask=_mask_phone(phone))


@bp.post("/verify")
def verify_and_commit():
    """
    Step 2 (frontend: 'verify'): Accept token + code.
    - Validates token and OTP.
    - Commits pending password to the user and marks reset as used.
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    code = (data.get("code") or "").strip()

    if not token or not code:
        return jsonify(ok=False, error="Missing token or code."), 400

    now = datetime.utcnow()
    pr = (
        PasswordReset.query.filter_by(token=token, used=False)
        .filter(PasswordReset.expires_at > now)
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    if not pr or not pr.otp_hash or not pr.otp_expires_at:
        return jsonify(ok=False, error="Invalid or expired code."), 400

    if pr.otp_expires_at < now:
        return jsonify(ok=False, error="Code has expired."), 400

    if pr.otp_hash != _hash(code):
        return jsonify(ok=False, error="Incorrect code."), 400

    if not pr.pending_password_hash:
        return jsonify(ok=False, error="No pending password found."), 400

    user = User.query.get(pr.user_id)
    if not user:
        return jsonify(ok=False, error="Account not found."), 404

    # Commit the password; here we treat pending_password_hash as "already hashed"
    # so we set it directly on the correct field.
    if hasattr(user, "password_hash"):
        user.password_hash = pr.pending_password_hash
    elif hasattr(user, "password"):
        user.password = pr.pending_password_hash
    else:
        _set_user_password(user, pr.pending_password_hash)  # type: ignore[arg-type]

    # Mark reset consumed
    pr.used = True
    pr.pending_password_hash = None
    pr.otp_hash = None
    pr.otp_expires_at = None
    db.session.commit()

    return jsonify(ok=True)
