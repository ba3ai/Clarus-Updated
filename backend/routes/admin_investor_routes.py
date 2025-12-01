# backend/routes/admin_investor_routes.py
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func

from backend.extensions import db
from backend.models import User, Investor, InvestorGroupMembership, Notification
import re

# ---------------------------------------------------------------------------
# ADMIN-ONLY INVESTOR / GROUP-ADMIN MANAGEMENT (Admin Panel)
# ---------------------------------------------------------------------------
bp = Blueprint("admin_investors", __name__, url_prefix="/api/admin")


def _is_admin() -> bool:
    """Return True if the current logged-in user is an admin."""
    if not getattr(current_user, "is_authenticated", False):
        return False
    return (current_user.user_type or "").strip().lower() == "admin"


def _user_row(u: User) -> dict:
    return {
        "id": u.id,
        "name": f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
        or u.email,
        "email": u.email,
        "user_type": u.user_type,
        "organization": u.organization_name,
        "status": u.status,
        "permission": u.permission,
    }


def _investor_row(inv: Investor) -> dict:
    return {
        "id": inv.id,
        "name": inv.name or inv.company_name or inv.email,
        "email": inv.email,
        "owner_id": inv.owner_id,
        "account_user_id": inv.account_user_id,
    }


# ---------------------------------------------------------------------------
# 1) List investor USERS (for the "Add Group Investor Admin" dropdown)
#    GET /api/admin/investors
# ---------------------------------------------------------------------------
@bp.get("/investors")
@login_required
def list_investor_users():
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    q = (
        User.query.filter(func.lower(User.user_type).like("%investor%"))
        .order_by(User.first_name, User.last_name)
    )

    users = q.all()
    return jsonify({"ok": True, "investors": [_user_row(u) for u in users]}), 200


# ---------------------------------------------------------------------------
# 2) Promote an investor user to Group Investor Admin
#    POST /api/admin/group-investor-admin
#    body: { "investor_id": <user_id> }
# ---------------------------------------------------------------------------
@bp.post("/group-investor-admin")
@login_required
def create_group_investor_admin():
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    data = request.get_json(silent=True) or {}
    investor_id = data.get("investor_id")

    if not investor_id:
        return jsonify({"ok": False, "message": "investor_id is required"}), 400

    try:
        user_id = int(investor_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "investor_id must be an integer"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"ok": False, "message": "User not found"}), 404

    current_type = (user.user_type or "").strip().lower().replace(" ", "")
    if current_type == "groupadmin":
        return jsonify({"ok": False, "message": "User is already a Group Investor Admin"}), 400

    user.user_type = "group admin"
    db.session.commit()

    return (
        jsonify(
            {
                "ok": True,
                "message": "User promoted to Group Investor Admin",
                "user": _user_row(user),
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# 3) Demote a Group Investor Admin back to investor
#    DELETE /api/admin/group-investor-admin/<user_id>
# ---------------------------------------------------------------------------
@bp.delete("/group-investor-admin/<int:user_id>")
@login_required
def delete_group_investor_admin(user_id: int):
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"ok": False, "message": "User not found"}), 404

    current_type = (user.user_type or "").strip().lower().replace(" ", "")
    if current_type != "groupadmin":
        return jsonify({"ok": False, "message": "User is not a Group Investor Admin"}), 400

    # Demote back to investor and remove memberships where this user is admin
    user.user_type = "investor"
    InvestorGroupMembership.query.filter_by(group_admin_id=user_id).delete()
    db.session.commit()

    return jsonify({"ok": True, "message": "Group Investor Admin removed"}), 200


# ---------------------------------------------------------------------------
# 4) List members (Investors) of a particular group admin (ADMIN view)
#    GET /api/admin/group-admins/<admin_id>/investors
# ---------------------------------------------------------------------------
@bp.get("/group-admins/<int:admin_id>/investors")
@login_required
def list_group_investors(admin_id: int):
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    memberships = (
        InvestorGroupMembership.query.filter_by(group_admin_id=admin_id)
        .join(Investor, InvestorGroupMembership.investor_id == Investor.id)
        .order_by(Investor.name)
        .all()
    )

    rows = []
    for m in memberships:
        inv = m.investor
        if not inv:
            continue
        rows.append(
            {
                "membership_id": m.id,
                "investor_id": inv.id,
                "name": inv.name or inv.company_name or inv.email,
                "email": inv.email,
                "added_at": m.created_at.isoformat() if m.created_at else None,
            }
        )

    return jsonify({"ok": True, "members": rows}), 200


# ---------------------------------------------------------------------------
# 5) List AVAILABLE investors for a given group admin (ADMIN view)
#    GET /api/admin/group-admins/<admin_id>/available-investors
# ---------------------------------------------------------------------------
@bp.get("/group-admins/<int:admin_id>/available-investors")
@login_required
def list_available_investors(admin_id: int):
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    # Subquery: investor_ids already assigned to this admin
    existing_ids_subq = db.session.query(InvestorGroupMembership.investor_id).filter_by(
        group_admin_id=admin_id
    )

    q = Investor.query

    # Exclude investors already in group
    q = q.filter(~Investor.id.in_(existing_ids_subq))

    # Exclude investors whose account_user is a group admin
    q = q.outerjoin(User, Investor.account_user_id == User.id)
    q = q.filter(
        ~(
            (User.id.isnot(None))
            & (func.lower(User.user_type).like("%group%admin%"))
        )
    )

    # Exclude investor that corresponds to this admin's own account (if any)
    q = q.filter(Investor.account_user_id != admin_id)

    q = q.order_by(Investor.name)

    investors = q.all()
    return (
        jsonify({"ok": True, "investors": [_investor_row(inv) for inv in investors]}),
        200,
    )


# ---------------------------------------------------------------------------
# 6) Add investors to a group (multi-select)  (ADMIN view)
#    POST /api/admin/group-admins/<admin_id>/investors
#    body: { "investor_ids": [1,2,3] }
# ---------------------------------------------------------------------------
@bp.post("/group-admins/<int:admin_id>/investors")
@login_required
def add_investors_to_group(admin_id: int):
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    data = request.get_json(silent=True) or {}
    id_list = data.get("investor_ids") or []

    if not isinstance(id_list, list) or not id_list:
        return (
            jsonify(
                {"ok": False, "message": "investor_ids must be a non-empty list"}
            ),
            400,
        )

    added = 0
    for raw_id in id_list:
        try:
            inv_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        inv = db.session.get(Investor, inv_id)
        if not inv:
            continue

        existing = InvestorGroupMembership.query.filter_by(
            group_admin_id=admin_id, investor_id=inv_id
        ).first()
        if existing:
            continue

        m = InvestorGroupMembership(group_admin_id=admin_id, investor_id=inv_id)
        db.session.add(m)
        added += 1

    if added:
        db.session.commit()

    return jsonify({"ok": True, "added": added}), 201


# ---------------------------------------------------------------------------
# 7) Remove an investor from a group (ADMIN view)
#    DELETE /api/admin/group-admins/<admin_id>/investors/<investor_id>
# ---------------------------------------------------------------------------
@bp.delete("/group-admins/<int:admin_id>/investors/<int:investor_id>")
@login_required
def remove_investor_from_group(admin_id: int, investor_id: int):
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    membership = InvestorGroupMembership.query.filter_by(
        group_admin_id=admin_id, investor_id=investor_id
    ).first()

    if not membership:
        return jsonify({"ok": False, "message": "Membership not found"}), 404

    db.session.delete(membership)
    db.session.commit()

    return jsonify({"ok": True, "message": "Investor removed from group"}), 200


# ---------------------------------------------------------------------------
# 9) Approve a group account request (called from Admin Dashboard)
#    POST /api/admin/group-requests/approve
#
# Body example:
# {
#   "notification_id": 42,
#   "parent_investor_id": 5,
#   "existing_investor_ids": [10, 11, 12]
# }
# ---------------------------------------------------------------------------
@bp.post("/group-requests/approve")
@login_required
def approve_group_request():
    if not _is_admin():
        return jsonify({"ok": False, "message": "Admins only"}), 403

    data = request.get_json(silent=True) or {}
    notif_id = data.get("notification_id")
    parent_investor_id = data.get("parent_investor_id")
    # Can still accept a list of investor ids (for future use)
    existing_ids = data.get("existing_investor_ids") or data.get("investor_ids") or []

    if not notif_id:
        return jsonify({"ok": False, "message": "notification_id is required"}), 400

    try:
        notif_id_int = int(notif_id)
    except (TypeError, ValueError):
        return jsonify(
            {"ok": False, "message": "notification_id must be an integer"}
        ), 400

    notif = db.session.get(Notification, notif_id_int)
    if not notif:
        return jsonify({"ok": False, "message": "Notification not found"}), 404

    # If parent_investor_id not explicitly provided, derive from the notification
    if not parent_investor_id:
        parent_investor_id = notif.investor_id

    try:
        parent_investor_id_int = int(parent_investor_id)
    except (TypeError, ValueError):
        return jsonify(
            {"ok": False, "message": "parent_investor_id must be an integer"}
        ), 400

    parent_inv = db.session.get(Investor, parent_investor_id_int)
    if not parent_inv:
        return jsonify({"ok": False, "message": "Parent investor not found"}), 404

    if not parent_inv.account_user_id:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Parent investor is not linked to a user account",
                }
            ),
            400,
        )

    # This is the user who will become the Group Investor Admin
    admin_user = db.session.get(User, parent_inv.account_user_id)
    if not admin_user:
        return jsonify({"ok": False, "message": "Group admin user not found"}), 404

    # Promote to group admin if not already
    ut_raw = (admin_user.user_type or "").strip().lower().replace(" ", "")
    if "groupadmin" not in ut_raw:
        admin_user.user_type = "group admin"
        db.session.add(admin_user)

    # Normalise list of existing investor IDs
    # If a single member_email is provided (from Admin UI),
    # automatically map it to existing Investor rows by email.
    member_email = (data.get("member_email") or "").strip().lower()
    if member_email:
        matches = (
            Investor.query.filter(func.lower(Investor.email) == member_email).all()
        )
        for inv in matches:
            existing_ids.append(inv.id)

    if not isinstance(existing_ids, list):
        existing_ids = [existing_ids]

    added = 0
    for raw in existing_ids:
        try:
            inv_id = int(raw)
        except (TypeError, ValueError):
            continue

        inv = db.session.get(Investor, inv_id)
        if not inv:
            continue

        # Avoid duplicates
        existing = InvestorGroupMembership.query.filter_by(
            group_admin_id=admin_user.id,
            investor_id=inv_id,
        ).first()
        if existing:
            continue

        m = InvestorGroupMembership(
            group_admin_id=admin_user.id,
            investor_id=inv_id,
        )
        db.session.add(m)
        added += 1

    # If we approved a specific member email but nothing was added,
    # let the UI know so the admin understands why.
    if member_email and added == 0:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": (
                        "No existing investor found to attach for this group request. "
                        "You may need to create or invite the investor first."
                    ),
                }
            ),
            404,
        )

    # Mark the notification as read/handled
    notif.is_read = True
    if hasattr(notif, "read_at"):
        notif.read_at = datetime.utcnow()
    db.session.add(notif)

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "group_admin_id": admin_user.id,
            "parent_investor_id": parent_inv.id,
            "added": added,
        }
    ), 200

# 8) GROUP-ADMIN SELF-SERVICE VIEW — list *my* group (for Investor Dashboard)
#    GET /api/group-admin/my-group
# ---------------------------------------------------------------------------

group_bp = Blueprint("group_admin_view", __name__, url_prefix="/api/group-admin")


def _is_group_admin() -> bool:
    if not getattr(current_user, "is_authenticated", False):
        return False
    user_type = (current_user.user_type or "").strip().lower()
    return "group" in user_type and "admin" in user_type


@group_bp.get("/my-group")
@login_required
def my_group():
    """
    Used by the Investor Dashboard ("My Group" tab) and also by the group-level
    overview aggregation. Returns the group investors for the current user.
    """
    if not _is_group_admin():
        return jsonify({"ok": False, "message": "Group Investor Admins only"}), 403

    user_id = int(current_user.id)

    # 1) normal group members
    memberships = (
        InvestorGroupMembership.query.filter_by(group_admin_id=user_id)
        .join(Investor, InvestorGroupMembership.investor_id == Investor.id)
        .order_by(Investor.name)
        .all()
    )

    rows = []
    for m in memberships:
        inv = m.investor
        if not inv:
            continue
        rows.append(
            {
                "investor_id": inv.id,
                "name": inv.name or inv.company_name or inv.email,
                "email": inv.email,
                "is_admin": False,
                "added_at": m.created_at.isoformat() if m.created_at else None,
            }
        )

    # 2) Ensure the group admin themselves is also listed as an "investor"
    admin_investor = Investor.query.filter_by(account_user_id=user_id).first()
    if admin_investor:
        rows.insert(
            0,
            {
                "investor_id": admin_investor.id,
                "name": admin_investor.name
                or admin_investor.company_name
                or admin_investor.email,
                "email": admin_investor.email,
                "is_admin": True,
                "added_at": admin_investor.created_at.isoformat()
                if admin_investor.created_at
                else None,
            },
        )

    return jsonify({"ok": True, "group_admin_id": user_id, "members": rows}), 200




def _is_admin_user():
    # Adapt to your User model shape
    try:
        return (getattr(current_user, "user_type", "") or "").lower() == "admin" or bool(
            getattr(current_user, "is_admin", False)
        )
    except Exception:
        return False


@group_bp.post("/group-requests/approve")
@login_required
def approve_group_request():
    """
    Approve a group account request.

    Body JSON:
      {
        "notification_id": 123,             # required
        "parent_investor_id": 10,           # optional – will default from notification.investor_id
        "existing_investor_ids": [11, 12]   # optional – list of child investor IDs
      }

    Behaviour:
      - Finds the parent Investor (group admin-to-be).
      - Promotes the linked User.user_type to "group admin" if needed.
      - Links any provided / auto-detected investors via InvestorGroupMembership.
      - Marks the notification as read.
    """
    if not _is_admin_user():
        return jsonify({"ok": False}), 403

    from backend.extensions import db
    from backend.models import Investor, InvestorGroupMembership, User, Notification

    data = request.get_json(silent=True) or {}
    notif_id = data.get("notification_id")
    parent_investor_id = data.get("parent_investor_id")
    existing_ids = data.get("existing_investor_ids") or data.get("investor_ids") or []

    if not notif_id:
        return jsonify({"ok": False, "error": "notification_id is required"}), 400

    notif = Notification.query.get(notif_id)
    if not notif or notif.kind != "group_request":
        return jsonify({"ok": False, "error": "Notification not found"}), 404

    # If parent investor not explicitly provided, fall back to notification.investor_id
    if not parent_investor_id:
        parent_investor_id = getattr(notif, "investor_id", None)

    parent_inv = Investor.query.get(parent_investor_id) if parent_investor_id else None
    if not parent_inv:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Parent investor not found for this group request",
                }
            ),
            404,
        )

    admin_user = (
        User.query.get(parent_inv.account_user_id) if parent_inv.account_user_id else None
    )
    if not admin_user:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "No user account attached to parent investor",
                }
            ),
            404,
        )

    # -------- Normalise investor IDs that may come from the UI --------
    if not isinstance(existing_ids, list):
        existing_ids = [existing_ids]

    normalized_ids: list[int] = []
    for raw in existing_ids:
        try:
            iv_id = int(raw)
        except (TypeError, ValueError):
            continue
        if iv_id not in normalized_ids:
            normalized_ids.append(iv_id)

    # -------- NEW: auto-detect existing investors from emails in the message --------
    msg = getattr(notif, "message", "") or ""
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    auto_ids: list[int] = []

    for email in email_pattern.findall(msg):
        email = email.strip()
        if not email:
            continue
        try:
            inv = Investor.query.filter(Investor.email.ilike(email)).first()
        except Exception:
            inv = None
        if inv and inv.id not in normalized_ids and inv.id not in auto_ids:
            auto_ids.append(inv.id)

    child_ids = normalized_ids + auto_ids

    # -------- Promote the parent user to group admin --------
    ut_raw = (admin_user.user_type or "").strip().lower().replace(" ", "")
    if "groupadmin" not in ut_raw:
        admin_user.user_type = "group admin"
        db.session.add(admin_user)

    # -------- Create group membership rows --------
    created_links = []
    for child_id in child_ids:
        existing_link = InvestorGroupMembership.query.filter_by(
            group_admin_id=parent_inv.id,
            investor_id=child_id,
        ).first()
        if existing_link:
            continue

        link = InvestorGroupMembership(
            group_admin_id=parent_inv.id,
            investor_id=child_id,
        )
        db.session.add(link)
        # we only know link.id after commit; but we can still return ids
        created_links.append(
            {
                "group_admin_id": parent_inv.id,
                "investor_id": child_id,
            }
        )

    # -------- Mark notification as read --------
    if hasattr(notif, "read_at"):
        notif.read_at = db.func.now()
    if hasattr(notif, "is_read"):
        notif.is_read = True
    db.session.add(notif)

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "group_admin_investor_id": parent_inv.id,
            "group_admin_user_id": admin_user.id,
            "linked_investor_ids": child_ids,
            "links_created": created_links,
        }
    )
