# backend/routes/accreditation_routes.py
from flask import Blueprint, request, jsonify
from flask_login import current_user, login_required
from backend.extensions import db
from backend.models import Investor, InvestorAccreditation, User

accreditation_bp = Blueprint("accreditation", __name__)


def _is_group_admin_user(u: User) -> bool:
  """
  Detect "Group Admin" investors. We normalize by
  stripping spaces and lowercasing, so "Group Admin"
  -> "groupadmin".
  """
  user_type = str(getattr(u, "user_type", "") or "")
  norm = "".join(ch for ch in user_type.lower() if not ch.isspace())
  return norm.startswith("groupadmin")


def _resolve_investor_for_request() -> Investor | None:
    """
    Resolve which investor this request is acting on.

    - Admins and Group Admins may target ?investor_id=... (or JSON investor_id).
    - Otherwise, use the logged-in user's own investor.
    """
    # Admin / Group Admin override
    inv_id_raw = request.args.get("investor_id") or (
        request.get_json(silent=True) or {}
    ).get("investor_id")

    if inv_id_raw and getattr(current_user, "is_authenticated", False):
        try:
            inv_id_int = int(inv_id_raw)
        except Exception:
            inv_id_int = None

        if inv_id_int is not None:
            u: User = current_user  # type: ignore
            user_type_raw = str(getattr(u, "user_type", "") or "")
            base = user_type_raw.lower()

            if base == "admin" or _is_group_admin_user(u):
                inv = Investor.query.get(inv_id_int)
                if inv:
                    return inv

    # Not admin/group-admin override or no valid investor_id:
    if not getattr(current_user, "is_authenticated", False):
        return None

    # 1) Preferred link: account_user_id
    inv = Investor.query.filter_by(account_user_id=current_user.id).first()
    if inv:
        return inv

    # 2) Legacy link: owner_id
    inv = Investor.query.filter_by(owner_id=current_user.id).first()
    if inv:
        return inv

    # 3) Soft fallback: match by email if present
    if getattr(current_user, "email", None):
        inv = Investor.query.filter_by(email=current_user.email).first()
        if inv:
            return inv

    return None


# Preflight so the browser will actually send the POST
@accreditation_bp.route("/accreditation", methods=["OPTIONS"], strict_slashes=False)
def _accreditation_options():
    return ("", 204)


@accreditation_bp.route("/accreditation", methods=["GET"], strict_slashes=False)
@login_required
def get_accreditation():
    inv = _resolve_investor_for_request()
    if not inv:
        return jsonify(error="Investor not found"), 404

    row = InvestorAccreditation.query.filter_by(investor_id=inv.id).first()
    if not row:
        # No record yet — return empty but 200 so the UI stays calm
        return jsonify(selection=None, accredited=False), 200

    return jsonify(
        investor_id=inv.id,
        selection=row.selection,
        accredited=bool(row.accredited),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    ), 200


@accreditation_bp.route("/accreditation", methods=["POST"], strict_slashes=False)
@login_required
def set_accreditation():
    inv = _resolve_investor_for_request()
    if not inv:
        return jsonify(error="Investor not found"), 404

    data = request.get_json(silent=True) or {}
    selection = (data.get("selection") or "").strip()
    accredited = bool(data.get("accredited"))

    if not selection:
        return jsonify(error="selection is required"), 400

    row = InvestorAccreditation.query.filter_by(investor_id=inv.id).first()
    if row:
        row.selection = selection
        row.accredited = accredited
    else:
        row = InvestorAccreditation(
            investor_id=inv.id,
            selection=selection,
            accredited=accredited,
        )
        db.session.add(row)

    db.session.commit()
    return jsonify(
        ok=True,
        investor_id=inv.id,
        selection=row.selection,
        accredited=bool(row.accredited),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    ), 200
