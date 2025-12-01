# backend/routes/portfolio_routes.py
from datetime import date
from flask import Blueprint, request, jsonify

from backend.models import AdminPeriodBalance  # uses the new admin table

portfolio_bp = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")


@portfolio_bp.get("/roi_monthly")
def portfolio_roi_monthly():
    """
    Monthly ELOP ROI series based on AdminPeriodBalance.

    Query params:
      - sheet: optional; only used if AdminPeriodBalance has a `sheet` column
      - start: YYYY-MM-DD (first day you care about)
      - end:   YYYY-MM-DD (last day you care about)
    Response:
      {
        "rows": [
          {
            "date": "2024-02-29",
            "beginning_balance": 12345.0,
            "ending_balance": 13000.0,
            "roi_pct": 5.31,
            "missing": false
          },
          ...
        ]
      }
    """
    start_s = request.args.get("start")
    end_s = request.args.get("end")
    sheet = (request.args.get("sheet") or "").strip()

    if not start_s or not end_s:
        return {"error": "start and end are required (YYYY-MM-DD)"}, 400

    try:
        start_d = date.fromisoformat(start_s)
        end_d = date.fromisoformat(end_s)
    except Exception:
        return {"error": "start/end must be YYYY-MM-DD"}, 400

    if start_d > end_d:
        start_d, end_d = end_d, start_d

    q = AdminPeriodBalance.query

    # If the model has `sheet`, respect the ?sheet= filter so it lines up
    if sheet and hasattr(AdminPeriodBalance, "sheet"):
        q = q.filter(AdminPeriodBalance.sheet == sheet)

    q = (
        q.filter(AdminPeriodBalance.as_of_date >= start_d)
         .filter(AdminPeriodBalance.as_of_date <= end_d)
         .order_by(AdminPeriodBalance.as_of_date.asc())
    )

    rows_db = q.all()
    if not rows_db:
        return jsonify({"rows": []})

    out_rows = []
    prev_end = None

    for r in rows_db:
        orig_beg = r.beginning_balance
        end_v = r.ending_balance
        beg_v = orig_beg
        missing = False

        # If beginning_balance is missing, try to backfill from previous ending
        if (beg_v is None or beg_v == 0) and prev_end not in (None, 0):
            beg_v = prev_end
            # mark as "derived" so the tooltip can show "missing data"
            missing = True

        roi = None
        if beg_v not in (None, 0) and end_v is not None:
            roi = ((float(end_v) - float(beg_v)) / float(beg_v)) * 100.0
        else:
            # can't compute ROI for this month
            missing = True

        out_rows.append(
            {
                "date": r.as_of_date.isoformat(),
                "beginning_balance": float(orig_beg) if orig_beg is not None else None,
                "ending_balance": float(end_v) if end_v is not None else None,
                "roi_pct": float(roi) if roi is not None else None,
                "missing": bool(missing),
            }
        )

        prev_end = end_v

    return jsonify({"rows": out_rows})
