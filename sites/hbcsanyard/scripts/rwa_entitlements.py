"""Fine-grained EC desk entitlements.

Roles (nested):
  Resident → EC Member → Office Bearer → EC Admin

- EC Admin and Office Bearer are always EC Members.
- EC Members (and office bearers) may receive one-off grantable entitlements.
- EC Admins get most entitlements implicitly; sensitive_ops / manage_roles are EC-Admin-only.
- issue_no_dues / issue_no_objection are explicit (not auto for EC Admins); default seed grants them to President.
- treasury is explicit; default seed grants it to Treasurer.
- manage_proceedings default seed grants it to General Secretary (EC Committee register).
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID, ensure_entitlements_schema, utc_now
from rwa_household import primary_member_photo_map
import rwa_household as household

ENTITLEMENT_DEFS: list[dict[str, str]] = [
    {"id": "manage_roster", "label": "Resident roster", "description": "View and edit plot contacts"},
    {"id": "manage_dues", "label": "Dues ledger", "description": "View and curate colony dues"},
    {
        "id": "issue_no_dues",
        "label": "No Dues Issuer",
        "description": "Review requests and issue No Dues Certificates (explicit grant)",
    },
    {
        "id": "issue_no_objection",
        "label": "No Objection Issuer",
        "description": "Review requests and issue No Objection Certificates (explicit grant)",
    },
    {
        "id": "treasury",
        "label": "Treasury",
        "description": "Validate and confirm financials — dues, cash, payments, certificates (explicit grant)",
    },
    {"id": "manage_notices", "label": "Notices", "description": "Publish and manage notices"},
    {
        "id": "moderate_messages",
        "label": "Messages",
        "description": "Moderate colony channel posts (hide, delete, pin)",
    },
    {"id": "manage_concerns", "label": "Concerns mailbox", "description": "Respond to resident concerns"},
    {"id": "manage_info", "label": "Info centre", "description": "Manage documents"},
    {"id": "manage_works", "label": "Works & events", "description": "Manage colony works"},
    {
        "id": "manage_proceedings",
        "label": "Proceedings / MOM",
        "description": "Record General House and EC meeting minutes (default: General Secretary)",
    },
    {"id": "manage_bank", "label": "Bank / UPI", "description": "Update collection account"},
    {"id": "generate_reports", "label": "Reports", "description": "Generate PDF reports"},
    {
        "id": "manage_templates",
        "label": "Templates",
        "description": "Upload and manage printable letterheads, receipts, and forms",
    },
    {"id": "manage_roles", "label": "Roles & entitlements", "description": "Designate EC members / office bearers, elevate EC Admin, grant access (EC Admin / sensitive ops only)"},
    {"id": "sensitive_ops", "label": "Sensitive ops", "description": "Roles, revision history, and ledger import (EC Admin only)"},
]

EC_ADMIN_ONLY_ENTITLEMENTS = frozenset({"sensitive_ops", "manage_roles"})
# Stored grants only — never implied by EC Admin role.
EXPLICIT_GRANT_ENTITLEMENTS = frozenset({"issue_no_dues", "issue_no_objection", "treasury"})
GRANTABLE_ENTITLEMENTS = frozenset(
    e["id"] for e in ENTITLEMENT_DEFS if e["id"] not in EC_ADMIN_ONLY_ENTITLEMENTS
)
ALL_ENTITLEMENTS = frozenset(e["id"] for e in ENTITLEMENT_DEFS)
# What EC Admins get without a row in resident_entitlements.
EC_ADMIN_IMPLICIT_ENTITLEMENTS = frozenset(ALL_ENTITLEMENTS - EXPLICIT_GRANT_ENTITLEMENTS)
EC_ADMIN_ENTITLEMENTS = frozenset(ALL_ENTITLEMENTS)  # capacity / UI catalog; effective set uses implicit + grants


def entitlements_meta() -> dict:
    return {
        "entitlements": ENTITLEMENT_DEFS,
        "grantable": sorted(GRANTABLE_ENTITLEMENTS),
        "explicit": sorted(EXPLICIT_GRANT_ENTITLEMENTS),
        "ecAdminOnly": sorted(EC_ADMIN_ONLY_ENTITLEMENTS),
        "roles": [
            {"id": "ec_member", "label": "EC Member", "description": "Committee member; may receive one-off entitlements"},
            {"id": "office_bearer", "label": "Office Bearer", "description": "Titled post; always an EC Member"},
            {"id": "ec_admin", "label": "EC Admin", "description": "Full desk access; must be an Office Bearer"},
        ],
    }


def ensure_ready(conn: sqlite3.Connection) -> None:
    ensure_entitlements_schema(conn)
    ensure_default_no_dues_issuer(conn)
    ensure_default_no_objection_issuer(conn)
    ensure_default_treasury(conn)
    ensure_default_proceedings_secretary(conn)


def _seed_explicit_grant_for_title(
    conn: sqlite3.Connection,
    *,
    entitlement: str,
    meta_key: str,
    title_match,
) -> None:
    """Once: if no grants exist for entitlement, grant to matching office titles."""
    ensure_entitlements_schema(conn)
    flagged = conn.execute(
        "SELECT value FROM meta WHERE key = ?",
        (meta_key,),
    ).fetchone()
    if flagged:
        return

    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM resident_entitlements WHERE entitlement = ?",
        (entitlement,),
    ).fetchone()
    n = int(existing["n"] if hasattr(existing, "keys") else existing[0])
    now = utc_now()
    if n == 0:
        rows = conn.execute(
            """
            SELECT house_id, official_title FROM residents
            WHERE house_id != ?
              AND status = 'active'
              AND official_title IS NOT NULL
              AND TRIM(official_title) != ''
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
        for r in rows:
            title = re.sub(r"\s+", " ", (r["official_title"] or "").strip()).lower()
            if title_match(title):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO resident_entitlements(house_id, entitlement, granted_by, granted_at)
                    VALUES (?, ?, 'system:default', ?)
                    """,
                    (r["house_id"], entitlement, now),
                )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (meta_key, now),
    )
    conn.commit()


def _is_president_title(title: str) -> bool:
    return title == "president" or bool(re.fullmatch(r"president(\s+rwa)?", title))


def ensure_default_no_dues_issuer(conn: sqlite3.Connection) -> None:
    """Once: grant issue_no_dues to President only (not Vice President)."""
    _seed_explicit_grant_for_title(
        conn,
        entitlement="issue_no_dues",
        meta_key="no_dues_issuer_defaulted",
        title_match=_is_president_title,
    )


def ensure_default_no_objection_issuer(conn: sqlite3.Connection) -> None:
    """Once: grant issue_no_objection to President only (not Vice President)."""
    _seed_explicit_grant_for_title(
        conn,
        entitlement="issue_no_objection",
        meta_key="no_objection_issuer_defaulted",
        title_match=_is_president_title,
    )


def ensure_default_treasury(conn: sqlite3.Connection) -> None:
    """Once: grant treasury to Treasurer only (not Vice Treasurer)."""
    def _is_treasurer(title: str) -> bool:
        return title == "treasurer" or bool(re.fullmatch(r"treasurer(\s+rwa)?", title))

    _seed_explicit_grant_for_title(
        conn,
        entitlement="treasury",
        meta_key="treasury_defaulted",
        title_match=_is_treasurer,
    )


def _is_general_secretary_title(title: str) -> bool:
    return title == "general secretary" or bool(re.fullmatch(r"general secretary(\s+rwa)?", title))


def ensure_default_proceedings_secretary(conn: sqlite3.Connection) -> None:
    """Once: grant manage_proceedings to General Secretary (MOM register keeper)."""
    _seed_explicit_grant_for_title(
        conn,
        entitlement="manage_proceedings",
        meta_key="proceedings_secretary_defaulted",
        title_match=_is_general_secretary_title,
    )


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


def actor_holds_ec_seat(actor: dict | None) -> bool:
    """True when this login is the designated EC seat holder for the plot.

    Seat holders are the plot owner or the primary delegate (bound via
    residents.ec_member_id). Other household delegates never inherit EC
    entitlements even if the plot is on the committee.
    """
    if not actor:
        return False
    if _is_super(actor):
        return True
    if actor.get("viewOnly"):
        return False
    # Explicit flag from enrich / public_resident
    if "holdsEcSeat" in actor:
        return bool(actor.get("holdsEcSeat"))
    mid = str(actor.get("memberId") or actor.get("member_id") or "").strip()
    seat = str(actor.get("ecMemberId") or actor.get("ec_member_id") or "").strip()
    if seat:
        return bool(mid) and mid == seat
    # Legacy plots without ec_member_id: primary owner holds the seat.
    return bool(actor.get("isPrimary"))


def entitlements_for_actor(conn: sqlite3.Connection, actor: dict | None) -> list[str]:
    if not actor:
        return []
    if _is_super(actor):
        return sorted(EC_ADMIN_ENTITLEMENTS)
    if actor.get("viewOnly") or not actor_holds_ec_seat(actor):
        return []
    grants = load_grants(conn, actor.get("houseId") or "")
    if (actor.get("role") or "") == "admin":
        return sorted(EC_ADMIN_IMPLICIT_ENTITLEMENTS | set(grants))
    if not is_ec_member(actor):
        return []
    return grants


def enrich_actor(conn: sqlite3.Connection, actor: dict) -> dict:
    ensure_ready(conn)
    hid = actor.get("houseId") or ""
    super_admin = _is_super(actor)
    ec_member_id = str(actor.get("ecMemberId") or "").strip() or None
    if hid and hid != SUPERADMIN_HOUSE_ID:
        row = conn.execute(
            """
            SELECT is_ec_member, is_office_bearer, official_title, role, ec_member_id
            FROM residents WHERE house_id = ?
            """,
            (hid,),
        ).fetchone()
        if row:
            try:
                ec_member_id = (row["ec_member_id"] or "").strip() or ec_member_id
            except (KeyError, IndexError, TypeError):
                pass
            is_ob = bool(int(row["is_office_bearer"] or 0)) or bool(str(row["official_title"] or "").strip()) or (
                (row["role"] or "") == "admin"
            )
            is_mem = bool(int(row["is_ec_member"] or 0)) or is_ob or (row["role"] or "") == "admin"
            actor["isOfficeBearer"] = is_ob or super_admin
            actor["isEcMember"] = is_mem or super_admin
            actor["ecMemberId"] = ec_member_id
            actor["plotIsEc"] = is_mem
        else:
            actor["isOfficeBearer"] = super_admin or bool(str(actor.get("officialTitle") or "").strip()) or (
                actor.get("role") == "admin"
            )
            actor["isEcMember"] = actor["isOfficeBearer"] or bool(actor.get("isEcMember"))
    else:
        actor["isOfficeBearer"] = True
        actor["isEcMember"] = True

    mid = str(actor.get("memberId") or "").strip()
    if super_admin:
        holds = True
    elif actor.get("viewOnly"):
        holds = False
    elif not actor.get("isEcMember") and not actor.get("isOfficeBearer") and (actor.get("role") or "") != "admin":
        holds = False
    elif ec_member_id:
        holds = bool(mid) and mid == ec_member_id
    else:
        holds = bool(actor.get("isPrimary"))
    actor["holdsEcSeat"] = holds
    actor["ecMemberId"] = ec_member_id

    # Plot-level EC flags apply to the seat holder only.
    if not holds and not super_admin:
        actor["isEcAdmin"] = False
        actor["isOfficeBearer"] = False
        actor["isEcMember"] = False
        actor["officialTitle"] = ""
        if (actor.get("role") or "") == "admin":
            actor["role"] = "resident"
        actor["entitlements"] = []
        return actor

    actor["isEcAdmin"] = is_ec_admin(actor) and not actor.get("viewOnly") and holds
    if actor.get("viewOnly"):
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
    if actor.get("viewOnly") or not actor_holds_ec_seat(actor):
        return False
    ents = actor.get("entitlements")
    if isinstance(ents, list):
        return key in ents
    if (actor.get("role") or "") == "admin":
        # Without enriched list: implicit only (explicit grants e.g. issue_no_dues / treasury).
        return key in EC_ADMIN_IMPLICIT_ENTITLEMENTS
    return False


def actor_can_open_ec_desk(actor: dict | None) -> bool:
    if not actor:
        return False
    if _is_super(actor):
        return True
    if actor.get("viewOnly") or not actor_holds_ec_seat(actor):
        return False
    if (actor.get("role") or "") == "admin" or actor.get("isEcAdmin"):
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
    """Grant entitlements to EC Members / office bearers; for EC Admins only explicit grants (e.g. issue_no_dues, treasury)."""
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
    is_admin = (row["role"] or "") == "admin"
    is_ob = int(row["is_office_bearer"] or 0) or bool(str(row["official_title"] or "").strip())
    is_mem = int(row["is_ec_member"] or 0) or is_ob or is_admin
    if not is_mem:
        raise ValueError("Grant entitlements only to EC Members")

    requested = []
    for e in entitlements or []:
        key = str(e or "").strip()
        if key in EC_ADMIN_ONLY_ENTITLEMENTS:
            raise ValueError(f"{key} cannot be granted; EC Admin / sensitive ops only")
        if key in GRANTABLE_ENTITLEMENTS and key not in requested:
            requested.append(key)

    now = utc_now()
    if is_admin:
        # EC Admins already have implicit desk access — only store explicit grants.
        clean = [k for k in requested if k in EXPLICIT_GRANT_ENTITLEMENTS]
        for key in EXPLICIT_GRANT_ENTITLEMENTS:
            conn.execute(
                "DELETE FROM resident_entitlements WHERE house_id = ? AND entitlement = ?",
                (hid, key),
            )
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
        return sorted(EC_ADMIN_IMPLICIT_ENTITLEMENTS | set(clean))

    clean = requested
    conn.execute("DELETE FROM resident_entitlements WHERE house_id = ?", (hid,))
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
    """EC members, office bearers, and EC admins (with seat-holder identity)."""
    ensure_ready(conn)
    rows = conn.execute(
        """
        SELECT house_id, plot_no, section, name, official_title, role, status,
               is_ec_member, is_office_bearer, ec_member_id
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
        grants = load_grants(conn, hid)
        effective = sorted(EC_ADMIN_IMPLICIT_ENTITLEMENTS | set(grants)) if is_ec else grants
        owner = household.primary_member(conn, hid)
        delegate = household.primary_delegate_member(conn, hid)
        seat_id = (r["ec_member_id"] or "").strip() or ((owner or {}).get("id") or "")
        seat = household.get_member(conn, seat_id) if seat_id else None
        seat_pub = household.public_member(seat) if seat else {}
        photo = photos.get(hid) or {}
        if seat_pub.get("hasPhoto"):
            photo = {
                "hasPhoto": True,
                "photoUrl": seat_pub.get("photoUrl") or "",
                "memberId": seat_pub.get("id"),
            }
        out.append({
            "houseId": hid,
            "plotNo": r["plot_no"] or hid,
            "section": r["section"] or "",
            "name": (seat_pub.get("name") or r["name"] or hid),
            "ownerName": (owner or {}).get("name") or r["name"] or hid,
            "primaryDelegateName": (delegate or {}).get("name") or "",
            "displayName": (
                f"{(owner or {}).get('name') or r['name'] or hid}"
                + (f" / {(delegate or {}).get('name')}" if (delegate or {}).get("name") else "")
            ),
            "officialTitle": r["official_title"] or "",
            "role": r["role"] or "resident",
            "isEcMember": is_mem,
            "isOfficeBearer": is_ob,
            "isEcAdmin": is_ec,
            "ecMemberId": seat_id or None,
            "ecSeatHolderName": seat_pub.get("name") or "",
            "ecSeatHolderLabel": seat_pub.get("identityLabel") or "",
            "eligibleMembers": household.eligible_ec_members(conn, hid),
            "entitlements": effective,
            "hasPhoto": bool(photo.get("hasPhoto")),
            "photoUrl": photo.get("photoUrl") or "",
            "primaryMemberId": photo.get("memberId"),
        })
    return out
