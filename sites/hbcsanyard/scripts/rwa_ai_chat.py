"""Private RAG assistant for the RWA message center.

Retrieves relevant colony documents (notices, Info Centre, works, FAQ) plus the
signed-in resident's own DB records (dues, payments, concerns, household, EC
roster) then answers via an OpenAI-compatible chat API when configured.
Without an API key, returns a grounded extractive answer from the top matches.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import urllib.error
import urllib.request
from typing import Any

AI_HOUSE_ID = "__AI__"
AI_AUTHOR_NAME = "RWA Assistant"
AI_AVATAR_URL = "/assets/rwa-assistant-avatar.svg"

_SUPERADMIN = "__SUPERADMIN__"
_ADHOC_GATE = "__ADHOC_GATE__"


def _load_env_file(path: pathlib.Path) -> None:
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def load_ai_config(site_root: pathlib.Path | None = None) -> dict[str, str]:
    if site_root is not None:
        root = pathlib.Path(site_root)
        _load_env_file(root / "data" / "ai.env")
        _load_env_file(root / "data" / "smtp.env")
    return {
        "apiKey": (os.environ.get("RWA_AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip(),
        "baseUrl": (
            os.environ.get("RWA_AI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/"),
        "model": (os.environ.get("RWA_AI_MODEL") or "gpt-4o-mini").strip(),
    }


def ai_status(site_root: pathlib.Path, conn=None) -> dict[str, Any]:
    cfg = load_ai_config(site_root)
    published_info = 0
    draft_info = 0
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM info_documents WHERE status = 'published'"
            ).fetchone()
            published_info = int(row["n"] if hasattr(row, "keys") else row[0] or 0)
        except Exception:
            published_info = 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM info_documents WHERE status = 'draft'"
            ).fetchone()
            draft_info = int(row["n"] if hasattr(row, "keys") else row[0] or 0)
        except Exception:
            draft_info = 0
    return {
        "configured": bool(cfg["apiKey"]),
        "model": cfg["model"] if cfg["apiKey"] else None,
        "mode": "llm+rag" if cfg["apiKey"] else "rag-only",
        "avatarUrl": AI_AVATAR_URL,
        # Corpus is rebuilt from DB + Info Centre files on every question — no separate reindex.
        "knowledgeLive": True,
        "publishedInfoDocs": published_info,
        "draftInfoDocs": draft_info,
        "knowledgeNote": (
            "Every uploaded or authored Information Centre document is included in "
            "assistant knowledge on the next question (published for members; drafts "
            "for Info managers). No separate reindex step."
        ),
    }


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1]


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _html_to_sections(html: str) -> list[dict[str, str]]:
    """Split authored HTML into heading → body sections (content hierarchy)."""
    raw = html or ""
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    m_content = re.search(
        r'<div class="content">\s*(.*?)\s*</div>\s*</article>',
        raw,
        flags=re.I | re.S,
    )
    if m_content:
        raw = m_content.group(1)
    else:
        m_body = re.search(r"<body\b[^>]*>(.*)</body>", raw, flags=re.I | re.S)
        if m_body:
            raw = m_body.group(1)

    parts = re.split(r"(?is)(?=<h[1-4]\b)", raw)
    sections: list[dict[str, str]] = []
    preamble = ""
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        hm = re.match(r"(?is)<h([1-4])\b[^>]*>(.*?)</h\1>\s*(.*)$", part, flags=re.S)
        if not hm:
            preamble = _strip_html(part)
            continue
        heading = _strip_html(hm.group(2))
        body = _strip_html(hm.group(3))
        if not heading and not body:
            continue
        sections.append({
            "heading": heading or "Section",
            "text": body,
            "level": hm.group(1),
        })
    if preamble:
        sections.insert(0, {"heading": "Introduction", "text": preamble, "level": "1"})
    if not sections:
        plain = _strip_html(raw)
        if plain:
            sections.append({"heading": "Content", "text": plain, "level": "1"})
    return sections


def _plain_to_sections(text: str) -> list[dict[str, str]]:
    """Split PDF/plain text into rough sections by pages, headings, or numbered rules."""
    raw = (text or "").strip()
    if not raw:
        return []
    pages = [p.strip() for p in re.split(r"\f+", raw) if p.strip()]
    if len(pages) > 1:
        return [
            {
                "heading": f"Page {i}",
                "text": re.sub(r"\s+", " ", page).strip(),
                "level": "2",
            }
            for i, page in enumerate(pages, start=1)
        ]

    lines = [ln.strip() for ln in raw.splitlines()]
    sections: list[dict[str, str]] = []
    cur_heading = "Content"
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_heading, cur_lines
        body = re.sub(r"\s+", " ", " ".join(cur_lines)).strip()
        if body or cur_heading != "Content":
            sections.append({
                "heading": cur_heading,
                "text": body,
                "level": "2",
            })
        cur_lines = []

    heading_re = re.compile(
        r"^(?:"
        r"(?:chapter|part|article|section|rule|clause|annex(?:ure)?)\s+[0-9ivxlcdm.\-]+"
        r"|[0-9]{1,2}[.)]\s+\S+"
        r"|[A-Z][A-Z0-9 ,/&\-]{8,80}"
        r")$",
        flags=re.I,
    )
    for ln in lines:
        if not ln:
            continue
        if heading_re.match(ln) and len(ln) <= 120:
            flush()
            cur_heading = ln
            continue
        cur_lines.append(ln)
    flush()
    if not sections:
        sections.append({
            "heading": "Content",
            "text": re.sub(r"\s+", " ", raw).strip()[:20000],
            "level": "1",
        })
    return sections


def _info_doc_section_units(
    site_root: pathlib.Path,
    doc_id: str,
    *,
    filename: str | None,
    mime: str | None,
) -> list[dict[str, str]]:
    """Return ordered content sections for an Info Centre document."""
    root = pathlib.Path(site_root) / "data" / "info-centre" / doc_id
    units: list[dict[str, str]] = []

    for name, lang in (("content.html", "en"), ("content_hi.html", "hi")):
        html_path = root / name
        if not html_path.is_file():
            continue
        try:
            raw = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for sec in _html_to_sections(raw):
            heading = sec["heading"]
            if lang == "hi":
                heading = f"{heading} (Hindi)" if heading else "Hindi content"
            units.append({
                "heading": heading,
                "text": (sec.get("text") or "")[:12000],
                "level": sec.get("level") or "2",
            })

    fname = (filename or "").strip()
    if fname:
        fpath = root / fname
        if fpath.is_file():
            lower = fname.lower()
            mime_l = (mime or "").lower()
            has_wrapped = any((root / n).is_file() for n in ("content.html", "content_hi.html"))
            if lower.endswith((".html", ".htm")) and not has_wrapped:
                try:
                    for sec in _html_to_sections(fpath.read_text(encoding="utf-8", errors="ignore")):
                        units.append({
                            "heading": sec["heading"],
                            "text": (sec.get("text") or "")[:12000],
                            "level": sec.get("level") or "2",
                        })
                except OSError:
                    pass
            elif lower.endswith(".pdf") or "pdf" in mime_l:
                pdf_text = _extract_pdf_text(fpath, max_chars=80000)
                for sec in _plain_to_sections(pdf_text):
                    units.append({
                        "heading": sec["heading"],
                        "text": (sec.get("text") or "")[:12000],
                        "level": sec.get("level") or "2",
                    })
            elif lower.endswith((".txt", ".md", ".csv")):
                try:
                    for sec in _plain_to_sections(
                        fpath.read_text(encoding="utf-8", errors="ignore")[:40000]
                    ):
                        units.append({
                            "heading": sec["heading"],
                            "text": (sec.get("text") or "")[:12000],
                            "level": sec.get("level") or "2",
                        })
                except OSError:
                    pass

    cleaned: list[dict[str, str]] = []
    for u in units:
        text = (u.get("text") or "").strip()
        heading = (u.get("heading") or "Content").strip()
        if not text and not heading:
            continue
        if (
            cleaned
            and cleaned[-1]["heading"] == heading
            and cleaned[-1]["text"][:200] == text[:200]
        ):
            continue
        cleaned.append({"heading": heading, "text": text, "level": u.get("level") or "2"})
    return cleaned


def _chunk(text: str, *, size: int = 700, overlap: int = 80) -> list[str]:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return []
    if len(raw) <= size:
        return [raw]
    out = []
    i = 0
    while i < len(raw):
        out.append(raw[i : i + size])
        i += max(1, size - overlap)
    return out


def _inr(amount: Any) -> str:
    try:
        n = int(amount or 0)
    except (TypeError, ValueError):
        n = 0
    return f"Rs {n:,}"


def _actor_house(actor: dict | None) -> str:
    if not actor:
        return ""
    return str(actor.get("houseId") or actor.get("house_id") or "").strip()


def _dues_snapshot(conn, house_id: str) -> dict[str, Any] | None:
    """Latest ledger row for a plot — same fields residents see on Dues."""
    row = conn.execute(
        """
        SELECT pr.*, pl.as_of, pl.source
        FROM payment_rows pr
        JOIN payment_ledgers pl ON pl.id = pr.ledger_id
        WHERE pr.house_id = ?
        ORDER BY pl.as_of DESC, pl.id DESC
        LIMIT 1
        """,
        (house_id,),
    ).fetchone()
    if not row:
        return None
    prev_total = int(row["balance_prev"] or 0)
    year_total = int(row["fee_amount"] or 0)
    received = int(row["amount_received"] or 0)
    total_due = int(row["total_due"] or (prev_total + year_total))
    outstanding = int(
        row["balance_outstanding"]
        if row["balance_outstanding"] is not None
        else (total_due - received)
    )
    prev_paid = min(max(received, 0), max(prev_total, 0)) if prev_total > 0 else 0
    prev_pending = max(0, prev_total - prev_paid)
    paid_toward_year = max(0, received - prev_paid)
    year_pending = max(0, year_total - paid_toward_year)
    return {
        "feeYear": row["fee_year"] or "",
        "asOf": row["as_of"] or "",
        "previousTotal": prev_total,
        "previousPaid": prev_paid,
        "previousPending": prev_pending,
        "currentYearTotal": year_total,
        "currentYearPaid": paid_toward_year,
        "currentYearPending": year_pending,
        "totalDue": total_due,
        "amountReceived": received,
        "pendingDues": outstanding,
        "remarks": (row["remarks"] or "").strip(),
        "treasuryStatus": (row["treasury_status"] if "treasury_status" in row.keys() else None) or "pending",
    }


def _ec_notes_person(notes: str | None) -> str:
    """Optional override in roster notes: 'EC: Full Name' or 'Member: Full Name'."""
    raw = (notes or "").strip()
    if not raw:
        return ""
    m = re.match(r"(?i)^(?:ec(?:\s*member)?|member|representative)\s*[:=\-]\s*(.+)$", raw)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80]


def _ec_person_for_plot(conn, house_id: str, *, plot_name: str, official_title: str, notes: str | None) -> str | None:
    """Who to name for an EC seat — never assume the plot owner is the seated member.

    Prefer (1) notes override, (2) a household parent, (3) plot name only when an
    office title is set (President etc.). Untitled general EC seats return None
    so callers list the plot without a personal name.
    """
    override = _ec_notes_person(notes)
    if override:
        return override
    try:
        parent = conn.execute(
            """
            SELECT name FROM household_members
            WHERE house_id = ? AND status = 'active' AND relation = 'parent'
              AND TRIM(COALESCE(name, '')) != ''
            ORDER BY name COLLATE NOCASE
            LIMIT 1
            """,
            (house_id,),
        ).fetchone()
        if parent and (parent["name"] or "").strip():
            return (parent["name"] or "").strip()
    except Exception:
        pass
    title = (official_title or "").strip()
    if title:
        # Office bearers: directory name is usually the officer; still OK to show.
        return (plot_name or "").strip() or None
    return None


def _build_ec_roster_doc(conn) -> dict[str, str] | None:
    """Colony-public EC roster that does not mislabel plot owners as seated members."""
    try:
        rows = conn.execute(
            """
            SELECT house_id, plot_no, name, official_title, role, notes,
                   is_ec_member, is_office_bearer
            FROM residents
            WHERE house_id != ?
              AND house_id != ?
              AND status = 'active'
              AND (
                is_ec_member = 1 OR is_office_bearer = 1 OR role = 'admin'
                OR (official_title IS NOT NULL AND TRIM(official_title) != '')
              )
            ORDER BY
              CASE WHEN role = 'admin' THEN 0
                   WHEN is_office_bearer = 1 OR (official_title IS NOT NULL AND TRIM(official_title) != '') THEN 1
                   ELSE 2 END,
              official_title COLLATE NOCASE,
              CAST(plot_no AS INTEGER),
              plot_no COLLATE NOCASE
            LIMIT 40
            """,
            (_SUPERADMIN, _ADHOC_GATE),
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    lines = [
        "Executive Committee / office bearers:",
        "Important: EC seats belong to plots/households. Do not assume the plot owner "
        "is the person who serves on the committee unless an office title is shown with a name. "
        "General EC member seats are listed by plot only.",
    ]
    for r in rows:
        plot = (r["plot_no"] or r["house_id"] or "").strip()
        title = (r["official_title"] or "").strip()
        if not title and (r["role"] or "") == "admin":
            title = "EC Admin"
        person = _ec_person_for_plot(
            conn,
            r["house_id"],
            plot_name=r["name"] or "",
            official_title=r["official_title"] or "",
            notes=r["notes"] if "notes" in r.keys() else None,
        )
        if title and person:
            lines.append(f"- {title}: {person} (plot {plot})")
        elif title:
            lines.append(f"- {title} — plot {plot}")
        else:
            # Untitled general EC seat — plot only (safe)
            lines.append(f"- EC member seat — plot {plot}")

    return {
        "id": "ec:roster",
        "title": "EC members and office bearers",
        "source": "ec",
        "text": "\n".join(lines),
        "priority": "high",
    }


def build_member_context(conn, actor: dict | None) -> list[dict[str, str]]:
    """Personal + shared operational facts for the signed-in resident only.

    Never includes other plots' balances, emails, or phone numbers.
    """
    docs: list[dict[str, str]] = []
    house_id = _actor_house(actor)
    if not house_id or house_id == _SUPERADMIN:
        return docs

    # --- EC / office-bearer roster (colony-public; no contacts) ---
    ec_doc = _build_ec_roster_doc(conn)
    if ec_doc:
        docs.append(ec_doc)

    # --- This plot's profile ---
    try:
        res = conn.execute(
            """
            SELECT house_id, plot_no, section, name, role, official_title, status
            FROM residents WHERE house_id = ?
            """,
            (house_id,),
        ).fetchone()
        if res:
            docs.append({
                "id": f"me:plot:{house_id}",
                "title": f"Your plot {house_id}",
                "source": "me",
                "text": (
                    f"You are signed in for plot {res['house_id']} "
                    f"(plot no {res['plot_no'] or res['house_id']}, "
                    f"section {res['section'] or '—'}). "
                    f"Primary name on record: {res['name'] or '—'}. "
                    f"Portal role: {res['role'] or 'resident'}. "
                    f"Official title: {res['official_title'] or 'none'}."
                ),
                "priority": "high",
            })
    except Exception:
        pass

    # --- Household members (own plot only; names/relations, no phones) ---
    try:
        members = conn.execute(
            """
            SELECT name, relation, is_primary, view_only, status, title
            FROM household_members
            WHERE house_id = ? AND status = 'active'
            ORDER BY is_primary DESC, name COLLATE NOCASE
            LIMIT 20
            """,
            (house_id,),
        ).fetchall()
        if members:
            lines = [f"Household members on plot {house_id}:"]
            for m in members:
                bits = [m["name"] or "—", f"relation {m['relation'] or 'other'}"]
                if m["title"]:
                    bits.append(str(m["title"]))
                if int(m["is_primary"] or 0):
                    bits.append("primary")
                if int(m["view_only"] or 0):
                    bits.append("view-only")
                lines.append("- " + ", ".join(bits))
            docs.append({
                "id": f"me:household:{house_id}",
                "title": "Your household members",
                "source": "me",
                "text": "\n".join(lines),
                "priority": "high",
            })
    except Exception:
        pass

    # --- Dues / ledger for this plot ---
    try:
        snap = _dues_snapshot(conn, house_id)
        if snap:
            text = (
                f"Dues ledger for your plot {house_id} "
                f"(fee year {snap['feeYear']}, as of {snap['asOf'] or 'latest'}):\n"
                f"- Previous period total {_inr(snap['previousTotal'])}; "
                f"paid {_inr(snap['previousPaid'])}; pending {_inr(snap['previousPending'])}\n"
                f"- Current year fee {_inr(snap['currentYearTotal'])}; "
                f"paid {_inr(snap['currentYearPaid'])}; pending {_inr(snap['currentYearPending'])}\n"
                f"- Total due {_inr(snap['totalDue'])}; amount received {_inr(snap['amountReceived'])}\n"
                f"- Outstanding / pending dues {_inr(snap['pendingDues'])}\n"
                f"- Treasury status on ledger row: {snap['treasuryStatus']}"
            )
            if snap["remarks"]:
                text += f"\n- Remarks: {snap['remarks']}"
            text += (
                "\nUse the Dues tab to upload receipts or request a No Dues Certificate. "
                "Figures come from the latest imported ledger."
            )
            docs.append({
                "id": f"me:dues:{house_id}",
                "title": f"Your dues — plot {house_id}",
                "source": "dues",
                "text": text,
                "priority": "high",
            })
        else:
            docs.append({
                "id": f"me:dues:{house_id}:none",
                "title": f"Your dues — plot {house_id}",
                "source": "dues",
                "text": (
                    f"No payment ledger row is loaded yet for plot {house_id}. "
                    "Check the Dues tab or ask EC / Treasurer."
                ),
                "priority": "high",
            })
    except Exception:
        pass

    # --- Recent payment / claim submissions ---
    try:
        rows = conn.execute(
            """
            SELECT id, kind, category, amount, paid_on, method, status, fee_year, note, created_at
            FROM payment_records
            WHERE house_id = ?
            ORDER BY created_at DESC
            LIMIT 8
            """,
            (house_id,),
        ).fetchall()
        if rows:
            lines = [f"Your recent payment / claim submissions for plot {house_id}:"]
            for r in rows:
                lines.append(
                    f"- {(r['kind'] or 'payment')} · {r['category'] or '—'} · "
                    f"{_inr(r['amount'])} · {r['paid_on'] or '—'} · "
                    f"{r['method'] or '—'} · status {r['status'] or '—'} "
                    f"(year {r['fee_year'] or '—'})"
                    + (f" · note: {(r['note'] or '')[:80]}" if r["note"] else "")
                )
            docs.append({
                "id": f"me:payments:{house_id}",
                "title": "Your payment submissions",
                "source": "dues",
                "text": "\n".join(lines),
                "priority": "high",
            })
    except Exception:
        pass

    # --- No Dues requests ---
    try:
        rows = conn.execute(
            """
            SELECT id, status, requested_at, reviewed_at, review_note, treasury_status
            FROM no_dues_requests
            WHERE house_id = ?
            ORDER BY requested_at DESC
            LIMIT 5
            """,
            (house_id,),
        ).fetchall()
        if rows:
            lines = [f"No Dues Certificate requests for plot {house_id}:"]
            for r in rows:
                lines.append(
                    f"- status {r['status'] or '—'}; requested {r['requested_at'] or '—'}; "
                    f"reviewed {r['reviewed_at'] or '—'}; "
                    f"treasury {r['treasury_status'] or 'pending'}"
                    + (f"; note {(r['review_note'] or '')[:100]}" if r["review_note"] else "")
                )
            docs.append({
                "id": f"me:nodues:{house_id}",
                "title": "Your No Dues requests",
                "source": "dues",
                "text": "\n".join(lines),
                "priority": "high",
            })
    except Exception:
        pass

    # --- Concerns raised by this plot ---
    try:
        rows = conn.execute(
            """
            SELECT id, subject, category, status, created_at, updated_at
            FROM grievances
            WHERE house_id = ?
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            (house_id,),
        ).fetchall()
        if rows:
            lines = [f"Concerns (mailbox) filed by plot {house_id}:"]
            for r in rows:
                lines.append(
                    f"- [{r['status'] or 'open'}] {r['subject'] or '(no subject)'} "
                    f"(category {r['category'] or 'general'}; "
                    f"updated {r['updated_at'] or r['created_at'] or '—'})"
                )
            docs.append({
                "id": f"me:concerns:{house_id}",
                "title": "Your concerns",
                "source": "concerns",
                "text": "\n".join(lines),
                "priority": "high",
            })
        else:
            docs.append({
                "id": f"me:concerns:{house_id}:none",
                "title": "Your concerns",
                "source": "concerns",
                "text": (
                    f"Plot {house_id} has no concerns on file. "
                    "Residents can open a concern from the Concerns tab."
                ),
                "priority": "normal",
            })
    except Exception:
        pass

    # Colony-wide concern counts (no private detail)
    try:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress_count,
              SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved_count
            FROM grievances
            """
        ).fetchone()
        if row and int(row["total"] or 0):
            docs.append({
                "id": "concerns:stats",
                "title": "Colony concern mailbox stats",
                "source": "concerns",
                "text": (
                    f"Colony mailbox totals: {int(row['total'] or 0)} concerns; "
                    f"{int(row['open_count'] or 0)} open; "
                    f"{int(row['in_progress_count'] or 0)} in progress; "
                    f"{int(row['resolved_count'] or 0)} resolved. "
                    "Individual concerns from other plots are private."
                ),
                "priority": "normal",
            })
    except Exception:
        pass

    return docs


def _extract_pdf_text(path: pathlib.Path, *, max_chars: int = 60000) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            t = (page.extract_text() or "").strip()
        except Exception:
            t = ""
        if not t:
            continue
        parts.append(t)
        total += len(t)
        if total >= max_chars:
            break
    text = re.sub(r"\s+", " ", "\n".join(parts)).strip()
    return text[:max_chars]


def _info_doc_body_text(site_root: pathlib.Path, doc_id: str, *, filename: str | None, mime: str | None) -> str:
    """Load searchable text for an Info Centre document (HTML page and/or uploaded file)."""
    units = _info_doc_section_units(site_root, doc_id, filename=filename, mime=mime)
    if not units:
        return ""
    parts = []
    for u in units:
        heading = (u.get("heading") or "").strip()
        text = (u.get("text") or "").strip()
        if heading and text:
            parts.append(f"{heading}\n{text}")
        elif text:
            parts.append(text)
        elif heading:
            parts.append(heading)
    return "\n\n".join(parts).strip()


def _actor_can_see_ec_info(actor: dict | None) -> bool:
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    if (actor.get("role") or "") == "admin":
        return True
    if actor.get("isEcAdmin") or actor.get("isEcMember") or actor.get("isOfficeBearer"):
        return True
    if str(actor.get("officialTitle") or "").strip():
        return True
    return False


def _actor_can_manage_info(actor: dict | None) -> bool:
    """True when the actor can see Information Centre drafts (manage_info)."""
    if not actor:
        return False
    if actor.get("superAdmin"):
        return True
    ents = actor.get("entitlements")
    if isinstance(ents, (list, tuple, set)) and "manage_info" in ents:
        return True
    # EC admins typically hold manage_info implicitly via entitlement resolver.
    if actor.get("isEcAdmin") or (actor.get("role") or "") == "admin":
        return True
    return False


def build_corpus(
    conn,
    site_root: pathlib.Path,
    actor: dict | None = None,
) -> list[dict[str, str]]:
    """Build searchable chunks from colony knowledge sources.

    Rebuilt on every assistant question from the live DB and Info Centre files.
    Every uploaded PDF/file or authored HTML in Information Centre is included
    according to visibility: published docs for members; drafts also for Info managers.
    No separate reindex step.
    """
    docs: list[dict[str, str]] = []

    faq = [
        (
            "Portal FAQ — login",
            "Residents sign in with plot number and OTP sent to registered email/phone. "
            "Household delegates can be added by the plot owner under Profile. "
            "View-only delegates cannot post concerns or messages.",
        ),
        (
            "Portal FAQ — dues",
            "Open the Dues tab to see pending balance, upload payment receipts, "
            "request cash-received notes, and track No Dues Certificate requests. "
            "EC verifies payments; Treasury validates and confirms financial items. "
            "Ask the AI Assistant 'what are my dues?' for your plot's ledger figures.",
        ),
        (
            "Portal FAQ — concerns",
            "Colony mailbox (Concerns) is a shared inbox. Any resident can post a concern "
            "and reply on threads. EC members with Concerns entitlement can update status. "
            "Ask the assistant about your own open concerns.",
        ),
        (
            "Portal FAQ — EC",
            "Executive Committee seats belong to plots/households. Office bearers "
            "(President, Secretary, Treasurer, etc.) are listed by title and name. "
            "General EC member seats are listed by plot only — the plot owner in the "
            "directory is not always the person who serves on the committee. "
            "Ask 'who is the president' or 'list EC members' for the roster.",
        ),
        (
            "Portal FAQ — messages",
            "Messages has a colony channel visible to all residents and private plot-to-plot chats. "
            "The AI Assistant thread is private — only you see those answers. "
            "You can like colony and DM messages.",
        ),
        (
            "Portal FAQ — Information Centre",
            "The Information Centre tab holds RWA documents, bylaws, circulars, and HTML guides "
            "as a content hierarchy: folder/topic → document → sections/pages. "
            "Every uploaded file or authored HTML page becomes part of the AI Assistant knowledge "
            "automatically on the next question — no separate reindex. "
            "Published documents are available to members; drafts are available to Info managers. "
            "Ask about a folder, document title, section, or compare bye-laws with the Act.",
        ),
        (
            "Portal FAQ — info and works",
            "Information Centre content is hierarchical (folder → document → sections). "
            "Works & Events tracks colony projects. Directory lists plots and residents.",
        ),
        (
            "Portal FAQ — Information Centre analysis",
            "You can ask the assistant about Information Centre content in plain language, "
            "including what is in a folder, what a document or section says, "
            "and analytical questions such as comparing society bye-laws with the "
            "HP Societies Registration Act, spotting conflicts or gaps, or ideas for reform. "
            "Answers use portal documents only and are not formal legal advice.",
        ),
    ]
    for title, body in faq:
        for i, ch in enumerate(_chunk(body, size=500)):
            docs.append({"id": f"faq:{title}:{i}", "title": title, "source": "faq", "text": ch})

    try:
        rows = conn.execute(
            """
            SELECT id, title, body, category, published_at
            FROM notices WHERE status = 'published'
            ORDER BY pinned DESC, published_at DESC LIMIT 80
            """
        ).fetchall()
        for r in rows:
            text = f"{r['title']}\n{r['body'] or ''}"
            for i, ch in enumerate(_chunk(text)):
                docs.append({
                    "id": f"notice:{r['id']}:{i}",
                    "title": f"Notice: {r['title']}",
                    "source": "notice",
                    "text": ch,
                })
    except Exception:
        pass

    # --- Information Centre (folders/topics + titles, summaries, HTML/PDF text) ---
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        folder_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(info_folders)").fetchall()
        } if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='info_folders'"
        ).fetchone() else set()
        if cols:
            include_drafts = _actor_can_manage_info(actor)
            select_cols = [
                "d.id", "d.title", "d.summary", "d.category", "d.status", "d.filename",
            ]
            if "audience" in cols:
                select_cols.append("d.audience")
            if "allowed_member_ids" in cols:
                select_cols.append("d.allowed_member_ids")
            if "doc_type" in cols:
                select_cols.append("d.doc_type")
            if "mime_type" in cols:
                select_cols.append("d.mime_type")
            if "original_name" in cols:
                select_cols.append("d.original_name")
            if "summary_hi" in cols:
                select_cols.append("d.summary_hi")
            if "title_hi" in cols:
                select_cols.append("d.title_hi")
            if "folder_id" in cols:
                select_cols.append("d.folder_id")
            join_sql = ""
            if folder_cols and "folder_id" in cols:
                select_cols.extend([
                    "f.title AS folder_title",
                    "f.title_hi AS folder_title_hi",
                    "f.summary AS folder_summary",
                ])
                if "audience" in folder_cols:
                    select_cols.append("f.audience AS folder_audience")
                if "allowed_member_ids" in folder_cols:
                    select_cols.append("f.allowed_member_ids AS folder_allowed_member_ids")
                join_sql = "LEFT JOIN info_folders f ON f.id = d.folder_id"
            if include_drafts:
                where_status = "d.status IN ('published', 'draft')"
            else:
                where_status = "d.status = 'published'"
            if folder_cols and "folder_id" in cols:
                order_sql = """
                ORDER BY
                  CASE WHEN d.folder_id IS NULL OR d.folder_id = '' THEN 1 ELSE 0 END,
                  COALESCE(f.sort_order, 9999) ASC,
                  COALESCE(f.title, '') COLLATE NOCASE ASC,
                  d.updated_at DESC
                """
            else:
                order_sql = "ORDER BY d.updated_at DESC"
            rows = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM info_documents d
                {join_sql}
                WHERE {where_status}
                {order_sql}
                LIMIT 200
                """,
            ).fetchall()

            # Enforce the same folder∩document ACL as the Info Centre API.
            try:
                import rwa_portal as _info_acl  # type: ignore
            except ImportError:
                _info_acl = None
            filtered_rows = []
            if _info_acl is not None and actor is not None:
                manage_info = _actor_can_manage_info(actor)
                folders_by_id = {
                    r["id"]: r
                    for r in conn.execute("SELECT * FROM info_folders").fetchall()
                } if folder_cols else {}
                for r in rows:
                    if manage_info:
                        filtered_rows.append(r)
                        continue
                    if (r["status"] or "") != "published":
                        continue
                    if _info_acl.can_view_info_document(
                        conn, actor, r, manage_info=False, folders_by_id=folders_by_id
                    ):
                        filtered_rows.append(r)
                rows = filtered_rows
            elif not include_drafts:
                # Fallback without portal helpers: all + EC only (legacy).
                keep = []
                for r in rows:
                    aud = "all"
                    if "audience" in r.keys() and r["audience"]:
                        aud = str(r["audience"]).strip().lower()
                    if aud == "all":
                        keep.append(r)
                    elif aud == "ec" and _actor_can_see_ec_info(actor):
                        keep.append(r)
                rows = keep

            # Folder map + per-folder inventories for topic questions
            folder_groups: dict[str, dict[str, Any]] = {}
            hierarchy_lines = [
                "Information Centre content hierarchy "
                "(Folder → Document → Sections/pages with stored content):",
            ]
            for r in rows:
                folder_id = ""
                if "folder_id" in r.keys() and r["folder_id"]:
                    folder_id = str(r["folder_id"]).strip()
                folder_title = ""
                if "folder_title" in r.keys() and r["folder_title"]:
                    folder_title = str(r["folder_title"]).strip()
                if not folder_title:
                    folder_title = "Unfiled"
                    folder_id = folder_id or "__unfiled__"
                folder_summary = ""
                if "folder_summary" in r.keys() and r["folder_summary"]:
                    folder_summary = str(r["folder_summary"]).strip()
                folder_title_hi = ""
                if "folder_title_hi" in r.keys() and r["folder_title_hi"]:
                    folder_title_hi = str(r["folder_title_hi"]).strip()
                g = folder_groups.setdefault(
                    folder_id or "__unfiled__",
                    {
                        "id": folder_id or "__unfiled__",
                        "title": folder_title,
                        "titleHi": folder_title_hi,
                        "summary": folder_summary,
                        "docs": [],
                    },
                )
                g["docs"].append({
                    "id": r["id"],
                    "title": (r["title"] or "").strip() or "(untitled)",
                    "category": (r["category"] or "general").strip(),
                    "row": r,
                })

            # Include empty folders so the assistant knows the topic map
            if folder_cols:
                try:
                    for fr in conn.execute(
                        """
                        SELECT id, title, title_hi, summary, sort_order
                        FROM info_folders
                        ORDER BY sort_order ASC, title COLLATE NOCASE ASC
                        """
                    ).fetchall():
                        fid = str(fr["id"] or "").strip()
                        if not fid or fid in folder_groups:
                            continue
                        folder_groups[fid] = {
                            "id": fid,
                            "title": (fr["title"] or "").strip() or fid,
                            "titleHi": (fr["title_hi"] or "").strip() if "title_hi" in fr.keys() else "",
                            "summary": (fr["summary"] or "").strip() if "summary" in fr.keys() else "",
                            "docs": [],
                        }
                except Exception:
                    pass

            catalog_lines = [
                "Published Information Centre documents (grouped by folder/topic):",
            ]
            folder_map_lines = [
                "Information Centre folders/topics (related documents live together):",
            ]

            for g in folder_groups.values():
                doc_entries = g["docs"]
                titles = [d["title"] for d in doc_entries]
                folder_map_lines.append(
                    f"- Folder “{g['title']}”"
                    + (f" / {g['titleHi']}" if g.get("titleHi") else "")
                    + (f": {g['summary']}" if g.get("summary") else "")
                    + f" — {len(titles)} published document"
                    + ("s" if len(titles) != 1 else "")
                )
                if titles:
                    folder_map_lines.append(
                        "  Documents: " + "; ".join(titles[:40])
                    )

                hierarchy_lines.append(f"Folder: {g['title']}")
                if g.get("summary"):
                    hierarchy_lines.append(f"  Summary: {g['summary']}")

                folder_section_notes: list[str] = []

                for entry in doc_entries:
                    r = entry["row"]
                    title = entry["title"]
                    cat = entry["category"]
                    folder_title = g["title"]
                    folder_summary = g.get("summary") or ""
                    folder_title_hi = g.get("titleHi") or ""
                    catalog_lines.append(
                        f"- [{folder_title}] {title} (category: {cat})"
                    )

                    mime = r["mime_type"] if "mime_type" in r.keys() else None
                    units = _info_doc_section_units(
                        site_root,
                        r["id"],
                        filename=r["filename"],
                        mime=mime,
                    )
                    section_headings = [
                        (u.get("heading") or "Content").strip()
                        for u in units
                        if (u.get("heading") or "").strip()
                    ][:30]

                    hierarchy_lines.append(f"  Document: {title} [{cat}]")
                    doc_status = (r["status"] or "published").strip().lower()
                    if doc_status == "draft":
                        hierarchy_lines.append("    Status: DRAFT (Info managers only; not published to all members)")
                    if r["summary"]:
                        hierarchy_lines.append(f"    Summary: {str(r['summary']).strip()[:240]}")
                    if section_headings:
                        hierarchy_lines.append(
                            "    Sections: " + " · ".join(section_headings[:20])
                        )
                        folder_section_notes.append(
                            f"- {title}: " + "; ".join(section_headings[:12])
                        )
                    else:
                        hierarchy_lines.append(
                            "    Sections: (full text not extractable — open original in Information Centre)"
                        )

                    breadcrumb_root = f"{folder_title} > {title}"
                    meta_bits = [
                        f"Information Centre path: {breadcrumb_root}",
                        f"Folder/topic: {folder_title}",
                        f"Document: {title}",
                        f"Category: {cat}",
                        f"Status: {doc_status}",
                    ]
                    if doc_status == "draft":
                        meta_bits.append(
                            "This document is a DRAFT — visible to Info managers in AI answers; "
                            "not yet published to all members."
                        )
                    if folder_title_hi:
                        meta_bits.append(f"Hindi folder name: {folder_title_hi}")
                    if folder_summary:
                        meta_bits.append(f"Folder summary: {folder_summary}")
                    if "title_hi" in r.keys() and r["title_hi"]:
                        meta_bits.append(f"Hindi title: {r['title_hi']}")
                    if r["summary"]:
                        meta_bits.append(str(r["summary"]))
                    if "summary_hi" in r.keys() and r["summary_hi"]:
                        meta_bits.append(str(r["summary_hi"]))
                    oname = r["original_name"] if "original_name" in r.keys() else None
                    if r["filename"]:
                        meta_bits.append(f"File: {oname or r['filename']}")

                    # Document overview chunk (path + summary + section index)
                    overview = "\n".join(meta_bits)
                    if section_headings:
                        overview += "\nSections in this document:\n" + "\n".join(
                            f"- {h}" for h in section_headings
                        )
                    docs.append({
                        "id": f"info:{r['id']}:overview",
                        "title": f"Info Centre [{folder_title}]: {title}",
                        "source": "info",
                        "text": overview,
                    })

                    if not units:
                        docs.append({
                            "id": f"info:{r['id']}:0",
                            "title": f"Info Centre [{folder_title}]: {title}",
                            "source": "info",
                            "text": (
                                overview
                                + "\nFull file text could not be extracted; open this document "
                                "in the Information Centre tab for the original file."
                            ),
                        })
                        continue

                    # Section-level content chunks with full hierarchy path
                    for si, unit in enumerate(units):
                        heading = (unit.get("heading") or "Content").strip()
                        body = (unit.get("text") or "").strip()
                        path = f"{breadcrumb_root} > {heading}"
                        draft_note = (
                            "Status: DRAFT (Info managers only).\n"
                            if doc_status == "draft"
                            else ""
                        )
                        base = (
                            f"Information Centre path: {path}\n"
                            f"Folder/topic: {folder_title}\n"
                            f"Document: {title}\n"
                            f"{draft_note}"
                            f"Section: {heading}\n"
                        )
                        payload = base + (body if body else "(No extractable text in this section.)")
                        for ci, ch in enumerate(_chunk(payload[:20000], size=900, overlap=120)):
                            docs.append({
                                "id": f"info:{r['id']}:s{si}:{ci}",
                                "title": f"Info Centre [{folder_title}]: {title} · {heading}",
                                "source": "info",
                                "text": ch,
                            })

                # Per-folder inventory including content section outline
                inv_parts = [
                    f"Information Centre folder/topic: {g['title']}",
                ]
                if g.get("titleHi"):
                    inv_parts.append(f"Hindi folder name: {g['titleHi']}")
                if g.get("summary"):
                    inv_parts.append(g["summary"])
                if titles:
                    inv_parts.append(
                        "Documents in this folder:\n"
                        + "\n".join(f"- {t}" for t in titles)
                    )
                else:
                    inv_parts.append("No published documents in this folder yet.")
                if folder_section_notes:
                    inv_parts.append(
                        "Content sections inside this folder:\n"
                        + "\n".join(folder_section_notes)
                    )
                inv_parts.append(
                    "Open the Information Centre tab and choose this folder to view "
                    "PDFs and HTML drafts together. Ask about a document or section by name."
                )
                docs.append({
                    "id": f"info:folder:{g['id']}",
                    "title": f"Info Centre folder: {g['title']}",
                    "source": "info",
                    "text": "\n".join(inv_parts),
                })

            if len(hierarchy_lines) > 1:
                # Keep hierarchy overview within a useful retrieval size
                hier_text = "\n".join(hierarchy_lines)
                for i, ch in enumerate(_chunk(hier_text[:24000], size=1200, overlap=100)):
                    docs.append({
                        "id": f"info:hierarchy:{i}",
                        "title": "Information Centre content hierarchy",
                        "source": "info",
                        "text": ch,
                    })
            if len(folder_map_lines) > 1:
                docs.append({
                    "id": "info:folders",
                    "title": "Information Centre folder map",
                    "source": "info",
                    "text": "\n".join(folder_map_lines),
                })
            if len(catalog_lines) > 1:
                docs.append({
                    "id": "info:catalog",
                    "title": "Information Centre document list",
                    "source": "info",
                    "text": "\n".join(catalog_lines),
                })
    except Exception:
        pass

    try:
        rows = conn.execute(
            """
            SELECT id, title, summary, status, location
            FROM colony_works
            ORDER BY updated_at DESC LIMIT 40
            """
        ).fetchall()
        for r in rows:
            text = f"{r['title']}\nStatus: {r['status']}\nLocation: {r['location'] or ''}\n{r['summary'] or ''}"
            for i, ch in enumerate(_chunk(text, size=500)):
                docs.append({
                    "id": f"work:{r['id']}:{i}",
                    "title": f"Works: {r['title']}",
                    "source": "works",
                    "text": ch,
                })
    except Exception:
        pass

    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM residents WHERE status='active' AND house_id != ? AND house_id != ?",
            (_SUPERADMIN, _ADHOC_GATE),
        ).fetchone()["n"]
        docs.append({
            "id": "dir:stats",
            "title": "Directory overview",
            "source": "directory",
            "text": f"Himuda Housing Colony Sanyard active plots in the directory: {int(n)}. "
            "Use the Directory tab to browse plot holders. Contact details are limited for privacy.",
        })
    except Exception:
        pass

    return docs


def _query_intent(query: str) -> set[str]:
    ql = " ".join(_tokenize(query))
    intents: set[str] = set()
    if any(t in ql for t in ("due", "dues", "pending", "balance", "payment", "paid", "ledger", "amount", "owe")):
        intents.add("dues")
    if any(t in ql for t in ("nodues", "certificate", "no")) and "due" in ql:
        intents.add("dues")
    if any(t in ql for t in ("nodues", "certificate")):
        intents.add("dues")
    if any(t in ql for t in ("ec", "president", "secretary", "treasurer", "committee", "office", "bearer")):
        intents.add("ec")
    if any(t in ql for t in ("who", "is")) and any(
        t in ql for t in ("president", "secretary", "treasurer", "ec", "office")
    ):
        intents.add("ec")
    if any(t in ql for t in ("concern", "concerns", "grievance", "complaint", "mailbox")):
        intents.add("concerns")
    if any(t in ql for t in ("household", "family", "members")):
        intents.add("me")
    if any(
        t in ql
        for t in (
            "notice", "notices", "circular",
            "info", "information", "document", "documents", "centre", "center",
            "bylaw", "bylaws", "bye", "law", "laws", "rule", "rules", "act",
            "society", "societies", "registration", "circular", "policy",
            "folder", "folders", "topic", "topics",
            "compare", "conflict", "conflicts", "gap", "gaps", "reform",
            "compliance", "versus", "difference", "differences",
        )
    ):
        intents.add("info")
    # Analytical questions across Info Centre docs (e.g. bylaws vs Act).
    if any(
        t in ql
        for t in (
            "compare", "conflict", "conflicts", "gap", "gaps", "reform",
            "compliance", "versus", "difference", "differences",
            "inconsistency", "align", "alignment",
        )
    ) or (
        "act" in ql
        and any(t in ql for t in ("bylaw", "bylaws", "bye", "rule", "rules"))
    ):
        intents.add("compare")
        intents.add("info")
    if any(t in ql for t in ("notice", "notices", "circular")):
        intents.add("notice")
    if any(t in ql for t in ("work", "works", "event", "project", "maintenance")):
        intents.add("works")
    return intents


def _info_family(title: str, text: str = "") -> str:
    """Classify an Info Centre chunk as act / bylaws / other."""
    blob = f"{title or ''} {(text or '')[:400]}".lower()
    if any(k in blob for k in ("societies registration act", "registration act 2006", "hp societies")):
        return "act"
    if (" act" in blob or blob.startswith("act")) and any(
        k in blob for k in ("societ", "registration", "2006", "himachal")
    ):
        return "act"
    if any(
        k in blob
        for k in (
            "bye-law", "bye law", "bylaw", "by-law", "rules and bylaws",
            "rules & bye", "interpretation", "society rules",
        )
    ):
        return "bylaws"
    return "other"


def _is_info_structure_chunk(doc: dict[str, str]) -> bool:
    """True for catalog/hierarchy/overview inventory chunks (not section body text)."""
    doc_id = str(doc.get("id") or "")
    return (
        doc_id.startswith("info:folder:")
        or doc_id.startswith("info:hierarchy:")
        or doc_id.endswith(":overview")
        or doc_id in {"info:folders", "info:catalog"}
    )


def _is_info_content_chunk(doc: dict[str, str]) -> bool:
    """True for extractable document/section body chunks."""
    if (doc.get("source") or "") != "info":
        return False
    doc_id = str(doc.get("id") or "")
    if _is_info_structure_chunk(doc):
        return False
    # Section body: info:<id>:s<si>:<ci>  or fallback full-text info:<id>:0
    return ":s" in doc_id or doc_id.endswith(":0")


def _is_info_browse_query(query: str) -> bool:
    """User is asking what exists (folders/docs), not what a clause says."""
    raw = (query or "").strip().lower()
    ql = " ".join(_tokenize(query))
    if not ql and not raw:
        return False
    # Explicit inventory / map asks
    explicit = (
        "list documents", "list folders", "list topics",
        "what documents", "which documents", "available documents",
        "documents available", "what folders", "which folders",
        "folder map", "document list", "document catalog", "document catalogue",
        "content hierarchy", "document hierarchy", "what is available",
        "whats available", "what's available", "show documents", "all documents",
        "information centre documents", "info centre documents",
        "what do we have", "inventory", "catalogue", "catalog",
    )
    if any(p in raw for p in explicit):
        return True
    if any(t in ql for t in ("hierarchy", "structure", "toc", "outline")) and any(
        t in ql for t in ("info", "information", "document", "documents", "folder", "folders", "centre", "center")
    ):
        return True
    # "what is in the information centre" / "what's in registration folder"
    if any(
        p in raw
        for p in (
            "what is in", "whats in", "what's in", "what are in",
            "contents of", "documents in the", "files in the",
        )
    ) and any(
        t in ql for t in ("info", "information", "centre", "center", "folder", "folders")
    ):
        return True
    return False


def retrieve(query: str, corpus: list[dict[str, str]], *, k: int = 4) -> list[dict[str, str]]:
    q_tokens = _tokenize(query)
    if not q_tokens or not corpus:
        return []
    q_set = set(q_tokens)
    intents = _query_intent(query)
    browse = _is_info_browse_query(query)
    if "compare" in intents:
        k = max(k, 14)
    elif "info" in intents:
        k = max(k, 8)
    scored: list[tuple[float, dict[str, str]]] = []
    for doc in corpus:
        d_tokens = _tokenize(doc.get("text", "") + " " + doc.get("title", ""))
        if not d_tokens:
            continue
        d_set = set(d_tokens)
        overlap = q_set & d_set
        if not overlap:
            continue
        score = float(len(overlap)) / (len(q_set) ** 0.5)
        title_tokens = set(_tokenize(doc.get("title", "")))
        score += 0.5 * len(q_set & title_tokens)
        doc_id = doc.get("id") or ""
        if _is_info_structure_chunk(doc):
            if browse:
                score += 2.5
            elif "compare" in intents:
                # Structure dumps drown out Act/bylaws passages
                score -= 2.0
            else:
                # Prefer specific section text over inventory for content questions
                score -= 1.2
        elif _is_info_content_chunk(doc) and ("info" in intents or "compare" in intents):
            score += 1.8
            if not browse:
                score += 0.6
        family = _info_family(doc.get("title") or "", doc.get("text") or "")
        if "compare" in intents and family in {"act", "bylaws"}:
            score += 2.5
            if _is_info_content_chunk(doc):
                score += 1.0
        src = doc.get("source") or ""
        if intents:
            if src in intents or (src == "me" and "me" in intents) or (
                src == "info" and ("info" in intents or "compare" in intents)
            ):
                score += 3.0
            elif src == "faq" and intents & {"dues", "concerns", "ec", "info", "compare"}:
                # FAQ about Information Centre often restates the whole hierarchy
                if src == "faq" and "info" in intents and not browse:
                    score -= 1.0
                else:
                    score += 0.4
            else:
                score -= 0.5
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Analytical questions: keep both Act and Bylaws passages in the top set.
    if "compare" in intents:
        picked: list[dict[str, str]] = []
        buckets: dict[str, list[dict[str, str]]] = {"act": [], "bylaws": [], "other": []}
        for _score, doc in scored:
            if doc.get("source") != "info":
                continue
            if _is_info_structure_chunk(doc):
                continue
            fam = _info_family(doc.get("title") or "", doc.get("text") or "")
            buckets.setdefault(fam, []).append(doc)
        for fam in ("act", "bylaws"):
            for d in buckets.get(fam, [])[:6]:
                if d not in picked:
                    picked.append(d)
        for _score, doc in scored:
            if _is_info_structure_chunk(doc) and not browse:
                continue
            if doc not in picked:
                picked.append(doc)
            if len(picked) >= k:
                break
        return picked[:k]

    # Content questions: prefer section body over hierarchy/catalog inventory.
    if "info" in intents and not browse:
        content_first = [d for _s, d in scored if _is_info_content_chunk(d)]
        other = [d for _s, d in scored if not _is_info_structure_chunk(d) and d not in content_first]
        # Allow at most one overview if no section text matched
        overviews = [d for _s, d in scored if str(d.get("id") or "").endswith(":overview")]
        picked: list[dict[str, str]] = []
        for d in content_first + other:
            if d not in picked:
                picked.append(d)
            if len(picked) >= k:
                break
        if not content_first and overviews:
            for d in overviews[:2]:
                if d not in picked:
                    picked.append(d)
                if len(picked) >= k:
                    break
        if picked:
            return picked[:k]

    return [d for _, d in scored[:k]]


def _force_personal_chunks(query: str, personal: list[dict[str, str]]) -> list[dict[str, str]]:
    """Pull only the personal docs that match the question intent (max 2)."""
    if not personal:
        return []
    intents = _query_intent(query)
    if not intents:
        return []
    want_sources: set[str] = set()
    if "dues" in intents:
        want_sources.add("dues")
    if "ec" in intents:
        want_sources.add("ec")
    if "concerns" in intents:
        want_sources.add("concerns")
    if "me" in intents:
        want_sources.add("me")
    if not want_sources:
        return []
    out: list[dict[str, str]] = []
    for d in personal:
        if (d.get("source") or "") in want_sources:
            out.append(d)
        if len(out) >= 2:
            break
    return out


def _force_info_hierarchy_chunks(corpus: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    """Only inject folder/catalog maps when the user asked what documents exist."""
    if "info" not in _query_intent(query):
        return []
    browse = _is_info_browse_query(query)
    q_tokens = set(_tokenize(query))
    folder_docs = [
        d for d in corpus
        if str(d.get("id") or "").startswith("info:folder:")
    ]
    scored = []
    for d in folder_docs:
        overlap = q_tokens & set(_tokenize((d.get("title") or "") + " " + (d.get("text") or "")[:500]))
        if overlap:
            scored.append((len(overlap), d))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[dict[str, str]] = []
    if browse:
        preferred_ids = ("info:folders", "info:catalog", "info:hierarchy:0")
        by_id = {d.get("id"): d for d in corpus if d.get("id")}
        for pid in preferred_ids:
            doc = by_id.get(pid)
            if doc:
                out.append(doc)
        for _, d in scored[:2]:
            if d not in out:
                out.append(d)
        return out[:3]

    # Content questions: at most one best-matching folder inventory — never the full hierarchy.
    for _, d in scored[:1]:
        out.append(d)
    return out[:1]


def _merge_chunks(*groups: list[dict[str, str]], limit: int = 4) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for group in groups:
        for d in group:
            key = d.get("id") or f"{d.get('title')}:{d.get('text', '')[:40]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
            if len(out) >= limit:
                return out
    return out


def _pick_answer_chunks(query: str, chunks: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep only the most relevant chunks for a focused reply."""
    if not chunks:
        return []
    intents = _query_intent(query)
    browse = _is_info_browse_query(query)
    preferred_order = []
    if "dues" in intents:
        preferred_order.append("dues")
    if "ec" in intents:
        preferred_order.append("ec")
    if "concerns" in intents:
        preferred_order.append("concerns")
    if "me" in intents:
        preferred_order.append("me")
    if "info" in intents:
        preferred_order.append("info")
    if "notice" in intents:
        preferred_order.append("notice")
    if "works" in intents:
        preferred_order.append("works")
    if "compare" in intents:
        limit = 12
    elif "info" in intents and browse:
        limit = 4
    elif "info" in intents:
        limit = 6
    else:
        limit = 2

    pool = list(chunks)
    if "info" in intents and not browse:
        content = [c for c in pool if _is_info_content_chunk(c)]
        non_structure = [c for c in pool if not _is_info_structure_chunk(c)]
        # Prefer section body; drop hierarchy/catalog unless nothing else matched
        if content:
            pool = content + [c for c in non_structure if c not in content]
        else:
            pool = non_structure or pool

    if preferred_order:
        matched = [c for c in pool if (c.get("source") or "") in preferred_order]
        if matched:
            ordered: list[dict[str, str]] = []
            for src in preferred_order:
                for c in matched:
                    if c.get("source") == src and c not in ordered:
                        ordered.append(c)
            return ordered[:limit]
        return pool[:limit]
    return pool[:limit]


def _format_specific_answer(query: str, chunk: dict[str, str]) -> str:
    """Turn one context chunk into a short direct answer."""
    text = (chunk.get("text") or "").strip()
    src = chunk.get("source") or ""
    title = (chunk.get("title") or "").strip()
    ql = " ".join(_tokenize(query))

    if src == "dues":
        # Prefer the ledger snapshot over payment list when both may appear
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        pending = next((ln for ln in lines if "Outstanding" in ln or "pending dues" in ln.lower()), "")
        year = next((ln for ln in lines if "Current year fee" in ln or ln.lower().startswith("- current year")), "")
        head = next((ln for ln in lines if ln.lower().startswith("dues ledger")), lines[0] if lines else title)
        bits = [head]
        if year and year not in bits:
            bits.append(year)
        if pending and pending not in bits:
            bits.append(pending)
        # Keep payment-submission docs shorter
        if "submissions" in title.lower() or "payment / claim" in text.lower():
            return f"Your recent payment submissions:\n" + "\n".join(lines[1:4])
        if "No Dues" in title or "No Dues" in text[:80]:
            return "\n".join(lines[:5])
        return "\n".join(bits[:4])

    if src == "ec":
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        bullets = [ln for ln in lines if ln.startswith("-")]
        note = next((ln for ln in lines if ln.lower().startswith("important:")), "")
        role_keys = ("president", "secretary", "treasurer", "vice")
        hit = next((r for r in role_keys if r in ql), "")
        if hit:
            filtered = [ln for ln in bullets if hit in ln.lower()]
            if filtered:
                return "\n".join(filtered)
        if not bullets:
            return text[:400]
        out = "EC / office bearers:\n" + "\n".join(bullets[:14])
        if note and "plot only" in note.lower():
            out += "\n\nGeneral EC seats are by plot; the plot owner may not be the seated member."
        return out

    if src == "concerns":
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        return "\n".join(lines[:8])

    if src == "info":
        if _is_info_structure_chunk(chunk) and not _is_info_browse_query(query):
            # Avoid dumping catalog/hierarchy on content questions in rag-only mode
            return ""
        # Prefer section body: drop long path/meta headers when possible
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        body_lines = [
            ln for ln in lines
            if not ln.lower().startswith((
                "information centre path:",
                "folder/topic:",
                "document:",
                "category:",
                "status:",
                "section:",
                "hindi ",
                "folder summary:",
                "file:",
            ))
        ]
        snippet = "\n".join(body_lines or lines)
        cap = 420 if _is_info_content_chunk(chunk) else 320
        if len(snippet) > cap:
            snippet = snippet[: cap - 1] + "…"
        label = title or "Answer"
        return f"{label}\n{snippet}"

    if src in ("me", "notice", "works", "faq"):
        snippet = text
        cap = 280
        if len(snippet) > cap:
            snippet = snippet[: cap - 1] + "…"
        label = title or "Answer"
        return f"{label}\n{snippet}"

    snippet = text
    if len(snippet) > 280:
        snippet = snippet[:277] + "…"
    return f"{title or 'Answer'}\n{snippet}"


def _extractive_answer(query: str, chunks: list[dict[str, str]]) -> str:
    picked = _pick_answer_chunks(query, chunks)
    if not picked:
        return (
            "I don’t have a specific match for that. Try asking about your dues, "
            "EC roles, Information Centre documents, or your concerns."
        )
    parts = [_format_specific_answer(query, ch) for ch in picked]
    answer = "\n\n".join(p for p in parts if p).strip()
    if not answer:
        return (
            "I don’t have a specific match for that. Try naming a document or topic "
            "from the Information Centre, or ask what folders/documents are available."
        )
    browse = _is_info_browse_query(query)
    if "compare" in _query_intent(query):
        cap = 1400
    elif "info" in _query_intent(query) and browse:
        cap = 900
    elif "info" in _query_intent(query):
        cap = 900
    else:
        cap = 900
    if len(answer) > cap:
        answer = answer[: cap - 1] + "…"
    return answer


def _chat_completions(
    cfg: dict[str, str],
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 350,
) -> str:
    url = f"{cfg['baseUrl']}/chat/completions"
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "max_tokens": max(120, min(int(max_tokens or 350), 1800)),
        "messages": messages,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['apiKey']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:300]
        raise ValueError(f"AI provider error ({exc.code}): {body}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"AI request failed: {exc}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Empty AI response")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise ValueError("Empty AI content")
    return content


def answer_query(
    conn,
    site_root: pathlib.Path,
    *,
    query: str,
    history: list[dict[str, str]] | None = None,
    actor: dict | None = None,
) -> dict[str, Any]:
    """Return {answer, sources, mode} for a resident question."""
    q = (query or "").strip()
    if not q:
        raise ValueError("Ask a question")
    if len(q) > 2000:
        raise ValueError("Question too long")

    personal = build_member_context(conn, actor)
    public = build_corpus(conn, site_root, actor=actor)
    corpus = personal + public
    intents = _query_intent(q)
    browse = _is_info_browse_query(q)
    info_heavy = "info" in intents or "compare" in intents
    retrieve_k = 14 if "compare" in intents else (10 if info_heavy else 4)
    merge_limit = 14 if "compare" in intents else (8 if info_heavy else 4)
    if info_heavy and not browse and "compare" not in intents:
        merge_limit = 6
    retrieved = retrieve(q, corpus, k=retrieve_k)
    forced = _force_personal_chunks(q, personal)
    info_forced = _force_info_hierarchy_chunks(public, q)
    # Browse: inventory first. Content/compare: retrieved section text first.
    if browse:
        chunks = _merge_chunks(forced, info_forced, retrieved, limit=merge_limit)
    else:
        chunks = _merge_chunks(forced, retrieved, info_forced, limit=merge_limit)
    answer_chunks = _pick_answer_chunks(q, chunks)

    cfg = load_ai_config(site_root)
    sources = [
        {"title": c.get("title"), "source": c.get("source"), "id": c.get("id")}
        for c in answer_chunks
    ]

    if not cfg["apiKey"]:
        return {
            "answer": _extractive_answer(q, answer_chunks),
            "sources": sources,
            "mode": "rag-only",
        }

    context = "\n\n".join(
        f"[{c.get('title')}]\n{c.get('text')}" for c in answer_chunks
    ) or "(No matching records found.)"
    house = _actor_house(actor) or "unknown"
    if "compare" in intents:
        system = (
            "You are the Himuda Housing Colony Sanyard RWA assistant. Answer using ONLY the provided "
            "Information Centre context (document section text). "
            "For comparison / conflict / gap / reform questions: "
            "1) cite both sources when present (e.g. society bye-laws/rules AND the HP Societies Registration Act), "
            "2) list clear alignments, conflicts or gaps as short bullets, "
            "3) suggest practical reform ideas only where the context supports them, "
            "4) say when the portal text is incomplete. "
            "Do NOT paste folder maps, full document inventories, or unrelated sections. "
            "This is guidance from published portal documents — not formal legal advice. "
            "Do NOT invent section numbers or clauses that are not in the context. "
            f"Resident plot: {house}."
        )
        user_tail = (
            "Reply with a structured analysis: Alignments, Conflicts/Gaps, "
            "Reform ideas (if any), and Limits of available text. "
            "Do not list the whole Information Centre."
        )
        max_tokens = 1100
    elif info_heavy and browse:
        system = (
            "You are the Himuda Housing Colony Sanyard RWA assistant. The user asked what is available "
            "in the Information Centre. Summarize only the relevant folders/documents "
            "from context as a short list. Do not paste full section text. "
            f"Resident plot: {house}."
        )
        user_tail = "Reply with a short inventory that answers the question."
        max_tokens = 450
    elif info_heavy:
        system = (
            "You are the Himuda Housing Colony Sanyard RWA assistant. Answer ONLY the user's specific question "
            "using relevant Information Centre section text from the context. "
            "Cite the document (and section when helpful) that answers the question. "
            "Keep the reply focused: short paragraphs or a few bullets. "
            "Do NOT list the full folder/document hierarchy or unrelated documents. "
            "Do NOT invent clauses not present in context. "
            "Do NOT dump dues, EC lists, or FAQ. "
            f"Resident plot: {house}. "
            "If context is insufficient, say what is missing in one sentence."
        )
        user_tail = (
            "Reply with only the specific answer from the matching document/section. "
            "Do not dump the document structure."
        )
        max_tokens = 550
    else:
        system = (
            "You are the Himuda Housing Colony Sanyard RWA assistant. Answer ONLY the user's question. "
            "Use only the provided context. Give a short, specific answer (2–6 sentences or a short bullet list). "
            "Do NOT dump unrelated dues, EC lists, concerns, or FAQ. "
            "Do NOT invent figures or contact details. "
            "For EC questions: office bearers may be named with their title; general EC member seats "
            "are plot-only — never say the plot owner is the EC member unless the context names them "
            "with an office title. "
            f"Resident plot: {house}. "
            "If context is insufficient, say what is missing in one sentence."
        )
        user_tail = "Reply with only the specific answer."
        max_tokens = 350
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for h in (history or [])[-4:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        content = (h.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content[:800]})
    messages.append({
        "role": "user",
        "content": f"Context:\n{context}\n\nQuestion: {q}\n\n{user_tail}",
    })
    try:
        answer = _chat_completions(cfg, messages, max_tokens=max_tokens)
        mode = "llm+rag"
    except ValueError:
        answer = _extractive_answer(q, answer_chunks)
        mode = "rag-only-fallback"
    return {"answer": answer, "sources": sources, "mode": mode}
