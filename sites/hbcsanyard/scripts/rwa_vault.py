"""Plot Documents Vault — single catalog over receipts, cash notes, No Dues, and uploads.

Files stay in their existing store (receipts / no-dues / attestations / vault/).
The vault table is the index + ACL (private vs shared with EC).
"""

from __future__ import annotations

import pathlib
import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, utc_now
import rwa_entitlements as entitlements

DOC_TYPES = ("receipt", "cash_note", "no_dues", "no_objection", "other")
VISIBILITIES = ("private", "shared_ec")
DOC_STATUSES = ("uploaded", "under_review", "verified", "rejected")
SOURCE_KINDS = ("receipt_file", "no_dues", "no_objection", "attestation", "vault_upload")

DOC_TYPE_LABELS = {
    "receipt": "Payment receipt",
    "cash_note": "Cash note",
    "no_dues": "No Dues certificate",
    "no_objection": "No Objection certificate",
    "other": "Document",
}
STATUS_LABELS = {
    "uploaded": "Uploaded",
    "under_review": "Under review",
    "verified": "Verified",
    "rejected": "Rejected",
}
VISIBILITY_LABELS = {
    "private": "Private",
    "shared_ec": "Shared with EC",
}

VAULT_MAX_BYTES = 5_000_000
VAULT_MAX_FILES = 5


def ensure_vault_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vault_documents (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          doc_type TEXT NOT NULL DEFAULT 'other'
            CHECK(doc_type IN ('receipt','cash_note','no_dues','no_objection','other')),
          title TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '',
          original_name TEXT,
          mime TEXT NOT NULL DEFAULT 'application/octet-stream',
          size_bytes INTEGER NOT NULL DEFAULT 0,
          stored_rel TEXT NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'private'
            CHECK(visibility IN ('private','shared_ec')),
          status TEXT NOT NULL DEFAULT 'uploaded'
            CHECK(status IN ('uploaded','under_review','verified','rejected')),
          source_kind TEXT NOT NULL DEFAULT 'vault_upload'
            CHECK(source_kind IN ('receipt_file','no_dues','no_objection','attestation','vault_upload')),
          source_id TEXT,
          linked_payment_record_id TEXT,
          linked_no_dues_id TEXT,
          linked_no_objection_id TEXT,
          linked_attestation_id TEXT,
          uploaded_by_house_id TEXT,
          uploaded_by_member_id TEXT,
          uploaded_by_role TEXT NOT NULL DEFAULT 'resident',
          verified_by_house_id TEXT,
          verified_at TEXT,
          verify_note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vault_house
          ON vault_documents(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_vault_visibility
          ON vault_documents(visibility, house_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_source
          ON vault_documents(source_kind, source_id)
          WHERE source_id IS NOT NULL AND source_id != '';
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(vault_documents)").fetchall()}
    if cols and "description" not in cols:
        conn.execute("ALTER TABLE vault_documents ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    if cols and "linked_no_objection_id" not in cols:
        conn.execute("ALTER TABLE vault_documents ADD COLUMN linked_no_objection_id TEXT")
    # Expand CHECK constraints when an older table is present.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='vault_documents'"
    ).fetchone()
    ddl = (row[0] if row else "") or ""
    if ddl and "no_objection" not in ddl:
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vault_documents_v2 (
              id TEXT PRIMARY KEY,
              house_id TEXT NOT NULL REFERENCES residents(house_id),
              doc_type TEXT NOT NULL DEFAULT 'other'
                CHECK(doc_type IN ('receipt','cash_note','no_dues','no_objection','other')),
              title TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              original_name TEXT,
              mime TEXT NOT NULL DEFAULT 'application/octet-stream',
              size_bytes INTEGER NOT NULL DEFAULT 0,
              stored_rel TEXT NOT NULL,
              visibility TEXT NOT NULL DEFAULT 'private'
                CHECK(visibility IN ('private','shared_ec')),
              status TEXT NOT NULL DEFAULT 'uploaded'
                CHECK(status IN ('uploaded','under_review','verified','rejected')),
              source_kind TEXT NOT NULL DEFAULT 'vault_upload'
                CHECK(source_kind IN ('receipt_file','no_dues','no_objection','attestation','vault_upload')),
              source_id TEXT,
              linked_payment_record_id TEXT,
              linked_no_dues_id TEXT,
              linked_no_objection_id TEXT,
              linked_attestation_id TEXT,
              uploaded_by_house_id TEXT,
              uploaded_by_member_id TEXT,
              uploaded_by_role TEXT NOT NULL DEFAULT 'resident',
              verified_by_house_id TEXT,
              verified_at TEXT,
              verify_note TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO vault_documents_v2(
              id, house_id, doc_type, title, description, original_name, mime, size_bytes,
              stored_rel, visibility, status, source_kind, source_id,
              linked_payment_record_id, linked_no_dues_id, linked_no_objection_id,
              linked_attestation_id, uploaded_by_house_id, uploaded_by_member_id,
              uploaded_by_role, verified_by_house_id, verified_at, verify_note,
              created_at, updated_at
            )
            SELECT
              id, house_id, doc_type, title, COALESCE(description, ''), original_name, mime, size_bytes,
              stored_rel, visibility, status, source_kind, source_id,
              linked_payment_record_id, linked_no_dues_id, NULL,
              linked_attestation_id, uploaded_by_house_id, uploaded_by_member_id,
              uploaded_by_role, verified_by_house_id, verified_at, verify_note,
              created_at, updated_at
            FROM vault_documents;
            DROP TABLE vault_documents;
            ALTER TABLE vault_documents_v2 RENAME TO vault_documents;
            CREATE INDEX IF NOT EXISTS idx_vault_house
              ON vault_documents(house_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_vault_visibility
              ON vault_documents(visibility, house_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_source
              ON vault_documents(source_kind, source_id)
              WHERE source_id IS NOT NULL AND source_id != '';
            """
        )
        conn.execute("PRAGMA foreign_keys=ON")
    # Unique path index may fail until dedupe_catalog runs — create when possible.
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_stored_rel
              ON vault_documents(stored_rel)
              WHERE stored_rel IS NOT NULL AND stored_rel != ''
            """
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def _status_rank(status: str | None) -> int:
    return {"verified": 4, "under_review": 3, "uploaded": 2, "rejected": 1}.get(status or "", 0)


def _source_rank(source_kind: str | None) -> int:
    # Prefer canonical issued docs over payment receipt copies / ad-hoc uploads.
    return {
        "no_dues": 4,
        "no_objection": 4,
        "attestation": 3,
        "receipt_file": 2,
        "vault_upload": 1,
    }.get(source_kind or "", 0)


def _pick_better_row(a: sqlite3.Row | dict, b: sqlite3.Row | dict) -> sqlite3.Row | dict:
    """Keep the stronger catalog row when collapsing duplicates."""
    a_status = a["status"] if hasattr(a, "keys") else a.get("status")
    b_status = b["status"] if hasattr(b, "keys") else b.get("status")
    if _status_rank(a_status) != _status_rank(b_status):
        return a if _status_rank(a_status) > _status_rank(b_status) else b
    a_src = a["source_kind"] if hasattr(a, "keys") else a.get("source_kind")
    b_src = b["source_kind"] if hasattr(b, "keys") else b.get("source_kind")
    if _source_rank(a_src) != _source_rank(b_src):
        return a if _source_rank(a_src) > _source_rank(b_src) else b
    a_at = a["created_at"] if hasattr(a, "keys") else a.get("created_at") or ""
    b_at = b["created_at"] if hasattr(b, "keys") else b.get("created_at") or ""
    return a if str(a_at) >= str(b_at) else b


def remove_receipt_catalog(
    conn: sqlite3.Connection,
    *,
    record_id: str | None = None,
    file_ids: list[str] | None = None,
    commit: bool = False,
) -> int:
    """Drop vault catalog rows for payment receipt files (before replace/reindex)."""
    ensure_vault_tables(conn)
    deleted = 0
    ids = [fid for fid in (file_ids or []) if fid]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"""
            DELETE FROM vault_documents
            WHERE source_kind = 'receipt_file' AND source_id IN ({placeholders})
            """,
            ids,
        )
        deleted += cur.rowcount or 0
    rid = (record_id or "").strip()
    if rid:
        cur = conn.execute(
            """
            DELETE FROM vault_documents
            WHERE source_kind = 'receipt_file' AND linked_payment_record_id = ?
            """,
            (rid,),
        )
        deleted += cur.rowcount or 0
    if commit:
        conn.commit()
    return deleted


def dedupe_catalog(conn: sqlite3.Connection) -> int:
    """One-shot cleanup: orphans, same-file dupes, cash-note receipt copies."""
    ensure_vault_tables(conn)
    flagged = conn.execute(
        "SELECT value FROM meta WHERE key = 'vault_dedupe_v1'"
    ).fetchone()
    if flagged:
        return 0

    removed = 0
    # Orphan receipt catalog rows (file row gone).
    orphans = conn.execute(
        """
        SELECT v.id FROM vault_documents v
        LEFT JOIN payment_receipt_files f ON f.id = v.source_id
        WHERE v.source_kind = 'receipt_file' AND f.id IS NULL
        """
    ).fetchall()
    for row in orphans:
        conn.execute("DELETE FROM vault_documents WHERE id = ?", (row["id"],))
        removed += 1

    # Same stored path must appear once.
    rel_groups = conn.execute(
        """
        SELECT stored_rel FROM vault_documents
        WHERE stored_rel IS NOT NULL AND stored_rel != ''
        GROUP BY stored_rel HAVING COUNT(*) > 1
        """
    ).fetchall()
    for g in rel_groups:
        rows = conn.execute(
            "SELECT * FROM vault_documents WHERE stored_rel = ? ORDER BY created_at DESC",
            (g["stored_rel"],),
        ).fetchall()
        keep = rows[0]
        for row in rows[1:]:
            keep = _pick_better_row(keep, row)
        keep_id = keep["id"]
        for row in rows:
            if row["id"] == keep_id:
                continue
            # Preserve useful links onto the survivor.
            conn.execute(
                """
                UPDATE vault_documents SET
                  linked_payment_record_id = COALESCE(linked_payment_record_id, ?),
                  linked_no_dues_id = COALESCE(linked_no_dues_id, ?),
                  linked_attestation_id = COALESCE(linked_attestation_id, ?),
                  description = CASE
                    WHEN description IS NULL OR description = '' THEN ?
                    ELSE description
                  END,
                  updated_at = ?
                WHERE id = ?
                """,
                (
                    row["linked_payment_record_id"],
                    row["linked_no_dues_id"],
                    row["linked_attestation_id"],
                    row["description"] or "",
                    utc_now(),
                    keep_id,
                ),
            )
            conn.execute("DELETE FROM vault_documents WHERE id = ?", (row["id"],))
            removed += 1

    # Cash payment receipt copies when an attested cash note already exists for the plot.
    cash_receipts = conn.execute(
        """
        SELECT v.id, v.house_id, v.linked_payment_record_id
        FROM vault_documents v
        JOIN payment_records pr ON pr.id = v.linked_payment_record_id
        WHERE v.source_kind = 'receipt_file'
          AND lower(COALESCE(pr.method, '')) = 'cash'
        """
    ).fetchall()
    for row in cash_receipts:
        note = conn.execute(
            """
            SELECT id FROM vault_documents
            WHERE house_id = ?
              AND source_kind = 'attestation'
              AND doc_type = 'cash_note'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (row["house_id"],),
        ).fetchone()
        if not note:
            continue
        conn.execute(
            """
            UPDATE vault_documents SET
              linked_payment_record_id = COALESCE(linked_payment_record_id, ?),
              updated_at = ?
            WHERE id = ?
            """,
            (row["linked_payment_record_id"], utc_now(), note["id"]),
        )
        conn.execute("DELETE FROM vault_documents WHERE id = ?", (row["id"],))
        removed += 1

    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('vault_dedupe_v1', ?)",
        (utc_now(),),
    )
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_stored_rel
              ON vault_documents(stored_rel)
              WHERE stored_rel IS NOT NULL AND stored_rel != ''
            """
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return removed


def vault_root(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "vault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_house(house_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", (house_id or "").strip()) or "_"


def _safe_name(name: str, fallback: str = "document.bin") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", (name or "").strip()) or fallback
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError("Invalid filename")
    return cleaned


def resolve_stored_file(site_root: pathlib.Path, stored_rel: str) -> pathlib.Path:
    root = pathlib.Path(site_root).resolve()
    rel = (stored_rel or "").lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        raise ValueError("Invalid stored path")
    path = (root / rel).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("Invalid stored path")
    return path


def _rel_path(site_root: pathlib.Path, absolute: pathlib.Path) -> str:
    root = pathlib.Path(site_root).resolve()
    path = absolute.resolve()
    return str(path.relative_to(root)).replace("\\", "/")


def can_browse_ec_shared(actor: dict) -> bool:
    if actor.get("superAdmin"):
        return True
    if entitlements.actor_has(actor, "manage_dues") or entitlements.actor_has(actor, "treasury"):
        return True
    if entitlements.actor_has(actor, "issue_no_dues"):
        return True
    if entitlements.actor_has(actor, "issue_no_objection"):
        return True
    return entitlements.is_ec_member(actor)


def can_verify_docs(actor: dict) -> bool:
    if actor.get("superAdmin"):
        return True
    return entitlements.actor_has(actor, "manage_dues") or entitlements.actor_has(actor, "treasury")


def can_view_doc(actor: dict, doc: dict) -> bool:
    if actor.get("superAdmin"):
        return True
    own = (actor.get("houseId") or actor.get("house_id") or "") == (doc.get("houseId") or "")
    if own:
        return True
    if (doc.get("visibility") or "") == "shared_ec" and can_browse_ec_shared(actor):
        return True
    return False


def can_upload_for_house(actor: dict, house_id: str) -> bool:
    if actor.get("viewOnly"):
        return False
    if actor.get("superAdmin") or entitlements.actor_has(actor, "manage_dues"):
        return True
    return (actor.get("houseId") or actor.get("house_id") or "") == house_id


def can_delete_doc(actor: dict, doc: dict) -> bool:
    """Rejected or newly uploaded (not yet verified) docs can be removed."""
    if actor.get("viewOnly"):
        return False
    if not can_upload_for_house(actor, doc.get("houseId") or ""):
        return False
    status = doc.get("status") or ""
    source = doc.get("sourceKind") or ""
    if status == "verified":
        return False
    # Issued certificates stay unless rejected in vault review.
    if source in ("no_dues", "no_objection", "attestation") and status != "rejected":
        return False
    return status in ("uploaded", "under_review", "rejected")


def public_doc(row: sqlite3.Row | dict, *, actor: dict | None = None) -> dict:
    data = {k: row[k] for k in row.keys()} if hasattr(row, "keys") else dict(row)
    doc_type = data.get("doc_type") or "other"
    status = data.get("status") or "uploaded"
    visibility = data.get("visibility") or "private"
    vid = data.get("id")
    out = {
        "id": vid,
        "houseId": data.get("house_id"),
        "docType": doc_type,
        "docTypeLabel": DOC_TYPE_LABELS.get(doc_type, doc_type),
        "title": data.get("title") or data.get("original_name") or "Document",
        "description": data.get("description") or "",
        "originalName": data.get("original_name") or "",
        "mime": data.get("mime") or "application/octet-stream",
        "sizeBytes": int(data.get("size_bytes") or 0),
        "visibility": visibility,
        "visibilityLabel": VISIBILITY_LABELS.get(visibility, visibility),
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status),
        "sourceKind": data.get("source_kind") or "",
        "sourceId": data.get("source_id") or "",
        "linkedPaymentRecordId": data.get("linked_payment_record_id") or "",
        "linkedNoDuesId": data.get("linked_no_dues_id") or "",
        "linkedNoObjectionId": data.get("linked_no_objection_id") or "",
        "linkedAttestationId": data.get("linked_attestation_id") or "",
        "uploadedByHouseId": data.get("uploaded_by_house_id") or "",
        "uploadedByRole": data.get("uploaded_by_role") or "",
        "verifiedByHouseId": data.get("verified_by_house_id") or "",
        "verifiedAt": data.get("verified_at") or "",
        "verifyNote": data.get("verify_note") or "",
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
        "downloadUrl": f"/api/rwa/vault/{vid}/file" if vid else None,
        "isImage": str(data.get("mime") or "").startswith("image/"),
        "isPdf": str(data.get("mime") or "") == "application/pdf"
        or str(data.get("original_name") or "").lower().endswith(".pdf"),
    }
    # Distinguish re-issued certificates that share a default filename.
    if doc_type == "no_dues":
        sid = (out["sourceId"] or out["linkedNoDuesId"] or "")[-6:]
        label = out["statusLabel"]
        base = (out["title"] or "No Dues certificate").strip()
        if sid and sid not in base:
            out["title"] = f"No Dues · {label}" + (f" ({sid})" if sid else "")
    if doc_type == "no_objection":
        sid = (out["sourceId"] or out["linkedNoObjectionId"] or "")[-6:]
        label = out["statusLabel"]
        base = (out["title"] or "No Objection certificate").strip()
        if sid and sid not in base:
            out["title"] = f"No Objection · {label}" + (f" ({sid})" if sid else "")
    if actor is not None:
        out["canDelete"] = can_delete_doc(actor, out)
    return out



def get_doc(conn: sqlite3.Connection, doc_id: str, *, actor: dict | None = None) -> dict | None:
    ensure_vault_tables(conn)
    row = conn.execute("SELECT * FROM vault_documents WHERE id = ?", ((doc_id or "").strip(),)).fetchone()
    return public_doc(row, actor=actor) if row else None


def get_doc_row(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row | None:
    ensure_vault_tables(conn)
    return conn.execute("SELECT * FROM vault_documents WHERE id = ?", ((doc_id or "").strip(),)).fetchone()


def list_docs(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    actor: dict,
) -> list[dict]:
    ensure_vault_tables(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        return []
    rows = conn.execute(
        """
        SELECT * FROM vault_documents
        WHERE house_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (hid,),
    ).fetchall()
    # Collapse same-file rows and cash-note receipt twins defensively.
    by_rel: dict[str, sqlite3.Row] = {}
    cash_note_houses: set[str] = set()
    for row in rows:
        if (row["source_kind"] or "") == "attestation" and (row["doc_type"] or "") == "cash_note":
            cash_note_houses.add(row["house_id"] or "")
        rel = (row["stored_rel"] or "").strip() or f"id:{row['id']}"
        prev = by_rel.get(rel)
        by_rel[rel] = row if prev is None else _pick_better_row(prev, row)  # type: ignore[assignment]

    out = []
    seen_ids: set[str] = set()
    for row in by_rel.values():
        if row["id"] in seen_ids:
            continue
        if (
            (row["source_kind"] or "") == "receipt_file"
            and (row["house_id"] or "") in cash_note_houses
            and row["linked_payment_record_id"]
        ):
            pay = conn.execute(
                "SELECT method FROM payment_records WHERE id = ?",
                (row["linked_payment_record_id"],),
            ).fetchone()
            if pay and str(pay["method"] or "").lower() == "cash":
                continue
        doc = public_doc(row, actor=actor)
        if can_view_doc(actor, doc):
            seen_ids.add(row["id"])
            out.append(doc)
    out.sort(key=lambda d: (d.get("createdAt") or "", d.get("id") or ""), reverse=True)
    return out


def _upsert_catalog(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    doc_type: str,
    title: str,
    original_name: str,
    mime: str,
    size_bytes: int,
    stored_rel: str,
    visibility: str,
    status: str,
    source_kind: str,
    source_id: str,
    description: str = "",
    linked_payment_record_id: str | None = None,
    linked_no_dues_id: str | None = None,
    linked_no_objection_id: str | None = None,
    linked_attestation_id: str | None = None,
    uploaded_by_house_id: str | None = None,
    uploaded_by_member_id: str | None = None,
    uploaded_by_role: str = "resident",
    commit: bool = True,
) -> dict:
    ensure_vault_tables(conn)
    now = utc_now()
    desc = (description or "").strip()[:1000]
    existing = None
    if source_id:
        existing = conn.execute(
            """
            SELECT id FROM vault_documents
            WHERE source_kind = ? AND source_id = ?
            """,
            (source_kind, source_id),
        ).fetchone()
    if not existing and stored_rel:
        existing = conn.execute(
            """
            SELECT id FROM vault_documents
            WHERE stored_rel = ?
            """,
            (stored_rel,),
        ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE vault_documents SET
              house_id = ?, doc_type = ?, title = ?, description = ?, original_name = ?, mime = ?,
              size_bytes = ?, stored_rel = ?, visibility = ?, status = ?,
              linked_payment_record_id = COALESCE(?, linked_payment_record_id),
              linked_no_dues_id = COALESCE(?, linked_no_dues_id),
              linked_no_objection_id = COALESCE(?, linked_no_objection_id),
              linked_attestation_id = COALESCE(?, linked_attestation_id),
              updated_at = ?
            WHERE id = ?
            """,
            (
                house_id,
                doc_type,
                (title or "")[:200],
                desc,
                (original_name or "")[:200] or None,
                mime or "application/octet-stream",
                int(size_bytes or 0),
                stored_rel,
                visibility if visibility in VISIBILITIES else "private",
                status if status in DOC_STATUSES else "uploaded",
                linked_payment_record_id,
                linked_no_dues_id,
                linked_no_objection_id,
                linked_attestation_id,
                now,
                existing["id"],
            ),
        )
        vid = existing["id"]
    else:
        vid = f"vd_{secrets.token_hex(8)}"
        conn.execute(
            """
            INSERT INTO vault_documents(
              id, house_id, doc_type, title, description, original_name, mime, size_bytes, stored_rel,
              visibility, status, source_kind, source_id,
              linked_payment_record_id, linked_no_dues_id, linked_no_objection_id, linked_attestation_id,
              uploaded_by_house_id, uploaded_by_member_id, uploaded_by_role,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vid,
                house_id,
                doc_type if doc_type in DOC_TYPES else "other",
                (title or "")[:200],
                desc,
                (original_name or "")[:200] or None,
                mime or "application/octet-stream",
                int(size_bytes or 0),
                stored_rel,
                visibility if visibility in VISIBILITIES else "private",
                status if status in DOC_STATUSES else "uploaded",
                source_kind if source_kind in SOURCE_KINDS else "vault_upload",
                source_id,
                linked_payment_record_id,
                linked_no_dues_id,
                linked_no_objection_id,
                linked_attestation_id,
                uploaded_by_house_id,
                uploaded_by_member_id,
                uploaded_by_role or "resident",
                now,
                now,
            ),
        )
    if commit:
        conn.commit()
    out = get_doc(conn, vid)
    if not out:
        raise ValueError("Vault document missing after save")
    return out


def index_receipt_file(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    record_id: str,
    file_id: str,
    filename: str,
    original_name: str,
    mime: str,
    size_bytes: int,
    title: str = "",
    description: str = "",
    uploaded_by_house_id: str | None = None,
    uploaded_by_member_id: str | None = None,
    uploaded_by_role: str = "resident",
    commit: bool = True,
) -> dict:
    import rwa_payments

    path = rwa_payments.receipt_file_path(site_root, house_id, record_id, filename)
    stored_rel = _rel_path(site_root, path)
    title_bit = (title or "").strip() or original_name or filename or "Payment receipt"

    # Cash note PDF is already catalogued as an attestation — link payment, don't add a twin.
    pay = conn.execute(
        "SELECT method FROM payment_records WHERE id = ?",
        (record_id,),
    ).fetchone()
    if pay and str(pay["method"] or "").lower() == "cash":
        note = conn.execute(
            """
            SELECT id FROM vault_documents
            WHERE house_id = ?
              AND source_kind = 'attestation'
              AND doc_type = 'cash_note'
              AND (
                linked_payment_record_id IS NULL
                OR linked_payment_record_id = ''
                OR linked_payment_record_id = ?
              )
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (house_id, record_id),
        ).fetchone()
        if note:
            conn.execute(
                """
                UPDATE vault_documents SET
                  linked_payment_record_id = ?,
                  title = CASE WHEN ? != '' THEN ? ELSE title END,
                  description = CASE WHEN ? != '' THEN ? ELSE description END,
                  updated_at = ?
                WHERE id = ?
                """,
                (
                    record_id,
                    title_bit,
                    title_bit[:200],
                    (description or "").strip()[:1000],
                    (description or "").strip()[:1000],
                    utc_now(),
                    note["id"],
                ),
            )
            if commit:
                conn.commit()
            out = get_doc(conn, note["id"])
            if out:
                return out

    return _upsert_catalog(
        conn,
        house_id=house_id,
        doc_type="receipt",
        title=title_bit,
        description=description or "",
        original_name=original_name or filename,
        mime=mime,
        size_bytes=size_bytes,
        stored_rel=stored_rel,
        visibility="shared_ec",
        status="under_review",
        source_kind="receipt_file",
        source_id=file_id,
        linked_payment_record_id=record_id,
        uploaded_by_house_id=uploaded_by_house_id,
        uploaded_by_member_id=uploaded_by_member_id,
        uploaded_by_role=uploaded_by_role,
        commit=commit,
    )


def index_no_dues_certificate(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    request_id: str,
    filename: str,
    original_name: str,
    attestation_id: str | None = None,
    uploaded_by_house_id: str | None = None,
    commit: bool = True,
) -> dict | None:
    import rwa_no_dues

    if not filename:
        return None
    path = rwa_no_dues.certificate_path(site_root, house_id, request_id, filename)
    if not path.is_file():
        return None
    return _upsert_catalog(
        conn,
        house_id=house_id,
        doc_type="no_dues",
        title=original_name or "No Dues certificate",
        original_name=original_name or filename,
        mime="application/pdf",
        size_bytes=path.stat().st_size,
        stored_rel=_rel_path(site_root, path),
        visibility="shared_ec",
        status="under_review",
        source_kind="no_dues",
        source_id=request_id,
        linked_no_dues_id=request_id,
        linked_attestation_id=attestation_id,
        uploaded_by_house_id=uploaded_by_house_id,
        uploaded_by_role="ec",
        commit=commit,
    )


def index_no_objection_certificate(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    request_id: str,
    filename: str,
    original_name: str,
    attestation_id: str | None = None,
    uploaded_by_house_id: str | None = None,
    commit: bool = True,
) -> dict | None:
    import rwa_no_objection

    if not filename:
        return None
    path = rwa_no_objection.certificate_path(site_root, house_id, request_id, filename)
    if not path.is_file():
        return None
    return _upsert_catalog(
        conn,
        house_id=house_id,
        doc_type="no_objection",
        title=original_name or "No Objection certificate",
        original_name=original_name or filename,
        mime="application/pdf",
        size_bytes=path.stat().st_size,
        stored_rel=_rel_path(site_root, path),
        visibility="shared_ec",
        status="under_review",
        source_kind="no_objection",
        source_id=request_id,
        linked_no_objection_id=request_id,
        linked_attestation_id=attestation_id,
        uploaded_by_house_id=uploaded_by_house_id,
        uploaded_by_role="ec",
        commit=commit,
    )


def index_attestation(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    attestation_id: str,
    artifact_type: str,
    house_id: str,
    stored_path: str,
    filename: str,
    uploaded_by_house_id: str | None = None,
    commit: bool = True,
) -> dict | None:
    path = resolve_stored_file(site_root, stored_path)
    if not path.is_file():
        return None
    if artifact_type == "cash_note":
        doc_type = "cash_note"
    elif artifact_type == "no_dues":
        doc_type = "no_dues"
    elif artifact_type == "no_objection":
        doc_type = "no_objection"
    else:
        doc_type = "other"
    # Certificates already indexed via request id when issued; skip duplicate path-only row.
    if artifact_type in ("no_dues", "no_objection"):
        return None
    return _upsert_catalog(
        conn,
        house_id=house_id,
        doc_type=doc_type,
        title=filename or DOC_TYPE_LABELS.get(doc_type, "Document"),
        original_name=filename or "",
        mime="application/pdf",
        size_bytes=path.stat().st_size,
        stored_rel=stored_path,
        visibility="shared_ec",
        status="uploaded",
        source_kind="attestation",
        source_id=attestation_id,
        linked_attestation_id=attestation_id,
        uploaded_by_house_id=uploaded_by_house_id,
        uploaded_by_role="ec",
        commit=commit,
    )


def upload_direct(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    house_id: str,
    files: list[tuple[bytes, str, str]],
    actor: dict,
    title: str = "",
    description: str = "",
    doc_type: str = "other",
    share_with_ec: bool = False,
) -> list[dict]:
    """Resident/EC direct vault upload (canonical files under data/vault/)."""
    import rwa_payments

    ensure_vault_tables(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        raise ValueError("Valid plot is required")
    if not files:
        raise ValueError("At least one file is required")
    if len(files) > VAULT_MAX_FILES:
        raise ValueError(f"At most {VAULT_MAX_FILES} files at once")

    role = "resident"
    if actor.get("superAdmin") or entitlements.actor_has(actor, "manage_dues"):
        role = "ec"
    visibility = "shared_ec" if (share_with_ec or role == "ec") else "private"
    status = "under_review" if visibility == "shared_ec" else "uploaded"
    dtype = doc_type if doc_type in DOC_TYPES else "other"
    desc = (description or "").strip()[:1000]
    title_base = (title or "").strip()[:200]

    out: list[dict] = []
    now = utc_now()
    for raw, content_type, original_name in files:
        if len(raw) > VAULT_MAX_BYTES:
            raise ValueError(f"{original_name or 'File'} exceeds 5 MB")
        data, mime, ext, _w, _h = rwa_payments._save_upload_bytes(raw, content_type, original_name)
        vid = f"vd_{secrets.token_hex(8)}"
        filename = f"doc_{vid[3:]}.{ext}"
        dest_dir = vault_root(site_root) / _safe_house(hid) / vid
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / filename
        path.write_bytes(data)
        stored_rel = _rel_path(site_root, path)
        conn.execute(
            """
            INSERT INTO vault_documents(
              id, house_id, doc_type, title, description, original_name, mime, size_bytes, stored_rel,
              visibility, status, source_kind, source_id,
              uploaded_by_house_id, uploaded_by_member_id, uploaded_by_role,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'vault_upload', ?, ?, ?, ?, ?, ?)
            """,
            (
                vid,
                hid,
                dtype,
                title_base or (original_name or filename)[:200],
                desc,
                (original_name or filename)[:200],
                mime,
                len(data),
                stored_rel,
                visibility,
                status,
                vid,
                actor.get("houseId") or actor.get("house_id"),
                actor.get("memberId") or actor.get("member_id"),
                role,
                now,
                now,
            ),
        )
        doc = get_doc(conn, vid, actor=actor)
        if doc:
            out.append(doc)
    conn.commit()
    return out


def delete_document(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    doc_id: str,
    *,
    actor: dict,
) -> dict:
    """Delete rejected or newly uploaded vault docs (and vault_upload files)."""
    import shutil

    import rwa_payments

    row = get_doc_row(conn, doc_id)
    if not row:
        raise ValueError("Document not found")
    doc = public_doc(row, actor=actor)
    if not can_delete_doc(actor, doc):
        raise PermissionError("Only rejected or newly uploaded documents can be deleted")

    source = row["source_kind"] or ""
    # Remove on-disk vault upload
    if source == "vault_upload":
        try:
            path = resolve_stored_file(site_root, row["stored_rel"])
            if path.is_file():
                shutil.rmtree(path.parent, ignore_errors=True)
        except Exception:
            pass
    elif source == "receipt_file":
        # Remove receipt file row + disk; leave payment record for EC to clean if empty.
        fid = row["source_id"] or ""
        rec_id = row["linked_payment_record_id"] or ""
        house_id = row["house_id"]
        filename = None
        fr = conn.execute(
            "SELECT filename FROM payment_receipt_files WHERE id = ?",
            (fid,),
        ).fetchone()
        if fr:
            filename = fr["filename"]
            conn.execute("DELETE FROM payment_receipt_files WHERE id = ?", (fid,))
        if filename and rec_id:
            try:
                path = rwa_payments.receipt_file_path(site_root, house_id, rec_id, filename)
                if path.is_file():
                    path.unlink()
            except Exception:
                pass

    conn.execute("DELETE FROM vault_documents WHERE id = ?", (doc_id,))
    conn.commit()
    return {"ok": True, "deletedId": doc_id}


def set_visibility(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: dict,
    visibility: str,
) -> dict:
    row = get_doc_row(conn, doc_id)
    if not row:
        raise ValueError("Document not found")
    doc = public_doc(row)
    own = (actor.get("houseId") or "") == doc["houseId"]
    if not own and not actor.get("superAdmin") and not entitlements.actor_has(actor, "manage_dues"):
        raise PermissionError("Only the plot owner or dues desk can change sharing")
    if visibility not in VISIBILITIES:
        raise ValueError("Invalid visibility")
    status = row["status"]
    if visibility == "shared_ec" and status == "uploaded":
        status = "under_review"
    conn.execute(
        """
        UPDATE vault_documents
        SET visibility = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (visibility, status, utc_now(), doc_id),
    )
    conn.commit()
    out = get_doc(conn, doc_id)
    if not out:
        raise ValueError("Document not found")
    return out


def set_verify_status(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: dict,
    status: str,
    note: str = "",
) -> dict:
    if not can_verify_docs(actor):
        raise PermissionError("Not allowed to verify vault documents")
    if status not in ("verified", "rejected", "under_review"):
        raise ValueError("Invalid verify status")
    note_text = (note or "").strip()[:500] or None
    if status == "rejected":
        import rwa_treasury

        note_text = rwa_treasury.require_rejection_reason(note)
    row = get_doc_row(conn, doc_id)
    if not row:
        raise ValueError("Document not found")
    doc = public_doc(row)
    if not can_view_doc(actor, doc):
        raise PermissionError("Document is not shared with EC")
    now = utc_now()
    conn.execute(
        """
        UPDATE vault_documents
        SET status = ?,
            verified_by_house_id = ?,
            verified_at = ?,
            verify_note = ?,
            visibility = 'shared_ec',
            updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            actor.get("houseId") or actor.get("house_id"),
            now if status in ("verified", "rejected") else None,
            note_text,
            now,
            doc_id,
        ),
    )
    conn.commit()
    out = get_doc(conn, doc_id)
    if not out:
        raise ValueError("Document not found")
    return out


def vault_context(
    conn: sqlite3.Connection,
    *,
    house_id: str,
    actor: dict,
) -> dict:
    """Bundle docs + related payment/ledger/no-dues status for the vault panel."""
    import rwa_payments
    import rwa_no_dues
    import rwa_treasury

    hid = (house_id or "").strip()
    docs = list_docs(conn, house_id=hid, actor=actor)
    resident = conn.execute(
        "SELECT house_id, plot_no, name FROM residents WHERE house_id = ?",
        (hid,),
    ).fetchone()
    ledger = None
    payment_row = conn.execute(
        """
        SELECT pr.*
        FROM payment_rows pr
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.house_id = ?
        ORDER BY pl.as_of DESC, pl.id DESC
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if payment_row:
        ledger = {
            "houseId": hid,
            **rwa_treasury.treasury_fields_from_row(payment_row),
        }

    can_dues = entitlements.actor_has(actor, "manage_dues") or bool(actor.get("superAdmin"))
    can_treasury = entitlements.actor_has(actor, "treasury") or bool(actor.get("superAdmin"))
    records = []
    if can_dues or (actor.get("houseId") or "") == hid:
        records = rwa_payments.list_records(conn, house_id=hid, limit=40)

    no_dues = []
    no_objection = []
    own_or_issuer = (
        can_dues
        or entitlements.actor_has(actor, "issue_no_dues")
        or entitlements.actor_has(actor, "issue_no_objection")
        or (actor.get("houseId") or "") == hid
        or bool(actor.get("superAdmin"))
    )
    if own_or_issuer:
        import rwa_no_objection

        rows = conn.execute(
            "SELECT * FROM no_dues_requests WHERE house_id = ? ORDER BY created_at DESC LIMIT 20",
            (hid,),
        ).fetchall()
        no_dues = [rwa_no_dues.public_request(conn, r) for r in rows]
        rows = conn.execute(
            "SELECT * FROM no_objection_requests WHERE house_id = ? ORDER BY created_at DESC LIMIT 20",
            (hid,),
        ).fetchall()
        no_objection = [rwa_no_objection.public_request(conn, r) for r in rows]

    return {
        "ok": True,
        "houseId": hid,
        "plotNo": (resident["plot_no"] if resident else None) or hid,
        "residentName": (resident["name"] if resident else "") or "",
        "documents": docs,
        "ledger": ledger,
        "paymentRecords": records,
        "noDues": no_dues,
        "noObjection": no_objection,
        "capabilities": {
            "canUpload": can_upload_for_house(actor, hid),
            "canShare": (actor.get("houseId") or "") == hid or can_dues,
            "canVerify": can_verify_docs(actor),
            "canTreasury": can_treasury,
            "canManageDues": can_dues,
        },
    }


def backfill_from_existing(conn: sqlite3.Connection, site_root: pathlib.Path) -> int:
    """Index existing receipt files, No Dues PDFs, and cash-note attestations (no file copies)."""
    ensure_vault_tables(conn)
    flagged = conn.execute(
        "SELECT value FROM meta WHERE key = 'vault_backfill_v1'"
    ).fetchone()
    if flagged:
        return 0

    added = 0
    import rwa_payments

    rows = conn.execute(
        """
        SELECT f.*, pr.house_id, pr.uploaded_by_house_id, pr.uploaded_by_member_id, pr.uploaded_by_role
        FROM payment_receipt_files f
        JOIN payment_records pr ON pr.id = f.record_id
        """
    ).fetchall()
    for r in rows:
        try:
            index_receipt_file(
                conn,
                site_root,
                house_id=r["house_id"],
                record_id=r["record_id"],
                file_id=r["id"],
                filename=r["filename"],
                original_name=r["original_name"] or r["filename"],
                mime=r["mime"],
                size_bytes=int(r["size_bytes"] or 0),
                uploaded_by_house_id=r["uploaded_by_house_id"],
                uploaded_by_member_id=r["uploaded_by_member_id"],
                uploaded_by_role=r["uploaded_by_role"] or "resident",
                commit=False,
            )
            added += 1
        except Exception:
            continue

    nd_rows = conn.execute(
        """
        SELECT id, house_id, filename, original_name, reviewed_by_house_id
        FROM no_dues_requests
        WHERE status = 'issued' AND filename IS NOT NULL AND filename != ''
        """
    ).fetchall()
    for r in nd_rows:
        try:
            if index_no_dues_certificate(
                conn,
                site_root,
                house_id=r["house_id"],
                request_id=r["id"],
                filename=r["filename"],
                original_name=r["original_name"] or r["filename"],
                uploaded_by_house_id=r["reviewed_by_house_id"],
                commit=False,
            ):
                added += 1
        except Exception:
            continue

    try:
        noc_rows = conn.execute(
            """
            SELECT id, house_id, filename, original_name, reviewed_by_house_id
            FROM no_objection_requests
            WHERE status = 'issued' AND filename IS NOT NULL AND filename != ''
            """
        ).fetchall()
        for r in noc_rows:
            try:
                if index_no_objection_certificate(
                    conn,
                    site_root,
                    house_id=r["house_id"],
                    request_id=r["id"],
                    filename=r["filename"],
                    original_name=r["original_name"] or r["filename"],
                    uploaded_by_house_id=r["reviewed_by_house_id"],
                    commit=False,
                ):
                    added += 1
            except Exception:
                continue
    except sqlite3.OperationalError:
        pass

    att_rows = conn.execute(
        """
        SELECT id, artifact_type, house_id, stored_path, filename, issuer_house_id
        FROM document_attestations
        WHERE artifact_type = 'cash_note'
        """
    ).fetchall()
    for r in att_rows:
        try:
            if index_attestation(
                conn,
                site_root,
                attestation_id=r["id"],
                artifact_type=r["artifact_type"],
                house_id=r["house_id"],
                stored_path=r["stored_path"],
                filename=r["filename"] or f"{r['id']}.pdf",
                uploaded_by_house_id=r["issuer_house_id"],
                commit=False,
            ):
                added += 1
        except Exception:
            continue

    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('vault_backfill_v1', ?)",
        (utc_now(),),
    )
    conn.commit()
    return added
