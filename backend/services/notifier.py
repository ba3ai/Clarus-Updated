from __future__ import annotations

import logging
from typing import Optional

from backend.extensions import db
from backend.models import Notification, Investor, User
from backend.services.emailer import send_email

log = logging.getLogger(__name__)


def _create_notification(
    *,
    user_id: Optional[int] = None,
    investor_id: Optional[int] = None,
    type_: str,
    title: str,
    body: str,
    link_url: Optional[str] = None,
) -> Notification:
    """
    Low-level helper to create a Notification row.

    NOTE: The Notification model uses fields:
      - kind      (string, what we called "type_")
      - title     (string)
      - message   (string, our "body")
      - link_url  (optional URL for the UI to deep-link somewhere)

    We only add/flush here; the caller is responsible for committing.
    """
    notif = Notification(
        user_id=user_id,
        investor_id=investor_id,
        kind=type_,          # <-- map type_ -> kind
        title=title,
        message=body,        # <-- map body -> message
        link_url=link_url,
    )
    db.session.add(notif)
    db.session.flush()  # get an ID without committing
    return notif


def notify_statement_ready(stmt, *, fail_silently: bool = True) -> None:
    """
    Create an in-app notification + send an email when a statement is generated.

    Called from:
      - statements_routes.generate_statement()
      - statements_routes.generate_all_for_quarter()
      - scheduler.generate_statements_for_current_quarter()
      - scheduler.backfill_missing_statements_daily()

    fail_silently:
      - True  => log email failures but do not raise (good for background jobs)
      - False => re-raise email exceptions so API callers see the error
    """
    inv: Optional[Investor] = Investor.query.get(getattr(stmt, "investor_id", None))

    if not inv:
        log.info(
            "Skipping notification for statement %s: no investor found",
            getattr(stmt, "id", None),
        )
        return

    user_id: Optional[int] = getattr(inv, "account_user_id", None)

    # Build period label for email/body
    period_label = ""
    if getattr(stmt, "period_start", None) and getattr(stmt, "period_end", None):
        period_label = (
            f" for "
            f"{stmt.period_start:%b}. {stmt.period_start.day}, {stmt.period_start.year} – "
            f"{stmt.period_end:%b}. {stmt.period_end.day}, {stmt.period_end.year}"
        )

    title = "Your investor statement is ready"
    body_html = (
        f"Dear {inv.name or 'Investor'},<br><br>"
        f"Your investor statement{period_label} has been generated and is now "
        f"available in your dashboard."
        f"<br><br>"
        f"You can log in to the investor portal to view or download the PDF."
        f"<br><br>"
        f"Best regards,<br>"
        f"Elpis Opportunity Fund"
    )

    # Optional deep-link to the statements page in your frontend
    link_url = "/investor/statements"

    # 1) In-app notification (even if investor has no email)
    _create_notification(
        user_id=user_id,
        investor_id=inv.id,
        type_="statement_generated",
        title=title,
        body=body_html,
        link_url=link_url,
    )

    # 2) Email notification
    if not inv.email:
        log.info(
            "Skipping email for statement %s: investor %s has no email",
            getattr(stmt, "id", None),
            inv.id,
        )
        return

    try:
        send_email(inv.email, title, html=body_html)
        log.info(
            "Statement email sent (or queued) to %s for stmt %s",
            inv.email,
            getattr(stmt, "id", None),
        )
    except Exception as e:
        log.exception(
            "Email send failed for %s (stmt %s): %s",
            inv.email,
            getattr(stmt, "id", None),
            e,
        )
        if not fail_silently:
            # Surface the error to the API route so you can see it in Postman / frontend
            raise


def notify_generic_user(
    user: User,
    *,
    type_: str,
    title: str,
    body: str,
    send_email_flag: bool = False,
    link_url: Optional[str] = None,
) -> None:
    """
    Generic helper to notify a User (admin or investor) with an in-app
    notification, and optionally an email.
    """
    if not user:
        return

    _create_notification(
        user_id=user.id,
        investor_id=None,
        type_=type_,
        title=title,
        body=body,
        link_url=link_url,
    )

    if send_email_flag and getattr(user, "email", None):
        try:
            send_email(user.email, title, html=body)
        except Exception as e:
            log.exception(
                "Email send failed for user %s (%s): %s",
                user.id,
                user.email,
                e,
            )



def create_investor_notification(
    *,
    investor_id: int,
    kind: str,
    title: str,
    message: str,
    link_url: Optional[str] = None,
    statement_id: Optional[int] = None,
    send_email_flag: bool = False,
) -> Optional[Notification]:
    """
    Create a bell notification for a single investor (optionally also email).

    - Automatically wires investor_id -> user_id (account_user_id)
      so the InvestorDashboard bell can see it.
    - Does NOT commit; the caller should call db.session.commit().
    """
    if not investor_id:
        log.warning("create_investor_notification called with no investor_id")
        return None

    inv = db.session.get(Investor, int(investor_id))
    if not inv:
        log.warning(
            "create_investor_notification: investor %s not found", investor_id
        )
        return None

    notif = Notification(
        user_id=inv.account_user_id,          # link to the login user if present
        investor_id=inv.id,
        kind=kind,
        title=title,
        message=message,
        link_url=link_url,
        statement_id=statement_id,
        is_read=False,
    )
    db.session.add(notif)

    if send_email_flag and getattr(inv, "email", None):
        try:
            send_email(inv.email, title, html=message)
        except Exception:
            log.exception(
                "create_investor_notification: email send failed for investor %s",
                inv.id,
            )

    return notif
