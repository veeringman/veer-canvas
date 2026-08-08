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
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM info_documents WHERE status = 'published'"
            ).fetchone()
            published_info = int(row["n"] if hasattr(row, "keys") else row[0] or 0)
        except Exception:
            published_info = 0
    return {
        "configured": bool(cfg["apiKey"]),
        "model": cfg["model"] if cfg["apiKey"] else None,
        "mode": "llm+rag" if cfg["apiKey"] else "rag-only",
        "avatarUrl": AI_AVATAR_URL,
        # Corpus is rebuilt from DB + files on every question — no separate reindex step.
        "knowledgeLive": True,
        "publishedInfoDocs": published_info,
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
            (_SUPERADMIN,),
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
    root = pathlib.Path(site_root) / "data" / "info-centre" / doc_id
    chunks: list[str] = []

    for name in ("content.html", "content_hi.html"):
        html_path = root / name
        if html_path.is_file():
            try:
                raw = _strip_html(html_path.read_text(encoding="utf-8", errors="ignore"))
                if raw:
                    chunks.append(raw[:20000])
            except OSError:
                pass

    fname = (filename or "").strip()
    if fname:
        fpath = root / fname
        if fpath.is_file():
            lower = fname.lower()
            mime_l = (mime or "").lower()
            if lower.endswith(".pdf") or "pdf" in mime_l:
                pdf_text = _extract_pdf_text(fpath)
                if pdf_text:
                    chunks.append(pdf_text)
            elif lower.endswith((".html", ".htm")):
                try:
                    chunks.append(_strip_html(fpath.read_text(encoding="utf-8", errors="ignore"))[:20000])
                except OSError:
                    pass
            elif lower.endswith((".txt", ".md", ".csv")):
                try:
                    chunks.append(fpath.read_text(encoding="utf-8", errors="ignore")[:20000])
                except OSError:
                    pass

    return "\n\n".join(c for c in chunks if c).strip()


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


def build_corpus(
    conn,
    site_root: pathlib.Path,
    actor: dict | None = None,
) -> list[dict[str, str]]:
    """Build searchable chunks from colony knowledge sources.

    Rebuilt on every assistant question from the live DB and Info Centre files,
    so newly published documents are included automatically (drafts are not).
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
            "The Information Centre tab holds published RWA documents, bylaws, circulars, "
            "and HTML guides. Newly published or updated documents are added to the assistant "
            "knowledge automatically on the next question — no separate reindex. "
            "Drafts are not included until published. Ask about a document by title or topic.",
        ),
        (
            "Portal FAQ — info and works",
            "Information Centre holds RWA documents and circulars. Works & Events tracks "
            "colony projects. Directory lists plots and residents.",
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

    # --- Information Centre (titles, summaries, HTML body, PDF text) ---
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(info_documents)").fetchall()}
        if cols:
            audiences = ["all"]
            if _actor_can_see_ec_info(actor):
                audiences.append("ec")
            audience_sql = ",".join("?" for _ in audiences)
            select_cols = [
                "id", "title", "summary", "category", "status", "filename",
            ]
            if "audience" in cols:
                select_cols.append("audience")
            if "doc_type" in cols:
                select_cols.append("doc_type")
            if "mime_type" in cols:
                select_cols.append("mime_type")
            if "original_name" in cols:
                select_cols.append("original_name")
            if "summary_hi" in cols:
                select_cols.append("summary_hi")
            if "title_hi" in cols:
                select_cols.append("title_hi")
            where_aud = f"AND audience IN ({audience_sql})" if "audience" in cols else ""
            rows = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM info_documents
                WHERE status = 'published' {where_aud}
                ORDER BY updated_at DESC LIMIT 120
                """,
                tuple(audiences) if "audience" in cols else (),
            ).fetchall()

            catalog_lines = ["Published Information Centre documents:"]
            for r in rows:
                title = (r["title"] or "").strip() or "(untitled)"
                cat = (r["category"] or "general").strip()
                catalog_lines.append(f"- {title} (category: {cat})")
                parts = [
                    f"Information Centre document: {title}",
                    f"Category: {cat}",
                ]
                if "title_hi" in r.keys() and r["title_hi"]:
                    parts.append(f"Hindi title: {r['title_hi']}")
                if r["summary"]:
                    parts.append(r["summary"])
                if "summary_hi" in r.keys() and r["summary_hi"]:
                    parts.append(r["summary_hi"])
                oname = r["original_name"] if "original_name" in r.keys() else None
                if r["filename"]:
                    parts.append(f"File: {oname or r['filename']}")
                mime = r["mime_type"] if "mime_type" in r.keys() else None
                body = _info_doc_body_text(
                    site_root, r["id"], filename=r["filename"], mime=mime
                )
                if body:
                    parts.append(body)
                else:
                    parts.append(
                        "Full file text could not be extracted; open this document in the "
                        "Information Centre tab for the original file."
                    )
                text = "\n".join(p for p in parts if p)
                # Cap per-doc indexing volume; chunk for retrieval
                for i, ch in enumerate(_chunk(text[:50000], size=800, overlap=100)):
                    docs.append({
                        "id": f"info:{r['id']}:{i}",
                        "title": f"Info Centre: {title}",
                        "source": "info",
                        "text": ch,
                    })
            if len(catalog_lines) > 1:
                docs.append({
                    "id": "info:catalog",
                    "title": "Information Centre document list",
                    "source": "info",
                    "text": "\n".join(catalog_lines),
                    "priority": "normal",
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
            "SELECT COUNT(*) AS n FROM residents WHERE status='active' AND house_id != ?",
            (_SUPERADMIN,),
        ).fetchone()["n"]
        docs.append({
            "id": "dir:stats",
            "title": "Directory overview",
            "source": "directory",
            "text": f"HBC Sanyard active plots in the directory: {int(n)}. "
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
        )
    ):
        intents.add("info")
    if any(t in ql for t in ("notice", "notices", "circular")):
        intents.add("notice")
    if any(t in ql for t in ("work", "works", "event", "project", "maintenance")):
        intents.add("works")
    return intents


def retrieve(query: str, corpus: list[dict[str, str]], *, k: int = 4) -> list[dict[str, str]]:
    q_tokens = _tokenize(query)
    if not q_tokens or not corpus:
        return []
    q_set = set(q_tokens)
    intents = _query_intent(query)
    # Info-centre questions need more passages from long PDFs
    if "info" in intents:
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
        src = doc.get("source") or ""
        if intents:
            if src in intents or (src == "me" and "me" in intents):
                score += 3.0
            elif src == "faq" and intents & {"dues", "concerns", "ec", "info"}:
                score += 0.4
            else:
                score -= 0.5
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
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
    limit = 4 if "info" in intents else 2
    if preferred_order:
        matched = [c for c in chunks if (c.get("source") or "") in preferred_order]
        if matched:
            ordered: list[dict[str, str]] = []
            for src in preferred_order:
                for c in matched:
                    if c.get("source") == src and c not in ordered:
                        ordered.append(c)
            return ordered[:limit]
    return chunks[:limit]


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

    if src in ("me", "info", "notice", "works", "faq"):
        snippet = text
        cap = 520 if src == "info" else 280
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
    cap = 1400 if "info" in _query_intent(query) else 900
    if len(answer) > cap:
        answer = answer[: cap - 1] + "…"
    return answer


def _chat_completions(cfg: dict[str, str], messages: list[dict[str, str]]) -> str:
    url = f"{cfg['baseUrl']}/chat/completions"
    payload = {
        "model": cfg["model"],
        "temperature": 0.1,
        "max_tokens": 350,
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
    retrieved = retrieve(q, corpus, k=8 if "info" in intents else 4)
    forced = _force_personal_chunks(q, personal)
    chunks = _merge_chunks(forced, retrieved, limit=8 if "info" in intents else 4)
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
    system = (
        "You are the HBC Sanyard RWA assistant. Answer ONLY the user's question. "
        "Use only the provided context. Give a short, specific answer (2–6 sentences or a short bullet list). "
        "Do NOT dump unrelated dues, EC lists, concerns, or FAQ. "
        "Do NOT invent figures or contact details. "
        "For EC questions: office bearers may be named with their title; general EC member seats "
        "are plot-only — never say the plot owner is the EC member unless the context names them "
        "with an office title. "
        f"Resident plot: {house}. "
        "If context is insufficient, say what is missing in one sentence."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for h in (history or [])[-4:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        content = (h.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content[:800]})
    messages.append({
        "role": "user",
        "content": f"Context:\n{context}\n\nQuestion: {q}\n\nReply with only the specific answer.",
    })
    try:
        answer = _chat_completions(cfg, messages)
        mode = "llm+rag"
    except ValueError:
        answer = _extractive_answer(q, answer_chunks)
        mode = "rag-only-fallback"
    return {"answer": answer, "sources": sources, "mode": mode}
