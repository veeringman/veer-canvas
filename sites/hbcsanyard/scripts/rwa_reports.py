"""RWA PDF reports (EC desk). Pending dues first; header with seal + office bearers."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from init_rwa_db import SUPERADMIN_HOUSE_ID, section_plot_sort_key

IST = ZoneInfo("Asia/Kolkata")
_RL = None  # lazy reportlab bundle


def _now_ist() -> datetime:
    return datetime.now(IST)


def _fmt_ist_datetime(dt: datetime | None = None) -> str:
    return (dt or _now_ist()).strftime("%d %b %Y %H:%M IST")


def _fmt_ist_date(dt: datetime | None = None) -> str:
    return (dt or _now_ist()).strftime("%d %b %Y")


def _reportlab():
    """Import reportlab on first PDF build (keeps admin app bootable without it)."""
    global _RL
    if _RL is not None:
        return _RL
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "reportlab is required for PDF reports. Install: pip install reportlab"
        ) from exc
    _RL = {
        "colors": colors,
        "TA_CENTER": TA_CENTER,
        "TA_JUSTIFY": TA_JUSTIFY,
        "TA_LEFT": TA_LEFT,
        "TA_RIGHT": TA_RIGHT,
        "A4": A4,
        "landscape": landscape,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "mm": mm,
        "Image": Image,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }
    return _RL


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

# Field catalog for Pending Dues report (id → label, default selected)
PENDING_DUES_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 48},
    {"id": "section", "label": "Sec.", "default": True, "align": "center", "width": 32},
    {"id": "name", "label": "Name", "default": True, "align": "left", "width": 110},
    {"id": "phone", "label": "Phone", "default": False, "align": "left", "width": 72},
    {"id": "previousTotal", "label": "Prev total", "default": True, "align": "right", "width": 58},
    {"id": "previousPending", "label": "Prev pending", "default": False, "align": "right", "width": 58},
    {"id": "currentYearTotal", "label": "Year total", "default": True, "align": "right", "width": 58},
    {"id": "currentYearPending", "label": "Year pending", "default": False, "align": "right", "width": 58},
    {"id": "amountReceived", "label": "Received", "default": True, "align": "right", "width": 58},
    {"id": "totalDue", "label": "Total due", "default": True, "align": "right", "width": 58},
    {"id": "pendingDues", "label": "Pending", "default": True, "align": "right", "width": 58},
    {"id": "remarks", "label": "Remarks", "default": False, "align": "left", "width": 90},
]

MONEY_FIELDS = {
    "previousTotal",
    "previousPending",
    "currentYearTotal",
    "currentYearPending",
    "amountReceived",
    "totalDue",
    "pendingDues",
    "amount",
    "estimatedCost",
    "actualCost",
}

DIRECTORY_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 48},
    {"id": "section", "label": "Sec.", "default": False, "align": "center", "width": 32},
    {"id": "name", "label": "Name", "default": True, "align": "left", "width": 110},
    {"id": "officialTitle", "label": "Office", "default": True, "align": "left", "width": 90},
    {"id": "phone", "label": "Phone", "default": True, "align": "left", "width": 78},
    {"id": "email", "label": "Email", "default": True, "align": "left", "width": 120},
    {"id": "profession", "label": "Profession", "default": False, "align": "left", "width": 90},
]

CONCERNS_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 48},
    {"id": "category", "label": "Category", "default": True, "align": "left", "width": 70},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 60},
    {"id": "subject", "label": "Subject", "default": True, "align": "left", "width": 140},
    {"id": "updatedAt", "label": "Updated", "default": True, "align": "left", "width": 80},
]

PAYMENT_RECORD_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 26},
    {"id": "paidOn", "label": "Date", "default": True, "align": "left", "width": 52},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 42},
    {"id": "residentName", "label": "Name", "default": True, "align": "left", "width": 90},
    {"id": "kindLabel", "label": "Type", "default": True, "align": "left", "width": 70},
    {"id": "categoryLabel", "label": "Category", "default": True, "align": "left", "width": 70},
    {"id": "methodLabel", "label": "Method", "default": True, "align": "left", "width": 48},
    {"id": "amount", "label": "Amount", "default": True, "align": "right", "width": 58},
    {"id": "feeYear", "label": "Year", "default": False, "align": "center", "width": 36},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 55},
    {"id": "treasuryStatus", "label": "Treasury", "default": False, "align": "center", "width": 55},
    {"id": "note", "label": "Note", "default": False, "align": "left", "width": 90},
    {"id": "reviewedAt", "label": "Reviewed", "default": False, "align": "left", "width": 70},
]

NO_DUES_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 48},
    {"id": "residentName", "label": "Name", "default": True, "align": "left", "width": 110},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 55},
    {"id": "treasuryStatus", "label": "Treasury", "default": True, "align": "center", "width": 55},
    {"id": "createdAt", "label": "Requested", "default": True, "align": "left", "width": 70},
    {"id": "issuedAt", "label": "Issued", "default": True, "align": "left", "width": 70},
    {"id": "requestNote", "label": "Note", "default": False, "align": "left", "width": 100},
]

WORKS_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "title", "label": "Title", "default": True, "align": "left", "width": 130},
    {"id": "kind", "label": "Kind", "default": True, "align": "left", "width": 55},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 60},
    {"id": "estimatedCost", "label": "Est. cost", "default": True, "align": "right", "width": 58},
    {"id": "actualCost", "label": "Actual", "default": True, "align": "right", "width": 58},
    {"id": "startDate", "label": "Start", "default": False, "align": "left", "width": 55},
    {"id": "endDate", "label": "End", "default": False, "align": "left", "width": 55},
    {"id": "visibility", "label": "Visibility", "default": False, "align": "center", "width": 55},
]

NOTICES_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "publishedAt", "label": "Published", "default": True, "align": "left", "width": 70},
    {"id": "category", "label": "Category", "default": True, "align": "left", "width": 60},
    {"id": "title", "label": "Title", "default": True, "align": "left", "width": 160},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 55},
    {"id": "pinned", "label": "Pinned", "default": False, "align": "center", "width": 40},
]

DATASETS_META = {
    "dues": {
        "id": "dues",
        "title": "Dues / ledger",
        "fields": PENDING_DUES_FIELDS,
        "defaultFilters": {"pendingOnly": True, "section": "all", "search": "", "houseIds": []},
        "filterUi": {"section": True, "search": True, "plots": True, "pendingOnly": True},
    },
    "payments": {
        "id": "payments",
        "title": "Payments received",
        "description": "Resident payments to RWA (UPI / bank / cash)",
        "fields": PAYMENT_RECORD_FIELDS,
        "defaultFilters": {"status": "verified", "search": "", "houseIds": [], "method": "all"},
        "filterUi": {"section": False, "search": True, "plots": True, "recordStatus": True, "method": True},
    },
    "cash": {
        "id": "cash",
        "title": "Cash register",
        "description": "Cash received notes and cash payment vouchers",
        "fields": PAYMENT_RECORD_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": [], "method": "cash"},
        "filterUi": {"section": False, "search": True, "plots": True, "recordStatus": True},
    },
    "reimbursements": {
        "id": "reimbursements",
        "title": "Reimbursement claims",
        "description": "Expense claims and payouts",
        "fields": PAYMENT_RECORD_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": []},
        "filterUi": {"section": False, "search": True, "plots": True, "recordStatus": True},
    },
    "transactions": {
        "id": "transactions",
        "title": "All transactions",
        "description": "Combined payments and reimbursement claims",
        "fields": PAYMENT_RECORD_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": [], "method": "all"},
        "filterUi": {"section": False, "search": True, "plots": True, "recordStatus": True, "method": True},
    },
    "no_dues": {
        "id": "no_dues",
        "title": "No Dues certificates",
        "fields": NO_DUES_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": []},
        "filterUi": {"section": False, "search": True, "plots": True, "noDuesStatus": True},
    },
    "directory": {
        "id": "directory",
        "title": "Resident directory",
        "fields": DIRECTORY_FIELDS,
        "defaultFilters": {"section": "all", "search": "", "officeBearersOnly": False},
        "filterUi": {"section": True, "search": True, "plots": False},
    },
    "concerns": {
        "id": "concerns",
        "title": "Resident concerns",
        "fields": CONCERNS_FIELDS,
        "defaultFilters": {"status": "open", "category": "all", "search": ""},
        "filterUi": {"section": False, "search": True, "plots": False, "concernStatus": True},
    },
    "works": {
        "id": "works",
        "title": "Works & events",
        "fields": WORKS_FIELDS,
        "defaultFilters": {"status": "all", "search": ""},
        "filterUi": {"section": False, "search": True, "plots": False, "worksStatus": True},
    },
    "notices": {
        "id": "notices",
        "title": "Notices",
        "fields": NOTICES_FIELDS,
        "defaultFilters": {"status": "published", "search": ""},
        "filterUi": {"section": False, "search": True, "plots": False, "noticeStatus": True},
    },
}


def reports_meta(conn=None) -> dict:
    datasets = DATASETS_META
    reports = [
        {
            "id": "pending-dues",
            "title": "Pending Dues Report",
            "description": "Subscription / dues outstanding by plot from the latest ledger.",
            "kind": "builtin",
            "dataset": "dues",
            "fields": PENDING_DUES_FIELDS,
            "defaultFilters": {
                "pendingOnly": True,
                "section": "all",
                "search": "",
                "houseIds": [],
            },
        },
        {
            "id": "custom",
            "title": "Custom report",
            "description": "Pick a dataset, columns, and filters — optionally save as a template.",
            "kind": "custom",
            "datasets": list(datasets.keys()),
        },
    ]
    templates = list_report_templates(conn) if conn is not None else []
    for tpl in templates:
        reports.append({
            "id": f"template:{tpl['id']}",
            "title": tpl["name"],
            "description": f"Saved template · {tpl['dataset']}",
            "kind": "template",
            "templateId": tpl["id"],
            "dataset": tpl["dataset"],
            "fields": tpl.get("fields") or [],
            "defaultFilters": tpl.get("filters") or {},
        })
    return {"reports": reports, "datasets": datasets}


def _title_rank(title: str) -> tuple[int, str]:
    t = (title or "").strip().lower()
    for key, rank in TITLE_RANK.items():
        if key in t:
            return rank, t
    return (25 if t else 99, t)


def office_bearers_for_header(conn) -> list[dict]:
    """Office bearers for PDF letterhead (prefer is_office_bearer + title)."""
    try:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, name, official_title, phone, is_office_bearer, role
            FROM residents
            WHERE status = 'active' AND house_id != ?
              AND (
                is_office_bearer = 1
                OR role = 'admin'
                OR (official_title IS NOT NULL AND TRIM(official_title) != '')
              )
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    except Exception:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, name, official_title, phone
            FROM residents
            WHERE role = 'admin' AND status = 'active' AND house_id != ?
            """,
            (SUPERADMIN_HOUSE_ID,),
        ).fetchall()
    members = [
        {
            "houseId": r["house_id"],
            "name": r["name"] or r["house_id"],
            "officialTitle": (r["official_title"] or "").strip(),
            "phone": r["phone"] or "",
        }
        for r in rows
    ]
    office = [m for m in members if m["officialTitle"]]
    office.sort(key=lambda m: (_title_rank(m["officialTitle"]), m["name"].lower()))
    if office:
        return office
    members.sort(key=lambda m: m["name"].lower())
    return [
        {**m, "officialTitle": m["officialTitle"] or "Office Bearer"}
        for m in members
    ]


def _fmt_inr(n: int | float | None) -> str:
    """Currency for PDF (Helvetica/WinAnsi has no ₹ — use Rs to avoid black tofu boxes)."""
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        v = 0
    sign = "-" if v < 0 else ""
    s = f"{abs(v):,}"
    return f"{sign}Rs {s}"


def _pdf_safe(text) -> str:
    """Strip glyphs Helvetica cannot draw (otherwise ReportLab shows solid black boxes)."""
    s = "" if text is None else str(text)
    s = s.replace("\u20b9", "Rs ")  # ₹
    s = s.replace("\u2014", "-")  # —
    s = s.replace("\u2013", "-")  # –
    s = s.replace("\u2026", "...")  # …
    s = s.replace("\u2713", "OK")  # ✓
    s = s.replace("\u2717", "X")  # ✗
    s = s.replace("\u25be", "v")  # ▾
    s = s.replace("\u00a0", " ")
    return s


def _normalize_house_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[\s,;]+", raw.strip())
        return [p.strip() for p in parts if p.strip()]
    out = []
    for item in raw:
        s = str(item or "").strip()
        if s:
            out.append(s)
    return out


def query_pending_dues_rows(conn, enrich_payment_row, *, filters: dict | None = None) -> list[dict]:
    """Latest ledger rows joined to residents, filtered for the report."""
    filters = filters or {}
    pending_only = bool(filters.get("pendingOnly", True))
    section = str(filters.get("section") or "all").strip()
    search = str(filters.get("search") or "").strip().lower()
    house_ids = {h.upper() for h in _normalize_house_list(filters.get("houseIds"))}

    rows = conn.execute(
        """
        SELECT pr.*, r.name, r.section, r.plot_no, r.phone, r.status AS resident_status
        FROM payment_rows pr
        JOIN residents r ON r.house_id = pr.house_id
        WHERE pr.ledger_id = (
          SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1
        )
          AND r.house_id != ?
          AND r.status = 'active'
        """,
        (SUPERADMIN_HOUSE_ID,),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        item = {
            **enrich_payment_row(r),
            "plotNo": r["plot_no"] or r["house_id"],
            "section": r["section"] or "",
            "name": r["name"] or r["house_id"],
            "phone": r["phone"] or "",
            "houseId": r["house_id"],
        }
        hid = str(item["houseId"] or "").upper()
        if house_ids and hid not in house_ids and str(item["plotNo"] or "").upper() not in house_ids:
            continue
        if section and section.lower() not in {"all", ""}:
            if str(item["section"] or "").upper() != section.upper():
                continue
        if search:
            blob = f"{item['plotNo']} {item['name']} {item['houseId']} {item.get('phone') or ''}".lower()
            if search not in blob:
                continue
        if pending_only and int(item.get("pendingDues") or 0) <= 0:
            continue
        out.append(item)
    out.sort(
        key=lambda row: section_plot_sort_key(
            row.get("section"),
            row.get("plotNo") or row.get("houseId"),
            row.get("houseId"),
        )
    )
    return out


def _resolve_fields(field_ids: list[str] | None) -> list[dict]:
    by_id = {f["id"]: f for f in PENDING_DUES_FIELDS}
    if not field_ids:
        return [f for f in PENDING_DUES_FIELDS if f.get("default")]
    selected = []
    seen = set()
    for fid in field_ids:
        if fid in by_id and fid not in seen:
            selected.append(by_id[fid])
            seen.add(fid)
    if "sno" not in seen:
        selected.insert(0, by_id["sno"])
    if len(selected) < 2:
        return [f for f in PENDING_DUES_FIELDS if f.get("default")]
    return selected


def _seal_path(site_root: Path) -> Path | None:
    for name in (
        "assets/hbcs-sanyard-seal-mark.png",
        "assets/hbcs-sanyard-seal-mark.jpg",
        "assets/hbcs-sanyard-seal-240.jpg",
        "assets/hbcs-sanyard-seal-512.png",
    ):
        path = site_root / name
        if path.is_file():
            return path
    return None


def _cell(value: str, *, align: str = "left", markup: bool = False):
    rl = _reportlab()
    styles = rl["getSampleStyleSheet"]()
    a = rl["TA_LEFT"]
    if align == "right":
        a = rl["TA_RIGHT"]
    elif align == "center":
        a = rl["TA_CENTER"]
    style = rl["ParagraphStyle"](
        "cell",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9,
        alignment=a,
    )
    text = _pdf_safe(value if value is not None else "-")
    if not markup:
        text = text.replace("&", "&amp;").replace("<", "&lt;")
    return rl["Paragraph"](text or "-", style)


def build_pending_dues_pdf(
    conn,
    *,
    site_root: Path,
    enrich_payment_row,
    fields: list[str] | None = None,
    filters: dict | None = None,
    org_title: str | None = None,
    org_subtitle: str | None = None,
) -> bytes:
    """Return PDF bytes for Pending Dues Report."""
    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Spacer = rl["Spacer"]
    Image = rl["Image"]
    styles = rl["getSampleStyleSheet"]()

    filters = filters or {}
    field_defs = _resolve_fields(fields)
    rows = query_pending_dues_rows(conn, enrich_payment_row, filters=filters)
    bearers = office_bearers_for_header(conn)

    org = org_title or "Housing Board Colony Sanyard\nResidents Welfare Association"
    sub = org_subtitle or "HIMUDA Housing Colony Sanyard · Mandi (H.P.)"
    generated = _fmt_ist_datetime()

    buf = io.BytesIO()
    page = rl["landscape"](rl["A4"])
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title="Pending Dues Report - HBC Sanyard RWA",
        author="HBC Sanyard RWA",
    )

    org_style = ParagraphStyle(
        "org",
        parent=styles["Heading1"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#15233f"),
        alignment=rl["TA_LEFT"],
        spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#4a3728"),
        spaceAfter=2,
    )
    report_style = ParagraphStyle(
        "reportTitle",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#15233f"),
        alignment=rl["TA_CENTER"],
        spaceBefore=4,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "meta",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#555555"),
    )
    bearer_style = ParagraphStyle(
        "bearer",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#3d2914"),
    )

    story: list = []

    seal = _seal_path(site_root)
    header_left: list = []
    if seal:
        try:
            img = Image(str(seal), width=18 * mm, height=18 * mm)
            header_left.append(img)
        except Exception:
            pass
    org_block = [
        Paragraph(org.replace("\n", "<br/>"), org_style),
        Paragraph(sub, sub_style),
    ]
    if header_left:
        header_table = Table(
            [[header_left[0], org_block]],
            colWidths=[22 * mm, doc.width - 22 * mm],
        )
        header_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ])
        )
        story.append(header_table)
    else:
        story.extend(org_block)

    if bearers:
        bits = []
        for b in bearers[:6]:
            post = b["officialTitle"] or "EC Member"
            bits.append(f"<b>{post}</b>: {b['name']}")
        story.append(Paragraph(" · ".join(bits), bearer_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Pending Dues Report", report_style))

    filt_bits = []
    if filters.get("pendingOnly", True):
        filt_bits.append("pending only")
    else:
        filt_bits.append("all ledger rows")
    sec = str(filters.get("section") or "all")
    if sec and sec.lower() not in {"all", ""}:
        filt_bits.append(f"section {sec}")
    if filters.get("search"):
        filt_bits.append(f"search “{filters['search']}”")
    ids = _normalize_house_list(filters.get("houseIds"))
    if ids:
        filt_bits.append(f"{len(ids)} selected plot(s)")
    story.append(
        Paragraph(
            f"Generated {generated} · {len(rows)} plot(s) · " + " · ".join(filt_bits),
            meta_style,
        )
    )
    story.append(Spacer(1, 3 * mm))

    header_row = [
        Paragraph(
            f"<b>{f['label']}</b>",
            ParagraphStyle(
                "th",
                parent=styles["Normal"],
                fontSize=7.5,
                textColor=colors.white,
                alignment=rl["TA_CENTER"],
            ),
        )
        for f in field_defs
    ]
    data = [header_row]
    totals = {fid: 0 for fid in MONEY_FIELDS}

    for i, row in enumerate(rows, 1):
        cells = []
        for f in field_defs:
            fid = f["id"]
            if fid == "sno":
                val = str(i)
            elif fid in MONEY_FIELDS:
                num = int(row.get(fid) or 0)
                totals[fid] = totals.get(fid, 0) + num
                val = _fmt_inr(num)
            else:
                val = str(row.get(fid) or "-")
            cells.append(_cell(val, align=f.get("align") or "left"))
        data.append(cells)

    if rows:
        total_cells = []
        for f in field_defs:
            fid = f["id"]
            if fid == "sno":
                total_cells.append(_cell(""))
            elif fid == "name":
                total_cells.append(_cell("<b>Total</b>", align="left", markup=True))
            elif fid in MONEY_FIELDS:
                total_cells.append(
                    _cell(f"<b>{_fmt_inr(totals.get(fid, 0))}</b>", align="right", markup=True)
                )
            else:
                total_cells.append(_cell(""))
        data.append(total_cells)

    col_widths = [min(f.get("width", 50), 140) for f in field_defs]
    total_w = sum(col_widths) or 1
    scale = doc.width / total_w
    col_widths = [w * scale for w in col_widths]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15233f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b4a2e")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if rows else -1), [colors.HexColor("#fffdf8"), colors.HexColor("#f5f1e8")]),
    ]
    if rows:
        style_cmds.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ebe4d4")))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            "Service to the Colony · Collective Strength · Cooperation for All - HBC Sanyard RWA",
            ParagraphStyle("foot", parent=meta_style, alignment=rl["TA_CENTER"], fontSize=7.5),
        )
    )

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(12 * mm, 8 * mm, "HBC Sanyard RWA - Pending Dues Report")
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def list_report_templates(conn) -> list[dict]:
    from init_rwa_db import ensure_report_templates_table

    ensure_report_templates_table(conn)
    rows = conn.execute(
        """
        SELECT id, name, dataset, fields_json, filters_json, created_by, created_at, updated_at
        FROM report_templates
        ORDER BY name COLLATE NOCASE
        """
    ).fetchall()
    out = []
    for r in rows:
        try:
            fields = json.loads(r["fields_json"] or "[]")
        except Exception:
            fields = []
        try:
            filters = json.loads(r["filters_json"] or "{}")
        except Exception:
            filters = {}
        out.append({
            "id": r["id"],
            "name": r["name"],
            "dataset": r["dataset"],
            "fields": fields if isinstance(fields, list) else [],
            "filters": filters if isinstance(filters, dict) else {},
            "createdBy": r["created_by"] or "",
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        })
    return out


def save_report_template(conn, payload: dict, *, created_by: str | None = None) -> dict:
    import secrets
    from init_rwa_db import ensure_report_templates_table, utc_now

    ensure_report_templates_table(conn)
    name = str(payload.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("Template name required")
    dataset = str(payload.get("dataset") or "").strip()
    if dataset not in DATASETS_META:
        raise ValueError("Invalid dataset")
    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("Select at least one field")
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    tpl_id = str(payload.get("id") or "").strip() or f"rt_{secrets.token_hex(6)}"
    now = utc_now()
    existing = conn.execute("SELECT id, created_at, created_by FROM report_templates WHERE id = ?", (tpl_id,)).fetchone()
    fields_json = json.dumps(fields, ensure_ascii=False)
    filters_json = json.dumps(filters, ensure_ascii=False)
    if existing:
        conn.execute(
            """
            UPDATE report_templates
            SET name=?, dataset=?, fields_json=?, filters_json=?, updated_at=?
            WHERE id=?
            """,
            (name, dataset, fields_json, filters_json, now, tpl_id),
        )
        created_at = existing["created_at"]
        created_by = existing["created_by"] or created_by
    else:
        conn.execute(
            """
            INSERT INTO report_templates(id, name, dataset, fields_json, filters_json, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tpl_id, name, dataset, fields_json, filters_json, created_by, now, now),
        )
        created_at = now
    conn.commit()
    return {
        "id": tpl_id,
        "name": name,
        "dataset": dataset,
        "fields": fields,
        "filters": filters,
        "createdBy": created_by or "",
        "createdAt": created_at,
        "updatedAt": now,
    }


def delete_report_template(conn, template_id: str) -> None:
    from init_rwa_db import ensure_report_templates_table

    ensure_report_templates_table(conn)
    tid = (template_id or "").strip()
    if not tid:
        raise ValueError("template id required")
    cur = conn.execute("DELETE FROM report_templates WHERE id = ?", (tid,))
    conn.commit()
    if cur.rowcount == 0:
        raise ValueError("Template not found")


def _resolve_dataset_fields(dataset: str, field_ids: list[str] | None) -> list[dict]:
    meta = DATASETS_META.get(dataset)
    if not meta:
        raise ValueError("Unknown dataset")
    catalog = meta["fields"]
    by_id = {f["id"]: f for f in catalog}
    if not field_ids:
        return [f for f in catalog if f.get("default")]
    selected = []
    seen = set()
    for fid in field_ids:
        if fid in by_id and fid not in seen:
            selected.append(by_id[fid])
            seen.add(fid)
    if "sno" in by_id and "sno" not in seen:
        selected.insert(0, by_id["sno"])
    if len(selected) < 2:
        return [f for f in catalog if f.get("default")]
    return selected


def query_directory_rows(directory_fn, conn, *, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    rows = directory_fn(conn, include_contacts=True)
    section = str(filters.get("section") or "all").strip()
    search = str(filters.get("search") or "").strip().lower()
    ob_only = bool(filters.get("officeBearersOnly"))
    out = []
    for r in rows:
        if (r.get("status") or "active") != "active":
            continue
        if ob_only and not r.get("isOfficeBearer") and not r.get("officialTitle"):
            continue
        if section and section.lower() not in {"all", ""}:
            if str(r.get("section") or "").upper() != section.upper():
                continue
        if search:
            blob = f"{r.get('plotNo')} {r.get('name')} {r.get('phone')} {r.get('email')} {r.get('officialTitle')}".lower()
            if search not in blob:
                continue
        out.append(r)
    out.sort(
        key=lambda row: section_plot_sort_key(
            row.get("section"),
            row.get("plotNo") or row.get("houseId"),
            row.get("houseId"),
        )
    )
    return out


def query_concerns_rows(list_grievances, conn, *, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    status = str(filters.get("status") or "open").strip() or "open"
    category = str(filters.get("category") or "all").strip() or "all"
    search = str(filters.get("search") or "").strip().lower()
    items = list_grievances(
        conn,
        status=None if status == "all" else status,
        category=None if category == "all" else category,
        limit=300,
        include_contacts=True,
    )
    out = []
    for g in items:
        row = {
            "plotNo": g.get("plotNo") or g.get("houseId") or "",
            "category": g.get("category") or "",
            "status": g.get("status") or "",
            "subject": g.get("subject") or g.get("title") or (g.get("body") or "")[:80],
            "updatedAt": (g.get("updatedAt") or g.get("createdAt") or "")[:16],
        }
        if search:
            blob = f"{row['plotNo']} {row['category']} {row['subject']} {row['status']}".lower()
            if search not in blob:
                continue
        out.append(row)
    return out


def query_payment_record_rows(
    conn,
    *,
    filters: dict | None = None,
    kind: str | None = None,
    force_method: str | None = None,
) -> list[dict]:
    """Rows from payment_records for payments / cash / claims / all transactions."""
    import rwa_payments

    filters = filters or {}
    status = str(filters.get("status") or "all").strip() or "all"
    search = str(filters.get("search") or "").strip().lower()
    method = str(force_method or filters.get("method") or "all").strip() or "all"
    house_ids = {h.upper() for h in _normalize_house_list(filters.get("houseIds"))}

    records = rwa_payments.list_records(
        conn,
        status=None if status == "all" else status,
        kind=None if not kind or kind == "all" else kind,
        limit=500,
    )
    out = []
    for rec in records:
        if method and method != "all" and str(rec.get("method") or "") != method:
            continue
        hid = str(rec.get("houseId") or "").upper()
        plot = str(rec.get("plotNo") or hid).upper()
        if house_ids and hid not in house_ids and plot not in house_ids:
            continue
        row = {
            "paidOn": (rec.get("paidOn") or "")[:10],
            "plotNo": rec.get("plotNo") or rec.get("houseId") or "",
            "houseId": rec.get("houseId") or "",
            "residentName": rec.get("residentName") or "",
            "kindLabel": rec.get("kindLabel") or rec.get("kind") or "",
            "categoryLabel": rec.get("categoryLabel") or rec.get("category") or "",
            "methodLabel": rec.get("methodLabel") or rec.get("method") or "",
            "amount": int(rec.get("amount") or 0),
            "feeYear": rec.get("feeYear") or "",
            "status": rec.get("status") or "",
            "treasuryStatus": rec.get("treasuryStatus") or "pending",
            "note": (rec.get("note") or "")[:120],
            "reviewedAt": (rec.get("reviewedAt") or "")[:16],
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    out.sort(
        key=lambda r: (
            r.get("paidOn") or "",
            *section_plot_sort_key("", r.get("plotNo"), r.get("houseId")),
        ),
        reverse=True,
    )
    return out


def query_no_dues_rows(conn, *, filters: dict | None = None) -> list[dict]:
    import rwa_no_dues

    filters = filters or {}
    status = str(filters.get("status") or "all").strip() or "all"
    search = str(filters.get("search") or "").strip().lower()
    house_ids = {h.upper() for h in _normalize_house_list(filters.get("houseIds"))}
    items = rwa_no_dues.list_requests(
        conn,
        status=None if status == "all" else status,
        limit=300,
    )
    out = []
    for item in items:
        hid = str(item.get("houseId") or "").upper()
        plot = str(item.get("plotNo") or hid).upper()
        if house_ids and hid not in house_ids and plot not in house_ids:
            continue
        row = {
            "plotNo": item.get("plotNo") or item.get("houseId") or "",
            "houseId": item.get("houseId") or "",
            "residentName": item.get("residentName") or "",
            "status": item.get("statusLabel") or item.get("status") or "",
            "treasuryStatus": item.get("treasuryStatus") or "pending",
            "createdAt": (item.get("createdAt") or "")[:10],
            "issuedAt": (item.get("issuedAt") or "")[:10],
            "requestNote": (item.get("requestNote") or "")[:120],
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    out.sort(
        key=lambda r: section_plot_sort_key("", r.get("plotNo"), r.get("houseId")),
    )
    return out


def query_works_rows(list_colony_works, conn, *, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    status = str(filters.get("status") or "all").strip() or "all"
    search = str(filters.get("search") or "").strip().lower()
    items = list_colony_works(
        conn,
        status=None if status == "all" else status,
        as_admin=True,
    )
    out = []
    for w in items:
        row = {
            "title": w.get("title") or "",
            "kind": w.get("kindLabel") or w.get("kind") or "",
            "status": w.get("statusLabel") or w.get("status") or "",
            "estimatedCost": int(w.get("estimatedCost") or w.get("estCost") or 0),
            "actualCost": int(w.get("actualCost") or w.get("actCost") or 0),
            "startDate": (w.get("startDate") or "")[:10],
            "endDate": (w.get("endDate") or "")[:10],
            "visibility": w.get("visibility") or "",
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    return out


def query_notices_rows(list_notices, conn, *, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    status = str(filters.get("status") or "published").strip() or "published"
    search = str(filters.get("search") or "").strip().lower()
    items = list_notices(conn, status=status if status != "all" else "all")
    out = []
    for n in items:
        row = {
            "publishedAt": (n.get("publishedAt") or n.get("updatedAt") or "")[:16],
            "category": n.get("category") or "",
            "title": n.get("title") or "",
            "status": n.get("status") or "",
            "pinned": "Yes" if n.get("pinned") else "",
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    return out


def build_tabular_pdf(
    conn,
    *,
    site_root: Path,
    title: str,
    field_defs: list[dict],
    rows: list[dict],
    money_fields: set[str] | None = None,
    filter_summary: str = "",
) -> bytes:
    """Generic landscape PDF with letterhead + table."""
    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Spacer = rl["Spacer"]
    Image = rl["Image"]
    styles = rl["getSampleStyleSheet"]()
    money_fields = money_fields or set()

    bearers = office_bearers_for_header(conn)
    generated = _fmt_ist_datetime()
    buf = io.BytesIO()
    page = rl["landscape"](rl["A4"])
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title=f"{title} - HBC Sanyard RWA",
        author="HBC Sanyard RWA",
    )
    org_style = ParagraphStyle(
        "org", parent=styles["Heading1"], fontSize=13, leading=16,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_LEFT"], spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#4a3728"), spaceAfter=2,
    )
    report_style = ParagraphStyle(
        "reportTitle", parent=styles["Heading2"], fontSize=11, leading=14,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"], spaceBefore=4, spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "meta", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#555555"),
    )
    bearer_style = ParagraphStyle(
        "bearer", parent=styles["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#3d2914"),
    )
    story: list = []
    seal = _seal_path(site_root)
    org = "Housing Board Colony Sanyard<br/>Residents Welfare Association"
    sub = "HIMUDA Housing Colony Sanyard · Mandi (H.P.)"
    if seal:
        try:
            img = Image(str(seal), width=18 * mm, height=18 * mm)
            header_table = Table(
                [[img, [Paragraph(org, org_style), Paragraph(sub, sub_style)]]],
                colWidths=[22 * mm, doc.width - 22 * mm],
            )
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(header_table)
        except Exception:
            story.append(Paragraph(org, org_style))
            story.append(Paragraph(sub, sub_style))
    else:
        story.append(Paragraph(org, org_style))
        story.append(Paragraph(sub, sub_style))
    if bearers:
        bits = [f"<b>{b['officialTitle'] or 'Office Bearer'}</b>: {b['name']}" for b in bearers[:6]]
        story.append(Paragraph(" · ".join(bits), bearer_style))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(title, report_style))
    story.append(Paragraph(
        f"Generated {generated} · {len(rows)} row(s)" + (f" · {filter_summary}" if filter_summary else ""),
        meta_style,
    ))
    story.append(Spacer(1, 3 * mm))

    header_row = [
        Paragraph(
            f"<b>{f['label']}</b>",
            ParagraphStyle("th", parent=styles["Normal"], fontSize=7.5, textColor=colors.white, alignment=rl["TA_CENTER"]),
        )
        for f in field_defs
    ]
    data = [header_row]
    totals = {fid: 0 for fid in money_fields}
    for i, row in enumerate(rows, 1):
        cells = []
        for f in field_defs:
            fid = f["id"]
            if fid == "sno":
                val = str(i)
            elif fid in money_fields:
                num = int(row.get(fid) or 0)
                totals[fid] = totals.get(fid, 0) + num
                val = _fmt_inr(num)
            else:
                val = str(row.get(fid) or "-")
            cells.append(_cell(val, align=f.get("align") or "left"))
        data.append(cells)
    if rows and money_fields:
        total_cells = []
        for f in field_defs:
            fid = f["id"]
            if fid == "name":
                total_cells.append(_cell("<b>Total</b>", align="left", markup=True))
            elif fid in money_fields:
                total_cells.append(_cell(f"<b>{_fmt_inr(totals.get(fid, 0))}</b>", align="right", markup=True))
            else:
                total_cells.append(_cell(""))
        data.append(total_cells)

    col_widths = [min(f.get("width", 50), 140) for f in field_defs]
    scale = doc.width / (sum(col_widths) or 1)
    col_widths = [w * scale for w in col_widths]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15233f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#6b4a2e")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2 if (rows and money_fields) else -1),
         [colors.HexColor("#fffdf8"), colors.HexColor("#f5f1e8")]),
    ]
    if rows and money_fields:
        style_cmds.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ebe4d4")))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(12 * mm, 8 * mm, f"HBC Sanyard RWA - {title}")
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def no_dues_eligibility(conn, house_id: str, *, enrich_payment_row) -> dict:
    """Check whether a plot can receive a No Dues Certificate."""
    from init_rwa_db import ensure_payment_records_tables

    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("houseId required")
    resident = conn.execute(
        """
        SELECT house_id, plot_no, name, section, status
        FROM residents WHERE house_id = ?
        """,
        (hid,),
    ).fetchone()
    if not resident:
        raise ValueError(f"Unknown plot {hid}")
    if (resident["status"] or "") != "active":
        raise ValueError("Plot is not active on the roster")

    row = conn.execute(
        """
        SELECT pr.*, pl.as_of, pl.source
        FROM payment_rows pr
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.house_id = ?
        ORDER BY pl.as_of DESC, pr.id DESC
        LIMIT 1
        """,
        (hid,),
    ).fetchone()
    if not row:
        raise ValueError("No ledger row for this plot yet")
    payment = enrich_payment_row(row)
    outstanding = int(payment.get("pendingDues") if payment.get("pendingDues") is not None else payment.get("balanceOutstanding") or 0)

    ensure_payment_records_tables(conn)
    pending_receipts = conn.execute(
        """
        SELECT COUNT(*) FROM payment_records
        WHERE house_id = ? AND status = 'submitted'
          AND COALESCE(kind, 'payment') = 'payment'
        """,
        (hid,),
    ).fetchone()[0]

    clear = outstanding <= 0 and int(pending_receipts or 0) == 0
    return {
        "eligible": clear,
        "houseId": hid,
        "plotNo": resident["plot_no"] or hid,
        "name": resident["name"] or hid,
        "section": resident["section"] or "",
        "outstanding": outstanding,
        "pendingReceipts": int(pending_receipts or 0),
        "payment": payment,
        "reason": (
            None
            if clear
            else (
                f"Outstanding dues {outstanding}" if outstanding > 0
                else f"{pending_receipts} payment receipt(s) awaiting EC verification"
            )
        ),
    }


def build_no_dues_certificate_pdf(
    conn,
    *,
    site_root: Path,
    house_id: str,
    enrich_payment_row,
    issued_by: str | None = None,
    purpose: str | None = None,
    letterhead: bool = True,
    require_eligible: bool = True,
    attestation_id: str | None = None,
    verify_url: str | None = None,
) -> tuple[bytes, str]:
    """Portrait No Dues Certificate PDF for one plot.

    letterhead=True (digital): seal + org header for screen/share.
    letterhead=False (paper print): omit letterhead; enlarge top/bottom margins
    so the body fits pre-printed RWA letterhead stationery.
    """
    info = no_dues_eligibility(conn, house_id, enrich_payment_row=enrich_payment_row)
    if require_eligible and not info["eligible"]:
        raise ValueError(info.get("reason") or "Plot is not clear of dues")

    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Image = rl["Image"]
    styles = rl["getSampleStyleSheet"]()

    bearers = office_bearers_for_header(conn)
    issued = _fmt_ist_date()
    fee_year = info["payment"].get("feeYear") or _now_ist().year
    purpose_text = (purpose or "").strip()[:400] or "Official / banking / transfer purposes"

    # Paper print leaves room for physical letterhead / stamp area.
    top_m = 48 * mm if not letterhead else 16 * mm
    bottom_m = 32 * mm if not letterhead else 16 * mm

    buf = io.BytesIO()
    page = rl["A4"]
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=f"No Dues Certificate - House/Plot {info['plotNo']}",
        author="HBC Sanyard RWA",
    )

    org_style = ParagraphStyle(
        "ndOrg", parent=styles["Heading1"], fontSize=14, leading=18,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"], spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "ndSub", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#4a3728"), alignment=rl["TA_CENTER"], spaceAfter=8,
    )
    title_style = ParagraphStyle(
        "ndTitle", parent=styles["Heading1"], fontSize=16, leading=20,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"],
        spaceBefore=10 if letterhead else 4, spaceAfter=14,
    )
    body_style = ParagraphStyle(
        "ndBody", parent=styles["Normal"], fontSize=11, leading=16,
        textColor=colors.HexColor("#1a1a1a"), alignment=rl["TA_JUSTIFY"], spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "ndMeta", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#444444"), spaceAfter=4,
    )

    story = []
    if letterhead:
        seal = _seal_path(site_root)
        if seal:
            try:
                img = Image(str(seal), width=22 * mm, height=22 * mm)
                img.hAlign = "CENTER"
                story.append(img)
                story.append(Spacer(1, 4 * mm))
            except Exception:
                pass

        story.append(Paragraph("Housing Board Colony Sanyard<br/>Residents Welfare Association", org_style))
        story.append(Paragraph("HIMUDA Housing Colony Sanyard · Mandi (H.P.)", sub_style))

    story.append(Paragraph("<b>NO DUES CERTIFICATE</b>", title_style))

    house_no = str(info.get("plotNo") or info.get("houseId") or house_id)
    body = (
        f"This is to certify that <b>{_escape(info['name'])}</b>, "
        f"resident of House/Plot <b>{_escape(house_no)}</b>, "
        f"Housing Board Colony Sanyard, Mandi, has <b>no outstanding subscription / maintenance dues</b> "
        f"as per the RWA ledger on record for fee year <b>{fee_year}</b>."
    )
    story.append(Paragraph(body, body_style))
    story.append(Paragraph(
        "Outstanding balance on the latest ledger: <b>Rs 0</b> "
        "(no pending dues; no payment receipts awaiting verification).",
        body_style,
    ))
    story.append(Paragraph(f"<b>Purpose:</b> {_escape(purpose_text)}", body_style))
    story.append(Paragraph(f"Issued on: <b>{issued}</b>", meta_style))
    if issued_by:
        story.append(Paragraph(f"Issued by: {_escape(issued_by)}", meta_style))
    story.append(Spacer(1, 8 * mm))

    if bearers:
        story.append(Paragraph("<b>Office bearers</b>", meta_style))
        for b in bearers[:6]:
            title = b.get("officialTitle") or "Office Bearer"
            story.append(Paragraph(
                f"{_escape(title)} - {_escape(b.get('name') or '')}"
                + (f" · {_escape(b['phone'])}" if b.get("phone") else ""),
                meta_style,
            ))

    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph(
        "This certificate reflects RWA subscription ledger status only and does not cover "
        "municipal taxes or utility bills.",
        ParagraphStyle("ndFoot", parent=meta_style, fontSize=8, leading=10, textColor=colors.HexColor("#666666")),
    ))

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _footer(canvas, _doc):
        # Digital only — paper print leaves the physical letterhead clean.
        if not letterhead:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(18 * mm, 10 * mm, "HBC Sanyard RWA - No Dues Certificate")
        canvas.drawRightString(page[0] - 18 * mm, 10 * mm, f"House/Plot {house_no}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    safe_plot = re.sub(r"[^A-Za-z0-9_-]+", "-", house_no)
    stamp = _now_ist().strftime("%Y%m%d")
    suffix = "" if letterhead else "-print"
    return buf.getvalue(), f"no-dues-{safe_plot}-{stamp}{suffix}.pdf"


def no_objection_eligibility(conn, house_id: str) -> dict:
    """Check whether a plot can receive a No Objection Certificate (active on roster)."""
    hid = (house_id or "").strip()
    if not hid:
        raise ValueError("houseId required")
    resident = conn.execute(
        """
        SELECT house_id, plot_no, name, status
        FROM residents WHERE house_id = ?
        """,
        (hid,),
    ).fetchone()
    if not resident:
        raise ValueError(f"Unknown plot {hid}")
    active = (resident["status"] or "") == "active"
    return {
        "eligible": active,
        "houseId": hid,
        "plotNo": resident["plot_no"] or hid,
        "name": resident["name"] or hid,
        "status": resident["status"] or "",
        "reason": None if active else "Plot is not active on the roster",
    }


def build_no_objection_certificate_pdf(
    conn,
    *,
    site_root: Path,
    house_id: str,
    issued_by: str | None = None,
    purpose: str | None = None,
    letterhead: bool = True,
    require_eligible: bool = True,
    attestation_id: str | None = None,
    verify_url: str | None = None,
) -> tuple[bytes, str]:
    """Portrait No Objection Certificate PDF for one plot.

    letterhead=True (digital): seal + org header for screen/share.
    letterhead=False (paper print): omit letterhead; enlarge top/bottom margins
    so the body fits pre-printed RWA letterhead stationery.
    """
    info = no_objection_eligibility(conn, house_id)
    if require_eligible and not info["eligible"]:
        raise ValueError(info.get("reason") or "Plot is not eligible")

    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Image = rl["Image"]
    styles = rl["getSampleStyleSheet"]()

    bearers = office_bearers_for_header(conn)
    issued = _fmt_ist_date()
    purpose_text = (
        (purpose or "").strip()[:400]
        or "Property transfer / sale / mortgage / official purposes"
    )

    top_m = 48 * mm if not letterhead else 16 * mm
    bottom_m = 32 * mm if not letterhead else 16 * mm

    buf = io.BytesIO()
    page = rl["A4"]
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=f"No Objection Certificate - House/Plot {info['plotNo']}",
        author="HBC Sanyard RWA",
    )

    org_style = ParagraphStyle(
        "nocOrg", parent=styles["Heading1"], fontSize=14, leading=18,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"], spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "nocSub", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#4a3728"), alignment=rl["TA_CENTER"], spaceAfter=8,
    )
    title_style = ParagraphStyle(
        "nocTitle", parent=styles["Heading1"], fontSize=16, leading=20,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"],
        spaceBefore=10 if letterhead else 4, spaceAfter=14,
    )
    body_style = ParagraphStyle(
        "nocBody", parent=styles["Normal"], fontSize=11, leading=16,
        textColor=colors.HexColor("#1a1a1a"), alignment=rl["TA_JUSTIFY"], spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "nocMeta", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#444444"), spaceAfter=4,
    )

    story = []
    if letterhead:
        seal = _seal_path(site_root)
        if seal:
            try:
                img = Image(str(seal), width=22 * mm, height=22 * mm)
                img.hAlign = "CENTER"
                story.append(img)
                story.append(Spacer(1, 4 * mm))
            except Exception:
                pass

        story.append(Paragraph("Housing Board Colony Sanyard<br/>Residents Welfare Association", org_style))
        story.append(Paragraph("HIMUDA Housing Colony Sanyard · Mandi (H.P.)", sub_style))

    story.append(Paragraph("<b>NO OBJECTION CERTIFICATE</b>", title_style))

    house_no = str(info.get("plotNo") or info.get("houseId") or house_id)
    body = (
        f"This is to certify that the Residents Welfare Association of "
        f"Housing Board Colony Sanyard, Mandi, has <b>no objection</b> for "
        f"<b>{_escape(info['name'])}</b>, resident of House/Plot <b>{_escape(house_no)}</b>, "
        f"in respect of the purpose stated below."
    )
    story.append(Paragraph(body, body_style))
    story.append(Paragraph(f"<b>Purpose:</b> {_escape(purpose_text)}", body_style))
    story.append(Paragraph(f"Issued on: <b>{issued}</b>", meta_style))
    if issued_by:
        story.append(Paragraph(f"Issued by: {_escape(issued_by)}", meta_style))
    story.append(Spacer(1, 8 * mm))

    if bearers:
        story.append(Paragraph("<b>Office bearers</b>", meta_style))
        for b in bearers[:6]:
            title = b.get("officialTitle") or "Office Bearer"
            story.append(Paragraph(
                f"{_escape(title)} - {_escape(b.get('name') or '')}"
                + (f" · {_escape(b['phone'])}" if b.get("phone") else ""),
                meta_style,
            ))

    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph(
        "This certificate expresses the RWA's non-objection for the stated purpose only "
        "and does not constitute a dues clearance, title deed, or municipal approval.",
        ParagraphStyle("nocFoot", parent=meta_style, fontSize=8, leading=10, textColor=colors.HexColor("#666666")),
    ))

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _footer(canvas, _doc):
        if not letterhead:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(18 * mm, 10 * mm, "HBC Sanyard RWA - No Objection Certificate")
        canvas.drawRightString(page[0] - 18 * mm, 10 * mm, f"House/Plot {house_no}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    safe_plot = re.sub(r"[^A-Za-z0-9_-]+", "-", house_no)
    stamp = _now_ist().strftime("%Y%m%d")
    suffix = "" if letterhead else "-print"
    return buf.getvalue(), f"no-objection-{safe_plot}-{stamp}{suffix}.pdf"


def build_cash_received_note_pdf(
    *,
    site_root: Path,
    kind: str,
    amount: int,
    paid_on: str,
    plot_no: str,
    payer_name: str,
    receiver_name: str,
    purpose: str = "",
    category_label: str = "",
    attestation_id: str | None = None,
    verify_url: str | None = None,
) -> tuple[bytes, str]:
    """Cash Received Note / Cash Payment Voucher PDF (upload as proof, then EC verifies)."""
    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    Image = rl["Image"]
    styles = rl["getSampleStyleSheet"]()

    is_claim = (kind or "payment").strip().lower() == "reimbursement"
    title = "CASH PAYMENT VOUCHER" if is_claim else "CASH RECEIVED NOTE"
    subtitle = (
        "Proof of cash paid for colony expense / reimbursement claim"
        if is_claim
        else "Proof of cash received toward RWA dues / collection"
    )
    amount = int(amount or 0)
    if amount < 1:
        raise ValueError("Amount is required")
    paid_on = str(paid_on or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", paid_on):
        raise ValueError("Date must be YYYY-MM-DD")
    try:
        paid_fmt = datetime.strptime(paid_on, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError as exc:
        raise ValueError("Invalid date") from exc

    plot_no = str(plot_no or "").strip() or "-"
    payer_name = str(payer_name or "").strip() or "-"
    receiver_name = str(receiver_name or "").strip() or "-"
    purpose = str(purpose or "").strip()[:400]
    category_label = str(category_label or "").strip()

    buf = io.BytesIO()
    page = rl["A4"]
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"{title} - Plot {plot_no}",
        author="HBC Sanyard RWA",
    )

    org_style = ParagraphStyle(
        "crOrg", parent=styles["Heading1"], fontSize=13, leading=17,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"], spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "crSub", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#4a3728"), alignment=rl["TA_CENTER"], spaceAfter=8,
    )
    title_style = ParagraphStyle(
        "crTitle", parent=styles["Heading1"], fontSize=15, leading=19,
        textColor=colors.HexColor("#15233f"), alignment=rl["TA_CENTER"],
        spaceBefore=8, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "crBody", parent=styles["Normal"], fontSize=10.5, leading=15,
        textColor=colors.HexColor("#1a1a1a"), alignment=rl["TA_LEFT"], spaceAfter=8,
    )
    meta_style = ParagraphStyle(
        "crMeta", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#444444"), spaceAfter=3,
    )
    sign_style = ParagraphStyle(
        "crSign", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor("#222222"), spaceBefore=2, spaceAfter=2,
    )

    story = []
    seal = _seal_path(site_root)
    if seal:
        try:
            img = Image(str(seal), width=20 * mm, height=20 * mm)
            img.hAlign = "CENTER"
            story.append(img)
            story.append(Spacer(1, 3 * mm))
        except Exception:
            pass

    story.append(Paragraph("Housing Board Colony Sanyard<br/>Residents Welfare Association", org_style))
    story.append(Paragraph("HIMUDA Housing Colony Sanyard · Mandi (H.P.)", sub_style))
    story.append(Paragraph(f"<b>{title}</b>", title_style))
    story.append(Paragraph(subtitle, sub_style))

    rows = [
        [Paragraph("<b>Date</b>", meta_style), Paragraph(_escape(paid_fmt), meta_style)],
        [Paragraph("<b>Plot</b>", meta_style), Paragraph(_escape(plot_no), meta_style)],
        [Paragraph("<b>Amount</b>", meta_style), Paragraph(f"Rs {amount:,}", meta_style)],
    ]
    if category_label:
        rows.append([Paragraph("<b>Category</b>", meta_style), Paragraph(_escape(category_label), meta_style)])
    if is_claim:
        rows.append([Paragraph("<b>Paid by (resident)</b>", meta_style), Paragraph(_escape(payer_name), meta_style)])
        rows.append([Paragraph("<b>Cash received by</b>", meta_style), Paragraph(_escape(receiver_name), meta_style)])
    else:
        rows.append([Paragraph("<b>Paid by (resident)</b>", meta_style), Paragraph(_escape(payer_name), meta_style)])
        rows.append([Paragraph("<b>Cash received by (RWA)</b>", meta_style), Paragraph(_escape(receiver_name), meta_style)])
    if purpose:
        rows.append([Paragraph("<b>Particulars</b>", meta_style), Paragraph(_escape(purpose), meta_style)])

    table = Table(rows, colWidths=[55 * mm, 110 * mm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9b8a0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2d5c4")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f1e8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 8 * mm))

    if is_claim:
        story.append(Paragraph(
            "This voucher acknowledges that cash was paid for the stated colony expense. "
            "Attach / upload this note as claim proof. An authorised EC member must verify and approve "
            "before reimbursement is marked paid.",
            body_style,
        ))
    else:
        story.append(Paragraph(
            "This note acknowledges that cash was received toward RWA dues / collection for the plot above. "
            "The recipient should sign, upload this note as the payment receipt, and another authorised "
            "EC member must verify it before the ledger is updated.",
            body_style,
        ))

    story.append(Spacer(1, 16 * mm))
    story.append(Paragraph("<b>Signatures</b>", meta_style))
    story.append(Spacer(1, 10 * mm))
    sig = Table(
        [[
            Paragraph("_________________________<br/>Payer / Resident", sign_style),
            Paragraph("_________________________<br/>Cash recipient", sign_style),
        ]],
        colWidths=[85 * mm, 85 * mm],
    )
    story.append(sig)
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph(
        "_________________________<br/>EC verifier (after upload)",
        sign_style,
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "Generated from the HBC Sanyard RWA portal. Print, sign if needed, then upload as receipt proof.",
        ParagraphStyle("crFoot", parent=meta_style, fontSize=8, leading=10, textColor=colors.HexColor("#666666")),
    ))

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(18 * mm, 10 * mm, f"HBC Sanyard RWA - {title}")
        canvas.drawRightString(page[0] - 18 * mm, 10 * mm, f"Plot {plot_no} · Rs {amount:,}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    safe_plot = re.sub(r"[^A-Za-z0-9_-]+", "-", plot_no) or "plot"
    stamp = _now_ist().strftime("%Y%m%d")
    prefix = "cash-voucher" if is_claim else "cash-received"
    return buf.getvalue(), f"{prefix}-{safe_plot}-{stamp}.pdf"


def _escape(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_report_pdf(
    conn,
    *,
    site_root: Path,
    enrich_payment_row,
    payload: dict,
    list_grievances=None,
    directory_fn=None,
    list_colony_works=None,
    list_notices=None,
) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for builtin / custom / saved template."""
    report_id = str(payload.get("reportId") or payload.get("id") or "pending-dues").strip()
    fields = payload.get("fields") if isinstance(payload.get("fields"), list) else None
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    for key in (
        "pendingOnly", "section", "search", "houseIds", "status", "category",
        "officeBearersOnly", "method", "dataset",
    ):
        if key in payload and key not in filters:
            filters[key] = payload[key]

    stamp = _now_ist().strftime("%Y%m%d")

    if report_id.startswith("template:"):
        tid = report_id.split(":", 1)[1]
        templates = {t["id"]: t for t in list_report_templates(conn)}
        tpl = templates.get(tid)
        if not tpl:
            raise ValueError("Saved template not found")
        report_id = "custom"
        payload = {
            "dataset": tpl["dataset"],
            "fields": fields or tpl["fields"],
            "filters": {**(tpl.get("filters") or {}), **filters},
            "title": payload.get("title") or tpl.get("name"),
        }
        fields = payload["fields"]
        filters = payload["filters"]

    if report_id == "pending-dues":
        pdf = build_pending_dues_pdf(
            conn,
            site_root=site_root,
            enrich_payment_row=enrich_payment_row,
            fields=fields,
            filters=filters,
        )
        return pdf, f"pending-dues-{stamp}.pdf"

    if report_id == "custom":
        dataset = str(payload.get("dataset") or filters.get("dataset") or "").strip()
        if dataset not in DATASETS_META:
            raise ValueError("Select a dataset for the custom report")
        field_defs = _resolve_dataset_fields(dataset, fields)
        title = str(payload.get("title") or DATASETS_META[dataset]["title"])
        money = MONEY_FIELDS

        if dataset == "dues":
            rows = query_pending_dues_rows(conn, enrich_payment_row, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Custom Dues Report",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · dues",
            )
            return pdf, f"custom-dues-{stamp}.pdf"

        if dataset == "payments":
            rows = query_payment_record_rows(conn, filters=filters, kind="payment")
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Payments Received",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · payments",
            )
            return pdf, f"custom-payments-{stamp}.pdf"

        if dataset == "cash":
            rows = query_payment_record_rows(conn, filters=filters, force_method="cash")
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Cash Register",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · cash register",
            )
            return pdf, f"custom-cash-{stamp}.pdf"

        if dataset == "reimbursements":
            rows = query_payment_record_rows(conn, filters=filters, kind="reimbursement")
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Reimbursement Claims",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · reimbursements",
            )
            return pdf, f"custom-reimbursements-{stamp}.pdf"

        if dataset == "transactions":
            rows = query_payment_record_rows(conn, filters=filters, kind="all")
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "All Transactions",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · transactions",
            )
            return pdf, f"custom-transactions-{stamp}.pdf"

        if dataset == "no_dues":
            rows = query_no_dues_rows(conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "No Dues Certificates",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · no dues",
            )
            return pdf, f"custom-no-dues-{stamp}.pdf"

        if dataset == "directory":
            if not directory_fn:
                raise ValueError("Directory source unavailable")
            rows = query_directory_rows(directory_fn, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Directory Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · directory",
            )
            return pdf, f"custom-directory-{stamp}.pdf"

        if dataset == "concerns":
            if not list_grievances:
                raise ValueError("Concerns source unavailable")
            rows = query_concerns_rows(list_grievances, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Concerns Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · concerns",
            )
            return pdf, f"custom-concerns-{stamp}.pdf"

        if dataset == "works":
            if not list_colony_works:
                raise ValueError("Works source unavailable")
            rows = query_works_rows(list_colony_works, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Works & Events",
                field_defs=field_defs, rows=rows, money_fields=money,
                filter_summary="custom · works",
            )
            return pdf, f"custom-works-{stamp}.pdf"

        if dataset == "notices":
            if not list_notices:
                raise ValueError("Notices source unavailable")
            rows = query_notices_rows(list_notices, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Notices Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · notices",
            )
            return pdf, f"custom-notices-{stamp}.pdf"

        raise ValueError("Unsupported dataset")

    raise ValueError(f"Unknown report: {report_id}")
