from __future__ import annotations

import json
from datetime import datetime, timedelta, date

from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func
from backend.extensions import db

from flask_login import UserMixin


# ------------------ User Model ------------------
class User(db.Model, UserMixin):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    first_name = db.Column(db.String(100), nullable=False)
    last_name  = db.Column(db.String(100), nullable=False)

    email    = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(120), unique=True, nullable=True)  # optional (legacy)

    # NOTE: we keep the same 'password' column name used elsewhere in the codebase.
    password = db.Column(db.String(200), nullable=False)

    # e.g., 'admin', 'investor'
    user_type         = db.Column(db.String(50), nullable=False)
    organization_name = db.Column(db.String(150), nullable=True)

    address = db.Column(db.String(255), nullable=True)
    phone   = db.Column(db.String(50),  nullable=True)

    # extra profile fields for admin invite acceptance
    country = db.Column(db.String(100), nullable=True)
    state   = db.Column(db.String(100), nullable=True)
    city    = db.Column(db.String(100), nullable=True)
    tax_id  = db.Column(db.String(64),  nullable=True)

    bank       = db.Column(db.String(100), nullable=True)
    status     = db.Column(db.String(20),  nullable=False, default="Active")
    permission = db.Column(db.String(50),  nullable=False, default="Viewer")

    # Activation & timestamps
    is_active  = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Admin “Account Controls”
    is_blocked     = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    blocked_at     = db.Column(db.DateTime, nullable=True)
    blocked_by     = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    blocked_reason = db.Column(db.Text, nullable=True)

    # Relationships
    investors = db.relationship("Investor", backref="owner", lazy=True, foreign_keys="Investor.owner_id")
    settings  = db.relationship("AdminSettings", backref="admin", uselist=False, lazy=True)

    # SharePoint connections
    sp_connections = db.relationship(
        "SharePointConnection",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    # QuickBooks connections (two-way)
    qbo_connections = db.relationship(
        "QuickBooksConnection",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    # Password reset requests
    password_resets = db.relationship(
        "PasswordReset",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def get_id(self) -> str:
        return str(self.id)

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"


# ------------------ SMS Verification Model ------------------
class SmsVerification(db.Model):
    __tablename__ = "sms_verification"

    id = db.Column(db.Integer, primary_key=True)

    # Which user this verification belongs to
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Phone number we sent the code to
    phone = db.Column(db.String(50), nullable=False)

    # 6-digit (or similar) code
    code = db.Column(db.String(12), nullable=False)

    # e.g. "login", "password_reset", etc. (for future reuse)
    purpose = db.Column(db.String(32), nullable=False, default="login")

    # pending | verified | expired | cancelled
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)

    # Timestamps
    created_at = db.Column(
        db.DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Optional JSON payload for extra info (IP, user agent, etc.)
    meta = db.Column(db.Text, nullable=True)

    # Relationship back to User
    user = db.relationship(
        "User",
        backref=db.backref(
            "sms_verifications",
            lazy=True,
            cascade="all, delete-orphan",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "phone": self.phone,
            "purpose": self.purpose,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    def mark_verified(self):
        self.status = "verified"
        self.verified_at = datetime.utcnow()


# ------------------ Invitation Model ------------------
class Invitation(db.Model):
    __tablename__ = "invitations"

    id    = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    name  = db.Column(db.String(255), nullable=True)

    # Unique invite token
    token  = db.Column(db.String(128), unique=True, index=True, nullable=False)

    # pending | approved | accepted | expired | revoked
    status = db.Column(db.String(32), default="pending", nullable=False, index=True)

    invited_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    inviter    = db.relationship("User", foreign_keys=[invited_by], lazy=True)

    # Legacy timestamps kept for compatibility
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)  # allow null for never-expiring links
    used_at    = db.Column(db.DateTime, nullable=True)  # set when accepted (legacy name)

    # New timestamps / metadata
    invited_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)  # mirrors created_at
    accepted_at = db.Column(db.DateTime, nullable=True)

    # Optional role stamping for the invite itself (helps separate admin vs investor invites)
    user_type = db.Column(db.String(50), nullable=True)  # e.g., 'admin' | 'investor'

    # Extra fields for investor invite flows (dependents)
    invited_investor_type       = db.Column(db.String(50), nullable=True)
    invited_parent_investor_id  = db.Column(db.Integer, db.ForeignKey("investor.id"), nullable=True)
    invited_parent_relationship = db.Column(db.String(100), nullable=True)

    def is_valid(self) -> bool:
        """Return True if this invitation link can still be used.

        We consider a link valid when:
          * status is "pending" (normal invites) OR "approved" (admin-approved dependent);
          * AND the current time is before expires_at (if an expiry is set).
        """
        now = datetime.utcnow()

        if self.status not in ("pending", "approved"):
            return False
        if self.expires_at is not None and self.expires_at < now:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "token": self.token,
            "status": self.status,
            "user_type": self.user_type,
            "invited_by": self.invited_by,
            "invited_investor_type": self.invited_investor_type,
            "invited_parent_investor_id": self.invited_parent_investor_id,
            "invited_parent_relationship": self.invited_parent_relationship,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "invited_at": self.invited_at.isoformat() if self.invited_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "used_at": self.used_at.isoformat() if self.used_at else None,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
        }


# ------------------ Investor Model ------------------
class Investor(db.Model):
    __tablename__ = "investor"

    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    # investor type (IRA | ROTH IRA | Retirement | Depends)
    investor_type = db.Column(db.String(20), nullable=False, default="IRA", index=True)

    # For dependent investors
    parent_investor_id = db.Column(
        db.Integer,
        db.ForeignKey("investor.id"),
        nullable=True,
        index=True,
    )
    # relationship to the parent (e.g., "Son", "Spouse", "Trustee")
    parent_relationship = db.Column(db.String(100), nullable=True)

    parent = db.relationship(
        "Investor",
        remote_side=[id],
        backref=db.backref("dependents", lazy=True),
        foreign_keys=[parent_investor_id],
        lazy=True,
    )

    # legacy composed fields (what the UI shows)
    company_name  = db.Column(db.String(150), nullable=True)
    address       = db.Column(db.String(255), nullable=True)
    contact_phone = db.Column(db.String(50),  nullable=True)
    email         = db.Column(db.String(120), nullable=True, index=True)

    # login user account mapped to this investor (if any)
    account_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    account_user    = db.relationship("User", foreign_keys=[account_user_id], lazy=True)

    # linkage back to the invitation used to create this investor
    invitation_id = db.Column(db.Integer, db.ForeignKey("invitations.id"), nullable=True)
    invitation    = db.relationship("Invitation", foreign_keys=[invitation_id], lazy=True)

    # granular profile fields
    birthdate   = db.Column(db.String(20),  nullable=True)  # "MM/DD/YYYY"
    citizenship = db.Column(db.String(100), nullable=True)
    ssn_tax_id  = db.Column(db.String(64),  nullable=True)  # consider encrypting/masking later

    # emergency contact
    emergency_contact = db.Column(db.String(50), nullable=True)

    # structured address
    address1 = db.Column(db.String(200), nullable=True)
    address2 = db.Column(db.String(200), nullable=True)
    country  = db.Column(db.String(100), nullable=True)
    city     = db.Column(db.String(100), nullable=True)
    state    = db.Column(db.String(100), nullable=True)
    zip      = db.Column(db.String(20),  nullable=True)

    # personal notes
    note = db.Column(db.String(500), nullable=True)

    # Bank Information (per-investor)
    bank_name           = db.Column(db.String(150), nullable=True)
    bank_account_name   = db.Column(db.String(150), nullable=True)
    bank_account_number = db.Column(db.String(64),  nullable=True)
    bank_account_type   = db.Column(db.String(50),  nullable=True)
    bank_routing_number = db.Column(db.String(64),  nullable=True)
    bank_address        = db.Column(db.String(255), nullable=True)

    avatar_url = db.Column(db.String(300), nullable=True)

    records = db.relationship("Record", backref="investor", lazy=True)

    contacts = db.relationship(
        "InvestorContact", backref="investor", lazy=True, cascade="all, delete-orphan"
    )

    disbursement_preference = db.relationship(
        "DisbursementPreference",
        backref="investor",
        uselist=False,
        lazy=True,
        cascade="all, delete-orphan",
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "company_name": self.company_name,
            "address": self.address,
            "contact_phone": self.contact_phone,
            "email": self.email,
            "owner_id": self.owner_id,
            "account_user_id": self.account_user_id,
            "invitation_id": self.invitation_id,

            "investor_type": self.investor_type,
            "parent_investor_id": self.parent_investor_id,
            "parent_relationship": self.parent_relationship,
            "dependents": [d.id for d in (self.dependents or [])],

            "birthdate": self.birthdate,
            "citizenship": self.citizenship,
            "ssn_tax_id": "***" if self.ssn_tax_id else None,
            "emergency_contact": self.emergency_contact,
            "address1": self.address1,
            "address2": self.address2,
            "country": self.country,
            "city": self.city,
            "state": self.state,
            "zip": self.zip,

            "note": self.note,

            "bank_name": self.bank_name,
            "bank_account_name": self.bank_account_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_type": self.bank_account_type,
            "bank_routing_number": self.bank_routing_number,
            "bank_address": self.bank_address,

            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ------------------ Investor Contact ------------------
class InvestorContact(db.Model):
    __tablename__ = "investor_contacts"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor.id"), nullable=False, index=True)

    name  = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), nullable=False, index=True)
    phone = db.Column(db.String(50),  nullable=True)
    notes = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("investor_id", "email", name="uq_contact_investor_email"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "investor_id": self.investor_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ------------------ Investor Deletion Request ------------------
class InvestorDeletionRequest(db.Model):
    __tablename__ = "investor_deletion_requests"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor.id", ondelete="CASCADE"), nullable=False)
    requested_by_investor_id = db.Column(db.Integer, db.ForeignKey("investor.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | approved | rejected
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True)

    investor = db.relationship("Investor", foreign_keys=[investor_id])
    requested_by = db.relationship("Investor", foreign_keys=[requested_by_investor_id])


# ------------------ Disbursement Preference ------------------
class DisbursementPreference(db.Model):
    __tablename__ = "disbursement_preferences"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor.id"), nullable=False, unique=True, index=True)

    method   = db.Column(db.String(20), nullable=False, default="ACH")  # ACH | Wire | Check
    currency = db.Column(db.String(10), nullable=True, default="USD")

    bank_name            = db.Column(db.String(150), nullable=True)
    account_name         = db.Column(db.String(150), nullable=True)
    account_number_last4 = db.Column(db.String(10),  nullable=True)
    routing_number_last4 = db.Column(db.String(10),  nullable=True)
    iban_last4           = db.Column(db.String(10),  nullable=True)
    swift_bic            = db.Column(db.String(20),  nullable=True)

    payee_name    = db.Column(db.String(150), nullable=True)
    mail_address1 = db.Column(db.String(200), nullable=True)
    mail_address2 = db.Column(db.String(200), nullable=True)
    mail_city     = db.Column(db.String(100), nullable=True)
    mail_state    = db.Column(db.String(100), nullable=True)
    mail_zip      = db.Column(db.String(20),  nullable=True)
    mail_country  = db.Column(db.String(100), nullable=True)

    preferred_day   = db.Column(db.Integer, nullable=True)
    minimum_amount  = db.Column(db.Float,   nullable=True)
    reinvest        = db.Column(db.Boolean, default=False, nullable=False)

    notes = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "investor_id": self.investor_id,
            "method": self.method,
            "currency": self.currency,
            "bank_name": self.bank_name,
            "account_name": self.account_name,
            "account_number_last4": self.account_number_last4,
            "routing_number_last4": self.routing_number_last4,
            "iban_last4": self.iban_last4,
            "swift_bic": self.swift_bic,
            "payee_name": self.payee_name,
            "mail_address1": self.mail_address1,
            "mail_address2": self.mail_address2,
            "mail_city": self.mail_city,
            "mail_state": self.mail_state,
            "mail_zip": self.mail_zip,
            "mail_country": self.mail_country,
            "preferred_day": self.preferred_day,
            "minimum_amount": self.minimum_amount,
            "reinvest": self.reinvest,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ------------------ Excel Upload History ------------------
class ExcelUploadHistory(db.Model):
    __tablename__ = "excel_upload_history"

    id = db.Column(db.Integer, primary_key=True)
    filename    = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "uploaded_at": self.uploaded_at.strftime("%Y-%m-%d %H:%M:%S") if self.uploaded_at else None,
        }


# ------------------ Record Model ------------------
class Record(db.Model):
    __tablename__ = "record"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor.id"), nullable=False)
    type   = db.Column(db.String(50))   # investment, expense, profit
    amount = db.Column(db.Float)
    source = db.Column(db.String(50))   # manual, sheet
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ------------------ Admin Settings (QuickBooks; legacy/global) ------------------
class AdminSettings(db.Model):
    __tablename__ = "admin_settings"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)

    qb_access_token   = db.Column(db.Text,    nullable=True)
    qb_refresh_token  = db.Column(db.Text,    nullable=True)
    qb_expires_in     = db.Column(db.Integer, nullable=True)
    qb_realm_id       = db.Column(db.String(100), nullable=True)
    qb_connection_note= db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "quickbooks_token": bool(self.qb_access_token),
            "quickbooks_refresh_token": bool(self.qb_refresh_token),
            "realm_id": self.qb_realm_id,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


# ------------------ Manual Investor Entry ------------------
class ManualInvestorEntry(db.Model):
    __tablename__ = "manual_investor_entries"

    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50),  nullable=True)

    birthdate   = db.Column(db.String(20),  nullable=True)
    citizenship = db.Column(db.String(100), nullable=True)
    ssn_tax_id  = db.Column(db.String(64),  nullable=True)

    # Emergency Contact phone number
    emergency_contact = db.Column(db.String(50), nullable=True)

    address1 = db.Column(db.String(200), nullable=True)
    address2 = db.Column(db.String(200), nullable=True)
    country  = db.Column(db.String(100), nullable=True)
    city     = db.Column(db.String(100), nullable=True)
    state    = db.Column(db.String(100), nullable=True)
    zip      = db.Column(db.String(20),  nullable=True)

    # optional composed
    address = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "birthdate": self.birthdate,
            "citizenship": self.citizenship,
            "ssn_tax_id": "***" if self.ssn_tax_id else None,
            "emergency_contact": self.emergency_contact,
            "address1": self.address1,
            "address2": self.address2,
            "country": self.country,
            "city": self.city,
            "state": self.state,
            "zip": self.zip,
            "address": self.address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ------------------ SharePoint Connection ------------------
class SharePointConnection(db.Model):
    __tablename__ = "sp_connections"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    url      = db.Column(db.Text, nullable=False)
    drive_id = db.Column(db.String(200), nullable=False)
    item_id  = db.Column(db.String(200), nullable=False)

    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    added_by = db.Column(db.String(200), nullable=True)

    # extras
    is_shared  = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (db.UniqueConstraint("user_id", "item_id", name="uq_spconn_user_item"),)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "url": self.url,
            "drive_id": self.drive_id,
            "item_id": self.item_id,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "added_by": self.added_by,
        }


# ------------------ File uploads (Files section) ------------------
class FileNode(db.Model):
    __tablename__ = "file_nodes"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    scope    = db.Column(db.String(20),  nullable=False)  # 'direct' | 'shared'
    name     = db.Column(db.String(255), nullable=False)
    type     = db.Column(db.String(20),  nullable=False)  # 'folder' | 'file'
    parent_id= db.Column(db.Integer, db.ForeignKey("file_nodes.id"), nullable=True)
    path     = db.Column(db.Text, nullable=False)
    permission= db.Column(db.String(50), default="Investor")
    created_at= db.Column(db.DateTime, default=datetime.utcnow)
    updated_at= db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = db.relationship("FileNode", remote_side=[id], backref="children")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "permission": self.permission,
            "dateUploaded": self.created_at.isoformat() if self.created_at else None,
            "children": [],
        }


# ===== PortfolioPeriodMetric (SharePoint monthly rollups) =====
class PortfolioPeriodMetric(db.Model):
    __tablename__ = "portfolio_period_metrics"

    id    = db.Column(db.Integer, primary_key=True)
    sheet = db.Column(db.String(120), nullable=False, index=True)
    as_of_date = db.Column(db.Date, nullable=False, index=True)

    beginning_balance    = db.Column(db.Float, nullable=True)
    ending_balance       = db.Column(db.Float, nullable=True)
    unrealized_gain_loss = db.Column(db.Float, nullable=True)
    realized_gain_loss   = db.Column(db.Float, nullable=True)
    management_fees      = db.Column(db.Float, nullable=True)

    source     = db.Column(db.String(40), nullable=False, default="sharepoint-live")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("sheet", "as_of_date", name="uq_sheet_asof"),)

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet,
            "as_of_date": self.as_of_date.isoformat(),
            "beginning_balance": self.beginning_balance,
            "ending_balance": self.ending_balance,
            "unrealized_gain_loss": self.unrealized_gain_loss,
            "realized_gain_loss": self.realized_gain_loss,
            "management_fees": self.management_fees,
            "source": self.source,
        }


class AdminPeriodBalance(db.Model):
    __tablename__ = "admin_period_balances"

    id = db.Column(db.Integer, primary_key=True)

    # One row per as_of_date
    as_of_date = db.Column(db.Date, nullable=False, unique=True, index=True)

    beginning_ownership = db.Column(db.Float, nullable=True)
    beginning_balance   = db.Column(db.Float, nullable=True)
    gross_profit        = db.Column(db.Float, nullable=True)
    management_fees     = db.Column(db.Float, nullable=True)
    operating_expenses  = db.Column(db.Float, nullable=True)
    allocated_fees      = db.Column(db.Float, nullable=True)
    additions           = db.Column(db.Float, nullable=True)
    withdrawals         = db.Column(db.Float, nullable=True)
    ending_balance      = db.Column(db.Float, nullable=True)

    source     = db.Column(db.String(32), nullable=False, default="aggregated")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "as_of_date": self.as_of_date.isoformat(),
            "beginning_ownership": self.beginning_ownership,
            "beginning_balance": self.beginning_balance,
            "gross_profit": self.gross_profit,
            "management_fees": self.management_fees,
            "operating_expenses": self.operating_expenses,
            "allocated_fees": self.allocated_fees,
            "additions": self.additions,
            "withdrawals": self.withdrawals,
            "ending_balance": self.ending_balance,
            "source": self.source,
        }


# ------------------ Investments & Sources & Values ------------------
class Investment(db.Model):
    __tablename__ = "investments"
    __table_args__ = {"sqlite_autoincrement": True}

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(255), nullable=False, unique=True, index=True)
    color_hex  = db.Column(db.String(7), nullable=True)
    industry   = db.Column(db.String(120), nullable=True)
    is_active  = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    values = db.relationship(
        "PortfolioInvestmentValue",
        backref="investment",
        lazy=True,
        cascade="all, delete-orphan",
        primaryjoin="Investment.id==PortfolioInvestmentValue.investment_id",
    )

    def to_dict(self) -> dict:
        return {
            "id": int(self.id) if self.id is not None else None,
            "name": self.name,
            "color_hex": self.color_hex,
            "industry": self.industry,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DataSource(db.Model):
    __tablename__ = "data_sources"
    __table_args__ = {"sqlite_autoincrement": True}

    id         = db.Column(db.Integer, primary_key=True)
    kind       = db.Column(db.String(30), nullable=False)     # 'sharepoint' | 'upload'
    drive_id   = db.Column(db.String(200), nullable=True)
    item_id    = db.Column(db.String(200), nullable=True)
    file_name  = db.Column(db.String(255), nullable=True)
    sheet_name = db.Column(db.String(255), nullable=True)
    added_by   = db.Column(db.String(200), nullable=True)
    added_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": int(self.id) if self.id is not None else None,
            "kind": self.kind,
            "drive_id": self.drive_id,
            "item_id": self.item_id,
            "file_name": self.file_name,
            "sheet_name": self.sheet_name,
            "added_by": self.added_by,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }


class PortfolioInvestmentValue(db.Model):
    __tablename__ = "portfolio_investment_values"
    __table_args__ = (
        db.UniqueConstraint("investment_id", "as_of_date", name="uq_investment_asof"),
        {"sqlite_autoincrement": True},
    )

    id             = db.Column(db.Integer, primary_key=True)
    investment_id  = db.Column(db.Integer, db.ForeignKey("investments.id", ondelete="CASCADE"), nullable=False, index=True)
    as_of_date     = db.Column(db.Date, nullable=False, index=True)
    value          = db.Column(db.Numeric(18, 2), nullable=False)
    source         = db.Column(db.String(50), default="valuation_sheet")
    source_id      = db.Column(db.Integer, db.ForeignKey("data_sources.id"), nullable=True)
    row_hash       = db.Column(db.String(40), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": int(self.id) if self.id is not None else None,
            "investment_id": int(self.investment_id) if self.investment_id is not None else None,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "value": float(self.value) if self.value is not None else None,
            "source": self.source,
            "source_id": int(self.source_id) if self.source_id is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ===== QuickBooks connection (per user/company) =====
class QuickBooksConnection(db.Model):
    __tablename__ = "quickbooks_connections"

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    realm_id= db.Column(db.String(32), nullable=False, index=True)
    environment = db.Column(db.String(16), nullable=False, default="sandbox")

    token_type    = db.Column(db.String(16), default="bearer")
    access_token  = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    expires_at    = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="qbo_connections")


# ===== QBO monthly rollups (optional) =====
class QboPeriodMetric(db.Model):
    __tablename__ = "qbo_period_metrics"

    id         = db.Column(db.Integer, primary_key=True)
    realm_id   = db.Column(db.String(32), nullable=False, index=True)
    sheet      = db.Column(db.String(64), default="QBO (BS+PL)")
    as_of_date = db.Column(db.Date, nullable=False, index=True)

    beginning_balance    = db.Column(db.Float, nullable=True)
    ending_balance       = db.Column(db.Float, nullable=True)
    unrealized_gain_loss = db.Column(db.Float, nullable=True)
    realized_gain_loss   = db.Column(db.Float, nullable=True)
    management_fees      = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("realm_id", "sheet", "as_of_date", name="uq_qbo_period_metrics_unique"),)


# ===== QBO raw entities dump =====
class QboEntity(db.Model):
    __tablename__ = "qbo_entities"

    id          = db.Column(db.Integer, primary_key=True)
    realm_id    = db.Column(db.String(32), nullable=False, index=True)
    entity_type = db.Column(db.String(64), nullable=False, index=True)  # "Invoice", "Customer", etc.
    qbo_id      = db.Column(db.String(64), nullable=False)

    txn_date    = db.Column(db.Date, nullable=True, index=True)
    doc_number  = db.Column(db.String(64), nullable=True, index=True)
    name        = db.Column(db.String(255), nullable=True, index=True)
    total_amount= db.Column(db.Float, nullable=True)

    raw_json    = db.Column(db.Text, nullable=False)

    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("realm_id", "entity_type", "qbo_id", name="uq_qbo_entity_unique"),)

    def to_dict(self) -> dict:
        return {
            "realm_id": self.realm_id,
            "entity_type": self.entity_type,
            "qbo_id": self.qbo_id,
            "txn_date": self.txn_date.isoformat() if self.txn_date else None,
            "doc_number": self.doc_number,
            "name": self.name,
            "total_amount": self.total_amount,
        }


# ===== QBO sync run logs =====
class QboSyncLog(db.Model):
    __tablename__ = "qbo_sync_logs"

    id       = db.Column(db.Integer, primary_key=True)
    realm_id = db.Column(db.String(32), nullable=False, index=True)
    ran_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    from_date= db.Column(db.Date, nullable=True)
    to_date  = db.Column(db.Date, nullable=True)
    entities = db.Column(db.Text, nullable=False)   # comma-separated list
    stats_json = db.Column(db.Text, nullable=True)  # {"Invoice": 120, ...}

    def to_dict(self) -> dict:
        return {
            "realm_id": self.realm_id,
            "ran_at": self.ran_at.isoformat(),
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "entities": self.entities.split(",") if self.entities else [],
            "stats": json.loads(self.stats_json) if self.stats_json else {},
        }


# ===== Market data (kept) =====
class MarketPrice(db.Model):
    __tablename__ = "market_prices"

    id     = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(32), nullable=False, index=True)
    date   = db.Column(db.Date, nullable=False, index=True)

    open  = db.Column(db.Float)
    high  = db.Column(db.Float)
    low   = db.Column(db.Float)
    close = db.Column(db.Float)
    adj_close = db.Column(db.Float)
    volume    = db.Column(db.BigInteger)

    source     = db.Column(db.String(32), nullable=False, default="yfinance")
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now(), nullable=False)

    __table_args__ = (db.UniqueConstraint("symbol", "date", name="uq_market_prices_symbol_date"),)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "date": self.date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            # keep compatibility with possible older 'ad_close' column
            "adj_close": self.ad_close if hasattr(self, "ad_close") else self.adj_close,
            "volume": self.volume,
            "source": self.source,
        }


# --- Documents (admin uploads shared to investors) ---
class DocumentFolder(db.Model):
    __tablename__ = "document_folders"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


    parent_id = db.Column(
    db.Integer,
    db.ForeignKey("document_folders.id"),
    nullable=True,
    )


        
    # optional convenience relationship
    parent = db.relationship(
        "DocumentFolder",
        remote_side="DocumentFolder.id",
        backref=db.backref("children", lazy="dynamic"),
    )

    # documents backref is defined on Document.folder relationship below
    shares = db.relationship(
        "DocumentFolderShare",
        backref="folder",
        cascade="all,delete-orphan",
    )


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(128))
    size_bytes = db.Column(db.Integer)

    # which admin created it
    uploaded_by_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # NEW: optional folder
    folder_id = db.Column(
        db.Integer,
        db.ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    folder = db.relationship(
        "DocumentFolder",
        backref=db.backref("documents", cascade="all,delete-orphan"),
    )

    shares = db.relationship(
        "DocumentShare",
        backref="document",
        cascade="all,delete-orphan",
    )


class DocumentShare(db.Model):
    __tablename__ = "document_shares"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    investor_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    # NEW: where the investor should see this file
    # "document"  -> Investor Documents section
    # "statement" -> Investor Statements section/tab
    share_type = db.Column(
        db.String(32),
        nullable=False,
        default="document",
        server_default="document",
        index=True,
    )

    shared_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "document_id",
            "investor_user_id",
            name="uq_doc_investor",
        ),
    )


class DocumentFolderShare(db.Model):
    __tablename__ = "document_folder_shares"

    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(
        db.Integer,
        db.ForeignKey("document_folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    investor_user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    shared_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "folder_id",
            "investor_user_id",
            name="uq_folder_investor",
        ),
    )



class Statement(db.Model):
    __tablename__ = "statements"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor.id"), nullable=False)
    investor_name = db.Column(db.String(255), nullable=False)        # denormalized for faster list views
    entity_name = db.Column(db.String(255), nullable=False)          # e.g., "Elpis Opportunity Fund LP"
    period_start = db.Column(db.Date, nullable=False)
    period_end   = db.Column(db.Date, nullable=False)
    beginning_balance = db.Column(db.Numeric(18, 2), nullable=False)
    contributions     = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    distributions     = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    unrealized_gl     = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    incentive_fees    = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    management_fees   = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    operating_expenses= db.Column(db.Numeric(18, 2), nullable=False, default=0)
    adjustment        = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    net_income_loss   = db.Column(db.Numeric(18, 2), nullable=False)
    ending_balance    = db.Column(db.Numeric(18, 2), nullable=False)
    ownership_percent = db.Column(db.Numeric(9, 6), nullable=True)
    roi_pct           = db.Column(db.Numeric(9, 4), nullable=True)
    pdf_path          = db.Column(db.String(512), nullable=True)
    created_at        = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('investor_id', 'period_start', 'period_end', name='uix_statement_quarter'),
    )


# -------- Password Reset --------
class PasswordReset(db.Model):
    __tablename__ = "password_resets"

    id = db.Column(db.Integer, primary_key=True)
    # User table is 'user'
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    email = db.Column(db.String(255), index=True)
    token = db.Column(db.String(64), unique=True, index=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    pending_pw_hash = db.Column(db.String(255))      # store after Step 3
    code_hash = db.Column(db.String(255))            # hashed 6-digit code
    code_sent_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ------------------ Group Investor Request ------------------
class GroupInvestorRequest(db.Model):
    __tablename__ = "group_investor_requests"

    id = db.Column(db.Integer, primary_key=True)

    # The user who is requesting to become Group Investor Admin
    requester_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )

    # Optional: the main Investor profile for this user (if any)
    requester_investor_id = db.Column(
        db.Integer,
        db.ForeignKey("investor.id"),
        nullable=True,
        index=True,
    )

    # JSON-encoded list of investor IDs that should belong to the group
    member_investor_ids = db.Column(db.Text, nullable=False)

    # pending | approved | rejected
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        index=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    decided_at = db.Column(db.DateTime, nullable=True)

    # Admin user who approved / rejected the request
    decided_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
    )

    requester_user = db.relationship("User", foreign_keys=[requester_user_id], lazy=True)
    requester_investor = db.relationship("Investor", foreign_keys=[requester_investor_id], lazy=True)
    decided_by = db.relationship("User", foreign_keys=[decided_by_user_id], lazy=True)

    def get_member_ids(self) -> list[int]:
        """Decode the JSON list of member investor IDs."""
        try:
            raw = json.loads(self.member_investor_ids or "[]")
            if not isinstance(raw, list):
                return []
            ids: list[int] = []
            for v in raw:
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    continue
            return ids
        except Exception:
            return []

    def set_member_ids(self, ids: list[int]) -> None:
        """Encode the list of member investor IDs as JSON."""
        self.member_investor_ids = json.dumps([int(i) for i in ids])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "requester_user_id": self.requester_user_id,
            "requester_investor_id": self.requester_investor_id,
            "member_investor_ids": self.get_member_ids(),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decided_by_user_id": self.decided_by_user_id,
        }


# ------------------ Investor Group Membership ------------------
class InvestorGroupMembership(db.Model):
    __tablename__ = "investor_group_membership"

    id = db.Column(db.Integer, primary_key=True)

    # The Group Investor Admin (user.id)
    group_admin_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )

    # The investor that belongs to that admin’s group (investor.id)
    investor_id = db.Column(
        db.Integer,
        db.ForeignKey("investor.id"),
        nullable=False,
        index=True,
    )

    # Relationships
    group_admin = db.relationship("User", foreign_keys=[group_admin_id], lazy=True)
    investor = db.relationship("Investor", lazy=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "group_admin_id",
            "investor_id",
            name="uq_group_admin_investor",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "group_admin_id": self.group_admin_id,
            "investor_id": self.investor_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# -------- Investor Accreditation --------
class InvestorAccreditation(db.Model):
    __tablename__ = "investor_accreditation"

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(
        db.Integer,
        db.ForeignKey("investor.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one record per investor
    )
    selection = db.Column(db.String(64), nullable=False)          # e.g. "inv_5m", "not_yet", ...
    accredited = db.Column(db.Boolean, nullable=False, server_default=db.text("false"))
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    investor = db.relationship("Investor", backref=db.backref("accreditation", uselist=False, cascade="all, delete"))


# -------- Activity Log --------
class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(64), nullable=True)        # "admin" | "groupadmin" | "investor" | etc.
    action = db.Column(db.String(16), nullable=False)     # "login" | "logout"
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<ActivityLog {self.id} {self.action} {self.name} {self.created_at}>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "action": self.action,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat() + "Z",
        }


# ------------------ Notification ------------------
class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    # Owner of the notification (can be user-level or investor-level)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    investor_id = db.Column(
        db.Integer,
        db.ForeignKey("investor.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # What happened
    kind = db.Column(db.String(80), nullable=False)  # e.g. "statement_generated", "dependent_request"
    title = db.Column(db.String(200), nullable=False)

    # Message body; both 'message' and 'body' support for compatibility
    message = db.Column(db.Text, nullable=True)
    body    = db.Column(db.Text, nullable=True)

    link_url = db.Column(db.String(500), nullable=True)

    # Optional link to a statement row
    statement_id = db.Column(
        db.Integer,
        db.ForeignKey("statements.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Read state
    is_read   = db.Column(db.Boolean, default=False, nullable=False)
    created_at= db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    read_at   = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        msg = self.message if self.message is not None else self.body
        return {
            "id": self.id,
            "user_id": self.user_id,
            "investor_id": self.investor_id,
            "kind": self.kind,
            "title": self.title,
            "message": msg,
            "link_url": self.link_url,
            "statement_id": self.statement_id,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }



# ------------------ Admin Mailbox Message ------------------
class AdminMessage(db.Model):
    __tablename__ = "admin_messages"

    id = db.Column(db.Integer, primary_key=True)

    # Investor who sent the message
    investor_id = db.Column(db.Integer, nullable=True)
    investor_name = db.Column(db.String(255), nullable=True)

    # Email fields
    subject = db.Column(db.String(255), nullable=True)
    body = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "investor_id": self.investor_id,
            "investor_name": self.investor_name,
            "subject": self.subject,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }
