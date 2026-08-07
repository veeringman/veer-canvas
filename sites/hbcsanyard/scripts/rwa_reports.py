"""RWA PDF reports (EC desk). Pending dues first; header with seal + office bearers."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from init_rwa_db import SUPERADMIN_HOUSE_ID

_RL = None  # lazy reportlab bundle


def _reportlab():
    """Import reportlab on first PDF build (keeps admin app bootable without it)."""
    global _RL
    if _RL is not None:
        return _RL
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
}

DIRECTORY_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 48},
    {"id": "section", "label": "Sec.", "default": True, "align": "center", "width": 32},
    {"id": "name", "label": "Name", "default": True, "align": "left", "width": 120},
    {"id": "officialTitle", "label": "Office", "default": True, "align": "left", "width": 90},
    {"id": "phone", "label": "Phone", "default": True, "align": "left", "width": 72},
    {"id": "email", "label": "Email", "default": False, "align": "left", "width": 110},
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

DATASETS_META = {
    "dues": {
        "id": "dues",
        "title": "Dues / ledger",
        "fields": PENDING_DUES_FIELDS,
        "defaultFilters": {"pendingOnly": True, "section": "all", "search": "", "houseIds": []},
    },
    "directory": {
        "id": "directory",
        "title": "Resident directory",
        "fields": DIRECTORY_FIELDS,
        "defaultFilters": {"section": "all", "search": "", "officeBearersOnly": False},
    },
    "concerns": {
        "id": "concerns",
        "title": "Resident concerns",
        "fields": CONCERNS_FIELDS,
        "defaultFilters": {"status": "open", "category": "all", "search": ""},
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
    try:
        v = int(n or 0)
    except (TypeError, ValueError):
        v = 0
    sign = "-" if v < 0 else ""
    s = f"{abs(v):,}"
    return f"{sign}₹{s}"


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
        ORDER BY r.section, r.plot_no
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
    text = str(value if value is not None else "—")
    if not markup:
        text = text.replace("&", "&amp;").replace("<", "&lt;")
    return rl["Paragraph"](text or "—", style)


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
    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    buf = io.BytesIO()
    page = rl["landscape"](rl["A4"])
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title="Pending Dues Report — HBC Sanyard RWA",
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
                val = str(row.get(fid) or "—")
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
            "Service to the Colony · Collective Strength · Cooperation for All — HBC Sanyard RWA",
            ParagraphStyle("foot", parent=meta_style, alignment=rl["TA_CENTER"], fontSize=7.5),
        )
    )

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(12 * mm, 8 * mm, "HBC Sanyard RWA — Pending Dues Report")
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
    generated = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    buf = io.BytesIO()
    page = rl["landscape"](rl["A4"])
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title=f"{title} — HBC Sanyard RWA",
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
                val = str(row.get(fid) or "—")
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
        canvas.drawString(12 * mm, 8 * mm, f"HBC Sanyard RWA — {title}")
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def generate_report_pdf(
    conn,
    *,
    site_root: Path,
    enrich_payment_row,
    payload: dict,
    list_grievances=None,
    directory_fn=None,
) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for builtin / custom / saved template."""
    report_id = str(payload.get("reportId") or payload.get("id") or "pending-dues").strip()
    fields = payload.get("fields") if isinstance(payload.get("fields"), list) else None
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    for key in ("pendingOnly", "section", "search", "houseIds", "status", "category", "officeBearersOnly"):
        if key in payload and key not in filters:
            filters[key] = payload[key]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

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
        if dataset == "dues":
            rows = query_pending_dues_rows(conn, enrich_payment_row, filters=filters)
            pdf = build_tabular_pdf(
                conn,
                site_root=site_root,
                title=str(payload.get("title") or "Custom Dues Report"),
                field_defs=field_defs,
                rows=rows,
                money_fields=MONEY_FIELDS,
                filter_summary="custom · dues",
            )
            return pdf, f"custom-dues-{stamp}.pdf"
        if dataset == "directory":
            if not directory_fn:
                raise ValueError("Directory source unavailable")
            rows = query_directory_rows(directory_fn, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn,
                site_root=site_root,
                title=str(payload.get("title") or "Directory Report"),
                field_defs=field_defs,
                rows=rows,
                filter_summary="custom · directory",
            )
            return pdf, f"custom-directory-{stamp}.pdf"
        if dataset == "concerns":
            if not list_grievances:
                raise ValueError("Concerns source unavailable")
            rows = query_concerns_rows(list_grievances, conn, filters=filters)
            pdf = build_tabular_pdf(
                conn,
                site_root=site_root,
                title=str(payload.get("title") or "Concerns Report"),
                field_defs=field_defs,
                rows=rows,
                filter_summary="custom · concerns",
            )
            return pdf, f"custom-concerns-{stamp}.pdf"
        raise ValueError("Unsupported dataset")

    raise ValueError(f"Unknown report: {report_id}")
