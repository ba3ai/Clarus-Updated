# backend/routes/documents_routes.py
import os, mimetypes, json, time, hmac, hashlib, base64
from flask import (
    Blueprint,
    request,
    jsonify,
    current_app,
    send_from_directory,
    send_file,
    url_for,
    abort,
)
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user

from backend.extensions import db
from backend.models import (
    User,
    Investor,
    Document,
    DocumentShare,
    DocumentFolder,
    DocumentFolderShare,
)
from sqlalchemy import or_

documents_bp = Blueprint("documents", __name__)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _ensure_upload_dir():
    """
    Resolve the physical directory where document files are stored.

    Priority:
      1) Environment variable UPLOAD_DOCS_DIR (if set)
      2) Azure App Service persistent path: /home/site/data/docs
      3) Local fallback: <app_root>/uploads/docs
    """
    # 1) Explicit override (works both locally and in Azure)
    upload_dir = os.getenv("UPLOAD_DOCS_DIR")

    if not upload_dir:
        # 2) Azure App Service: /home/site/data is the persisted volume
        azure_base = "////home/site/data"
        if os.path.isdir(azure_base) or os.getenv("WEBSITE_SITE_NAME"):
            upload_dir = os.path.join(azure_base, "docs")
        else:
            # 3) Local dev fallback
            upload_dir = os.path.join(
                current_app.root_path, "uploads", "docs"
            )

    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir



def _is_admin() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and str(getattr(current_user, "user_type", "")).lower() == "admin"
    )


def _get_folder_or_404(folder_id: int):
    folder = DocumentFolder.query.get(int(folder_id))
    if not folder:
        abort(404, description="Folder not found.")
    return folder


def _ensure_admin():
    if not _is_admin():
        abort(403, description="Admins only.")


def _is_group_admin() -> bool:
    """
    Detect "Group Admin" investors.

    Mirrors the frontend normalization which strips whitespace and lowercases
    the user_type (e.g. "Group Admin" -> "groupadmin").
    """
    if not getattr(current_user, "is_authenticated", False):
        return False
    user_type = str(getattr(current_user, "user_type", "") or "")
    norm = "".join(ch for ch in user_type.lower() if not ch.isspace())
    return norm.startswith("groupadmin")


def _authed_user_id():
    if (
        getattr(current_user, "is_authenticated", False)
        and getattr(current_user, "id", None) is not None
    ):
        try:
            return int(current_user.id)
        except Exception:
            return current_user.id
    return None


def _view_as_investor_id() -> int | None:
    """
    For admin users, read the X-View-As-Investor header (set by the
    admin dashboard when 'viewing as' a specific investor).
    """
    raw = request.headers.get("X-View-As-Investor") or ""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _is_admin_or_shared(doc_id: int) -> bool:
    """
    Access control for downloads / previews.

    - Admins and Group Admins are treated as having full access (frontend
      restricts which investor they can "view as").
    - Otherwise, only users listed in DocumentShare for this doc_id may access.
    """
    if _is_admin() or _is_group_admin():
        return True
    uid = _authed_user_id()
    if not uid:
        return False
    return (
        db.session.query(DocumentShare.id)
        .filter_by(document_id=doc_id, investor_user_id=uid)
        .first()
        is not None
    )


def _to_int_list(values):
    """Coerce a string/array of ids into a list of ints."""
    if values is None:
        return []
    if isinstance(values, (list, tuple)):
        raw = values
    else:
        s = str(values).strip()
        if not s:
            return []
        raw = json.loads(s) if s.startswith("[") else [x for x in s.split(",")]
    out = []
    for x in raw:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


def _resolve_user_ids(raw_ids):
    """
    Accept ids that might be user.id OR investor.id.
    Return a de-duplicated list of user.id suitable for DocumentShare.investor_user_id.
    """
    ids = _to_int_list(raw_ids)
    if not ids:
        return []

    users = User.query.with_entities(User.id).filter(User.id.in_(ids)).all()
    user_ids = {u.id for u in users}

    remaining = set(ids) - user_ids
    if remaining:
        linked = (
            Investor.query.with_entities(Investor.account_user_id)
            .filter(
                Investor.id.in_(remaining),
                Investor.account_user_id.isnot(None),
            )
            .all()
        )
        user_ids.update(int(row[0]) for row in linked if row and row[0])

    # de-dupe but preserve order
    return list(dict.fromkeys(user_ids))


def _label_from_user(first_name, last_name, email, fallback):
    name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip()
    return name or (email or fallback)


def _label_for_user_id(user_id: int):
    """
    Build a human label and email for a user id, preferring:
    1) User first + last
    2) Linked Investor.name
    3) User email
    4) 'User {id}'
    """
    row = (
        db.session.query(
            User.first_name,
            User.last_name,
            User.email,
            Investor.name.label("investor_name"),
        )
        .outerjoin(Investor, Investor.account_user_id == User.id)
        .filter(User.id == int(user_id))
        .first()
    )
    if not row:
        return {"label": f"User {user_id}", "email": None}
    name = f"{(row.first_name or '').strip()} {(row.last_name or '').strip()}".strip()
    if not name:
        name = (row.investor_name or "").strip()
    if not name:
        name = row.email or f"User {user_id}"
    return {"label": name, "email": row.email}


def _serialize(doc: Document):
    # include human-readable labels for shares
    shares = []
    for s in doc.shares:
        meta = _label_for_user_id(s.investor_user_id)
        shares.append(
            {
                "investor_user_id": s.investor_user_id,
                "shared_at": s.shared_at.isoformat(),
                "label": meta.get("label"),
                "email": meta.get("email"),
                # NEW: document vs statement
                "share_type": getattr(s, "share_type", "document"),
            }
        )

    folder = getattr(doc, "folder", None)
    return {
        "id": doc.id,
        "title": doc.title,
        "original_name": doc.original_name,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "uploaded_at": doc.uploaded_at.isoformat(),
        "shares": shares,
        "folder_id": doc.folder_id,
        "folder_name": folder.name if folder else None,
    }


def _serialize_folder(folder: DocumentFolder, include_doc_count: bool = False):
    data = {
        "id": folder.id,
        "name": folder.name,
        # new: parent_id for nested folders (use getattr so it won't crash
        # if the column is temporarily missing)
        "parent_id": getattr(folder, "parent_id", None),
        "created_at": folder.created_at.isoformat()
        if getattr(folder, "created_at", None)
        else None,
    }
    if include_doc_count:
        data["doc_count"] = len(folder.documents or [])
    return data


def _unique_filename(directory: str, requested_name: str) -> str:
    """
    Store with the (sanitized) original name, adding ' (1)', ' (2)'… before
    the extension to avoid overwrites.
    """
    base = secure_filename(requested_name) or "upload"
    name, ext = os.path.splitext(base)
    candidate = base
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{name} ({counter}){ext}"
        counter += 1
    return candidate

# ─────────────────────────────────────────────────────────────
# HMAC preview signing (short-lived public links)
# ─────────────────────────────────────────────────────────────
def _preview_secret() -> bytes:
    return (current_app.config.get("PREVIEW_SECRET") or "change-me").encode()


def _preview_ttl() -> int:
    # seconds; default 5 minutes
    return int(current_app.config.get("PREVIEW_TTL", 300))


def _sign_public_url(abs_path_no_query: str, ttl_sec: int | None = None) -> str:
    exp = int(time.time()) + int(ttl_sec or _preview_ttl())
    msg = f"{abs_path_no_query}|{exp}".encode()
    sig = (
        base64.urlsafe_b64encode(
            hmac.new(_preview_secret(), msg, hashlib.sha256).digest()
        )
        .decode()
        .rstrip("=")
    )
    return f"{abs_path_no_query}?exp={exp}&sig={sig}"


def _validate_sig(base_url_no_query: str, exp: int, sig: str) -> bool:
    try:
        if exp < int(time.time()):
            return False
        msg = f"{base_url_no_query}|{exp}".encode()
        want = (
            base64.urlsafe_b64encode(
                hmac.new(_preview_secret(), msg, hashlib.sha256).digest()
            )
            .decode()
            .rstrip("=")
        )
        return hmac.compare_digest(want, sig or "")
    except Exception:
        return False

# ─────────────────────────────────────────────────────────────
# Role-based share options
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/documents/share-options")
@login_required
def share_options():
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    role = (request.args.get("role") or "").strip().lower()
    options = []

    if role == "admin":
        rows = (
            User.query.with_entities(
                User.id, User.first_name, User.last_name, User.email
            )
            .filter(User.user_type == "admin")
            .order_by(User.first_name.asc(), User.last_name.asc())
            .all()
        )
        for u in rows:
            options.append(
                {
                    "user_id": u.id,
                    "label": _label_from_user(
                        u.first_name, u.last_name, u.email, f"User {u.id}"
                    ),
                    "email": u.email,
                    "investor_id": None,
                }
            )

    elif role == "group_admin":
        rows = (
            User.query.with_entities(
                User.id, User.first_name, User.last_name, User.email
            )
            .filter(User.user_type == "group_admin")
            .order_by(User.first_name.asc(), User.last_name.asc())
            .all()
        )
        for u in rows:
            options.append(
                {
                    "user_id": u.id,
                    "label": _label_from_user(
                        u.first_name, u.last_name, u.email, f"User {u.id}"
                    ),
                    "email": u.email,
                    "investor_id": None,
                }
            )

    elif role == "investor":
        linked_rows = (
            db.session.query(
                Investor.id.label("investor_id"),
                Investor.name.label("investor_name"),
                Investor.email.label("investor_email"),
                Investor.account_user_id.label("user_id"),
                User.first_name,
                User.last_name,
                User.email,
            )
            .join(User, User.id == Investor.account_user_id)
            .order_by(Investor.name.asc())
            .all()
        )
        seen_user_ids = set()
        for r in linked_rows:
            label = (
                f"{(r.first_name or '').strip()} {(r.last_name or '').strip()}".strip()
                or (r.investor_name or "")
                or (r.email or r.investor_email or "")
                or f"User {r.user_id}"
            )
            options.append(
                {
                    "user_id": r.user_id,
                    "investor_id": r.investor_id,
                    "label": label,
                    "email": r.email or r.investor_email,
                }
            )
            seen_user_ids.add(r.user_id)

        more_users = (
            User.query.with_entities(
                User.id, User.first_name, User.last_name, User.email
            )
            .filter(User.user_type == "investor", ~User.id.in_(seen_user_ids))
            .order_by(User.first_name.asc(), User.last_name.asc())
            .all()
        )
        for u in more_users:
            options.append(
                {
                    "user_id": u.id,
                    "investor_id": None,
                    "label": _label_from_user(
                        u.first_name, u.last_name, u.email, f"User {u.id}"
                    ),
                    "email": u.email,
                }
            )
    else:
        return jsonify(error="Unknown role. Use admin | group_admin | investor."), 400

    return jsonify(ok=True, options=options)

# ─────────────────────────────────────────────────────────────
# Folders
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/document-folders")
@login_required
def list_document_folders():
    """
    List folders for both admins and investors.

    - Admins: see all folders; when include_counts=1, doc_count is the total
      number of documents in each folder.

    - Non-admins (investors / group admins): also see all folders so that
      folder structure matches the admin’s. However, doc_count (when requested)
      counts only the documents in that folder that are actually shared with
      this logged-in user.

    This way:
      * Admin does NOT need to share a folder explicitly.
      * As soon as a file in a folder is shared with an investor, it appears
        under that same folder in the investor’s Documents view.
    """
    include_counts = bool(request.args.get("include_counts"))

    # Everyone sees the global folder list
    folders = DocumentFolder.query.order_by(DocumentFolder.name.asc()).all()

    user_is_admin = _is_admin()
    user_id_for_counts = None

    if not user_is_admin:
        # For investors / group-admins, we count only docs shared to them.
        user_id_for_counts = _authed_user_id()

    # If counts are not requested, just serialize and return.
    if not include_counts:
        return jsonify(
            ok=True,
            folders=[_serialize_folder(f, include_doc_count=False) for f in folders],
        )

    # We need doc_count per folder.
    # Start with base serialization (no counts yet).
    payload_by_id = {
        f.id: _serialize_folder(f, include_doc_count=False) for f in folders
    }

    if user_is_admin or user_id_for_counts is None:
        # Admin: doc_count = total number of docs in each folder.
        for f in folders:
            payload_by_id[f.id]["doc_count"] = len(f.documents or [])
    else:
        # Investor / group admin: doc_count = number of docs in this folder
        # shared with *this* user.
        rows = (
            db.session.query(Document.folder_id, db.func.count(Document.id))
            .join(DocumentShare, DocumentShare.document_id == Document.id)
            .filter(
                DocumentShare.investor_user_id == int(user_id_for_counts),
                Document.folder_id.isnot(None),
            )
            .group_by(Document.folder_id)
            .all()
        )
        counts = {folder_id: int(cnt) for folder_id, cnt in rows}
        for f in folders:
            payload_by_id[f.id]["doc_count"] = counts.get(f.id, 0)

    return jsonify(ok=True, folders=list(payload_by_id.values()))


@documents_bp.post("/api/document-folders")
@login_required
def create_document_folder():
    """Create a new folder (optionally inside a parent folder)."""
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(error="Folder name is required."), 400

    # Optional parent folder (for nested structure)
    parent_id_raw = data.get("parent_id", None)
    parent = None
    if parent_id_raw not in (None, "", 0, "0"):
        try:
            parent_id = int(parent_id_raw)
        except (TypeError, ValueError):
            return jsonify(error="parent_id must be an integer or null."), 400
        parent = DocumentFolder.query.get(parent_id)
        if not parent:
            return jsonify(error="Parent folder not found."), 404

    folder = DocumentFolder(
        name=name,
        parent_id=parent.id if parent is not None else None,
        created_by_user_id=int(_authed_user_id() or 0),
    )
    db.session.add(folder)
    db.session.commit()
    return jsonify(ok=True, folder=_serialize_folder(folder))



@documents_bp.post("/api/document-folders/share")
@login_required
def share_document_folder():
    """
    Share a folder with one or more investors.

    This:
      * creates DocumentFolderShare rows
      * also ensures all existing documents in the folder have DocumentShare
        rows for the same investors, so investors can actually see files.
    """
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    data = request.get_json(silent=True) or {}
    folder_id = int(data.get("folder_id") or 0)
    raw_ids = (
        [data["investor_id"]]
        if data.get("investor_id")
        else (data.get("investor_ids") or [])
    )
    resolved_user_ids = _resolve_user_ids(raw_ids)

    if not folder_id or not resolved_user_ids:
        return (
            jsonify(error="folder_id and investor_id(s) are required."),
            400,
        )

    folder = DocumentFolder.query.get(folder_id)
    if not folder:
        return jsonify(error="Folder not found."), 404

    # 1) Folder-level shares
    existing_folder_users = {
        s.investor_user_id for s in (folder.shares or [])
    }
    for uid in resolved_user_ids:
        if int(uid) not in existing_folder_users:
            db.session.add(
                DocumentFolderShare(
                    folder_id=folder.id,
                    investor_user_id=int(uid),
                )
            )

    # 2) Propagate to all documents inside the folder
    for doc in folder.documents or []:
        existing_doc_users = {s.investor_user_id for s in (doc.shares or [])}
        for uid in resolved_user_ids:
            if int(uid) not in existing_doc_users:
                db.session.add(
                    DocumentShare(
                        document_id=doc.id,
                        investor_user_id=int(uid),
                    )
                )

    db.session.commit()
    return jsonify(ok=True)

# ─────────────────────────────────────────────────────────────
# Upload (stores using the original filename, made unique)
# ─────────────────────────────────────────────────────────────
@documents_bp.post("/api/documents/upload")
@login_required
def upload_document():
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    file = request.files.get("file")
    if not file:
        return jsonify(error="No file provided."), 400

    title = (request.form.get("title") or "").strip() or None

    # Optional folder_id for this upload
    raw_folder = (request.form.get("folder_id") or "").strip()
    folder_id = None
    if raw_folder:
        try:
            folder_id = int(raw_folder)
        except Exception:
            return jsonify(error="folder_id must be an integer."), 400

    raw_single = request.form.get("investor_id")
    raw_multi = request.form.get("investor_ids")
    raw_ids = [raw_single] if raw_single else _to_int_list(raw_multi)
    resolved_user_ids = _resolve_user_ids(raw_ids)

    upload_dir = _ensure_upload_dir()

    # Use sanitized original filename, ensure uniqueness on disk
    original = secure_filename(file.filename or "upload.bin")
    stored = _unique_filename(upload_dir, original)

    mime = (
        file.mimetype
        or mimetypes.guess_type(original)[0]
        or "application/octet-stream"
    )
    path = os.path.join(upload_dir, stored)
    file.save(path)
    size = os.path.getsize(path)

    doc = Document(
        title=title or os.path.splitext(original)[0],
        original_name=original,  # uploaded name
        stored_name=stored,  # on-disk name (original or "original (n).ext")
        mime_type=mime,
        size_bytes=size,
        uploaded_by_user_id=int(_authed_user_id() or 0),
        folder_id=folder_id,
    )
    db.session.add(doc)
    db.session.flush()

    # If document is placed in a folder, also share with everyone who has
    # access to that folder.
    folder_share_user_ids = []
    if folder_id:
        folder = DocumentFolder.query.get(folder_id)
        if folder:
            folder_share_user_ids = [
                s.investor_user_id for s in (folder.shares or [])
            ]

    all_share_ids = list(
        dict.fromkeys(list(resolved_user_ids) + folder_share_user_ids)
    )

    for uid in all_share_ids:
        db.session.add(
            DocumentShare(
                document_id=doc.id,
                investor_user_id=int(uid),
            )
        )

    db.session.commit()
    return jsonify(ok=True, document=_serialize(doc))

# ─────────────────────────────────────────────────────────────
# List documents
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# List documents
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/documents")
@login_required
def list_documents():
    """
    - Normal investor user: documents shared with *their* user id.
    - Admin:
        * with X-View-As-Investor or ?investor_id: docs shared with that investor's user
        * otherwise: all documents
    - Group Admin:
        * without investor_id: docs shared with their own user
        * with investor_id: docs shared with that investor's user (My Group child view)

    Extra:
      - share_type=document   (default) -> normal Documents section
      - share_type=statement           -> docs shared specifically "for statements"
    """
    user_is_admin = _is_admin()
    user_is_group_admin = _is_group_admin()
    investor_id_param = request.args.get("investor_id", type=int)
    folder_id_param = request.args.get("folder_id", type=int)
    share_type_param = (request.args.get("share_type") or "").strip().lower()

    def _apply_folder_filter(q):
        if folder_id_param is not None:
            q = q.filter(Document.folder_id == folder_id_param)
        return q

    # For views that join DocumentShare (investor / group admin / admin-view-as),
    # decide which share_type we want:
    #   - "document" (default)  => normal Documents tab
    #   - "statement"           => only statement-linked docs
    def _apply_share_type_filter(q):
        if share_type_param == "statement":
            return q.filter(DocumentShare.share_type == "statement")
        # default: treat as "document"
        return q.filter(
            or_(
                DocumentShare.share_type == "document",
                DocumentShare.share_type.is_(None),
            )
        )

    if user_is_admin:
        view_as_id = _view_as_investor_id() or investor_id_param
        if view_as_id:
            inv = Investor.query.get(view_as_id)
            if not inv or not inv.account_user_id:
                docs = []
            else:
                uid = int(inv.account_user_id)
                q = (
                    Document.query.join(DocumentShare)
                    .filter(DocumentShare.investor_user_id == uid)
                )
                q = _apply_share_type_filter(q)
                q = _apply_folder_filter(q)
                docs = q.order_by(Document.uploaded_at.desc()).all()
        else:
            # Admin management view: see all documents regardless of share_type
            q = Document.query
            q = _apply_folder_filter(q)
            docs = q.order_by(Document.uploaded_at.desc()).all()

    elif user_is_group_admin:
        if investor_id_param:
            inv = Investor.query.get(investor_id_param)
            if not inv or not inv.account_user_id:
                docs = []
            else:
                uid = int(inv.account_user_id)
                q = (
                    Document.query.join(DocumentShare)
                    .filter(DocumentShare.investor_user_id == uid)
                )
                q = _apply_share_type_filter(q)
                q = _apply_folder_filter(q)
                docs = q.order_by(Document.uploaded_at.desc()).all()
        else:
            uid = _authed_user_id()
            if uid is None:
                return jsonify(ok=True, documents=[])
            q = (
                Document.query.join(DocumentShare)
                .filter(DocumentShare.investor_user_id == uid)
            )
            q = _apply_share_type_filter(q)
            q = _apply_folder_filter(q)
            docs = q.order_by(Document.uploaded_at.desc()).all()

    else:
        uid = _authed_user_id()
        if uid is None:
            return jsonify(ok=True, documents=[])
        q = (
            Document.query.join(DocumentShare)
            .filter(DocumentShare.investor_user_id == uid)
        )
        q = _apply_share_type_filter(q)
        q = _apply_folder_filter(q)
        docs = q.order_by(Document.uploaded_at.desc()).all()

    return jsonify(ok=True, documents=[_serialize(d) for d in docs])


# ─────────────────────────────────────────────────────────────
# Share / Revoke
# ─────────────────────────────────────────────────────────────
@documents_bp.post("/api/documents/share")
@login_required
def share_document():
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    data = request.get_json(silent=True) or {}
    doc_id = int(data.get("document_id") or 0)
    raw_ids = (
        [data["investor_id"]]
        if data.get("investor_id")
        else (data.get("investor_ids") or [])
    )
    resolved_user_ids = _resolve_user_ids(raw_ids)

    # NEW: "Document" vs "Statement" destination for investors
    # (admin/group_admin sharing will always be treated as "document")
    share_target = (data.get("share_target") or "document").strip().lower()
    if share_target not in ("document", "statement"):
        share_target = "document"

    if not doc_id or not resolved_user_ids:
        return (
            jsonify(error="document_id and investor_id(s) are required."),
            400,
        )

    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Document not found."), 404

    # Existing shares keyed by investor_user_id so we can update share_type
    existing_by_user = {
        s.investor_user_id: s
        for s in (doc.shares or [])
    }

    for uid in resolved_user_ids:
        uid = int(uid)
        share = existing_by_user.get(uid)
        if share:
            # already shared; just update where it should appear
            share.share_type = share_target
        else:
            db.session.add(
                DocumentShare(
                    document_id=doc.id,
                    investor_user_id=uid,
                    share_type=share_target,
                )
            )

    db.session.commit()
    return jsonify(ok=True, document=_serialize(doc))



@documents_bp.delete("/api/documents/share")
@login_required
def revoke_share():
    if not _is_admin():
        return jsonify(error="Admins only."), 403
    data = request.get_json(silent=True) or {}
    doc_id = int(data.get("document_id") or 0)
    investor_id = int(data.get("investor_id") or 0)
    if not doc_id or not investor_id:
        return (
            jsonify(error="document_id and investor_id are required."),
            400,
        )
    DocumentShare.query.filter_by(
        document_id=doc_id, investor_user_id=investor_id
    ).delete()
    db.session.commit()
    return jsonify(ok=True)

# ─────────────────────────────────────────────────────────────
# Download (Admin or shared user)
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/documents/download/<int:doc_id>")
@login_required
def download_document(doc_id: int):
    if not _is_admin_or_shared(doc_id):
        return jsonify(error="Not authorized."), 403
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Not found."), 404
    upload_dir = _ensure_upload_dir()
    return send_from_directory(
        upload_dir,
        doc.stored_name,  # equals original or original (n).ext
        download_name=doc.original_name,  # preserve uploader name
        mimetype=doc.mime_type,
        as_attachment=True,
    )

# ─────────────────────────────────────────────────────────────
# Inline view (authenticated) – handy for quick previews
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/documents/view/<int:doc_id>")
@login_required
def view_document(doc_id: int):
    if not _is_admin_or_shared(doc_id):
        return jsonify(error="Not authorized."), 403
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Not found."), 404
    upload_dir = _ensure_upload_dir()
    path = os.path.join(upload_dir, doc.stored_name)
    if not os.path.exists(path):
        return jsonify(error="File missing on server."), 404
    return send_file(path, mimetype=doc.mime_type or "application/octet-stream")

# ─────────────────────────────────────────────────────────────
# Signed preview URL (for cloud viewers)
# ─────────────────────────────────────────────────────────────
@documents_bp.get("/api/documents/preview-url/<int:doc_id>")
@login_required
def preview_url_document(doc_id: int):
    if not _is_admin_or_shared(doc_id):
        return jsonify(error="Not authorized."), 403
    abs_path = url_for(
        "documents.public_download_document", doc_id=doc_id, _external=True
    )
    return jsonify({"url": _sign_public_url(abs_path)})


@documents_bp.get("/api/documents/public-download/<int:doc_id>")
def public_download_document(doc_id: int):
    exp = int(request.args.get("exp", "0") or 0)
    sig = request.args.get("sig", "") or ""
    base_no_query = request.base_url
    if not _validate_sig(base_no_query, exp, sig):
        return abort(403)

    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Not found."), 404

    upload_dir = _ensure_upload_dir()
    path = os.path.join(upload_dir, doc.stored_name or "")
    if not os.path.exists(path):
        return jsonify(error="File missing on server."), 404

    return send_file(
        path,
        mimetype=doc.mime_type or "application/octet-stream",
        as_attachment=False,
        download_name=doc.original_name,
        max_age=_preview_ttl(),
        conditional=True,
        etag=True,
        last_modified=doc.uploaded_at,
    )

# ─────────────────────────────────────────────────────────────
# Delete document (admin only). Removes shares, file, row
# ─────────────────────────────────────────────────────────────
@documents_bp.delete("/api/documents/<int:doc_id>")
@login_required
def delete_document(doc_id: int):
    if not _is_admin():
        return jsonify(error="Admins only."), 403
    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Not found."), 404

    upload_dir = _ensure_upload_dir()
    path = os.path.join(upload_dir, doc.stored_name or "")
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    DocumentShare.query.filter_by(document_id=doc.id).delete()
    db.session.delete(doc)
    db.session.commit()
    return jsonify(ok=True)


@documents_bp.route("/api/document-folders/<int:folder_id>", methods=["PATCH"])
@login_required
def rename_document_folder(folder_id):
    """
    Update a document folder.

    Body may contain:
      - "name": new folder name
      - "parent_id": new parent folder id (or null / empty for top level)

    Either field (or both) can be sent.
    """
    _ensure_admin()
    folder = _get_folder_or_404(folder_id)

    data = request.get_json(silent=True) or {}

    changed = False

    # ── Rename ──────────────────────────────────────────────────────────────
    if "name" in data:
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify(error="Folder name is required."), 400

        if new_name != folder.name:
            # Optional uniqueness check (case-insensitive)
            existing = (
                DocumentFolder.query.filter(
                    DocumentFolder.id != folder.id,
                    db.func.lower(DocumentFolder.name) == new_name.lower(),
                )
                .first()
            )
            if existing:
                return (
                    jsonify(
                        error="A folder with this name already exists."
                    ),
                    409,
                )

            folder.name = new_name
            changed = True

    # ── Move (change parent folder) ────────────────────────────────────────
    if "parent_id" in data:
        parent_raw = data.get("parent_id")
        parent = None
        if parent_raw not in (None, "", 0, "0"):
            try:
                parent_id = int(parent_raw)
            except (TypeError, ValueError):
                return jsonify(
                    error="parent_id must be an integer or null."
                ), 400

            parent = DocumentFolder.query.get(parent_id)
            if not parent:
                return jsonify(error="Destination folder not found."), 404

            # Prevent moving into itself or one of its descendants
            cur = parent
            while cur is not None:
                if cur.id == folder.id:
                    return (
                        jsonify(
                            error=(
                                "Cannot move a folder inside itself or "
                                "one of its subfolders."
                            )
                        ),
                        400,
                    )
                # Walk up using parent_id to avoid needing an explicit relationship
                pid = getattr(cur, "parent_id", None)
                cur = (
                    DocumentFolder.query.get(pid)
                    if pid is not None
                    else None
                )
        new_parent_id = parent.id if parent is not None else None

        if getattr(folder, "parent_id", None) != new_parent_id:
            folder.parent_id = new_parent_id
            changed = True

    if not changed:
        return jsonify(error="No changes requested."), 400

    db.session.commit()

    return jsonify(
        ok=True,
        folder=_serialize_folder(folder, include_doc_count=False),
    )


@documents_bp.route("/api/document-folders/<int:folder_id>", methods=["DELETE"])
@login_required
def delete_document_folder(folder_id):
    """
    Delete a folder. Documents are kept, but their folder_id is set to NULL.
    """
    _ensure_admin()
    folder = _get_folder_or_404(folder_id)

    # Move documents out of this folder (keep files)
    docs = Document.query.filter_by(folder_id=folder.id).all()
    for doc in docs:
        doc.folder_id = None

    db.session.delete(folder)
    db.session.commit()

    return jsonify(ok=True)



# ─────────────────────────────────────────────────────────────
# Update document (admin only) – move to folder / change title
# ─────────────────────────────────────────────────────────────
@documents_bp.route("/api/documents/<int:doc_id>", methods=["PATCH"])
@login_required
def update_document(doc_id: int):
    """
    Update document metadata.

    Supported fields:
      - "folder_id": move file into a folder (or null / empty for top level)
      - "title": optional custom title
    """
    if not _is_admin():
        return jsonify(error="Admins only."), 403

    doc = Document.query.get(doc_id)
    if not doc:
        return jsonify(error="Not found."), 404

    data = request.get_json(silent=True) or {}
    changed = False

    # Change title
    if "title" in data:
        new_title = (data.get("title") or "").strip() or None
        if new_title != doc.title:
            doc.title = new_title
            changed = True

    # Move to folder
    if "folder_id" in data:
        folder_raw = data.get("folder_id")
        folder = None
        if folder_raw not in (None, "", 0, "0"):
            try:
                folder_id = int(folder_raw)
            except (TypeError, ValueError):
                return jsonify(
                    error="folder_id must be an integer or null."
                ), 400

            folder = DocumentFolder.query.get(folder_id)
            if not folder:
                return jsonify(error="Destination folder not found."), 404

        new_folder_id = folder.id if folder is not None else None
        if doc.folder_id != new_folder_id:
            doc.folder_id = new_folder_id
            changed = True

    if not changed:
        return jsonify(error="No fields to update."), 400

    db.session.commit()
    # Re-use existing serializer
    return jsonify(ok=True, document=_serialize(doc))
