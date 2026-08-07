"""Fine-grained EC desk entitlements.

Roles (nested):
  Resident → EC Member → Office Bearer → EC Admin

- EC Admin and Office Bearer are always EC Members.
- EC Members (and office bearers) may receive one-off grantable entitlements.
- EC Admins get all entitlements implicitly; sensitive_ops is EC-Admin-only.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, ensure_entitlements_schema, utc_now
from rwa_household import primary_member_photo_map

ENTITLEMENT_DEFS: list[dict[str, str]] = [
    {"id": "manage_roster", "label": "Resident roster", "description": "View and edit plot contacts"},
    {"id": "manage_dues", "label": "Dues ledger", "description": "View and curate colony dues"},
    {"id": "manage_notices", "label": "Notices", "description": "Publish and manage notices"},
    {"id": "manage_concerns", "label": "Concerns mailbox", "description": "Respond to resident concerns"},
    {"id": "manage_info", "label": "Info centre", "description": "Manage documents"},
    {"id": "manage_works", "label": "Works & events", "description": "Manage colony works"},
    {"id": "manage_bank", "label": "Bank / UPI", "description": "Update collection account"},
    {"id": "generate_reports", "label": "Reports", "description": "Generate PDF reports"},
    {"id": "manage_roles", "label": "Roles & entitlements", "description": "Designate EC members / office bearers, elevate EC Admin, grant access (EC Admin / sensitive ops only)"},
    {"id": "sensitive_ops", "label": "Sensitive ops", "description": "Roles, revision history, and ledger import (EC Admin only)"},
]

EC_ADMIN_ONLY_ENTITLEMENTS = frozenset({"sensitive_ops", "manage_roles"})
GRANTABLE_ENTITLEMENTS = frozenset(
    e["id"] for e in ENTITLEMENT_DEFS if e["id"] not in EC_ADMIN_ONLY_ENTITLEMENTS
)
ALL_ENTITLEMENTS = frozenset(e["id"] for e in ENTITLEMENT_DEFS)
EC_ADMIN_ENTITLEMENTS = frozenset(ALL_ENTITLEMENTS)


def entitlements_meta() -> dict:
    return {
        "entitlements": ENTITLEMENT_DEFS,
        "grantable": sorted(GRANTABLE_ENTITLEMENTS),
        "ecAdminOnly": sorted(EC_ADMIN_ONLY_ENTITLEMENTS),
        "roles": [
            {"id": "ec_member", "label": "EC Member", "description": "Committee member; may receive one-off entitlements"},
            {"id": "office_bearer", "label": "Office Bearer", "description": "Titled post; always an EC Member"},
            {"id": "ec_admin", "label": "EC Admin", "description": "Full desk access; must be an Office Bearer"},
        ],
    }


def ensure_ready(conn: sqlite3.Connection) -> None:
    ensure_entitlements_schema(conn)


def _is_super(actor: dict | None) -> bool:
    if not actor:
        return False
    return bool(actor.get("superAdmin")) or str(actor.get("houseId") or "") == SUPERADMIN_HOUSE_ID


def is_ec_admin(actor: dict | None) -> bool:
    if not actor:
        return False
    if _is_super(actor):
        return True
    return (actor.get("role") or "") == "admin"


def is_ec_member(actor: dict | None) -> bool:
    if not actor:
        return False
    if _is_super(actor) or is_ec_admin(actor):
        return True
    if actor.get("isEcMember") is not None:
        return bool(actor.get("isEcMember"))
    if actor.get("isOfficeBearer"):
        return True
    return bool(str(actor.get("officialTitle") or "").strip())


def is_office_bearer(actor: dict | None) -> bool:
    if not actor:
        return False
    if _is_super(actor):
        return True
    if actor.get("isOfficeBearer") is not None:
        return bool(actor.get("isOfficeBearer"))
    return bool(str(actor.get("officialTitle") or "").strip()) or is_ec_admin(actor)


def load_grants(conn: sqlite3.Connection, house_id: str) -> list[str]:
    ensure_ready(conn)
    hid = (house_id or "").strip()
    if not hid:
        return []
    rows = conn.execute(
        "SELECT entitlement FROM resident_entitlements WHERE house_id = ? ORDER BY entitlement",
        (hid,),
    ).fetchall()
    out = []
    for r in rows:
        key = r["entitlement"] if hasattr(r, "keys") else r[0]
        if key in GRANTABLE_ENTITLEMENTS:
            out.append(key)
    return out


def entitlements_for_actor(conn: sqlite3.Connection, actor: dict | None) -> list[str]:
    if not actor:
        return []
    if _is_super(actor):
        return sorted(EC_ADMIN_ENTITLEMENTS)
    if actor.get("viewOnly") or actor.get("isPrimary") is False:
        return []
    if (actor.get("role") or "") == "admin":
        return sorted(EC_ADMIN_ENTITLEMENTS)
    if not is_ec_member(actor):
        return []
    return load_grants(conn, actor.get("houseId") or "")


def enrich_actor(conn: sqlite3.Connection, actor: dict) -> dict:
    ensure_ready(conn)
    hid = actor.get("houseId") or ""
    super_admin = _is_super(actor)
    if hid and hid != SUPERADMIN_HOUSE_ID:
        row = conn.execute(
            """
            SELECT is_ec_member, is_office_bearer, official_title, role
            FROM residents WHERE house_id = ?
            """,
            (hid,),
        ).fetchone()
        if row:
            is_ob = bool(int(row["is_office_bearer"] or 0)) or bool(str(row["official_title"] or "").strip()) or (
                (row["role"] or "") == "admin"
            )
            is_mem = bool(int(row["is_ec_member"] or 0)) or is_ob or (row["role"] or "") == "admin"
            actor["isOfficeBearer"] = is_ob or super_admin
            actor["isEcMember"] = is_mem or super_admin
        else:
            actor["isOfficeBearer"] = super_admin or bool(str(actor.get("officialTitle") or "").strip()) or (
                actor.get("role") == "admin"
            )
            actor["isEcMember"] = actor["isOfficeBearer"] or bool(actor.get("isEcMember"))
    else:
        actor["isOfficeBearer"] = True
        actor["isEcMember"] = True

    actor["isEcAdmin"] = is_ec_admin(actor) and not actor.get("viewOnly") and actor.get("isPrimary") is not False
    if actor.get("viewOnly") or actor.get("isPrimary") is False:
        actor["isEcAdmin"] = False
        actor["entitlements"] = []
        return actor
    actor["entitlements"] = entitlements_for_actor(conn, actor)
    return actor


def actor_has(actor: dict | None, key: str) -> bool:
    if not actor or key not in ALL_ENTITLEMENTS:
        return False
    if _is_super(actor):
        return True
    if actor.get("viewOnly") or actor.get("isPrimary") is False:
        return False
    ents = actor.get("entitlements")
    if isinstance(ents, list):
        return key in ents
    if (actor.get("role") or "") == "admin":
        return True
    return False


def actor_can_open_ec_desk(actor: dict | None) -> bool:
    if not actor:
        return False
    if _is_super(actor):
        return True
    if actor.get("viewOnly") or actor.get("isPrimary") is False:
        return False
    if (actor.get("role") or "") == "admin":
        return True
    ents = actor.get("entitlements") or []
    return bool(ents)


def count_ec_admins(conn: sqlite3.Connection) -> int:
    ensure_ready(conn)
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM residents
        WHERE role = 'admin' AND status = 'active' AND house_id != ?
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchone()
    return int(row["n"] if hasattr(row, "keys") else row[0])


def set_grants(
    conn: sqlite3.Connection,
    house_id: str,
    entitlements: list[str],
    *,
    granted_by: str | None = None,
    commit: bool = True,
) -> list[str]:
    """Grant one-off entitlements to an EC Member (including office bearers). Not for EC Admins."""
    ensure_ready(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        raise ValueError("Invalid plot")
    row = conn.execute(
        """
        SELECT role, is_ec_member, is_office_bearer, official_title
        FROM residents WHERE house_id = ?
        """,
        (hid,),
    ).fetchone()
    if not row:
        raise ValueError("Plot not found")
    if (row["role"] or "") == "admin":
        raise ValueError("EC Admins already have all entitlements")
    is_ob = int(row["is_office_bearer"] or 0) or bool(str(row["official_title"] or "").strip())
    is_mem = int(row["is_ec_member"] or 0) or is_ob
    if not is_mem:
        raise ValueError("Grant entitlements only to EC Members")
    clean = []
    for e in entitlements or []:
        key = str(e or "").strip()
        if key == "sensitive_ops" or key == "manage_roles":
            raise ValueError(f"{key} cannot be granted; EC Admin / sensitive ops only")
        if key in GRANTABLE_ENTITLEMENTS and key not in clean:
            clean.append(key)
    conn.execute("DELETE FROM resident_entitlements WHERE house_id = ?", (hid,))
    now = utc_now()
    for key in clean:
        conn.execute(
            """
            INSERT INTO resident_entitlements(house_id, entitlement, granted_by, granted_at)
            VALUES (?, ?, ?, ?)
            """,
            (hid, key, granted_by, now),
        )
    if commit:
        conn.commit()
    return clean


def list_office_and_ec(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """EC members, office bearers, and EC admins."""
    ensure_ready(conn)
    rows = conn.execute(
        """
        SELECT house_id, plot_no, section, name, official_title, role, status,
               is_ec_member, is_office_bearer
        FROM residents
        WHERE house_id != ?
          AND status = 'active'
          AND (
            is_ec_member = 1 OR is_office_bearer = 1 OR role = 'admin'
            OR (official_title IS NOT NULL AND official_title != '')
          )
        ORDER BY
          CASE WHEN role = 'admin' THEN 0
               WHEN is_office_bearer = 1 THEN 1
               ELSE 2 END,
          official_title COLLATE NOCASE,
          name COLLATE NOCASE
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchall()
    out = []
    photos = primary_member_photo_map(conn)
    for r in rows:
        hid = r["house_id"]
        is_ec = (r["role"] or "") == "admin"
        is_ob = bool(int(r["is_office_bearer"] or 0)) or bool(r["official_title"]) or is_ec
        is_mem = bool(int(r["is_ec_member"] or 0)) or is_ob or is_ec
        grants = [] if is_ec else load_grants(conn, hid)
        photo = photos.get(hid) or {}
        out.append({
            "houseId": hid,
            "plotNo": r["plot_no"] or hid,
            "section": r["section"] or "",
            "name": r["name"] or hid,
            "officialTitle": r["official_title"] or "",
            "role": r["role"] or "resident",
            "isEcMember": is_mem,
            "isOfficeBearer": is_ob,
            "isEcAdmin": is_ec,
            "entitlements": sorted(EC_ADMIN_ENTITLEMENTS) if is_ec else grants,
            "hasPhoto": bool(photo.get("hasPhoto")),
            "photoUrl": photo.get("photoUrl") or "",
            "primaryMemberId": photo.get("memberId"),
        })
    return out
