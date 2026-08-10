#!/usr/bin/env python3
"""Generate printable EC committee pad HTML from rwa.db (not for the live portal).

Usage:
  python3 scripts/export_ec_pad.py
  python3 scripts/export_ec_pad.py --db /path/to/rwa.db
  python3 scripts/export_ec_pad.py --db data/rwa.db --output documents/ec-committee-pad.html
"""
from __future__ import annotations

import argparse
import html
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = SITE_ROOT / "data" / "rwa.db"
DEFAULT_OUT = SITE_ROOT / "documents" / "ec-committee-pad.html"
SUPERADMIN = "__SUPERADMIN__"

TITLE_RANK = {
    "president": 0,
    "vice president": 1,
    "vice-president": 1,
    "general secretary": 2,
    "secretary": 3,
    "joint secretary": 4,
    "treasurer": 5,
    "joint treasurer": 6,
}


def title_rank(title: str) -> tuple[int, str]:
    t = (title or "").strip().lower()
    for key, rank in TITLE_RANK.items():
        if key in t:
            return rank, t
    return (25 if t else 99, t)


def fmt_phone(phone: str | None) -> str:
    if not phone:
        return "—"
    digits = "".join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:5]} {digits[5:]}"
    return str(phone).strip()


def load_ec(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        """
        SELECT house_id, plot_no, name, title, official_title, phone
        FROM residents
        WHERE role = 'admin' AND status = 'active' AND house_id != ?
        """,
        (SUPERADMIN,),
    ).fetchall()
    members = [
        {
            "house_id": r[0],
            "plot_no": r[1] or r[0],
            "name": r[2] or r[0],
            "title": r[3] or "",
            "official_title": r[4] or "",
            "phone": r[5] or "",
        }
        for r in rows
    ]
    office = [m for m in members if m["official_title"]]
    general = [m for m in members if not m["official_title"]]
    office.sort(key=lambda m: (title_rank(m["official_title"]), m["name"].lower()))
    general.sort(key=lambda m: m["name"].lower())
    return office, general


def office_rows(office: list[dict], general: list[dict]) -> str:
    rows = office[:]
    if not rows and general:
        rows = general
        general = []
    if not rows:
        return (
            '<tr><td colspan="4" style="text-align:center;padding:8px;">'
            "No Executive Committee members in database yet."
            "</td></tr>"
        )
    out = []
    for i, m in enumerate(rows, 1):
        post = m["official_title"] or "Executive Committee Member"
        out.append(
            f"<tr><td>{i}</td><td>{html.escape(post)}</td>"
            f"<td>{html.escape(m['name'])}</td>"
            f"<td>{html.escape(fmt_phone(m['phone']))}</td></tr>"
        )
    return "\n".join(out)


def member_tables(general: list[dict], start_no: int) -> str:
    if not general:
        return '<p class="empty-members">—</p>'
    mid = (len(general) + 1) // 2
    left, right = general[:mid], general[mid:]

    def table_chunk(items: list[dict], offset: int) -> str:
        if not items:
            return ""
        rows = []
        for j, m in enumerate(items, offset):
            rows.append(
                f"<tr><td>{j}</td><td>{html.escape(m['name'])}</td>"
                f"<td>{html.escape(fmt_phone(m['phone']))}</td></tr>"
            )
        return (
            '<table class="member-table"><thead><tr>'
            "<th>S.No.</th><th>Name</th><th>Mobile</th>"
            "</tr></thead><tbody>"
            + "\n".join(rows)
            + "</tbody></table>"
        )

    return (
        f'<div class="member-columns">{table_chunk(left, start_no)}'
        f"{table_chunk(right, start_no + len(left))}</div>"
    )


def render(office: list[dict], general: list[dict]) -> str:
    office_count = len(office) if office else len(general)
    member_start = office_count + 1
    if office:
        general_for_members = general
    else:
        general_for_members = []

    generated = datetime.now(IST).strftime("%d %b %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Himuda Housing Colony Sanyard — Executive Committee Pad</title>
  <style>
    @page {{ size: A4 portrait; margin: 10mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Times New Roman", Times, Georgia, serif;
      color: #1a1208;
      background: #e8e0d0;
    }}
    .sheet {{
      width: 210mm;
      min-height: 297mm;
      margin: 0 auto;
      padding: 8mm 10mm 10mm;
      background: #fdfaf3;
      border: 2px solid #6b4a2e;
      position: relative;
    }}
    .corner {{ position: absolute; width: 16mm; height: 16mm; border: 2px solid #6b4a2e; }}
    .c-tl {{ top: 5mm; left: 5mm; border-right: 0; border-bottom: 0; }}
    .c-tr {{ top: 5mm; right: 5mm; border-left: 0; border-bottom: 0; }}
    .c-bl {{ bottom: 5mm; left: 5mm; border-right: 0; border-top: 0; }}
    .c-br {{ bottom: 5mm; right: 5mm; border-left: 0; border-top: 0; }}
    .head {{
      display: grid;
      grid-template-columns: 26mm 1fr;
      gap: 7mm;
      align-items: center;
      margin-bottom: 4mm;
    }}
    .seal {{
      width: 24mm;
      height: 24mm;
      border-radius: 50%;
      object-fit: cover;
      border: 2px solid #9e7d3a;
    }}
    .org h1 {{
      margin: 0;
      font-size: 16pt;
      color: #3d2914;
      line-height: 1.12;
    }}
    .org p {{
      margin: 1.5mm 0 0;
      font-size: 10pt;
      color: #4a3728;
      line-height: 1.3;
    }}
    .main-banner {{
      text-align: center;
      background: #4a3728;
      color: #fdf6e8;
      font-size: 10pt;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      padding: 2.5mm;
      margin: 3mm 0 4mm;
    }}
    .section-title {{
      text-align: center;
      font-size: 11pt;
      font-weight: 700;
      color: #3d2914;
      margin: 4mm 0 2mm;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 9.5pt;
    }}
    th, td {{
      border: 1px solid #6b4a2e;
      padding: 1.8mm 2mm;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      background: #4a3728;
      color: #fdf6e8;
      font-weight: 700;
      text-align: center;
      font-size: 9pt;
      letter-spacing: 0.04em;
    }}
    td:first-child {{ text-align: center; width: 10mm; }}
    .office-table td:nth-child(2) {{ width: 38%; }}
    .members-heading {{
      display: flex;
      align-items: center;
      gap: 4mm;
      margin: 5mm 0 2mm;
    }}
    .members-heading::before,
    .members-heading::after {{
      content: "";
      flex: 1;
      border-top: 1px solid #6b4a2e;
    }}
    .members-heading span {{
      font-size: 10pt;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #3d2914;
      white-space: nowrap;
    }}
    .member-columns {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4mm;
    }}
    .member-table td:first-child {{ width: 8mm; }}
    .empty-members {{ text-align: center; color: #666; font-size: 9pt; }}
    .footer {{
      margin-top: 6mm;
      text-align: center;
      font-size: 8.5pt;
      color: #6b4a2e;
      letter-spacing: 0.06em;
      border-top: 1px solid rgba(107, 74, 46, 0.4);
      padding-top: 3mm;
    }}
    .meta {{
      text-align: right;
      font-size: 7.5pt;
      color: #888;
      margin-top: 2mm;
    }}
    .screen-hint {{
      text-align: center;
      padding: 8px;
      font-family: system-ui, sans-serif;
      font-size: 13px;
      color: #555;
    }}
    @media print {{
      body {{ background: #fff; }}
      .screen-hint {{ display: none; }}
      .sheet {{ margin: 0; box-shadow: none; }}
    }}
  </style>
</head>
<body>
  <p class="screen-hint">Print on A4 — send to press for EC pad / chart. Generated {html.escape(generated)}.</p>
  <div class="sheet">
    <span class="corner c-tl" aria-hidden="true"></span>
    <span class="corner c-tr" aria-hidden="true"></span>
    <span class="corner c-bl" aria-hidden="true"></span>
    <span class="corner c-br" aria-hidden="true"></span>

    <header class="head">
      <img class="seal" src="../assets/mhws-logo/mhws-logo-print.png" alt="Himuda Housing Colony Sanyard">
      <div class="org">
        <h1>Himuda Housing Colony Sanyard</h1>
        <p>Housing Colony Sanyard, Mandi HP 175001</p>
        <p>Unity · Harmony · Progress</p>
        <p><strong>Executive Committee</strong></p>
      </div>
    </header>

    <div class="main-banner">Office Bearers &amp; Executive Committee Members</div>

    <div class="section-title">Office Bearers</div>
    <table class="office-table">
      <thead>
        <tr><th>S.No.</th><th>Designation</th><th>Name</th><th>Mobile</th></tr>
      </thead>
      <tbody>
        {office_rows(office, general)}
      </tbody>
    </table>

    <div class="members-heading"><span>Executive Committee Members</span></div>
    {member_tables(general_for_members, member_start)}

    <footer class="footer">Unity · Harmony · Progress</footer>
    <p class="meta">Chart generated {html.escape(generated)} · Himuda Housing Colony Sanyard</p>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export printable EC committee pad HTML")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to rwa.db")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT, help="Output HTML path")
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"Database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        office, general = load_ec(conn)
    finally:
        conn.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(office, general), encoding="utf-8")
    print(f"Wrote {args.output} ({len(office)} office bearers, {len(general)} members)")


if __name__ == "__main__":
    main()
