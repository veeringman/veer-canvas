"""Compose export helpers — HTML fragment to text / Word, pad body injection."""

from __future__ import annotations

import base64
import io
import pathlib
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any


def _html_escape(text: Any) -> str:
    s = "" if text is None else str(text)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

COMPOSE_PAD_BODY_CSS = """
<style id="mhws-compose-body">
  .screen-hint, .layout-picker { display: none !important; }
  .body-area p { margin: 0 0 8pt; }
  .body-area h2 { margin: 0 0 8pt; font-size: 13pt; color: #0b2a56; }
  .body-area h3 { margin: 0 0 6pt; font-size: 12pt; color: #0b2a56; }
  .body-area table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
  .body-area th, .body-area td { border: 0.6pt solid #0b2a56; padding: 4pt 6pt; vertical-align: top; }
  .body-area th { background: #eef2f8; }
  .body-area img { max-width: 100%; height: auto; }
  .body-area .mhws-img { max-width: 100%; }
  .body-area .mhws-img img { width: 100%; height: auto; display: block; }
  .brand .logo, header.org img, .org img {
    display: block;
    width: 24mm;
    height: auto;
    visibility: visible;
  }
  img.wm { display: block; }
  @media print {
    body { background: #fff !important; }
    .sheet { margin: 0 !important; border: 0 !important; box-shadow: none !important; }
  }
</style>
"""

COMPOSE_PDF_CSS = """
<style id="mhws-compose-pdf">
  @page { size: A4 portrait; margin: 0; }
  html, body {
    background: #fff !important;
    width: 210mm !important;
    margin: 0 !important;
  }
  .screen-hint, .layout-picker { display: none !important; }
  .sheet {
    width: 210mm !important;
    min-height: 297mm !important;
    height: auto !important;
    max-height: none !important;
    margin: 0 !important;
    border: 0 !important;
    overflow: visible !important;
    box-shadow: none !important;
  }
  .pad { overflow: visible !important; max-height: none !important; }
  .body-area {
    min-height: 40mm !important;
    max-height: none !important;
    overflow: visible !important;
  }
  .foot, footer.foot { position: relative !important; }
</style>
"""


def inject_compose_pdf_css(html: str) -> str:
    if not html:
        return html
    if "</head>" in html:
        return html.replace("</head>", COMPOSE_PDF_CSS + "\n</head>", 1)
    return COMPOSE_PDF_CSS + html

_BODY_AREA_RE = re.compile(
    r'(<div\b[^>]*\bbody-area\b[^>]*>)(.*?)(</div>)',
    re.I | re.S,
)
_SCREEN_HINT_RE = re.compile(r'<p\s+class=["\']screen-hint["\'][\s\S]*?</p>', re.I)
_DATA_URI_RE = re.compile(
    r"^data:image/(png|jpe?g|gif|webp|svg\+xml);base64,(.+)$",
    re.I | re.S,
)


def as_bool(raw: Any, default: bool = True) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    return str(raw).strip().lower() not in {"", "0", "false", "no", "off", "none"}


def inject_body_area(pad_html: str, body: str) -> str | None:
    match = _BODY_AREA_RE.search(pad_html or "")
    if not match:
        return None
    return pad_html[: match.start()] + match.group(1) + body + match.group(3) + pad_html[match.end() :]


def strip_screen_chrome(html: str) -> str:
    return _SCREEN_HINT_RE.sub("", html or "", count=1)


def rewrite_pad_urls(html: str) -> str:
    text = html or ""
    text = text.replace("../assets/", "/assets/")
    text = re.sub(r"""(\s(?:src|href)=["'])assets/""", r"\1/assets/", text, flags=re.I)
    return text


def set_html_title(html: str, title: str) -> str:
    heading = _html_escape((title or "Document").strip() or "Document")
    if re.search(r"<title\b", html or "", re.I):
        return re.sub(r"<title>[^<]*</title>", f"<title>{heading}</title>", html, count=1, flags=re.I)
    if "</head>" in (html or ""):
        return html.replace("</head>", f"<title>{heading}</title>\n</head>", 1)
    return html


def html_fragment_to_text(body_html: str) -> str:
    from rwa_templates import sanitize_compose_html

    html = sanitize_compose_html(body_html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|h[1-6]|li|blockquote|tr|div)>", "\n", html)
    html = re.sub(r"(?i)</t[dh]>", "\t", html)
    html = re.sub(r"(?i)<hr\s*/?>", "\n---\n", html)
    html = re.sub(r"(?i)<img\b[^>]*>", "[image]\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = unescape(html).replace("\xa0", " ").replace("&nbsp;", " ")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in html.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _parse_width_pct(style: str, default: int = 40) -> int:
    match = re.search(r"width\s*:\s*(\d+(?:\.\d+)?)\s*%", style or "", re.I)
    if not match:
        return default
    try:
        pct = int(round(float(match.group(1))))
    except ValueError:
        return default
    return max(10, min(100, pct))


def _image_bytes_from_src(src: str, site_root: pathlib.Path | None) -> tuple[bytes, str] | None:
    raw = (src or "").strip()
    if not raw:
        return None
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    data = _DATA_URI_RE.match(raw)
    if data:
        kind = data.group(1).lower()
        try:
            blob = base64.b64decode(data.group(2), validate=False)
        except Exception:
            return None
        ext = "jpg" if kind.startswith("jp") else ("png" if "png" in kind else ("gif" if "gif" in kind else "png"))
        return blob, ext
    if site_root is None:
        return None
    cleaned = raw.replace("\\", "/")
    while cleaned.startswith("../"):
        cleaned = cleaned[3:]
    cleaned = cleaned.lstrip("./")
    if cleaned.startswith("/"):
        cleaned = cleaned.lstrip("/")
    if not cleaned.startswith("assets/") and not cleaned.startswith("documents/"):
        if raw.startswith("/") or raw.startswith("../"):
            pass
        else:
            return None
    path = (pathlib.Path(site_root) / cleaned).resolve()
    root = pathlib.Path(site_root).resolve()
    if str(path).startswith(str(root)) and path.is_file():
        return path.read_bytes(), path.suffix.lstrip(".").lower() or "png"
    return None


_SRC_ATTR_RE = re.compile(r"""(\ssrc\s*=\s*)(['"])([^'"]+)\2""", re.I)
_BASE_TAG_RE = re.compile(r"<base\b[^>]*/?>", re.I)
_ASSET_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}


def strip_base_tag(html: str) -> str:
    return _BASE_TAG_RE.sub("", html or "", count=1)


def embed_local_asset_urls(
    html: str,
    site_root: pathlib.Path | None,
    *,
    max_bytes: int = 1_800_000,
) -> str:
    """Inline local /assets images so blob preview and PDF both see the logo."""
    if not html or site_root is None:
        return html

    def repl(match: re.Match[str]) -> str:
        prefix, quote, src = match.group(1), match.group(2), match.group(3)
        if (src or "").startswith(("data:", "http:", "https:", "blob:")):
            return match.group(0)
        got = _image_bytes_from_src(src, site_root)
        if not got:
            return match.group(0)
        blob, ext = got
        if len(blob) > max_bytes:
            return match.group(0)
        mime = _ASSET_MIME.get(ext, "image/png")
        return f"{prefix}{quote}data:{mime};base64,{base64.b64encode(blob).decode('ascii')}{quote}"

    return _SRC_ATTR_RE.sub(repl, html)


def _picture_stream(blob: bytes, ext: str) -> io.BytesIO | None:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return io.BytesIO(blob) if ext in {"png", "jpg", "jpeg", "gif"} else None
    try:
        im = Image.open(io.BytesIO(blob))
        if im.mode not in {"RGB", "L"}:
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="PNG")
        out.seek(0)
        return out
    except Exception:
        return None


class _DocxBuilder(HTMLParser):
    def __init__(self, document, *, usable_mm: float, site_root: pathlib.Path | None):
        super().__init__(convert_charrefs=True)
        self.doc = document
        self.usable_mm = usable_mm
        self.site_root = site_root
        self.skip_stack: list[str] = []
        self.bold = 0
        self.italic = 0
        self.underline = 0
        self.para = None
        self.in_table = 0
        self.rows: list[list[str]] = []
        self.cur_row: list[str] | None = None
        self.td_bits: list[str] | None = None
        self.img_width_pct = 40
        self.class_stack: list[str] = []

    def _classes(self, raw: str) -> set[str]:
        return {c for c in (raw or "").split() if c}

    def _has_class(self, name: str) -> bool:
        return any(name in item.split() for item in self.class_stack)

    def _ensure_para(self):
        if self.in_table:
            return
        if self.para is None:
            self.para = self.doc.add_paragraph()

    def _add_run(self, text: str):
        if self.td_bits is not None:
            self.td_bits.append(text)
            return
        self._ensure_para()
        run = self.para.add_run(text)
        run.bold = self.bold > 0 or self._has_class("title") or self._has_class("name")
        run.italic = self.italic > 0
        run.underline = self.underline > 0

    def _add_picture(self, src: str, width_pct: int | None = None, width_mm: float | None = None):
        from docx.shared import Mm

        got = _image_bytes_from_src(src, self.site_root)
        if not got:
            if self.td_bits is not None:
                self.td_bits.append("[image]")
            return
        blob, ext = got
        stream = _picture_stream(blob, ext)
        if stream is None:
            return
        if width_mm is None:
            pct = width_pct if width_pct is not None else self.img_width_pct
            width_mm = max(18.0, min(self.usable_mm, self.usable_mm * (pct / 100.0)))
        if self.in_table:
            return
        self._ensure_para()
        try:
            self.para.add_run().add_picture(stream, width=Mm(width_mm))
        except Exception:
            pass

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs}
        classes = self._classes(ad.get("class", ""))
        if self.skip_stack:
            return
        if tag in {"script", "style", "head", "svg", "noscript"} or classes & {
            "screen-hint",
            "layout-picker",
            "accent-edge",
            "accent-edge-thin",
        }:
            self.skip_stack.append(tag)
            return
        if tag not in {"img", "br", "hr", "meta", "link", "input", "col"}:
            self.class_stack.append(ad.get("class", ""))
        if tag in {"b", "strong"}:
            self.bold += 1
        elif tag in {"i", "em"}:
            self.italic += 1
        elif tag == "u":
            self.underline += 1
        elif tag == "br":
            if self.td_bits is not None:
                self.td_bits.append("\n")
            elif self.para is not None:
                self.para.add_run("\n")
        elif tag in {"p", "h1", "h2", "h3", "blockquote", "header", "footer"}:
            if not self.in_table:
                self.para = self.doc.add_paragraph()
                if tag in {"h1", "h2", "header", "footer"} or classes & {"brand", "org", "foot"}:
                    try:
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        self.para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    except Exception:
                        pass
        elif tag == "li":
            if not self.in_table:
                self.para = self.doc.add_paragraph()
                self._add_run("• ")
        elif tag == "div" and classes & {"role", "contact"}:
            if not self.in_table:
                self.para = self.doc.add_paragraph()
        elif tag == "table":
            self.in_table += 1
            self.rows = []
            self.cur_row = None
            self.para = None
        elif tag == "tr":
            self.cur_row = []
        elif tag in {"td", "th"}:
            self.td_bits = []
        elif tag == "span" and "mhws-img" in classes:
            self.img_width_pct = _parse_width_pct(ad.get("style", ""), default=int(ad.get("data-width") or 40) or 40)
        elif tag == "img":
            if "wm" in classes:
                return
            src = ad.get("src") or ""
            if "logo" in classes or "seal" in classes or self._has_class("org") or self._has_class("brand"):
                self._add_picture(src, width_mm=22.0)
                return
            width = self.img_width_pct
            style_w = _parse_width_pct(ad.get("style", ""), default=0)
            if style_w:
                width = style_w
            self._add_picture(src, width)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self.skip_stack:
            if self.skip_stack[-1] == tag:
                self.skip_stack.pop()
            return
        if tag in {"b", "strong"}:
            self.bold = max(0, self.bold - 1)
        elif tag in {"i", "em"}:
            self.italic = max(0, self.italic - 1)
        elif tag == "u":
            self.underline = max(0, self.underline - 1)
        elif tag in {"p", "h1", "h2", "h3", "blockquote", "li", "header", "footer"}:
            self.para = None
        elif tag == "span" and self._has_class("title"):
            self._add_run(" — ")
        elif tag in {"td", "th"}:
            text = unescape("".join(self.td_bits or [])).strip()
            if self.cur_row is not None:
                self.cur_row.append(text)
            self.td_bits = None
        elif tag == "tr":
            if self.cur_row is not None:
                self.rows.append(self.cur_row)
            self.cur_row = None
        elif tag == "table":
            self.in_table = max(0, self.in_table - 1)
            rows = self.rows
            self.rows = []
            if rows:
                cols = max(len(r) for r in rows)
                table = self.doc.add_table(rows=len(rows), cols=max(1, cols))
                try:
                    table.style = "Table Grid"
                except Exception:
                    pass
                for i, row in enumerate(rows):
                    for j in range(cols):
                        table.rows[i].cells[j].text = row[j] if j < len(row) else ""
            self.para = None
        elif tag == "span":
            self.img_width_pct = 40
        if self.class_stack:
            self.class_stack.pop()

    def handle_data(self, data: str):
        if self.skip_stack:
            return
        text = data.replace("\xa0", " ")
        if not text or (not text.strip() and text != " "):
            if text == " ":
                self._add_run(" ")
            return
        self._add_run(text)


def wrapped_html_to_docx_bytes(*, html: str, site_root: pathlib.Path | None = None) -> bytes:
    try:
        from docx import Document  # type: ignore
        from docx.shared import Mm
    except Exception as exc:
        raise ValueError("Word export needs python-docx on the server.") from exc

    from rwa_templates import parse_doc_margins_mm

    margins = parse_doc_margins_mm(html)
    doc = Document()
    section = doc.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    left = max(12.0, margins["left"] * 0.6)
    right = max(12.0, margins["right"] * 0.6)
    section.top_margin = Mm(max(10.0, margins["top"] * 0.6))
    section.right_margin = Mm(right)
    section.bottom_margin = Mm(max(10.0, margins["bottom"] * 0.6))
    section.left_margin = Mm(left)
    usable = 210.0 - left - right

    builder = _DocxBuilder(doc, usable_mm=usable, site_root=site_root)
    builder.feed(html or "")
    builder.close()

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def html_fragment_to_docx_bytes(
    *,
    title: str,
    body_html: str,
    site_root: pathlib.Path | None = None,
) -> bytes:
    """Back-compat: wrap a fragment in a minimal heading then convert."""
    heading = _html_escape((title or "").strip())
    html = f"<html><body><h1>{heading}</h1>{body_html or ''}</body></html>"
    return wrapped_html_to_docx_bytes(html=html, site_root=site_root)


def export_filename(title: str, suffix: str) -> str:
    from rwa_templates import _safe_attach_name

    return _safe_attach_name(title or "document", suffix)

