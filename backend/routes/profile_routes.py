from __future__ import annotations

import os, uuid
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from backend.extensions import db
from backend.models import User, Investor  # <-- ensure Investor is imported

profile_bp = Blueprint("profile", __name__, url_prefix="/api")


def _json_user(u: User) -> dict:
    return {
        "id": u.id,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "email": u.email,
        "phone": getattr(u, "phone", None),
        "address": getattr(u, "address", None),
        "avatar_url": getattr(u, "avatar_url", None),
    }


def _effective_user_and_investor() -> tuple[User | None, Investor | None]:
    """
    Resolve which User/Investor the request should operate on.

    - Normal login: current_user + their linked Investor (if any).
    - Admin:
        * X-View-As-Investor header (admin UI)
        * or ?investor_id= parameter (fallback)
    - Group Admin:
        * ?investor_id= parameter selects a child investor (My Group view)
    """
    if not getattr(current_user, "is_authenticated", False):
        return None, None

    base_user = User.query.get(int(current_user.id)) if current_user.id else None
    if not base_user:
        return None, None

    user_type_raw = (getattr(current_user, "user_type", "") or "")
    user_type = user_type_raw.lower()
    investor_id_param = request.args.get("investor_id", type=int)

    # ----- Admin: header first, then ?investor_id -----
    if user_type == "admin":
        raw = (request.headers.get("X-View-As-Investor") or "").strip()
        inv_id = None
        if raw:
            try:
                inv_id = int(raw)
            except Exception:
                inv_id = None
        if not inv_id and investor_id_param:
            inv_id = investor_id_param

        if inv_id:
            inv = Investor.query.get(inv_id)
            if inv and inv.account_user_id:
                view_user = User.query.get(int(inv.account_user_id))
                if view_user:
                    return view_user, inv

    # ----- Group Admin: ?investor_id selects a child investor -----
    norm = "".join(ch for ch in user_type_raw.lower() if not ch.isspace())
    if norm.startswith("groupadmin") and investor_id_param:
        inv = Investor.query.get(investor_id_param)
        if inv and inv.account_user_id:
            view_user = User.query.get(int(inv.account_user_id))
            if view_user:
                return view_user, inv

    # Fallback: act on the logged-in user's own investor record
    inv = Investor.query.filter_by(account_user_id=base_user.id).first()
    return base_user, inv


@profile_bp.route("/auth/me", methods=["GET"], strict_slashes=False)
@login_required
def me():
    """
    Return the current (or admin/group-admin 'view-as') user's profile,
    combining User fields + extended Investor fields, including the NEW
    fields: note + bank_*.
    """
    u, inv = _effective_user_and_investor()
    if not u:
        return jsonify({"msg": "User not found"}), 404

    profile = {
        # core (from User)
        "first_name": u.first_name,
        "last_name": u.last_name,
        "email": u.email,
        "phone": getattr(u, "phone", None),

        # extended (from Investor if available)
        "birthdate":         getattr(inv, "birthdate", "") or "",
        "citizenship":       getattr(inv, "citizenship", "") or "",
        "ssn":               getattr(inv, "ssn_tax_id", "") or "",
        "emergency_contact": getattr(inv, "emergency_contact", "") or "",
        "note":              getattr(inv, "note", "") or "",  # NEW: note

        # address (split fields kept on Investor; User.address used as fallback)
        "address1": getattr(inv, "address1", "") or (
            getattr(u, "address", "") or ""
        ),
        "address2": getattr(inv, "address2", "") or "",
        "country":  getattr(inv, "country", "") or "",
        "city":     getattr(inv, "city", "") or "",
        "state":    getattr(inv, "state", "") or "",
        "zip":      getattr(inv, "zip", "") or "",

        # bank information (NEW fields from Investor)
        "bank_name":           getattr(inv, "bank_name", "") or "",
        "bank_account_name":   getattr(inv, "bank_account_name", "") or "",
        "bank_account_number": getattr(inv, "bank_account_number", "") or "",
        "bank_account_type":   getattr(inv, "bank_account_type", "") or "",
        "bank_routing_number": getattr(inv, "bank_routing_number", "") or "",
        "bank_address":        getattr(inv, "bank_address", "") or "",

        "avatar_url": getattr(u, "avatar_url", None),
    }
    return jsonify({"user": _json_user(u), "profile": profile}), 200


@profile_bp.route("/auth/profile", methods=["OPTIONS"], strict_slashes=False)
def _profile_options():
    return ("", 204)


@profile_bp.route("/auth/profile", methods=["PUT"], strict_slashes=False)
@login_required
def update_profile():
    """
    Update the profile for:
    - the logged in user (normal case), or
    - the investor selected via:
        * X-View-As-Investor (admin UI)
        * or ?investor_id= (admin + group-admin from Investor Dashboard)
    Includes the NEW Investor fields: note + bank_*.
    """
    u, inv = _effective_user_and_investor()
    if not u:
        return jsonify({"msg": "User not found"}), 404

    # Ensure an Investor row exists for this user
    if not inv:
        inv = Investor(
            account_user_id=u.id,
            # owner_id merged from second file: if your schema requires it
            owner_id=getattr(u, "id", None),
            name=f"{u.first_name} {u.last_name}".strip() or u.email,
        )
        db.session.add(inv)

    data = request.get_json(silent=True) or {}

    # Update User basics
    u.first_name = data.get("first_name") or u.first_name
    u.last_name = data.get("last_name") or u.last_name
    u.email = data.get("email") or u.email
    if "phone" in data:
        u.phone = data.get("phone")

    # Update Investor extended fields
    inv.birthdate = data.get("birthdate") or inv.birthdate
    inv.citizenship = data.get("citizenship") or inv.citizenship
    inv.ssn_tax_id = data.get("ssn") or inv.ssn_tax_id
    inv.emergency_contact = (
        data.get("emergency_contact") or inv.emergency_contact
    )
    inv.note = data.get("note") or getattr(inv, "note", None)  # NEW: note

    # Address
    inv.address1 = data.get("address1") or inv.address1
    inv.address2 = data.get("address2") or inv.address2
    inv.country = data.get("country") or inv.country
    inv.city = data.get("city") or inv.city
    inv.state = data.get("state") or inv.state
    inv.zip = data.get("zip") or inv.zip

    # Bank Information (NEW fields)
    inv.bank_name = data.get("bank_name") or getattr(inv, "bank_name", None)
    inv.bank_account_name = (
        data.get("bank_account_name") or getattr(inv, "bank_account_name", None)
    )
    inv.bank_account_number = (
        data.get("bank_account_number")
        or getattr(inv, "bank_account_number", None)
    )
    inv.bank_account_type = (
        data.get("bank_account_type") or getattr(inv, "bank_account_type", None)
    )
    inv.bank_routing_number = (
        data.get("bank_routing_number")
        or getattr(inv, "bank_routing_number", None)
    )
    inv.bank_address = (
        data.get("bank_address") or getattr(inv, "bank_address", None)
    )

    # Keep User.address as a simple mirror of address1 for legacy code
    if "address1" in data:
        u.address = data.get("address1") or u.address

    db.session.commit()
    return jsonify({"ok": True}), 200


@profile_bp.route("/auth/profile/avatar", methods=["OPTIONS"], strict_slashes=False)
def _avatar_options():
    return ("", 204)


@profile_bp.route("/auth/profile/avatar", methods=["PUT"], strict_slashes=False)
@login_required
def update_avatar():
    """
    Update/remove avatar for the effective user. This still respects the
    admin/group-admin 'view-as' logic: avatar belongs to the effective User (u),
    not the admin account.
    """
    u, _ = _effective_user_and_investor()
    if not u:
        return jsonify({"msg": "User not found"}), 404

    if request.form.get("remove_avatar") == "1":
        if hasattr(u, "avatar_url"):
            u.avatar_url = None
        db.session.commit()
        return jsonify({"ok": True, "avatar_url": None}), 200

    f = request.files.get("avatar")
    if not f:
        return jsonify({"msg": "No file uploaded"}), 400

    upload_dir = os.path.join(current_app.root_path, "uploads", "avatars")
    os.makedirs(upload_dir, exist_ok=True)

    fname = f"{uuid.uuid4().hex}_{f.filename}"
    path = os.path.join(upload_dir, fname)
    f.save(path)

    public_url = f"/uploads/avatars/{fname}"
    if hasattr(u, "avatar_url"):
        u.avatar_url = public_url

    db.session.commit()
    return jsonify({"ok": True, "avatar_url": public_url}), 200
