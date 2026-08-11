#!/usr/bin/env python3
"""Generate printable EC committee charter HTML from rwa.db (not for the live portal).

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

# Fallback executive members when the roster has no non-office-bearer EC rows yet.
FALLBACK_GENERAL = [
    {"name": "Hari Singh Dogra", "phone": ""},
    {"name": "Roop Lal Sharma", "phone": ""},
    {"name": "Jitesh Sharma", "phone": ""},
    {"name": "Rajesh Kumar Saini", "phone": ""},
]

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
    return str(phone).strip() or "—"


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
                f"<td>{html.escape(fmt_phone(m.get('phone')))}</td></tr>"
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
        general_for_members = general or list(FALLBACK_GENERAL)
    else:
        general_for_members = []

    generated = datetime.now(IST).strftime("%d %b %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Himuda Housing Colony Sanyard — Executive Committee Charter</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Source+Sans+3:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    @page {{ size: A4 portrait; margin: 6mm; }}
    * {{ box-sizing: border-box; }}
    :root {{
      --navy: #0b2a56;
      --navy-2: #143a6e;
      --green: #1a6b3a;
      --gold: #c9a227;
      --ink: #12233f;
      --muted: #5a6a80;
      --paper: #ffffff;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #cfd8e6;
      font-family: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
    }}
    .screen-hint {{
      text-align: center;
      padding: 10px 14px;
      font: 500 13px/1.45 system-ui, sans-serif;
      color: #445;
      max-width: 210mm;
      margin: 0 auto;
    }}
    .sheet {{
      position: relative;
      width: 210mm;
      min-height: 297mm;
      margin: 0 auto 18px;
      padding: 0;
      background: var(--paper);
      border: 1pt solid rgba(11, 42, 86, 0.55);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    .accent-edge {{
      display: grid;
      grid-template-columns: 1fr 7mm 1fr;
      height: 2.6mm;
      flex: 0 0 auto;
    }}
    .accent-edge .n {{ background: var(--navy); }}
    .accent-edge .g {{ background: var(--gold); }}
    .accent-edge .e {{ background: var(--green); }}
    .accent-edge-thin {{
      height: 0.4mm;
      background: rgba(11, 42, 86, 0.12);
      flex: 0 0 auto;
    }}
    .wm {{
      position: absolute;
      left: 50%;
      top: 52%;
      transform: translate(-50%, -50%);
      width: 96mm;
      height: auto;
      opacity: 0.42;
      pointer-events: none;
      z-index: 0;
    }}
    .pad {{
      position: relative;
      z-index: 1;
      flex: 1;
      display: flex;
      flex-direction: column;
      padding: 5mm 12mm 0;
      min-height: 0;
    }}
    .brand {{
      display: grid;
      grid-template-columns: 24mm 1fr;
      gap: 5mm;
      align-items: center;
      padding: 0 0 3mm;
    }}
    .brand .logo {{
      width: 24mm;
      height: auto;
      display: block;
    }}
    .brand h1 {{
      margin: 0;
      font-family: "Cormorant Garamond", "Times New Roman", Georgia, serif;
      font-size: 16pt;
      font-weight: 700;
      letter-spacing: 0.055em;
      color: var(--navy);
      line-height: 1.05;
      text-transform: uppercase;
    }}
    .brand .colony {{
      margin: 0.8mm 0 0;
      font-size: 10pt;
      font-weight: 700;
      color: var(--navy-2);
      letter-spacing: 0.03em;
    }}
    .brand .addr {{
      margin: 1.2mm 0 0;
      font-size: 8.5pt;
      font-weight: 600;
      color: var(--green);
    }}
    .rule {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 3mm;
      margin: 0 0 3.5mm;
    }}
    .rule::before,
    .rule::after {{
      content: "";
      height: 0;
      border-top: 1pt solid var(--navy);
    }}
    .rule .pip {{
      width: 2.2mm;
      height: 2.2mm;
      background: var(--gold);
      transform: rotate(45deg);
      box-shadow: 0 0 0 1.2pt #fff, 0 0 0 1.7pt rgba(11, 42, 86, 0.35);
    }}
    .banner {{
      text-align: center;
      background: linear-gradient(90deg, var(--navy) 0%, var(--navy-2) 48%, #124a38 100%);
      color: #f7f3ea;
      font-size: 9.5pt;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      padding: 2.6mm 4mm;
      margin: 0 0 4mm;
    }}
    .banner .sep {{ color: var(--gold); margin: 0 1.4mm; letter-spacing: 0; }}
    .section-title {{
      margin: 0 0 2mm;
      font-size: 8pt;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--green);
      text-align: center;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 9.2pt;
    }}
    th, td {{
      border: 1px solid rgba(11, 42, 86, 0.28);
      padding: 2mm 2.4mm;
      text-align: left;
      vertical-align: middle;
    }}
    th {{
      background: rgba(11, 42, 86, 0.92);
      color: #f7f3ea;
      font-weight: 700;
      text-align: center;
      font-size: 8pt;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    td:first-child {{ text-align: center; width: 12mm; color: var(--muted); font-weight: 600; }}
    .office-table td:nth-child(2) {{
      width: 34%;
      color: var(--green);
      font-weight: 700;
      text-transform: uppercase;
      font-size: 8.2pt;
      letter-spacing: 0.04em;
    }}
    .office-table td:nth-child(3) {{
      font-weight: 700;
      color: var(--navy);
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .members-heading {{
      display: flex;
      align-items: center;
      gap: 4mm;
      margin: 5.5mm 0 2.5mm;
    }}
    .members-heading::before,
    .members-heading::after {{
      content: "";
      flex: 1;
      border-top: 1pt solid rgba(11, 42, 86, 0.28);
    }}
    .members-heading span {{
      font-size: 8pt;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--green);
      white-space: nowrap;
    }}
    .member-columns {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4mm;
    }}
    .member-table td:nth-child(2) {{
      font-weight: 700;
      color: var(--navy);
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }}
    .member-table td:first-child {{ width: 10mm; }}
    .empty-members {{ text-align: center; color: var(--muted); font-size: 9pt; }}
    .body-spacer {{ flex: 1; min-height: 12mm; }}
    .foot {{ margin-top: auto; padding: 0; }}
    .contacts {{
      display: grid;
      grid-template-columns: 1.35fr 1.25fr 1fr;
      gap: 3mm;
      padding: 2.8mm 0 2.6mm;
      border-top: 1pt solid rgba(11, 42, 86, 0.45);
      font-size: 7.4pt;
      align-items: start;
    }}
    .contact {{
      display: grid;
      grid-template-columns: 4.2mm 1fr;
      gap: 1.6mm;
      align-items: start;
    }}
    .contact svg {{
      width: 3.6mm;
      height: 3.6mm;
      margin-top: 0.4mm;
      stroke: var(--green);
      fill: none;
      stroke-width: 1.7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .contact .k {{
      display: block;
      font-size: 6.2pt;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--green);
      margin-bottom: 0.5mm;
    }}
    .contact .v {{
      color: var(--navy);
      font-weight: 600;
      line-height: 1.25;
    }}
    .slogan-bar {{
      margin: 0 -12mm;
      background: linear-gradient(90deg, var(--navy) 0%, var(--navy-2) 48%, #124a38 100%);
      color: #f7f3ea;
      text-align: center;
      padding: 2.3mm 10mm;
      font-size: 8.2pt;
      font-weight: 700;
      letter-spacing: 0.24em;
      text-transform: uppercase;
    }}
    .slogan-bar .sep {{ color: var(--gold); margin: 0 1.6mm; letter-spacing: 0; }}
    .slogan-bar .u {{ color: #dbe7ff; }}
    .slogan-bar .h {{ color: #b8e6c6; }}
    .slogan-bar .p {{ color: #f0d48a; }}
    .meta {{
      text-align: right;
      font-size: 7pt;
      color: var(--muted);
      margin: 2mm 0 3mm;
    }}
    @media print {{
      body {{ background: #fff; }}
      .screen-hint {{ display: none !important; }}
      .sheet {{
        margin: 0;
        border-width: 0.8pt;
        min-height: 100vh;
      }}
    }}
  </style>
</head>
<body>
  <p class="screen-hint">
    Executive Committee Charter — Himuda Housing Colony Sanyard.<br>
    Open → Print → A4. Generated {html.escape(generated)}.
  </p>

  <div class="sheet">
    <div class="accent-edge" aria-hidden="true"><span class="n"></span><span class="g"></span><span class="e"></span></div>
    <div class="accent-edge-thin" aria-hidden="true"></div>
    <img class="wm" src="../assets/mhws-logo/mhws-logo-watermark.png" alt="" aria-hidden="true">

    <div class="pad">
      <header class="brand">
        <img class="logo" src="../assets/mhws-logo/mhws-logo-seal-cert.png" alt="Himuda Housing Colony Sanyard">
        <div>
          <h1>Mandi Housing Welfare Society</h1>
          <p class="colony">Himuda Housing Colony Sanyard</p>
          <p class="addr">Housing Colony Sanyard, Mandi HP 175001</p>
        </div>
      </header>

      <div class="rule" aria-hidden="true"><span class="pip"></span></div>

      <div class="banner">Executive Committee Charter <span class="sep">·</span> Office Bearers &amp; Members</div>

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

      <div class="body-spacer" aria-hidden="true"></div>

      <footer class="foot">
        <div class="contacts">
          <div class="contact">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s7-5.2 7-11a7 7 0 10-14 0c0 5.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.4"/></svg>
            <div>
              <span class="k">Address</span>
              <span class="v">Housing Colony Sanyard, Mandi HP 175001</span>
            </div>
          </div>
          <div class="contact">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="6" width="17" height="12" rx="1.5"/><path d="M4 7l8 6 8-6"/></svg>
            <div>
              <span class="k">Email</span>
              <span class="v">housingcolonysanyard@gmail.com</span>
            </div>
          </div>
          <div class="contact">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.5 2.8 2.5 13.2 0 16M12 4c-2.5 2.8-2.5 13.2 0 16"/></svg>
            <div>
              <span class="k">Website</span>
              <span class="v">housingcolonysanyard.in</span>
            </div>
          </div>
        </div>
        <div class="slogan-bar" aria-label="Society slogan">
          <span class="u">Unity</span><span class="sep">·</span>
          <span class="h">Harmony</span><span class="sep">·</span>
          <span class="p">Progress</span>
        </div>
        <p class="meta">Executive Committee Charter · Generated {html.escape(generated)} · Himuda Housing Colony Sanyard</p>
      </footer>
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export printable EC committee charter HTML")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to rwa.db")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT, help="Output HTML path")
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"Database not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    try:
        office, general = load_ec(conn)
    finally:
        conn.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(office, general), encoding="utf-8")
    print(f"Wrote {args.output} ({len(office)} office bearers, {len(general) or len(FALLBACK_GENERAL)} members)")


if __name__ == "__main__":
    main()
