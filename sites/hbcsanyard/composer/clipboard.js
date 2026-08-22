/**
 * Cut / copy / paste for the composer: OS clipboard (Ctrl/Cmd C X V),
 * paste from other apps, and toolbar actions.
 */
import { wrappedImageHtml } from './driver-dom.js';

const IMAGE_MAX = 1.2 * 1024 * 1024;
const ALLOWED = new Set([
  'P', 'BR', 'DIV', 'SPAN', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'STRIKE',
  'H1', 'H2', 'H3', 'H4', 'UL', 'OL', 'LI', 'TABLE', 'THEAD', 'TBODY', 'TR',
  'TD', 'TH', 'IMG', 'BLOCKQUOTE', 'A', 'SUP', 'SUB', 'HR', 'COLGROUP', 'COL',
]);
const ATTR_OK = new Set([
  'href', 'src', 'alt', 'colspan', 'rowspan', 'class', 'style',
  'data-width', 'data-float', 'contenteditable',
]);
const STYLE_OK = /^(color|background-color|font-size|font-family|font-weight|font-style|text-decoration|text-align|width|max-width|height|float|margin|margin-left|margin-right|margin-top|margin-bottom|display|vertical-align)$/i;

function emit(host) {
  host.dispatchEvent(new Event('input', { bubbles: true }));
}

function inHost(host) {
  const sel = window.getSelection();
  return Boolean(sel && sel.rangeCount && host.contains(sel.anchorNode));
}

function exec(cmd) {
  try {
    document.execCommand('styleWithCSS', false, true);
  } catch {
    /* older WebKit */
  }
  return document.execCommand(cmd, false, null);
}

export function copySelection(host) {
  if (host) host.focus();
  if (host && !inHost(host)) return false;
  if (exec('copy')) return true;
  const text = window.getSelection()?.toString() || '';
  if (!text || !navigator.clipboard?.writeText) return false;
  navigator.clipboard.writeText(text).catch(() => {});
  return true;
}

export function cutSelection(host) {
  if (host) host.focus();
  if (host && !inHost(host)) return false;
  if (exec('cut')) {
    emit(host);
    return true;
  }
  const sel = window.getSelection();
  const text = sel?.toString() || '';
  if (!sel || sel.isCollapsed) return false;
  const range = sel.getRangeAt(0);
  const write = navigator.clipboard?.writeText
    ? navigator.clipboard.writeText(text)
    : Promise.resolve();
  return write.then(() => {
    range.deleteContents();
    emit(host);
  }).then(() => true, () => false);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file || !/^image\//.test(file.type || '')) {
      reject(new Error('Not an image'));
      return;
    }
    if (file.size > IMAGE_MAX) {
      reject(new Error('Image is too large (max about 1.2 MB).'));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Could not read image.'));
    reader.readAsDataURL(file);
  });
}

function insertHtml(host, html) {
  host.focus();
  const ok = document.execCommand('insertHTML', false, html);
  if (!ok) {
    const sel = window.getSelection();
    if (sel && sel.rangeCount) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const frag = document.createDocumentFragment();
      while (tmp.firstChild) frag.appendChild(tmp.firstChild);
      range.insertNode(frag);
    }
  }
  emit(host);
}

function insertPlain(host, text) {
  const raw = String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (!raw) return;
  const esc = (s) => s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  const html = raw
    .split(/\n{2,}/)
    .map((block) => `<p>${esc(block).replace(/\n/g, '<br>')}</p>`)
    .join('');
  insertHtml(host, html || `<p>${esc(raw)}</p>`);
}

function cleanStyle(value) {
  return String(value || '')
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => STYLE_OK.test(part.split(':')[0] || ''))
    .join('; ');
}

function wrapLooseImages(root) {
  root.querySelectorAll('img').forEach((img) => {
    if (img.closest('.mhws-img')) return;
    const src = img.getAttribute('src') || '';
    if (!src || src.startsWith('javascript:')) {
      img.remove();
      return;
    }
    const wrap = document.createElement('span');
    wrap.className = 'mhws-img';
    wrap.contentEditable = 'false';
    wrap.dataset.width = '40';
    wrap.dataset.float = 'none';
    wrap.setAttribute('style', 'width:40%;max-width:100%;display:inline-block;vertical-align:middle;margin:0 6pt 4pt 0');
    img.removeAttribute('width');
    img.removeAttribute('height');
    img.draggable = false;
    img.style.width = '100%';
    img.style.height = 'auto';
    img.style.display = 'block';
    img.replaceWith(wrap);
    wrap.append(img);
  });
}

export function sanitizePastedHtml(html) {
  const raw = String(html || '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<\/?(o:|v:|w:)[^>]*>/gi, '');
  const doc = new DOMParser().parseFromString(raw, 'text/html');
  doc.querySelectorAll('script, style, meta, link, xml, noscript, iframe, object, embed').forEach((n) => n.remove());
  const walk = (node) => {
    [...node.childNodes].forEach((child) => {
      if (child.nodeType === Node.COMMENT_NODE) {
        child.remove();
        return;
      }
      if (child.nodeType !== Node.ELEMENT_NODE) return;
      const tag = child.tagName;
      if (!ALLOWED.has(tag)) {
        const parent = child.parentNode;
        while (child.firstChild) parent.insertBefore(child.firstChild, child);
        child.remove();
        return;
      }
      [...child.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        if (name.startsWith('on') || name === 'srcdoc') {
          child.removeAttribute(attr.name);
          return;
        }
        if (!ATTR_OK.has(name)) {
          child.removeAttribute(attr.name);
          return;
        }
        if (name === 'href' && /^\s*javascript:/i.test(attr.value || '')) {
          child.removeAttribute(attr.name);
          return;
        }
        if (name === 'src' && /^\s*javascript:/i.test(attr.value || '')) {
          child.removeAttribute(attr.name);
          return;
        }
        if (name === 'style') {
          const next = cleanStyle(attr.value);
          if (next) child.setAttribute('style', next);
          else child.removeAttribute('style');
        }
        if (name === 'class') {
          const keep = String(attr.value || '')
            .split(/\s+/)
            .filter((c) => c === 'mhws-img' || c === 'mhws-table');
          if (keep.length) child.setAttribute('class', keep.join(' '));
          else child.removeAttribute('class');
        }
      });
      walk(child);
    });
  };
  walk(doc.body);
  wrapLooseImages(doc.body);
  return (doc.body.innerHTML || '').trim();
}

function fileFromClipboard(cd) {
  if (cd?.files?.length) {
    const hit = [...cd.files].find((f) => /^image\//.test(f.type || ''));
    if (hit) return hit;
  }
  const items = cd?.items;
  if (!items) return null;
  for (const item of items) {
    if (item.kind === 'file' && /^image\//.test(item.type || '')) {
      return item.getAsFile();
    }
  }
  return null;
}

function applyClipboardData(host, cd) {
  const file = fileFromClipboard(cd);
  if (file) {
    readFileAsDataUrl(file)
      .then((src) => insertHtml(host, wrappedImageHtml(src)))
      .catch((err) => window.alert(err.message || 'Image paste failed'));
    return true;
  }
  const html = cd?.getData?.('text/html') || '';
  const text = cd?.getData?.('text/plain') || '';
  if (html && /<(p|div|span|table|ul|ol|h[1-6]|img|br|b|strong|i|em)\b/i.test(html)) {
    const clean = sanitizePastedHtml(html);
    if (clean) {
      insertHtml(host, clean);
      return true;
    }
  }
  if (text) {
    insertPlain(host, text);
    return true;
  }
  return false;
}

export async function pasteFromClipboard(host) {
  if (!host) return false;
  host.focus();
  try {
    if (navigator.clipboard?.read) {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const types = item.types || [];
        const imageType = types.find((t) => t.startsWith('image/'));
        if (imageType) {
          const blob = await item.getType(imageType);
          const src = await readFileAsDataUrl(new File([blob], 'paste.png', { type: imageType }));
          insertHtml(host, wrappedImageHtml(src));
          return true;
        }
        if (types.includes('text/html')) {
          const html = await (await item.getType('text/html')).text();
          const clean = sanitizePastedHtml(html);
          if (clean) {
            insertHtml(host, clean);
            return true;
          }
        }
        if (types.includes('text/plain')) {
          const text = await (await item.getType('text/plain')).text();
          insertPlain(host, text);
          return true;
        }
      }
    }
  } catch {
    /* permission or Safari — fall through */
  }
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      insertPlain(host, text);
      return true;
    }
  } catch {
    /* ignore */
  }
  if (exec('paste')) {
    emit(host);
    return true;
  }
  window.alert('Use Ctrl+V (or Cmd+V) to paste.');
  return false;
}

export function attachClipboard(host) {
  if (!host) return { destroy() {} };

  const onPaste = (event) => {
    const cd = event.clipboardData;
    if (!cd) return;
    const hasFile = Boolean(fileFromClipboard(cd));
    const hasHtml = Boolean(cd.getData?.('text/html'));
    const hasText = Boolean(cd.getData?.('text/plain'));
    if (!hasFile && !hasHtml && !hasText) return;
    event.preventDefault();
    event.stopPropagation();
    applyClipboardData(host, cd);
  };

  const onCopy = (event) => {
    if (!inHost(host)) return;
    event.stopPropagation();
  };

  const onCut = (event) => {
    if (!inHost(host)) return;
    event.stopPropagation();
    window.setTimeout(() => emit(host), 0);
  };

  const onKey = (event) => {
    const mod = event.metaKey || event.ctrlKey;
    if (!mod || event.altKey) return;
    const key = String(event.key || '').toLowerCase();
    if (key === 'c') {
      event.stopPropagation();
      return;
    }
    if (key === 'x') {
      event.stopPropagation();
      return;
    }
    if (key === 'v') {
      event.stopPropagation();
    }
  };

  host.addEventListener('paste', onPaste);
  host.addEventListener('copy', onCopy);
  host.addEventListener('cut', onCut);
  host.addEventListener('keydown', onKey, true);

  return {
    destroy() {
      host.removeEventListener('paste', onPaste);
      host.removeEventListener('copy', onCopy);
      host.removeEventListener('cut', onCut);
      host.removeEventListener('keydown', onKey, true);
    },
  };
}
