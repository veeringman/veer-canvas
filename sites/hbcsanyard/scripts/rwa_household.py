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


def photo_fields_for_member(member_id: str | None, filename: str | None) -> dict:
    mid = (member_id or "").strip()
    fn = (filename or "").strip()
    if mid and fn:
        return {
            "memberId": mid,
            "hasPhoto": True,
            "photoUrl": f"/api/rwa/profile/photo/{mid}",
        }
    return {"memberId": mid or None, "hasPhoto": False, "photoUrl": ""}


def primary_member_photo_map(conn: sqlite3.Connection) -> dict[str, dict]:
    """house_id -> photo fields for the primary household member."""
    ensure_household_members_table(conn)
    rows = conn.execute(
        """
        SELECT house_id, id, photo_filename
        FROM household_members
        WHERE status = 'active' AND is_primary = 1
        """
    ).fetchall()
    return {
        str(r["house_id"]): photo_fields_for_member(r["id"], r["photo_filename"])
        for r in rows
    }


def member_photo_map(conn: sqlite3.Connection, member_ids: list[str] | None = None) -> dict[str, dict]:
    """member_id -> photo fields."""
    ensure_household_members_table(conn)
    if member_ids is not None:
        ids = [str(m).strip() for m in member_ids if str(m or "").strip()]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, photo_filename FROM household_members WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, photo_filename FROM household_members WHERE status = 'active'"
        ).fetchall()
    return {
        str(r["id"]): photo_fields_for_member(r["id"], r["photo_filename"])
        for r in rows
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
        "isPrimaryDelegate": bool(
            int(data.get("is_primary_delegate") or data.get("isPrimaryDelegate") or 0)
        ),
        "canManage": bool(int(data.get("can_manage") or data.get("canManage") or 0)),
        "viewOnly": bool(int(data.get("view_only") or data.get("viewOnly") or 0)),
        "status": data.get("status") or "active",
        "identityId": data.get("id"),
    }
    if out["isPrimary"]:
        out["identityLabel"] = "Owner"
    elif out["isPrimaryDelegate"]:
        out["identityLabel"] = "Primary delegate"
    else:
        out["identityLabel"] = out["relationLabel"] or "Delegate"
    if include_contacts:
        out["email"] = data.get("email") or ""
        out["phone"] = data.get("phone") or ""
    else:
        out["emailMasked"] = mask_email(data.get("email"))
        out["hasEmail"] = bool(str(data.get("email") or "").strip())
        out["hasPhone"] = bool(str(data.get("phone") or "").strip())
    photo = (data.get("photo_filename") or data.get("photoFilename") or "").strip()
    out["hasPhoto"] = bool(photo)
    out["photoFilename"] = photo or None
    if photo and out.get("id"):
        out["photoUrl"] = f"/api/rwa/profile/photo/{out['id']}"
    else:
        out["photoUrl"] = ""
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
            ORDER BY is_primary DESC, is_primary_delegate DESC, can_manage DESC,
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
            ORDER BY is_primary DESC, is_primary_delegate DESC, can_manage DESC,
              CASE relation
                WHEN 'owner' THEN 0 WHEN 'spouse' THEN 1 WHEN 'parent' THEN 2
                WHEN 'child' THEN 3 ELSE 4 END,
              name COLLATE NOCASE
            """,
            (hid,),
        ).fetchall()
    return [_row_dict(r) for r in rows]


def primary_delegate_member(conn: sqlite3.Connection, house_id: str) -> dict | None:
    """Active primary delegate for a plot (if any)."""
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    if not hid:
        return None
    row = conn.execute(
        """
        SELECT * FROM household_members
        WHERE house_id = ? AND status = 'active' AND is_primary_delegate = 1
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    return _row_dict(row) if row else None


def assert_unique_member_identity(
    conn: sqlite3.Connection,
    *,
    email: str | None,
    phone: str | None,
    exclude_member_id: str | None = None,
) -> None:
    """Owners and delegates must not share email / phone with another active login."""
    ensure_household_members_table(conn)
    email_n = str(email or "").strip().lower() or None
    phone_n = normalize_phone(phone) if phone else None
    exclude = (exclude_member_id or "").strip() or None
    if email_n:
        row = conn.execute(
            """
            SELECT id, house_id, name FROM household_members
            WHERE status = 'active' AND lower(trim(email)) = ?
              AND (? IS NULL OR id != ?)
            LIMIT 1
            """,
            (email_n, exclude, exclude),
        ).fetchone()
        if row:
            raise ValueError(
                f"Email already used by {row['name']} (plot {row['house_id']}) — each person needs a unique login identity"
            )
    if phone_n:
        digits = re.sub(r"\D", "", phone_n)
        rows = conn.execute(
            """
            SELECT id, house_id, name, phone FROM household_members
            WHERE status = 'active' AND phone IS NOT NULL AND trim(phone) != ''
              AND (? IS NULL OR id != ?)
            """,
            (exclude, exclude),
        ).fetchall()
        for row in rows:
            other = re.sub(r"\D", "", str(row["phone"] or ""))
            if len(other) >= 10 and other[-10:] == digits[-10:]:
                raise ValueError(
                    f"Phone already used by {row['name']} (plot {row['house_id']}) — each person needs a unique login identity"
                )


def is_ec_eligible_member(member: dict | None) -> bool:
    """Owner or primary delegate (not view-only) may hold an EC seat."""
    if not member:
        return False
    if (member.get("status") or "active") != "active":
        return False
    if int(member.get("view_only") or member.get("viewOnly") or 0):
        return False
    if int(member.get("is_primary") or member.get("isPrimary") or 0):
        return True
    if int(member.get("is_primary_delegate") or member.get("isPrimaryDelegate") or 0):
        return True
    return False


def eligible_ec_members(conn: sqlite3.Connection, house_id: str) -> list[dict]:
    """People who may be designated as the EC seat holder for this plot."""
    return [
        public_member(m)
        for m in list_members(conn, house_id, include_inactive=False)
        if is_ec_eligible_member(m)
    ]


def set_primary_delegate(
    conn: sqlite3.Connection,
    house_id: str,
    member_id: str,
    *,
    enabled: bool = True,
    commit: bool = True,
) -> dict:
    """Mark / clear primary delegate (at most one per plot; never the owner)."""
    ensure_household_members_table(conn)
    hid = (house_id or "").strip()
    mid = (member_id or "").strip()
    member = get_member(conn, mid)
    if not member or member.get("house_id") != hid:
        raise ValueError("Member not found")
    if int(member.get("is_primary") or 0):
        raise ValueError("The plot owner cannot also be marked as primary delegate")
    if (member.get("status") or "active") != "active":
        raise ValueError("Only an active delegate can be primary")
    now = utc_now()
    if enabled:
        if int(member.get("view_only") or 0):
            raise ValueError("Clear view-only before marking as primary delegate (EC-eligible)")
        conn.execute(
            "UPDATE household_members SET is_primary_delegate = 0, updated_at = ? WHERE house_id = ?",
            (now, hid),
        )
        conn.execute(
            """
            UPDATE household_members
            SET is_primary_delegate = 1, view_only = 0, updated_at = ?
            WHERE id = ?
            """,
            (now, mid),
        )
    else:
        conn.execute(
            "UPDATE household_members SET is_primary_delegate = 0, updated_at = ? WHERE id = ?",
            (now, mid),
        )
        # If this person held the EC seat, fall seat back to owner.
        owner = primary_member(conn, hid)
        conn.execute(
            """
            UPDATE residents
            SET ec_member_id = ?, updated_at = ?
            WHERE house_id = ? AND ec_member_id = ?
            """,
            ((owner or {}).get("id"), now, hid, mid),
        )
    if commit:
        conn.commit()
    return public_member(get_member(conn, mid))


def resolve_ec_member_id(
    conn: sqlite3.Connection,
    house_id: str,
    *,
    ec_member_id: str | None = None,
    require_eligible: bool = True,
) -> str | None:
    """Validate / default the EC seat holder for a plot."""
    hid = (house_id or "").strip()
    mid = (ec_member_id or "").strip() or None
    if mid:
        member = get_member(conn, mid)
        if not member or member.get("house_id") != hid:
            raise ValueError("EC seat holder must belong to this plot")
        if require_eligible and not is_ec_eligible_member(member):
            raise ValueError(
                "Only the plot owner or the primary delegate can hold an EC seat"
            )
        return mid
    owner = primary_member(conn, hid)
    return (owner or {}).get("id")


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
    """Primary owners with EC Admin role or any granted entitlement (or super admin)."""
    try:
        import rwa_entitlements as ents
        return ents.actor_can_open_ec_desk(actor)
    except Exception:
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
    if actor.get("viewOnly"):
        return False
    actor_house = actor.get("houseId") or actor.get("house_id")
    if actor_house == house_id:
        return bool(actor.get("canManageHousehold") or actor.get("canManage") or actor.get("isPrimary"))
    # Cross-plot: EC seat holders with admin (or manage_roles via entitlements).
    try:
        import rwa_entitlements as ents

        return ents.actor_holds_ec_seat(actor) and (
            ents.is_ec_admin(actor) or ents.actor_has(actor, "manage_roles")
        )
    except Exception:
        return bool(actor.get("holdsEcSeat")) and (
            (actor.get("role") or "") == "admin" or actor.get("isEcAdmin")
        )


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
    want_primary_delegate = bool(
        payload.get("isPrimaryDelegate") or payload.get("is_primary_delegate")
    )
    if want_primary_delegate and view_only:
        raise ValueError("Primary delegate cannot be view-only")
    assert_unique_member_identity(conn, email=email, phone=phone)
    # Delegates never get manage by default; owners stay primary
    mid = f"hm_{secrets.token_hex(8)}"
    now = utc_now()
    conn.execute(
        """
        INSERT INTO household_members(
          id, house_id, relation, is_primary, is_primary_delegate, can_manage, view_only,
          name, title, email, phone, status, created_at, updated_at
        ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (mid, hid, relation, 1 if view_only else 0, name, title, email, phone, now, now),
    )
    if want_primary_delegate:
        set_primary_delegate(conn, hid, mid, enabled=True, commit=False)
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
    is_primary_delegate = int(member.get("is_primary_delegate") or 0)
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
                if view_only and is_primary_delegate:
                    raise ValueError("Clear primary-delegate status before setting view-only")
        if "status" in payload and payload.get("status") in {"active", "inactive"}:
            if is_primary and payload.get("status") == "inactive":
                raise ValueError("Cannot deactivate the primary owner")
            status = payload["status"]
        if payload.get("makePrimary") and not is_primary:
            # Transfer primary + manage to this member
            conn.execute(
                """
                UPDATE household_members
                SET is_primary = 0, is_primary_delegate = 0, can_manage = 0, view_only = 0
                WHERE house_id = ?
                """,
                (hid,),
            )
            is_primary = 1
            is_primary_delegate = 0
            can_manage = 1
            view_only = 0
            relation = "owner"
        if "isPrimaryDelegate" in payload or "is_primary_delegate" in payload:
            want_pd = bool(payload.get("isPrimaryDelegate", payload.get("is_primary_delegate")))
            if want_pd:
                set_primary_delegate(conn, hid, member_id, enabled=True, commit=False)
                is_primary_delegate = 1
                view_only = 0
            else:
                set_primary_delegate(conn, hid, member_id, enabled=False, commit=False)
                is_primary_delegate = 0

    assert_unique_member_identity(
        conn, email=email, phone=phone, exclude_member_id=member_id
    )

    now = utc_now()
    conn.execute(
        """
        UPDATE household_members
        SET name = ?, title = ?, email = ?, phone = ?, relation = ?,
            is_primary = ?, is_primary_delegate = ?, can_manage = ?, view_only = ?,
            status = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            name, title, email, phone, relation,
            is_primary, is_primary_delegate, can_manage, view_only, status, now, member_id,
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
    if int(member.get("is_primary_delegate") or 0):
        set_primary_delegate(conn, hid, member_id, enabled=False, commit=False)
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
    if changed:
        assert_unique_member_identity(
            conn, email=new_email, phone=new_phone, exclude_member_id=member_id
        )
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
