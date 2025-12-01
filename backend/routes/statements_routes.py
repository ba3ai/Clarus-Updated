from __future__ import annotations

import os
from datetime import date, datetime
from flask import Blueprint, jsonify, send_file, request, abort
from flask_login import current_user, login_required
from sqlalchemy import func, and_, exists

from backend.extensions import db
from backend.models import Statement, Investor
from backend.models_snapshot import InvestorPeriodBalance
from backend.services.statement_service import (
    quarter_bounds,
    compute_statement_from_period_balances,
    ensure_statement_pdf,
)
from backend.services.auth_utils import get_request_user
from backend.services.notifier import notify_statement_ready

statements_bp = Blueprint("statements", __name__, url_prefix="/api/statements")


# ----------------------------- helpers ----------------------------

def _safe_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _normalize_name(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.split()).lower()


def _parse_iso(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(d).date()
    except Exception:
        return None


def _resolve_investor_from_payload(payload) -> int | None:
    """
    Try to map a 'payload' dict (from token or session) to an Investor.id.
    Returns None for admins (unrestricted) or when no mapping is found.
    """
    if not payload:
        return None

    user_type = (payload.get("user_type") or "").lower()
    if user_type == "admin":
        return None  # admins can see all

    # 1) direct account_user_id link
    uid = _safe_int(payload.get("id"))
    if uid:
        link = Investor.query.filter_by(account_user_id=uid).first()
        if link:
            return int(link.id)

    # 2) explicit investor id in payload (various shapes)
    explicit_id = payload.get("investor_id") or (payload.get("investor") or {}).get("id")
    eid = _safe_int(explicit_id)
    if eid:
        return eid

    # 3) email match
    email = (payload.get("email") or "").strip().lower()
    if email:
        inv = Investor.query.filter(Investor.email.ilike(email)).first()
        if inv:
            return int(inv.id)

    # 4) normalized name match
    candidates = []
    if payload.get("name"):
        candidates.append(payload["name"])
    first = (payload.get("first_name") or "").strip()
    last = (payload.get("last_name") or "").strip()
    if first or last:
        candidates.append(f"{first} {last}")

    for cand in candidates:
        norm = _normalize_name(cand)
        if not norm:
            continue
        inv = Investor.query.filter(
            func.lower(func.trim(Investor.name)) == norm
        ).first()
        if inv:
            return int(inv.id)

    return None


def _current_investor_id() -> int | None:
    """
    Resolve investor id from either the Flask-Login session OR the request token.

    IMPORTANT CHANGE:
    - We now prefer the Flask-Login `current_user` first.
    - Only if that fails do we fall back to the legacy JWT-style payload
      from `get_request_user(request)`.
    This avoids old/stale Authorization headers incorrectly overriding
    the logged-in admin session.
    """
    # 1) Prefer Flask-Login session
    if getattr(current_user, "is_authenticated", False):
        session_payload = {
            "id": getattr(current_user, "id", None),
            "email": getattr(current_user, "email", None),
            "first_name": getattr(current_user, "first_name", None),
            "last_name": getattr(current_user, "last_name", None),
            "user_type": getattr(current_user, "user_type", None),
        }
        inv_id = _resolve_investor_from_payload(session_payload)
        if inv_id is not None:
            return inv_id

    # 2) Fall back to any token in the request (old JWT path)
    ru = get_request_user(request) or {}
    inv_id = _resolve_investor_from_payload(ru)
    return inv_id


def _is_admin() -> bool:
    """
    Determine whether the *current request* is an admin user.

    IMPORTANT CHANGE:
    - Prefer `current_user.user_type` from Flask-Login.
    - Only use `get_request_user(request)` if there is no authenticated session.
    This prevents a stale JWT (e.g. for an investor) from downgrading an
    admin who is logged in via cookie/session.
    """
    if getattr(current_user, "is_authenticated", False):
        return (getattr(current_user, "user_type", "") or "").lower() == "admin"

    ru = get_request_user(request) or {}
    if ru:
        return (ru.get("user_type") or "").lower() == "admin"
    return False


def _is_group_admin() -> bool:
    """
    Determine whether the current request user is a "Group Admin" investor.

    Mirrors the frontend normalization which strips whitespace and lowercases
    the user_type (e.g. "Group Admin" -> "groupadmin").
    """
    # Prefer Flask-Login session, then fall back to any auth payload
    if getattr(current_user, "is_authenticated", False):
        user_type = getattr(current_user, "user_type", "") or ""
    else:
        ru = get_request_user(request) or {}
        user_type = (ru.get("user_type") or "")

    norm = "".join(ch for ch in user_type.lower() if not ch.isspace())
    # accept "groupadmin" and variants like "groupadmininvestor"
    return norm.startswith("groupadmin")


def _view_as_investor_id_from_header() -> int | None:
    """
    For admin users, read the X-View-As-Investor header set
    by the admin dashboard.
    """
    raw = (request.headers.get("X-View-As-Investor") or "").strip()
    return _safe_int(raw)


_NUM_KEYS = [
    "beginning_balance",
    "contributions",
    "distributions",
    "unrealized_gl",
    "incentive_fees",
    "management_fees",
    "operating_expenses",
    "adjustment",
    "net_income_loss",
    "ending_balance",
    "ownership_percent",
    "roi_pct",
]


def _block_from_stmt(stmt: Statement, prefix: str) -> dict:
    """
    Build a numbers dictionary from Statement attributes with the given prefix.
    Example: prefix='current' -> current_beginning_balance, current_contributions, ...
    Unknown/missing attributes are treated as 0.0.
    """
    out: dict[str, float] = {}
    for key in _NUM_KEYS:
        attr = f"{prefix}_{key}"
        val = getattr(stmt, attr, None)
        try:
            out[key] = float(val if val is not None else 0.0)
        except Exception:
            out[key] = 0.0
    return out


def _payload_from_stmt(stmt: Statement) -> dict:
    """
    Serialize a Statement row into the JSON structure expected by the UI.
    """
    return {
        "id": stmt.id,
        "entity": getattr(stmt, "entity_name", "") or "",
        "investor": getattr(stmt, "investor_name", "") or "",
        "period": {
            "start": stmt.period_start.isoformat() if stmt.period_start else None,
            "end": stmt.period_end.isoformat() if stmt.period_end else None,
        },
        "current": _block_from_stmt(stmt, "current"),
        "ytd": _block_from_stmt(stmt, "ytd"),
        "pdfAvailable": bool(getattr(stmt, "pdf_path", None)),
    }


def _enforce_ownership(stmt: Statement) -> None:
    """
    Ensure that non-admin callers only access their own statements.

    Group Admins are treated like admins for statement access so they can
    view statements for investors in their group (the frontend limits which
    investors they can select).
    """
    if _is_admin() or _is_group_admin():
        return

    my_inv_id = _current_investor_id()
    if not my_inv_id:
        abort(403, description="Not allowed")

    if getattr(stmt, "investor_id", None) == my_inv_id:
        return

    # Fallback: match by normalized name
    me = Investor.query.get(my_inv_id)
    me_name = (me.name or "").strip().lower() if me else ""
    stmt_name = (getattr(stmt, "investor_name", "") or "").strip().lower()
    if not me_name or me_name != stmt_name:
        abort(403, description="Not allowed")


def _statement_exists(investor_id: int, start: date, end: date) -> bool:
    """
    Does a statement already exist for this investor + quarter?
    """
    return db.session.query(
        exists().where(
            and_(
                Statement.investor_id == investor_id,
                Statement.period_start == start,
                Statement.period_end == end,
            )
        )
    ).scalar()


def _has_quarter_data(inv: Investor, start: date, end: date) -> bool:
    """
    Does this investor have ANY month-level balance rows in this quarter?

    NOTE: we match on LOWER(TRIM(investor_name)) to be robust to
    whitespace/casing differences between the snapshot table and investors.
    """
    name = inv.name or ""
    if not name:
        return False

    return db.session.query(
        exists().where(
            and_(
                func.lower(func.trim(InvestorPeriodBalance.investor))
                == func.lower(func.trim(name)),
                InvestorPeriodBalance.period_date >= start,
                InvestorPeriodBalance.period_date <= end,
            )
        )
    ).scalar()


# ------------------------------ routes -----------------------------


@statements_bp.get("")
@login_required
def list_statements_no_slash():
    """
    GET /api/statements
    Query params:
      - investor_id: int (optional)
          * Admins: may pass any investor_id (or rely on X-View-As-Investor header).
          * Group Admins: may pass investor_id for a child in their group.
          * Normal investors: ignored if different from their own id.
      - start: ISO date (optional)  -> filters period_end >= start
      - end: ISO date (optional)    -> filters period_start <= end
    """
    user_is_admin = _is_admin()
    user_is_group_admin = _is_group_admin()
    investor_id_param = request.args.get("investor_id", type=int)
    header_investor_id = _view_as_investor_id_from_header() if user_is_admin else None

    if user_is_admin:
        # Admin: if viewing-as a specific investor, force that filter.
        investor_id = header_investor_id or investor_id_param
    else:
        my_inv = _current_investor_id()
        if my_inv:
            # Normal investors cannot spoof investor_id; group admins can
            if investor_id_param and investor_id_param != my_inv:
                if not user_is_group_admin:
                    return jsonify([])  # or abort(403)
                # Group Admin: allow viewing child (frontend restricts which ids it sends)
                investor_id = investor_id_param
            else:
                investor_id = my_inv
        else:
            # couldn’t resolve from auth payload; fall back to the param
            investor_id = investor_id_param
            if not investor_id:
                # still nothing -> nothing to show (don’t leak)
                return jsonify([])

    start = _parse_iso(request.args.get("start"))
    end = _parse_iso(request.args.get("end"))

    q = Statement.query
    if investor_id:
        q = q.filter(Statement.investor_id == investor_id)
    if start:
        q = q.filter(Statement.period_end >= start)
    if end:
        q = q.filter(Statement.period_start <= end)

    rows = q.order_by(Statement.period_end.desc()).all()
    payload = []
    for s in rows:
        payload.append(
            {
                "id": s.id,
                "name": f"Investor Statement {s.period_start}–{s.period_end}",
                "investor": s.investor_name,
                "entity": s.entity_name,
                "dueDate": s.period_end.isoformat() if s.period_end else None,
                "status": "Paid"
                if (getattr(s, "ending_balance", 0) or 0) >= 0
                else "Outstanding",
                "amountDue": float(0),
                "paidDate": None,
                "pdfAvailable": bool(getattr(s, "pdf_path", None)),
            }
        )
    return jsonify(payload)


@statements_bp.get("/")
@login_required
def list_statements_with_slash():
    # Trailing slash variant for convenience/reverse proxy configurations
    return list_statements_no_slash()


@statements_bp.get("/<int:statement_id>")
@login_required
def get_statement_detail(statement_id: int):
    """
    GET /api/statements/<id>
    Returns JSON for the preview drawer.

    Ownership is enforced for non-admin users.

    If stored computed fields are missing or stale, recompute them in-memory
    (and persist the refreshed numbers).
    """
    stmt = Statement.query.get(statement_id)
    if not stmt:
        abort(404, description="Statement not found")

    _enforce_ownership(stmt)

    # If the statement might predate new fields, recompute using the service so
    # the JSON always has values the UI expects.
    need_recompute = False
    for key in (
        "current_beginning_balance",
        "current_ending_balance",
        "ytd_beginning_balance",
        "ytd_ending_balance",
    ):
        if not hasattr(stmt, key):
            need_recompute = True
            break

    if not need_recompute:
        for k in ("current_beginning_balance", "current_ending_balance"):
            if getattr(stmt, k, None) is None:
                need_recompute = True
                break

    if need_recompute:
        inv = Investor.query.get(getattr(stmt, "investor_id", None))
        if inv and stmt.period_start and stmt.period_end:
            stmt = compute_statement_from_period_balances(
                inv,
                stmt.period_start,
                stmt.period_end,
                getattr(stmt, "entity_name", "") or "Elpis Opportunity Fund LP",
            )
            db.session.commit()

    payload = _payload_from_stmt(stmt)
    return jsonify(payload)


@statements_bp.get("/<int:statement_id>/view")
@login_required
def get_statement_view_alias(statement_id: int):
    """
    GET /api/statements/<id>/view
    Convenience alias for the frontend "View" action.
    """
    return get_statement_detail(statement_id)


@statements_bp.delete("/<int:statement_id>")
@login_required
def delete_statement(statement_id: int):
    """
    DELETE /api/statements/<id>
    Removes the statement and (best-effort) deletes the generated PDF file.
    """
    stmt = Statement.query.get(statement_id)
    if not stmt:
        abort(404, description="Statement not found")

    # Only owner or admin may delete
    _enforce_ownership(stmt)

    # Best-effort cleanup of the generated PDF
    try:
        if stmt.pdf_path and os.path.isfile(stmt.pdf_path):
            os.remove(stmt.pdf_path)
    except Exception:
        pass

    db.session.delete(stmt)
    db.session.commit()
    return jsonify({"ok": True})


@statements_bp.post("/generate")
@login_required
def generate_statement():
    """
    POST /api/statements/generate
    Body: { "investor_id": 123, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "entity_name": "..." }
    If start/end are omitted, generates for the current quarter.

    IMPORTANT:
    - Will NOT generate an empty statement (requires month-wise data).
    - Will NOT regenerate if a statement for that quarter already exists.
    """
    data = request.get_json(silent=True) or {}
    investor_id = data.get("investor_id")
    if not investor_id:
        return jsonify(error="investor_id is required"), 400

    inv = Investor.query.get_or_404(investor_id)

    start = _parse_iso(data.get("start"))
    end = _parse_iso(data.get("end"))
    if not (start and end):
        start, end = quarter_bounds(date.today())

    # Do not generate empty statements — require at least one month row in quarter
    if not _has_quarter_data(inv, start, end):
        return (
            jsonify(
                ok=False,
                skipped=True,
                reason="no_source_data_for_quarter",
                period={"start": start.isoformat(), "end": end.isoformat()},
            ),
            409,
        )

    # Never re-generate if it already exists
    if _statement_exists(inv.id, start, end):
        return jsonify(
            ok=True,
            already_exists=True,
            period={"start": start.isoformat(), "end": end.isoformat()},
        )

    entity_name = (data.get("entity_name") or "Elpis Opportunity Fund LP").strip()

    # create/update statement record and its PDF
    stmt = compute_statement_from_period_balances(inv, start, end, entity_name)
    db.session.flush()

    pdf_path = ensure_statement_pdf(stmt)
    stmt.pdf_path = pdf_path

    # notify investor (in-app + email) that the statement is ready
    # fail_silently=False => email failures bubble up so you can see them
    notify_statement_ready(stmt, fail_silently=False)

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "statement_id": stmt.id,
            "pdf": pdf_path,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "investor": {"id": inv.id, "name": inv.name},
        }
    )


@statements_bp.post("/generate-quarter")
@login_required
def generate_all_for_quarter():
    """
    POST /api/statements/generate-quarter
    Body: { "year": 2025, "quarter": 1, "entity_name": "..." }

    Generates statements for ALL investors in that quarter, but:
    - only if they have month-wise balance data in the quarter
    - and only if a Statement DOESN'T already exist for that investor+quarter
    """
    data = request.get_json(silent=True) or {}
    year = int(data.get("year") or date.today().year)
    quarter = int(data.get("quarter") or ((date.today().month - 1) // 3 + 1))

    start_month = 3 * (quarter - 1) + 1
    from calendar import monthrange

    start = date(year, start_month, 1)
    end = date(year, start_month + 2, monthrange(year, start_month + 2)[1])

    entity_name = (data.get("entity_name") or "Elpis Opportunity Fund LP").strip()

    created = []
    skipped = []

    for inv in Investor.query.all():
        # Require quarter data
        if not _has_quarter_data(inv, start, end):
            skipped.append(
                {"investor_id": inv.id, "name": inv.name, "reason": "no_source_data"}
            )
            continue

        # Never re-generate
        if _statement_exists(inv.id, start, end):
            skipped.append(
                {"investor_id": inv.id, "name": inv.name, "reason": "already_exists"}
            )
            continue

        stmt = compute_statement_from_period_balances(inv, start, end, entity_name)
        db.session.flush()

        pdf_path = ensure_statement_pdf(stmt)
        stmt.pdf_path = pdf_path

        # Surface email problems to API caller
        notify_statement_ready(stmt, fail_silently=False)
        created.append(stmt.id)

    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "created_ids": created,
            "skipped": skipped,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
        }
    )


@statements_bp.post("/backfill-missing")
@login_required
def backfill_missing():
    """
    ADMIN: Scan all month-wise balances and create statements for any quarter
    that has data but no Statement row yet. Never re-generates existing rows.
    This is the manual version of what the nightly scheduler does.
    """
    if not _is_admin():
        abort(403)

    entity_name = ((request.json or {}).get("entity_name") or "Elpis Opportunity Fund LP").strip()

    created = []
    examined = 0

    def q_of(d: date) -> int:
        return (d.month - 1) // 3 + 1

    # For each investor, find which quarters they have month data for
    for inv in Investor.query.all():
        if not inv.name:
            continue

        months = (
            db.session.query(InvestorPeriodBalance.period_date)
            .filter(
                func.lower(func.trim(InvestorPeriodBalance.investor))
                == func.lower(func.trim(inv.name))
            )
            .order_by(InvestorPeriodBalance.period_date)
            .all()
        )
        quarters = {(m[0].year, q_of(m[0])) for m in months}

        for (yr, q) in sorted(quarters):
            examined += 1
            start_q, end_q = quarter_bounds(date(yr, 1, 1).replace(month=3 * (q - 1) + 1))

            if _statement_exists(inv.id, start_q, end_q):
                continue

            stmt = compute_statement_from_period_balances(
                inv, start_q, end_q, entity_name
            )
            db.session.flush()
            stmt.pdf_path = ensure_statement_pdf(stmt)

            # Surface email issues here as well (admin endpoint)
            notify_statement_ready(stmt, fail_silently=False)

            created.append(
                {
                    "investor_id": inv.id,
                    "year": yr,
                    "quarter": q,
                    "statement_id": stmt.id,
                }
            )

    db.session.commit()

    return jsonify(
        {"ok": True, "created": created, "examined_quarters": examined}
    )


@statements_bp.get("/<int:statement_id>/pdf")
@login_required
def download_statement_pdf(statement_id: int):
    """
    GET /api/statements/<id>/pdf
    Always returns a PDF (renders one if missing).
    Ownership is enforced for non-admin users.
    Use ?inline=1 to preview in an <iframe>.
    """
    stmt = Statement.query.get_or_404(statement_id)

    _enforce_ownership(stmt)

    if not stmt.pdf_path:
        pdf_path = ensure_statement_pdf(stmt)
        stmt.pdf_path = pdf_path
        db.session.commit()

    filename = (
        f"{stmt.investor_name}_{stmt.period_end}.pdf"
        if stmt.period_end
        else "statement.pdf"
    )

    inline = request.args.get("inline") == "1"
    return send_file(
        stmt.pdf_path, as_attachment=not inline, download_name=filename
    )
