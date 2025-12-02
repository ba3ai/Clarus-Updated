from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from backend.models import AdminMessage
from backend.extensions import db

admin_messages_bp = Blueprint(
    "admin_messages",
    __name__,
    url_prefix="/api/admin/messages",
)


def _is_admin() -> bool:
    return (
        getattr(current_user, "is_authenticated", False)
        and str(getattr(current_user, "user_type", "")).lower() == "admin"
    )


@admin_messages_bp.get("")
@login_required
def list_messages():
    """Return latest admin mailbox messages for the admin dashboard."""
    if not _is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    items = (
        AdminMessage.query.order_by(AdminMessage.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify(
        [
            {
                "id": m.id,
                "investor_id": m.investor_id,
                "investor_name": m.investor_name,
                "subject": m.subject,
                "body": m.body,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "read_at": m.read_at.isoformat() if m.read_at else None,
            }
            for m in items
        ]
    )


@admin_messages_bp.get("/unread-count")
@login_required
def unread_count():
    """Return the count of unread mailbox messages."""
    if not _is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    count = AdminMessage.query.filter(AdminMessage.read_at.is_(None)).count()
    return jsonify({"count": int(count)})


@admin_messages_bp.post("/<int:msg_id>/mark-read")
@login_required
def mark_read(msg_id: int):
    """Mark a single mailbox message as read."""
    if not _is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    m = AdminMessage.query.get(msg_id)
    if not m:
        return jsonify({"error": "Message not found"}), 404

    if m.read_at is None:
        m.read_at = db.func.now()
        db.session.commit()

    return jsonify(
        {
            "ok": True,
            "id": m.id,
            "read_at": m.read_at.isoformat() if m.read_at else None,
        }
    )
