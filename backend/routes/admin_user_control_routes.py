# backend/routes/admin_user_control_routes.py
from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import json

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import or_

from backend.extensions import db
from backend.models import User, PasswordReset
from backend.models import ActivityLog  # correct place for ActivityLog

# If you already have helpers, feel free to import them:
try:
    from backend.routes.password_reset_routes import _build_reset_url
except Exception:
    # fallback; front-end expects /reset-password?token=<token>
    def _build_reset_url(token: str) -> str:
        from flask import current_app

        base = current_app.config.get("APP_BASE_URL", "http://localhost:5173")
        return f"{base}/reset-password?token={token}"


admin_uc_bp = Blueprint("admin_uc", __name__, url_prefix="/api/admin/users")


def _is_admin() -> bool:
    """Check if the current logged-in user is admin."""
    if not getattr(current_user, "is_authenticated", False):
        return False
    return (current_user.user_type or "").lower() == "admin"


def _log(
    actor_id: int | None,
    target_id: int | None,
    action: str,
    ip: str | None = None,
    details: dict | None = None,
):
    """Write an admin action into ActivityLog (best-effort)."""
    try:
        ua = ""
        if details:
            try:
                ua = json.dumps(details, sort_keys=True)
            except Exception:
                ua = str(details)
        db.session.add(
            ActivityLog(
                user_id=actor_id,
                name=None,
                role="admin",
                action=action,
                ip=ip or "admin-ui",
                user_agent=ua,
                created_at=datetime.utcnow(),
            )
        )
        db.session.flush()
    except Exception:
        # Don't break the main request if logging fails.
        pass


@admin_uc_bp.get("")
@login_required
def list_users():
    if not _is_admin():
        return jsonify(ok=False, error="forbidden"), 403

    q = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip().lower()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 100)

    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.email.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
    if role in ("admin", "investor"):
        query = query.filter(User.user_type.ilike(role))

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    def row(u: User):
        return {
            "id": u.id,
            "name": f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
            or (u.email or ""),
            "email": u.email,
            "role": (u.user_type or "").lower(),
            "is_blocked": bool(getattr(u, "is_blocked", False)),
            "blocked_at": u.blocked_at.isoformat()
            if getattr(u, "blocked_at", None)
            else None,
        }

    return jsonify(
        ok=True,
        data=[row(u) for u in pagination.items],
        page=pagination.page,
        pages=pagination.pages,
        total=pagination.total,
    )


@admin_uc_bp.post("/<int:user_id>/block")
@login_required
def block_user(user_id: int):
    if not _is_admin():
        return jsonify(ok=False, error="forbidden"), 403

    admin_id = getattr(current_user, "id", None)
    if admin_id is not None and int(admin_id) == user_id:
        return jsonify(ok=False, error="You cannot block yourself."), 400

    u = db.session.get(User, user_id)
    if not u:
        return jsonify(ok=False, error="User not found"), 404

    payload = request.get_json(silent=True) or {}
    reason = (payload.get("reason") or "").strip() or None

    u.is_blocked = True
    u.blocked_at = datetime.utcnow()
    u.blocked_by = int(admin_id) if admin_id is not None else None
    u.blocked_reason = reason
    db.session.add(u)

    _log(
        int(admin_id) if admin_id is not None else None,
        u.id,
        "block_user",
        request.headers.get("X-Forwarded-For", request.remote_addr),
        {"reason": reason},
    )
    db.session.commit()
    return jsonify(ok=True)


@admin_uc_bp.post("/<int:user_id>/unblock")
@login_required
def unblock_user(user_id: int):
    if not _is_admin():
        return jsonify(ok=False, error="forbidden"), 403

    admin_id = getattr(current_user, "id", None)

    u = db.session.get(User, user_id)
    if not u:
        return jsonify(ok=False, error="User not found"), 404

    u.is_blocked = False
    u.blocked_at = None
    u.blocked_by = None
    u.blocked_reason = None
    db.session.add(u)

    _log(
        int(admin_id) if admin_id is not None else None,
        u.id,
        "unblock_user",
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    db.session.commit()
    return jsonify(ok=True)


@admin_uc_bp.post("/<int:user_id>/send-reset")
@login_required
def send_reset(user_id: int):
    if not _is_admin():
        return jsonify(ok=False, error="forbidden"), 403

    admin_id = getattr(current_user, "id", None)

    user = db.session.get(User, user_id)
    if not user:
        return jsonify(ok=False, error="User not found"), 404

    # Generate a one-time reset token compatible with your PasswordReset table
    token_plain = secrets.token_urlsafe(24)
    expires = datetime.utcnow() + timedelta(hours=2)
    pr = PasswordReset(
        user_id=user.id,
        email=user.email,
        token=token_plain,
        expires_at=expires,
        used=False,
    )
    db.session.add(pr)
    db.session.commit()

    reset_url = _build_reset_url(token_plain)

    # Send via your existing email wrapper (if present)
    try:
        from backend.utils.emailing import send_password_reset

        send_password_reset(user.email, reset_url)
    except Exception:
        # swallow email errors; you can log if needed
        pass

    _log(
        int(admin_id) if admin_id is not None else None,
        user.id,
        "password_reset_sent",
        request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    return jsonify(ok=True, url=reset_url)
