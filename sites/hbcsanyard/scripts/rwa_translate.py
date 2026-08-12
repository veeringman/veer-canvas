"""Lightweight EN↔HI translation for RWA portal content.

Uses Google's public translate endpoint (no API key) with MyMemory as fallback.
Intended for signed-in residents viewing/authoring bilingual overlays — not bulk OCR.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

_MAX_CHARS = 4500
_MAX_BATCH = 40
_UA = "HBCSanyardRWA/1.0 (+https://housingcolonysanyard.in)"


def normalize_lang(code: str | None) -> str:
    key = (code or "en").strip().lower()
    if key in {"hi", "hindi", "hin"}:
        return "hi"
    return "en"


def _chunk_text(text: str, limit: int = _MAX_CHARS) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    if len(raw) <= limit:
        return [raw]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"(\n\s*\n)", raw):
        if size + len(para) > limit and buf:
            parts.append("".join(buf).strip())
            buf = [para]
            size = len(para)
        else:
            buf.append(para)
            size += len(para)
    if buf:
        parts.append("".join(buf).strip())
    # Hard-split any leftover oversized chunk.
    out: list[str] = []
    for p in parts:
        if len(p) <= limit:
            if p:
                out.append(p)
            continue
        for i in range(0, len(p), limit):
            out.append(p[i : i + limit])
    return out


def _http_get_json(url: str, timeout: float = 12.0):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _translate_google(text: str, source: str, target: str) -> str:
    q = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": text,
        }
    )
    url = f"https://translate.googleapis.com/translate_a/single?{q}"
    data = _http_get_json(url)
    # Shape: [[[translated, original, ...], ...], ...]
    chunks = data[0] if isinstance(data, list) and data else []
    parts = []
    for row in chunks or []:
        if isinstance(row, list) and row and isinstance(row[0], str):
            parts.append(row[0])
    out = "".join(parts).strip()
    if not out:
        raise RuntimeError("Empty Google translation")
    return out


def _translate_mymemory(text: str, source: str, target: str) -> str:
    q = urllib.parse.urlencode(
        {
            "q": text[:500],
            "langpair": f"{source}|{target}",
        }
    )
    url = f"https://api.mymemory.translated.net/get?{q}"
    data = _http_get_json(url)
    out = ((data or {}).get("responseData") or {}).get("translatedText") or ""
    out = str(out).strip()
    if not out:
        raise RuntimeError("Empty MyMemory translation")
    # MyMemory sometimes echoes INVALID QUERY / rate limit messages
    if out.upper().startswith("MYMEMORY WARNING"):
        raise RuntimeError(out)
    return out


def translate_text(text: str, *, source: str = "en", target: str = "hi") -> str:
    src = normalize_lang(source)
    dst = normalize_lang(target)
    raw = (text or "").strip()
    if not raw:
        return ""
    if src == dst:
        return raw
    pieces = _chunk_text(raw)
    translated: list[str] = []
    for piece in pieces:
        try:
            translated.append(_translate_google(piece, src, dst))
        except Exception:
            translated.append(_translate_mymemory(piece, src, dst))
    return "\n\n".join(p for p in translated if p).strip()


def translate_batch(
    texts: Iterable[str],
    *,
    source: str = "en",
    target: str = "hi",
) -> list[dict]:
    """Translate up to _MAX_BATCH strings. Returns [{text, ok, error?}]."""
    src = normalize_lang(source)
    dst = normalize_lang(target)
    items = [str(t or "") for t in texts][:_MAX_BATCH]
    out: list[dict] = []
    for text in items:
        try:
            out.append({"text": translate_text(text, source=src, target=dst), "ok": True})
        except Exception as exc:
            out.append({"text": "", "ok": False, "error": str(exc)[:200]})
    return out
