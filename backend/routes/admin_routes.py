# backend/routes/admin_routes.py (merged with mailbox)
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash
from functools import wraps
from datetime import datetime, timedelta
import secrets
import logging

from functools import wraps
from flask import jsonify
from flask_login import current_user, login_required

from backend.extensions import db
from backend.models import User, Investor, Record, Invitation, AdminMessage

admin_bp = Blueprint("admin", __name__)

# ───────────────────────── Helpers ─────────────────────────

# Optional email sender:
# - If Flask-Mail is configured (current_app.extensions["mail"]), we use it.
# - Otherwise we log the invite link to the server console (dev fallback).
try:
    from flask_mail import Message  # optional
except Exception:  # pragma: no cover
    Message = None


def send_invite_email(email: str, name: str | None, link: str) -> None:
    mail_ext = current_app.extensions.get("mail")
    subject = "You're invited to BA3 AI"
    body = (
        f"Hi {name or ''},\n\n"
        f"You’ve been invited to join BA3 AI.\n\n"
        f"Finish your account setup here:\n{link}\n\n"
        f"This link will expire in 7 days.\n"
    )
    if mail_ext and Message:
        msg = Message(subject=subject, recipients=[email], body=body)
        mail_ext.send(msg)
    else:
        current_app.logger.info("[DEV] Invite link for %s: %s", email, link)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_authenticated", False):
            return jsonify({"msg": "Unauthorized"}), 401
        if getattr(current_user, "user_type", "").lower() != "admin":
            return jsonify({"msg": "Admins only"}), 403
        return fn(*args, **kwargs)

    return wrapper


# ─────────────────────── Invite Flow ───────────────────────

@admin_bp.route("/invite", methods=["POST"])
@login_required
@admin_required
def invite_user():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    user_type = (data.get("user_type") or "investor").strip().lower()

    # NEW
    inv_type = (data.get("investor_type") or "IRA").strip()
    depends_on_id = data.get("depends_on_id")
    parent_relationship = (data.get("parent_relationship") or "").strip()

    ALLOWED_TYPES = {"IRA", "ROTH IRA", "Retirement", "Depends"}
    if inv_type not in ALLOWED_TYPES:
        inv_type = "IRA"

    if not email:
        return jsonify({"msg": "Email is required"}), 400

    if User.query.filter(User.email.ilike(email)).first():
        return jsonify({"msg": "A user with this email already exists"}), 409

    existing = Invitation.query.filter_by(email=email, status="pending").first()
    if existing:
        return jsonify({"msg": "An active invitation already exists"}), 409

    token = secrets.token_urlsafe(32)

    inv = Invitation(
        email=email,
        name=name or None,
        token=token,
        invited_by=getattr(current_user, "id", None),
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=7),
        created_at=datetime.utcnow(),
    )

    if hasattr(Invitation, "user_type"):
        setattr(inv, "user_type", user_type)

    # store type + parent + relationship if columns exist
    if hasattr(Invitation, "invited_investor_type"):
        setattr(inv, "invited_investor_type", inv_type)
    if hasattr(Invitation, "invited_parent_investor_id"):
        parent_id = int(depends_on_id) if (inv_type == "Depends" and depends_on_id) else None
        setattr(inv, "invited_parent_investor_id", parent_id)
    if hasattr(Invitation, "invited_parent_relationship"):
        setattr(inv, "invited_parent_relationship", parent_relationship or None)

    db.session.add(inv)
    db.session.commit()

    frontend = current_app.config.get("FRONTEND_URL", "https://clarus.elpiscapital.com")
    link = f"{frontend}/invite/accept?token={token}"
    try:
        send_invite_email(email, name, link)
    except Exception:
        current_app.logger.exception("Failed to send invite email")

    return jsonify({"msg": "Invitation created", "token": token}), 201


# ───────────────── Existing Endpoints (merged & de-duped) ─────────────────

# ✅ Admin creates a new investor user and their profile
@admin_bp.route("/create-user", methods=["POST"])
@login_required
@admin_required
def create_user():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")
    investor_name = data.get("investor_name")

    if not email or not password or not investor_name:
        return jsonify({"msg": "Email, password, and investor_name are required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "User with this email already exists"}), 409

    hashed_pw = generate_password_hash(password)
    user = User(
        email=email,
        password=hashed_pw,
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name", ""),
        user_type="investor",
    )
    db.session.add(user)
    db.session.commit()

    investor = Investor(name=investor_name, owner_id=user.id)
    db.session.add(investor)
    db.session.commit()

    return jsonify({"msg": f"Investor user '{email}' created."}), 201


# ✅ Add a new investor
@admin_bp.route("/investor", methods=["POST"])
@login_required
@admin_required
def add_investor():
    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"msg": "name is required"}), 400
    investor = Investor(name=data["name"], owner_id=get_jwt_identity())
    db.session.add(investor)
    db.session.commit()
    return jsonify({"msg": "Investor added"}), 201


# ✅ Add a financial record manually
@admin_bp.route("/record", methods=["POST"])
@login_required
@admin_required
def add_record():
    data = request.get_json() or {}
    try:
        record = Record(
            investor_id=data["investor_id"],
            type=data["type"],
            amount=data["amount"],
            source="manual",
        )
    except KeyError as e:
        return jsonify({"msg": f"Missing field: {e}"}), 400

    db.session.add(record)
    db.session.commit()
    return jsonify({"msg": "Record added"}), 201


# ✅ Admin adds user (direct create; separate from invite flow)
@admin_bp.route("/add_user", methods=["POST"])
@login_required
@admin_required
def add_user():
    data = request.get_json() or {}

    required_fields = ["email", "password", "first_name", "last_name", "user_type"]
    if not all(data.get(field) for field in required_fields):
        return jsonify({"msg": "Missing required fields"}), 400

    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"msg": "User with this email already exists"}), 409

    hashed_pw = generate_password_hash(data["password"])

    user = User(
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        password=hashed_pw,
        user_type=data["user_type"],
        organization_name=data.get("organization"),
        bank=data.get("bank"),
        status=data.get("status", "Active"),
        permission=data.get("permission", "Viewer"),
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"msg": f"User '{data['email']}' created successfully."}), 201


# ✅ Get all users
# ✅ Get all users (with optional role + pagination) – used by AllAdmins.jsx
@admin_bp.route("/users", methods=["GET"])
@login_required
@admin_required
def get_all_users():
    """
    Returns JSON in the shape AllAdmins.jsx expects:

        {
          "ok": true,
          "data": [ ...user dicts... ],
          "page": 1,
          "per_page": 50,
          "total": 12,
          "total_pages": 1
        }

    Query params:
      - role=admin        (filter by user_type)
      - page=1            (1-based)
      - per_page=50
    """
    role = (request.args.get("role") or "").strip().lower()
    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=50)

    query = User.query

    if role:
        # AllAdmins.jsx calls this with ?role=admin
        query = query.filter(User.user_type.ilike(role))

    pagination = query.order_by(User.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for user in pagination.items:
        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        items.append(
            {
                "id": user.id,
                "name": full_name or None,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "bank": getattr(user, "bank", None),
                # these two are what you want to see in the table:
                "status": getattr(user, "status", None) or "Active",
                "permission": getattr(user, "permission", None) or "Viewer",
                "user_type": user.user_type,
                "organization": getattr(user, "organization_name", None),
            }
        )

    return jsonify(
        ok=True,
        data=items,
        page=page,
        per_page=per_page,
        total=pagination.total,
        total_pages=pagination.pages or 1,
    ), 200



# ───────────────────── Admin Mailbox (from 2nd developer) ─────────────────────

# These endpoints back the AdminDashboard mailbox:
# - GET  /api/admin/messages/unread-count
# - GET  /api/admin/messages
# - POST /api/admin/messages/<id>/mark-read


@admin_bp.route("/messages/unread-count", methods=["GET"])
@login_required
@admin_required
def admin_messages_unread_count():
    """
    Return count of unread admin mailbox messages.
    """
    count = AdminMessage.query.filter_by(read_at=None).count()
    return jsonify({"count": count}), 200


@admin_bp.route("/messages", methods=["GET"])
@login_required
@admin_required
def admin_messages_list():
    """
    Return all admin mailbox messages, newest first.
    """
    # You can add pagination later if needed.
    msgs = (
        AdminMessage.query.order_by(AdminMessage.created_at.desc())
        .all()
    )
    return jsonify([m.to_dict() for m in msgs]), 200


@admin_bp.route("/messages/<int:message_id>/mark-read", methods=["POST"])
@login_required
@admin_required
def admin_messages_mark_read(message_id: int):
    """
    Mark a specific admin mailbox message as read.
    """
    msg = AdminMessage.query.get(message_id)
    if not msg:
        return jsonify({"msg": "Message not found"}), 404

    if msg.read_at is None:
        msg.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({"msg": "Message marked as read"}), 200



@admin_bp.route("/users/<int:user_id>", methods=["PATCH"])
@login_required
@admin_required
def update_user(user_id: int):
    """
    Update basic admin/user settings (used by GroupInvestorAdmin tab).

    Allows changing:
      - status
      - permission
      - user_type (optional)
    """
    data = request.get_json(silent=True) or {}
    user = User.query.get(user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # Only update if explicitly provided
    if "status" in data:
        user.status = (data.get("status") or "").strip() or None

    if "permission" in data:
        user.permission = (data.get("permission") or "").strip() or None

    if "user_type" in data:
        # you can restrict this further if needed
        new_type = (data.get("user_type") or "").strip()
        if new_type:
            user.user_type = new_type

    db.session.add(user)
    db.session.commit()

    full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()

    return (
        jsonify(
            ok=True,
            user={
                "id": user.id,
                "name": full_name or None,
                "email": user.email,
                "status": getattr(user, "status", None),
                "permission": getattr(user, "permission", None),
                "user_type": user.user_type,
            },
        ),
        200,
    )
