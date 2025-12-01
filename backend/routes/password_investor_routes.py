# backend/routes/password_investor_routes.py
from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import hashlib

from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash

from backend.extensions import db
from backend.models import User, PasswordReset
from backend.utils.emailing import send_password_code

bp_code = Blueprint("password_code", __name__, url_prefix="/api/auth/password/code")


def _now() -> datetime:
    return datetime.utcnow()


def _hash_code(value: str) -> str:
    """Hash the 6-digit code so we don't store it in plain text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------- STEP 1: send code ----------------
@bp_code.post("/start")
def start_code_flow():
    """
    Step 1: Accept an email and send a 6-digit code.
    Response is generic so we don't reveal whether the email exists.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()

    if not email:
        return jsonify(ok=False, msg="Email is required."), 400

    # Look up user (case-insensitive)
    user: User | None = User.query.filter(User.email.ilike(email)).first()

    if not user:
        # Do not reveal that the email doesn't exist
        current_app.logger.info(
            "[password-code] Non-existent email requested: %s", email
        )
        return jsonify(
            ok=True,
            msg="If this email exists, a 6-digit code has been sent.",
        )

    # Generate a 6-digit numeric code, e.g. "123456"
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = _hash_code(code)

    # Optionally clear previous codes for this user
    PasswordReset.query.filter_by(user_id=user.id).delete()

    pr = PasswordReset(
        user_id=user.id,
        token=code_hash,
        expires_at=_now() + timedelta(minutes=15),
    )
    db.session.add(pr)
    db.session.commit()

    # Send email – if mail isn't configured, helper will just log the code
    try:
        send_password_code(
            user.email,
            getattr(user, "first_name", None),
            code,
        )
    except Exception as exc:
        current_app.logger.exception("Failed to send password code email: %s", exc)

    return jsonify(
        ok=True,
        msg="If this email exists, a 6-digit code has been sent.",
    )


# ---------------- internal helper ----------------
def _get_valid_reset(user: User, code: str) -> PasswordReset | None:
    """
    Find a valid PasswordReset row for this user + code.
    - Must exist
    - Must not be expired
    - Must not be used (if used_at column exists)
    """
    code_hash = _hash_code(code)

    pr: PasswordReset | None = (
        PasswordReset.query.filter_by(user_id=user.id, token=code_hash)
        .order_by(PasswordReset.id.desc())
        .first()
    )

    if not pr:
        return None

    # If the model has used_at and it's set, treat as invalid
    if hasattr(pr, "used_at") and getattr(pr, "used_at"):
        return None

    # Check expiry if the column exists
    if getattr(pr, "expires_at", None) and pr.expires_at < _now():
        return None

    return pr


# ---------------- STEP 2: verify code ----------------
@bp_code.post("/verify")
def verify_code():
    """
    Step 2: verify that the 6-digit code is correct and not expired.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()

    if not email or not code:
        return jsonify(ok=False, msg="Email and code are required."), 400

    user: User | None = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify(ok=False, msg="Invalid or expired code."), 400

    pr = _get_valid_reset(user, code)
    if not pr:
        return jsonify(ok=False, msg="Invalid or expired code."), 400

    return jsonify(ok=True, msg="Code verified.")


# ---------------- STEP 3: complete reset ----------------
@bp_code.post("/complete")
def complete_reset():
    """
    Step 3: change password using email + code + new password.
    This MUST actually update the User row.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()
    password = data.get("password") or ""
    confirm = data.get("confirm") or ""

    if not all([email, code, password, confirm]):
        return jsonify(ok=False, msg="All fields are required."), 400

    if password != confirm:
        return jsonify(ok=False, msg="Passwords do not match."), 400

    # Optionally: add extra password-strength checks here

    user: User | None = User.query.filter(User.email.ilike(email)).first()
    if not user:
        # Same generic error – don't leak whether user exists
        return jsonify(ok=False, msg="Invalid or expired code."), 400

    pr = _get_valid_reset(user, code)
    if not pr:
        return jsonify(ok=False, msg="Invalid or expired code."), 400

    # *** CRITICAL: update the correct column on User ***
    # Your app uses `password` (see _seed_default_admin in app.py),
    # so we must assign to `user.password`, not `user.password_hash`.
    user.password = generate_password_hash(password)

    # Mark the reset as used if the column exists
    if hasattr(pr, "used_at"):
        pr.used_at = _now()

    db.session.commit()

    return jsonify(ok=True, msg="Password updated successfully.")
