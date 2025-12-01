from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from calendar import monthrange
from typing import Tuple, Optional

from sqlalchemy import func

from backend.extensions import db
from backend.models import Statement, Investor
from backend.models_snapshot import InvestorPeriodBalance
from backend.pdf.statement_renderer import render_investor_statement_pdf

# Try to import an optional AppSetting model for admin-managed settings.
# If it's not present, logo resolution will gracefully fall back to env/static.
try:
    from backend.models_settings import AppSetting  # type: ignore
except Exception:  # pragma: no cover
    AppSetting = None  # type: ignore


# ----------------------------- Quarter helpers ----------------------------- #
def quarter_bounds(d: date) -> Tuple[date, date]:
    """
    Return (start, end) dates for the quarter that contains date d.
    Q1: Jan–Mar, Q2: Apr–Jun, Q3: Jul–Sep, Q4: Oct–Dec.
    """
    q = (d.month - 1) // 3 + 1
    start_month = 3 * (q - 1) + 1
    start = date(d.year, start_month, 1)
    end = date(d.year, start_month + 2, monthrange(d.year, start_month + 2)[1])
    return start, end


# --------------------------- Aggregation helpers --------------------------- #
def _sum_months(investor_name: str, start: date, end: date) -> Optional[dict]:
    """
    Aggregate monthly InvestorPeriodBalance rows within [start, end] inclusive
    for a given investor (by name), using the *new* investor_period_balances schema.

    We match on LOWER(TRIM(name)) == LOWER(TRIM(investor_name)) so that whitespace
    or casing differences don't break the link.

    Field mapping:

      InvestorPeriodBalance.beginning_balance  -> beginning_balance
      InvestorPeriodBalance.ending_balance     -> ending_balance
      InvestorPeriodBalance.gross_profit       -> unrealized_gl
      InvestorPeriodBalance.management_fees    -> management_fees
      InvestorPeriodBalance.operating_expenses -> operating_expenses
      InvestorPeriodBalance.additions          -> contributions
      InvestorPeriodBalance.withdrawals        -> distributions

    Returns a dict:

      beginning_balance, ending_balance, unrealized_gl,
      management_fees, operating_expenses, contributions, distributions
    """
    if not investor_name:
        return None

    rows = (
        db.session.query(InvestorPeriodBalance)
        .filter(
            func.lower(func.trim(InvestorPeriodBalance.name))
            == func.lower(func.trim(investor_name)),
            InvestorPeriodBalance.as_of_date >= start,
            InvestorPeriodBalance.as_of_date <= end,
        )
        .order_by(InvestorPeriodBalance.as_of_date.asc())
        .all()
    )
    if not rows:
        return None

    beg = Decimal(str(rows[0].beginning_balance or 0.0))
    ending = Decimal(str(rows[-1].ending_balance or 0.0))

    unreal = Decimal("0")
    mgmt = Decimal("0")
    opex = Decimal("0")
    contrib = Decimal("0")
    distr = Decimal("0")

    for r in rows:
        unreal += Decimal(str(r.gross_profit or 0.0))
        mgmt += Decimal(str(r.management_fees or 0.0))
        opex += Decimal(str(r.operating_expenses or 0.0))
        contrib += Decimal(str(r.additions or 0.0))
        distr += Decimal(str(r.withdrawals or 0.0))

    # Identity uses: end = beg + (contrib - distr) + (unreal + carry - mgmt - opex + adj)
    # We don't track carry/adj here, so cash_net backs out the known P&L parts:
    cash_net = ending - beg - unreal + mgmt + opex  # noqa: F841 (documentary)

    return {
        "beginning_balance": beg,
        "ending_balance": ending,
        "unrealized_gl": unreal,
        "management_fees": mgmt,
        "operating_expenses": opex,
        "contributions": contrib,
        "distributions": distr,
    }


def compute_statement_from_period_balances(
    investor: Investor,
    start: date,
    end: date,
    entity_name: str,
) -> Statement:
    """
    Build (or refresh) a Statement by aggregating InvestorPeriodBalance rows
    between start and end (inclusive). Also compute ownership_percent at period end.

    IMPORTANT: we clamp extreme percentage values so they fit into NUMERIC(9,6)
    and don't blow up when fund_nav is tiny or data is noisy.
    """
    stmt = (
        Statement.query.filter_by(investor_id=investor.id, period_start=start, period_end=end)
        .first()
    )

    sums = _sum_months(investor.name, start, end) or {
        "beginning_balance": Decimal("0"),
        "ending_balance": Decimal("0"),
        "unrealized_gl": Decimal("0"),
        "management_fees": Decimal("0"),
        "operating_expenses": Decimal("0"),
        "contributions": Decimal("0"),
        "distributions": Decimal("0"),
    }

    beg     = Decimal(sums["beginning_balance"])
    ending  = Decimal(sums["ending_balance"])
    unreal  = Decimal(sums["unrealized_gl"])
    mgmt    = Decimal(sums["management_fees"])
    opex    = Decimal(sums["operating_expenses"])
    contrib = Decimal(sums["contributions"])
    distr   = Decimal(sums["distributions"])

    carry = Decimal("0.00")
    adj   = Decimal("0.00")
    net   = unreal + carry + mgmt + opex + adj

    calc_end = beg + (contrib - distr) + net
    end_bal  = ending if ending != 0 else calc_end

    # --- ROI percentage (protect against tiny beginning balances) ---
    roi: Optional[Decimal]
    if beg:
        raw_roi = (end_bal - beg) / beg * Decimal("100")
        # clamp to something safe for NUMERIC(9,6) to avoid overflow
        if raw_roi < Decimal("-999.999999") or raw_roi > Decimal("999.999999"):
            roi = None
        else:
            roi = raw_roi
    else:
        roi = None

    # --- ownership percent based on fund NAV at period end ---
    from sqlalchemy import func as _func

    fund_nav = db.session.query(
        _func.coalesce(_func.sum(InvestorPeriodBalance.ending_balance), 0.0)
    ).filter(InvestorPeriodBalance.as_of_date == end).scalar() or 0.0

    ownership_pct: Optional[float]
    if fund_nav:
        raw_pct = float(end_bal) / float(fund_nav) * 100.0
        # If this looks insane (|pct| > 1000%), treat it as unknown instead of crashing
        if abs(raw_pct) > 1000.0:
            ownership_pct = None
        else:
            ownership_pct = raw_pct
    else:
        ownership_pct = None

    if stmt is None:
        stmt = Statement(
            investor_id=investor.id,
            investor_name=investor.name,
            entity_name=entity_name,
            period_start=start,
            period_end=end,
            beginning_balance=beg,
            contributions=contrib,
            distributions=distr,
            unrealized_gl=unreal,
            incentive_fees=carry,
            management_fees=mgmt,
            operating_expenses=opex,
            adjustment=adj,
            net_income_loss=net,
            ending_balance=end_bal,
            ownership_percent=ownership_pct,
            roi_pct=roi,
        )
        db.session.add(stmt)
        db.session.flush()
        return stmt

    # Update existing statement in-place
    stmt.investor_name      = investor.name
    stmt.entity_name        = entity_name
    stmt.beginning_balance  = beg
    stmt.contributions      = contrib
    stmt.distributions      = distr
    stmt.unrealized_gl      = unreal
    stmt.incentive_fees     = carry
    stmt.management_fees    = mgmt
    stmt.operating_expenses = opex
    stmt.adjustment         = adj
    stmt.net_income_loss    = net
    stmt.ending_balance     = end_bal
    stmt.ownership_percent  = ownership_pct
    stmt.roi_pct            = roi
    db.session.flush()
    return stmt


def _compute_ytd(investor_name: str, period_end: date) -> dict:
    """
    Year-to-date aggregation: Jan 1 of period_end.year .. period_end.
    Keys match the renderer's expectations.
    """
    start_of_year = date(period_end.year, 1, 1)
    sums = _sum_months(investor_name, start_of_year, period_end) or {
        "beginning_balance": Decimal("0"),
        "ending_balance": Decimal("0"),
        "unrealized_gl": Decimal("0"),
        "management_fees": Decimal("0"),
        "operating_expenses": Decimal("0"),
        "contributions": Decimal("0"),
        "distributions": Decimal("0"),
    }

    net = (
        Decimal(sums["unrealized_gl"])
        + Decimal(sums["management_fees"])
        + Decimal(sums["operating_expenses"])
    )

    return {
        "label_range": f"(Jan. 1, {period_end.year} – {period_end:%b}. {period_end.day}, {period_end.year})",
        "beginning_balance": sums["beginning_balance"],
        "contributions": sums["contributions"],
        "distributions": sums["distributions"],
        "unrealized_gl": sums["unrealized_gl"],
        "incentive_fees": Decimal("0"),
        "management_fees": sums["management_fees"],
        "operating_expenses": sums["operating_expenses"],
        "adjustment": Decimal("0"),
        "net_income_loss": net,
        "ending_balance": sums["ending_balance"],
    }


# ------------------------------ Branding / Logo ----------------------------- #
def _resolve_logo_path() -> str | None:
    """
    Resolve a logo path in this priority:
      1) AppSetting 'brand_logo_path' (admin-uploaded)
      2) ELOP_LOGO_PATH environment variable
      3) backend/static/elpis_logo.png (repo default)
    Returns an absolute filesystem path, or None if not found.
    """
    # 1) DB setting from admin panel (if the model exists)
    if AppSetting is not None:
        try:
            path = AppSetting.get("brand_logo_path")  # type: ignore[attr-defined]
            if path and os.path.exists(path):
                return os.path.abspath(path)
        except Exception:
            pass

    # 2) Environment override
    env_path = os.environ.get("ELOP_LOGO_PATH")
    if env_path and os.path.exists(env_path):
        return os.path.abspath(env_path)

    # 3) Project static fallback
    this_dir = os.path.dirname(__file__)                   # backend/services
    repo_root = os.path.abspath(os.path.join(this_dir, ".."))
    static_path = os.path.join(repo_root, "static", "elpis_logo.png")
    if os.path.exists(static_path):
        return static_path

    return None


# --------------------------------- PDF output -------------------------------- #
def ensure_statement_pdf(stmt: Statement) -> str:
    """
    Render the two-column (Current Period vs YTD) investor statement PDF.
    """
    cur_label = (
        f"({stmt.period_start:%b}. {stmt.period_start.day}, {stmt.period_start.year} – "
        f"{stmt.period_end:%b}. {stmt.period_end.day}, {stmt.period_end.year})"
    )
    ytd = _compute_ytd(stmt.investor_name, stmt.period_end)

    brand = {
        "logo_path": _resolve_logo_path(),
        "entity_address_lines": [
            stmt.entity_name or "Elpis Opportunity Fund LP",
            "7190 E. 106th Street",
            "Fishers, IN 46038",
        ],
    }

    return render_investor_statement_pdf(
        stmt=stmt,
        current_period_label=cur_label,
        ytd=ytd,
        brand=brand,
    )
