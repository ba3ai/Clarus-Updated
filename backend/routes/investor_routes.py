from __future__ import annotations

from datetime import datetime, timedelta
import secrets
import json

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func

from backend.extensions import db
from backend.models import (
    Record,
    User,
    Investor,
    InvestorGroupMembership,
    Statement,
    InvestorDeletionRequest,
    Notification,
    Invitation,
    GroupInvestorRequest,
    ManualInvestorEntry,
)

import pandas as pd


investor_bp = Blueprint("investor", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _is_investor() -> bool:
    """True if current user is logged in as an investor."""
    if not getattr(current_user, "is_authenticated", False):
        return False
    return (current_user.user_type or "").strip().lower() == "investor"


def _is_group_admin() -> bool:
    """True if current user is logged in as a Group Investor Admin."""
    if not getattr(current_user, "is_authenticated", False):
        return False
    t = (current_user.user_type or "").strip().lower()
    return "group" in t and "admin" in t


def _get_payload() -> dict:
    """
    Read request data in a robust way:

    1. Try JSON (application/json)
    2. Fallback to form data (application/x-www-form-urlencoded, multipart/form-data)
    3. Fallback to raw request.data parsed as JSON
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict) and data:
        return data

    if request.form:
        return request.form.to_dict()

    try:
        if request.data:
            parsed = json.loads(request.data.decode("utf-8"))
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass

    return {}


def _extract_name_email(payload: dict) -> tuple[str, str]:
    """
    Extract investor name + email from a variety of possible keys so that
    small frontend differences don't break the API.
    """
    raw_name = (
        payload.get("investor_name")
        or payload.get("name")
        or payload.get("investorName")
        or ""
    )
    raw_email = (
        payload.get("investor_email")
        or payload.get("email")
        or payload.get("investorEmail")
        or ""
    )
    return str(raw_name).strip(), str(raw_email).strip().lower()


# -------------------------------------------------------------------
# 1) Legacy simple dashboard (per-investor summary)
# -------------------------------------------------------------------


@investor_bp.route("/dashboard", methods=["GET"])
@login_required
def get_dashboard():
    """
    Simple dashboard that aggregates Record rows for the logged-in
    investor User (investment / expense / profit).
    """
    if not _is_investor():
        return jsonify({"msg": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"msg": "User not found"}), 404

    records = Record.query.filter_by(investor_id=user.id).all()
    investment = sum((r.amount or 0) for r in records if r.type == "investment")
    expense = sum((r.amount or 0) for r in records if r.type == "expense")
    profit = sum((r.amount or 0) for r in records if r.type == "profit")
    balance = investment + profit - expense

    return (
        jsonify(
            {
                "investment": investment,
                "expense": expense,
                "profit": profit,
                "balance": balance,
                "investmentStartDate": None,
                "investmentType": None,
                "bankName": user.bank,
                "status": user.status,
            }
        ),
        200,
    )


# -------------------------------------------------------------------
# 2) Group Investor Admin: group members + investments
# -------------------------------------------------------------------


@investor_bp.route("/group/members", methods=["GET"])
@login_required
def group_members():
    """
    Return all Investor records that belong to the current Group Investor Admin.

    Response:
    {
      "group_admin_user_id": <user.id>,
      "investors": [
        { "id": <investor.id>, "name": "...", "email": "...", "is_admin": true|false },
        ...
      ]
    }
    """
    if not _is_group_admin():
        return jsonify({"msg": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # 1) Group admin's own Investor profile(s) (mapped via account_user_id).
    admin_investors = Investor.query.filter_by(account_user_id=user.id).all()

    # 2) Explicit group memberships (other investors in their group).
    memberships = InvestorGroupMembership.query.filter_by(
        group_admin_id=user.id
    ).all()
    member_investors = [m.investor for m in memberships if m.investor is not None]

    # 3) Merge and de-duplicate by investor.id.
    by_id: dict[int, dict] = {}
    for inv in admin_investors:
        by_id[inv.id] = {
            "id": inv.id,
            "name": inv.name,
            "email": inv.email,
            "is_admin": True,
        }

    for inv in member_investors:
        if inv.id in by_id:
            # don't overwrite is_admin=True if already set
            by_id[inv.id].setdefault("is_admin", False)
        else:
            by_id[inv.id] = {
                "id": inv.id,
                "name": inv.name,
                "email": inv.email,
                "is_admin": False,
            }

    return jsonify(
        {
            "group_admin_user_id": user.id,
            "investors": list(by_id.values()),
        }
    )


@investor_bp.route("/group/investments", methods=["GET"])
@login_required
def group_investments():
    """
    Return a flat list of 'investments' (latest Statements) for all
    investors in this Group Admin's group.

    Each row corresponds to one investor + one fund/entity (Statement.entity_name),
    using the latest Statement.period_end per (investor_id, entity_name).

    Response:
    [
      {
        "investment_id": <statement.id>,
        "investor_id": <statement.investor_id>,
        "investor_name": <statement.investor_name>,
        "vehicle_name": <statement.entity_name>,
        "initial_value": <beginning_balance>,
        "current_value": <ending_balance>,
        "distributed": <distributions>,
        "irr": <roi_pct or null>,
        "since": <period_start>,
      },
      ...
    ]
    """
    if not _is_group_admin():
        return jsonify({"msg": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"msg": "User not found"}), 404

    # 1) Resolve all investor IDs in this admin's group.
    admin_investors = Investor.query.filter_by(account_user_id=user.id).all()
    admin_ids = [inv.id for inv in admin_investors]

    memberships = InvestorGroupMembership.query.filter_by(
        group_admin_id=user.id
    ).all()
    member_ids = [m.investor_id for m in memberships]

    investor_ids = sorted({*admin_ids, *member_ids})
    if not investor_ids:
        return jsonify([])

    # 2) Pull all Statements for those investors and keep only the latest row
    #    per (investor_id, entity_name).
    stmts = (
        Statement.query.filter(Statement.investor_id.in_(investor_ids))
        .order_by(Statement.investor_id, Statement.entity_name, Statement.period_end)
        .all()
    )

    latest_by_key: dict[tuple[int, str], Statement] = {}
    for s in stmts:
        key = (s.investor_id, s.entity_name)
        prev = latest_by_key.get(key)
        if prev is None or s.period_end > prev.period_end:
            latest_by_key[key] = s

    rows: list[dict] = []
    for (inv_id, entity_name), s in latest_by_key.items():
        rows.append(
            {
                "investment_id": s.id,
                "investor_id": s.investor_id,
                "investor_name": s.investor_name,
                "vehicle_name": s.entity_name,
                "initial_value": float(s.beginning_balance or 0),
                "current_value": float(s.ending_balance or 0),
                "distributed": float(s.distributions or 0),
                "irr": float(s.roi_pct) if s.roi_pct is not None else None,
                "since": s.period_start.isoformat()
                if s.period_start is not None
                else None,
            }
        )

    return jsonify(rows)


# -------------------------------------------------------------------
# 3) List of all investors (for dropdowns / search)
# -------------------------------------------------------------------


@investor_bp.route("/investors/all", methods=["GET"])
@login_required
def list_all_investors():
    """
    Return a de-duplicated list of investors from multiple sources:
    - Investor table
    - ManualInvestorEntry
    - Users with user_type='investor'
    """
    if not (_is_investor() or _is_group_admin()):
        return jsonify({"error": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"error": "User not found"}), 404

    current_email = (user.email or "").strip().lower()
    combined: dict[str, dict] = {}

    def add_entry(source: str, source_id: int, name: str | None, email: str | None):
        nonlocal combined, current_email
        email_norm = (email or "").strip().lower()

        # Skip the logged-in investor themselves
        if email_norm and email_norm == current_email:
            return

        key = email_norm or f"{source}:{source_id}"
        if key in combined:
            return

        display_name = (name or "").strip()
        if not display_name:
            display_name = email or f"Investor #{source_id}"

        combined[key] = {
            "id": source_id,
            "name": display_name,
            "email": email,
            "source": source,
        }

    # 1) Main Investor table
    investors = Investor.query.order_by(Investor.name).all()
    for inv in investors:
        add_entry(
            "investor",
            inv.id,
            inv.name or inv.company_name,
            inv.email,
        )

    # 2) ManualInvestorEntry (imported list)
    manual_list = ManualInvestorEntry.query.order_by(ManualInvestorEntry.name).all()
    for m in manual_list:
        add_entry("manual_investor_entries", m.id, m.name, m.email)

    # 3) User accounts where user_type == "investor"
    investor_users = (
        User.query.filter(func.lower(User.user_type) == "investor")
        .order_by(User.first_name, User.last_name)
        .all()
    )
    for u in investor_users:
        full_name = f"{u.first_name or ''} {u.last_name or ''}".strip() or None
        add_entry("user", u.id, full_name, u.email)

    return jsonify({"investors": list(combined.values())}), 200


# -------------------------------------------------------------------
# 4) Group Investor request (name + email)
# -------------------------------------------------------------------


# example path – adjust to match your existing blueprint prefix
@investor_bp.route("/group-investor/request", methods=["POST"])
@login_required
def request_group_investor():
    """
    Called from Settings when an investor asks to become a Group Admin.
    Creates a Notification(kind="group_request") visible in the admin
    'Group Requests' tab.
    """
    # Find the investor record for the current user
    inv = Investor.query.filter_by(account_user_id=current_user.id).first()
    if not inv:
        return jsonify({"error": "Investor profile not found for this user."}), 404

    data = request.get_json(silent=True) or {}
    raw_name = (data.get("investor_name") or "").strip()
    raw_email = (data.get("investor_email") or "").strip().lower()

    # Fallback to profile data if the form is left blank
    name = raw_name or inv.name or f"Investor #{inv.id}"
    email = raw_email or inv.email or (getattr(current_user, "email", "") or "")

    # ---------- Build message in the exact format the UI expects ----------
    lines = [
        f"Group account request from {name} ({email}).",
        # Treat the requester as the first 'member' so the admin gets an
        # Approve / Send invite row even if you only collect one name/email.
        f"- {name} <{email}>",
    ]

    body = "\n".join(lines)

    notif = Notification(
        investor_id=inv.id,
        kind="group_request",
        title="Group account request",
        body=body,
    )
    db.session.add(notif)
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "message": "Your request to open a Group Investor account has been sent to the admin.",
        }
    ), 200
# -------------------------------------------------------------------
# 5) Dependent investors: list + "Add Dependent Investor" request
# -------------------------------------------------------------------


@investor_bp.route("/investors/dependents", methods=["GET"])
@login_required
def list_dependents():
    """
    Return all dependent Investor records for the currently logged-in investor.
    """
    if not _is_investor():
        return jsonify({"error": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"error": "User not found"}), 404

    parent = Investor.query.filter_by(account_user_id=user.id).first()
    if not parent:
        # no investor profile => no dependents
        return jsonify([])

    dependents = Investor.query.filter_by(parent_investor_id=parent.id).all()
    if not dependents:
        return jsonify([])

    child_ids = [d.id for d in dependents]

    # Map deletion-request status per child
    del_requests = (
        InvestorDeletionRequest.query.filter(
            InvestorDeletionRequest.investor_id.in_(child_ids)
        ).all()
    )
    del_status_by_child = {dr.investor_id: dr.status for dr in del_requests}

    rows: list[dict] = []
    for child in dependents:
        # Try to recover relationship text from the latest accepted invite, if any
        invite = (
            Invitation.query.filter(
                Invitation.email == child.email,
                Invitation.invited_parent_investor_id == parent.id,
            )
            .order_by(
                Invitation.accepted_at.desc().nullslast(),
                Invitation.created_at.desc(),
            )
            .first()
        )

        relationship = invite.invited_parent_relationship if invite else None

        rows.append(
            {
                "id": child.id,
                "investor_id": child.id,
                "name": child.name,
                "email": child.email,
                "investor_type": child.investor_type,
                "parent_investor_id": child.parent_investor_id,
                "parent_relationship": relationship,
                "delete_request_status": del_status_by_child.get(child.id),
            }
        )

    return jsonify(rows)


@investor_bp.route("/dependents/request", methods=["POST"])
@investor_bp.route("/investors/dependents/request", methods=["POST"])  # alias for newer frontend
@login_required
def request_dependent_investor():
    """
    Create a 'dependent investor' (Depends) request.

    Behaviour:
      * Regular investors and group admins can call this.
      * We record an Invitation with invited_investor_type="Depends" and
        invited_parent_investor_id set to the requesting investor.
      * Admin approval logic (in invitations_routes.approve_dependent_invitation)
        will:
          - If an Investor exists with this email → set investor_type="Depends"
            and parent_investor_id to the parent.
          - If not → send an account-creation invite link to this email.

    This endpoint is **idempotent** per (parent, email):
      - If a pending invitation already exists for the same parent+email,
        we return 200 with a friendly message instead of 400.
    """
    # allow both regular investors AND group admins to initiate
    if not (_is_investor() or _is_group_admin()):
        return jsonify({"error": "Unauthorized"}), 403

    user: User | None = db.session.get(User, int(current_user.id))
    if not user:
        return jsonify({"error": "User not found"}), 404

    # "Parent" is the Investor profile connected to this user
    parent = Investor.query.filter_by(account_user_id=user.id).first()
    if not parent:
        return (
            jsonify({"error": "No investor profile found for this user."}),
            400,
        )

    payload = _get_payload()
    raw_name, raw_email = _extract_name_email(payload)
    relationship = str(payload.get("relationship") or "").strip()

    if not raw_name or not raw_email:
        return (
            jsonify({"error": "Investor name and email are required."}),
            400,
        )

    # Optional lookup: existing investor matching this name+email
    existing_investor = (
        Investor.query.filter(
            func.lower(Investor.email) == raw_email,
            func.lower(Investor.name) == func.lower(raw_name),
        ).first()
    )

    # Avoid self-referencing
    if existing_investor and existing_investor.id == parent.id:
        return jsonify({"error": "You cannot add yourself as a dependent."}), 400

    # Prevent duplicate pending request for same email/parent – but treat as success
    existing_invite = (
        Invitation.query.filter(
            Invitation.email == raw_email,
            Invitation.invited_parent_investor_id == parent.id,
            Invitation.status == "pending",
        ).first()
    )
    if existing_invite:
        return (
            jsonify(
                {
                    "message": "There is already a pending request for this investor.",
                    "invitation_id": existing_invite.id,
                    "existing_investor": bool(existing_investor),
                    "duplicate": True,
                }
            ),
            200,
        )

    # Create invite token (used later when admin approves / investor accepts)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=14)

    invite = Invitation(
        email=raw_email,
        name=raw_name,
        token=token,
        status="pending",
        invited_by=user.id,
        user_type="investor",
        # requested account type for the dependent
        invited_investor_type="Depends",
        # the parent who will own this dependent
        invited_parent_investor_id=parent.id,
        invited_parent_relationship=relationship or None,
        expires_at=expires_at,
    )
    db.session.add(invite)

    # Optional notification for admin UI
    note = Notification(
        investor_id=parent.id,
        kind="dependent_investor_request",
        title="New dependent investor request",
        body=f"Request created for {raw_name} ({raw_email}).",
    )
    db.session.add(note)

    db.session.commit()

    return (
        jsonify(
            {
                "message": "Dependent investor request created. An admin will review it shortly.",
                "invitation_id": invite.id,
                "existing_investor": bool(existing_investor),
                "duplicate": False,
            }
        ),
        201,
    )


# -------------------------------------------------------------------
# 6) Q4 Excel workbook demo (per-investor report)
# -------------------------------------------------------------------

EXCEL_FILE_PATH = (
    "uploads/Elpis_-_CAS_v.08_-_2025_Q1_PCAP_1.xlsm"  # adjust for your env
)
TARGET_SHEET = "bcas_q4_adj"  # adjust to match your sheet/tab name


@investor_bp.route("/dashboard/q4_report", methods=["GET"])
@login_required
def investor_q4_report():
    """
    Example: read a specific Excel sheet and return a small report for
    the logged-in investor based on matching their full name.
    """
    try:
        if not _is_investor():
            return jsonify({"error": "Unauthorized"}), 403

        user: User | None = db.session.get(User, int(current_user.id))
        if not user:
            return jsonify({"error": "User not found"}), 404

        full_name = f"{user.first_name} {user.last_name}".strip().lower()

        # Read the Excel sheet using pandas
        df = pd.read_excel(EXCEL_FILE_PATH, sheet_name=TARGET_SHEET, header=9)

        # Normalize column names
        df.columns = df.columns.str.strip()

        # Normalize "Name Match" column and filter investor row
        df["Name Match"] = df["Name Match"].astype(str).str.strip().str.lower()
        investor_row = df[df["Name Match"] == full_name]

        if investor_row.empty:
            return (
                jsonify(
                    {"error": f"No data found for investor {full_name}"}
                ),
                404,
            )

        row = investor_row.iloc[0]

        report = {
            "Ending Balance": row.get("Ending Balance"),
            "Unrealized Gain/Loss": row.get("Unrealized Gain/Loss"),
            "Management Fee": row.get("Management Fee"),
            "Committed": row.get("Committed"),
        }

        return jsonify(report), 200

    except Exception as e:  # defensive logging
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
