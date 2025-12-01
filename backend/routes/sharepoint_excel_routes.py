# backend/routes/sharepoint_excel_routes.py
from __future__ import annotations

import re
import time
import secrets
import traceback
from typing import Optional, List, Dict, Any

import pandas as pd
from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import generate_password_hash

from backend.config import Config
from backend.routes.auth_ms_routes import get_session_bearer
from backend.graph_sharepoint import (
    open_excel_by_components,
    list_worksheets,
    list_tables,
    read_range,
    read_table_rows,
    pandas_from_range_payload,
    open_excel_by_share_url,
)
from backend.extensions import db
from backend.models import SharePointConnection, User

# Reuse the same ingest + classifier helpers as the Excel upload routes
try:
    from backend.routes.excel_routes import (
        _ingest_new_balance_sheet,
        _ingest_investments_table,
        _classify_workbook,
        _normalize_sheet_name,
    )
except Exception:  # fallback if your project layout is slightly different
    from backend.routes.excel_routes import (
        _ingest_new_balance_sheet,
        _ingest_investments_table,
        _classify_workbook,
        _normalize_sheet_name,
    )

# Optional MSAL for app-only auth
try:  # pragma: no cover
    from msal import ConfidentialClientApplication  # type: ignore
except Exception:  # pragma: no cover
    ConfidentialClientApplication = None


bp = Blueprint("sharepoint_excel", __name__, url_prefix="/api/sharepoint/excel")

_HOST_RE = re.compile(r"^[a-zA-Z0-9.-]+\.sharepoint\.com$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _cfg(key: str, default=None):
    if current_app and getattr(current_app, "config", None):
        if key in current_app.config and current_app.config[key] is not None:
            return current_app.config[key]
    return getattr(Config, key, default)


# ---------------------------------------------------------------------------
# App-only (client credentials) token cache
# ---------------------------------------------------------------------------

_app_token_cache: Dict[str, Any] = {
    "authority": None,
    "access_token": None,
    "exp": 0.0,
}
_msal_app: Optional["ConfidentialClientApplication"] = None


def _resolve_app_authority() -> str:
    """
    Resolve the authority for app-only Graph calls:
      - Prefer per-request X-Tenant-Id
      - Else AZURE_TENANT_ID
      - Replace invalid 'common'/'consumers' with 'organizations'
    """
    req_tenant = (request.headers.get("X-Tenant-Id") or "").strip()
    env_tenant = str(_cfg("AZURE_TENANT_ID") or "").strip()
    tenant = (req_tenant or env_tenant or "").strip()
    if tenant.lower() in ("", "common", "consumers"):
        tenant = "organizations"
    return f"https://login.microsoftonline.com/{tenant}"


def _get_app_bearer() -> str:
    """Acquire (and cache) an application token for Microsoft Graph."""
    global _msal_app, _app_token_cache

    if ConfidentialClientApplication is None:
        raise RuntimeError("msal is not installed. Run `pip install msal`.")

    client_id = str(_cfg("AZURE_CLIENT_ID") or "").strip()
    client_secret = str(_cfg("AZURE_CLIENT_SECRET") or "").strip()
    if not (client_id and client_secret):
        raise RuntimeError("Missing AZURE_CLIENT_ID / AZURE_CLIENT_SECRET")

    authority = _resolve_app_authority()

    if _msal_app is None or _app_token_cache["authority"] != authority:
        _msal_app = ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=client_secret,
        )
        _app_token_cache.update({"authority": authority, "access_token": None, "exp": 0.0})

    now = time.time()
    if _app_token_cache.get("access_token") and now < (_app_token_cache["exp"] - 120):
        return _app_token_cache["access_token"]  # type: ignore

    result = _msal_app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise PermissionError(result.get("error_description") or str(result))

    _app_token_cache["access_token"] = result["access_token"]
    _app_token_cache["exp"] = now + int(result.get("expires_in", 3600))
    return result["access_token"]


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def _bearer_from_request() -> Optional[str]:
    """
    Decide whether to use delegated auth (per-user token) or app-only
    (client credentials) based on GRAPH_AUTH_MODE.
    """
    mode = str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower()
    if mode == "delegated":
        # token stored in session by /auth/ms routes
        return get_session_bearer()
    return _get_app_bearer()


def _tenant_from_request() -> Optional[str]:
    return request.headers.get("X-Tenant-Id")


def _validate_host(hostname: str) -> bool:
    return bool(_HOST_RE.match(hostname))


def _current_user_id() -> Optional[int]:
    """
    Get or create a local app user:
      - Prefer session["user_id"]
      - Fallback to session["ms_account"], create viewer user if not exists
    """
    uid = session.get("user_id")
    if uid:
        try:
            return int(uid)
        except Exception:
            return None

    acct = session.get("ms_account") or {}
    email = acct.get("userPrincipalName") or acct.get("mail")
    if not email:
        return None

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            password=generate_password_hash(secrets.token_urlsafe(16)),
            user_type="viewer",
            permission="Viewer",
            status="active",
            first_name=acct.get("givenName"),
            last_name=acct.get("surname"),
        )
        db.session.add(user)
        db.session.commit()

    session["user_id"] = user.id
    return user.id


# ---------------------------------------------------------------------------
# URL-based metadata / preview
# ---------------------------------------------------------------------------

@bp.route("/metadata_by_url", methods=["POST"])
def metadata_by_url():
    data = request.get_json(silent=True) or {}
    share_url = (data.get("url") or "").strip()
    if not share_url:
        return jsonify(error="Missing 'url'."), 400

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_share_url(share_url, bearer)
        sheets = list_worksheets(drive_id, item_id, bearer, _tenant_from_request())
        tables = list_tables(drive_id, item_id, bearer, _tenant_from_request())
        return jsonify(ok=True, drive_id=drive_id, item_id=item_id,
                       worksheets=sheets, tables=tables)
    except PermissionError as e:
        return jsonify(error=str(e)), 401
    except Exception as e:
        current_app.logger.exception("metadata_by_url failed")
        return jsonify(error=str(e)), 500


@bp.route("/preview_by_url", methods=["POST"])
def preview_by_url():
    data = request.get_json(silent=True) or {}
    share_url = (data.get("url") or "").strip()
    if not share_url:
        return jsonify(error="Missing 'url'."), 400

    mode = (data.get("mode") or "range").strip().lower()
    worksheet = (data.get("worksheet") or "").strip()
    address = (data.get("address") or "").strip()
    table = (data.get("table") or "").strip()
    first_row_headers = bool(data.get("first_row_headers", True))

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_share_url(share_url, bearer)
        if mode == "table":
            rows_payload = read_table_rows(drive_id, item_id, table, bearer)
            values: List[List[Any]] = []
            for r in rows_payload.get("value", []):
                values.extend(r.get("values", []))
            df = pd.DataFrame(values)
            if first_row_headers and not df.empty:
                cols = [str(c) for c in list(df.iloc[0])]
                df = df.iloc[1:].reset_index(drop=True)
                df.columns = cols
        else:
            rng_payload = read_range(drive_id, item_id, worksheet, address, bearer)
            df = pandas_from_range_payload(rng_payload, first_row_headers=first_row_headers)

        max_rows = int(_cfg("EXCEL_PREVIEW_ROW_LIMIT", 500))
        truncated = False
        if len(df) > max_rows:
            df = df.head(max_rows)
            truncated = True

        columns = [str(c) for c in df.columns]
        rows_out = [
            dict(zip(columns, (x if x is not None else "" for x in row)))
            for row in df.fillna("").to_numpy()
        ]
        return jsonify(ok=True, columns=columns, rows=rows_out, truncated=truncated)
    except PermissionError as e:
        return jsonify(error=str(e)), 401
    except Exception as e:
        current_app.logger.exception("preview_by_url failed")
        return jsonify(error=str(e)), 500


# ---------------------------------------------------------------------------
# Component-based metadata / preview (not used by your current UI but kept)
# ---------------------------------------------------------------------------

@bp.route("/metadata", methods=["POST"])
def metadata():
    data = request.get_json(silent=True) or {}

    hostname = (data.get("hostname") or "").strip()
    site_path = (data.get("site_path") or "").strip("/")
    drive_name = (data.get("drive_name") or "Documents").strip()
    file_path = (data.get("file_path") or "").strip("/")

    if not hostname or not drive_name or not file_path:
        return jsonify(error="Missing hostname, drive_name, or file_path"), 400
    if not _validate_host(hostname):
        return jsonify(error="Invalid SharePoint hostname"), 400

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_components(
            hostname, site_path, drive_name, file_path, bearer
        )
        sheets = list_worksheets(drive_id, item_id, bearer, _tenant_from_request())
        tables = list_tables(drive_id, item_id, bearer, _tenant_from_request())
        return jsonify(ok=True, drive_id=drive_id, item_id=item_id,
                       worksheets=sheets, tables=tables)
    except PermissionError as e:
        return jsonify(error=str(e)), 401
    except Exception as e:
        current_app.logger.exception("metadata failed")
        return jsonify(error=str(e)), 500


@bp.route("/preview", methods=["POST"])
def preview():
    data = request.get_json(silent=True) or {}

    hostname = (data.get("hostname") or "").strip()
    site_path = (data.get("site_path") or "").strip("/")
    drive_name = (data.get("drive_name") or "Documents").strip()
    file_path = (data.get("file_path") or "").strip("/")

    mode = (data.get("mode") or "range").strip().lower()
    worksheet = (data.get("worksheet") or "").strip()
    address = (data.get("address") or "").strip()
    table = (data.get("table") or "").strip()
    first_row_headers = bool(data.get("first_row_headers", True))

    if not hostname or not drive_name or not file_path:
        return jsonify(error="Missing hostname, drive_name, or file_path"), 400
    if not _validate_host(hostname):
        return jsonify(error="Invalid SharePoint hostname"), 400

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_components(
            hostname, site_path, drive_name, file_path, bearer
        )
        if mode == "table":
            rows_payload = read_table_rows(drive_id, item_id, table, bearer)
            values: List[List[Any]] = []
            for r in rows_payload.get("value", []):
                values.extend(r.get("values", []))
            df = pd.DataFrame(values)
            if first_row_headers and not df.empty:
                cols = [str(c) for c in list(df.iloc[0])]
                df = df.iloc[1:].reset_index(drop=True)
                df.columns = cols
        else:
            rng_payload = read_range(drive_id, item_id, worksheet, address, bearer)
            df = pandas_from_range_payload(rng_payload, first_row_headers=first_row_headers)

        max_rows = int(_cfg("EXCEL_PREVIEW_ROW_LIMIT", 500))
        truncated = False
        if len(df) > max_rows:
            df = df.head(max_rows)
            truncated = True

        columns = [str(c) for c in df.columns]
        rows_out = [
            dict(zip(columns, (x if x is not None else "" for x in row)))
            for row in df.fillna("").to_numpy()
        ]
        return jsonify(ok=True, columns=columns, rows=rows_out, truncated=truncated)
    except PermissionError as e:
        return jsonify(error=str(e)), 401
    except Exception as e:
        current_app.logger.exception("preview failed")
        return jsonify(error=str(e)), 500


# ---------------------------------------------------------------------------
# Connections (DB-backed)
# ---------------------------------------------------------------------------

@bp.route("/connect_by_url", methods=["POST"])
def connect_by_url():
    data = request.get_json(silent=True) or {}
    share_url = (data.get("url") or "").strip()
    if not share_url:
        return jsonify(error="Missing 'url'"), 400

    user_id = _current_user_id()
    if not user_id:
        return jsonify(error="Unauthorized: please log in."), 401

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_share_url(share_url, bearer)
        # validate by listing sheets once
        _ = list_worksheets(drive_id, item_id, bearer, _tenant_from_request())

        acct = session.get("ms_account") or {}
        added_by = (
            acct.get("userPrincipalName")
            or acct.get("mail")
            or acct.get("displayName")
        )

        existing = SharePointConnection.query.filter_by(
            user_id=user_id, item_id=item_id
        ).first()
        if not existing:
            conn = SharePointConnection(
                user_id=user_id,
                url=share_url,
                drive_id=drive_id,
                item_id=item_id,
                added_by=added_by,
            )
            db.session.add(conn)
            db.session.commit()

        conns = (
            SharePointConnection.query.filter_by(user_id=user_id)
            .order_by(SharePointConnection.id.desc())
            .all()
        )
        return jsonify(ok=True, connections=[c.to_dict() for c in conns])
    except PermissionError as e:
        return jsonify(error=str(e)), 401
    except Exception as e:
        current_app.logger.exception("connect_by_url failed")
        return jsonify(error=str(e)), 500


@bp.route("/connections", methods=["GET"])
def list_connections():
    user_id = _current_user_id()
    if not user_id:
        return jsonify(ok=True, connections=[])
    conns = (
        SharePointConnection.query.filter_by(user_id=user_id)
        .order_by(SharePointConnection.id.desc())
        .all()
    )
    return jsonify(ok=True, connections=[c.to_dict() for c in conns])


@bp.route("/connections/<conn_id>", methods=["DELETE"])
def delete_connection(conn_id: str):
    user_id = _current_user_id()
    if not user_id:
        return jsonify(error="Unauthorized"), 401

    conn = SharePointConnection.query.filter_by(id=conn_id, user_id=user_id).first()
    if conn:
        db.session.delete(conn)
        db.session.commit()

    conns = (
        SharePointConnection.query.filter_by(user_id=user_id)
        .order_by(SharePointConnection.id.desc())
        .all()
    )
    return jsonify(ok=True, connections=[c.to_dict() for c in conns])


# ---------------------------------------------------------------------------
# Helpers: read sheets via Graph
# ---------------------------------------------------------------------------

def _read_sheet_values(
    drive_id: str,
    item_id: str,
    sheet_name: str,
    bearer: str,
    address: str = "A1:AZ2000",
) -> List[List[Any]]:
    """
    Fetch cell values for a worksheet via Graph.
    We use a big range (A1:AZ2000) because your grids live near top-left.
    """
    payload = read_range(drive_id, item_id, sheet_name, address, bearer)
    values = payload.get("values") or []
    out: List[List[Any]] = []
    for row in values:
        if isinstance(row, list):
            out.append(row)
        else:
            out.append([row])
    return out


def _ordered_sheet_names(all_names: List[str], sheet_hint: Optional[str]) -> List[str]:
    """
    Same priority logic as /excel/upload_and_ingest:
      - if 'sheet_hint' matches a sheet name, process it first
      - else fuzzy match via _normalize_sheet_name
      - then the rest in their original order
    """
    names = list(all_names or [])
    if not names:
        return []

    if not sheet_hint:
        return names

    hint = sheet_hint.strip()
    ordered: List[str] = []

    if hint in names:
        ordered.append(hint)
    else:
        norm_hint = _normalize_sheet_name(hint)
        # exact normalized match
        for n in names:
            if _normalize_sheet_name(n) == norm_hint:
                ordered.append(n)
                break
        # substring fallback
        if not ordered:
            for n in names:
                if norm_hint in _normalize_sheet_name(n):
                    ordered.append(n)
                    break

    for n in names:
        if n not in ordered:
            ordered.append(n)
    return ordered


# ---------------------------------------------------------------------------
# Sync: balance sheets (admin + investor balances)
# ---------------------------------------------------------------------------

@bp.route("/sync_balance_by_url", methods=["POST"])
def sync_balance_by_url():
    """
    Balance Sync from SharePoint workbook.

    Request JSON:
      {
        "url": "<sharepoint sharing link>",
        "sheet": "optional sheet name hint",  // can be empty
        "address": "A1:AZ2000"                // optional, default used if omitted
      }

    Behaviour:
      - Open workbook using the URL
      - Iterate **all worksheets**
      - For each worksheet:
          * read A1:AZ2000
          * classify via _classify_workbook(values)
          * if looks like a BALANCE sheet -> _ingest_new_balance_sheet(values, sheet_name)
      - Collect all results and return aggregated JSON.
      - This **does not require** a sheet literally named "Clarus Balance Sheet".
    """
    data = request.get_json(silent=True) or {}
    share_url = (data.get("url") or "").strip()
    sheet_hint = (data.get("sheet") or "").strip() or None
    address = (data.get("address") or "A1:AZ2000").strip() or "A1:AZ2000"

    if not share_url:
        return jsonify(error="Missing 'url'."), 400

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_share_url(share_url, bearer)
        worksheets = list_worksheets(drive_id, item_id, bearer, _tenant_from_request())
        sheet_names = [w.get("name", "") for w in (worksheets or []) if w.get("name")]

        if not sheet_names:
            return jsonify(error="Workbook has no worksheets."), 400

        ordered_sheets = _ordered_sheet_names(sheet_names, sheet_hint)

        admin_periods_all: set[str] = set()
        balance_results: List[Dict[str, Any]] = []
        file_types_by_sheet: Dict[str, str] = {}
        first_processed_sheet: Optional[str] = None

        for sheet_name in ordered_sheets:
            values = _read_sheet_values(drive_id, item_id, sheet_name, bearer, address)
            if not any(any(c is not None for c in row) for row in values):
                continue

            normalized = _normalize_sheet_name(sheet_name)
            file_type = _classify_workbook(values or [])
            file_types_by_sheet[sheet_name] = file_type

            is_master = normalized == "master"
            is_invest_sheet = normalized in {"investment", "investments"}

            looks_balance = (
                ("bcas" in normalized)
                or ("q4adj" in normalized)
                or (file_type == "balance")
            )
            looks_invest = is_master or is_invest_sheet or (file_type == "investment")

            if file_type == "mixed":
                # mixed sheets: treat Master/Investment as investments, others as balance
                looks_invest = is_master or is_invest_sheet
                looks_balance = not looks_invest

            if not looks_balance:
                continue

            if first_processed_sheet is None:
                first_processed_sheet = sheet_name

            try:
                res = _ingest_new_balance_sheet(values or [], sheet_name)
                balance_results.append(res)
                for p in res.get("admin_periods_upserted", []) or []:
                    admin_periods_all.add(p)
            except Exception as e:
                traceback.print_exc()
                balance_results.append(
                    {
                        "ok": False,
                        "sheet": sheet_name,
                        "error": f"Balance ingest failed: {e}",
                    }
                )

        distinct_types = {t for t in file_types_by_sheet.values() if t}
        if len(distinct_types) == 1:
            top_type = next(iter(distinct_types))
        elif distinct_types:
            top_type = "multi"
        else:
            top_type = "unknown"

        return jsonify(
            {
                "ok": True,
                "sheet": first_processed_sheet,
                "sheets_processed": list(file_types_by_sheet.keys()),
                "file_type": top_type,
                "file_type_by_sheet": file_types_by_sheet,
                "admin_periods_upserted": sorted(admin_periods_all),
                "investor_periods_result": balance_results,
            }
        ), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify(error=f"SharePoint balance sync failed: {e}"), 500


# ---------------------------------------------------------------------------
# Sync: investment valuation sheets (Master / Investment tabs)
# ---------------------------------------------------------------------------

@bp.route("/sync_investments_by_url", methods=["POST"])
def sync_investments_by_url():
    """
    Investment Sync from SharePoint workbook.

    Request JSON:
      {
        "url": "<sharepoint sharing link>",
        "sheet": "optional valuation sheet hint",   // can be empty
        "address": "A1:AZ2000"                      // optional
      }

    Behaviour:
      - Open workbook via URL
      - Iterate ALL worksheets
      - For each:
          * read A1:AZ2000
          * classify via _classify_workbook
          * if looks like INVESTMENT sheet -> _ingest_investments_table(values, sheet_name)
      - No requirement for a sheet literally named "Valuation"; works with "Master",
        "Investment", etc., just like your Excel upload route.
    """
    data = request.get_json(silent=True) or {}
    share_url = (data.get("url") or "").strip()
    sheet_hint = (data.get("sheet") or "").strip() or None
    address = (data.get("address") or "A1:AZ2000").strip() or "A1:AZ2000"

    if not share_url:
        return jsonify(error="Missing 'url'."), 400

    bearer = _bearer_from_request()
    if str(_cfg("GRAPH_AUTH_MODE", "delegated")).lower() == "delegated" and not bearer:
        return jsonify(error="Unauthorized: please sign in with Microsoft."), 401

    try:
        drive_id, item_id = open_excel_by_share_url(share_url, bearer)
        worksheets = list_worksheets(drive_id, item_id, bearer, _tenant_from_request())
        sheet_names = [w.get("name", "") for w in (worksheets or []) if w.get("name")]

        if not sheet_names:
            return jsonify(error="Workbook has no worksheets."), 400

        ordered_sheets = _ordered_sheet_names(sheet_names, sheet_hint)

        investments_results: List[Dict[str, Any]] = []
        file_types_by_sheet: Dict[str, str] = {}
        first_processed_sheet: Optional[str] = None

        # For now we don't create a DataSource row specifically for SharePoint;
        # pass source_id=None and let ingest logic handle it.
        source_id: Optional[int] = None
        preferred_year: Optional[int] = None

        for sheet_name in ordered_sheets:
            values = _read_sheet_values(drive_id, item_id, sheet_name, bearer, address)
            if not any(any(c is not None for c in row) for row in values):
                continue

            normalized = _normalize_sheet_name(sheet_name)
            file_type = _classify_workbook(values or [])
            file_types_by_sheet[sheet_name] = file_type

            is_master = normalized == "master"
            is_invest_sheet = normalized in {"investment", "investments"}

            looks_balance = (
                ("bcas" in normalized)
                or ("q4adj" in normalized)
                or (file_type == "balance")
            )
            looks_invest = is_master or is_invest_sheet or (file_type == "investment")

            if file_type == "mixed":
                looks_invest = is_master or is_invest_sheet
                looks_balance = not looks_invest

            if not looks_invest:
                continue

            if first_processed_sheet is None:
                first_processed_sheet = sheet_name

            try:
                res = _ingest_investments_table(
                    values or [], sheet_name, source_id, preferred_year=preferred_year
                )
                investments_results.append(res)
            except Exception as e:
                traceback.print_exc()
                investments_results.append(
                    {
                        "ok": False,
                        "sheet": sheet_name,
                        "error": f"Investments ingest failed: {e}",
                    }
                )

        distinct_types = {t for t in file_types_by_sheet.values() if t}
        if len(distinct_types) == 1:
            top_type = next(iter(distinct_types))
        elif distinct_types:
            top_type = "multi"
        else:
            top_type = "unknown"

        # For compatibility with your current frontend, we expose a few simple fields.
        total_rows = 0
        for r in investments_results:
            if isinstance(r, dict) and isinstance(r.get("values"), int):
                total_rows += r["values"]

        return jsonify(
            {
                "ok": True,
                "sheet": first_processed_sheet,
                "sheets_processed": list(file_types_by_sheet.keys()),
                "file_type": top_type,
                "file_type_by_sheet": file_types_by_sheet,
                "data_source_id": source_id,
                "investments_result": investments_results,
                "rows": total_rows or None,
            }
        ), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify(error=f"SharePoint investment sync failed: {e}"), 500
