"""Household members: owner + delegates per plot (optional view-only access)."""

from __future__ import annotations

import re
import secrets
import sqlite3
from typing import Any

from init_rwa_db import (
    MEMBER_RELATIONS,
    SUPERADMIN_HOUSE_ID,
    ensure_household_members_table,
    utc_now,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RELATION_LABELS = {
    "owner": "Owner",
    "spouse": "Spouse",
    "parent": "Parent",
    "child": "Child",
    "other": "Other",
}


def _row_dict(row: sqlite3.Row | dict | None) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def normalize_phone(raw: str | None) -> str | None:
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw).strip())
    if not digits:
        return None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        cleaned = re.sub(r"[^\d+]", "", str(raw).strip())
        return cleaned[:20] or None
    return digits


def validate_email(raw: str | None) -> str:
    email = str(raw or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    return email


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        shown = local[:1] + "*"
    else:
        shown = local[:2] + "*" * max(1, len(local) - 2)
    return f"{shown}@{domain}"


def public_member(m: dict | sqlite3.Row | None, *, include_contacts: bool = True) -> dict:
    data = _row_dict(m)
    if not data:
        return {}
    relation = (data.get("relation") or "other").strip().lower()
    if relation not in MEMBER_RELATIONS:
        relation = "other"
    out = {
        "id": data.get("id"),
        "houseId": data.get("house_id") or data.get("houseId"),
        "name": data.get("name") or "",
        "title": data.get("title") or "",
        "relation": relation,
        "relationLabel": RELATION_LABELS.get(relation, relation.title()),
        "isPrimary": bool(int(data.get("is_primary") or data.get("isPrimary") or 0)),
        "canManage": bool(int(data.get("can_manage") or data.get("canManage") or 0)),
        "viewOnly": bool(int(data.get("view_only") or data.get("viewOnly") or 0)),
        "status": data.get("status") or "active",
    }
    if include_contacts:
        out["email"] = data.get("email") or ""
        out["phone"] = data.get("phone") or ""
    else:
        out["emailMasked"] = mask_email(data.get("email"))
        out["hasEmail"] = bool(str(data.get("email") or "").strip())
        out["hasPhone"] = bool(str(data.get("phone") or "").strip())
    return out


def get_member(conn: sqlite3.Connection, member_id: str) -> dict | None:
    ensure_household_members_table(conn)
    mid = (member_id or "").strip()
    if not mid:
        return None
    row = conn.execute("SELECT * FROM household_members WHERE id = ?", (mid,)).fetchone()
    return _row_dict(row) if row else None


def list_members(
    conn: sqlite3.Connection,
    house_id: str,
    *,
    include_inactive: bool = False,
) -> list[dict]:
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        return []
    if include_inactive:
        rows = conn.execute(
            """
            SELECT * FROM household_members
            WHERE house_id = ?
            ORDER BY is_primary DESC, can_manage DESC,
              CASE relation
                WHEN 'owner' THEN 0 WHEN 'spouse' THEN 1 WHEN 'parent' THEN 2
                WHEN 'child' THEN 3 ELSE 4 END,
              name COLLATE NOCASE
            """,
            (hid,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM household_members
            WHERE house_id = ? AND status = 'active'
            ORDER BY is_primary DESC, can_manage DESC,
              CASE relation
                WHEN 'owner' THEN 0 WHEN 'spouse' THEN 1 WHEN 'parent' THEN 2
                WHEN 'child' THEN 3 ELSE 4 END,
              name COLLATE NOCASE
            """,
            (hid,),
        ).fetchall()
    return [_row_dict(r) for r in rows]


def primary_member(conn: sqlite3.Connection, house_id: str) -> dict | None:
    members = list_members(conn, house_id, include_inactive=False)
    if not members:
        return None
    for m in members:
        if int(m.get("is_primary") or 0):
            return m
    return members[0]


def sync_primary_to_resident(conn: sqlite3.Connection, house_id: str) -> None:
    """Keep residents.name/email/phone/title aligned with the primary member."""
    primary = primary_member(conn, house_id)
    if not primary:
        return
    conn.execute(
        """
        UPDATE residents
        SET name = ?, title = ?, email = ?, phone = ?, updated_at = ?
        WHERE house_id = ?
        """,
        (
            primary.get("name") or house_id,
            primary.get("title"),
            primary.get("email") or None,
            primary.get("phone") or None,
            utc_now(),
            house_id,
        ),
    )


def member_contact_gaps(member: dict | None) -> dict:
    m = member or {}
    missing_email = not str(m.get("email") or "").strip()
    missing_phone = not str(m.get("phone") or "").strip()
    return {
        "missingEmail": missing_email,
        "missingPhone": missing_phone,
        "needsContact": missing_email or missing_phone,
    }


def login_members_public(conn: sqlite3.Connection, house_id: str) -> list[dict]:
    """Member list shown on the login picker (no full emails)."""
    return [
        public_member(m, include_contacts=False)
        for m in list_members(conn, house_id, include_inactive=False)
    ]


def actor_can_use_ec_desk(actor: dict | None) -> bool:
    """Only primary owners (or super admin) of an EC plot may use EC desk.

    Delegates on an EC household always get resident access at most.
    """
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    if actor.get("viewOnly"):
        return False
    if not actor.get("isPrimary"):
        return False
    return actor.get("role") == "admin"


def can_actor_manage_household(actor: dict | None, house_id: str) -> bool:
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    # EC desk users (primary owners of EC plots) may manage any household roster.
    if actor_can_use_ec_desk(actor):
        return True
    if (actor.get("houseId") or actor.get("house_id")) != house_id:
        return False
    if actor.get("viewOnly"):
        return False
    return bool(actor.get("canManageHousehold") or actor.get("canManage") or actor.get("isPrimary"))


def actor_is_view_only(actor: dict | None) -> bool:
    return bool(actor and actor.get("viewOnly") and not actor.get("superAdmin"))


def actor_can_write(actor: dict | None) -> bool:
    """Post concerns, like/comment — blocked for view-only delegates."""
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    return not bool(actor.get("viewOnly"))


def add_member(
    conn: sqlite3.Connection,
    house_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    if not hid or hid == SUPERADMIN_HOUSE_ID:
        raise ValueError("Invalid plot")
    if not can_actor_manage_household(actor, hid):
        raise ValueError("Only the owner (or EC) can add household members")

    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("Name required")
    relation = str(payload.get("relation") or "other").strip().lower()
    if relation not in MEMBER_RELATIONS:
        raise ValueError("Invalid relation")
    if relation == "owner":
        # Only one conceptual owner/primary — force other relations for delegates
        relation = "other"

    title = str(payload.get("title") or "").strip()[:40] or None
    email = None
    if "email" in payload and str(payload.get("email") or "").strip():
        email = validate_email(payload.get("email"))
    phone = None
    if "phone" in payload and str(payload.get("phone") or "").strip():
        phone = normalize_phone(payload.get("phone"))
        if not phone or len(re.sub(r"\D", "", phone)) < 10:
            raise ValueError("Enter a valid 10-digit mobile number")

    view_only = bool(payload.get("viewOnly") or payload.get("view_only"))
    # Delegates never get manage by default; owners stay primary
    mid = f"hm_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO household_members(
          id, house_id, relation, is_primary, can_manage, view_only,
          name, title, email, phone, status, created_at, updated_at
        ) VALUES (?, ?, ?, 0, 0, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (mid, hid, relation, 1 if view_only else 0, name, title, email, phone, now, now),
    )
    conn.commit()
    return public_member(get_member(conn, mid))


def update_member(
    conn: sqlite3.Connection,
    house_id: str,
    member_id: str,
    payload: dict,
    *,
    actor: dict | None = None,
) -> dict:
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    member = get_member(conn, member_id)
    if not member or member.get("house_id") != hid:
        raise ValueError("Member not found")

    actor_member_id = (actor or {}).get("memberId") or (actor or {}).get("member_id")
    is_self = actor_member_id and actor_member_id == member_id
    managing = can_actor_manage_household(actor, hid)

    if not is_self and not managing:
        raise ValueError("Not allowed to update this member")
    if actor_is_view_only(actor) and not is_self:
        raise ValueError("View-only access cannot manage household members")

    name = member.get("name")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()[:120]
        if not name:
            raise ValueError("Name required")

    title = member.get("title")
    if "title" in payload:
        title = str(payload.get("title") or "").strip()[:40] or None

    email = member.get("email")
    if "email" in payload:
        raw = str(payload.get("email") or "").strip()
        email = validate_email(raw) if raw else None

    phone = member.get("phone")
    if "phone" in payload:
        raw = str(payload.get("phone") or "").strip()
        if raw:
            phone = normalize_phone(raw)
            if not phone or len(re.sub(r"\D", "", phone)) < 10:
                raise ValueError("Enter a valid 10-digit mobile number")
        else:
            phone = None

    relation = member.get("relation") or "other"
    is_primary = int(member.get("is_primary") or 0)
    can_manage = int(member.get("can_manage") or 0)
    view_only = int(member.get("view_only") or 0)
    status = member.get("status") or "active"

    if managing and not (is_self and not can_actor_manage_household(actor, hid)):
        if "relation" in payload and not is_primary:
            rel = str(payload.get("relation") or "").strip().lower()
            if rel in MEMBER_RELATIONS and rel != "owner":
                relation = rel
        if "viewOnly" in payload or "view_only" in payload:
            if is_primary or can_manage:
                view_only = 0
            else:
                view_only = 1 if (payload.get("viewOnly", payload.get("view_only"))) else 0
        if "status" in payload and payload.get("status") in {"active", "inactive"}:
            if is_primary and payload.get("status") == "inactive":
                raise ValueError("Cannot deactivate the primary owner")
            status = payload["status"]
        if payload.get("makePrimary") and not is_primary:
            # Transfer primary + manage to this member
            conn.execute(
                "UPDATE household_members SET is_primary = 0, can_manage = 0, view_only = 0 WHERE house_id = ?",
                (hid,),
            )
            is_primary = 1
            can_manage = 1
            view_only = 0
            relation = "owner"

    now = utc_now()
    conn.execute(
        """
        UPDATE household_members
        SET name = ?, title = ?, email = ?, phone = ?, relation = ?,
            is_primary = ?, can_manage = ?, view_only = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            name, title, email, phone, relation,
            is_primary, can_manage, view_only, status, now, member_id,
        ),
    )
    if is_primary:
        sync_primary_to_resident(conn, hid)
    conn.commit()
    return public_member(get_member(conn, member_id))


def delete_member(
    conn: sqlite3.Connection,
    house_id: str,
    member_id: str,
    *,
    actor: dict | None = None,
) -> None:
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    if not can_actor_manage_household(actor, hid):
        raise ValueError("Only the owner (or EC) can remove household members")
    member = get_member(conn, member_id)
    if not member or member.get("house_id") != hid:
        raise ValueError("Member not found")
    if int(member.get("is_primary") or 0) or int(member.get("can_manage") or 0):
        # Soft-guard: never delete the last managing owner
        managers = [
            m for m in list_members(conn, hid, include_inactive=False)
            if int(m.get("can_manage") or 0) or int(m.get("is_primary") or 0)
        ]
        if len(managers) <= 1 and member_id in {m["id"] for m in managers}:
            raise ValueError("Cannot remove the only owner / manager for this plot")
        if int(member.get("is_primary") or 0):
            raise ValueError("Make another member primary before removing the owner")
    conn.execute("DELETE FROM household_members WHERE id = ?", (member_id,))
    conn.commit()


def apply_member_contacts(
    conn: sqlite3.Connection,
    member_id: str,
    *,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    """Fill empty email/phone on a member after OTP verify."""
    member = get_member(conn, member_id)
    if not member:
        raise ValueError("Member not found")
    gaps = member_contact_gaps(member)
    new_email = member.get("email")
    new_phone = member.get("phone")
    changed = False
    if gaps["missingEmail"] and email:
        new_email = validate_email(email)
        changed = True
    if gaps["missingPhone"] and phone:
        new_phone = normalize_phone(phone)
        if not new_phone or len(re.sub(r"\D", "", new_phone)) < 10:
            raise ValueError("Enter a valid 10-digit mobile number")
        changed = True
    if not changed:
        return member
    conn.execute(
        """
        UPDATE household_members SET email = ?, phone = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_email, new_phone, utc_now(), member_id),
    )
    if int(member.get("is_primary") or 0):
        sync_primary_to_resident(conn, member["house_id"])
    conn.commit()
    return get_member(conn, member_id) or member


def prepare_member_pending_contacts(
    member: dict,
    *,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    gaps = member_contact_gaps(member)
    pending_email = None
    pending_phone = None
    if gaps["missingEmail"]:
        pending_email = validate_email(email)
    if gaps["missingPhone"]:
        if not phone:
            raise ValueError("Mobile number is required for the colony register")
        normalized = normalize_phone(phone)
        if not normalized or len(re.sub(r"\D", "", normalized)) < 10:
            raise ValueError("Enter a valid 10-digit mobile number")
        pending_phone = normalized
    delivery_email = pending_email or (str(member.get("email") or "").strip().lower() or None)
    if not delivery_email:
        raise ValueError("Email is required so we can send your login code")
    return {
        "pendingEmail": pending_email,
        "pendingPhone": pending_phone,
        "deliveryEmail": delivery_email,
        "missingEmail": gaps["missingEmail"],
        "missingPhone": gaps["missingPhone"],
    }
