# backend/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date
from calendar import monthrange

from sqlalchemy import func, and_, exists

from .services.statement_service import (
    quarter_bounds,
    compute_statement_from_period_balances,
    ensure_statement_pdf,
)
from .services.notifier import notify_statement_ready
from .models import Investor, Statement
from .models_snapshot import InvestorPeriodBalance
from .extensions import db


def _statement_exists(investor_id: int, start: date, end: date) -> bool:
    return db.session.query(
        exists().where(
            and_(
                Statement.investor_id == investor_id,
                Statement.period_start == start,
                Statement.period_end == end,
            )
        )
    ).scalar()


def _has_quarter_data(inv_name: str, start: date, end: date) -> bool:
    """
    Check if there is at least one month row for this investor name
    in [start, end] inclusive. Uses LOWER(TRIM(column)) for robustness.

    NOTE: Uses the *new* InvestorPeriodBalance schema:
      - name        (was: investor)
      - as_of_date  (was: period_date)
    """
    if not inv_name:
        return False

    return db.session.query(
        exists().where(
            and_(
                func.lower(func.trim(InvestorPeriodBalance.name))
                == func.lower(func.trim(inv_name)),
                InvestorPeriodBalance.as_of_date >= start,
                InvestorPeriodBalance.as_of_date <= end,
            )
        )
    ).scalar()


def generate_statements_for_current_quarter(app):
    """
    Runs on a cron once a quarter (or frequently in dev);
    will SKIP empty quarters for each investor and never re-generate
    an existing statement for the same investor+quarter.
    """
    with app.app_context():
        now = datetime.utcnow()
        year = now.year
        quarter = (now.month - 1) // 3 + 1
        start_month = 3 * (quarter - 1) + 1
        end_month = start_month + 2
        start_date = date(year, start_month, 1)
        end_date = date(year, end_month, monthrange(year, end_month)[1])

        print(f"📦 Auto-generating statements for Q{quarter} {year}...")

        entity_name = "Elpis Opportunity Fund LP"
        created, skipped = [], []

        for inv in Investor.query.all():
            name = inv.name or ""

            # skip investors with no data in this quarter
            if not _has_quarter_data(name, start_date, end_date):
                skipped.append((inv.id, "no_source_data"))
                continue

            # never re-generate existing statements
            if _statement_exists(inv.id, start_date, end_date):
                skipped.append((inv.id, "already_exists"))
                continue

            stmt = compute_statement_from_period_balances(
                investor=inv,
                start=start_date,
                end=end_date,
                entity_name=entity_name,
            )
            stmt.pdf_path = ensure_statement_pdf(stmt)
            try:
                notify_statement_ready(stmt)
            except Exception as e:
                print(f"⚠️ notify failed for investor {inv.id}: {e}")
            created.append(stmt.id)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ commit failed for quarterly statements: {e}")

        print(
            f"✅ Generated {len(created)} statements for Q{quarter} {year} | "
            f"skipped={len(skipped)}"
        )


def backfill_missing_statements_daily(app):
    """
    Nightly job (your daily crawler):
    - Scan month-level balances (InvestorPeriodBalance)
    - For each (investor, quarter) that has data but NO Statement row yet,
      create the statement + PDF + notifications.
    - Never re-generate an already existing quarter.

    Uses the *new* InvestorPeriodBalance schema:
      - name
      - as_of_date
    """
    with app.app_context():
        print("🔎 Backfill: scanning for quarters with data but missing statements...")
        entity_name = "Elpis Opportunity Fund LP"
        created = 0
        examined = 0

        def q_of(d: date) -> int:
            return (d.month - 1) // 3 + 1

        for inv in Investor.query.all():
            if not inv.name:
                continue

            # pull all months where this investor has data
            months = (
                db.session.query(InvestorPeriodBalance.as_of_date)
                .filter(
                    func.lower(func.trim(InvestorPeriodBalance.name))
                    == func.lower(func.trim(inv.name))
                )
                .order_by(InvestorPeriodBalance.as_of_date)
                .all()
            )
            if not months:
                continue

            quarters = {(m[0].year, q_of(m[0])) for m in months}
            for (yr, q) in sorted(quarters):
                examined += 1
                # get quarter start/end using quarter_bounds helper
                qs, qe = quarter_bounds(
                    date(yr, 1, 1).replace(month=3 * (q - 1) + 1)
                )
                if _statement_exists(inv.id, qs, qe):
                    continue

                # We know data exists in this quarter by construction
                stmt = compute_statement_from_period_balances(
                    inv, qs, qe, entity_name
                )
                stmt.pdf_path = ensure_statement_pdf(stmt)
                try:
                    notify_statement_ready(stmt)
                except Exception as e:
                    print(f"⚠️ notify failed for investor {inv.id}: {e}")
                created += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ commit failed in backfill: {e}")

        print(
            f"✅ Backfill done. created={created}, examined_quarters={examined}"
        )


def start_scheduler(app, dev_mode: bool = True):
    scheduler = BackgroundScheduler()
    try:
        scheduler.remove_all_jobs()
    except Exception:
        pass

    if dev_mode:
        # Dev: run an immediate backfill + very frequent jobs for testing
        try:
            backfill_missing_statements_daily(app)
        except Exception as e:
            print(f"⚠️ initial dev backfill failed: {e}")

        scheduler.add_job(
            lambda: generate_statements_for_current_quarter(app),
            trigger="interval",
            minutes=1,
            id="quarterly_statements_dev",
            replace_existing=True,
        )
        scheduler.add_job(
            lambda: backfill_missing_statements_daily(app),
            trigger="interval",
            minutes=1,
            id="backfill_missing_dev",
            replace_existing=True,
        )
        print("⏱️ Dev scheduler: Q-gen every 1m, backfill every 1m.")
    else:
        # Production:
        #  - generate statements on quarter boundaries
        #  - run the backfill crawler once per night
        scheduler.add_job(
            lambda: generate_statements_for_current_quarter(app),
            trigger="cron",
            month="1,4,7,10",
            day=1,
            hour=0,
            minute=0,
            id="quarterly_statements",
            replace_existing=True,
        )
        scheduler.add_job(
            lambda: backfill_missing_statements_daily(app),
            trigger="cron",
            hour=2,
            minute=5,
            id="backfill_missing",
            replace_existing=True,
        )
        print("📅 Scheduler started: quarterly generation + nightly backfill.")

    scheduler.start()


def test_quarterly_generation(app):
    generate_statements_for_current_quarter(app)
