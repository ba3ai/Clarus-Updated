# backend/services/investor_metrics.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from math import isfinite
import re

from backend.extensions import db

# Snapshot models (string investor fields)
try:
    from backend.models_snapshot import InvestorPeriodBalance, InvestorBalance
except Exception:  # pragma: no cover
    InvestorPeriodBalance = None  # type: ignore
    InvestorBalance = None        # type: ignore

EPS = 1e-9

@dataclass
class MonthRow:
    dt: date
    beginning: Optional[float]
    ending: Optional[float]
    contributions: Optional[float] = None  # snapshot typically None
    distributions: Optional[float] = None  # snapshot typically None
    fees: Optional[float] = None

def _as_date(x) -> Optional[date]:
    if not x: return None
    if isinstance(x, date): return x
    if isinstance(x, datetime): return x.date()
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        return None

def _safe_div(num: float, den: float) -> float:
    d = den if isfinite(den) and abs(den) > EPS else EPS
    return num / d

def _month_key(d: date) -> str:
    return f"{d.year}-{str(d.month).zfill(2)}"

def _parse_month_from_text(text: str) -> Optional[date]:
    """Extract a target month like 'June 2025' or '2025-06'."""
    import re, calendar
    t = (text or "").strip()
    # YYYY-MM or YYYY/MM
    m = re.search(r"(20\d{2})[-/](0[1-9]|1[0-2])", t)
    if m:
        y, mm = int(m.group(1)), int(m.group(2))
        return date(y, mm, 1)
    # Month YYYY
    months = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
    m2 = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t)?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
        t, re.IGNORECASE
    )
    if m2:
        mm = months[m2.group(1).lower()]
        y = int(m2.group(2))
        return date(y, mm, 1)
    return None

def load_monthly_series_for_investor(investor_name: str) -> List[MonthRow]:
    """Build ascending monthly series from snapshots (prefer InvestorPeriodBalance)."""
    series: List[MonthRow] = []

    # 1) Preferred: monthly snapshot rows
    try:
        if InvestorPeriodBalance is not None:
            rows = (InvestorPeriodBalance.query
                    .filter(InvestorPeriodBalance.investor.ilike(f"%{investor_name}%"))
                    .order_by(InvestorPeriodBalance.period_date.asc())
                    .all())
            for r in rows:
                dt = _as_date(getattr(r, "period_date", None))
                if not dt: continue
                series.append(MonthRow(
                    dt=dt,
                    # current balance == ending; initial balance == beginning
                    beginning=float(getattr(r, "beginning_balance", None) or 0.0),
                    ending=float(getattr(r, "ending_balance", None) or 0.0),
                    fees=float(getattr(r, "management_fees", None) or 0.0),
                ))
    except Exception:
        pass

    # 2) Fallback: build pseudo rows from InvestorBalance (summary)
    if not series:
        try:
            if InvestorBalance is not None:
                rows = (InvestorBalance.query
                        .filter(InvestorBalance.investor.ilike(f"%{investor_name}%"))
                        .order_by(InvestorBalance.current_date.asc())
                        .all())
                for r in rows:
                    dt = _as_date(getattr(r, "current_date", None))
                    if not dt: continue
                    series.append(MonthRow(
                        dt=dt,
                        # initial_value -> beginning, current_value -> ending
                        beginning=float(getattr(r, "initial_value", None) or 0.0),
                        ending=float(getattr(r, "current_value", None) or 0.0),
                    ))
        except Exception:
            pass

    # Make strictly increasing by month key (keep last if duplicates)
    dedup: Dict[str, MonthRow] = {}
    for row in series:
        dedup[_month_key(row.dt)] = row
    out = list(dedup.values())
    out.sort(key=lambda r: r.dt)
    return out

def _pick_row(series: List[MonthRow], target_month: Optional[date]) -> Optional[MonthRow]:
    if not series: return None
    if not target_month:
        return series[-1]
    key = _month_key(target_month)
    by_key = { _month_key(r.dt): r for r in series }
    if key in by_key:
        return by_key[key]
    # choose the nearest *earlier*, else latest
    earlier = [r for r in series if r.dt <= date(target_month.year, target_month.month, 28)]
    return earlier[-1] if earlier else series[-1]

# ---------- Deterministic metrics ----------
def compute_roi(beg: Optional[float], end: Optional[float],
                contrib: Optional[float]=None, dist: Optional[float]=None) -> Optional[float]:
    if beg is None or end is None: return None
    if contrib is None and dist is None:
        # Simple ROI
        return 100.0 * _safe_div((end - beg), beg)
    # Cashflow-aware ROI
    cf = (contrib or 0.0) - (dist or 0.0)
    denom = beg + (contrib or 0.0) - (dist or 0.0)
    return 100.0 * _safe_div((end - beg - cf), max(EPS, denom))

def compute_moic(beg: Optional[float], end: Optional[float]) -> Optional[float]:
    if beg is None or end is None: return None
    return _safe_div(end, max(EPS, beg))

def _months_between(a: date, b: date) -> float:
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day)/30.0

def compute_irr_approx_from_balances(series: List[MonthRow]) -> Optional[float]:
    """If no cashflows, approximate annualized IRR from first→last balance."""
    if not series: return None
    start, end = series[0], series[-1]
    if start.beginning is None or end.ending is None: return None
    months = max(1.0, _months_between(start.dt, end.dt))
    growth = _safe_div(end.ending, max(EPS, start.beginning))
    try:
        ann = (growth ** (12.0/months)) - 1.0
        return 100.0 * ann
    except Exception:
        return None

def calc_for_message(series: List[MonthRow], user_text: str) -> Dict[str, Any]:
    """Produce ROI/MOIC for a requested month (or latest). IRR is lifetime approx if flows unavailable."""
    target = _parse_month_from_text(user_text)
    row = _pick_row(series, target)
    if not row:
        return {"ok": False, "reason": "no_series"}
    roi = compute_roi(row.beginning, row.ending, row.contributions, row.distributions)
    moic = compute_moic(row.beginning, row.ending)
    irr = compute_irr_approx_from_balances(series)  # lifetime approx
    return {
        "ok": True,
        "period": row.dt.isoformat(),
        "roi_pct": None if roi is None else float(roi),
        "moic": None if moic is None else float(moic),
        "irr_pct": None if irr is None else float(irr),
        "inputs": {
            "beginning_balance": row.beginning,
            "ending_balance": row.ending
        }
    }

# ---------- NEW: direct balance extraction ----------
def _which_balance(text: str) -> str:
    """Return 'ending' (default) or 'beginning' based on the words in text."""
    t = (text or "").lower()
    if re.search(r"\b(ending|current|end)\b", t) and "balance" in t:
        return "ending"
    if re.search(r"\b(beginning|initial|start)\b", t) and "balance" in t:
        return "beginning"
    # If the word 'balance' appears without qualifier, assume ending/current
    if "balance" in t:
        return "ending"
    return "ending"

def balance_for_message(series: List[MonthRow], user_text: str) -> Dict[str, Any]:
    """Return the requested balance (ending/current or beginning/initial) for the target month."""
    target = _parse_month_from_text(user_text)
    row = _pick_row(series, target)
    if not row:
        return {"ok": False, "reason": "no_series"}
    kind = _which_balance(user_text)
    val = row.ending if kind == "ending" else row.beginning
    return {
        "ok": True,
        "kind": kind,                 # 'ending' (== current) or 'beginning' (== initial)
        "period": row.dt.isoformat(), # YYYY-MM-01
        "value": None if val is None else float(val)
    }
