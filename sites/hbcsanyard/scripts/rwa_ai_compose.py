"""Intent-based document drafting for Templates → Write a document.

Pipeline:
  1. Understand — classify the writer's request (local + optional eGenie).
  2. Think — retrieve colony templates, Info Centre docs, and meeting minutes.
  3. Act — Syntheon synthesizes HTML; OpenAI-compatible chat is the fallback.

eGenie and Syntheon run on a **separate** EC2 (not the housingcolonysanyard
host). Defaults point at that public Caddy front door. Override in
``data/ai.env`` if the hostname changes.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import pathlib
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse

import rwa_ai_chat
from rwa_template_starters import list_document_starters, starter_by_id
from rwa_templates import sanitize_compose_html

INTENT_MAX = 4000
DEFAULT_EGENIE_URL = "https://egenie.veerlabs.solutions"
DEFAULT_SYNTHEON_URL = "https://syntheon.veerlabs.solutions"

EGENIE_PATHS = (
    "/v1/wishes",
    "/v1/fulfill",
    "/fulfill",
    "/api/v1/fulfill",
    "/v1/understand",
)
SYNTHEON_PATHS = (
    "/v1/synthesize",
    "/v1/compose",
    "/v1/documents",
    "/synthesize",
    "/compose",
)

_STARTER_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("mom_gh", ("general house", "general body", "gbm", "agm minutes", "agm mom")),
    ("mom_ec", ("ec minutes", "executive committee minutes", "ec mom", "committee minutes")),
    ("agenda", ("agenda",)),
    ("office_note", ("office note", "file note", "put up for orders")),
    ("covering_letter", ("covering letter", "authorised signator", "authorized signator", "bank of baroda")),
    ("forwarding_letter", ("forwarding letter", "please find enclosed", "forwarding of")),
    ("circular", ("circular",)),
    ("notice", ("notice", "colony notice", "all plot owners")),
    ("resolution", ("resolution", "resolved that", "certified true copy")),
]


def _remote_or_default(raw: str | None, default: str) -> str:
    """Ignore leftover localhost URLs from the first portal-box draft."""
    value = (raw or "").strip()
    if not value:
        return default
    low = value.lower()
    if "127.0.0.1" in low or "localhost" in low:
        return default
    return value


def load_compose_config(site_root: pathlib.Path | None = None) -> dict[str, str]:
    ai = rwa_ai_chat.load_ai_config(site_root)
    egenie_on = (os.environ.get("EGENIE_ENABLED") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }
    syntheon_on = (os.environ.get("SYNTHEON_ENABLED") or "1").strip().lower() not in {
        "0", "false", "off", "no",
    }
    return {
        **ai,
        "egenieUrl": _remote_or_default(
            os.environ.get("EGENIE_URL"),
            DEFAULT_EGENIE_URL,
        ).rstrip("/"),
        "egenieKey": (os.environ.get("EGENIE_API_KEY") or os.environ.get("EGENIE_TOKEN") or "").strip(),
        "egenieEnabled": "1" if egenie_on else "0",
        "egenieTimeoutMs": (os.environ.get("EGENIE_TIMEOUT_MS") or "90000").strip(),
        "syntheonUrl": _remote_or_default(
            os.environ.get("SYNTHEON_URL"),
            DEFAULT_SYNTHEON_URL,
        ).rstrip("/"),
        "syntheonKey": (
            os.environ.get("SYNTHEON_API_KEY") or os.environ.get("SYNTHEON_TOKEN") or ""
        ).strip(),
        "syntheonEnabled": "1" if syntheon_on else "0",
        "syntheonTimeoutMs": (os.environ.get("SYNTHEON_TIMEOUT_MS") or "20000").strip(),
    }


def compose_status(site_root: pathlib.Path, conn=None) -> dict[str, Any]:
    cfg = load_compose_config(site_root)
    egenie = _service_health(cfg["egenieUrl"], cfg["egenieKey"], timeout_s=2.0)
    syntheon = _service_health(cfg["syntheonUrl"], cfg["syntheonKey"], timeout_s=2.0)
    llm = bool(cfg.get("apiKey"))
    engines: list[str] = []
    if cfg["egenieEnabled"] == "1" and egenie.get("ok"):
        engines.append("egenie")
    if cfg["syntheonEnabled"] == "1" and syntheon.get("ok"):
        engines.append("syntheon")
    if llm:
        engines.append("llm")
    engines.append("rag")
    return {
        "configured": bool(engines),
        "mode": "+".join(engines),
        "egenie": {
            "enabled": cfg["egenieEnabled"] == "1",
            "url": _public_service_url(cfg["egenieUrl"]),
            **egenie,
        },
        "syntheon": {
            "enabled": cfg["syntheonEnabled"] == "1",
            "url": _public_service_url(cfg["syntheonUrl"]),
            **syntheon,
        },
        "llm": {"configured": llm, "model": cfg.get("model") if llm else None},
        "note": (
            "Describe the letter, resolution, notice, or minutes. The assistant uses "
            "Write-a-document starters, saved templates, Information Centre files, and "
            "published meeting proceedings. eGenie understands intent; Syntheon writes "
            "the draft onto Society letterhead style."
        ),
    }


def draft_document(
    conn,
    site_root: pathlib.Path,
    *,
    intent_text: str,
    actor: dict | None = None,
    starter_id: str = "",
    title: str = "",
    current_html: str = "",
) -> dict[str, Any]:
    utterance = (intent_text or "").strip()
    if not utterance:
        raise ValueError("Describe the document you want to write")
    if len(utterance) > INTENT_MAX:
        raise ValueError("Request is too long")

    local_intent = classify_intent(utterance, starter_id=starter_id)
    starter = starter_by_id(local_intent["starterId"]) or starter_by_id("blank")
    corpus = build_compose_corpus(conn, site_root, actor=actor)
    retrieved, rag_engine = rwa_ai_chat.retrieve_smart(
        utterance,
        corpus,
        k=8,
        site_root=site_root,
    )
    passages = _passages_for_prompt(utterance, retrieved)

    cfg = load_compose_config(site_root)
    warnings: list[str] = []
    used: list[str] = []

    egenie_out: dict[str, Any] | None = None
    if cfg["egenieEnabled"] == "1":
        egenie_out = call_egenie(
            cfg,
            utterance=utterance,
            starter=starter or {},
            passages=passages,
            title=title,
        )
        if egenie_out is None:
            warnings.append("eGenie unreachable — used local intent.")
        else:
            used.append("egenie")
            local_intent = _merge_intent(local_intent, egenie_out)
            starter = starter_by_id(local_intent["starterId"]) or starter

    html_body = _html_from_remote(egenie_out)
    remote_title = _title_from_remote(egenie_out)

    syntheon_out: dict[str, Any] | None = None
    if not html_body and cfg["syntheonEnabled"] == "1":
        syntheon_out = call_syntheon(
            cfg,
            utterance=utterance,
            intent=local_intent,
            starter=starter or {},
            passages=passages,
            title=title,
            current_html=current_html,
        )
        if syntheon_out is None:
            warnings.append("Syntheon unreachable — used on-box drafting.")
        else:
            used.append("syntheon")
            html_body = _html_from_remote(syntheon_out)
            remote_title = _title_from_remote(syntheon_out) or remote_title
            local_intent = _merge_intent(local_intent, syntheon_out)

    mode = ""
    if not html_body:
        html_body, mode = _fallback_draft(
            cfg,
            utterance=utterance,
            intent=local_intent,
            starter=starter or {},
            passages=passages,
            title=title,
            current_html=current_html,
        )
        if mode:
            used.append(mode)

    if not html_body:
        html_body = _extractive_draft(utterance, starter or {}, passages)

    html_body = sanitize_compose_html(html_body)
    suggested = (remote_title or local_intent.get("title") or title or "").strip()
    if not suggested:
        suggested = (starter or {}).get("suggestedTitle") or (starter or {}).get("title") or "Untitled document"
        if suggested.endswith("—") or suggested.endswith("-"):
            suggested = f"{suggested} {local_intent.get('topic') or 'draft'}".strip()

    sources = [
        {"title": p.get("title"), "source": p.get("source"), "id": p.get("id")}
        for p in passages
        if p.get("title")
    ]
    engines = used or ["rag"]
    return {
        "title": suggested[:160],
        "starterId": local_intent.get("starterId") or (starter or {}).get("id") or "",
        "category": (starter or {}).get("category") or "correspondence",
        "htmlBody": html_body,
        "intent": local_intent,
        "sources": sources,
        "mode": "+".join(engines),
        "ragEngine": rag_engine,
        "warnings": warnings,
    }


def classify_intent(text: str, *, starter_id: str = "") -> dict[str, Any]:
    picked = (starter_id or "").strip().lower()
    if picked and starter_by_id(picked):
        starter_id_out = picked
    else:
        starter_id_out = _guess_starter(text)
    starter = starter_by_id(starter_id_out) or starter_by_id("blank")
    topic = _topic_from_text(text)
    return {
        "kind": "document.compose",
        "starterId": starter_id_out,
        "docType": (starter or {}).get("title") or starter_id_out,
        "topic": topic,
        "title": _suggested_title(starter or {}, topic, text),
        "summary": text.strip()[:400],
        "source": "local" if not picked else "user",
    }


def build_compose_corpus(
    conn,
    site_root: pathlib.Path,
    actor: dict | None = None,
) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for starter in list_document_starters():
        body = _html_to_text(starter.get("bodyHtml") or "")
        docs.append({
            "id": f"starter:{starter['id']}",
            "title": f"Starter — {starter.get('title') or starter['id']}",
            "text": (
                f"{starter.get('title')}. {starter.get('description') or ''}\n{body}"
            )[:8000],
            "source": "template",
        })
    docs.extend(_library_template_chunks(conn, site_root))
    public = rwa_ai_chat.build_corpus(conn, site_root, actor=actor)
    for chunk in public:
        src = (chunk.get("source") or "").strip()
        if src in {"info", "proceedings", "notice", "faq"}:
            docs.append(chunk)
    return docs


def call_egenie(
    cfg: dict[str, str],
    *,
    utterance: str,
    starter: dict[str, Any],
    passages: list[dict[str, str]],
    title: str,
) -> dict[str, Any] | None:
    """POST ``{wish: str}`` to eGenie ``/v1/wishes`` on the dedicated EC2."""
    wish = _egenie_wish_text(utterance, starter=starter, passages=passages, title=title)
    payload = {
        "wish": wish,
        "fast": False,
        "kind": "document.compose",
        "tenant": "hbcsanyard",
        "title": title,
        "starterId": starter.get("id") or "",
    }
    return _post_first_ok(
        cfg["egenieUrl"],
        EGENIE_PATHS,
        payload,
        api_key=cfg.get("egenieKey") or "",
        timeout_ms=cfg.get("egenieTimeoutMs") or "90000",
        default_timeout=90.0,
        cap=120.0,
    )


def _egenie_wish_text(
    utterance: str,
    *,
    starter: dict[str, Any],
    passages: list[dict[str, str]],
    title: str,
) -> str:
    bits = [
        "You are drafting an official document for Mandi Housing Welfare Society "
        "(Himuda Housing Colony Sanyard, Registration No. 467 dated 21/07/2012).",
        f"Document type: {starter.get('title') or 'letter'}.",
    ]
    if title:
        bits.append(f"Working title: {title}.")
    bits.append("Writer request:")
    bits.append(utterance.strip())
    starter_html = (starter.get("bodyHtml") or "").strip()
    if starter_html:
        bits.append("Starter HTML to follow or fill:")
        bits.append(starter_html[:4000])
    compact = _compact_passages(passages)
    if compact:
        bits.append("Colony context (templates, Information Centre, meetings) — use only these facts:")
        for p in compact:
            bits.append(f"- {p.get('title')}: {(p.get('text') or '')[:500]}")
    bits.append(
        "Write the complete document body as HTML using <p>, <ol>, <ul>, <li>, <strong>, <em>, <br>. "
        "Do not wrap in <html> or add letterhead. Unknown facts stay as ________. "
        "Do not invent amounts, case numbers, or legal clauses."
    )
    return "\n".join(bits)[:12000]


def call_syntheon(
    cfg: dict[str, str],
    *,
    utterance: str,
    intent: dict[str, Any],
    starter: dict[str, Any],
    passages: list[dict[str, str]],
    title: str,
    current_html: str,
) -> dict[str, Any] | None:
    payload = {
        "kind": "document.compose",
        "format": "html",
        "tenant": "hbcsanyard",
        "utterance": utterance,
        "intent": intent,
        "title": title or intent.get("title") or "",
        "starterId": starter.get("id") or "",
        "templateHtml": (starter.get("bodyHtml") or "")[:8000],
        "currentHtml": (current_html or "")[:8000],
        "sources": _compact_passages(passages),
        "instructions": (
            "Write a complete Society document in simple HTML (<p>, <ol>, <ul>, "
            "<strong>, <em>, <br>). Fill facts from sources. Leave unknowns as "
            "________. Do not invent plot numbers, amounts, or legal citations."
        ),
    }
    return _post_first_ok(
        cfg["syntheonUrl"],
        SYNTHEON_PATHS,
        payload,
        api_key=cfg.get("syntheonKey") or "",
        timeout_ms=cfg.get("syntheonTimeoutMs") or "20000",
        default_timeout=20.0,
        cap=45.0,
    )


def _fallback_draft(
    cfg: dict[str, str],
    *,
    utterance: str,
    intent: dict[str, Any],
    starter: dict[str, Any],
    passages: list[dict[str, str]],
    title: str,
    current_html: str,
) -> tuple[str, str]:
    if not cfg.get("apiKey"):
        return "", ""
    context = "\n\n".join(
        f"[{p.get('title')}]\n{p.get('text')}" for p in passages if (p.get("text") or "").strip()
    ) or "(No matching colony records.)"
    starter_html = (starter.get("bodyHtml") or "<p></p>")[:6000]
    system = (
        "You draft official documents for Mandi Housing Welfare Society "
        "(Himuda Housing Colony Sanyard). Output HTML body fragments only "
        "(p, ol, ul, li, strong, em, br). No <html> or letterhead wrapper — "
        "the portal adds stationery. Use only the provided context. "
        "Keep Society names, registration no. 467 dated 21/07/2012, and office "
        "bearers when they appear in context. Unknown facts stay as ________. "
        "Do not invent amounts, case numbers, or legal clauses."
    )
    user = (
        f"Document type: {intent.get('docType') or starter.get('title')}\n"
        f"Suggested title: {title or intent.get('title') or ''}\n"
        f"Writer request:\n{utterance}\n\n"
        f"Starter HTML:\n{starter_html}\n\n"
        f"Current draft (optional):\n{(current_html or '')[:3000] or '(empty)'}\n\n"
        f"Colony context:\n{context}\n\n"
        "Return the filled HTML body only."
    )
    try:
        raw = rwa_ai_chat._chat_completions(
            cfg,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=1400,
        )
    except ValueError:
        return "", ""
    return _coerce_html(raw), "llm"


def _extractive_draft(
    utterance: str,
    starter: dict[str, Any],
    passages: list[dict[str, str]],
) -> str:
    base = sanitize_compose_html(starter.get("bodyHtml") or "<p></p>")
    facts: list[str] = []
    for p in passages[:4]:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        snippet = text.split("\n")[0][:280]
        title = html_lib.escape(str(p.get("title") or "Source"))
        facts.append(f"<li><strong>{title}:</strong> {html_lib.escape(snippet)}</li>")
    request = html_lib.escape(utterance.strip()[:800])
    extra = (
        "<p><strong>AI Assist notes (review before issuing):</strong></p>"
        f"<p>{request}</p>"
    )
    if facts:
        extra += "<ul>" + "".join(facts) + "</ul>"
    extra += (
        "<p><em>Drafted from colony templates, documents, and meetings. "
        "Replace blanks and verify names, dates, and figures.</em></p>"
    )
    if base in {"<p></p>", "<p>"}:
        return extra
    return f"{base}\n{extra}"


def _guess_starter(text: str) -> str:
    low = (text or "").lower()
    for starter_id, needles in _STARTER_HINTS:
        if any(n in low for n in needles):
            return starter_id
    if "minute" in low or "mom" in low:
        return "mom_ec"
    if "letter" in low:
        return "forwarding_letter"
    return "blank"


def _topic_from_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= 80:
        return cleaned
    return cleaned[:77] + "…"


def _suggested_title(starter: dict[str, Any], topic: str, text: str) -> str:
    prefix = (starter.get("suggestedTitle") or starter.get("title") or "").strip()
    hint = topic or _topic_from_text(text)
    if not prefix:
        return hint[:160] or "Untitled document"
    if prefix.endswith("—") or prefix.endswith("-"):
        return f"{prefix} {hint}".strip()[:160]
    if hint and hint.lower() not in prefix.lower():
        return f"{prefix} — {hint}"[:160]
    return prefix[:160]


def _merge_intent(base: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    blob = remote if isinstance(remote, dict) else {}
    nested = blob.get("intent") if isinstance(blob.get("intent"), dict) else None
    wish = blob.get("wish") if isinstance(blob.get("wish"), dict) else None
    understand = blob.get("understand") if isinstance(blob.get("understand"), dict) else None
    for layer in (blob, nested, wish, understand):
        if not isinstance(layer, dict):
            continue
        sid = str(layer.get("starterId") or layer.get("starter_id") or layer.get("docType") or "").strip().lower()
        if sid and starter_by_id(sid):
            out["starterId"] = sid
        title = str(layer.get("title") or layer.get("suggestedTitle") or "").strip()
        if title:
            out["title"] = title[:160]
        summary = str(layer.get("summary") or layer.get("utterance") or "").strip()
        if summary:
            out["summary"] = summary[:400]
        topic = str(layer.get("topic") or "").strip()
        if topic:
            out["topic"] = topic[:120]
    for item in blob.get("phases") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("phase") or "").lower() == "understand":
            summary = str(item.get("text") or "").strip()
            if summary:
                out["summary"] = summary[:400]
    out["source"] = "egenie" if blob else base.get("source")
    starter = starter_by_id(out.get("starterId") or "")
    if starter:
        out["docType"] = starter.get("title") or out.get("starterId")
    return out


def _html_from_remote(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    from_phases = _html_from_egenie_phases(data)
    if from_phases:
        return from_phases
    for key in ("htmlBody", "bodyHtml", "html", "content", "document", "answer", "text"):
        val = data.get(key)
        if isinstance(val, dict):
            inner = _html_from_remote(val)
            if inner:
                return inner
        elif isinstance(val, str) and _usable_model_text(val):
            return _coerce_html(val)
    for nested_key in ("act", "result", "output", "data", "wish"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            inner = _html_from_remote(nested)
            if inner:
                return inner
    return ""


def _html_from_egenie_phases(data: dict[str, Any]) -> str:
    phases = data.get("phases")
    if not isinstance(phases, list):
        return ""
    by_phase: dict[str, str] = {}
    for item in phases:
        if not isinstance(item, dict):
            continue
        name = str(item.get("phase") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        if name and _usable_model_text(text):
            by_phase[name] = text
    for name in ("act", "think", "understand"):
        if by_phase.get(name):
            return _coerce_html(by_phase[name])
    return ""


def _usable_model_text(raw: str) -> bool:
    text = (raw or "").strip()
    if not text:
        return False
    low = text.lower()
    if "model returned no text" in low:
        return False
    if low in {"(no text)", "n/a", "none"}:
        return False
    return True


def _title_from_remote(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("title", "suggestedTitle", "name"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:160]
    for nested_key in ("intent", "document", "result", "act", "output"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            found = _title_from_remote(nested)
            if found:
                return found
    return ""


def _coerce_html(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if "<" not in text:
        paras = [html_lib.escape(p.strip()) for p in re.split(r"\n\s*\n", text) if p.strip()]
        return "".join(f"<p>{p}</p>" for p in paras) or "<p></p>"
    return text


def _html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def _library_template_chunks(conn, site_root: pathlib.Path) -> list[dict[str, str]]:
    if conn is None:
        return []
    try:
        from rwa_templates import COMPOSE_BODY_STORE, template_item_dir
    except Exception:
        return []
    out: list[dict[str, str]] = []
    try:
        rows = conn.execute(
            """
            SELECT id, title, description, category, tags_json, options_json, status
            FROM print_templates
            WHERE status IN ('published', 'draft')
            ORDER BY updated_at DESC
            LIMIT 80
            """
        ).fetchall()
    except Exception:
        return []
    root = pathlib.Path(site_root)
    for row in rows:
        tid = str(row["id"] if hasattr(row, "keys") else row[0] or "")
        title = str(row["title"] if hasattr(row, "keys") else row[1] or "").strip()
        desc = str(row["description"] if hasattr(row, "keys") else row[2] or "").strip()
        body = ""
        try:
            path = template_item_dir(root, tid) / COMPOSE_BODY_STORE
            if path.is_file():
                body = _html_to_text(path.read_text(encoding="utf-8"))[:4000]
        except Exception:
            body = ""
        text = f"{title}. {desc}\n{body}".strip()
        if not text:
            continue
        out.append({
            "id": f"library:{tid}",
            "title": f"Template — {title or tid}",
            "text": text[:8000],
            "source": "template",
        })
    return out


def _passages_for_prompt(query: str, retrieved: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for chunk in retrieved[:8]:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        trimmed = rwa_ai_chat._trim_chunk_for_context(query, chunk, max_chars=420)
        out.append(trimmed)
    return out


def _compact_passages(passages: list[dict[str, str]]) -> list[dict[str, str]]:
    compact = []
    for p in passages[:8]:
        compact.append({
            "id": p.get("id") or "",
            "title": (p.get("title") or "")[:180],
            "source": p.get("source") or "",
            "text": (p.get("text") or "")[:800],
        })
    return compact


def _service_health(base_url: str, api_key: str, *, timeout_s: float) -> dict[str, Any]:
    url = (base_url or "").strip()
    if not url:
        return {"ok": False, "error": "not configured"}
    for path in ("/health", "/v1/health", "/"):
        try:
            data = _http_json(
                urljoin(url.rstrip("/") + "/", path.lstrip("/")),
                method="GET",
                api_key=api_key,
                timeout_s=timeout_s,
            )
            if data is None:
                continue
            if isinstance(data, dict) and data.get("ok") is False:
                continue
            return {"ok": True, "path": path}
        except Exception:
            continue
    return {"ok": False, "error": "unreachable"}


def _public_service_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme or 'http'}://{host}{port}"
    except Exception:
        return url


def _post_first_ok(
    base_url: str,
    paths: tuple[str, ...],
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout_ms: str,
    default_timeout: float,
    cap: float,
) -> dict[str, Any] | None:
    try:
        timeout_s = int(timeout_ms or 0) / 1000.0
    except ValueError:
        timeout_s = default_timeout
    timeout_s = max(0.8, min(timeout_s or default_timeout, cap))  # remote eGenie can take ~60–90s
    last_err: Exception | None = None
    for path in paths:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        try:
            data = _http_json(
                url,
                method="POST",
                payload=payload,
                api_key=api_key,
                timeout_s=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        if isinstance(data, dict) and data:
            if data.get("ok") is False and not _html_from_remote(data):
                continue
            return data
    if last_err:
        return None
    return None


def _http_json(
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    timeout_s: float = 8.0,
) -> dict[str, Any] | None:
    headers = {"Accept": "application/json"}
    data = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload or {}).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 405, 501}:
            return None
        body = exc.read().decode("utf-8", errors="ignore")[:400]
        raise ValueError(f"{url} ({exc.code}): {body}") from exc
    except Exception:
        return None
    if not raw.strip():
        return {"ok": True}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        if method == "GET":
            return {"ok": True, "raw": raw[:200]}
        return None
    if isinstance(parsed, dict):
        return parsed
    return None
