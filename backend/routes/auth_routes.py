# backend/routes/auth_routes.py
from __future__ import annotations

import secrets
from datetime import timedelta, datetime
from typing import Optional, Dict, Any

from flask import (
    Blueprint, jsonify, request, session, current_app, make_response
)
from werkzeug.security import check_password_hash
from flask_login import login_user, logout_user, current_user, login_required

from backend.models import User, Investor, SmsVerification
from backend.extensions import db
from backend.services.sms import send_sms
from backend.models import ActivityLog  # login/logout activity logs

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _find_user_by_identifier(identifier: str) -> Optional[User]:
    """Try email first, then username (if present)."""
    ident = (identifier or "").strip().lower()
    if not ident:
        return None

    user = User.query.filter(User.email.ilike(ident)).first()
    if user:
        return user

    if "@" not in ident and hasattr(User, "username"):
        return User.query.filter(User.username.ilike(ident)).first()

    return None


def _issue_csrf_cookie(resp):
    """
    Double-submit CSRF cookie:
    - Server stores token in session["csrf_token"]
    - Client echoes cookie value in 'X-XSRF-TOKEN' on mutating requests
    """
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token

    samesite = current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax")
    secure = current_app.config.get("SESSION_COOKIE_SECURE", True)

    resp.set_cookie(
        "XSRF-TOKEN",
        token,
        max_age=int(timedelta(hours=12).total_seconds()),
        httponly=False,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _clear_csrf_cookie(resp):
    resp.set_cookie("XSRF-TOKEN", "", max_age=0, expires=0, path="/")


def _session_user_dict() -> Dict[str, Any]:
    """Return normalized user dict from current_user/session."""
    # Prefer Flask-Login
    if getattr(current_user, "is_authenticated", False):
        u = current_user
    else:
        uid = session.get("user_id")
        if not uid:
            return {}
        u = User.query.get(int(uid))
        if not u:
            session.clear()
            return {}

    def _n(s): return (s or "").strip()

    return {
        "id": int(u.id),
        "email": (u.email or "").lower(),
        "name": f"{_n(getattr(u, 'first_name', ''))} {_n(getattr(u, 'last_name', ''))}".strip() or None,
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
        "user_type": (getattr(u, "user_type", "") or "Investor"),
        "permission": getattr(u, "permission", "Viewer"),
    }


def _map_user_to_investor(user_dict: Dict[str, Any]) -> Optional[Investor]:
    """Map the logged-in user → Investor by account_user_id → email → full name."""
    if not user_dict:
        return None

    inv = Investor.query.filter_by(account_user_id=user_dict.get("id")).first()
    if inv:
        return inv

    email = user_dict.get("email")
    if email:
        inv = Investor.query.filter(Investor.email.ilike(email)).first()
        if inv:
            return inv

    full = " ".join(filter(
        None,
        [
            (user_dict.get("first_name") or "").strip(),
            (user_dict.get("last_name") or "").strip(),
        ],
    )).strip() or (user_dict.get("name") or "")
    if full:
        inv = Investor.query.filter(Investor.name.ilike(full)).first()
        if inv:
            return inv

    return None


def _require_csrf():
    """Validate CSRF header for mutating calls when session exists."""
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    if not (session.get("user_id") or getattr(current_user, "is_authenticated", False)):
        # No logged-in session → nothing to protect yet
        return
    sent = request.headers.get("X-XSRF-TOKEN", "")
    if not sent or sent != session.get("csrf_token"):
        return jsonify({"ok": False, "error": "CSRF validation failed"}), 403


def _needs_sms_verification(user: User) -> bool:
    """
    Require SMS verification when:

    - The user is an INVESTOR (user_type == 'investor'), AND
    - They have a phone, AND
    - EITHER:
        • last_sms_verified_at is NULL  → first login
        • OR last_sms_verified_at is older than 30 days.
    """
    user_type = (getattr(user, "user_type", "") or "").strip().lower()
    if user_type != "investor":
        # Admins / group admins / others: no SMS requirement (for now)
        return False

    phone = getattr(user, "phone", None)
    if not phone:
        # No phone configured -> can't do SMS; skip requirement
        return False

    last = getattr(user, "last_sms_verified_at", None)
    if not last:
        # First login (no previous SMS verification)
        return True

    # Monthly re-check
    return datetime.utcnow() - last >= timedelta(days=30)


def _start_sms_challenge(user: User) -> None:
    """
    Create a 6-digit OTP challenge and store it in BOTH:
      - the session (for quick lookup), and
      - the sms_verification table (for audit + re-checking).
    """
    # Clear any old challenge from the session
    session.pop("pending_sms_user_id", None)
    session.pop("pending_sms_code", None)
    session.pop("pending_sms_verification_id", None)

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    # Create DB row
    sv = SmsVerification(
        user_id=user.id,
        phone=user.phone,
        code=code,
        purpose="login",
        status="pending",
        expires_at=expires_at,
    )
    db.session.add(sv)
    db.session.commit()  # so sv.id is available

    # Mirror minimal info in the session to bind browser ⇄ record
    session["pending_sms_user_id"] = int(user.id)
    session["pending_sms_code"] = code
    session["pending_sms_verification_id"] = int(sv.id)

    # Actually send the SMS
    msg = f"Your Elpis investor portal verification code is: {code}"
    send_sms(user.phone, msg)


def _log_activity(user: Optional[User], action: str) -> None:
    """
    Write a login/logout event to ActivityLog (best-effort).
    """
    try:
        uid = int(getattr(user, "id", 0)) if user else None
        name = None
        role = None
        if user:
            name = (
                f"{(user.first_name or '').strip()} "
                f"{(user.last_name or '').strip()}".strip()
                or (user.email or "")
            )
            role = (user.user_type or "viewer").lower()

        db.session.add(
            ActivityLog(
                user_id=uid,
                name=name,
                role=role,
                action=action,
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=(request.headers.get("User-Agent") or "")[:255],
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


# ─────────────────────────────────────────────────────────────
# Global CSRF guard for /api and /auth
# ─────────────────────────────────────────────────────────────

@auth_bp.before_app_request
def _csrf_guard():
    if request.path.startswith(("/api", "/auth")):
        err = _require_csrf()
        if err:
            return err
    return None


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@auth_bp.post("/login")
def login():
    """
    Simple login with SMS verification disabled.

    Accepts JSON: { email|username, password }
    On success:
      - logs the user in with Flask-Login
      - stores basic info in the session
      - issues XSRF cookie
      - returns { ok: True, requires_sms: False }
    """
    data = request.get_json(silent=True) or {}
    identifier = (data.get("email") or data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not identifier or not password:
        return jsonify({"ok": False, "error": "Missing credentials"}), 400

    user = _find_user_by_identifier(identifier)
    if not user:
        return jsonify({"ok": False, "error": "Invalid email/username or password"}), 401

    hashed = getattr(user, "password_hash", None) or getattr(user, "password", None)
    if not hashed or not check_password_hash(hashed, password):
        return jsonify({"ok": False, "error": "Invalid email/username or password"}), 401

    # ⬇⬇ SMS VERIFICATION DISABLED HERE ⬇⬇
    # We skip _needs_sms_verification / _start_sms_challenge
    login_user(user, remember=False)

    session["user_id"]    = int(user.id)
    session["email"]      = (user.email or "").lower()
    session["user_type"]  = (getattr(user, "user_type", "") or "Investor").lower()
    session["permission"] = getattr(user, "permission", "Viewer")
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(hours=12)

    resp = make_response(jsonify({"ok": True, "requires_sms": False}))
    _issue_csrf_cookie(resp)
    return resp, 200


@auth_bp.post("/verify-sms")
def verify_sms():
    """
    Second step of login for investors that require SMS verification.
    Accepts JSON: { code }.
    On success: logs the user in, records ActivityLog('login'), issues CSRF.
    """
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()

    if not code:
        return jsonify({"ok": False, "error": "Code is required"}), 400

    uid = session.get("pending_sms_user_id")
    expected = session.get("pending_sms_code")
    ver_id = session.get("pending_sms_verification_id")
    print(code,"This is verify code")
    if not uid or not expected or not ver_id:
        return jsonify({"ok": False, "error": "No SMS verification in progress"}), 400

    if code != expected:
        return jsonify({"ok": False, "error": "Invalid code"}), 400

    # Look up DB record
    sv = SmsVerification.query.get(ver_id)
    if sv and sv.status == "pending":
        # Optional: extra safety check
        if sv.user_id != uid:
            return jsonify({"ok": False, "error": "Invalid verification context"}), 400
        if sv.expires_at and datetime.utcnow() > sv.expires_at:
            sv.status = "expired"
            db.session.commit()
            return jsonify({"ok": False, "error": "Code has expired"}), 400

        # Mark verified in DB
        sv.mark_verified()
        db.session.commit()

    # Clean session flags for this challenge
    session.pop("pending_sms_user_id", None)
    session.pop("pending_sms_code", None)
    session.pop("pending_sms_verification_id", None)

    # NOW log the user in and issue CSRF cookie
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 400

    login_user(user, remember=False)
    session["user_id"] = int(user.id)
    session["email"] = (user.email or "").lower()
    session["user_type"] = (getattr(user, "user_type", "") or "Investor").lower()
    session["permission"] = getattr(user, "permission", "Viewer")
    session.permanent = True
    current_app.permanent_session_lifetime = timedelta(hours=12)

    _log_activity(user, "login")

    resp = make_response(jsonify({"ok": True}))
    _issue_csrf_cookie(resp)
    return resp, 200


@auth_bp.post("/logout")
def logout():
    """Log out Flask-Login and clear the session + CSRF cookie, logging activity."""
    # Capture user before clearing session
    user = current_user if getattr(current_user, "is_authenticated", False) else None
    try:
        logout_user()
    except Exception:
        pass
    session.clear()

    if user:
        _log_activity(user, "logout")

    resp = make_response(jsonify({"ok": True}))
    _clear_csrf_cookie(resp)
    return resp, 200


@auth_bp.get("/me")
@login_required
def me():
    """
    Return the logged-in user + mapped investor for the dashboard.
    Shape: { ok, user: {...}, investor: {id, name} | null }
    """
    user_dict = _session_user_dict()
    if not user_dict:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    inv = _map_user_to_investor(user_dict)
    return (
        jsonify(
            {
                "ok": True,
                "user": user_dict,
                "investor": {
                    "id": getattr(inv, "id", None),
                    "name": getattr(inv, "name", None),
                }
                if inv
                else None,
            }
        ),
        200,
    )


# Optional debugging helper
@auth_bp.get("/whoami")
def whoami():
    return me()
