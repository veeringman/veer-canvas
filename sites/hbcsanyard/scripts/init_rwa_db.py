#!/usr/bin/env python3
"""HBC Sanyard RWA SQLite schema, seed, and PDF ledger import helpers."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import secrets
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 5
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
    ("12B(i)", "NAVEEN THAKUR", 10600, 2400, 13000, 0, "A", ""),
    ("12B(ii)", "YADAV KUMAR", 10600, 2400, 13000, 0, "A", ""),
    ("12B(iii)", "SARBJIT SINGH", 10600, 2400, 13000, 0, "A", ""),
    ("12B(iv)", "VIKRANT THAKUR", 10600, 2400, 13000, 0, "A", ""),
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
    "colony": "HIMUDA Housing Colony Sanyard, Mandi",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_house_id(plot: str, section: str = "A") -> str:
    raw = re.sub(r"\s+", "", (plot or "").strip().upper())
    if not raw:
        raise ValueError("plot required")
    # Combined plots like 33/34 → 33-34 (slash breaks URL paths)
    raw = raw.replace("/", "-")
    # Keep roman suffixes lowercase for readability: 12B(i)
    raw = re.sub(r"\(([IVX]+)\)", lambda m: f"({m.group(1).lower()})", raw)
    if raw.startswith("B-") or section == "B":
        if raw.startswith("B-"):
            return raw
        return f"B-{raw}"
    return raw


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
          email TEXT,
          phone TEXT,
          role TEXT NOT NULL DEFAULT 'resident' CHECK(role IN ('admin','resident')),
          status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')),
          notes TEXT,
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

        CREATE TABLE IF NOT EXISTS otp_challenges (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          house_id TEXT NOT NULL,
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
    ensure_grievances_table(conn)
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
    ]
    for name, sql in alters:
        if name not in cols:
            conn.execute(sql)
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
            (house_id, plot, section, name, remarks or None, now, now),
        )

    # Bootstrap EC admin: Plot 43 (can be changed later via promote API).
    conn.execute(
        "UPDATE residents SET role = 'admin', updated_at = ? WHERE house_id = '43'",
        (now,),
    )
    cur = conn.execute(
        "INSERT INTO payment_ledgers(source, as_of, notes, imported_at) VALUES (?, ?, ?, ?)",
        (
            "HIMUDA Housing Colony Sanyard LIST.pdf",
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
            "Welcome to the HBC Sanyard resident portal",
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
    parser = argparse.ArgumentParser(description="Init / seed HBC Sanyard RWA SQLite DB")
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
