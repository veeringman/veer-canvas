#!/usr/bin/env python3
"""Himuda Housing Colony Sanyard RWA SQLite schema, seed, and PDF ledger import helpers."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 16
SUPERADMIN_HOUSE_ID = "__SUPERADMIN__"

# Residential plots A (rows 1–60) then commercial plots B (61–62) from HIMUDA ledger 15-06-2026.
LEDGER_ROWS = [
    # (plot_no, name, balance_prev, fee_2026, total, amount_received, section, remarks)
    ("1", "SURENDER KUMAR", 10600, 2400, 13000, 0, "A", ""),
    ("2", "Ms. NEENA THAKUR", 10600, 2400, 13000, 0, "A", ""),
    ("3", "SATISH K MAHAJAN", 10600, 2400, 13000, 0, "A", ""),
    ("4", "Dr. B R HIMALAYAN", 0, 2400, 2400, 2400, "A", ""),
    ("5", "R C KAUSHAL", 0, 2400, 2400, 2400, "A", ""),
    ("6", "Ms. CHITERLEKHA BHARDWAJ", 0, 2400, 2400, 2400, "A", ""),
    ("7", "Ms. BHARTI SHARMA", 8800, 2400, 11200, 0, "A", ""),
    ("8", "MADAN LAL SHARMA", 2400, 2400, 4800, 0, "A", ""),
    ("9", "Ms. INDIRA SHARMA", 9000, 2400, 11400, 0, "A", ""),
    ("10", "GURUDEV SINGH", 0, 2400, 2400, 2400, "A", ""),
    ("11", "NAVEEN K KAPOOR", 10600, 2400, 13000, 7200, "A", ""),
    ("12", "PRAVEEN KUMAR", 8800, 2400, 11200, 0, "A", ""),
    ("12A", "BISHAN CHAND SHARMA", 7200, 2400, 9600, 0, "A", ""),
    ("12B-1", "NAVEEN THAKUR", 10600, 2400, 13000, 0, "A", ""),
    ("12B-2", "YADAV KUMAR", 10600, 2400, 13000, 0, "A", ""),
    ("12B-3", "SARBJIT SINGH", 10600, 2400, 13000, 0, "A", ""),
    ("12B-4", "VIKRANT THAKUR", 10600, 2400, 13000, 0, "A", ""),
    ("14", "Ms. SATINDER KAUR", 2400, 2400, 4800, 4800, "A", ""),
    ("15", "Ms. KAUSHALYA KATOCH", 10600, 2400, 13000, 0, "A", ""),
    ("16", "SANDEEP SEN", 10600, 2400, 13000, 0, "A", ""),
    ("17", "ARUN KAPOOR", 8800, 2400, 11200, 10000, "A", ""),
    ("18", "NARENDER KUMAR", 8000, 2400, 10400, 0, "A", ""),
    ("19", "ATUL KUMAR GUPTA", 0, 2400, 2400, 0, "A", ""),
    ("20", "MAN SINGH JAMWAL", 8200, 2400, 10600, 0, "A", ""),
    ("21", "BHARPUR SINGH", 0, 2400, 2400, 2400, "A", ""),
    ("22", "ABHISHEK MAHAJAN", 10600, 2400, 13000, 0, "A", ""),
    ("23", "ANUP VAIDYA", 10600, 2400, 13000, 0, "A", ""),
    ("24", "Ms. ANAMIKA", 0, 2400, 2400, 2400, "A", ""),
    ("25", "UMESH KUMAR", 10600, 2400, 13000, 0, "A", ""),
    ("26", "SURINDER SINGH CHAUDHARI", 6400, 2400, 8800, 0, "A", ""),
    ("27", "Ms. SUNITA THAKUR", 7200, 2400, 9600, 0, "A", ""),
    ("28", "PARVEEN KUMAR", 0, 2400, 2400, 0, "A", ""),
    ("29", "Ms. SIMARJEET KAUR", 10600, 2400, 13000, 0, "A", ""),
    ("30", "JANAK BEHL", 10600, 2400, 13000, 13000, "A", ""),
    ("31", "DEEPAK SHARMA", 10600, 2400, 13000, 0, "A", ""),
    ("32", "DINESH K THAKUR", 10600, 2400, 13000, 0, "A", ""),
    ("33-34", "HARI SINGH DOGRA", 0, 2400, 2400, 2400, "A", ""),
    ("35", "KARAM SINGH GULERIA", 10600, 2400, 13000, 0, "A", ""),
    ("36", "ARINDOM ROY", 2400, 2400, 4800, 0, "A", ""),
    ("37", "HANS RAJ", 0, 2400, 2400, 2400, "A", ""),
    ("38", "NAVKIRAN KAUR", 0, 2400, 2400, 2400, "A", ""),
    ("39", "RAKESH ARORA", 10600, 2400, 13000, 0, "A", ""),
    ("40", "VINOD KUMAR", 10600, 2400, 13000, 0, "A", ""),
    ("41", "Ms. INDU VAIDYA", 10600, 2400, 13000, 0, "A", ""),
    ("42", "NANDLAL CHANDEL", 0, 2400, 2400, 2400, "A", ""),
    ("43", "VIJAY KUMAR SHARMA", 0, 2400, 2400, 0, "A", ""),
    ("44", "NITIN SHARMA", 0, 2400, 2400, 0, "A", ""),
    ("45", "ANIL THAKUR", 0, 2400, 2400, 2400, "A", "Already received"),
    ("46", "VIVEK ANAND", 0, 2400, 2400, 2400, "A", ""),
    ("47", "ISHWAR DASS SHARMA", 0, 2400, 2400, 2400, "A", ""),
    ("48", "RAJESH KUMAR SAINI", 0, 2400, 2400, 0, "A", ""),
    ("49", "JITESH KUMAR", 0, 2400, 2400, 2400, "A", ""),
    ("50", "M L MODGIL", -2400, 2400, 0, 2400, "A", "Already received"),
    ("51", "T R CHAUHAN", 10600, 2400, 13000, 0, "A", ""),
    ("52", "Ms. JAGTAMBA VAIDYA", 10600, 2400, 13000, 0, "A", ""),
    ("53", "Dr. UVEE TYAGI BARWAL", 0, 2400, 2400, 0, "A", ""),
    ("54", "D K GUPTA", 0, 2400, 2400, 2400, "A", ""),
    ("55", "ASHOK THAKUR", 8100, 2400, 10500, 0, "A", ""),
    ("56", "DHARAM PAL SHARMA", 2400, 2400, 4800, 0, "A", ""),
    ("57", "ABHAY SINGH", 10400, 2400, 12800, 0, "A", ""),
    ("B-1", "ABHAY SINGH", 10600, 2400, 13000, 0, "B", "Commercial"),
    ("B-2", "GIAN CHAND", 0, 2400, 2400, 0, "B", "Commercial"),
]

BANK = {
    "bank_name": "Bank of Baroda — Mandi Branch",
    "account_no": "09640100004511",
    "ifsc": "BARB0MANDIX",
    "ledger_as_of": "2026-06-15",
    "colony": "Himuda Housing Colony Sanyard, Mandi",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_ROMAN_TO_ARABIC = {
    "I": "1",
    "II": "2",
    "III": "3",
    "IV": "4",
    "V": "5",
    "VI": "6",
    "VII": "7",
    "VIII": "8",
    "IX": "9",
    "X": "10",
}


def normalize_house_id(plot: str, section: str = "A") -> str:
    """Canonical plot id. Roman suffixes become arabic: 12B(i) → 12B-1."""
    raw = re.sub(r"\s+", "", (plot or "").strip().upper())
    if not raw:
        raise ValueError("plot required")
    # Combined plots like 33/34 → 33-34 (slash breaks URL paths)
    raw = raw.replace("/", "-")
    # 12B(i) / 12B(II) → 12B-1 / 12B-2
    def _roman_suffix(match: re.Match[str]) -> str:
        roman = match.group(1).upper()
        return f"-{_ROMAN_TO_ARABIC.get(roman, roman)}"

    raw = re.sub(r"\(([IVX]+)\)", _roman_suffix, raw)
    # 12B(1) typed with arabic in parens → 12B-1
    raw = re.sub(r"\((\d+)\)", r"-\1", raw)
    if raw.startswith("B-") or section == "B":
        if raw.startswith("B-"):
            return raw
        return f"B-{raw}"
    return raw


def plot_sort_key(plot: str | None) -> tuple:
    """Natural plot order: 1, 2, 10, 12B, 12B-1 (not lexicographic 1, 10, 11, 2)."""
    s = re.sub(r"\s+", "", str(plot or "").strip().upper())
    if not s:
        return ((1, ""),)
    parts = re.findall(r"\d+|[^\d]+", s)
    key: list[tuple] = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def section_plot_sort_key(
    section: str | None,
    plot: str | None,
    house_id: str | None = None,
) -> tuple:
    """Sort by section, then natural plot number, then house id."""
    return (
        str(section or "").strip().upper(),
        plot_sort_key(plot or house_id),
        str(house_id or plot or "").strip().upper(),
    )


def migrate_roman_plot_ids(conn: sqlite3.Connection) -> int:
    """Rename legacy 12B(i)-style house_ids to 12B-1 everywhere in the DB."""
    rows = conn.execute("SELECT house_id, plot_no, section FROM residents").fetchall()
    renames: list[tuple[str, str, str]] = []
    for r in rows:
        old = str(r["house_id"] or "")
        if not old or old == SUPERADMIN_HOUSE_ID:
            continue
        try:
            new = normalize_house_id(old, r["section"] or "A")
        except ValueError:
            continue
        new_plot = normalize_house_id(str(r["plot_no"] or old), r["section"] or "A")
        if new != old or new_plot != str(r["plot_no"] or ""):
            renames.append((old, new, new_plot))

    if not renames:
        # Still fix any plot_no that still shows roman while house_id is already new.
        fixed = 0
        for r in rows:
            old_plot = str(r["plot_no"] or "")
            if "(" not in old_plot:
                continue
            try:
                new_plot = normalize_house_id(old_plot, r["section"] or "A")
            except ValueError:
                continue
            if new_plot != old_plot:
                conn.execute(
                    "UPDATE residents SET plot_no = ?, updated_at = ? WHERE house_id = ?",
                    (new_plot, utc_now(), r["house_id"]),
                )
                fixed += 1
        if fixed:
            conn.commit()
        return fixed

    conn.execute("PRAGMA foreign_keys = OFF")
    updated = 0
    for old, new, new_plot in renames:
        if old == new:
            conn.execute(
                "UPDATE residents SET plot_no = ?, updated_at = ? WHERE house_id = ?",
                (new_plot, utc_now(), old),
            )
            updated += 1
            continue
        # Skip if target already exists (avoid UNIQUE collisions).
        exists = conn.execute(
            "SELECT 1 FROM residents WHERE house_id = ? COLLATE NOCASE",
            (new,),
        ).fetchone()
        if exists:
            continue

        text_cols = [
            ("payment_rows", "house_id"),
            ("sessions", "house_id"),
            ("otp_challenges", "house_id"),
            ("portal_accounts", "house_id"),
            ("notice_shares", "house_id"),
            ("notice_shares", "shared_by"),
            ("notice_likes", "house_id"),
            ("notice_comments", "house_id"),
            ("household_members", "house_id"),
            ("access_events", "house_id"),
            ("resident_revisions", "house_id"),
            ("resident_revisions", "changed_by_house_id"),
            ("grievances", "house_id"),
            ("grievances", "responded_by_house_id"),
            ("grievance_messages", "author_house_id"),
            ("notices", "published_by"),
            ("info_documents", "published_by"),
            ("colony_works", "created_by"),
            ("colony_works", "closed_by"),
        ]
        for table, col in text_cols:
            try:
                conn.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                    (new, old),
                )
            except sqlite3.OperationalError:
                # Table/column may not exist on older DBs yet.
                pass

        conn.execute(
            """
            UPDATE residents
            SET house_id = ?, plot_no = ?, updated_at = ?
            WHERE house_id = ?
            """,
            (new, new_plot, utc_now(), old),
        )
        updated += 1

    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    return updated


def connect(db_path: pathlib.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS residents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          house_id TEXT NOT NULL UNIQUE,
          plot_no TEXT NOT NULL,
          section TEXT NOT NULL DEFAULT 'A',
          name TEXT NOT NULL,
          title TEXT,
          profession TEXT,
          employment_status TEXT NOT NULL DEFAULT 'unknown'
            CHECK(employment_status IN ('working','retired','unknown')),
          official_title TEXT,
          is_ec_member INTEGER NOT NULL DEFAULT 0,
          is_office_bearer INTEGER NOT NULL DEFAULT 0,
          ec_member_id TEXT,
          email TEXT,
          phone TEXT,
          role TEXT NOT NULL DEFAULT 'resident' CHECK(role IN ('admin','resident')),
          status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
          notes TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resident_entitlements (
          house_id TEXT NOT NULL,
          entitlement TEXT NOT NULL,
          granted_by TEXT,
          granted_at TEXT NOT NULL,
          PRIMARY KEY (house_id, entitlement)
        );

        CREATE TABLE IF NOT EXISTS report_templates (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dataset TEXT NOT NULL,
          fields_json TEXT NOT NULL,
          filters_json TEXT NOT NULL DEFAULT '{}',
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payment_ledgers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          as_of TEXT NOT NULL,
          notes TEXT,
          imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payment_rows (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ledger_id INTEGER NOT NULL REFERENCES payment_ledgers(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          balance_prev INTEGER NOT NULL DEFAULT 0,
          fee_year INTEGER NOT NULL DEFAULT 0,
          fee_amount INTEGER NOT NULL DEFAULT 0,
          total_due INTEGER NOT NULL DEFAULT 0,
          amount_received INTEGER NOT NULL DEFAULT 0,
          balance_outstanding INTEGER NOT NULL DEFAULT 0,
          remarks TEXT,
          UNIQUE(ledger_id, house_id)
        );

        CREATE TABLE IF NOT EXISTS notices (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'general',
          pinned INTEGER NOT NULL DEFAULT 0,
          pin_order INTEGER NOT NULL DEFAULT 0,
          published_at TEXT NOT NULL,
          published_by TEXT,
          status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published','archived'))
        );

        CREATE TABLE IF NOT EXISTS notice_shares (
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          can_edit INTEGER NOT NULL DEFAULT 1,
          shared_at TEXT NOT NULL,
          shared_by TEXT,
          PRIMARY KEY (notice_id, house_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notice_shares_house ON notice_shares(house_id);

        CREATE TABLE IF NOT EXISTS notice_likes (
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          member_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (notice_id, member_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notice_likes_notice ON notice_likes(notice_id);

        CREATE TABLE IF NOT EXISTS notice_comments (
          id TEXT PRIMARY KEY,
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          member_id TEXT,
          author_name TEXT,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active', 'hidden', 'deleted'))
        );
        CREATE INDEX IF NOT EXISTS idx_notice_comments_notice
          ON notice_comments(notice_id, created_at ASC);

        CREATE TABLE IF NOT EXISTS household_members (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          relation TEXT NOT NULL DEFAULT 'owner'
            CHECK(relation IN ('owner','spouse','parent','child','other')),
          is_primary INTEGER NOT NULL DEFAULT 0,
          is_primary_delegate INTEGER NOT NULL DEFAULT 0,
          can_manage INTEGER NOT NULL DEFAULT 0,
          view_only INTEGER NOT NULL DEFAULT 0,
          name TEXT NOT NULL,
          title TEXT,
          email TEXT,
          phone TEXT,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','inactive')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_household_members_house
          ON household_members(house_id, status);
        CREATE INDEX IF NOT EXISTS idx_household_members_email
          ON household_members(email);

        CREATE TABLE IF NOT EXISTS access_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          house_id TEXT,
          actor_name TEXT,
          role TEXT,
          is_superadmin INTEGER NOT NULL DEFAULT 0,
          event_type TEXT NOT NULL DEFAULT 'api',
          method TEXT,
          path TEXT,
          action TEXT NOT NULL,
          status_code INTEGER,
          panel TEXT,
          detail TEXT,
          ip TEXT,
          user_agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_access_events_created ON access_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_access_events_house ON access_events(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_access_events_action ON access_events(action, created_at DESC);

        CREATE TABLE IF NOT EXISTS info_documents (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          summary TEXT,
          category TEXT NOT NULL DEFAULT 'general',
          doc_type TEXT NOT NULL DEFAULT 'file'
            CHECK(doc_type IN ('file','html','link')),
          filename TEXT,
          original_name TEXT,
          mime_type TEXT,
          size_bytes INTEGER,
          external_url TEXT,
          status TEXT NOT NULL DEFAULT 'draft'
            CHECK(status IN ('draft','published','archived')),
          audience TEXT NOT NULL DEFAULT 'all'
            CHECK(audience IN ('all','ec')),
          published_at TEXT,
          published_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_info_docs_status
          ON info_documents(status, category, published_at DESC);

        CREATE TABLE IF NOT EXISTS colony_works (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          kind TEXT NOT NULL
            CHECK(kind IN ('maintenance','development','activity','event')),
          category TEXT NOT NULL DEFAULT 'general',
          summary TEXT,
          details TEXT,
          benefits TEXT,
          timeline_notes TEXT,
          milestones_json TEXT,
          status TEXT NOT NULL DEFAULT 'planned'
            CHECK(status IN ('planned','approved','in_progress','on_hold','completed','closed','cancelled')),
          visibility TEXT NOT NULL DEFAULT 'published'
            CHECK(visibility IN ('draft','published')),
          location TEXT,
          start_date TEXT,
          end_date TEXT,
          event_date TEXT,
          estimated_cost INTEGER,
          actual_cost INTEGER,
          cost_notes TEXT,
          contractor_name TEXT,
          contractor_contact TEXT,
          contractor_details TEXT,
          funding_json TEXT,
          assigned_to TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          closed_at TEXT,
          closed_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_colony_works_status
          ON colony_works(status, kind, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_colony_works_visibility
          ON colony_works(visibility, status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS otp_challenges (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          house_id TEXT NOT NULL,
          member_id TEXT,
          code_hash TEXT NOT NULL,
          email_masked TEXT,
          expires_at TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          consumed INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          pending_email TEXT,
          pending_phone TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          member_id TEXT,
          role TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          label TEXT NOT NULL,
          bank_name TEXT NOT NULL,
          account_no TEXT NOT NULL,
          ifsc TEXT NOT NULL,
          is_primary INTEGER NOT NULL DEFAULT 1,
          upi_id TEXT,
          upi_name TEXT,
          qr_filename TEXT
        );

        CREATE TABLE IF NOT EXISTS portal_accounts (
          username TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          is_superadmin INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resident_revisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          house_id TEXT NOT NULL,
          changed_at TEXT NOT NULL,
          changed_by_house_id TEXT,
          changed_by_name TEXT,
          change_source TEXT NOT NULL DEFAULT 'profile',
          snapshot_before TEXT NOT NULL,
          snapshot_after TEXT NOT NULL,
          changed_fields TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS grievances (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          category TEXT NOT NULL,
          subject TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open'
            CHECK(status IN ('open','in_progress','resolved','closed')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          response TEXT,
          responded_at TEXT,
          responded_by_house_id TEXT,
          responded_by_name TEXT
        );

        CREATE TABLE IF NOT EXISTS grievance_messages (
          id TEXT PRIMARY KEY,
          grievance_id TEXT NOT NULL REFERENCES grievances(id) ON DELETE CASCADE,
          author_house_id TEXT,
          author_name TEXT NOT NULL,
          author_role TEXT NOT NULL DEFAULT 'resident'
            CHECK(author_role IN ('resident','ec')),
          body TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_residents_section ON residents(section);
        CREATE INDEX IF NOT EXISTS idx_payment_rows_house ON payment_rows(house_id);
        CREATE INDEX IF NOT EXISTS idx_otp_house ON otp_challenges(house_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_house ON sessions(house_id);
        CREATE INDEX IF NOT EXISTS idx_revisions_house ON resident_revisions(house_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_revisions_changed ON resident_revisions(changed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_grievances_house ON grievances(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_grievances_status ON grievances(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_grievance_messages ON grievance_messages(grievance_id, created_at ASC);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    ensure_resident_profile_columns(conn)
    ensure_bank_account_columns(conn)
    ensure_otp_pending_columns(conn)
    ensure_notice_engagement_tables(conn)
    ensure_household_members_table(conn)
    ensure_grievances_table(conn)
    ensure_info_documents_table(conn)
    ensure_print_templates_table(conn)
    ensure_colony_works_table(conn)
    ensure_meeting_proceedings_table(conn)
    ensure_entitlements_schema(conn)
    ensure_report_templates_table(conn)
    ensure_bilingual_content_columns(conn)
    ensure_payment_records_tables(conn)
    ensure_no_dues_requests_table(conn)
    ensure_no_objection_requests_table(conn)
    ensure_document_attestations_table(conn)
    ensure_treasury_columns(conn)
    ensure_messages_and_push_tables(conn)
    ensure_msg_likes_and_ai(conn)
    try:
        import rwa_vault as _rwa_vault

        _rwa_vault.ensure_vault_tables(conn)
    except Exception:
        pass
    migrate_roman_plot_ids(conn)
    ensure_superadmin_account(conn)


def ensure_resident_profile_columns(conn: sqlite3.Connection) -> None:
    """Add profile columns on older DBs (SQLite has no IF NOT EXISTS for ADD COLUMN)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(residents)").fetchall()}
    alters = [
        ("title", "ALTER TABLE residents ADD COLUMN title TEXT"),
        ("profession", "ALTER TABLE residents ADD COLUMN profession TEXT"),
        (
            "employment_status",
            "ALTER TABLE residents ADD COLUMN employment_status TEXT NOT NULL DEFAULT 'unknown'",
        ),
        ("official_title", "ALTER TABLE residents ADD COLUMN official_title TEXT"),
        (
            "is_ec_member",
            "ALTER TABLE residents ADD COLUMN is_ec_member INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "is_office_bearer",
            "ALTER TABLE residents ADD COLUMN is_office_bearer INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "ec_member_id",
            "ALTER TABLE residents ADD COLUMN ec_member_id TEXT",
        ),
    ]
    for name, sql in alters:
        if name not in cols:
            conn.execute(sql)
    conn.commit()


def ensure_entitlements_schema(conn: sqlite3.Connection) -> None:
    """EC member / office bearer flags + entitlement grants (migrate-safe)."""
    ensure_resident_profile_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resident_entitlements (
          house_id TEXT NOT NULL,
          entitlement TEXT NOT NULL,
          granted_by TEXT,
          granted_at TEXT NOT NULL,
          PRIMARY KEY (house_id, entitlement)
        )
        """
    )
    # Backfill office bearers from title / admin role
    conn.execute(
        """
        UPDATE residents
        SET is_office_bearer = 1
        WHERE house_id != ?
          AND (
            role = 'admin'
            OR (official_title IS NOT NULL AND TRIM(official_title) != '')
          )
        """,
        (SUPERADMIN_HOUSE_ID,),
    )
    # EC admins and office bearers are always EC members
    conn.execute(
        """
        UPDATE residents
        SET is_ec_member = 1
        WHERE house_id != ?
          AND (role = 'admin' OR is_office_bearer = 1
               OR (official_title IS NOT NULL AND TRIM(official_title) != ''))
        """,
        (SUPERADMIN_HOUSE_ID,),
    )
    # Bind EC seat to primary owner when plot is on EC and seat is unset.
    ensure_household_members_table(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(residents)").fetchall()}
    if "ec_member_id" in cols:
        rows = conn.execute(
            """
            SELECT house_id FROM residents
            WHERE house_id != ?
              AND (is_ec_member = 1 OR is_office_bearer = 1 OR role = 'admin'
                   OR (official_title IS NOT NULL AND TRIM(official_title) != ''))
              AND (ec_member_id IS NULL OR TRIM(ec_member_id) = '')
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
        for r in rows:
            hid = r["house_id"]
            primary = conn.execute(
                """
                SELECT id FROM household_members
                WHERE house_id = ? AND status = 'active' AND is_primary = 1
                ORDER BY created_at ASC LIMIT 1
                """,
                (hid,),
            ).fetchone()
            if primary:
                conn.execute(
                    "UPDATE residents SET ec_member_id = ? WHERE house_id = ?",
                    (primary["id"], hid),
                )
    conn.commit()


def ensure_report_templates_table(conn: sqlite3.Connection) -> None:
    """Saved custom report definitions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_templates (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dataset TEXT NOT NULL,
          fields_json TEXT NOT NULL,
          filters_json TEXT NOT NULL DEFAULT '{}',
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def ensure_print_templates_table(conn: sqlite3.Connection) -> None:
    """EC Desk printable templates (letterhead, receipts, forms)."""
    try:
        import rwa_templates as _rwa_templates

        _rwa_templates.ensure_print_templates_table(conn)
    except Exception:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS print_templates (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT,
              category TEXT NOT NULL DEFAULT 'other',
              tags_json TEXT NOT NULL DEFAULT '[]',
              doc_type TEXT NOT NULL DEFAULT 'file'
                CHECK(doc_type IN ('file','static')),
              filename TEXT,
              original_name TEXT,
              mime_type TEXT,
              size_bytes INTEGER,
              static_path TEXT,
              status TEXT NOT NULL DEFAULT 'published'
                CHECK(status IN ('draft','published','archived')),
              created_by TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_print_templates_cat
              ON print_templates(status, category, updated_at DESC);
            """
        )
    conn.commit()


def ensure_bank_account_columns(conn: sqlite3.Connection) -> None:
    """Add UPI / QR columns on older bank_accounts tables."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(bank_accounts)").fetchall()}
    alters = [
        ("upi_id", "ALTER TABLE bank_accounts ADD COLUMN upi_id TEXT"),
        ("upi_name", "ALTER TABLE bank_accounts ADD COLUMN upi_name TEXT"),
        ("qr_filename", "ALTER TABLE bank_accounts ADD COLUMN qr_filename TEXT"),
    ]
    for name, sql in alters:
        if name not in cols:
            conn.execute(sql)
    conn.commit()


def ensure_otp_pending_columns(conn: sqlite3.Connection) -> None:
    """Store unverified email/phone on OTP rows until code is confirmed."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(otp_challenges)").fetchall()}
    alters = [
        ("pending_email", "ALTER TABLE otp_challenges ADD COLUMN pending_email TEXT"),
        ("pending_phone", "ALTER TABLE otp_challenges ADD COLUMN pending_phone TEXT"),
    ]
    for name, sql in alters:
        if name not in cols:
            conn.execute(sql)
    conn.commit()


def ensure_notice_pin_order(conn: sqlite3.Connection) -> None:
    """Add pin_order so EC can reorder pinned board notices."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notices)").fetchall()}
    if "pin_order" not in cols:
        conn.execute("ALTER TABLE notices ADD COLUMN pin_order INTEGER NOT NULL DEFAULT 0")
        pinned = conn.execute(
            "SELECT id FROM notices WHERE pinned = 1 ORDER BY published_at DESC, id ASC"
        ).fetchall()
        for idx, row in enumerate(pinned):
            conn.execute("UPDATE notices SET pin_order = ? WHERE id = ?", (idx, row[0]))
        conn.commit()


def ensure_notice_audience(conn: sqlite3.Connection) -> None:
    """members (default colony board) vs public (pre-login landing)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notices)").fetchall()}
    if "audience" not in cols:
        conn.execute(
            "ALTER TABLE notices ADD COLUMN audience TEXT NOT NULL DEFAULT 'members'"
        )
        conn.commit()
    # Normalize legacy/blank values.
    conn.execute(
        """
        UPDATE notices
        SET audience = 'members'
        WHERE audience IS NULL OR TRIM(audience) = '' OR audience NOT IN ('members', 'public')
        """
    )
    conn.commit()


def ensure_notice_shares_table(conn: sqlite3.Connection) -> None:
    """Draft collaboration shares (selected EC members)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notice_shares (
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          can_edit INTEGER NOT NULL DEFAULT 1,
          shared_at TEXT NOT NULL,
          shared_by TEXT,
          PRIMARY KEY (notice_id, house_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notice_shares_house ON notice_shares(house_id);
        """
    )
    conn.commit()


def ensure_notice_engagement_tables(conn: sqlite3.Connection) -> None:
    """Likes and comments on published colony-board notices."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notice_likes (
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (notice_id, house_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notice_likes_notice ON notice_likes(notice_id);

        CREATE TABLE IF NOT EXISTS notice_comments (
          id TEXT PRIMARY KEY,
          notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
          house_id TEXT NOT NULL,
          author_name TEXT,
          body TEXT NOT NULL,
          created_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active', 'hidden', 'deleted'))
        );
        CREATE INDEX IF NOT EXISTS idx_notice_comments_notice
          ON notice_comments(notice_id, created_at ASC);
        """
    )
    conn.commit()


MEMBER_RELATIONS = ("owner", "spouse", "parent", "child", "other")


def ensure_household_members_table(conn: sqlite3.Connection) -> None:
    """People who can log in for a plot (owner + delegates).

    Owners may mark a delegate as view_only (read notices/dues/directory;
    cannot post concerns, like/comment, edit household, or use EC desk).
    """
    import secrets as _secrets

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS household_members (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          relation TEXT NOT NULL DEFAULT 'owner'
            CHECK(relation IN ('owner','spouse','parent','child','other')),
          is_primary INTEGER NOT NULL DEFAULT 0,
          is_primary_delegate INTEGER NOT NULL DEFAULT 0,
          can_manage INTEGER NOT NULL DEFAULT 0,
          view_only INTEGER NOT NULL DEFAULT 0,
          name TEXT NOT NULL,
          title TEXT,
          email TEXT,
          phone TEXT,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active','inactive')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_household_members_house
          ON household_members(house_id, status);
        CREATE INDEX IF NOT EXISTS idx_household_members_email
          ON household_members(email);
        """
    )

    member_cols = {row[1] for row in conn.execute("PRAGMA table_info(household_members)").fetchall()}
    if "view_only" not in member_cols:
        conn.execute("ALTER TABLE household_members ADD COLUMN view_only INTEGER NOT NULL DEFAULT 0")
    # Refresh columns after possible alter
    member_cols = {row[1] for row in conn.execute("PRAGMA table_info(household_members)").fetchall()}
    if "photo_filename" not in member_cols:
        conn.execute("ALTER TABLE household_members ADD COLUMN photo_filename TEXT")
    member_cols = {row[1] for row in conn.execute("PRAGMA table_info(household_members)").fetchall()}
    if "is_primary_delegate" not in member_cols:
        conn.execute(
            "ALTER TABLE household_members ADD COLUMN is_primary_delegate INTEGER NOT NULL DEFAULT 0"
        )
    # At most one primary delegate per plot (active).
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_household_one_primary_delegate
          ON household_members(house_id)
          WHERE is_primary_delegate = 1 AND status = 'active'
        """
    )

    sess_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "member_id" not in sess_cols and sess_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN member_id TEXT")

    otp_cols = {row[1] for row in conn.execute("PRAGMA table_info(otp_challenges)").fetchall()}
    if "member_id" not in otp_cols and otp_cols:
        conn.execute("ALTER TABLE otp_challenges ADD COLUMN member_id TEXT")

    comment_cols = {row[1] for row in conn.execute("PRAGMA table_info(notice_comments)").fetchall()}
    if "member_id" not in comment_cols and comment_cols:
        conn.execute("ALTER TABLE notice_comments ADD COLUMN member_id TEXT")

    # Seed one primary owner member per plot from the residents row (before likes migration).
    plots = conn.execute(
        """
        SELECT house_id, name, title, email, phone, status, created_at, updated_at
        FROM residents
        WHERE house_id != ?
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchall()
    now = utc_now()
    for r in plots:
        exists = conn.execute(
            "SELECT 1 FROM household_members WHERE house_id = ? LIMIT 1",
            (r["house_id"],),
        ).fetchone()
        if exists:
            continue
        mid = f"hm_{_secrets.token_hex(8)}"
        conn.execute(
            """
            INSERT INTO household_members(
              id, house_id, relation, is_primary, is_primary_delegate, can_manage, view_only,
              name, title, email, phone, status, created_at, updated_at
            ) VALUES (?, ?, 'owner', 1, 0, 1, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                r["house_id"],
                r["name"] or r["house_id"],
                r["title"],
                (r["email"] or None),
                (r["phone"] or None),
                r["status"] or "active",
                r["created_at"] or now,
                r["updated_at"] or now,
            ),
        )

    like_cols = {row[1] for row in conn.execute("PRAGMA table_info(notice_likes)").fetchall()}
    if "member_id" not in like_cols:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notice_likes_v2 (
              notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
              member_id TEXT NOT NULL,
              house_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (notice_id, member_id)
            );
            """
        )
        old = conn.execute("SELECT notice_id, house_id, created_at FROM notice_likes").fetchall()
        for row in old:
            mid = conn.execute(
                """
                SELECT id FROM household_members
                WHERE house_id = ? AND status = 'active'
                ORDER BY is_primary DESC, created_at ASC LIMIT 1
                """,
                (row[1],),
            ).fetchone()
            if not mid:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO notice_likes_v2(notice_id, member_id, house_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (row[0], mid[0], row[1], row[2]),
            )
        conn.executescript(
            """
            DROP TABLE IF EXISTS notice_likes;
            ALTER TABLE notice_likes_v2 RENAME TO notice_likes;
            CREATE INDEX IF NOT EXISTS idx_notice_likes_notice ON notice_likes(notice_id);
            """
        )

    conn.commit()


def ensure_access_events_table(conn: sqlite3.Connection) -> None:
    """Super-admin observability: who used which app functions."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS access_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          house_id TEXT,
          actor_name TEXT,
          role TEXT,
          is_superadmin INTEGER NOT NULL DEFAULT 0,
          event_type TEXT NOT NULL DEFAULT 'api',
          method TEXT,
          path TEXT,
          action TEXT NOT NULL,
          status_code INTEGER,
          panel TEXT,
          detail TEXT,
          ip TEXT,
          user_agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_access_events_created ON access_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_access_events_house ON access_events(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_access_events_action ON access_events(action, created_at DESC);
        """
    )
    conn.commit()


def ensure_info_documents_table(conn: sqlite3.Connection) -> None:
    """Information Centre: RWA documents for all members."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS info_folders (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          title_hi TEXT,
          summary TEXT,
          parent_id TEXT,
          sort_order INTEGER NOT NULL DEFAULT 100,
          audience TEXT NOT NULL DEFAULT 'all'
            CHECK(audience IN ('all','ec','restricted')),
          allowed_member_ids TEXT NOT NULL DEFAULT '[]',
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_info_folders_sort
          ON info_folders(sort_order, title COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_info_folders_parent
          ON info_folders(parent_id, sort_order, title COLLATE NOCASE);

        CREATE TABLE IF NOT EXISTS info_documents (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          summary TEXT,
          category TEXT NOT NULL DEFAULT 'general',
          folder_id TEXT,
          doc_type TEXT NOT NULL DEFAULT 'file'
            CHECK(doc_type IN ('file','html','link')),
          filename TEXT,
          original_name TEXT,
          mime_type TEXT,
          size_bytes INTEGER,
          external_url TEXT,
          status TEXT NOT NULL DEFAULT 'draft'
            CHECK(status IN ('draft','published','archived')),
          audience TEXT NOT NULL DEFAULT 'all'
            CHECK(audience IN ('all','ec','restricted')),
          allowed_member_ids TEXT NOT NULL DEFAULT '[]',
          published_at TEXT,
          published_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_info_docs_status
          ON info_documents(status, category, published_at DESC);
        """
    )
    # Existing DBs may predate folder_id / parent_id — add columns before indexes that need them.
    folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_folders)").fetchall()}
    if "parent_id" not in folder_cols:
        conn.execute("ALTER TABLE info_folders ADD COLUMN parent_id TEXT")
        folder_cols.add("parent_id")
    if "audience" not in folder_cols:
        conn.execute(
            "ALTER TABLE info_folders ADD COLUMN audience TEXT NOT NULL DEFAULT 'all'"
        )
        folder_cols.add("audience")
    if "allowed_member_ids" not in folder_cols:
        conn.execute(
            "ALTER TABLE info_folders ADD COLUMN allowed_member_ids TEXT NOT NULL DEFAULT '[]'"
        )
        folder_cols.add("allowed_member_ids")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_folders_parent
          ON info_folders(parent_id, sort_order, title COLLATE NOCASE)
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
    if "audience" not in cols:
        conn.execute(
            "ALTER TABLE info_documents ADD COLUMN audience TEXT NOT NULL DEFAULT 'all'"
        )
        cols.add("audience")
    if "folder_id" not in cols:
        conn.execute("ALTER TABLE info_documents ADD COLUMN folder_id TEXT")
        cols.add("folder_id")
    if "external_url" not in cols:
        conn.execute("ALTER TABLE info_documents ADD COLUMN external_url TEXT")
        cols.add("external_url")
    if "allowed_member_ids" not in cols:
        conn.execute(
            "ALTER TABLE info_documents ADD COLUMN allowed_member_ids TEXT NOT NULL DEFAULT '[]'"
        )
        cols.add("allowed_member_ids")
    # Older installs may lack 'link' doc_type and/or 'restricted' audience in CHECK — rebuild.
    create_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='info_documents'"
    ).fetchone()
    create_sql = (create_row[0] or "") if create_row else ""
    needs_rebuild = bool(
        create_sql
        and (
            "'link'" not in create_sql
            or "'restricted'" not in create_sql
            or "allowed_member_ids" not in create_sql
        )
    )
    if needs_rebuild:
        conn.executescript(
            """
            CREATE TABLE info_documents__acl (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              summary TEXT,
              category TEXT NOT NULL DEFAULT 'general',
              folder_id TEXT,
              doc_type TEXT NOT NULL DEFAULT 'file'
                CHECK(doc_type IN ('file','html','link')),
              filename TEXT,
              original_name TEXT,
              mime_type TEXT,
              size_bytes INTEGER,
              external_url TEXT,
              status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','published','archived')),
              audience TEXT NOT NULL DEFAULT 'all'
                CHECK(audience IN ('all','ec','restricted')),
              allowed_member_ids TEXT NOT NULL DEFAULT '[]',
              published_at TEXT,
              published_by TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              title_hi TEXT,
              summary_hi TEXT,
              has_html_hi INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        # Copy with optional bilingual / ACL columns from older schemas.
        src_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        select_bits = [
            "id",
            "title",
            "summary",
            "category",
            "folder_id" if "folder_id" in src_cols else "NULL AS folder_id",
            "doc_type",
            "filename",
            "original_name",
            "mime_type",
            "size_bytes",
            "external_url" if "external_url" in src_cols else "NULL AS external_url",
            "status",
            "audience" if "audience" in src_cols else "'all' AS audience",
            (
                "allowed_member_ids"
                if "allowed_member_ids" in src_cols
                else "'[]' AS allowed_member_ids"
            ),
            "published_at",
            "published_by",
            "created_at",
            "updated_at",
            "title_hi" if "title_hi" in src_cols else "NULL AS title_hi",
            "summary_hi" if "summary_hi" in src_cols else "NULL AS summary_hi",
            "has_html_hi" if "has_html_hi" in src_cols else "0 AS has_html_hi",
        ]
        conn.execute(
            f"""
            INSERT INTO info_documents__acl(
              id, title, summary, category, folder_id, doc_type, filename, original_name,
              mime_type, size_bytes, external_url, status, audience, allowed_member_ids,
              published_at, published_by, created_at, updated_at, title_hi, summary_hi, has_html_hi
            )
            SELECT {", ".join(select_bits)} FROM info_documents
            """
        )
        conn.execute("DROP TABLE info_documents")
        conn.execute("ALTER TABLE info_documents__acl RENAME TO info_documents")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
    # Folders: rebuild CHECK if audience cannot be 'restricted' (ALTER alone does not widen CHECK).
    folder_create = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='info_folders'"
    ).fetchone()
    folder_sql = (folder_create[0] or "") if folder_create else ""
    if folder_sql and (
        "audience" not in folder_sql
        or "'restricted'" not in folder_sql
        or "allowed_member_ids" not in folder_sql
    ):
        conn.executescript(
            """
            CREATE TABLE info_folders__acl (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              title_hi TEXT,
              summary TEXT,
              parent_id TEXT,
              sort_order INTEGER NOT NULL DEFAULT 100,
              audience TEXT NOT NULL DEFAULT 'all'
                CHECK(audience IN ('all','ec','restricted')),
              allowed_member_ids TEXT NOT NULL DEFAULT '[]',
              created_by TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        fsrc = {row[1] for row in conn.execute("PRAGMA table_info(info_folders)").fetchall()}
        fbits = [
            "id",
            "title",
            "title_hi" if "title_hi" in fsrc else "NULL AS title_hi",
            "summary" if "summary" in fsrc else "NULL AS summary",
            "parent_id" if "parent_id" in fsrc else "NULL AS parent_id",
            "sort_order" if "sort_order" in fsrc else "100 AS sort_order",
            "audience" if "audience" in fsrc else "'all' AS audience",
            (
                "allowed_member_ids"
                if "allowed_member_ids" in fsrc
                else "'[]' AS allowed_member_ids"
            ),
            "created_by" if "created_by" in fsrc else "NULL AS created_by",
            "created_at",
            "updated_at",
        ]
        conn.execute(
            f"""
            INSERT INTO info_folders__acl(
              id, title, title_hi, summary, parent_id, sort_order,
              audience, allowed_member_ids, created_by, created_at, updated_at
            )
            SELECT {", ".join(fbits)} FROM info_folders
            """
        )
        conn.execute("DROP TABLE info_folders")
        conn.execute("ALTER TABLE info_folders__acl RENAME TO info_folders")
        folder_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_folders)").fetchall()}
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_docs_folder
          ON info_documents(folder_id, status, published_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_docs_status
          ON info_documents(status, category, published_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_folders_parent
          ON info_folders(parent_id, sort_order, title COLLATE NOCASE)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_info_folders_sort
          ON info_folders(sort_order, title COLLATE NOCASE)
        """
    )
    # Seed a registration folder once (for bye-laws / registration certificates).
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO info_folders(
          id, title, title_hi, summary, sort_order, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "folder_registration",
            "Society Registration",
            "सोसाइटी पंजीकरण",
            "Registration certificate, resolutions, member lists, and related drafts.",
            10,
            "system",
            now,
            now,
        ),
    )
    # Seed readable HTML edition of the HP Societies Registration Act (link → /documents/…).
    ensure_bilingual_content_columns(conn)
    act_id = "info_hp_societies_act_2006_html"
    existing_act = conn.execute(
        "SELECT id FROM info_documents WHERE id = ?", (act_id,)
    ).fetchone()
    if not existing_act:
        info_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        if "external_url" in info_cols:
            conn.execute(
                """
                INSERT INTO info_documents(
                  id, title, summary, category, folder_id, doc_type, filename, original_name,
                  mime_type, size_bytes, external_url, status, audience, published_at, published_by,
                  created_at, updated_at, title_hi, summary_hi, has_html_hi
                ) VALUES (
                  ?, ?, ?, ?, ?, 'link', NULL, ?, 'text/html', 0, ?, 'published', 'all',
                  ?, 'system', ?, ?, ?, ?, 0
                )
                """,
                (
                    act_id,
                    "The Himachal Pradesh Societies Registration Act, 2006",
                    "Readable HTML edition of Act No. 25 of 2006 — chapters and sections for browsing in the portal.",
                    "bylaws",
                    "folder_registration",
                    "hp-societies-registration-act-2006.html",
                    "/documents/hp-societies-registration-act-2006.html",
                    now,
                    now,
                    now,
                    "हिमाचल प्रदेश सोसाइटी पंजीकरण अधिनियम, 2006",
                    "अधिनियम की पठनीय HTML प्रति — अध्याय और धाराएँ।",
                ),
            )
    bylaws_id = "info_mhws_sanyard_rules_bylaws_html"
    existing_bylaws = conn.execute(
        "SELECT id FROM info_documents WHERE id = ?", (bylaws_id,)
    ).fetchone()
    if not existing_bylaws:
        info_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        if "external_url" in info_cols:
            conn.execute(
                """
                INSERT INTO info_documents(
                  id, title, summary, category, folder_id, doc_type, filename, original_name,
                  mime_type, size_bytes, external_url, status, audience, published_at, published_by,
                  created_at, updated_at, title_hi, summary_hi, has_html_hi
                ) VALUES (
                  ?, ?, ?, ?, ?, 'link', NULL, ?, 'text/html', 0, ?, 'published', 'all',
                  ?, 'system', ?, ?, ?, ?, 0
                )
                """,
                (
                    bylaws_id,
                    "Himuda Housing Colony Sanyard — Rules & Bye-laws",
                    "Bilingual (Hindi / English) readable edition of Himuda Housing Colony Sanyard rules and bye-laws.",
                    "bylaws",
                    "folder_registration",
                    "mhws-sanyard-rules-bylaws.html",
                    "/documents/mhws-sanyard-rules-bylaws.html",
                    now,
                    now,
                    now,
                    "हाउसिंग कॉलोनी सन्यारड — नियम एवं उपनियम",
                    "एमएचडब्ल्यूएस सन्यारड नियमों व उपनियमों का द्विभाषी पठनीय संस्करण।",
                ),
            )
    # Court Case No 01 folder + Civil Suit 2023 path-right summary (link → /documents/…).
    court_folder_row = conn.execute(
        "SELECT id FROM info_folders WHERE title = ? COLLATE NOCASE LIMIT 1",
        ("Court Case No 01",),
    ).fetchone()
    if court_folder_row:
        court_folder_id = court_folder_row[0]
    else:
        court_folder_id = "folder_court_case_01"
        conn.execute(
            """
            INSERT OR IGNORE INTO info_folders(
              id, title, title_hi, summary, sort_order, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                court_folder_id,
                "Court Case No 01",
                None,
                "Civil suit papers and readable summaries related to the colony path / access dispute.",
                20,
                "system",
                now,
                now,
            ),
        )
    suit_id = "info_civil_suit_2023_path_right_html"
    suit_title = "Court Case No 01 — Path / link road dispute (Civil Suit 2023)"
    suit_summary = (
        "Pending Senior Civil Judge, Mandi matter (~086/2023): plaint, HIMUDA & colony/Plot 12-A replies, "
        "and plaintiff replication on the Himuda Housing Colony Sanyardh path / gate dispute. Further hearings expected."
    )
    existing_suit = conn.execute(
        "SELECT id FROM info_documents WHERE id = ?", (suit_id,)
    ).fetchone()
    if not existing_suit:
        info_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        if "external_url" in info_cols:
            conn.execute(
                """
                INSERT INTO info_documents(
                  id, title, summary, category, folder_id, doc_type, filename, original_name,
                  mime_type, size_bytes, external_url, status, audience, published_at, published_by,
                  created_at, updated_at, title_hi, summary_hi, has_html_hi
                ) VALUES (
                  ?, ?, ?, ?, ?, 'link', NULL, ?, 'text/html', 0, ?, 'published', 'all',
                  ?, 'system', ?, ?, ?, ?, 0
                )
                """,
                (
                    suit_id,
                    suit_title,
                    suit_summary,
                    "legal",
                    court_folder_id,
                    "civil-suit-2023-sanyardh-path-right.html",
                    "/documents/civil-suit-2023-sanyardh-path-right.html",
                    now,
                    now,
                    now,
                    None,
                    None,
                ),
            )
    else:
        # Keep published docs under the Court Case folder and refresh briefing metadata.
        conn.execute(
            """
            UPDATE info_documents
               SET folder_id = ?,
                   title = ?,
                   summary = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (court_folder_id, suit_title, suit_summary, now, suit_id),
        )
        conn.execute(
            """
            UPDATE info_folders
               SET summary = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                "Pending civil suit on colony path / link road access: plaint, HIMUDA & colony replies, plaintiff replication. Further hearings expected.",
                now,
                court_folder_id,
            ),
        )
    conn.commit()


def ensure_colony_works_table(conn: sqlite3.Connection) -> None:
    """Works & Events: maintenance, projects, activities, events."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS colony_works (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          kind TEXT NOT NULL
            CHECK(kind IN ('maintenance','development','activity','event')),
          category TEXT NOT NULL DEFAULT 'general',
          summary TEXT,
          details TEXT,
          benefits TEXT,
          timeline_notes TEXT,
          milestones_json TEXT,
          status TEXT NOT NULL DEFAULT 'planned'
            CHECK(status IN ('planned','approved','in_progress','on_hold','completed','closed','cancelled')),
          visibility TEXT NOT NULL DEFAULT 'published'
            CHECK(visibility IN ('draft','published')),
          location TEXT,
          start_date TEXT,
          end_date TEXT,
          event_date TEXT,
          estimated_cost INTEGER,
          actual_cost INTEGER,
          cost_notes TEXT,
          contractor_name TEXT,
          contractor_contact TEXT,
          contractor_details TEXT,
          funding_json TEXT,
          assigned_to TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          closed_at TEXT,
          closed_by TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_colony_works_status
          ON colony_works(status, kind, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_colony_works_visibility
          ON colony_works(visibility, status, updated_at DESC);
        """
    )
    # Additive columns for DBs created before benefits/timeline fields.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(colony_works)").fetchall()}
    for name, sql in (
        ("benefits", "ALTER TABLE colony_works ADD COLUMN benefits TEXT"),
        ("timeline_notes", "ALTER TABLE colony_works ADD COLUMN timeline_notes TEXT"),
        ("milestones_json", "ALTER TABLE colony_works ADD COLUMN milestones_json TEXT"),
    ):
        if name not in cols:
            conn.execute(sql)
    conn.commit()


def ensure_colony_campaigns_tables(conn: sqlite3.Connection) -> None:
    """Campaigns and funding drives — plantation drives, member contributions."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS colony_campaigns (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'general'
            CHECK(kind IN ('plantation','maintenance','development','welfare','event','general')),
          summary TEXT,
          details TEXT,
          status TEXT NOT NULL DEFAULT 'draft'
            CHECK(status IN ('draft','active','paused','completed','cancelled')),
          audience TEXT NOT NULL DEFAULT 'members'
            CHECK(audience IN ('members','public')),
          target_amount INTEGER,
          deadline TEXT,
          event_date TEXT,
          location TEXT,
          payment_instructions TEXT,
          work_id TEXT,
          mode TEXT NOT NULL DEFAULT 'both'
            CHECK(mode IN ('pledge','funding','both')),
          pledge_amount_type TEXT DEFAULT 'discretionary'
            CHECK(pledge_amount_type IN ('fixed','discretionary')),
          fixed_pledge_amount INTEGER,
          image_file TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_colony_campaigns_status
          ON colony_campaigns(status, audience, updated_at DESC);
        CREATE TABLE IF NOT EXISTS campaign_pledges (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          member_id TEXT,
          contributor_name TEXT NOT NULL,
          amount INTEGER NOT NULL CHECK(amount > 0),
          note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES colony_campaigns(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_pledges_campaign
          ON campaign_pledges(campaign_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS campaign_contributions (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          member_id TEXT,
          contributor_name TEXT,
          amount INTEGER NOT NULL CHECK(amount > 0),
          method TEXT NOT NULL DEFAULT 'upi'
            CHECK(method IN ('upi','cash','bank_transfer','cheque','other')),
          paid_on TEXT,
          note TEXT,
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','verified','rejected')),
          files_json TEXT,
          verified_by TEXT,
          verified_at TEXT,
          rejected_reason TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES colony_campaigns(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_campaign_contributions_campaign
          ON campaign_contributions(campaign_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_campaign_contributions_house
          ON campaign_contributions(house_id, campaign_id);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(colony_campaigns)").fetchall()}
    for name, sql in (
        ("mode", "ALTER TABLE colony_campaigns ADD COLUMN mode TEXT NOT NULL DEFAULT 'both'"),
        ("pledge_amount_type", "ALTER TABLE colony_campaigns ADD COLUMN pledge_amount_type TEXT DEFAULT 'discretionary'"),
        ("fixed_pledge_amount", "ALTER TABLE colony_campaigns ADD COLUMN fixed_pledge_amount INTEGER"),
        ("image_file", "ALTER TABLE colony_campaigns ADD COLUMN image_file TEXT"),
    ):
        if name not in cols:
            conn.execute(sql)
    conn.commit()


def ensure_meeting_proceedings_table(conn: sqlite3.Connection) -> None:
    """Proceedings / MOM register — General House and Executive Committee meetings."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meeting_proceedings (
          id TEXT PRIMARY KEY,
          register_no INTEGER NOT NULL DEFAULT 1,
          meeting_type TEXT NOT NULL
            CHECK(meeting_type IN ('gh','ec')),
          meeting_subtype TEXT NOT NULL DEFAULT 'regular',
          title TEXT NOT NULL,
          meeting_date TEXT NOT NULL,
          meeting_time TEXT,
          venue TEXT,
          chair_person TEXT,
          members_present TEXT,
          members_absent TEXT,
          quorum_met INTEGER,
          agenda TEXT,
          proceedings_body TEXT,
          resolutions_json TEXT,
          action_items_json TEXT,
          next_meeting_date TEXT,
          signed_by TEXT,
          approved_at TEXT,
          status TEXT NOT NULL DEFAULT 'draft'
            CHECK(status IN ('draft','published','archived')),
          visibility TEXT NOT NULL DEFAULT 'published'
            CHECK(visibility IN ('draft','published')),
          published_at TEXT,
          published_by TEXT,
          created_by TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_proceedings_type_date
          ON meeting_proceedings(meeting_type, meeting_date DESC, status);
        CREATE INDEX IF NOT EXISTS idx_proceedings_register
          ON meeting_proceedings(meeting_type, substr(meeting_date, 1, 4), register_no);
        """
    )
    conn.commit()


def ensure_grievances_table(conn: sqlite3.Connection) -> None:
    """Create grievances + message-thread tables on older DBs."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS grievances (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          category TEXT NOT NULL,
          subject TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open'
            CHECK(status IN ('open','in_progress','resolved','closed')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          response TEXT,
          responded_at TEXT,
          responded_by_house_id TEXT,
          responded_by_name TEXT
        );
        CREATE TABLE IF NOT EXISTS grievance_messages (
          id TEXT PRIMARY KEY,
          grievance_id TEXT NOT NULL REFERENCES grievances(id) ON DELETE CASCADE,
          author_house_id TEXT,
          author_name TEXT NOT NULL,
          author_role TEXT NOT NULL DEFAULT 'resident'
            CHECK(author_role IN ('resident','ec')),
          body TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_grievances_house ON grievances(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_grievances_status ON grievances(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_grievance_messages ON grievance_messages(grievance_id, created_at ASC);
        """
    )
    conn.commit()
    # Backfill opening + EC reply messages for rows that predate the thread table.
    rows = conn.execute("SELECT * FROM grievances").fetchall()
    for g in rows:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM grievance_messages WHERE grievance_id = ?",
            (g["id"],),
        ).fetchone()["c"]
        if count:
            continue
        res = conn.execute(
            "SELECT name FROM residents WHERE house_id = ?",
            (g["house_id"],),
        ).fetchone()
        opener_name = (res["name"] if res else None) or g["house_id"]
        conn.execute(
            """
            INSERT INTO grievance_messages(id, grievance_id, author_house_id, author_name, author_role, body, created_at)
            VALUES (?, ?, ?, ?, 'resident', ?, ?)
            """,
            (
                f"gm_{secrets.token_hex(5)}",
                g["id"],
                g["house_id"],
                opener_name,
                g["body"] or g["subject"],
                g["created_at"],
            ),
        )
        if (g["response"] or "").strip():
            conn.execute(
                """
                INSERT INTO grievance_messages(id, grievance_id, author_house_id, author_name, author_role, body, created_at)
                VALUES (?, ?, ?, ?, 'ec', ?, ?)
                """,
                (
                    f"gm_{secrets.token_hex(5)}",
                    g["id"],
                    g["responded_by_house_id"],
                    g["responded_by_name"] or "EC",
                    g["response"],
                    g["responded_at"] or g["updated_at"] or g["created_at"],
                ),
            )
    conn.commit()


def ensure_payment_records_tables(conn: sqlite3.Connection) -> None:
    """Per-plot payment + reimbursement claims with receipt files."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS payment_records (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          kind TEXT NOT NULL DEFAULT 'payment'
            CHECK(kind IN ('payment','reimbursement')),
          fee_year INTEGER NOT NULL,
          category TEXT NOT NULL DEFAULT 'annual_dues',
          amount INTEGER NOT NULL,
          paid_on TEXT NOT NULL,
          method TEXT NOT NULL DEFAULT 'upi'
            CHECK(method IN ('upi','bank','cash','other')),
          note TEXT,
          status TEXT NOT NULL DEFAULT 'submitted'
            CHECK(status IN ('submitted','verified','rejected','reimbursed')),
          uploaded_by_house_id TEXT,
          uploaded_by_member_id TEXT,
          uploaded_by_role TEXT NOT NULL DEFAULT 'resident'
            CHECK(uploaded_by_role IN ('resident','ec')),
          reviewed_by_house_id TEXT,
          reviewed_at TEXT,
          review_note TEXT,
          ledger_applied INTEGER NOT NULL DEFAULT 0,
          reimbursed_at TEXT,
          reimbursed_by_house_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_payment_records_house
          ON payment_records(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_payment_records_status
          ON payment_records(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS payment_receipt_files (
          id TEXT PRIMARY KEY,
          record_id TEXT NOT NULL REFERENCES payment_records(id) ON DELETE CASCADE,
          filename TEXT NOT NULL,
          original_name TEXT,
          mime TEXT NOT NULL,
          size_bytes INTEGER NOT NULL DEFAULT 0,
          width INTEGER,
          height INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_payment_receipt_files_record
          ON payment_receipt_files(record_id);
        """
    )

    # Migrate v11 → v12: add kind / reimbursed columns; rebuild if old category CHECK blocks claims.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(payment_records)").fetchall()}
    create_sql = ""
    row_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='payment_records'"
    ).fetchone()
    if row_sql and row_sql[0]:
        create_sql = row_sql[0]
    needs_rebuild = bool(cols) and (
        "kind" not in cols
        or "reimbursed" not in create_sql
        or "reimbursement" not in create_sql
    )
    if needs_rebuild:
        # FK OFF so DROP does not CASCADE-wipe payment_receipt_files (ON DELETE CASCADE).
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE payment_records_v12 (
              id TEXT PRIMARY KEY,
              house_id TEXT NOT NULL REFERENCES residents(house_id),
              kind TEXT NOT NULL DEFAULT 'payment'
                CHECK(kind IN ('payment','reimbursement')),
              fee_year INTEGER NOT NULL,
              category TEXT NOT NULL DEFAULT 'annual_dues',
              amount INTEGER NOT NULL,
              paid_on TEXT NOT NULL,
              method TEXT NOT NULL DEFAULT 'upi'
                CHECK(method IN ('upi','bank','cash','other')),
              note TEXT,
              status TEXT NOT NULL DEFAULT 'submitted'
                CHECK(status IN ('submitted','verified','rejected','reimbursed')),
              uploaded_by_house_id TEXT,
              uploaded_by_member_id TEXT,
              uploaded_by_role TEXT NOT NULL DEFAULT 'resident'
                CHECK(uploaded_by_role IN ('resident','ec')),
              reviewed_by_house_id TEXT,
              reviewed_at TEXT,
              review_note TEXT,
              ledger_applied INTEGER NOT NULL DEFAULT 0,
              reimbursed_at TEXT,
              reimbursed_by_house_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        kind_expr = "kind" if "kind" in cols else "'payment'"
        reimb_at = "reimbursed_at" if "reimbursed_at" in cols else "NULL"
        reimb_by = "reimbursed_by_house_id" if "reimbursed_by_house_id" in cols else "NULL"
        conn.execute(
            f"""
            INSERT INTO payment_records_v12(
              id, house_id, kind, fee_year, category, amount, paid_on, method, note, status,
              uploaded_by_house_id, uploaded_by_member_id, uploaded_by_role,
              reviewed_by_house_id, reviewed_at, review_note, ledger_applied,
              reimbursed_at, reimbursed_by_house_id, created_at, updated_at
            )
            SELECT
              id, house_id, COALESCE({kind_expr}, 'payment'), fee_year, category, amount, paid_on, method, note, status,
              uploaded_by_house_id, uploaded_by_member_id, uploaded_by_role,
              reviewed_by_house_id, reviewed_at, review_note, ledger_applied,
              {reimb_at}, {reimb_by}, created_at, updated_at
            FROM payment_records
            """
        )
        conn.execute("DROP TABLE payment_records")
        conn.execute("ALTER TABLE payment_records_v12 RENAME TO payment_records")
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(payment_records)").fetchall()}
        if cols and "reimbursed_at" not in cols:
            conn.execute("ALTER TABLE payment_records ADD COLUMN reimbursed_at TEXT")
        if cols and "reimbursed_by_house_id" not in cols:
            conn.execute("ALTER TABLE payment_records ADD COLUMN reimbursed_by_house_id TEXT")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_records_house ON payment_records(house_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_records_status ON payment_records(status, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_records_kind ON payment_records(kind, status, created_at DESC)"
    )
    ensure_treasury_columns_on_table(conn, "payment_records")
    conn.commit()


def ensure_no_dues_requests_table(conn: sqlite3.Connection) -> None:
    """Resident requests for No Dues Certificates; issuer generates a downloadable PDF."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS no_dues_requests (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          status TEXT NOT NULL DEFAULT 'requested'
            CHECK(status IN ('requested','issued','rejected')),
          request_note TEXT,
          purpose TEXT NOT NULL DEFAULT '',
          requested_by_house_id TEXT,
          requested_by_member_id TEXT,
          reviewed_by_house_id TEXT,
          reviewed_at TEXT,
          review_note TEXT,
          issued_at TEXT,
          filename TEXT,
          original_name TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_no_dues_requests_house
          ON no_dues_requests(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_no_dues_requests_status
          ON no_dues_requests(status, created_at DESC);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(no_dues_requests)").fetchall()}
    if cols and "purpose" not in cols:
        conn.execute("ALTER TABLE no_dues_requests ADD COLUMN purpose TEXT NOT NULL DEFAULT ''")
    ensure_treasury_columns_on_table(conn, "no_dues_requests")
    conn.commit()


def ensure_no_objection_requests_table(conn: sqlite3.Connection) -> None:
    """Resident requests for No Objection Certificates; issuer generates a downloadable PDF."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS no_objection_requests (
          id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL REFERENCES residents(house_id),
          status TEXT NOT NULL DEFAULT 'requested'
            CHECK(status IN ('requested','issued','rejected')),
          request_note TEXT,
          purpose TEXT NOT NULL DEFAULT '',
          requested_by_house_id TEXT,
          requested_by_member_id TEXT,
          reviewed_by_house_id TEXT,
          reviewed_at TEXT,
          review_note TEXT,
          issued_at TEXT,
          filename TEXT,
          original_name TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_no_objection_requests_house
          ON no_objection_requests(house_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_no_objection_requests_status
          ON no_objection_requests(status, created_at DESC);
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(no_objection_requests)").fetchall()}
    if cols and "purpose" not in cols:
        conn.execute("ALTER TABLE no_objection_requests ADD COLUMN purpose TEXT NOT NULL DEFAULT ''")
    ensure_treasury_columns_on_table(conn, "no_objection_requests")
    conn.commit()


TREASURY_STATUS_DEFAULT = "pending"
TREASURY_COLUMN_DEFS: list[tuple[str, str]] = [
    ("treasury_status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("treasury_validated_by", "TEXT"),
    ("treasury_validated_at", "TEXT"),
    ("treasury_confirmed_by", "TEXT"),
    ("treasury_confirmed_at", "TEXT"),
    ("treasury_note", "TEXT"),
]


def ensure_treasury_columns_on_table(conn: sqlite3.Connection, table: str) -> None:
    """Add treasury_* columns to an existing table (migrate-safe)."""
    allowed = {"payment_records", "payment_rows", "no_dues_requests", "no_objection_requests"}
    if table not in allowed:
        raise ValueError(f"Unsupported treasury table: {table}")
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if not cols:
        return
    for name, decl in TREASURY_COLUMN_DEFS:
        if name not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def ensure_treasury_columns(conn: sqlite3.Connection) -> None:
    """Ensure treasury validation columns on payments, ledger rows, and certificates."""
    # payment_rows may exist from base schema without treasury columns.
    ensure_treasury_columns_on_table(conn, "payment_rows")
    ensure_treasury_columns_on_table(conn, "payment_records")
    ensure_treasury_columns_on_table(conn, "no_dues_requests")
    ensure_treasury_columns_on_table(conn, "no_objection_requests")
    conn.commit()


def ensure_document_attestations_table(conn: sqlite3.Connection) -> None:
    """Portal HMAC attestations for EC-issued PDFs (free verify-via-QR)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS document_attestations (
          id TEXT PRIMARY KEY,
          artifact_type TEXT NOT NULL
            CHECK(artifact_type IN ('no_dues','no_objection','cash_note')),
          artifact_id TEXT NOT NULL,
          house_id TEXT,
          issuer_house_id TEXT,
          issued_at TEXT NOT NULL,
          content_sha256 TEXT NOT NULL,
          hmac_hex TEXT NOT NULL,
          stored_path TEXT,
          filename TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_document_attestations_artifact
          ON document_attestations(artifact_type, artifact_id);
        CREATE INDEX IF NOT EXISTS idx_document_attestations_house
          ON document_attestations(house_id, created_at DESC);
        """
    )
    # Expand artifact_type CHECK when an older table is present.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='document_attestations'"
    ).fetchone()
    ddl = (row[0] if row else "") or ""
    if ddl and "no_objection" not in ddl:
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_attestations_v2 (
              id TEXT PRIMARY KEY,
              artifact_type TEXT NOT NULL
                CHECK(artifact_type IN ('no_dues','no_objection','cash_note')),
              artifact_id TEXT NOT NULL,
              house_id TEXT,
              issuer_house_id TEXT,
              issued_at TEXT NOT NULL,
              content_sha256 TEXT NOT NULL,
              hmac_hex TEXT NOT NULL,
              stored_path TEXT,
              filename TEXT,
              created_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO document_attestations_v2(
              id, artifact_type, artifact_id, house_id, issuer_house_id,
              issued_at, content_sha256, hmac_hex, stored_path, filename, created_at
            )
            SELECT id, artifact_type, artifact_id, house_id, issuer_house_id,
                   issued_at, content_sha256, hmac_hex, stored_path, filename, created_at
            FROM document_attestations;
            DROP TABLE document_attestations;
            ALTER TABLE document_attestations_v2 RENAME TO document_attestations;
            CREATE INDEX IF NOT EXISTS idx_document_attestations_artifact
              ON document_attestations(artifact_type, artifact_id);
            CREATE INDEX IF NOT EXISTS idx_document_attestations_house
              ON document_attestations(house_id, created_at DESC);
            """
        )
        conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


COLONY_THREAD_ID = "msg_colony"


def ensure_messages_and_push_tables(conn: sqlite3.Connection) -> None:
    """Message center (colony + DMs) and Web Push subscriptions / prefs / outbox."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS msg_threads (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL CHECK(kind IN ('colony', 'dm', 'ai')),
          house_a TEXT,
          house_b TEXT,
          title TEXT,
          pinned_message_id TEXT,
          owner_member_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_threads_dm_pair
          ON msg_threads(house_a, house_b) WHERE kind = 'dm';
        CREATE INDEX IF NOT EXISTS idx_msg_threads_updated
          ON msg_threads(updated_at DESC);
        -- idx_msg_threads_ai_owner is created in ensure_msg_likes_and_ai after
        -- owner_member_id is ALTERed onto older msg_threads tables.

        CREATE TABLE IF NOT EXISTS msg_messages (
          id TEXT PRIMARY KEY,
          thread_id TEXT NOT NULL,
          author_member_id TEXT,
          house_id TEXT NOT NULL,
          author_name TEXT,
          body TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active'
            CHECK(status IN ('active', 'hidden', 'deleted')),
          reply_to_id TEXT,
          is_ai INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          FOREIGN KEY(thread_id) REFERENCES msg_threads(id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_messages_thread
          ON msg_messages(thread_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_msg_messages_status
          ON msg_messages(thread_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS msg_attachments (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL,
          thread_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          filename TEXT NOT NULL,
          original_name TEXT,
          mime TEXT NOT NULL,
          size_bytes INTEGER NOT NULL DEFAULT 0,
          width INTEGER,
          height INTEGER,
          created_at TEXT NOT NULL,
          FOREIGN KEY(message_id) REFERENCES msg_messages(id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_attachments_message
          ON msg_attachments(message_id);

        CREATE TABLE IF NOT EXISTS msg_reads (
          member_id TEXT NOT NULL,
          thread_id TEXT NOT NULL,
          last_read_message_id TEXT,
          last_read_at TEXT NOT NULL,
          PRIMARY KEY (member_id, thread_id)
        );

        CREATE TABLE IF NOT EXISTS push_subscriptions (
          id TEXT PRIMARY KEY,
          endpoint TEXT NOT NULL UNIQUE,
          p256dh TEXT NOT NULL,
          auth TEXT NOT NULL,
          member_id TEXT,
          house_id TEXT NOT NULL,
          user_agent TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_push_subs_house
          ON push_subscriptions(house_id);
        CREATE INDEX IF NOT EXISTS idx_push_subs_member
          ON push_subscriptions(member_id);

        CREATE TABLE IF NOT EXISTS notification_prefs (
          member_id TEXT PRIMARY KEY,
          house_id TEXT NOT NULL,
          messages INTEGER NOT NULL DEFAULT 1,
          notices INTEGER NOT NULL DEFAULT 1,
          concerns INTEGER NOT NULL DEFAULT 1,
          dues INTEGER NOT NULL DEFAULT 1,
          treasury INTEGER NOT NULL DEFAULT 1,
          no_dues INTEGER NOT NULL DEFAULT 1,
          no_objection INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS push_outbox (
          id TEXT PRIMARY KEY,
          event_type TEXT NOT NULL,
          pref_key TEXT NOT NULL,
          audience_json TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          url TEXT,
          payload_json TEXT,
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued', 'sending', 'sent', 'failed', 'skipped')),
          error TEXT,
          created_at TEXT NOT NULL,
          sent_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_push_outbox_status
          ON push_outbox(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS msg_likes (
          message_id TEXT NOT NULL,
          member_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (message_id, member_id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_likes_message ON msg_likes(message_id);
        """
    )
    now = utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO msg_threads(id, kind, house_a, house_b, title, pinned_message_id, created_at, updated_at)
        VALUES (?, 'colony', NULL, NULL, 'Colony channel', NULL, ?, ?)
        """,
        (COLONY_THREAD_ID, now, now),
    )
    pref_cols = {row[1] for row in conn.execute("PRAGMA table_info(notification_prefs)").fetchall()}
    for col in ("treasury", "no_dues", "no_objection"):
        if pref_cols and col not in pref_cols:
            conn.execute(
                f"ALTER TABLE notification_prefs ADD COLUMN {col} INTEGER NOT NULL DEFAULT 1"
            )
    conn.commit()
    ensure_msg_likes_and_ai(conn)


def ensure_msg_likes_and_ai(conn: sqlite3.Connection) -> None:
    """Likes + private AI threads (migrate older CHECK constraints)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS msg_likes (
          message_id TEXT NOT NULL,
          member_id TEXT NOT NULL,
          house_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (message_id, member_id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_likes_message ON msg_likes(message_id);
        """
    )
    thread_cols = {row[1] for row in conn.execute("PRAGMA table_info(msg_threads)").fetchall()}
    if thread_cols and "owner_member_id" not in thread_cols:
        conn.execute("ALTER TABLE msg_threads ADD COLUMN owner_member_id TEXT")

    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(msg_messages)").fetchall()}
    if msg_cols and "is_ai" not in msg_cols:
        conn.execute("ALTER TABLE msg_messages ADD COLUMN is_ai INTEGER NOT NULL DEFAULT 0")
    if msg_cols and "edited_at" not in msg_cols:
        conn.execute("ALTER TABLE msg_messages ADD COLUMN edited_at TEXT")

    # Expand kind CHECK to include 'ai' when an older table is present.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='msg_threads'"
    ).fetchone()
    ddl = (row[0] if row else "") or ""
    needs_rebuild = bool(ddl) and ("'ai'" not in ddl and '"ai"' not in ddl)
    if needs_rebuild:
        # Child tables reference msg_threads; turn FKs off for the swap.
        # PRAGMA foreign_keys only takes effect outside a transaction.
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS msg_threads_v2 (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL CHECK(kind IN ('colony', 'dm', 'ai')),
              house_a TEXT,
              house_b TEXT,
              title TEXT,
              pinned_message_id TEXT,
              owner_member_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO msg_threads_v2(
              id, kind, house_a, house_b, title, pinned_message_id, owner_member_id, created_at, updated_at
            )
            SELECT id, kind, house_a, house_b, title, pinned_message_id,
                   owner_member_id, created_at, updated_at
            FROM msg_threads;
            DROP TABLE msg_threads;
            ALTER TABLE msg_threads_v2 RENAME TO msg_threads;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_threads_dm_pair
              ON msg_threads(house_a, house_b) WHERE kind = 'dm';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_threads_ai_owner
              ON msg_threads(owner_member_id) WHERE kind = 'ai';
            CREATE INDEX IF NOT EXISTS idx_msg_threads_updated
              ON msg_threads(updated_at DESC);
            """
        )
        conn.execute("PRAGMA foreign_keys=ON")
    else:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_threads_ai_owner
              ON msg_threads(owner_member_id) WHERE kind = 'ai'
            """
        )
    conn.commit()


def ensure_bilingual_content_columns(conn: sqlite3.Connection) -> None:
    """Hindi companion fields for notices, concerns, and in-house info HTML."""
    notice_cols = {row[1] for row in conn.execute("PRAGMA table_info(notices)").fetchall()}
    if notice_cols:
        if "title_hi" not in notice_cols:
            conn.execute("ALTER TABLE notices ADD COLUMN title_hi TEXT")
        if "body_hi" not in notice_cols:
            conn.execute("ALTER TABLE notices ADD COLUMN body_hi TEXT")

    grievance_cols = {row[1] for row in conn.execute("PRAGMA table_info(grievances)").fetchall()}
    if grievance_cols:
        if "subject_hi" not in grievance_cols:
            conn.execute("ALTER TABLE grievances ADD COLUMN subject_hi TEXT")
        if "body_hi" not in grievance_cols:
            conn.execute("ALTER TABLE grievances ADD COLUMN body_hi TEXT")

    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(grievance_messages)").fetchall()}
    if msg_cols and "body_hi" not in msg_cols:
        conn.execute("ALTER TABLE grievance_messages ADD COLUMN body_hi TEXT")

    info_cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
    if info_cols:
        if "title_hi" not in info_cols:
            conn.execute("ALTER TABLE info_documents ADD COLUMN title_hi TEXT")
        if "summary_hi" not in info_cols:
            conn.execute("ALTER TABLE info_documents ADD COLUMN summary_hi TEXT")
        if "has_html_hi" not in info_cols:
            conn.execute("ALTER TABLE info_documents ADD COLUMN has_html_hi INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def hash_password(password: str, *, salt_hex: str | None = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    rounds = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return secrets.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def ensure_superadmin_account(conn: sqlite3.Connection) -> None:
    """Create/update portal super-admin (username/password) linked to a synthetic resident."""
    import os

    username = (os.environ.get("RWA_SUPERADMIN_USER") or "admin").strip().lower() or "admin"
    password = os.environ.get("RWA_SUPERADMIN_PASSWORD") or "Admin15@8"
    now = utc_now()

    conn.execute(
        """
        INSERT INTO residents(house_id, plot_no, section, name, email, phone, role, status, notes, created_at, updated_at)
        VALUES (?, 'SA', 'SA', 'Portal Super Admin', NULL, NULL, 'admin', 'active', 'system super-admin', ?, ?)
        ON CONFLICT(house_id) DO UPDATE SET
          role='admin',
          status='active',
          name='Portal Super Admin',
          updated_at=excluded.updated_at
        """,
        (SUPERADMIN_HOUSE_ID, now, now),
    )

    row = conn.execute(
        "SELECT username, password_hash FROM portal_accounts WHERE username = ?",
        (username,),
    ).fetchone()
    force = (os.environ.get("RWA_SUPERADMIN_RESET") or "").strip() in {"1", "true", "yes"}
    if row is None:
        conn.execute(
            """
            INSERT INTO portal_accounts(username, password_hash, house_id, is_superadmin, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (username, hash_password(password), SUPERADMIN_HOUSE_ID, now, now),
        )
    elif force:
        conn.execute(
            """
            UPDATE portal_accounts
            SET password_hash=?, house_id=?, is_superadmin=1, updated_at=?
            WHERE username=?
            """,
            (hash_password(password), SUPERADMIN_HOUSE_ID, now, username),
        )
    conn.commit()


def seed_from_ledger(conn: sqlite3.Connection, *, reset: bool = False) -> dict:
    if reset:
        conn.executescript(
            """
            DELETE FROM payment_rows;
            DELETE FROM payment_ledgers;
            DELETE FROM otp_challenges;
            DELETE FROM sessions;
            DELETE FROM notices;
            DELETE FROM bank_accounts;
            DELETE FROM residents;
            """
        )

    now = utc_now()
    for plot, name, bal_prev, fee, total, received, section, remarks in LEDGER_ROWS:
        house_id = normalize_house_id(plot, section)
        conn.execute(
            """
            INSERT INTO residents(house_id, plot_no, section, name, email, phone, role, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, 'resident', 'active', ?, ?, ?)
            ON CONFLICT(house_id) DO UPDATE SET
              name=excluded.name,
              plot_no=excluded.plot_no,
              section=excluded.section,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            (house_id, house_id, section, name, remarks or None, now, now),
        )

    # Bootstrap EC admin: Plot 43 (can be changed later via promote API).
    conn.execute(
        "UPDATE residents SET role = 'admin', updated_at = ? WHERE house_id = '43'",
        (now,),
    )
    cur = conn.execute(
        "INSERT INTO payment_ledgers(source, as_of, notes, imported_at) VALUES (?, ?, ?, ?)",
        (
            "Himuda Housing Colony Sanyard LIST.pdf",
            BANK["ledger_as_of"],
            "Registration & subscription fees status as of 15-06-2026",
            now,
        ),
    )
    ledger_id = cur.lastrowid
    for plot, name, bal_prev, fee, total, received, section, remarks in LEDGER_ROWS:
        house_id = normalize_house_id(plot, section)
        outstanding = int(total) - int(received)
        conn.execute(
            """
            INSERT INTO payment_rows(
              ledger_id, house_id, balance_prev, fee_year, fee_amount,
              total_due, amount_received, balance_outstanding, remarks
            ) VALUES (?, ?, ?, 2026, ?, ?, ?, ?, ?)
            ON CONFLICT(ledger_id, house_id) DO UPDATE SET
              balance_prev=excluded.balance_prev,
              fee_amount=excluded.fee_amount,
              total_due=excluded.total_due,
              amount_received=excluded.amount_received,
              balance_outstanding=excluded.balance_outstanding,
              remarks=excluded.remarks
            """,
            (ledger_id, house_id, bal_prev, fee, total, received, outstanding, remarks or None),
        )

    conn.execute(
        """
        INSERT INTO bank_accounts(label, bank_name, account_no, ifsc, is_primary)
        SELECT 'Society dues', ?, ?, ?, 1
        WHERE NOT EXISTS (SELECT 1 FROM bank_accounts WHERE is_primary=1)
        """,
        (BANK["bank_name"], BANK["account_no"], BANK["ifsc"]),
    )

    conn.execute(
        """
        INSERT OR REPLACE INTO notices(id, title, body, category, pinned, pin_order, published_at, published_by, status)
        VALUES (?, ?, ?, 'general', 1, 0, ?, NULL, 'published')
        """,
        (
            "n_welcome",
            "Welcome to the Himuda Housing Colony Sanyard resident portal",
            "**Official colony board**\n\n"
            "Use this portal for notices, directory, payment dues, and profile updates.\n\n"
            "**How to sign in**\n"
            "Enter your plot / house number. A one-time code is emailed to the address "
            "registered with the RWA.",
            now,
        ),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO notices(id, title, body, category, pinned, pin_order, published_at, published_by, status)
        VALUES (?, ?, ?, 'payments', 0, 0, ?, NULL, 'published')
        """,
        (
            "n_bank",
            "Deposit dues — Bank of Baroda Mandi",
            f"A/C {BANK['account_no']} · IFSC {BANK['ifsc']}. "
            f"Ledger snapshot imported from HIMUDA list dated {BANK['ledger_as_of']}.",
            now,
        ),
    )
    conn.commit()
    counts = {
        "residents": conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0],
        "payment_rows": conn.execute("SELECT COUNT(*) FROM payment_rows").fetchone()[0],
        "notices": conn.execute("SELECT COUNT(*) FROM notices").fetchone()[0],
    }
    return counts


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def ensure_db(db_path: pathlib.Path, *, seed: bool = True) -> pathlib.Path:
    conn = connect(db_path)
    try:
        init_schema(conn)
        n = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
        if seed and n == 0:
            seed_from_ledger(conn)
    finally:
        conn.close()
    return db_path


def main() -> int:
    import argparse

    site_root = pathlib.Path(__file__).resolve().parents[1]
    default_db = site_root / "data" / "rwa.db"
    parser = argparse.ArgumentParser(description="Init / seed Himuda Housing Colony Sanyard RWA SQLite DB")
    parser.add_argument("--db", default=str(default_db))
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    db_path = pathlib.Path(args.db)
    conn = connect(db_path)
    init_schema(conn)
    counts = seed_from_ledger(conn, reset=args.reset)
    conn.close()
    print(json.dumps({"ok": True, "db": str(db_path), **counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
