from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, desc, func
from sqlalchemy.exc import SQLAlchemyError

from backend.extensions import db
from backend.models import (
    Invitation,
    Investor,
    Statement,
    InvestorDeletionRequest,
    User,
    Notification,
)
from backend.utils.emailing import send_invite_email

# Optional snapshot fallback
try:
    from backend.models_snapshot import InvestorPeriodBalance  # type: ignore
except Exception:  # pragma: no cover
    InvestorPeriodBalance = None


invitations_bp = Blueprint("invitations", __name__, url_prefix="/api")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _normalize_investor_type(value: str | None) -> str | None:
    """
    Normalize investor_type so we always use 'Depends' for dependent accounts.

    Accepts legacy values like 'Dependent', 'dependent', 'depends', etc.
    """
    if not value:
        return value
    v = value.strip()
    if not v:
        return None
    if v.lower() in {"dependent", "depends"}:
        return "Depends"
    return v


def _resolve_current_balance(
    investor_id: int | None, investor_name: str | None
) -> tuple[float | None, str, str | None, str | None]:
    """Return the newest received balance for an investor.

    Priority:
      1) Latest Statement row for this investor_id
      2) Latest InvestorPeriodBalance snapshot (if available) matched by name
    Returns: (balance, source, received_at_iso, as_of_iso)
      - source: 'statement' | 'snapshot' | 'none'
    """
    # 1) Latest Statement-based ending balance
    if investor_id:
        st = (
            Statement.query.filter(Statement.investor_id == investor_id)
            .order_by(
                desc(Statement.created_at).nullslast(),
                desc(Statement.period_end).nullslast(),
            )
            .first()
        )
        if st:
            received_at = getattr(st, "created_at", None)
            as_of = getattr(st, "period_end", None)
            val = float(st.ending_balance) if st.ending_balance is not None else None
            return (
                val,
                "statement",
                received_at.isoformat() if received_at else None,
                as_of.isoformat() if as_of else None,
            )

    # 2) Fallback to latest InvestorPeriodBalance snapshot by investor_name
    if investor_name and InvestorPeriodBalance is not None:
        # Match on LOWER(TRIM(name)) == LOWER(TRIM(investor_name)) to be robust
        q = InvestorPeriodBalance.query.filter(
            func.lower(func.trim(InvestorPeriodBalance.name))
            == func.lower(func.trim(investor_name))
        )

        # Prefer created_at if the column exists, otherwise just as_of_date
        if hasattr(InvestorPeriodBalance, "created_at"):
            q = q.order_by(
                desc(InvestorPeriodBalance.created_at).nullslast(),
                desc(InvestorPeriodBalance.as_of_date).nullslast(),
            )
        else:
            q = q.order_by(desc(InvestorPeriodBalance.as_of_date).nullslast())

        row = q.first()
        if row:
            received_at = getattr(row, "created_at", None)
            as_of = getattr(row, "as_of_date", None)
            val = float(row.ending_balance) if row.ending_balance is not None else None
            return (
                val,
                "snapshot",
                received_at.isoformat() if received_at else None,
                as_of.isoformat() if as_of else None,
            )

    return None, "none", None, None


def _serialize_invitation(inv: Invitation) -> dict:
    """
    Serialize an invitation and attach the linked Investor and current balance.

    Also adds dependent-request metadata so the Admin UI knows when to show
    an "Accept" button and who the parent is.
    """
    if hasattr(inv, "to_dict"):
        base = inv.to_dict()
    else:
        base = {
            "id": getattr(inv, "id", None),
            "name": getattr(inv, "name", None),
            "email": getattr(inv, "email", None),
            "status": getattr(inv, "status", None),
            "invited_by": getattr(inv, "invited_by", None),
            "created_at": getattr(inv, "created_at", None),
            "used_at": getattr(inv, "used_at", None),
            # include expiry + token for invite-management UI
            "expires_at": getattr(inv, "expires_at", None),
            "token": getattr(inv, "token", None),
        }

    # Dependent-specific metadata from Invitation
    invited_parent_id = getattr(inv, "invited_parent_investor_id", None)
    base["invited_parent_investor_id"] = invited_parent_id
    base["invited_parent_relationship"] = getattr(
        inv, "invited_parent_relationship", None
    )
    base["invited_investor_type"] = _normalize_investor_type(
        getattr(inv, "invited_investor_type", None)
    )
    base["is_dependent_request"] = bool(invited_parent_id)

    # Attach linked Investor info (if invite already used)
    linked = Investor.query.filter_by(invitation_id=inv.id).first()
    investor_payload = None
    if linked:
        if hasattr(linked, "to_dict"):
            investor_payload = linked.to_dict()
        else:
            investor_payload = {
                "id": getattr(linked, "id", None),
                "name": getattr(linked, "name", None),
                "email": getattr(linked, "email", None),
                "company_name": getattr(linked, "company_name", None),
                "address": getattr(linked, "address", None),
                "contact_phone": getattr(linked, "contact_phone", None),
                "investor_type": getattr(linked, "investor_type", None),
                "parent_investor_id": getattr(linked, "parent_investor_id", None),
                "parent_relationship": getattr(
                    linked, "parent_relationship", None
                ),
            }
        # normalize type inside payload
        investor_payload["investor_type"] = _normalize_investor_type(
            investor_payload.get("investor_type")
        )

    base["investor"] = investor_payload

    # ---- resolve parent for the "Parent" column ----
    parent_pk = None
    if investor_payload and investor_payload.get("parent_investor_id"):
        parent_pk = investor_payload["parent_investor_id"]
    elif invited_parent_id:
        parent_pk = invited_parent_id

    parent_name = None
    if parent_pk:
        parent_obj = Investor.query.get(parent_pk)
        if parent_obj:
            parent_name = parent_obj.name
            parent_pk = parent_obj.id  # ensure it's a proper int

    base["parent_investor_id"] = parent_pk
    base["parent_name"] = parent_name  # drives Parent column in admin table

    # ---- balance info ----
    inv_id = linked.id if linked else None
    inv_name = linked.name if linked else base.get("name")
    current_balance, source, received_at, as_of = _resolve_current_balance(
        inv_id, inv_name
    )

    base["current_balance"] = current_balance
    base["balance_source"] = source
    base["balance_received_at"] = received_at
    base["balance_as_of"] = as_of
    return base


def _deliver_invite(email: str, token: str, name: str | None) -> None:
    """
    Best-effort invite delivery.

    The frontend route that renders the investor invite form is:
        /invite/accept?token=...

    So we must generate links pointing there.
    """
    base = (current_app.config.get("FRONTEND_BASE_URL") or "").rstrip("/")
    if not base:
        base = request.host_url.rstrip("/")

    link = f"{base}/invite/accept?token={token}"

    # Ignore boolean return: don't fail API if email sending fails.
    send_invite_email(email, name, link)


def _get_current_investor() -> Investor | None:
    uid = getattr(current_user, "id", None)
    if not uid:
        return None
    return Investor.query.filter_by(account_user_id=uid).first()


def _resolve_view_as_target(me: Investor):
    """
    For "view as dependent" support:

    X-View-As-Investor: <dependent_id> (header)
    """
    hdr = request.headers.get("X-View-As-Investor", "").strip()
    if not hdr:
        return None
    try:
        child_id = int(hdr)
    except Exception:
        return None

    child = Investor.query.get(child_id)
    if not child:
        return jsonify({"error": "Requested dependent not found"}), 404
    if int(getattr(child, "parent_investor_id", 0) or 0) != int(me.id):
        return jsonify({"error": "Not authorized to view this investor"}), 403
    return child


def _purge_investor_record(inv: Investor):
    """
    Hard-delete an investor safely by:
    - detaching dependents,
    - deleting FK children (e.g., statements),
    - removing invitation / user if not referenced elsewhere.

    NOTE: Deletion-requests referencing this investor are removed by callers
    (approve endpoint and admin delete endpoint) before calling this helper,
    so this function must NOT touch InvestorDeletionRequest to avoid stale
    state when the caller holds a loaded request instance.
    """
    # 1) detach dependents
    for child in list(inv.dependents or []):
        child.parent_investor_id = None

    # 2) delete FK children first (add other child tables here if needed)
    Statement.query.filter_by(investor_id=inv.id).delete(synchronize_session=False)
    # If you later add other FK children (e.g. Contacts / Notes), delete them here too.

    # 3) remember external refs
    invitation_id = inv.invitation_id
    account_user_id = inv.account_user_id

    # 4) delete investor
    db.session.delete(inv)
    db.session.flush()

    # 5) delete invitation (optional soft-cancel if you prefer)
    if invitation_id:
        Invitation.query.filter_by(id=invitation_id).delete(
            synchronize_session=False
        )

    # 6) prune user if unused by any investor
    if account_user_id:
        from backend.models import (
            User as UserModel,
            Investor as InvestorModel,
            DocumentShare,
        )

        other_refs = (
            InvestorModel.query.filter(
                InvestorModel.account_user_id == account_user_id
            ).count()
        )
        if other_refs == 0:
            try:
                DocumentShare.query.filter_by(
                    investor_user_id=account_user_id
                ).delete(synchronize_session=False)
            except Exception:
                pass
            UserModel.query.filter_by(id=account_user_id).delete(
                synchronize_session=False
            )


def _is_admin() -> bool:
    """Lightweight admin check based on user_type / is_admin flag."""
    try:
        return (getattr(current_user, "user_type", "") or "").lower() == "admin" or bool(
            getattr(current_user, "is_admin", False)
        )
    except Exception:
        return False


# ---------------------------------------------------------------------
# Invitation CRUD
# ---------------------------------------------------------------------


@invitations_bp.route("/invitations", methods=["OPTIONS"], strict_slashes=False)
def invitations_options():
    return ("", 204)


@invitations_bp.route(
    "/invitations/<int:invitation_id>", methods=["OPTIONS"], strict_slashes=False
)
def invitations_item_options(invitation_id: int):  # noqa: ARG001
    return ("", 204)


@invitations_bp.route("/invitations/stats", methods=["GET"], strict_slashes=False)
@login_required
def invitations_stats():
    """Return simple counts per status; used for showing 'Pending: N'."""
    q = db.session.query(Invitation.status, func.count(Invitation.id)).group_by(
        Invitation.status
    ).all()
    stats = {"pending": 0, "accepted": 0, "canceled": 0}
    for status, cnt in q:
        if not status:
            continue
        s = status.lower()
        if s in stats:
            stats[s] = int(cnt)
    return jsonify(stats), 200


@invitations_bp.route("/invitations", methods=["GET"], strict_slashes=False)
@login_required
def list_invitations():
    status = (request.args.get("status") or "").strip().lower()
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = min(max(int(request.args.get("per_page", 25) or 25), 1), 200)
    sort = (request.args.get("sort") or "used_at").strip()
    order = (request.args.get("order") or "desc").strip().lower()

    query = Invitation.query
    if status:
        query = query.filter(Invitation.status.ilike(status))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Invitation.name.ilike(like),
                Invitation.email.ilike(like),
                Invitation.invited_by.cast(db.String).ilike(like),
            )
        )

    order_col = Invitation.created_at if sort == "created_at" else Invitation.used_at
    query = query.order_by(
        (
            order_col.asc().nullslast()
            if order == "asc"
            else order_col.desc().nullslast()
        ),
        Invitation.created_at.desc(),
    )

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [_serialize_invitation(inv) for inv in paginated.items]

    # For 'accepted', only show invites that actually created an Investor
    if status == "accepted":
        items = [it for it in items if it.get("investor") and it["investor"].get("id")]

    return (
        jsonify(
            {
                "items": items,
                "page": page,
                "per_page": per_page,
                "total": paginated.total,
                "sort": "created_at"
                if order_col is Invitation.created_at
                else "used_at",
                "order": order,
                "status_filter": status,
                "q": q,
            }
        ),
        200,
    )


@invitations_bp.route("/invitations", methods=["POST"], strict_slashes=False)
@login_required
def create_or_resend_invitation():
    """
    Create or resend an investor invitation.

    Body (base):
      { "name": "...", "email": "...", "user_type": "Investor" }

    Extra for dependent flow:
      {
        "parent_investor_id":  <int>,                  # parent investor who requested
        "parent_relationship": "Trust" (optional),     # default "Trust" if parent_investor_id is given
        "invited_investor_type": "Depends"             # optional override; default "Depends" when parent given
      }

    Behavior:
      - If a pending invitation exists for the email -> refresh token + expiry
        and treat as resend (200, msg="resent")
      - Otherwise create new (201, msg="created")

    The accept endpoint will use invited_investor_type + invited_parent_* fields
    to create the Investor with proper type and parent linkage.
    """
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    user_type = (data.get("user_type") or "Investor").strip()
    invited_by = data.get("invited_by")

    # Dependent-specific inputs (parent + relationship + requested type)
    raw_parent_id = (
        data.get("parent_investor_id")
        or data.get("invited_parent_investor_id")
        or None
    )
    try:
        parent_investor_id = int(raw_parent_id) if raw_parent_id is not None else None
    except Exception:
        parent_investor_id = None

    parent_relationship = (
        (data.get("parent_relationship") or data.get("invited_parent_relationship") or "")
        .strip()
        or None
    )

    # If a parent is provided but no relationship, default to "Trust"
    if parent_investor_id and not parent_relationship:
        parent_relationship = "Trust"

    # If a parent is provided, default investor type to "Depends"
    default_invited_type = "Depends" if parent_investor_id else "IRA"
    invited_investor_type_raw = (
        (data.get("invited_investor_type") or default_invited_type).strip()
    )
    invited_investor_type = _normalize_investor_type(invited_investor_type_raw)

    if not name or not email:
        return jsonify({"msg": "Name and email are required."}), 400

    if invited_by is None:
        invited_by = getattr(current_user, "id", None)

    # Does a PENDING invite already exist?
    existing = Invitation.query.filter(
        func.lower(Invitation.email) == email.lower(),
        Invitation.status == "pending",
    ).first()

    if existing:
        # Treat as RESEND: refresh token and expiry, update name/inviter if provided
        existing.name = name or existing.name
        if invited_by is not None:
            existing.invited_by = invited_by
        existing.token = secrets.token_urlsafe(32)
        existing.expires_at = datetime.utcnow() + timedelta(days=14)

        # Update dependent meta if columns exist
        if hasattr(existing, "invited_investor_type"):
            existing.invited_investor_type = invited_investor_type
        if hasattr(existing, "invited_parent_investor_id"):
            existing.invited_parent_investor_id = parent_investor_id
        if hasattr(existing, "invited_parent_relationship"):
            existing.invited_parent_relationship = parent_relationship

        db.session.commit()

        _deliver_invite(existing.email, existing.token, existing.name)
        out = _serialize_invitation(existing)
        out["user_type"] = user_type
        out["msg"] = "resent"
        return jsonify(out), 200

    # Create NEW invitation
    inv = Invitation(
        email=email,
        name=name,
        token=secrets.token_urlsafe(32),
        status="pending",
        invited_by=invited_by,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=14),
        used_at=None,
    )

    # If your Invitation model has a user_type column, store it as well
    if hasattr(inv, "user_type"):
        inv.user_type = user_type

    # Store dependent metadata if the columns exist
    if hasattr(inv, "invited_investor_type"):
        inv.invited_investor_type = invited_investor_type
    if hasattr(inv, "invited_parent_investor_id"):
        inv.invited_parent_investor_id = parent_investor_id
    if hasattr(inv, "invited_parent_relationship"):
        inv.invited_parent_relationship = parent_relationship

    db.session.add(inv)
    db.session.commit()

    _deliver_invite(inv.email, inv.token, inv.name)
    out = _serialize_invitation(inv)
    out["user_type"] = user_type
    out["msg"] = "created"
    return jsonify(out), 201


@invitations_bp.route(
    "/invitations/<int:invitation_id>", methods=["DELETE"], strict_slashes=False
)
@login_required
def cancel_invitation(invitation_id: int):
    """
    Cancel a PENDING invitation. If already accepted, return 409.
    We do not hard-delete to preserve audit.
    """
    inv = Invitation.query.get(invitation_id)
    if not inv:
        return jsonify({"error": "Invitation not found"}), 404
    status = (inv.status or "").lower()
    if status == "accepted":
        return jsonify({"error": "Invitation already accepted"}), 409
    if status == "canceled":
        # idempotent success
        return jsonify({"ok": True, "status": "canceled"}), 200
    inv.status = "canceled"
    inv.used_at = inv.used_at or datetime.utcnow()  # optional book-keeping
    db.session.commit()
    return jsonify({"ok": True, "status": "canceled"}), 200


# ---------------------------------------------------------------------
# Approve dependent-investor invitation
# ---------------------------------------------------------------------


@invitations_bp.route(
    "/invitations/<int:invitation_id>/approve-dependent",
    methods=["POST"],
    strict_slashes=False,
)
@login_required
def approve_dependent_invitation(invitation_id: int):
    """
    Admin approves a 'dependent investor' (Depends) request.

    * If an Investor already exists with this email:
        - link that investor as Depends of invited_parent_investor_id
        - set investor_type to 'Depends'
        - mark invitation as 'accepted'
    * If no Investor exists yet:
        - ensure token/expiry, send invite email
        - mark invitation status as 'approved'
    """
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403

    inv = Invitation.query.get(invitation_id)
    if not inv:
        return jsonify({"error": "Invitation not found"}), 404

    parent_id = getattr(inv, "invited_parent_investor_id", None)
    if not parent_id:
        return jsonify({"error": "Not a dependent-investor request."}), 400

    if (inv.status or "").lower() not in {"pending", "approved"}:
        return jsonify(
            {"error": f"Cannot approve invitation with status {inv.status}"}
        ), 409

    parent = Investor.query.get(parent_id)
    if not parent:
        return jsonify({"error": "Parent investor not found"}), 404

    # remember on the invitation who the parent is (for safety)
    inv.invited_parent_investor_id = parent.id

    email = (inv.email or "").strip().lower()
    existing = None
    if email:
        existing = Investor.query.filter(
            func.lower(Investor.email) == email.lower()
        ).first()

    # CASE 1: existing investor -> just link as Depends
    if existing:
        existing.parent_investor_id = parent.id
        if hasattr(existing, "parent_relationship"):
            rel = getattr(inv, "invited_parent_relationship", None)
            if rel:
                existing.parent_relationship = rel

        existing.investor_type = _normalize_investor_type("Depends") or "Depends"

        inv.status = "accepted"
        inv.used_at = datetime.utcnow()

    else:
        # CASE 2: no investor yet -> send invite email to create Depends account
        if not inv.token:
            inv.token = secrets.token_urlsafe(32)
        if not inv.expires_at:
            inv.expires_at = datetime.utcnow() + timedelta(days=30)

        # child will be created later via invite_accept route;
        # there we will read invited_parent_investor_id and set parent_investor_id
        inv.status = "approved"
        _deliver_invite(inv.email, inv.token, inv.name)

    # Notify the parent investor (best effort)
    try:
        note = Notification(
            investor_id=parent.id,
            title="Dependent investor request approved",
            body=f"Request for {inv.name} ({inv.email}) has been approved.",
            kind="dependent_request_approved",
        )
        db.session.add(note)
    except Exception:
        pass

    db.session.commit()
    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------
# Investor update / delete
# ---------------------------------------------------------------------


@invitations_bp.route(
    "/investors/<int:investor_id>", methods=["PUT"], strict_slashes=False
)
@login_required
def update_investor(investor_id: int):
    inv = Investor.query.get(investor_id)
    if not inv:
        return jsonify({"error": "Investor not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    investor_type = (data.get("investor_type") or inv.investor_type or "IRA").strip()
    investor_type = _normalize_investor_type(investor_type)
    parent_relationship = (data.get("parent_relationship") or "").strip()

    if name:
        inv.name = name
    if email:
        inv.email = email
    if investor_type:
        inv.investor_type = investor_type

    depends_ids = data.get("depends_on_ids") or []
    parent_id = None
    for i in depends_ids:
        if i is not None:
            parent_id = i
            break
    try:
        if (investor_type or "").lower() == "depends":
            if parent_id is None:
                inv.parent_investor_id = None
                inv.parent_relationship = parent_relationship or None
            else:
                if int(parent_id) == int(inv.id):
                    return (
                        jsonify(
                            {"error": "An investor cannot depend on itself."}
                        ),
                        400,
                    )
                parent = Investor.query.get(parent_id)
                if not parent:
                    return (
                        jsonify(
                            {"error": "Selected parent investor not found."}
                        ),
                        404,
                    )
                inv.parent_investor_id = int(parent.id)
                inv.parent_relationship = (
                    parent_relationship or inv.parent_relationship
                )
        else:
            inv.parent_investor_id = None
            inv.parent_relationship = None

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500

    payload = (
        inv.to_dict()
        if hasattr(inv, "to_dict")
        else {
            "id": inv.id,
            "name": inv.name,
            "email": inv.email,
            "investor_type": inv.investor_type,
            "parent_investor_id": inv.parent_investor_id,
        }
    )
    return jsonify(payload), 200


@invitations_bp.route(
    "/investors/<int:investor_id>", methods=["DELETE"], strict_slashes=False
)
@login_required
def delete_investor(investor_id: int):
    inv = Investor.query.get(investor_id)
    if not inv:
        return jsonify({"error": "Investor not found"}), 404

    try:
        # Remove any deletion-requests referencing this investor to avoid FK errors
        InvestorDeletionRequest.query.filter_by(
            investor_id=inv.id
        ).delete(synchronize_session=False)

        _purge_investor_record(inv)
        db.session.commit()
        return jsonify({"ok": True}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ---------------------------------------------------------------------
# Dependent-aware + "view as" endpoints
# ---------------------------------------------------------------------


@invitations_bp.route("/investor/me", methods=["GET"], strict_slashes=False)
@login_required
def investor_me():
    me = _get_current_investor()
    if not me:
        return jsonify({"error": "No investor profile for this user"}), 404

    va = _resolve_view_as_target(me)
    if isinstance(va, tuple):  # error tuple from helper
        return va
    subject = va or me

    kids = (
        Investor.query.with_entities(
            Investor.id, Investor.name, Investor.email, Investor.investor_type
        )
        .filter(Investor.parent_investor_id == subject.id)
        .order_by(Investor.name.asc())
        .all()
    )
    dependents = [
        {
            "id": k.id,
            "name": k.name,
            "email": k.email,
            "investor_type": _normalize_investor_type(k.investor_type),
        }
        for k in kids
    ]

    return (
        jsonify(
            {
                "id": subject.id,
                "name": subject.name,
                "email": subject.email,
                "investor_type": _normalize_investor_type(subject.investor_type),
                "parent_investor_id": subject.parent_investor_id,
                "dependents": dependents,
            }
        ),
        200,
    )


@invitations_bp.route("/investors/dependents", methods=["GET"], strict_slashes=False)
@login_required
def list_dependents():
    me = _get_current_investor()
    if not me:
        return jsonify([]), 200

    va = _resolve_view_as_target(me)
    if isinstance(va, tuple):
        return va
    if va is not None:
        return jsonify([]), 200

    if (_normalize_investor_type(me.investor_type) or "").lower().startswith(
        "depends"
    ):
        return jsonify([]), 200

    rows = (
        Investor.query.filter(Investor.parent_investor_id == me.id)
        .order_by(Investor.name.asc())
        .all()
    )
    out = []
    for r in rows:
        bal, _, _, _ = _resolve_current_balance(r.id, r.name)
        # include latest deletion-request status for UI
        req = (
            InvestorDeletionRequest.query.filter_by(investor_id=r.id)
            .order_by(InvestorDeletionRequest.created_at.desc())
            .first()
        )
        status = req.status if req else None

        out.append(
            {
                "id": r.id,
                "name": r.name,
                "email": r.email,
                "investor_type": _normalize_investor_type(r.investor_type),
                "parent_investor_id": r.parent_investor_id,
                "parent_relationship": r.parent_relationship,
                "delete_request_status": status,  # drives Dependents tab UI
                "current_balance": bal,
            }
        )
    return jsonify(out), 200


# ---------------------------------------------------------------------
# Deletion Requests (create/list/stats/approve/reject)
# ---------------------------------------------------------------------


@invitations_bp.route("/deletion-requests", methods=["POST"])
@login_required
def create_deletion_request():
    """Child or Parent can request deletion of a child investor account."""
    data = request.get_json(silent=True) or {}
    target_id = int(data.get("investor_id") or 0)
    reason = (data.get("reason") or "").strip()

    me = _get_current_investor()
    if not me:
        return jsonify({"error": "No investor profile for this user"}), 403

    target = Investor.query.get(target_id)
    if not target:
        return jsonify({"error": "Investor not found"}), 404

    # Allow: the child themself OR the child's parent
    is_self = target.id == me.id
    is_parent = int(getattr(target, "parent_investor_id", 0) or 0) == int(me.id)
    if not (is_self or is_parent):
        return jsonify(
            {"error": "Not authorized to request deletion for this investor"}
        ), 403

    # No duplicate pending
    existing = InvestorDeletionRequest.query.filter_by(
        investor_id=target.id, status="pending"
    ).first()
    if existing:
        return jsonify({"ok": True, "id": existing.id, "status": "pending"}), 200

    req = InvestorDeletionRequest(
        investor_id=target.id,
        requested_by_investor_id=me.id,
        status="pending",
        reason=reason or None,
    )
    db.session.add(req)
    db.session.commit()
    return jsonify({"ok": True, "id": req.id, "status": "pending"}), 201


@invitations_bp.route("/deletion-requests/stats", methods=["GET"])
@login_required
def deletion_requests_stats():
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403
    pending = (
        db.session.query(func.count(InvestorDeletionRequest.id))
        .filter(InvestorDeletionRequest.status == "pending")
        .scalar()
        or 0
    )
    return jsonify({"pending": int(pending)}), 200


@invitations_bp.route("/deletion-requests", methods=["GET"])
@login_required
def list_deletion_requests():
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403
    rows = (
        InvestorDeletionRequest.query.order_by(
            InvestorDeletionRequest.created_at.desc()
        ).all()
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "investor_id": r.investor_id,
                "requested_by_investor_id": r.requested_by_investor_id,
                "status": r.status,
                "reason": r.reason,
                "created_at": r.created_at.isoformat(),
                "reviewed_at": r.reviewed_at.isoformat()
                if r.reviewed_at
                else None,
            }
        )
    return jsonify(out), 200


@invitations_bp.route(
    "/deletion-requests/<int:req_id>/approve", methods=["POST"]
)
@login_required
def approve_deletion_request(req_id: int):
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403

    req = InvestorDeletionRequest.query.get(req_id)
    if not req:
        return jsonify({"error": "Request not found"}), 404
    if req.status != "pending":
        return jsonify({"error": f"Request already {req.status}"}), 409

    inv = Investor.query.get(req.investor_id)
    try:
        if inv:
            # IMPORTANT: remove the request FIRST to avoid FK blocking delete
            db.session.delete(req)
            db.session.flush()

            _purge_investor_record(inv)
        else:
            # no investor to purge; just remove request
            db.session.delete(req)

        db.session.commit()
        return jsonify({"ok": True}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Delete failed", "details": str(e)}), 500


@invitations_bp.route(
    "/deletion-requests/<int:req_id>/reject", methods=["POST"]
)
@login_required
def reject_deletion_request(req_id: int):
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403
    req = InvestorDeletionRequest.query.get(req_id)
    if not req:
        return jsonify({"error": "Request not found"}), 404
    if req.status != "pending":
        return jsonify({"error": f"Request already {req.status}"}), 409
    req.status = "rejected"
    req.reviewed_at = datetime.utcnow()
    req.reviewed_by_user_id = getattr(current_user, "id", None)
    db.session.commit()
    return jsonify({"ok": True}), 200
