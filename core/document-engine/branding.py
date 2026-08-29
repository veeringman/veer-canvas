"""Load society branding from site-meta.json for compose shells and stationery defaults."""

from __future__ import annotations

import html
import json
import pathlib
from typing import Any


def _cache_bust(path: str, meta: dict[str, Any]) -> str:
    if not path:
        return path
    if "?v=" in path or "&v=" in path:
        return path
    stamp = meta.get("lastUpdated") or meta.get("version") or ""
    if not stamp:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}v={stamp}"


def load_society_branding(site_root: pathlib.Path | str) -> dict[str, Any]:
    """Return normalized branding for compose simple shell and stationery defaults."""
    root = pathlib.Path(site_root).resolve()
    meta_path = root / "site-meta.json"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            parsed = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                meta = parsed
        except (OSError, json.JSONDecodeError):
            meta = {}

    compose = meta.get("composeBranding") if isinstance(meta.get("composeBranding"), dict) else {}
    society = str(meta.get("societyName") or compose.get("societyName") or "").strip()
    colony = str(
        meta.get("siteName")
        or meta.get("brandName")
        or compose.get("colonyName")
        or ""
    ).strip()
    origin = str(meta.get("publicOrigin") or compose.get("publicOrigin") or "").strip().rstrip("/")
    email = str(compose.get("email") or meta.get("email") or "").strip()
    address = str(compose.get("addressLine") or compose.get("address") or "").strip()
    footer = str(compose.get("footerLine") or compose.get("footer") or "").strip()
    if not footer and society:
        footer = society

    logo_print = _cache_bust(
        str(meta.get("logoPrint") or compose.get("logoPrint") or "/assets/favicon-192.png"),
        meta,
    )
    logo_wm = _cache_bust(
        str(meta.get("logoWatermark") or compose.get("logoWatermark") or logo_print),
        meta,
    )

    meta_bits: list[str] = []
    if address:
        meta_bits.append(address)
    if email:
        meta_bits.append(email)
    if origin:
        host = origin.replace("https://", "").replace("http://", "")
        if host and host not in " · ".join(meta_bits):
            meta_bits.append(host)
    meta_line = " · ".join(meta_bits)

    return {
        "societyName": society or colony or "Residents Welfare Association",
        "colonyName": colony or society or "Society",
        "addressLine": address,
        "email": email,
        "publicOrigin": origin,
        "metaLine": meta_line,
        "footerLine": footer,
        "logoPrint": logo_print if logo_print.startswith("/") else f"/{logo_print.lstrip('/')}",
        "logoWatermark": logo_wm if logo_wm.startswith("/") else f"/{logo_wm.lstrip('/')}",
    }


def simple_compose_shell_html(branding: dict[str, Any], body_html: str, page_margin: str) -> tuple[str, str, str]:
    """Return (header_inner_html, footer_html, logo_src) for the simple compose chrome."""
    society = branding.get("societyName") or "Society"
    colony = branding.get("colonyName") or society
    meta_line = branding.get("metaLine") or ""
    footer = branding.get("footerLine") or society
    logo = branding.get("logoPrint") or "/assets/favicon-192.png"
    header = (
        f"<header class=\"org\">"
        f"<img src=\"{html.escape(str(logo))}\" alt=\"\">"
        f"<h1>{html.escape(str(society))}</h1>"
        f"<p class=\"sub\">{html.escape(str(colony))}</p>"
    )
    if meta_line:
        header += f"<p class=\"meta\">{html.escape(str(meta_line))}</p>"
    header += "</header>"
    foot = f"<footer class=\"foot\">{html.escape(str(footer))}</footer>"
    return header, foot, logo
