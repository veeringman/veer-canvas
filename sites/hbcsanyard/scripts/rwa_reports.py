"""RWA PDF reports (EC desk). Pending dues first; header with seal + office bearers."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from init_rwa_db import SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID, section_plot_sort_key

IST = ZoneInfo("Asia/Kolkata")
_RL = None  # lazy reportlab bundle

# Registered society + colony branding for all portal PDFs.
ORG_SOCIETY = "Mandi Housing Welfare Society"
ORG_COLONY = "Himuda Housing Colony Sanyard"
ORG_NAME = ORG_COLONY
ORG_NAME_HTML = ORG_COLONY
ORG_NAME_MULTILINE = ORG_COLONY
ORG_SUBTITLE = "Housing Colony Sanyard, Mandi HP 175001"
ORG_REGISTRATION = "Registration No. 467 dated 21/07/2012"
ORG_SLOGAN = "Unity · Harmony · Progress"
ORG_SHORT = ORG_COLONY
ORG_AUTHOR = ORG_SOCIETY
def _logo_candidates_from_manifest() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Prefer compact PDF/web marks — never the full ~1MB official master."""
    fallback_logo = (
        "assets/mhws-logo/mhws-logo-seal-cert.png",
        "assets/mhws-logo/mhws-logo-print.png",
        "assets/mhws-logo/mhws-logo-web-256.png",
        "assets/mhws-logo/mhws-logo-web-512.png",
        "assets/mhws-logo/mhws-logo-pdf.png",
        "assets/hbcs-sanyard-seal-mark.png",
        "assets/hbcs-sanyard-seal-512.png",
    )
    fallback_wm = (
        "assets/mhws-logo/mhws-logo-watermark.png",
    )
    try:
        from logo_registry import load_manifest, role_path

        m = load_manifest()

        def _role(name: str) -> str | None:
            try:
                return role_path(m, name)
            except Exception:
                return None

        # Prefer vivid certificate seal for PDF headers (hard alpha / full contrast).
        logos = tuple(
            p
            for p in (
                _role("sealCert"),
                _role("print"),
                _role("web256"),
                _role("web512"),
                _role("pdf"),
                _role("sealMark"),
                _role("pwa512"),
            )
            if p
        ) or fallback_logo
        wms = tuple(
            p for p in (_role("watermark"),) if p
        ) or fallback_wm
        return logos, wms
    except Exception:
        return fallback_logo, fallback_wm


LOGO_CANDIDATES, WATERMARK_CANDIDATES = _logo_candidates_from_manifest()
_IMAGE_READER_CACHE: dict[str, Any] = {}


def _image_reader(path: Path):
    """Reuse decoded ReportLab ImageReaders across pages / certificates in-process."""
    key = str(path.resolve())
    hit = _IMAGE_READER_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from reportlab.lib.utils import ImageReader
    except Exception:
        return str(path)
    reader = ImageReader(str(path))
    _IMAGE_READER_CACHE[key] = reader
    return reader


def _seal_image_reader(path: Path):
    """Full-contrast header seal for ReportLab (file-backed hard alpha).

    Soft-alpha PNGs embed as washed soft-masks in PDF viewers. Prefer the
    prebuilt sealCert asset; otherwise harden on the fly and cache to disk.
    """
    key = f"seal-file:{path.resolve()}"
    hit = _IMAGE_READER_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from reportlab.lib.utils import ImageReader
        from PIL import Image, ImageEnhance
    except Exception:
        return _image_reader(path)

    try:
        # Already a cert seal — load directly.
        if "seal-cert" in path.name or "seal_cert" in path.name:
            reader = ImageReader(str(path))
            _IMAGE_READER_CACHE[key] = reader
            return reader

        cache_path = path.with_name(f"{path.stem}-pdfhard.png")
        src_mtime = path.stat().st_mtime
        if not cache_path.is_file() or cache_path.stat().st_mtime < src_mtime:
            im = Image.open(path).convert("RGBA")
            rgb = ImageEnhance.Contrast(im.convert("RGB")).enhance(1.28)
            rgb = ImageEnhance.Color(rgb).enhance(1.18)
            alpha = im.split()[3].point(lambda v: 255 if v >= 20 else 0)
            out = Image.merge("RGBA", (*rgb.split(), alpha))
            out.save(cache_path, format="PNG", optimize=True)
        reader = ImageReader(str(cache_path))
        _IMAGE_READER_CACHE[key] = reader
        return reader
    except Exception:
        return _image_reader(path)


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
        from reportlab.lib.pagesizes import A4, A5, A6, landscape
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
        "A5": A5,
        "A6": A6,
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
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 42},
    {"id": "householdCode", "label": "HH code", "default": True, "align": "left", "width": 58},
    {"id": "section", "label": "Sec.", "default": True, "align": "center", "width": 28},
    {"id": "name", "label": "Name", "default": True, "align": "left", "width": 100},
    {"id": "phone", "label": "Phone", "default": False, "align": "left", "width": 68},
    {"id": "previousTotal", "label": "Prev total", "default": True, "align": "right", "width": 54},
    {"id": "previousPending", "label": "Prev pending", "default": False, "align": "right", "width": 54},
    {"id": "currentYearTotal", "label": "Year total", "default": True, "align": "right", "width": 54},
    {"id": "currentYearPending", "label": "Year pending", "default": False, "align": "right", "width": 54},
    {"id": "amountReceived", "label": "Received", "default": True, "align": "right", "width": 54},
    {"id": "totalDue", "label": "Total due", "default": True, "align": "right", "width": 54},
    {"id": "pendingDues", "label": "Pending", "default": True, "align": "right", "width": 54},
    {"id": "remarks", "label": "Remarks", "default": False, "align": "left", "width": 80},
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
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 42},
    {"id": "householdCode", "label": "HH code", "default": True, "align": "left", "width": 58},
    {"id": "section", "label": "Sec.", "default": False, "align": "center", "width": 28},
    {"id": "name", "label": "Name", "default": True, "align": "left", "width": 100},
    {"id": "officialTitle", "label": "Office", "default": True, "align": "left", "width": 80},
    {"id": "phone", "label": "Phone", "default": True, "align": "left", "width": 72},
    {"id": "email", "label": "Email", "default": True, "align": "left", "width": 110},
    {"id": "profession", "label": "Profession", "default": False, "align": "left", "width": 80},
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

PASSES_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 26},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 40},
    {"id": "kindLabel", "label": "Kind", "default": True, "align": "left", "width": 48},
    {"id": "code", "label": "Code", "default": True, "align": "left", "width": 62},
    {"id": "plateDisplay", "label": "Plate", "default": True, "align": "left", "width": 70},
    {"id": "vehicleTypeLabel", "label": "Vehicle", "default": True, "align": "left", "width": 48},
    {"id": "visitorName", "label": "Name", "default": True, "align": "left", "width": 80},
    {"id": "statusLabel", "label": "Status", "default": True, "align": "left", "width": 70},
    {"id": "issuedAtLabel", "label": "Issued", "default": True, "align": "left", "width": 70},
    {"id": "expiresAtLabel", "label": "Expires", "default": True, "align": "left", "width": 70},
    {"id": "memberName", "label": "Requested by", "default": False, "align": "left", "width": 80},
    {"id": "colour", "label": "Colour", "default": False, "align": "left", "width": 45},
    {"id": "adhocCategoryLabel", "label": "Ad-hoc type", "default": False, "align": "left", "width": 55},
]

TENANTS_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 28},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 42},
    {"id": "name", "label": "Tenant", "default": True, "align": "left", "width": 100},
    {"id": "phone", "label": "Phone", "default": True, "align": "left", "width": 72},
    {"id": "email", "label": "Email", "default": True, "align": "left", "width": 110},
    {"id": "status", "label": "Status", "default": True, "align": "center", "width": 50},
    {"id": "occupancyStart", "label": "From", "default": True, "align": "left", "width": 55},
    {"id": "occupancyEnd", "label": "Until", "default": True, "align": "left", "width": 55},
    {"id": "note", "label": "Note", "default": False, "align": "left", "width": 90},
    {"id": "createdByName", "label": "Added by", "default": False, "align": "left", "width": 70},
]

VEHICLES_FIELDS: list[dict[str, Any]] = [
    {"id": "sno", "label": "S.No.", "default": True, "align": "center", "width": 26},
    {"id": "plotNo", "label": "Plot", "default": True, "align": "left", "width": 40},
    {"id": "kindLabel", "label": "Kind", "default": True, "align": "left", "width": 48},
    {"id": "plateDisplay", "label": "Plate", "default": True, "align": "left", "width": 75},
    {"id": "vehicleTypeLabel", "label": "Type", "default": True, "align": "left", "width": 48},
    {"id": "colour", "label": "Colour", "default": True, "align": "left", "width": 45},
    {"id": "visitorName", "label": "Holder", "default": True, "align": "left", "width": 90},
    {"id": "statusLabel", "label": "Status", "default": True, "align": "left", "width": 70},
    {"id": "code", "label": "Pass code", "default": True, "align": "left", "width": 62},
    {"id": "issuedAtLabel", "label": "Issued", "default": False, "align": "left", "width": 70},
    {"id": "expiresAtLabel", "label": "Expires", "default": True, "align": "left", "width": 70},
    {"id": "memberName", "label": "Owner contact", "default": False, "align": "left", "width": 80},
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
    "passes": {
        "id": "passes",
        "title": "Passes",
        "description": "Member, visitor, tenant, household staff, and ad-hoc gate passes",
        "fields": PASSES_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": [], "kind": "all"},
        "filterUi": {"section": False, "search": True, "plots": True, "passStatus": True, "passKind": True},
    },
    "tenants": {
        "id": "tenants",
        "title": "Tenants",
        "description": "Household occupancy records (tenants)",
        "fields": TENANTS_FIELDS,
        "defaultFilters": {"status": "active", "search": "", "houseIds": []},
        "filterUi": {"section": False, "search": True, "plots": True, "tenantStatus": True},
    },
    "vehicles": {
        "id": "vehicles",
        "title": "Vehicles",
        "description": "Registered member and tenant vehicles (excludes visitors / on-foot)",
        "fields": VEHICLES_FIELDS,
        "defaultFilters": {"status": "all", "search": "", "houseIds": []},
        "filterUi": {"section": False, "search": True, "plots": True, "passStatus": True},
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
    """Office bearers for PDF/HTML letterhead — seat-holder name/phone from charter DB."""
    try:
        from rwa_entitlements import list_office_and_ec

        people = list_office_and_ec(conn)
    except Exception:
        people = []
    members = [
        {
            "houseId": p.get("houseId"),
            "name": (p.get("name") or p.get("houseId") or "").strip(),
            "officialTitle": (p.get("officialTitle") or "").strip(),
            "phone": (p.get("phone") or "").strip(),
        }
        for p in people
        if (p.get("officialTitle") or "").strip()
        or p.get("isOfficeBearer")
        or p.get("isEcAdmin")
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

    try:
        import rwa_household as _hh

        _hh.ensure_household_codes(conn)
    except Exception:
        _hh = None

    rows = conn.execute(
        """
        SELECT pr.*, r.name, r.section, r.plot_no, r.phone, r.household_code,
               r.status AS resident_status
        FROM payment_rows pr
        JOIN residents r ON r.house_id = pr.house_id
        WHERE pr.ledger_id = (
          SELECT id FROM payment_ledgers ORDER BY as_of DESC, id DESC LIMIT 1
        )
          AND r.house_id != ?
          AND r.house_id != ?
          AND r.status = 'active'
        """,
        (SUPERADMIN_HOUSE_ID, ADHOC_GATE_HOUSE_ID),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        owner_name = r["name"] or r["house_id"]
        phone = r["phone"] or ""
        if _hh is not None:
            try:
                owner = _hh.primary_member(conn, r["house_id"])
                if owner:
                    owner_name = (owner.get("name") or owner_name).strip() or owner_name
                    phone = (owner.get("phone") or phone or "").strip()
            except Exception:
                pass
        item = {
            **enrich_payment_row(r),
            "plotNo": r["plot_no"] or r["house_id"],
            "section": r["section"] or "",
            "name": owner_name,
            "phone": phone,
            "householdCode": (r["household_code"] or "").strip(),
            "houseId": r["house_id"],
        }
        hid = str(item["houseId"] or "").upper()
        if house_ids and hid not in house_ids and str(item["plotNo"] or "").upper() not in house_ids:
            continue
        if section and section.lower() not in {"all", ""}:
            if str(item["section"] or "").upper() != section.upper():
                continue
        if search:
            blob = (
                f"{item['plotNo']} {item['name']} {item['houseId']} "
                f"{item.get('phone') or ''} {item.get('householdCode') or ''}"
            ).lower()
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
    """Prefer official society logo; fall back to legacy HBC seals if missing."""
    for name in LOGO_CANDIDATES:
        path = site_root / name
        if path.is_file():
            return path
    return None


def _watermark_path(site_root: Path) -> Path | None:
    """Prefer pre-faded watermark asset for reportlab letterhead pages."""
    for name in WATERMARK_CANDIDATES:
        path = site_root / name
        if path.is_file():
            return path
    return _seal_path(site_root)


def _org_title_default(*, html: bool = False) -> str:
    return ORG_NAME_HTML if html else ORG_NAME_MULTILINE


def _org_subtitle_default() -> str:
    return ORG_SUBTITLE


# Colours matching documents/mhws-letterhead-pad.html / cash-receipt booklet.
BRAND_NAVY = "#0b2a56"
BRAND_NAVY_2 = "#143a6e"
BRAND_GREEN = "#1a6b3a"
BRAND_GOLD = "#c9a227"
BRAND_INK = "#12233f"
BRAND_MUTED = "#5a6a80"
ORG_EMAIL = "housingcolonysanyard@gmail.com"
ORG_WEB = "housingcolonysanyard.in"
ORG_PHONE_DESK = ""  # society desk line (optional)

# Letterhead pad officer order (matches Templates folder pad).
_LETTERHEAD_ROLE_ORDER = (
    "president",
    "general secretary",
    "vice president",
    "vice-president",
    "treasurer",
)

def _fmt_phone_display(phone: str | None) -> str:
    """Display phones as 5+5 groups for India mobiles; blank → empty string."""
    raw = str(phone or "").strip()
    if not raw:
        return ""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:5]} {digits[5:]}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"{digits[2:7]} {digits[7:]}"
    return raw


def _letterhead_officers(conn) -> list[dict]:
    """Four office-bearer slots for letterhead chrome — always from charter DB."""
    bearers = office_bearers_for_header(conn) if conn is not None else []
    by_key: dict[str, dict] = {}
    for b in bearers:
        title = (b.get("officialTitle") or "").strip().lower()
        for key in _LETTERHEAD_ROLE_ORDER:
            if key in title and key not in by_key:
                by_key[key] = b
                break
    slots = [
        ("President", "president"),
        ("General Secretary", "general secretary"),
        ("Vice President", "vice president"),
        ("Treasurer", "treasurer"),
    ]
    out: list[dict] = []
    for label, key in slots:
        hit = by_key.get(key)
        if not hit and key == "vice president":
            hit = by_key.get("vice-president")
        name = ((hit or {}).get("name") or "").strip()
        phone = ((hit or {}).get("phone") or "").strip()
        out.append({
            "title": label,
            "name": name,
            "phone": _fmt_phone_display(phone),
        })
    return out


def charter_roster(conn) -> dict[str, list[dict]]:
    """Office-bearer slots + other EC members for charter pads (DB seat holders)."""
    officers = _letterhead_officers(conn)
    officer_names = {((o.get("name") or "").strip().lower()) for o in officers if (o.get("name") or "").strip()}
    members: list[dict] = []
    try:
        from rwa_entitlements import list_office_and_ec

        for p in list_office_and_ec(conn):
            if not (p.get("isEcMember") or p.get("isEcAdmin") or p.get("isOfficeBearer")):
                continue
            name = (p.get("name") or "").strip()
            if not name:
                continue
            title = (p.get("officialTitle") or "").strip()
            # Keep titled primary seats in the office-bearers table only.
            title_l = title.lower()
            is_primary = any(k in title_l for k in _LETTERHEAD_ROLE_ORDER)
            if is_primary:
                continue
            if name.lower() in officer_names:
                continue
            members.append({
                "name": name,
                "phone": _fmt_phone_display(p.get("phone") or ""),
                "officialTitle": title,
                "houseId": p.get("houseId"),
            })
    except Exception:
        members = []
    members.sort(key=lambda m: m["name"].lower())
    return {"officers": officers, "members": members}



def _amount_in_words_inr(amount: int) -> str:
    """Simple Indian-English amount-in-words for cash receipts."""
    n = int(amount or 0)
    if n < 0:
        n = abs(n)
    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen",
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def under_thousand(x: int) -> str:
        if x == 0:
            return ""
        if x < 20:
            return ones[x]
        if x < 100:
            return (tens[x // 10] + (" " + ones[x % 10] if x % 10 else "")).strip()
        return (ones[x // 100] + " Hundred" + ((" " + under_thousand(x % 100)) if x % 100 else "")).strip()

    if n == 0:
        return "Zero Rupees Only"
    crore = n // 10000000
    n %= 10000000
    lakh = n // 100000
    n %= 100000
    thousand = n // 1000
    rem = n % 1000
    parts: list[str] = []
    if crore:
        parts.append(f"{under_thousand(crore)} Crore")
    if lakh:
        parts.append(f"{under_thousand(lakh)} Lakh")
    if thousand:
        parts.append(f"{under_thousand(thousand)} Thousand")
    if rem:
        parts.append(under_thousand(rem))
    return (" ".join(parts) + " Rupees Only").strip()


def _draw_mhws_watermark(
    canvas,
    site_root: Path,
    *,
    page_w: float,
    page_h: float,
    size_mm: float = 112,
    cy_frac: float = 0.45,
    alpha: float = 0.065,
) -> None:
    seal = _watermark_path(site_root)
    if not seal:
        return
    rl = _reportlab()
    mm = rl["mm"]
    # Pre-faded watermark PNG already carries opacity; avoid double-fading.
    use_alpha = 1.0 if "watermark" in seal.name else alpha
    try:
        canvas.saveState()
        if hasattr(canvas, "setFillAlpha") and use_alpha < 1.0:
            canvas.setFillAlpha(use_alpha)
        w = size_mm * mm
        h = size_mm * mm
        x = (page_w - w) / 2
        y = page_h * cy_frac - h / 2
        canvas.drawImage(
            _image_reader(seal),
            x,
            y,
            width=w,
            height=h,
            preserveAspectRatio=True,
            mask="auto",
        )
        canvas.restoreState()
    except Exception:
        try:
            canvas.restoreState()
        except Exception:
            pass


def _draw_report_page_chrome(
    canvas,
    site_root: Path,
    *,
    page_w: float,
    page_h: float,
    mm,
    footer_left: str,
    page_num: int,
) -> None:
    """Standard letterhead watermark + report footer on every page."""
    from reportlab.lib import colors

    seal_mm = min(90.0, (page_h / mm) * 0.55)
    _draw_mhws_watermark(
        canvas,
        site_root,
        page_w=page_w,
        page_h=page_h,
        size_mm=seal_mm,
        cy_frac=0.5,
        alpha=0.04,
    )
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(12 * mm, 8 * mm, footer_left)
    canvas.drawRightString(page_w - 12 * mm, 8 * mm, f"Page {page_num}")
    canvas.restoreState()


def _draw_accent_edge(canvas, page_w: float, *, y_top: float, mm) -> float:
    """Draw navy/gold/green triad at top; return y below the thin rule."""
    from reportlab.lib import colors

    bar_h = 2.6 * mm
    gold_w = 7 * mm
    side = (page_w - gold_w) / 2
    y = y_top - bar_h
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.rect(0, y, side, bar_h, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(BRAND_GOLD))
    canvas.rect(side, y, gold_w, bar_h, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.rect(side + gold_w, y, side, bar_h, fill=1, stroke=0)
    thin = 0.4 * mm
    y2 = y - thin
    canvas.setFillColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.12))
    canvas.rect(0, y2, page_w, thin, fill=1, stroke=0)
    return y2


def _draw_mhws_letterhead_chrome(
    canvas,
    site_root: Path,
    officers: list[dict],
    *,
    page_w: float,
    page_h: float,
    mm,
    doc_label: str = "",
) -> None:
    """Paint the official letterhead pad frame (matches Templates folder HTML)."""
    from reportlab.lib import colors

    # Outer border
    canvas.setStrokeColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.55))
    canvas.setLineWidth(0.8)
    canvas.rect(3 * mm, 3 * mm, page_w - 6 * mm, page_h - 6 * mm, fill=0, stroke=1)

    y = _draw_accent_edge(canvas, page_w, y_top=page_h - 3 * mm, mm=mm)
    _draw_mhws_watermark(
        canvas, site_root, page_w=page_w, page_h=page_h, size_mm=96, cy_frac=0.48, alpha=0.04
    )

    pad_x = 12 * mm
    # Brand row — full-opacity header seal (never inherit watermark fill alpha).
    seal = _seal_path(site_root)
    brand_top = y - 5 * mm
    logo_w = 24 * mm
    if seal:
        try:
            if hasattr(canvas, "setFillAlpha"):
                canvas.setFillAlpha(1.0)
            if hasattr(canvas, "setStrokeAlpha"):
                canvas.setStrokeAlpha(1.0)
            canvas.drawImage(
                _seal_image_reader(seal),
                pad_x,
                brand_top - logo_w,
                width=logo_w,
                height=logo_w,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    text_x = pad_x + logo_w + 5 * mm
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.setFont("Times-Bold", 13)
    canvas.drawString(text_x, brand_top - 7 * mm, ORG_SOCIETY.upper())
    canvas.setFont("Times-Bold", 11)
    canvas.drawString(text_x, brand_top - 11.5 * mm, ORG_COLONY.upper())
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(text_x, brand_top - 15.5 * mm, ORG_SUBTITLE)
    canvas.setFillColor(colors.HexColor(BRAND_MUTED))
    canvas.setFont("Helvetica-Bold", 7.2)
    canvas.drawString(text_x, brand_top - 19.2 * mm, ORG_REGISTRATION)

    # Gold pip rule
    rule_y = brand_top - logo_w - 3 * mm
    canvas.setStrokeColor(colors.HexColor(BRAND_NAVY))
    canvas.setLineWidth(0.9)
    mid = page_w / 2
    canvas.line(pad_x, rule_y, mid - 4 * mm, rule_y)
    canvas.line(mid + 4 * mm, rule_y, page_w - pad_x, rule_y)
    canvas.saveState()
    canvas.translate(mid, rule_y)
    canvas.rotate(45)
    canvas.setFillColor(colors.HexColor(BRAND_GOLD))
    canvas.rect(-1.1 * mm, -1.1 * mm, 2.2 * mm, 2.2 * mm, fill=1, stroke=0)
    canvas.restoreState()

    # Officers: one centered top row (4 across), top-aligned columns
    slots = officers[:4] if officers else _letterhead_officers(None)
    while len(slots) < 4:
        slots.append({"title": "", "name": "", "phone": ""})
    grid_top = rule_y - 4.5 * mm
    col_w = (page_w - 2 * pad_x) / 4
    for i, slot in enumerate(slots):
        cx = pad_x + col_w * i + col_w / 2
        cy = grid_top
        canvas.setFillColor(colors.HexColor(BRAND_GREEN))
        canvas.setFont("Helvetica-Bold", 5.6)
        title = (slot.get("title") or "").upper()
        canvas.drawCentredString(cx, cy, title)
        canvas.setFillColor(colors.HexColor(BRAND_NAVY))
        canvas.setFont("Helvetica-Bold", 7.2)
        name = (slot.get("name") or "-").upper()
        # Keep long names on one visual line (slightly smaller if needed).
        if len(name) > 18:
            canvas.setFont("Helvetica-Bold", 6.2)
        canvas.drawCentredString(cx, cy - 3.2 * mm, _pdf_safe(name))
        phone = (slot.get("phone") or "").strip()
        canvas.setFillColor(colors.HexColor(BRAND_MUTED))
        canvas.setFont("Helvetica", 6.2)
        ph = f"Ph {phone}" if phone else "Ph -"
        canvas.drawCentredString(cx, cy - 5.6 * mm, _pdf_safe(ph))
        if i < 3:
            canvas.setStrokeColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.14))
            canvas.setLineWidth(0.55)
            xdiv = pad_x + col_w * (i + 1)
            canvas.line(xdiv, cy - 6.0 * mm, xdiv, cy + 1 * mm)

    # Officers foot gold rule
    foot_rule_y = grid_top - 9.5 * mm
    canvas.setStrokeColor(colors.Color(201 / 255, 162 / 255, 39 / 255, alpha=0.55))
    canvas.setLineWidth(0.7)
    canvas.line(mid - 18 * mm, foot_rule_y, mid + 18 * mm, foot_rule_y)

    if doc_label:
        canvas.setFillColor(colors.HexColor(BRAND_MUTED))
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(page_w - pad_x, foot_rule_y + 2 * mm, doc_label)

    # Footer contacts + slogan bar
    slogan_h = 8 * mm
    slogan_y = 3 * mm
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.rect(3 * mm, slogan_y, page_w - 6 * mm, slogan_h, fill=1, stroke=0)
    # soft gradient mimic: right greenish strip
    canvas.setFillColor(colors.HexColor("#124a38"))
    canvas.rect(page_w * 0.62, slogan_y, page_w * 0.38 - 3 * mm, slogan_h, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#f7f3ea"))
    canvas.setFont("Helvetica-Bold", 8)
    slogan = "UNITY   ·   HARMONY   ·   PROGRESS"
    canvas.drawCentredString(page_w / 2, slogan_y + 2.8 * mm, slogan)

    contact_y = slogan_y + slogan_h + 3 * mm
    canvas.setStrokeColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.45))
    canvas.setLineWidth(0.9)
    canvas.line(pad_x, contact_y + 8 * mm, page_w - pad_x, contact_y + 8 * mm)

    contacts = [
        (k, v)
        for k, v in (
            ("Address", ORG_SUBTITLE),
            ("Email", ORG_EMAIL),
            ("Website", ORG_WEB),
        )
        if str(v or "").strip()
    ]
    col_gap = (page_w - 2 * pad_x) / max(1, len(contacts))
    for i, (k, v) in enumerate(contacts):
        x = pad_x + i * col_gap
        canvas.setFillColor(colors.HexColor(BRAND_GREEN))
        canvas.setFont("Helvetica-Bold", 6)
        canvas.drawString(x, contact_y + 5 * mm, k.upper())
        canvas.setFillColor(colors.HexColor(BRAND_NAVY))
        canvas.setFont("Helvetica-Bold", 7)
        # wrap long address
        if len(v) > 36:
            canvas.drawString(x, contact_y + 2.2 * mm, v[:36])
            canvas.drawString(x, contact_y - 0.5 * mm, v[36:])
        else:
            canvas.drawString(x, contact_y + 2.2 * mm, v)


CASH_RECEIPT_SERIAL_MAX = 9_999_999


def _format_cash_receipt_no(receipt_no: str | None, *, fallback: str = "0000001") -> str:
    """Prefer 7-digit red-book style serials (0000123); keep longer alphanumeric IDs as-is."""
    raw = str(receipt_no or "").strip()
    if not raw:
        return fallback
    digits = "".join(c for c in raw if c.isdigit())
    if digits.isdigit() and len(digits) <= 7 and (raw == digits or raw.upper().startswith("NO")):
        try:
            return f"{int(digits):07d}"
        except ValueError:
            pass
    return raw


def _draw_cash_receipt_leaf_chrome(
    canvas,
    site_root: Path,
    *,
    page_w: float,
    page_h: float,
    mm,
    receipt_no: str,
    paid_fmt: str,
    copy_tag: str = "Original",
    paper_tint: str = "cream",
    paper_pattern: str = "lines",
) -> tuple[float, float, float, float]:
    """Draw one cash-receipt leaf frame; return content box (x, y, w, h)."""
    from reportlab.lib import colors
    from reportlab.lib.colors import Color

    margin = 10 * mm
    box_x = margin
    box_y = margin
    box_w = page_w - 2 * margin
    box_h = page_h - 2 * margin

    tint_map = {
        "white": colors.white,
        "cream": colors.HexColor("#fbf6ea"),
        "ivory": colors.HexColor("#f7f3e8"),
        "mint": colors.HexColor("#eef8f1"),
        "sky": colors.HexColor("#eef4fb"),
        "rose": colors.HexColor("#fbf0f2"),
    }
    canvas.setFillColor(tint_map.get(paper_tint, tint_map["cream"]))
    canvas.rect(box_x, box_y, box_w, box_h, fill=1, stroke=0)

    # Optional background pattern
    canvas.saveState()
    canvas.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.06))
    canvas.setLineWidth(0.4)
    if paper_pattern == "lines":
        y = box_y + 4 * mm
        while y < box_y + box_h - 2 * mm:
            canvas.line(box_x + 2 * mm, y, box_x + box_w - 2 * mm, y)
            y += 3.4 * mm
    elif paper_pattern == "diagonal":
        step = 5 * mm
        x0 = box_x - box_h
        while x0 < box_x + box_w + box_h:
            canvas.line(x0, box_y, x0 + box_h, box_y + box_h)
            x0 += step
    elif paper_pattern == "dots":
        canvas.setFillColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.08))
        step = 3.4 * mm
        y = box_y + 3 * mm
        while y < box_y + box_h - 2 * mm:
            x = box_x + 3 * mm
            while x < box_x + box_w - 2 * mm:
                canvas.circle(x, y, 0.35 * mm, fill=1, stroke=0)
                x += step
            y += step
    elif paper_pattern == "guilloche":
        canvas.setStrokeColor(Color(26 / 255, 107 / 255, 58 / 255, alpha=0.05))
        cx, cy = box_x + box_w / 2, box_y + box_h / 2
        for r in range(8, int(max(box_w, box_h) / mm), 8):
            canvas.circle(cx, cy, r * mm, fill=0, stroke=1)
    canvas.restoreState()

    canvas.setStrokeColor(colors.HexColor(BRAND_NAVY))
    canvas.setLineWidth(1.25)
    canvas.rect(box_x, box_y, box_w, box_h, fill=0, stroke=1)

    # Watermark ~70% of receipt height
    wm_size_mm = (box_h / mm) * 0.70
    _draw_mhws_watermark(
        canvas,
        site_root,
        page_w=page_w,
        page_h=page_h,
        size_mm=wm_size_mm,
        cy_frac=0.48,
        alpha=0.08,
    )

    pad = 5 * mm
    inner_x = box_x + pad
    top = box_y + box_h - pad

    # Copy tag
    canvas.setFillColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.35))
    canvas.setFont("Helvetica", 6)
    canvas.drawRightString(box_x + box_w - pad, top - 2 * mm, copy_tag.upper())

    # Header: full-contrast logo + org + meta
    seal = _seal_path(site_root)
    logo_w = 18 * mm
    if seal:
        try:
            if hasattr(canvas, "setFillAlpha"):
                canvas.setFillAlpha(1.0)
            if hasattr(canvas, "setStrokeAlpha"):
                canvas.setStrokeAlpha(1.0)
            canvas.drawImage(
                _seal_image_reader(seal),
                inner_x,
                top - logo_w - 1 * mm,
                width=logo_w,
                height=logo_w,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    tx = inner_x + logo_w + 3 * mm
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.setFont("Times-Bold", 10)
    canvas.drawString(tx, top - 5 * mm, ORG_SOCIETY.upper())
    canvas.setFont("Times-Bold", 8.5)
    canvas.drawString(tx, top - 8.8 * mm, ORG_COLONY.upper())
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(tx, top - 12 * mm, ORG_SUBTITLE)
    canvas.setFillColor(colors.HexColor(BRAND_MUTED))
    canvas.setFont("Helvetica-Bold", 6.2)
    canvas.drawString(tx, top - 15 * mm, ORG_REGISTRATION)

    meta_x = box_x + box_w - pad
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(meta_x, top - 5 * mm, "CASH RECEIPT")
    # Red physical-book style serial
    display_no = _format_cash_receipt_no(receipt_no)
    canvas.setFillColor(colors.HexColor("#c62828"))
    canvas.setFont("Courier-Bold", 14)
    canvas.drawRightString(meta_x, top - 11 * mm, display_no)
    canvas.setFillColor(colors.HexColor(BRAND_MUTED))
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(meta_x, top - 14.5 * mm, f"Date {paid_fmt}")

    # Header rule
    rule_y = top - logo_w - 3 * mm
    canvas.setStrokeColor(colors.HexColor(BRAND_NAVY))
    canvas.setLineWidth(1)
    canvas.line(inner_x, rule_y, box_x + box_w - pad, rule_y)

    # Banner
    ban_h = 7 * mm
    ban_y = rule_y - ban_h - 2 * mm
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.rect(inner_x, ban_y, box_w - 2 * pad, ban_h, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#f7f3ea"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawCentredString(
        page_w / 2,
        ban_y + 2.2 * mm,
        "RECEIVED WITH THANKS   ·   UNITY · HARMONY · PROGRESS",
    )

    # Footer contacts inside the leaf (email + website).
    foot_y = box_y + 6 * mm
    canvas.setStrokeColor(colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.28))
    canvas.setLineWidth(0.6)
    canvas.line(inner_x, foot_y + 8 * mm, box_x + box_w - pad, foot_y + 8 * mm)
    canvas.setFillColor(colors.HexColor(BRAND_GREEN))
    canvas.setFont("Helvetica-Bold", 5.8)
    canvas.drawString(inner_x, foot_y + 4.8 * mm, "EMAIL")
    canvas.drawString(inner_x + 62 * mm, foot_y + 4.8 * mm, "WEBSITE")
    canvas.setFillColor(colors.HexColor(BRAND_NAVY))
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(inner_x, foot_y + 1.8 * mm, ORG_EMAIL)
    canvas.drawString(inner_x + 62 * mm, foot_y + 1.8 * mm, ORG_WEB)
    canvas.setFillColor(colors.HexColor(BRAND_MUTED))
    canvas.setFont("Helvetica", 6)
    canvas.drawRightString(box_x + box_w - pad, foot_y + 1.8 * mm, ORG_SUBTITLE)

    content_top = ban_y - 4 * mm
    content_bottom = box_y + 18 * mm
    return inner_x, content_bottom, box_w - 2 * pad, content_top - content_bottom


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


def _cash_receipt_layout(layout: str | None) -> tuple[str, dict[str, Any]]:
    """Page grid for blank cash-receipt booklets.

    Shared slip width = 210 mm (A4 portrait width / A5 landscape width).
    - a5-2: A5 landscape, 1×2 stacked
    - a4-3 / a4-4: A4 portrait, 1×3 or 1×4 stacked
    """
    layouts: dict[str, dict[str, Any]] = {
        "a4-3": {
            "page": "A4",
            "page_orient": "portrait",
            "cols": 1,
            "rows": 3,
            "slips": 3,
        },
        "a5-2": {
            "page": "A5",
            "page_orient": "landscape",
            "cols": 1,
            "rows": 2,
            "slips": 2,
        },
        "a4-4": {
            "page": "A4",
            "page_orient": "portrait",
            "cols": 1,
            "rows": 4,
            "slips": 4,
        },
    }
    key = (layout or "a4-3").strip().lower()
    if key not in layouts:
        key = "a4-3"
    return key, layouts[key]


def _cash_receipt_page_grid(
    layout_key: str,
    layout_spec: dict[str, Any],
    orientation: str | None,
    rl: dict[str, Any],
) -> tuple[float, float, int, int, int, str]:
    """Resolve page size: A5 landscape for 1×2; A4 portrait for 1×3 / 1×4."""
    page_sizes = {"A4": rl["A4"], "A5": rl["A5"]}
    base = page_sizes[layout_spec["page"]]
    page_orient = str(layout_spec.get("page_orient") or "portrait")
    if page_orient == "landscape":
        page_w, page_h = rl["landscape"](base)
    else:
        page_w, page_h = base
    cols = int(layout_spec["cols"])
    rows = int(layout_spec["rows"])
    return page_w, page_h, cols, rows, int(layout_spec["slips"]), page_orient


def build_cash_receipt_booklet_pdf(
    *,
    site_root: Path,
    start_no: int = 1,
    page_count: int = 1,
    paper_tint: str = "cream",
    paper_pattern: str = "lines",
    layout: str = "a4-3",
    orientation: str = "portrait",
    signatories: int = 1,
) -> tuple[bytes, str]:
    """Blank cash-receipt booklet — slip width always 210 mm (A4 / A5-landscape)."""
    from reportlab.lib import colors
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas as pdfcanvas

    rl = _reportlab()
    mm = rl["mm"]
    layout_key, layout_spec = _cash_receipt_layout(layout)
    page_w, page_h, cols, rows, slips_per_page, orient_key = _cash_receipt_page_grid(
        layout_key, layout_spec, orientation, rl
    )

    start_no = max(1, min(CASH_RECEIPT_SERIAL_MAX, int(start_no or 1)))
    page_count = max(1, min(100, int(page_count or 1)))
    tint = (paper_tint or "cream").strip().lower()
    pattern = (paper_pattern or "lines").strip().lower()
    if tint not in {"white", "cream", "ivory", "mint", "sky", "rose"}:
        tint = "cream"
    if pattern not in {"none", "lines", "diagonal", "dots", "guilloche"}:
        pattern = "lines"
    try:
        signatory_count = int(signatories or 1)
    except (TypeError, ValueError):
        signatory_count = 1
    signatory_count = 2 if signatory_count >= 2 else 1

    tint_map = {
        "white": colors.white,
        "cream": colors.HexColor("#fbf6ea"),
        "ivory": colors.HexColor("#f7f3e8"),
        "mint": colors.HexColor("#eef8f1"),
        "sky": colors.HexColor("#eef4fb"),
        "rose": colors.HexColor("#fbf0f2"),
    }

    # Full page width (210 mm) minus small margins — same on A4 portrait & A5 landscape.
    margin_x = 3.5 * mm
    margin_y = 3.0 * mm
    gap_y = 1.5 * mm if rows > 1 else 0
    slip_w = page_w - 2 * margin_x
    usable_h = page_h - 2 * margin_y - (rows - 1) * gap_y
    slip_h = usable_h / rows
    # Content scale relative to a comfortable ~90 mm tall slip (A4 1×3).
    scale = max(0.78, min(1.08, slip_h / (90 * mm)))

    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(page_w, page_h))
    seal = _seal_path(site_root)

    def _draw_pattern(box_x: float, box_y: float, box_w: float, box_h: float) -> None:
        c.saveState()
        c.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.07))
        c.setLineWidth(0.35)
        step_y = 3.5 * mm
        if pattern == "lines":
            y = box_y + 3 * mm
            while y < box_y + box_h - 2 * mm:
                c.line(box_x + 1.5 * mm, y, box_x + box_w - 1.5 * mm, y)
                y += step_y
        elif pattern == "diagonal":
            step = 5 * mm
            x0 = box_x - box_h
            while x0 < box_x + box_w + box_h:
                c.line(x0, box_y, x0 + box_h, box_y + box_h)
                x0 += step
        elif pattern == "dots":
            c.setFillColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.09))
            step = 3.5 * mm
            y = box_y + 2.5 * mm
            while y < box_y + box_h - 2 * mm:
                x = box_x + 2.5 * mm
                while x < box_x + box_w - 2 * mm:
                    c.circle(x, y, 0.32 * mm, fill=1, stroke=0)
                    x += step
                y += step
        elif pattern == "guilloche":
            c.setStrokeColor(Color(26 / 255, 107 / 255, 58 / 255, alpha=0.06))
            cx, cy = box_x + box_w / 2, box_y + box_h / 2
            for r in range(6, int(max(box_w, box_h) / mm), 7):
                c.circle(cx, cy, r * mm, fill=0, stroke=1)
        c.restoreState()

    def _draw_slip(box_x: float, box_y: float, box_w: float, box_h: float, serial: int) -> None:
        """Draw one full-width receipt; ruled rows spread across the face."""
        c.setFillColor(tint_map.get(tint, tint_map["cream"]))
        c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=0)
        _draw_pattern(box_x, box_y, box_w, box_h)

        c.saveState()
        p = c.beginPath()
        p.rect(box_x, box_y, box_w, box_h)
        c.clipPath(p, stroke=0)
        _draw_mhws_watermark(
            c,
            site_root,
            page_w=page_w,
            page_h=page_h,
            size_mm=(min(box_w, box_h) / mm) * 0.78,
            cy_frac=(box_y + box_h / 2) / page_h,
            alpha=0.08,
        )
        c.restoreState()

        pad = 3.0 * mm
        inner_x = box_x + pad
        top = box_y + box_h - pad
        right = box_x + box_w - pad

        # --- Header (fixed) ---
        logo_w = 12 * mm * min(1.0, scale)
        if seal:
            try:
                if hasattr(c, "setFillAlpha"):
                    c.setFillAlpha(1.0)
                c.drawImage(
                    _seal_image_reader(seal),
                    inner_x,
                    top - logo_w,
                    width=logo_w,
                    height=logo_w,
                    preserveAspectRatio=True,
                    mask="auto",
                )
            except Exception:
                pass
        tx = inner_x + logo_w + 2.5 * mm
        c.setFillColor(colors.HexColor(BRAND_NAVY))
        c.setFont("Times-Bold", max(8, 10 * scale))
        c.drawString(tx, top - 3.6 * mm * scale, ORG_SOCIETY.upper())
        c.setFont("Times-Bold", max(7, 8.2 * scale))
        c.drawString(tx, top - 7.0 * mm * scale, ORG_COLONY.upper())
        c.setFillColor(colors.HexColor(BRAND_GREEN))
        c.setFont("Helvetica-Bold", max(5.8, 6.6 * scale))
        c.drawString(tx, top - 9.8 * mm * scale, ORG_SUBTITLE)
        c.setFillColor(colors.HexColor(BRAND_MUTED))
        c.setFont("Helvetica-Bold", max(5.4, 6.0 * scale))
        c.drawString(tx, top - 12.4 * mm * scale, ORG_REGISTRATION)

        c.setFillColor(colors.HexColor(BRAND_NAVY))
        c.setFont("Helvetica-Bold", max(7.5, 9 * scale))
        c.drawRightString(right, top - 3.5 * mm * scale, "CASH RECEIPT")
        c.setFillColor(colors.HexColor("#c62828"))
        c.setFont("Courier-Bold", max(11, 13 * scale))
        c.drawRightString(right, top - 9.0 * mm * scale, f"{serial:07d}")
        c.setFillColor(colors.HexColor(BRAND_MUTED))
        c.setFont("Helvetica", max(6, 7 * scale))
        c.drawRightString(right, top - 12.2 * mm * scale, "Date _______________")

        rule_y = top - logo_w - 2.2 * mm
        c.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.35))
        c.setLineWidth(0.75)
        c.line(inner_x, rule_y, right, rule_y)

        ban_h = 5.2 * mm * min(1.0, scale + 0.05)
        ban_y = rule_y - ban_h - 1.4 * mm
        c.setFillColor(colors.HexColor(BRAND_NAVY))
        c.rect(inner_x, ban_y, right - inner_x, ban_h, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#f7f3ea"))
        c.setFont("Helvetica-Bold", max(6, 7.2 * scale))
        c.drawCentredString(
            (inner_x + right) / 2,
            ban_y + 1.6 * mm,
            "RECEIVED WITH THANKS   ·   UNITY · HARMONY · PROGRESS",
        )

        # --- Signature zone reserved at bottom; fields spread in between ---
        sig_zone = max(16 * mm, min(24 * mm, box_h * 0.28))
        fields_top = ban_y - 3.5 * mm
        fields_bottom = box_y + sig_zone
        fields = [
            "Received from",
            "Plot / House",
            "Amount (₹)",
            "In words",
            "Towards",
            "Period / note",
        ]
        n_fields = len(fields)
        span = max(fields_top - fields_bottom, n_fields * 4.5 * mm)
        line_h = span / n_fields
        label_w = 28 * mm
        font_sz = max(6.2, min(8.0, 6.5 + (line_h / mm - 5) * 0.35))

        y = fields_top - line_h * 0.35
        for label in fields:
            c.setFont("Helvetica-Bold", font_sz)
            c.setFillColor(colors.HexColor(BRAND_GREEN))
            c.drawString(inner_x, y, label.upper())
            c.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.42))
            c.setLineWidth(0.6)
            c.line(inner_x + label_w, y - 0.5 * mm, right, y - 0.5 * mm)
            if label.startswith("Towards"):
                c.setFillColor(colors.HexColor(BRAND_INK))
                c.setFont("Helvetica", max(5.5, font_sz - 0.6))
                c.drawString(
                    inner_x + label_w + 1.2 * mm,
                    y + 1.0 * mm,
                    "[ ] Maintenance   [ ] Membership   [ ] Works / donation   [ ] Other ________",
                )
            y -= line_h

        # --- Footer / signature block ---
        foot_top = box_y + sig_zone - 1.5 * mm
        c.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.28))
        c.setLineWidth(0.55)
        c.line(inner_x, foot_top, right, foot_top)
        c.setFillColor(colors.HexColor(BRAND_MUTED))
        note_fs = max(5.5, 6.2 * scale)
        c.setFont("Helvetica", note_fs)
        if signatory_count == 2:
            c.drawString(inner_x, foot_top - 4.0 * mm, "Mode: Cash only. Subject to verification.")
        else:
            c.drawString(inner_x, foot_top - 4.0 * mm, "Mode: Cash only. Subject to verification by the Society.")
        c.drawString(inner_x, foot_top - 7.2 * mm, f"{ORG_EMAIL}  ·  {ORG_WEB}")
        sig_base = box_y + 5.5 * mm
        sig_gap = 2.8 * mm
        sig_roles = (
            ["Treasurer / Office bearer"]
            if signatory_count == 1
            else ["President", "Treasurer / Office bearer"]
        )
        if signatory_count == 1:
            sig_w = 48 * mm
            slots = [(right - sig_w, sig_w, sig_roles[0])]
        else:
            sig_w = 34 * mm
            total_w = 2 * sig_w + sig_gap
            sig_start = right - total_w
            slots = [
                (sig_start, sig_w, sig_roles[0]),
                (sig_start + sig_w + sig_gap, sig_w, sig_roles[1]),
            ]
        c.setStrokeColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.45))
        c.setLineWidth(0.65)
        for sx, sw, role in slots:
            c.line(sx, sig_base + 6.5 * mm, sx + sw, sig_base + 6.5 * mm)
            c.setFillColor(colors.HexColor(BRAND_NAVY))
            c.setFont("Helvetica-Bold", max(5.6, 6.8 * scale))
            c.drawCentredString(sx + sw / 2, sig_base + 3.2 * mm, "Authorised signatory")
            c.setFillColor(colors.HexColor(BRAND_GREEN))
            c.setFont("Helvetica", max(5.0, 5.8 * scale))
            c.drawCentredString(sx + sw / 2, sig_base + 0.8 * mm, role)

    serial = start_no
    for _page_i in range(page_count):
        for row in range(rows):
            for col in range(cols):
                box_x = margin_x + col * slip_w
                box_y = page_h - margin_y - (row + 1) * slip_h - row * gap_y
                _draw_slip(box_x, box_y, slip_w, slip_h, serial)
                if row < rows - 1:
                    tear_y = box_y - gap_y / 2
                    c.setFillColor(Color(11 / 255, 42 / 255, 86 / 255, alpha=0.35))
                    c.setFont("Helvetica", 5)
                    c.drawCentredString(page_w / 2, tear_y - 0.7 * mm, "· · · tear here · · ·")
                serial += 1
                if serial > CASH_RECEIPT_SERIAL_MAX:
                    serial = 1
        c.showPage()

    c.save()
    end_no = start_no + page_count * slips_per_page - 1
    fname = (
        f"mhws-cash-receipts-{layout_key}-{orient_key}-"
        f"{start_no:07d}-{min(end_no, CASH_RECEIPT_SERIAL_MAX):07d}.pdf"
    )
    return buf.getvalue(), fname


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

    org = org_title or _org_title_default(html=False)
    sub = org_subtitle or _org_subtitle_default()
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
        title=f"Pending Dues Report - {ORG_SHORT}",
        author=ORG_AUTHOR,
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
        Paragraph(ORG_SLOGAN, sub_style),
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
            f"{ORG_SLOGAN} — {ORG_SHORT}",
            ParagraphStyle("foot", parent=meta_style, alignment=rl["TA_CENTER"], fontSize=7.5),
        )
    )

    def _footer(canvas, _doc):
        _draw_report_page_chrome(
            canvas,
            site_root,
            page_w=page[0],
            page_h=page[1],
            mm=mm,
            footer_left=f"{ORG_SHORT} - Pending Dues Report",
            page_num=_doc.page,
        )

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
            blob = f"{r.get('plotNo')} {r.get('name')} {r.get('phone')} {r.get('email')} {r.get('officialTitle')} {r.get('householdCode')}".lower()
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


def query_passes_rows(conn, *, filters: dict | None = None) -> list[dict]:
    import rwa_parking

    filters = filters or {}
    status = str(filters.get("status") or "all").strip() or "all"
    kind = str(filters.get("kind") or "all").strip().lower() or "all"
    search = str(filters.get("search") or "").strip().lower()
    house_ids = _normalize_house_list(filters.get("houseIds"))
    kinds = None if kind in ("", "all") else [kind]
    items = rwa_parking.list_passes_for_report(
        conn,
        kinds=kinds,
        status=None if status == "all" else status,
        house_ids=house_ids or None,
    )
    out = []
    for item in items:
        row = {
            "plotNo": item.get("plotNo") or item.get("houseId") or "",
            "houseId": item.get("houseId") or "",
            "kindLabel": item.get("kindLabel") or item.get("kind") or "",
            "code": item.get("code") or "",
            "plateDisplay": item.get("plateDisplay") or item.get("plate") or "",
            "vehicleTypeLabel": item.get("vehicleTypeLabel") or item.get("vehicleType") or "",
            "visitorName": item.get("visitorName") or item.get("tenantName") or "",
            "statusLabel": item.get("statusLabel") or item.get("status") or "",
            "issuedAtLabel": item.get("issuedAtLabel") or (item.get("issuedAt") or "")[:16],
            "expiresAtLabel": item.get("expiresAtLabel") or (item.get("expiresAt") or "")[:16],
            "memberName": item.get("memberName") or "",
            "colour": item.get("colour") or "",
            "adhocCategoryLabel": item.get("categoryLabel") or item.get("staffCategoryLabel") or item.get("adhocCategoryLabel") or "",
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    return out


def query_tenants_rows(conn, *, filters: dict | None = None) -> list[dict]:
    import rwa_tenants

    filters = filters or {}
    status = str(filters.get("status") or "active").strip() or "active"
    search = str(filters.get("search") or "").strip().lower()
    house_ids = _normalize_house_list(filters.get("houseIds"))
    items = rwa_tenants.list_tenants_for_report(
        conn,
        status=None if status == "all" else status,
        house_ids=house_ids or None,
    )
    out = []
    for item in items:
        row = {
            "plotNo": item.get("plotNo") or item.get("houseId") or "",
            "houseId": item.get("houseId") or "",
            "name": item.get("name") or "",
            "phone": item.get("phone") or "",
            "email": item.get("email") or "",
            "status": item.get("status") or "",
            "occupancyStart": (item.get("occupancyStart") or "")[:10],
            "occupancyEnd": (item.get("occupancyEnd") or "")[:10],
            "note": (item.get("note") or "")[:120],
            "createdByName": item.get("createdByName") or "",
        }
        if search:
            blob = " ".join(str(row.get(k) or "") for k in row).lower()
            if search not in blob:
                continue
        out.append(row)
    return out


def query_vehicles_rows(conn, *, filters: dict | None = None) -> list[dict]:
    """Registered member + tenant vehicles (excludes visitors, ad-hoc, on-foot)."""
    import rwa_parking

    filters = filters or {}
    status = str(filters.get("status") or "all").strip() or "all"
    search = str(filters.get("search") or "").strip().lower()
    house_ids = _normalize_house_list(filters.get("houseIds"))
    items = rwa_parking.list_passes_for_report(
        conn,
        kinds=[rwa_parking.KIND_MEMBER, rwa_parking.KIND_TENANT],
        status=None if status == "all" else status,
        house_ids=house_ids or None,
        exclude_foot=True,
    )
    out = []
    for item in items:
        row = {
            "plotNo": item.get("plotNo") or item.get("houseId") or "",
            "houseId": item.get("houseId") or "",
            "kindLabel": item.get("kindLabel") or item.get("kind") or "",
            "plateDisplay": item.get("plateDisplay") or item.get("plate") or "",
            "vehicleTypeLabel": item.get("vehicleTypeLabel") or item.get("vehicleType") or "",
            "colour": item.get("colour") or "",
            "visitorName": item.get("visitorName") or item.get("tenantName") or "",
            "statusLabel": item.get("statusLabel") or item.get("status") or "",
            "code": item.get("code") or "",
            "issuedAtLabel": item.get("issuedAtLabel") or (item.get("issuedAt") or "")[:16],
            "expiresAtLabel": item.get("expiresAtLabel") or (item.get("expiresAt") or "")[:16],
            "memberName": item.get("memberName") or "",
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
        title=f"{title} - {ORG_SHORT}",
        author=ORG_AUTHOR,
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
    org = _org_title_default(html=True)
    sub = _org_subtitle_default()
    if seal:
        try:
            img = Image(str(seal), width=18 * mm, height=18 * mm)
            header_table = Table(
                [[img, [
                    Paragraph(org, org_style),
                    Paragraph(sub, sub_style),
                    Paragraph(ORG_SLOGAN, sub_style),
                ]]],
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
            story.append(Paragraph(ORG_SLOGAN, sub_style))
    else:
        story.append(Paragraph(org, org_style))
        story.append(Paragraph(sub, sub_style))
        story.append(Paragraph(ORG_SLOGAN, sub_style))
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
        _draw_report_page_chrome(
            canvas,
            site_root,
            page_w=page[0],
            page_h=page[1],
            mm=mm,
            footer_left=f"{ORG_SHORT} - {title}",
            page_num=_doc.page,
        )

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

    letterhead=True (digital): official letterhead pad layout + watermark
    (same template as Templates folder letterhead).
    letterhead=False (paper print): omit letterhead chrome; enlarge margins for
    pre-printed stationery — society watermark is still drawn on every page.
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
    styles = rl["getSampleStyleSheet"]()

    officers = _letterhead_officers(conn)
    issued = _fmt_ist_date()
    fee_year = info["payment"].get("feeYear") or _now_ist().year
    purpose_text = (purpose or "").strip()[:400] or "Official / banking / transfer purposes"
    house_no = str(info.get("plotNo") or info.get("houseId") or house_id)

    if letterhead:
        top_m, bottom_m, left_m, right_m = 62 * mm, 32 * mm, 14 * mm, 14 * mm
    else:
        top_m, bottom_m, left_m, right_m = 48 * mm, 32 * mm, 18 * mm, 18 * mm

    buf = io.BytesIO()
    page = rl["A4"]
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=f"No Dues Certificate - House/Plot {info['plotNo']}",
        author=ORG_AUTHOR,
    )

    title_style = ParagraphStyle(
        "ndTitle", parent=styles["Heading1"], fontSize=15, leading=19,
        textColor=colors.HexColor(BRAND_NAVY), alignment=rl["TA_CENTER"],
        spaceBefore=2, spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "ndBody", parent=styles["Normal"], fontSize=11, leading=16,
        textColor=colors.HexColor(BRAND_INK), alignment=rl["TA_JUSTIFY"], spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "ndMeta", parent=styles["Normal"], fontSize=9.5, leading=13,
        textColor=colors.HexColor(BRAND_MUTED), spaceAfter=4,
    )

    story = []
    story.append(Paragraph("<b>NO DUES CERTIFICATE</b>", title_style))
    body = (
        f"This is to certify that <b>{_escape(info['name'])}</b>, "
        f"resident of House/Plot <b>{_escape(house_no)}</b>, "
        f"{_escape(ORG_COLONY)} ({_escape(ORG_SUBTITLE)}), "
        f"has <b>no outstanding subscription / maintenance dues</b> "
        f"with <b>{_escape(ORG_SOCIETY)}</b> "
        f"as per the society ledger on record for fee year <b>{fee_year}</b>."
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
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "This certificate reflects society subscription ledger status only and does not cover "
        "municipal taxes or utility bills.",
        ParagraphStyle("ndFoot", parent=meta_style, fontSize=8, leading=10),
    ))

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _page(canvas, _doc):
        canvas.saveState()
        try:
            if letterhead:
                _draw_mhws_letterhead_chrome(
                    canvas,
                    site_root,
                    officers,
                    page_w=page[0],
                    page_h=page[1],
                    mm=mm,
                    doc_label=f"No Dues · Plot {house_no}",
                )
            else:
                # Paper-print omits full letterhead chrome but still carries society watermark.
                _draw_mhws_watermark(
                    canvas,
                    site_root,
                    page_w=page[0],
                    page_h=page[1],
                    size_mm=96,
                    cy_frac=0.48,
                    alpha=0.04,
                )
        finally:
            canvas.restoreState()

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
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

    letterhead=True (digital): official letterhead pad layout + watermark.
    letterhead=False (paper print): omit letterhead chrome for stationery fit;
    society watermark is still drawn on every page.
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
    styles = rl["getSampleStyleSheet"]()

    officers = _letterhead_officers(conn)
    issued = _fmt_ist_date()
    purpose_text = (
        (purpose or "").strip()[:400]
        or "Property transfer / sale / mortgage / official purposes"
    )
    house_no = str(info.get("plotNo") or info.get("houseId") or house_id)

    if letterhead:
        top_m, bottom_m, left_m, right_m = 62 * mm, 32 * mm, 14 * mm, 14 * mm
    else:
        top_m, bottom_m, left_m, right_m = 48 * mm, 32 * mm, 18 * mm, 18 * mm

    buf = io.BytesIO()
    page = rl["A4"]
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=f"No Objection Certificate - House/Plot {info['plotNo']}",
        author=ORG_AUTHOR,
    )

    title_style = ParagraphStyle(
        "nocTitle", parent=styles["Heading1"], fontSize=15, leading=19,
        textColor=colors.HexColor(BRAND_NAVY), alignment=rl["TA_CENTER"],
        spaceBefore=2, spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "nocBody", parent=styles["Normal"], fontSize=11, leading=16,
        textColor=colors.HexColor(BRAND_INK), alignment=rl["TA_JUSTIFY"], spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "nocMeta", parent=styles["Normal"], fontSize=9.5, leading=13,
        textColor=colors.HexColor(BRAND_MUTED), spaceAfter=4,
    )

    story = []
    story.append(Paragraph("<b>NO OBJECTION CERTIFICATE</b>", title_style))
    body = (
        f"This is to certify that <b>{_escape(ORG_SOCIETY)}</b> "
        f"({_escape(ORG_COLONY)}, {_escape(ORG_SUBTITLE)}) "
        f"has <b>no objection</b> for "
        f"<b>{_escape(info['name'])}</b>, resident of House/Plot <b>{_escape(house_no)}</b>, "
        f"in respect of the purpose stated below."
    )
    story.append(Paragraph(body, body_style))
    story.append(Paragraph(f"<b>Purpose:</b> {_escape(purpose_text)}", body_style))
    story.append(Paragraph(f"Issued on: <b>{issued}</b>", meta_style))
    if issued_by:
        story.append(Paragraph(f"Issued by: {_escape(issued_by)}", meta_style))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "This certificate expresses the Society's non-objection for the stated purpose only "
        "and does not constitute a dues clearance, title deed, or municipal approval.",
        ParagraphStyle("nocFoot", parent=meta_style, fontSize=8, leading=10),
    ))

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _page(canvas, _doc):
        canvas.saveState()
        try:
            if letterhead:
                _draw_mhws_letterhead_chrome(
                    canvas,
                    site_root,
                    officers,
                    page_w=page[0],
                    page_h=page[1],
                    mm=mm,
                    doc_label=f"NOC · Plot {house_no}",
                )
            else:
                _draw_mhws_watermark(
                    canvas,
                    site_root,
                    page_w=page[0],
                    page_h=page[1],
                    size_mm=96,
                    cy_frac=0.48,
                    alpha=0.04,
                )
        finally:
            canvas.restoreState()

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
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
    receipt_no: str | None = None,
    conn=None,
    officers: list[dict] | None = None,
) -> tuple[bytes, str]:
    """Cash receipt / voucher PDF matching the Templates folder receipt leaf + watermark."""
    rl = _reportlab()
    colors = rl["colors"]
    mm = rl["mm"]
    ParagraphStyle = rl["ParagraphStyle"]
    Paragraph = rl["Paragraph"]
    Spacer = rl["Spacer"]
    Table = rl["Table"]
    TableStyle = rl["TableStyle"]
    styles = rl["getSampleStyleSheet"]()

    is_claim = (kind or "payment").strip().lower() == "reimbursement"
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
    words = _amount_in_words_inr(amount)
    stamp = _now_ist().strftime("%Y%m%d")
    safe_plot = re.sub(r"[^A-Za-z0-9_-]+", "-", plot_no) or "plot"
    receipt_no = (receipt_no or f"CR-{safe_plot}-{stamp}").strip()

    # Split plot into house + block hints when possible (e.g. 12B-1).
    block = ""
    house_disp = plot_no
    if "-" in plot_no:
        parts = plot_no.rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            house_disp, block = parts[0], parts[1]

    # Purpose checkboxes from the standard leaf.
    purpose_l = (purpose + " " + category_label).lower()
    checks = {
        "dues": any(k in purpose_l for k in ("dues", "maintenance", "subscription", "fee")),
        "membership": "member" in purpose_l,
        "works": any(k in purpose_l for k in ("work", "donation", "donat")),
    }
    checks["other"] = not (checks["dues"] or checks["membership"] or checks["works"])

    def _box(on: bool) -> str:
        return "[x]" if on else "[ ]"

    title = "CASH PAYMENT VOUCHER" if is_claim else "CASH RECEIPT"
    buf = io.BytesIO()
    page = rl["A4"]

    if is_claim:
        # Reimbursement keeps letterhead-style voucher with watermark + office bearers.
        officer_slots = officers if officers is not None else _letterhead_officers(conn)
        doc = rl["SimpleDocTemplate"](
            buf,
            pagesize=page,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=62 * mm,
            bottomMargin=32 * mm,
            title=f"{title} - Plot {plot_no}",
            author=ORG_AUTHOR,
        )
        title_style = ParagraphStyle(
            "crTitle", parent=styles["Heading1"], fontSize=14, leading=18,
            textColor=colors.HexColor(BRAND_NAVY), alignment=rl["TA_CENTER"],
            spaceAfter=10,
        )
        meta_style = ParagraphStyle(
            "crMeta", parent=styles["Normal"], fontSize=10, leading=13,
            textColor=colors.HexColor(BRAND_INK), spaceAfter=3,
        )
        story = [Paragraph(f"<b>{title}</b>", title_style)]
        rows = [
            [Paragraph("<b>Date</b>", meta_style), Paragraph(_escape(paid_fmt), meta_style)],
            [Paragraph("<b>Plot</b>", meta_style), Paragraph(_escape(plot_no), meta_style)],
            [Paragraph("<b>Amount</b>", meta_style), Paragraph(f"Rs {amount:,}", meta_style)],
            [Paragraph("<b>In words</b>", meta_style), Paragraph(_escape(words), meta_style)],
            [Paragraph("<b>Paid by</b>", meta_style), Paragraph(_escape(payer_name), meta_style)],
            [Paragraph("<b>Cash received by</b>", meta_style), Paragraph(_escape(receiver_name), meta_style)],
        ]
        if purpose:
            rows.append([Paragraph("<b>Particulars</b>", meta_style), Paragraph(_escape(purpose), meta_style)])
        table = Table(rows, colWidths=[45 * mm, 120 * mm])
        table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor(BRAND_NAVY)),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.25)),
            ("BACKGROUND", (0, 0), (0, -1), colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.04)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph(
            "This voucher acknowledges cash paid for the stated colony expense. "
            "Upload as claim proof; an authorised office bearer must verify before reimbursement.",
            meta_style,
        ))
        if attestation_id and verify_url:
            try:
                import rwa_attest
                rwa_attest.append_attestation_to_story(
                    story, rl, verify_url=verify_url, attestation_id=attestation_id
                )
            except Exception:
                pass

        def _page(canvas, _doc):
            canvas.saveState()
            try:
                _draw_mhws_letterhead_chrome(
                    canvas, site_root, officer_slots,
                    page_w=page[0], page_h=page[1], mm=mm,
                    doc_label=f"Voucher · Plot {plot_no}",
                )
            finally:
                canvas.restoreState()

        doc.build(story, onFirstPage=_page, onLaterPages=_page)
        return buf.getvalue(), f"cash-voucher-{safe_plot}-{stamp}.pdf"

    # Standard cash receipt leaf (Templates folder booklet design, single filled slip).
    doc = rl["SimpleDocTemplate"](
        buf,
        pagesize=page,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=42 * mm,
        bottomMargin=36 * mm,
        title=f"Cash Receipt - Plot {plot_no}",
        author=ORG_AUTHOR,
    )
    label = ParagraphStyle(
        "crLbl", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.HexColor(BRAND_GREEN), fontName="Helvetica-Bold",
    )
    value = ParagraphStyle(
        "crVal", parent=styles["Normal"], fontSize=10.5, leading=14,
        textColor=colors.HexColor(BRAND_NAVY), fontName="Helvetica-Bold",
    )
    note = ParagraphStyle(
        "crNote", parent=styles["Normal"], fontSize=8, leading=11,
        textColor=colors.HexColor(BRAND_MUTED),
    )
    story = []
    story.append(Paragraph("Received from", label))
    story.append(Paragraph(_escape(payer_name), value))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Plot / House", label))
    story.append(Paragraph(_escape(house_disp), value))
    if block:
        story.append(Paragraph("Block", label))
        story.append(Paragraph(_escape(block), value))
    story.append(Spacer(1, 3 * mm))

    amt_table = Table(
        [[
            Paragraph("Amount (Rs)", label),
            Paragraph(f"<font size='16'><b>{amount:,}</b></font>", value),
        ]],
        colWidths=[40 * mm, 120 * mm],
    )
    amt_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor(BRAND_NAVY)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.Color(11 / 255, 42 / 255, 86 / 255, alpha=0.04)),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(amt_table)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("In words", label))
    story.append(Paragraph(_escape(words), value))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Towards", label))
    purpose_line = (
        f"{_box(checks['dues'])} Maintenance / dues &nbsp;&nbsp; "
        f"{_box(checks['membership'])} Membership &nbsp;&nbsp; "
        f"{_box(checks['works'])} Works / donation &nbsp;&nbsp; "
        f"{_box(checks['other'])} Other"
    )
    story.append(Paragraph(purpose_line, value))
    note_text = purpose or category_label or "—"
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Period / note", label))
    story.append(Paragraph(_escape(note_text), value))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"<b>Mode:</b> Cash only on this slip. Subject to verification by the Society. "
        f"Keep this as your acknowledgement. Web: {_escape(ORG_WEB)} · {_escape(ORG_EMAIL)}",
        note,
    ))
    story.append(Spacer(1, 14 * mm))
    sig = Table(
        [[
            Paragraph(
                f"_________________________<br/>Authorised signatory<br/>"
                f"<font size='8' color='#5a6a80'>{_escape(receiver_name)}</font>",
                note,
            ),
            Paragraph(
                "_________________________<br/>Member acknowledgement<br/>"
                f"<font size='8' color='#5a6a80'>{_escape(payer_name)}</font>",
                note,
            ),
        ]],
        colWidths=[80 * mm, 80 * mm],
    )
    story.append(sig)

    if attestation_id and verify_url:
        try:
            import rwa_attest
            rwa_attest.append_attestation_to_story(
                story, rl, verify_url=verify_url, attestation_id=attestation_id
            )
        except Exception:
            pass

    def _page(canvas, _doc):
        canvas.saveState()
        try:
            _draw_cash_receipt_leaf_chrome(
                canvas,
                site_root,
                page_w=page[0],
                page_h=page[1],
                mm=mm,
                receipt_no=receipt_no,
                paid_fmt=paid_fmt,
                copy_tag="Original",
            )
        finally:
            canvas.restoreState()

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    return buf.getvalue(), f"cash-received-{safe_plot}-{stamp}.pdf"


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
        "officeBearersOnly", "method", "dataset", "kind",
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

        if dataset == "passes":
            rows = query_passes_rows(conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Passes Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · passes",
            )
            return pdf, f"custom-passes-{stamp}.pdf"

        if dataset == "tenants":
            rows = query_tenants_rows(conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Tenants Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · tenants",
            )
            return pdf, f"custom-tenants-{stamp}.pdf"

        if dataset == "vehicles":
            rows = query_vehicles_rows(conn, filters=filters)
            pdf = build_tabular_pdf(
                conn, site_root=site_root, title=title or "Vehicles Report",
                field_defs=field_defs, rows=rows,
                filter_summary="custom · vehicles",
            )
            return pdf, f"custom-vehicles-{stamp}.pdf"

        raise ValueError("Unsupported dataset")

    raise ValueError(f"Unknown report: {report_id}")
