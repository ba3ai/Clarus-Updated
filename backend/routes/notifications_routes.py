# backend/routes/notifications_routes.py
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from backend.extensions import db
from backend.models import Investor, Notification
import os

notifications_bp = Blueprint(
    "notifications",
    __name__,
    url_prefix="/api/notifications",
)


def _me_investor_id():
    """
    Resolve the Investor.id for the currently logged-in user.
    """
    inv = Investor.query.filter_by(
        account_user_id=getattr(current_user, "id", None)
    ).first()
    return inv.id if inv else None


# -------------------------------------------------------------------
# Admin check (from second developer)
# -------------------------------------------------------------------


def _is_admin_user() -> bool:
    # Adapt to your User model shape
    try:
        return (getattr(current_user, "user_type", "") or "").lower() == "admin" or bool(
            getattr(current_user, "is_admin", False)
        )
    except Exception:
        return False


# -------------------------------------------------------------------
# Investor-facing APIs  (used by investor dashboard notification bell)
#   (base + more robust read flags)
# -------------------------------------------------------------------


@notifications_bp.get("/unread-count")
@login_required
def unread_count():
    """
    Get unread notification count for the current investor.
    Response: { "count": <int> }
    """
    inv_id = _me_investor_id()
    if not inv_id:
        return jsonify({"count": 0})

    q = Notification.query.filter(Notification.investor_id == inv_id)

    # Prefer read_at if present, fall back to is_read if that's what the model uses
    if hasattr(Notification, "read_at"):
        q = q.filter(Notification.read_at.is_(None))
    elif hasattr(Notification, "is_read"):
        q = q.filter(Notification.is_read.is_(False))

    cnt = q.count()
    return jsonify({"count": int(cnt)})


@notifications_bp.get("")
@login_required
def list_notifications():
    """
    List recent notifications for the current investor.
    Response: plain list, like:
      [
        { id, title, message, created_at, read_at, kind, link_url },
        ...
      ]
    """
    inv_id = _me_investor_id()
    if not inv_id:
        return jsonify([])

    items = (
        Notification.query.filter(Notification.investor_id == inv_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )

    data = []
    for n in items:
        # Support both legacy `message` and newer `body` field names
        msg = getattr(n, "message", None)
        if msg is None and hasattr(n, "body"):
            msg = n.body

        created = getattr(n, "created_at", None)
        read_at = getattr(n, "read_at", None) if hasattr(n, "read_at") else None

        data.append(
            {
                "id": n.id,
                "title": getattr(n, "title", "") or "",
                "message": msg,
                "link_url": getattr(n, "link_url", None)
                if hasattr(n, "link_url")
                else None,
                "created_at": created.isoformat() if created else None,
                "read_at": read_at.isoformat() if read_at else None,
                "kind": getattr(n, "kind", None),
            }
        )

    return jsonify(data)


@notifications_bp.post("/mark-read")
@login_required
def mark_read():
    """
    Mark one or more notifications as read for the current investor.
    Body: { "ids": [1, 2, 3] }
    """
    inv_id = _me_investor_id()
    if not inv_id:
        return jsonify({"ok": True})

    body = request.get_json(silent=True) or {}
    ids = body.get("ids", [])
    if not ids:
        return jsonify({"ok": True})

    q = Notification.query.filter(
        Notification.investor_id == inv_id,
        Notification.id.in_(ids),
    )

    updates = {}
    if hasattr(Notification, "read_at"):
        updates[Notification.read_at] = db.func.now()
    if hasattr(Notification, "is_read"):
        updates[Notification.is_read] = True

    if not updates:
        return (
            jsonify({"ok": False, "error": "Notification model has no read flag"}),
            500,
        )

    q.update(updates, synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# Admin dependent-request APIs
#   - used for "Dependent account requests" panel in Admin Dashboard
#   (from second developer)
# -------------------------------------------------------------------


@notifications_bp.get("/admin/dependent-requests/unread-count")
@login_required
def admin_dependent_unread_count():
    """
    Count unread dependent-account request notifications for admins.
    Response: { "count": <int> }
    """
    if not _is_admin_user():
        return jsonify({"count": 0}), 403

    q = Notification.query.filter(Notification.kind == "dependent_request")

    if hasattr(Notification, "read_at"):
        q = q.filter(Notification.read_at.is_(None))
    elif hasattr(Notification, "is_read"):
        q = q.filter(Notification.is_read.is_(False))

    cnt = q.count()
    return jsonify({"count": int(cnt)})


@notifications_bp.get("/admin/dependent-requests")
@login_required
def admin_list_dependent_requests():
    """
    List *unread* dependent-account request notifications for admins.
    Response: list of { id, title, message, created_at, read_at, kind }
    """
    if not _is_admin_user():
        return jsonify([]), 403

    q = Notification.query.filter(Notification.kind == "dependent_request")

    # Only show unread, so that "X / Approve / Send invitation" removes them
    if hasattr(Notification, "read_at"):
        q = q.filter(Notification.read_at.is_(None))
    elif hasattr(Notification, "is_read"):
        q = q.filter(Notification.is_read.is_(False))

    items = q.order_by(Notification.created_at.desc()).limit(100).all()

    data = []
    for n in items:
        msg = getattr(n, "message", None)
        if msg is None and hasattr(n, "body"):
            msg = n.body

        created = getattr(n, "created_at", None)
        read_at = getattr(n, "read_at", None) if hasattr(n, "read_at") else None

        data.append(
            {
                "id": n.id,
                "title": getattr(n, "title", "") or "",
                "message": msg,
                "link_url": getattr(n, "link_url", None)
                if hasattr(n, "link_url")
                else None,
                "created_at": created.isoformat() if created else None,
                "read_at": read_at.isoformat() if read_at else None,
                "kind": getattr(n, "kind", None),
            }
        )

    return jsonify(data)


@notifications_bp.post("/admin/dependent-requests/mark-read")
@login_required
def admin_mark_dependent_read():
    """
    Mark one or more dependent-account request notifications as read.
    Body: { "ids": [1, 2, 3] }
    """
    if not _is_admin_user():
        return jsonify({"ok": False}), 403
    body = request.get_json(silent=True) or {}
    ids = body.get("ids", [])
    if not ids:
        return jsonify({"ok": True})

    q = Notification.query.filter(
        Notification.id.in_(ids),
        Notification.kind == "dependent_request",
    )

    updates = {}
    if hasattr(Notification, "read_at"):
        updates[Notification.read_at] = db.func.now()
    if hasattr(Notification, "is_read"):
        updates[Notification.is_read] = True

    if not updates:
        return (
            jsonify({"ok": False, "error": "Notification model has no read flag"}),
            500,
        )

    q.update(updates, synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# Admin group-request APIs
#   - used for "Group account requests" panel in Admin Dashboard
#   - notifications are created with kind="group_request"
#   (from second developer)
# -------------------------------------------------------------------


@notifications_bp.get("/admin/group-requests/unread-count")
@login_required
def admin_group_unread_count():
    """
    Count unread group-account request notifications for admins.
    Response: { "count": <int> }
    """
    if not _is_admin_user():
        return jsonify({"count": 0}), 403

    q = Notification.query.filter(Notification.kind == "group_request")

    if hasattr(Notification, "read_at"):
        q = q.filter(Notification.read_at.is_(None))
    elif hasattr(Notification, "is_read"):
        q = q.filter(Notification.is_read.is_(False))

    cnt = q.count()
    return jsonify({"count": int(cnt)})


@notifications_bp.get("/admin/group-requests")
@login_required
def admin_list_group_requests():
    """
    List *unread* group-account request notifications for admins.

    Response: list of:
      {
        id,
        title,
        message,        # includes who requested + list of people
        link_url,
        created_at,
        read_at,
        kind: "group_request"
      }
    """
    if not _is_admin_user():
        return jsonify([]), 403

    q = Notification.query.filter(Notification.kind == "group_request")

    # Only show unread so that closing / approving / inviting can remove them
    if hasattr(Notification, "read_at"):
        q = q.filter(Notification.read_at.is_(None))
    elif hasattr(Notification, "is_read"):
        q = q.filter(Notification.is_read.is_(False))

    items = q.order_by(Notification.created_at.desc()).limit(100).all()

    data = []
    for n in items:
        msg = getattr(n, "message", None)
        if msg is None and hasattr(n, "body"):
            msg = n.body

        created = getattr(n, "created_at", None)
        read_at = getattr(n, "read_at", None) if hasattr(n, "read_at") else None

        data.append(
            {
                "id": n.id,
                "title": getattr(n, "title", "") or "",
                "message": msg,
                "link_url": getattr(n, "link_url", None)
                if hasattr(n, "link_url")
                else None,
                "created_at": created.isoformat() if created else None,
                "read_at": read_at.isoformat() if read_at else None,
                "kind": getattr(n, "kind", None),
            }
        )

    return jsonify(data)


@notifications_bp.post("/admin/group-requests/mark-read")
@login_required
def admin_mark_group_read():
    """
    Mark one or more group-account request notifications as read.
    Body: { "ids": [1, 2, 3] }

    Call this when:
      - Admin clicks the 'X' icon to close a notification, or
      - After Approve / Send Invitation is completed for all members.
    """
    if not _is_admin_user():
        return jsonify({"ok": False}), 403
    body = request.get_json(silent=True) or {}
    ids = body.get("ids", [])
    if not ids:
        return jsonify({"ok": True})

    q = Notification.query.filter(
        Notification.id.in_(ids),
        Notification.kind == "group_request",
    )

    updates = {}
    if hasattr(Notification, "read_at"):
        updates[Notification.read_at] = db.func.now()
    if hasattr(Notification, "is_read"):
        updates[Notification.is_read] = True

    if not updates:
        return (
            jsonify({"ok": False, "error": "Notification model has no read flag"}),
            500,
        )

    q.update(updates, synchronize_session=False)
    db.session.commit()
    return jsonify({"ok": True})


# -------------------------------------------------------------------
# Simple SMTP test endpoint
#   (kept from YOUR base file: POST and no login_required)
# -------------------------------------------------------------------


@notifications_bp.route("/test-email", methods=["POST"])
def test_email():
    from backend.services.emailer import send_email

    send_email(
        to=os.getenv("ETHEREAL_USER"),
        subject="Test from BA3 AI",
        html="<b>Hello from test-email route</b>",
    )
    return jsonify({"ok": True})
