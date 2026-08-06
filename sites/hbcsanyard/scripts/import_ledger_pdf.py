#!/usr/bin/env python3
"""Import HIMUDA Housing Colony Sanyard ledger PDF into rwa.db."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys

SITE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from init_rwa_db import (  # noqa: E402
    BANK,
    SUPERADMIN_HOUSE_ID,
    connect,
    ensure_db,
    init_schema,
    normalize_house_id,
    utc_now,
)

ROW_RE = re.compile(
    r"^(\d+)\s+"
    r"(\d+[A-Za-z]?(?:\s*\([ivxIVX]+\))?|\d+/\d+)\s+"
    r"(.+?)\s+"
    r"(-?\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?(.*)$"
)


def extract_pdf_text(pdf_path: pathlib.Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit("pypdf required: pip install pypdf") from exc
    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def parse_ledger_text(text: str) -> list[dict]:
    section = "A"
    rows: list[dict] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        upper = line.upper()
        if "COMMERCIAL PLOTS" in upper and "- B" in upper:
            section = "B"
            continue
        if "RESIDENTIAL PLOTS" in upper and "- A" in upper:
            section = "A"
            continue
        if not line or line.startswith("S No") or line.startswith("₹") or line.startswith("TOTAL"):
            continue
        if line.startswith("Status of") or line.startswith("HIMUDA") or line.startswith("The members"):
            continue
        if line.startswith("A/C") or line.startswith("IFSC") or line.startswith("Remarks") or line.startswith("No."):
            continue
        if line.startswith("Name ") or line.startswith("Amount of") or line.startswith("Balance"):
            continue
        m = ROW_RE.match(line)
        if not m:
            continue
        sno, plot, name, bal_prev, fee, total, received, remarks = m.groups()
        sno_i = int(sno)
        # PDF prints "COMMERCIAL PLOTS - B" after rows 61–62; treat those as section B.
        row_section = "B" if sno_i >= 61 else section
        plot = re.sub(r"\s+", "", plot)
        # Legacy PDF prints 12B(i); normalize_house_id maps that to 12B-1.
        remarks = (remarks or "").strip()
        remarks = re.sub(r"^\(+|\)+$", "", remarks).strip()
        if "Already received" in remarks or "already received" in remarks.lower():
            remarks = "Already received"
        rows.append({
            "sno": sno_i,
            "plot": plot,
            "name": name.strip(),
            "balance_prev": int(bal_prev),
            "fee_amount": int(fee),
            "total_due": int(total),
            "amount_received": int(received or 0),
            "remarks": remarks,
            "section": row_section,
        })
    return rows


def import_rows(conn, rows: list[dict], *, source: str, as_of: str) -> dict:
    now = utc_now()
    # Preserve emails/phones/roles across re-import
    existing = {
        r["house_id"]: dict(r)
        for r in conn.execute("SELECT * FROM residents").fetchall()
    }
    for row in rows:
        house_id = normalize_house_id(row["plot"], row["section"])
        prev = existing.get(house_id) or {}
        conn.execute(
            """
            INSERT INTO residents(house_id, plot_no, section, name, email, phone, role, status, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(house_id) DO UPDATE SET
              plot_no=excluded.plot_no,
              section=excluded.section,
              name=excluded.name,
              notes=COALESCE(excluded.notes, residents.notes),
              updated_at=excluded.updated_at
            """,
            (
                house_id,
                house_id,
                row["section"],
                row["name"],
                prev.get("email"),
                prev.get("phone"),
                prev.get("role") or "resident",
                row["remarks"] or None,
                prev.get("created_at") or now,
                now,
            ),
        )

    # Keep plot 43 as admin if present
    conn.execute(
        "UPDATE residents SET role='admin', updated_at=? WHERE house_id='43'",
        (now,),
    )

    imported_ids = {normalize_house_id(r["plot"], r["section"]) for r in rows}
    imported_ids.add(SUPERADMIN_HOUSE_ID)
    for hid in list(existing.keys()):
        if hid not in imported_ids:
            conn.execute("DELETE FROM payment_rows WHERE house_id=?", (hid,))
            conn.execute("DELETE FROM sessions WHERE house_id=?", (hid,))
            conn.execute("DELETE FROM otp_challenges WHERE house_id=?", (hid,))
            conn.execute("DELETE FROM residents WHERE house_id=?", (hid,))

    cur = conn.execute(
        "INSERT INTO payment_ledgers(source, as_of, notes, imported_at) VALUES (?, ?, ?, ?)",
        (source, as_of, f"Imported {len(rows)} rows", now),
    )
    ledger_id = cur.lastrowid
    for row in rows:
        house_id = normalize_house_id(row["plot"], row["section"])
        outstanding = int(row["total_due"]) - int(row["amount_received"])
        conn.execute(
            """
            INSERT INTO payment_rows(
              ledger_id, house_id, balance_prev, fee_year, fee_amount,
              total_due, amount_received, balance_outstanding, remarks
            ) VALUES (?, ?, ?, 2026, ?, ?, ?, ?, ?)
            """,
            (
                ledger_id,
                house_id,
                row["balance_prev"],
                row["fee_amount"],
                row["total_due"],
                row["amount_received"],
                outstanding,
                row["remarks"] or None,
            ),
        )

    conn.execute(
        """
        INSERT INTO bank_accounts(label, bank_name, account_no, ifsc, is_primary)
        SELECT 'Society dues', ?, ?, ?, 1
        WHERE NOT EXISTS (SELECT 1 FROM bank_accounts WHERE is_primary=1)
        """,
        (BANK["bank_name"], BANK["account_no"], BANK["ifsc"]),
    )
    conn.commit()
    return {
        "rows": len(rows),
        "residents": conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0],
        "ledgerId": ledger_id,
        "asOf": as_of,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", help="Path to HIMUDA ledger PDF")
    parser.add_argument("--db", default=str(SITE_ROOT / "data" / "rwa.db"))
    parser.add_argument("--as-of", default=BANK["ledger_as_of"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    default_pdf = SITE_ROOT / "data" / "imports" / "HIMUDA-HOUSING-COLONY-SANYARD-LIST.pdf"
    icloud = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/HIMUDA HOUSING COLONY SANYARD LIST.pdf"
    pdf_path = pathlib.Path(args.pdf) if args.pdf else (default_pdf if default_pdf.is_file() else icloud)
    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    imports_dir = SITE_ROOT / "data" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    archived = imports_dir / "HIMUDA-HOUSING-COLONY-SANYARD-LIST.pdf"
    if pdf_path.resolve() != archived.resolve():
        shutil.copy2(pdf_path, archived)
        print(f"Archived PDF -> {archived}")

    text = extract_pdf_text(pdf_path)
    rows = parse_ledger_text(text)
    if len(rows) < 50:
        print(f"error: only parsed {len(rows)} rows — check PDF layout", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps({"ok": True, "parsed": len(rows), "sample": rows[:3], "tail": rows[-3:]}, indent=2))
        return 0

    db_path = pathlib.Path(args.db)
    ensure_db(db_path, seed=False)
    conn = connect(db_path)
    init_schema(conn)
    # Drop prior payment rows only; keep residents profile fields via upsert
    conn.execute("DELETE FROM payment_rows")
    conn.execute("DELETE FROM payment_ledgers")
    result = import_rows(conn, rows, source=pdf_path.name, as_of=args.as_of)
    conn.close()
    print(json.dumps({"ok": True, "pdf": str(pdf_path), **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
