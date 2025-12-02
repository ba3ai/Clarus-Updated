# backend/utils/activity.py
from flask import request
from backend.extensions import db
from backend.models import ActivityLog

def log_activity(user, action: str):
    """
    action: "login" or "logout"
    """
    if not user:
        return

    # Infer role from your User model
    role = (getattr(user, "user_type", "") or "").lower()

    name_parts = [
        getattr(user, "name", None),
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
    ]
    name = next((p for p in name_parts if p), user.email if getattr(user, "email", None) else None)

    log = ActivityLog(
        user_id=user.id,
        name=name,
        role=role,                       # "admin" | "investor" | "groupadmin"
        action=action,                   # "login" or "logout"
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    db.session.add(log)
    db.session.commit()
