# backend/utils/emailing.py
from __future__ import annotations

from flask import current_app


def _resolve_sender() -> str | None:
    """Pick a sender in priority order from config."""
    cfg = current_app.config
    return (
        cfg.get("MAIL_DEFAULT_SENDER")
        or cfg.get("SMTP_FROM")
        or cfg.get("MAIL_USERNAME")
    )


def send_invite_email(email: str, name: str | None, link: str) -> bool:
    """
    Send an invite email. Returns True on success, False on failure.
    If Flask-Mail isn't configured, we log a dev-friendly link and return False
    (to preserve existing best-effort behavior in your routes).
    """
    mail_ext = current_app.extensions.get("mail")  # Flask-Mail instance
    if not mail_ext:
        current_app.logger.warning("[Mail disabled] Invite link for %s: %s", email, link)
        return False

    sender = _resolve_sender()
    if not sender:
        current_app.logger.error(
            "No sender configured. Set MAIL_DEFAULT_SENDER or MAIL_USERNAME."
        )
        return False

    try:
        # imported lazily so app can start without Flask-Mail installed
        from flask_mail import Message

        subject = current_app.config.get(
            "INVITE_SUBJECT", "You're invited to the Investor Portal"
        )
        safe_name = (name or "").strip()

        text_body = (
            f"Hi {safe_name},\n\n"
            f"You’ve been invited. Finish setup here:\n{link}\n\n"
            f"This link expires in 14 days."
        )
        html_body = (
            f"<p>Hi {safe_name},</p>"
            f"<p>You’ve been invited. Finish setup here: "
            f'<a href="{link}" target="_blank" rel="noopener noreferrer">{link}</a></p>'
            f"<p>This link expires in 14 days.</p>"
        )

        msg = Message(
            subject=subject,
            recipients=[email],
            sender=sender,  # critical to avoid AssertionError
            body=text_body,
            html=html_body,
            reply_to=current_app.config.get("MAIL_REPLY_TO", sender),
        )

        mail_ext.send(msg)
        current_app.logger.info(
            "Invite email sent to %s via %s", email, current_app.config.get("MAIL_SERVER")
        )
        return True

    except Exception:
        current_app.logger.exception("Failed to send invitation email to %s", email)
        return False


def send_password_reset_email(email: str, link: str) -> bool:
    """
    Send a password reset email containing the 'link'.
    Returns True if sent (or logged in dev), False on hard failure.

    If Flask-Mail isn't configured, we LOG the link and return True so the
    frontend flow can proceed during development.
    """
    mail_ext = current_app.extensions.get("mail")
    subject = current_app.config.get("PASSWORD_RESET_SUBJECT", "Reset your password")
    sender = _resolve_sender()

    # Dev-friendly fallback: not configured -> log the link and report success.
    if not mail_ext:
        current_app.logger.warning(
            "[Mail disabled] Password reset link for %s: %s", email, link
        )
        return True

    if not sender:
        current_app.logger.error(
            "No sender configured. Set MAIL_DEFAULT_SENDER or MAIL_USERNAME."
        )
        return False

    try:
        from flask_mail import Message

        text_body = (
            "We received a request to reset your password.\n\n"
            f"Click the link below to set a new password:\n{link}\n\n"
            "This link will expire in 30 minutes. If you didn't request this, "
            "you can ignore this email."
        )
        html_body = (
            "<p>We received a request to reset your password.</p>"
            f'<p><a href="{link}" target="_blank" rel="noopener noreferrer">Reset your password</a></p>'
            "<p>This link will expire in 30 minutes. If you didn't request this, "
            "you can ignore this email.</p>"
        )

        msg = Message(
            subject=subject,
            recipients=[email],
            sender=sender,
            body=text_body,
            html=html_body,
            reply_to=current_app.config.get("MAIL_REPLY_TO", sender),
        )

        mail_ext.send(msg)
        current_app.logger.info(
            "Password reset email sent to %s via %s",
            email,
            current_app.config.get("MAIL_SERVER"),
        )
        return True

    except Exception:
        current_app.logger.exception("Failed to send password reset email to %s", email)
        return False


# ---- NEW: send a 6-digit verification code for password change ----
def send_password_code(email: str, name: str | None, code: str) -> bool:
    """
    Send a 6-digit password reset/verification code to the user.

    Returns True if sent (or logged in dev), False on hard failure.
    """
    mail_ext = current_app.extensions.get("mail")
    subject = current_app.config.get(
        "PASSWORD_CODE_SUBJECT", "Your password verification code"
    )
    sender = _resolve_sender()

    # Dev-friendly fallback: mail not configured -> log the code and report success.
    if not mail_ext:
        current_app.logger.warning(
            "[Mail disabled] Password reset code for %s: %s", email, code
        )
        return True

    if not sender:
        current_app.logger.error(
            "No sender configured. Set MAIL_DEFAULT_SENDER or MAIL_USERNAME."
        )
        return False

    try:
        from flask_mail import Message

        safe_name = (name or "").strip() or "there"

        text_body = (
            f"Hi {safe_name},\n\n"
            f"You requested to change your password.\n\n"
            f"Your verification code is: {code}\n\n"
            "This code will expire in about 15 minutes.\n\n"
            "If you did not request this, you can safely ignore this email."
        )
        html_body = (
            f"<p>Hi {safe_name},</p>"
            "<p>You requested to change your password.</p>"
            f"<p><strong>Your verification code is: {code}</strong></p>"
            "<p>This code will expire in about 15 minutes.</p>"
            "<p>If you did not request this, you can safely ignore this email.</p>"
        )

        msg = Message(
            subject=subject,
            recipients=[email],
            sender=sender,
            body=text_body,
            html=html_body,
            reply_to=current_app.config.get("MAIL_REPLY_TO", sender),
        )

        mail_ext.send(msg)
        current_app.logger.info(
            "Password reset code email sent to %s via %s",
            email,
            current_app.config.get("MAIL_SERVER"),
        )
        return True

    except Exception:
        current_app.logger.exception(
            "Failed to send password reset code email to %s", email
        )
        return False


# ---- Convenience alias so routes can import `send_password_reset` ----
def send_password_reset(email: str, link: str) -> bool:
    """Wrapper for backwards-compatibility with existing imports."""
    return send_password_reset_email(email, link)
