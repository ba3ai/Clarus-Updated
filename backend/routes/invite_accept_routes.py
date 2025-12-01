# backend/routes/invite_accept_routes.py
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from backend.extensions import db
from backend.models import Invitation, User, Investor

invite_accept_bp = Blueprint("invite_accept", __name__, url_prefix="/admin")


def _safe_getattr(obj, name, default=None):
    """Get attribute if it exists; otherwise return default (never raises)."""
    try:
        return getattr(obj, name)
    except Exception:
        return default


@invite_accept_bp.get("/invite/<token>")
def get_invite(token: str):
    """
    Prefill data for the invitation acceptance screen.
    Also returns any invited type/parent stored on the Invitation so the UI can show it.
    """
    inv = Invitation.query.filter_by(token=token).first()

    # Use Invitation.is_valid() so 'pending' + 'approved' + unexpired links work
    if not inv or not inv.is_valid():
        return jsonify({"msg": "Invalid or expired link"}), 400

    payload = {
        "email": inv.email,
        "name": inv.name,
        "token": inv.token,
        "user_type": _safe_getattr(inv, "user_type", "investor"),
    }

    # Extra information so the form can preselect investor type / parent
    invited_type = _safe_getattr(inv, "invited_investor_type", None)
    invited_parent_id = _safe_getattr(inv, "invited_parent_investor_id", None)
    invited_parent_rel = _safe_getattr(inv, "invited_parent_relationship", None)
    if invited_type:
        payload["invited_investor_type"] = invited_type
    if invited_parent_id:
        payload["invited_parent_investor_id"] = invited_parent_id
    if invited_parent_rel:
        payload["invited_parent_relationship"] = invited_parent_rel

    return jsonify(payload), 200


@invite_accept_bp.post("/invite/<token>")
def accept_invite(token: str):
    """
    Accept an invitation:
      - Create User (login).
      - Create/attach Investor.
      - Apply invited investor_type and invited parent (if any).
      - Store extra personal/contact/address fields when provided.
    """
    inv = Invitation.query.filter_by(token=token).first()

    # Same validation rule as GET: allow valid (pending/approved) and unexpired links
    if not inv or not inv.is_valid():
        return jsonify({"msg": "Invalid or expired link"}), 400

    data = request.get_json(silent=True) or {}

    # ---- Personal information ----
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    full_name = (first_name + " " + last_name).strip() or (inv.name or "").strip()

    birthdate = (data.get("birthdate") or "").strip()
    citizenship = (data.get("citizenship") or "").strip()
    ssn_tax_id = (data.get("ssn") or "").strip()
    emergency_contact = (data.get("emergency_contact") or "").strip()

    # ---- Contact / login ----
    email = (data.get("email") or inv.email or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = (data.get("password") or "").strip()

    # ---- Address ----
    address1 = (data.get("address1") or "").strip()
    address2 = (data.get("address2") or "").strip()
    country = (data.get("country") or "").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "").strip()
    zip_code = (data.get("zip") or "").strip()
    parent_relationship = (data.get("parent_relationship") or "").strip()

    # Basic validation
    if not email or not password or not first_name or not last_name:
        return (
            jsonify({"msg": "First/Last name, email and password are required"}),
            400,
        )

    # Prevent duplicate accounts
    if User.query.filter((User.email == email) | (User.username == email)).first():
        return jsonify({"msg": "An account already exists for this email"}), 409

    # Compose single-line address for current schema
    lines = [address1] if address1 else []
    if address2:
        lines.append(address2)
    locality = ", ".join([p for p in [city, state] if p])
    endline = " ".join([p for p in [locality, zip_code] if p]).strip()
    if country:
        endline = (endline + (", " if endline else "") + country).strip(", ")
    if endline:
        lines.append(endline)
    composed_address = ", ".join(lines)

    # ---- Create User ----
    user = User(
        first_name=first_name or (inv.name or "").strip(),
        last_name=last_name or "",
        email=email,
        username=email,
        password=generate_password_hash(password),
        user_type="investor",
        address=composed_address or None,
        phone=phone or None,
        status="Active",
        permission="Viewer",
    )
    db.session.add(user)
    db.session.flush()  # need user.id below

    # ---- Read invited type/parent from Invitation (if those columns exist) ----
    raw_invited_type = _safe_getattr(inv, "invited_investor_type", None)
    invited_parent_id = _safe_getattr(inv, "invited_parent_investor_id", None)
    invited_parent_rel = _safe_getattr(inv, "invited_parent_relationship", None)

    # If a parent is set but no type, treat this as a Depends invitation (your logic)
    if not raw_invited_type and invited_parent_id:
        raw_invited_type = "Depends"

    invited_type = (raw_invited_type or "IRA").strip()
    effective_relationship = parent_relationship or invited_parent_rel or None

    # ---- Create or fetch Investor (by invitation_id) ----
    investor = Investor.query.filter_by(invitation_id=inv.id).first()
    if not investor:
        investor = Investor(
            name=full_name or email,
            owner_id=_safe_getattr(inv, "invited_by", None) or user.id,
            invitation_id=inv.id,
            investor_type=invited_type,  # apply invited type on creation
        )
        db.session.add(investor)
        db.session.flush()  # ensure investor.id is available for self-FK checks

    # Keep fields up-to-date
    investor.name = full_name or investor.name
    investor.address = composed_address or investor.address
    investor.contact_phone = phone or investor.contact_phone
    investor.email = email
    investor.account_user_id = user.id
    investor.investor_type = invited_type or investor.investor_type

    # ---- Link parent if invited as Depends ----
    # Child holds the FK via investor.parent_investor_id.
    parent_id = None
    try:
        parent_id = int(invited_parent_id) if invited_parent_id is not None else None
    except Exception:
        parent_id = None

    if (investor.investor_type or "").lower() == "depends" and parent_id:
        if parent_id != int(investor.id):
            parent = Investor.query.get(parent_id)
            if parent:
                investor.parent_investor_id = parent.id
                # default relationship "Trust" if nothing provided (your logic)
                investor.parent_relationship = effective_relationship or "Trust"
    else:
        # For non-Depends investors, make sure parent fields are cleared
        if (investor.investor_type or "").lower() != "depends":
            investor.parent_investor_id = None
            investor.parent_relationship = None

    # ---- Persist additional fields on Investor ----
    investor.birthdate = birthdate or investor.birthdate
    investor.citizenship = citizenship or investor.citizenship
    investor.ssn_tax_id = ssn_tax_id or investor.ssn_tax_id
    investor.emergency_contact = emergency_contact or investor.emergency_contact

    investor.address1 = address1 or investor.address1
    investor.address2 = address2 or investor.address2
    investor.country = country or investor.country
    investor.city = city or investor.city
    investor.state = state or investor.state
    investor.zip = zip_code or investor.zip

    # ---- Mark invitation used ----
    inv.status = "accepted"
    inv.used_at = datetime.utcnow()

    db.session.commit()

    # Response (mask SSN)
    return (
        jsonify(
            {
                "msg": "Account created",
                "user_id": user.id,
                "investor": (
                    investor.to_dict()
                    if hasattr(investor, "to_dict")
                    else {
                        "id": investor.id,
                        "name": investor.name,
                        "email": investor.email,
                        "investor_type": investor.investor_type,
                        "parent_investor_id": investor.parent_investor_id,
                    }
                ),
                "received_extras": {
                    "birthdate": birthdate,
                    "citizenship": citizenship,
                    "ssn": "***" if ssn_tax_id else "",
                    "emergency_contact": emergency_contact,
                },
            }
        ),
        201,
    )
