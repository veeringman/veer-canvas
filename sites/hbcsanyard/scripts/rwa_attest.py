"""Free portal attestation for EC-issued PDFs (HMAC + QR verify page).

Not an IT Act digital signature — authenticity for members/banks via the RWA portal.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import pathlib
import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import ensure_document_attestations_table, utc_now

ARTIFACT_TYPES = frozenset({"no_dues", "no_objection", "cash_note"})


def attest_secret() -> bytes:
    raw = (
        os.environ.get("VEERCANVAS_ATTEST_SECRET")
        or os.environ.get("VEERCANVAS_ADMIN_SECRET")
        or os.environ.get("VEER_ADMIN_SECRET")
        or "veercanvas-admin-secret"
    )
    return str(raw).encode("utf-8")


def public_base_url(site_root: pathlib.Path) -> str:
    """HTTPS origin for attest.html links (from site.config.json when present)."""
    cfg_path = pathlib.Path(site_root) / "site.config.json"
    domain = ""
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            domain = str(data.get("domain") or "").strip()
        except (OSError, json.JSONDecodeError, TypeError):
            domain = ""
    if not domain:
        domain = os.environ.get("VEERCANVAS_SITE_DOMAIN", "").strip()
    if domain:
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain.rstrip("/")
        return f"https://{domain}"
    return ""


def new_attestation_id() -> str:
    return f"att_{secrets.token_hex(8)}"


def verify_url_for(site_root: pathlib.Path, attestation_id: str, *, public_base: str | None = None) -> str:
    base = (public_base or "").strip().rstrip("/") or public_base_url(site_root)
    aid = (attestation_id or "").strip()
    if not aid:
        return f"{base}/attest.html" if base else "/attest.html"
    if not base:
        return f"/attest.html?id={aid}"
    return f"{base}/attest.html?id={aid}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_hmac(
    *,
    content_sha256: str,
    artifact_type: str,
    artifact_id: str,
    issuer_house_id: str,
    issued_at: str,
) -> str:
    msg = "|".join(
        [
            (content_sha256 or "").strip().lower(),
            (artifact_type or "").strip(),
            (artifact_id or "").strip(),
            (issuer_house_id or "").strip(),
            (issued_at or "").strip(),
        ]
    )
    return hmac.new(attest_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def qr_png_bytes(url: str, *, box_size: int = 4, border: int = 2) -> bytes | None:
    """Return PNG bytes for a QR code, or None if qrcode is unavailable."""
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(url, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def append_attestation_to_story(
    story: list,
    rl: dict,
    *,
    verify_url: str,
    attestation_id: str,
) -> None:
    """Append a short attestation block (+ QR when possible) to a reportlab story."""
    Paragraph = rl["Paragraph"]
    ParagraphStyle = rl["ParagraphStyle"]
    Spacer = rl["Spacer"]
    Image = rl["Image"]
    colors = rl["colors"]
    mm = rl["mm"]
    styles = rl["getSampleStyleSheet"]()

    foot = ParagraphStyle(
        "attestFoot",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#555555"),
        spaceBefore=6,
        spaceAfter=2,
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "<b>Portal attestation</b> - Digitally attested by HBC Sanyard RWA "
            "(not an IT Act eSign). Verify authenticity on the colony portal:",
            foot,
        )
    )
    safe_url = (
        str(verify_url or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    story.append(Paragraph(f'<link href="{safe_url}">{safe_url}</link>', foot))
    story.append(Paragraph(f"Attestation ID: <b>{attestation_id}</b>", foot))

    png = qr_png_bytes(verify_url) if verify_url else None
    if png:
        try:
            img = Image(io.BytesIO(png), width=28 * mm, height=28 * mm)
            img.hAlign = "LEFT"
            story.append(Spacer(1, 3 * mm))
            story.append(img)
            story.append(Paragraph("Scan to verify", foot))
        except Exception:
            pass


def attestations_dir(site_root: pathlib.Path) -> pathlib.Path:
    path = pathlib.Path(site_root) / "data" / "attestations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_attestation(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    *,
    attestation_id: str,
    artifact_type: str,
    artifact_id: str,
    house_id: str | None,
    issuer_house_id: str | None,
    issued_at: str,
    pdf_bytes: bytes,
    stored_path: str | None,
    filename: str | None,
    commit: bool = True,
) -> dict[str, Any]:
    ensure_document_attestations_table(conn)
    atype = (artifact_type or "").strip()
    if atype not in ARTIFACT_TYPES:
        raise ValueError("Invalid artifact_type")
    aid = (attestation_id or "").strip()
    if not aid:
        raise ValueError("attestation_id required")
    if not pdf_bytes:
        raise ValueError("PDF bytes required")

    content_sha = sha256_hex(pdf_bytes)
    mac = compute_hmac(
        content_sha256=content_sha,
        artifact_type=atype,
        artifact_id=str(artifact_id or ""),
        issuer_house_id=str(issuer_house_id or ""),
        issued_at=str(issued_at or ""),
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO document_attestations(
          id, artifact_type, artifact_id, house_id, issuer_house_id, issued_at,
          content_sha256, hmac_hex, stored_path, filename, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          content_sha256=excluded.content_sha256,
          hmac_hex=excluded.hmac_hex,
          stored_path=excluded.stored_path,
          filename=excluded.filename,
          issued_at=excluded.issued_at
        """,
        (
            aid,
            atype,
            str(artifact_id or ""),
            (house_id or None),
            (issuer_house_id or None),
            issued_at,
            content_sha,
            mac,
            stored_path,
            filename,
            now,
        ),
    )
    if commit:
        conn.commit()
    return {
        "id": aid,
        "artifactType": atype,
        "artifactId": artifact_id,
        "contentSha256": content_sha,
        "verifyUrl": verify_url_for(site_root, aid),
    }


def resolve_stored_file(site_root: pathlib.Path, stored_path: str | None) -> pathlib.Path | None:
    if not stored_path:
        return None
    rel = str(stored_path).lstrip("/")
    if ".." in rel or rel.startswith("/"):
        return None
    path = (pathlib.Path(site_root) / rel).resolve()
    root = pathlib.Path(site_root).resolve()
    if not str(path).startswith(str(root)):
        return None
    return path if path.is_file() else None


def get_attestation(conn: sqlite3.Connection, attestation_id: str) -> dict | None:
    ensure_document_attestations_table(conn)
    aid = (attestation_id or "").strip()
    if not aid:
        return None
    row = conn.execute(
        "SELECT * FROM document_attestations WHERE id = ?",
        (aid,),
    ).fetchone()
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def verify_attestation(
    conn: sqlite3.Connection,
    site_root: pathlib.Path,
    attestation_id: str,
) -> dict[str, Any]:
    """Public-safe verification result."""
    ensure_document_attestations_table(conn)
    row = get_attestation(conn, attestation_id)
    if not row:
        return {
            "ok": True,
            "found": False,
            "valid": False,
            "status": "unknown",
            "message": "No attestation found for this ID",
        }

    expected_mac = compute_hmac(
        content_sha256=row["content_sha256"],
        artifact_type=row["artifact_type"],
        artifact_id=row["artifact_id"],
        issuer_house_id=row["issuer_house_id"] or "",
        issued_at=row["issued_at"] or "",
    )
    seal_ok = hmac.compare_digest(expected_mac, row["hmac_hex"] or "")

    file_path = resolve_stored_file(site_root, row.get("stored_path"))
    tampered = False
    file_present = False
    if file_path:
        file_present = True
        live_sha = sha256_hex(file_path.read_bytes())
        tampered = live_sha.lower() != (row["content_sha256"] or "").lower()

    valid = seal_ok and not tampered
    if not seal_ok:
        status = "invalid_seal"
        message = "Attestation seal does not match — do not trust this record"
    elif tampered:
        status = "tampered"
        message = "Stored PDF no longer matches the attested hash"
    else:
        status = "valid"
        message = (
            "Attestation is valid"
            + (" (file on server matches)" if file_present else " (seal OK; file not re-checked)")
        )

    plot_no = ""
    resident_name = ""
    issuer_name = ""
    issuer_title = ""
    hid = row.get("house_id") or ""
    if hid:
        r = conn.execute(
            "SELECT plot_no, name FROM residents WHERE house_id = ?",
            (hid,),
        ).fetchone()
        if r:
            plot_no = r["plot_no"] or hid
            resident_name = r["name"] or ""
    iid = row.get("issuer_house_id") or ""
    if iid:
        ir = conn.execute(
            "SELECT name, official_title, plot_no FROM residents WHERE house_id = ?",
            (iid,),
        ).fetchone()
        if ir:
            issuer_name = ir["name"] or iid
            issuer_title = ir["official_title"] or ""

    type_labels = {
        "no_dues": "No Dues Certificate",
        "no_objection": "No Objection Certificate",
        "cash_note": "Cash Received Note / Payment Voucher",
    }
    return {
        "ok": True,
        "found": True,
        "valid": valid,
        "status": status,
        "message": message,
        "id": row["id"],
        "artifactType": row["artifact_type"],
        "artifactTypeLabel": type_labels.get(row["artifact_type"], row["artifact_type"]),
        "artifactId": row["artifact_id"],
        "houseId": hid,
        "plotNo": plot_no,
        "residentName": resident_name,
        "issuerHouseId": iid,
        "issuerName": issuer_name,
        "issuerTitle": issuer_title,
        "issuedAt": row["issued_at"],
        "filename": row.get("filename") or "",
        "filePresent": file_present,
        "tampered": tampered,
        "sealOk": seal_ok,
        "disclaimer": (
            "This is a free portal attestation (HMAC). It proves the file was sealed by this "
            "RWA portal; it is not a Class-3 / Aadhaar eSign under the IT Act."
        ),
    }


def safe_rel_path(site_root: pathlib.Path, absolute: pathlib.Path) -> str:
    root = pathlib.Path(site_root).resolve()
    abs_p = absolute.resolve()
    return str(abs_p.relative_to(root)).replace("\\", "/")
