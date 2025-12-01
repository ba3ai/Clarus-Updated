from __future__ import annotations

import os
import time
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import func

from backend.extensions import db
from backend.models_settings import AppSetting
from backend.models import (
    ActivityLog,
    User,
    Investor,
    InvestorDeletionRequest,
    Invitation,
    Notification,
)

# NOTE: in app.py this blueprint is registered WITHOUT extra prefix:
#   app.register_blueprint(settings_bp)
# All routes below therefore expose full `/api/...` paths.
settings_bp = Blueprint("settings_bp", __name__)

ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "svg"}
LOGO_SETTING_KEY = "brand_logo_path"  # absolute path to current logo file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _static_root() -> Path:
    """Absolute static directory Flask serves."""
    static_folder = current_app.static_folder
    return Path(static_folder)


def _static_url_prefix() -> str:
    """URL prefix for static assets, e.g. '/_static' or '/static'."""
    return (current_app.static_url_path or "/_static").rstrip("/")


def _brand_dir() -> Path:
    """Directory inside static/ where we keep branding assets."""
    root = _static_root()
    brand = root / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    return brand


def _public_url_for(abs_path: Path) -> str:
    """Convert absolute static file path -> public URL."""
    root = _static_root()
    rel = abs_path.relative_to(root).as_posix()  # e.g. 'brand/logo.png'
    return f"{_static_url_prefix()}/{rel}"


def _file_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _current_user_obj() -> User | None:
    """Return the fully-loaded current User or None."""
    if not getattr(current_user, "is_authenticated", False):
        return None
    if getattr(current_user, "id", None) is None:
        return None
    return db.session.get(User, int(current_user.id))


def _parent_investor() -> Investor | None:
    """Investor profile tied to currently logged-in user."""
    user = _current_user_obj()
    if not user:
        return None
    return Investor.query.filter_by(account_user_id=user.id).first()


# ---------------------------------------------------------------------------
# Brand logo API
#   GET    /api/settings/logo
#   POST   /api/settings/logo
#   DELETE /api/settings/logo
# ---------------------------------------------------------------------------

@settings_bp.get("/api/settings/logo")
def get_logo():
    abs_path = AppSetting.get(LOGO_SETTING_KEY)
    if not abs_path or not os.path.exists(abs_path):
        return jsonify({"url": None})
    url = _public_url_for(Path(abs_path))
    return jsonify({"url": f"{url}?v={int(time.time())}"})


@settings_bp.post("/api/settings/logo")
def upload_logo():
    if "file" not in request.files:
        return jsonify({"error": "Missing file"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = _file_ext(f.filename)
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    brand_dir = _brand_dir()
    filename = secure_filename(f"statement_logo.{ext}")
    abs_path = brand_dir / filename

    # Remove any previous statement_logo.* files
    for old in brand_dir.glob("statement_logo.*"):
        try:
            old.unlink()
        except OSError:
            pass

    f.save(str(abs_path))
    AppSetting.set(LOGO_SETTING_KEY, str(abs_path))

    url = _public_url_for(abs_path)
    return jsonify({"ok": True, "url": f"{url}?v={int(time.time())}"})


@settings_bp.delete("/api/settings/logo")
def delete_logo():
    abs_path = AppSetting.get(LOGO_SETTING_KEY)
    if abs_path and os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass
    AppSetting.delete(LOGO_SETTING_KEY)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Activity Log API
#   GET /api/settings/activity?page=1&limit=25&role=admin&action=login
#
# Uses your original manual payload shape, but keeps the newer query style.
# ---------------------------------------------------------------------------

@settings_bp.get("/api/settings/activity")
def list_activity():
    # Parse pagination safely
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        limit = min(200, max(1, int(request.args.get("limit", 25))))
    except ValueError:
        limit = 25

    q = ActivityLog.query

    role = request.args.get("role")
    if role:
        q = q.filter(ActivityLog.role == role)

    action = request.args.get("action")
    if action:
        q = q.filter(ActivityLog.action == action)

    q = q.order_by(ActivityLog.created_at.desc())

    items = q.offset((page - 1) * limit).limit(limit).all()
    total = q.order_by(None).count()

    payload = [
        {
            "id": i.id,
            "user_id": i.user_id,
            "name": i.name,
            "role": i.role,
            "action": i.action,
            "ip": i.ip,
            "user_agent": i.user_agent,
            "created_at": i.created_at.isoformat() + "Z",
        }
        for i in items
    ]

    return jsonify({"items": payload, "page": page, "limit": limit, "total": total})


# ---------------------------------------------------------------------------
# Dependent Investors API  (from second developer, merged in)
#
#   GET  /api/investors/dependents
#   POST /api/investors/dependents/request
#
# These are used by:
#   - Investor dependents tab (GET)
#   - Settings "Add Dependent Investor" modal (POST)
# ---------------------------------------------------------------------------

@settings_bp.get("/api/investors/dependents")
@login_required
def get_dependents():
    parent = _parent_investor()
    if not parent:
        # Logged-in user has no investor profile yet
        return jsonify([])

    dependents = Investor.query.filter_by(parent_investor_id=parent.id).all()
    if not dependents:
        return jsonify([])

    child_ids = [d.id for d in dependents]

    # Deletion request status per child
    del_requests = InvestorDeletionRequest.query.filter(
        InvestorDeletionRequest.investor_id.in_(child_ids)
    ).all()
    del_status_by_child = {dr.investor_id: dr.status for dr in del_requests}

    # Relationship: derive from most recent Invitation, if any
    child_emails = [d.email for d in dependents if d.email]
    rel_by_email: dict[str, str] = {}
    if child_emails:
        invites = (
            Invitation.query.filter(
                Invitation.invited_parent_investor_id == parent.id,
                Invitation.email.in_(child_emails),
            )
            .order_by(Invitation.created_at.desc())
            .all()
        )
        for inv in invites:
            if inv.invited_parent_relationship and inv.email not in rel_by_email:
                rel_by_email[inv.email] = inv.invited_parent_relationship

    rows: list[dict] = []
    for child in dependents:
        rows.append(
            {
                "id": child.id,
                "investor_id": child.id,
                "name": child.name,
                "email": child.email,
                "investor_type": child.investor_type,
                "parent_investor_id": child.parent_investor_id,
                "parent_relationship": rel_by_email.get(child.email),
                "delete_request_status": del_status_by_child.get(child.id),
            }
        )

    return jsonify(rows)


@settings_bp.post("/api/investor/dependents/request")
@login_required
def request_dependent():
    """
    Called from the Settings page when the current investor wants to
    register someone as a dependent.
    """
    parent = _parent_investor()
    if not parent:
        return jsonify({"error": "Investor profile not found for this user."}), 404

    payload = request.get_json(silent=True) or {}
    raw_name = (payload.get("name") or "").strip()
    raw_email = (payload.get("email") or "").strip().lower()
    relationship = (payload.get("relationship") or "").strip() or None

    if not raw_name or not raw_email:
        return jsonify({"error": "Investor name and email are required."}), 400

    # Prevent adding yourself
    if parent.email and parent.email.lower() == raw_email:
        return jsonify({"error": "You cannot add yourself as a dependent."}), 400

    # ---- Build human-readable message for admin dashboard ----
    parent_name = parent.name or f"Investor #{parent.id}"
    parent_email = parent.email or getattr(current_user, "email", None) or ""

    lines = [
        f"Dependent account request from {parent_name} ({parent_email}).",
        f"- {raw_name} <{raw_email}>",
    ]
    if relationship:
        lines.append(f"Relationship: {relationship}")

    body = "\n".join(lines)

    # ---- Create a notification that the admin panels can read ----
    notif = Notification(
        investor_id=parent.id,
        kind="dependent_request",
        title="Dependent account request",
        body=body,   # NOTE: your model has `body`, not `message`
    )
    db.session.add(notif)
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "message": "Your request to add a dependent investor has been sent to the admin.",
        }
    ), 200
