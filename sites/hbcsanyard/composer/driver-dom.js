/**
 * DOM EditorDriver — contenteditable + CSS styling.
 * Same command ids as formats.js. Replace this file with a TipTap/ProseMirror
 * driver later; session.js only depends on this shape.
 */
const FONT_SIZE_MAP = {
  1: '8pt',
  2: '10pt',
  3: '12pt',
  4: '14pt',
  5: '18pt',
  6: '24pt',
  7: '32pt',
};

function exec(cmd, value = null) {
  try {
    document.execCommand('styleWithCSS', false, true);
  } catch {
    /* older WebKit */
  }
  return document.execCommand(cmd, false, value);
}

function emitInput(host) {
  host.dispatchEvent(new Event('input', { bubbles: true }));
}

const MARGIN_MARK = /<!--mhws-margins:([\d.]+),([\d.]+),([\d.]+),([\d.]+)-->/;
const DEFAULT_PAGE_MARGINS = { top: 16, right: 16, bottom: 16, left: 16 };

function clampMm(value, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(50, Math.round(n * 10) / 10));
}

export function parsePageMargins(html) {
  const hit = String(html || '').match(MARGIN_MARK);
  if (!hit) return { ...DEFAULT_PAGE_MARGINS };
  return {
    top: clampMm(hit[1], 16),
    right: clampMm(hit[2], 16),
    bottom: clampMm(hit[3], 16),
    left: clampMm(hit[4], 16),
  };
}

export function stripPageMargins(html) {
  return String(html || '').replace(MARGIN_MARK, '');
}

function readPageMargins(host) {
  return {
    top: clampMm(host.dataset.mhwsMt, DEFAULT_PAGE_MARGINS.top),
    right: clampMm(host.dataset.mhwsMr, DEFAULT_PAGE_MARGINS.right),
    bottom: clampMm(host.dataset.mhwsMb, DEFAULT_PAGE_MARGINS.bottom),
    left: clampMm(host.dataset.mhwsMl, DEFAULT_PAGE_MARGINS.left),
  };
}

function applyPageMargins(host, spec = {}) {
  const cur = readPageMargins(host);
  const next = {
    top: clampMm(spec.top, cur.top),
    right: clampMm(spec.right, cur.right),
    bottom: clampMm(spec.bottom, cur.bottom),
    left: clampMm(spec.left, cur.left),
  };
  host.dataset.mhwsMt = String(next.top);
  host.dataset.mhwsMr = String(next.right);
  host.dataset.mhwsMb = String(next.bottom);
  host.dataset.mhwsMl = String(next.left);
  if (!host.classList.contains('is-paged')) {
    host.style.padding = `${next.top}mm ${next.right}mm ${next.bottom}mm ${next.left}mm`;
  }
  return next;
}

function currentBlock(root) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !root.contains(sel.anchorNode)) return null;
  let node = sel.anchorNode;
  if (node.nodeType === Node.TEXT_NODE) node = node.parentElement;
  return node;
}

function closestEditableBlock(root) {
  let node = currentBlock(root);
  while (node && node !== root) {
    const tag = node.tagName;
    if (tag && /^(P|H1|H2|H3|H4|LI|BLOCKQUOTE|TD|TH|DIV)$/.test(tag)) return node;
    node = node.parentElement;
  }
  return null;
}

const BLOCK_TAGS = {
  paragraph: 'P',
  p: 'P',
  h2: 'H2',
  h3: 'H3',
  blockquote: 'BLOCKQUOTE',
};

function selectedTextBlocks(root) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !root.contains(sel.anchorNode)) return [];
  if (sel.isCollapsed) return [];
  const range = sel.getRangeAt(0);
  return [...root.querySelectorAll('p, h2, h3, h4, li, blockquote')].filter((el) => {
    try {
      return range.intersectsNode(el);
    } catch {
      return false;
    }
  });
}

function applyBlockStyle(root, kind) {
  const tag = BLOCK_TAGS[String(kind || 'paragraph')] || 'P';
  const name = tag.toLowerCase();
  exec('formatBlock', name);
  exec('formatBlock', `<${name}>`);
  let block = closestEditableBlock(root);
  if (block && /^(LI|TD|TH)$/.test(block.tagName)) {
    return true;
  }
  if (block && block.tagName !== tag) {
    const next = document.createElement(name);
    next.innerHTML = block.innerHTML || '<br>';
    if (block.style.marginLeft) next.style.marginLeft = block.style.marginLeft;
    if (block.style.lineHeight) next.style.lineHeight = block.style.lineHeight;
    block.replaceWith(next);
    block = next;
    const range = document.createRange();
    range.selectNodeContents(block);
    range.collapse(true);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }
  if (block && (tag === 'H2' || tag === 'H3')) {
    block.querySelectorAll('[style]').forEach((el) => {
      el.style.fontSize = '';
      el.style.fontWeight = '';
    });
  }
  emitInput(root);
  return true;
}

function applyLineHeight(root, raw) {
  const value = String(raw || '').trim();
  if (!value) return false;
  const selected = selectedTextBlocks(root);
  const targets = selected.length
    ? selected
    : [root, ...root.querySelectorAll('p, h2, h3, h4, li, blockquote')];
  targets.forEach((el) => {
    el.style.lineHeight = value;
  });
  if (!selected.length) root.dataset.mhwsLh = value;
  emitInput(root);
  return true;
}

function indentBlock(root, out) {
  let block = closestEditableBlock(root);
  if (!block) {
    if (!root.firstElementChild) root.innerHTML = '<p></p>';
    block = root.querySelector('p, h2, h3, li, div') || root.firstElementChild;
  }
  if (!block) return false;
  if (block.tagName === 'LI') {
    return exec(out ? 'outdent' : 'indent');
  }
  const step = 36;
  const cur = Number.parseFloat(block.style.marginLeft) || 0;
  const next = Math.max(0, cur + (out ? -step : step));
  block.style.marginLeft = next ? `${next}pt` : '';
  return true;
}

function rangeInHost(host, range) {
  try {
    const node = range.commonAncestorContainer;
    return host === node || host.contains(node);
  } catch {
    return false;
  }
}

function collectSplitTextNodes(range) {
  const ancestor = range.commonAncestorContainer;
  const scope = ancestor.nodeType === Node.TEXT_NODE ? ancestor.parentNode : ancestor;
  if (!scope) return [];
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.data) return NodeFilter.FILTER_REJECT;
      if (node.parentElement?.closest('[contenteditable="false"]')) return NodeFilter.FILTER_REJECT;
      try {
        return range.intersectsNode(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      } catch {
        return NodeFilter.FILTER_REJECT;
      }
    },
  });
  const raw = [];
  while (walker.nextNode()) raw.push(walker.currentNode);
  const pieces = [];
  for (let i = raw.length - 1; i >= 0; i -= 1) {
    const node = raw[i];
    let from = 0;
    let to = node.data.length;
    if (node === range.startContainer) from = range.startOffset;
    if (node === range.endContainer) to = range.endOffset;
    if (from < 0) from = 0;
    if (to > node.data.length) to = node.data.length;
    if (from >= to) continue;
    let piece = node;
    if (to < piece.data.length) piece.splitText(to);
    if (from > 0) piece = piece.splitText(from);
    if (piece.data) pieces.push(piece);
  }
  pieces.reverse();
  return pieces;
}

function canReuseSpan(el) {
  if (!el || el.tagName !== 'SPAN') return false;
  if (el.className && el.className !== 'mhws-type') return false;
  if (el.contentEditable === 'false') return false;
  return el.childNodes.length === 1;
}

function wrapTextNode(node, styles) {
  const parent = node.parentElement;
  if (canReuseSpan(parent)) {
    Object.assign(parent.style, styles);
    return parent;
  }
  const span = document.createElement('span');
  span.className = 'mhws-type';
  Object.assign(span.style, styles);
  parent.insertBefore(span, node);
  span.appendChild(node);
  return span;
}

function clearDescendantStyles(span, styles) {
  span.querySelectorAll('[style]').forEach((el) => {
    Object.keys(styles).forEach((key) => {
      el.style[key] = '';
    });
    if (el.tagName === 'FONT') {
      if (styles.fontSize) el.removeAttribute('size');
      if (styles.fontFamily) el.removeAttribute('face');
    }
  });
}

function selectNodes(nodes) {
  if (!nodes.length) return;
  const sel = window.getSelection();
  const range = document.createRange();
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  range.setStart(first, 0);
  range.setEnd(last, last.nodeType === Node.TEXT_NODE ? last.data.length : last.childNodes.length);
  sel.removeAllRanges();
  sel.addRange(range);
}

function applyInlineStyles(root, styles) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);
  if (!rangeInHost(root, range)) return false;
  if (range.collapsed) {
    const span = document.createElement('span');
    span.className = 'mhws-type';
    Object.assign(span.style, styles);
    span.appendChild(document.createTextNode('\u200b'));
    range.insertNode(span);
    const next = document.createRange();
    next.setStart(span.firstChild, 1);
    next.collapse(true);
    sel.removeAllRanges();
    sel.addRange(next);
    emitInput(root);
    return true;
  }
  const nodes = collectSplitTextNodes(range);
  if (!nodes.length) return false;
  const spans = nodes.map((node) => wrapTextNode(node, styles));
  spans.forEach((span) => clearDescendantStyles(span, styles));
  selectNodes(nodes);
  emitInput(root);
  return true;
}

function normalizeFontSize(raw) {
  const size = String(raw || '').trim();
  if (!size) return '';
  if (/^[1-7]$/.test(size)) return FONT_SIZE_MAP[size] || '';
  if (/^\d+(\.\d+)?$/.test(size)) return `${size}pt`;
  return size;
}

function deepestTextEnd(node) {
  if (!node) return null;
  if (node.nodeType === Node.TEXT_NODE) {
    return node.data.replace(/[\u200b]/g, '').length ? node : null;
  }
  for (let i = node.childNodes.length - 1; i >= 0; i -= 1) {
    const found = deepestTextEnd(node.childNodes[i]);
    if (found) return found;
  }
  return null;
}

function placeCaret(node, offset) {
  const sel = window.getSelection();
  const range = document.createRange();
  const max = node.nodeType === Node.TEXT_NODE ? node.data.length : node.childNodes.length;
  const at = Math.max(0, Math.min(offset, max));
  range.setStart(node, at);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

/**
 * Chrome skips characters and eats <br>/paragraphs when the editable host
 * is a flex item (fixed by wrapping the paper). Strip zero-width markers
 * so Backspace can delete the previous visible character on the line.
 */
function insertTabAtCaret(root) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !root.contains(sel.anchorNode)) return false;
  const range = sel.getRangeAt(0);
  range.collapse(true);
  const span = document.createElement('span');
  span.className = 'mhws-tab';
  span.appendChild(document.createTextNode('\t'));
  range.insertNode(span);
  const after = document.createRange();
  after.setStartAfter(span);
  after.collapse(true);
  sel.removeAllRanges();
  sel.addRange(after);
  emitInput(root);
  return true;
}

function deleteTabBeforeCaret(root) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !sel.isCollapsed || !root.contains(sel.anchorNode)) return false;
  const range = sel.getRangeAt(0);
  let node = range.startContainer;
  let offset = range.startOffset;
  if (node.nodeType === Node.ELEMENT_NODE && offset > 0) {
    const prev = node.childNodes[offset - 1];
    if (prev?.nodeType === Node.ELEMENT_NODE && prev.classList.contains('mhws-tab')) {
      prev.remove();
      emitInput(root);
      return true;
    }
    if (prev?.nodeType === Node.TEXT_NODE) {
      node = prev;
      offset = prev.data.length;
    }
  }
  if (node.nodeType === Node.TEXT_NODE) {
    if (offset > 0 && node.data.charAt(offset - 1) === '\t') {
      node.deleteData(offset - 1, 1);
      placeCaret(node, offset - 1);
      emitInput(root);
      return true;
    }
    if (node.parentElement?.classList.contains('mhws-tab')) {
      const span = node.parentElement;
      const parent = span.parentNode;
      const idx = [...parent.childNodes].indexOf(span);
      span.remove();
      if (parent.childNodes[idx]) placeCaret(parent.childNodes[idx], 0);
      else placeCaret(parent, idx);
      emitInput(root);
      return true;
    }
  }
  return false;
}

function handleBackspace(root, event) {
  if (event.altKey || event.ctrlKey || event.metaKey) return false;
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount || !root.contains(sel.anchorNode)) return false;
  if (!sel.isCollapsed) return false;

  const range = sel.getRangeAt(0);
  let node = range.startContainer;
  let offset = range.startOffset;

  if (node.nodeType === Node.ELEMENT_NODE && offset > 0) {
    const prev = node.childNodes[offset - 1];
    if (prev?.nodeType === Node.TEXT_NODE) {
      node = prev;
      offset = prev.data.length;
    } else if (prev?.nodeType === Node.ELEMENT_NODE) {
      const text = deepestTextEnd(prev);
      if (text) {
        node = text;
        offset = text.data.length;
      }
    }
  }

  if (node.nodeType !== Node.TEXT_NODE || offset <= 0) return false;
  let stripped = false;
  while (offset > 0 && node.data.charAt(offset - 1) === '\u200b') {
    node.deleteData(offset - 1, 1);
    offset -= 1;
    stripped = true;
  }
  if (stripped) placeCaret(node, offset);
  return false;
}

const TABLE_LINE = '0.6pt solid #0b2a56';

function tableHtml(rows, cols) {
  const r = Math.min(20, Math.max(1, Number(rows) || 3));
  const c = Math.min(12, Math.max(1, Number(cols) || 3));
  const w = `${(100 / c).toFixed(4)}%`;
  const colgroup = `<colgroup>${`<col style="width:${w}">`.repeat(c)}</colgroup>`;
  const cell = `<td style="border:${TABLE_LINE}">&nbsp;</td>`;
  const header = `<tr>${`<th style="border:${TABLE_LINE};background:#eef2f8">&nbsp;</th>`.repeat(c)}</tr>`;
  const body = Array.from({ length: r - 1 }, () => `<tr>${cell.repeat(c)}</tr>`).join('');
  return `<table class="mhws-table" data-mhws-bw="0.6" data-mhws-bc="#0b2a56" style="table-layout:fixed;width:100%">${colgroup}<thead>${header}</thead><tbody>${body}</tbody></table><p></p>`;
}

function copyCellChrome(from, to) {
  if (!from || !to) return;
  ['border', 'borderWidth', 'borderStyle', 'borderColor', 'backgroundColor', 'color', 'padding'].forEach((k) => {
    if (from.style[k]) to.style[k] = from.style[k];
  });
}

export function imageFloatStyle(width, flt) {
  const pct = Math.max(10, Math.min(100, Number(width) || 40));
  const w = `width:${pct}%;max-width:100%;`;
  if (flt === 'left') return `${w}float:left;margin:0 10pt 8pt 0;display:block;`;
  if (flt === 'right') return `${w}float:right;margin:0 0 8pt 10pt;display:block;`;
  if (flt === 'center') return `${w}display:block;margin:8pt auto;float:none;`;
  return `${w}display:block;margin:0;float:none;flex:0 0 ${pct}%;`;
}

const VALIGN_FLEX = { top: 'flex-start', middle: 'center', center: 'center', bottom: 'flex-end' };

export function applyPairValign(pair, valign) {
  if (!pair) return;
  const v = ['top', 'middle', 'bottom'].includes(valign) ? valign : (pair.dataset.valign || 'top');
  pair.dataset.valign = v;
  const align = VALIGN_FLEX[v] || 'flex-start';
  pair.style.display = 'flex';
  pair.style.alignItems = 'stretch';
  pair.style.gap = '10pt';
  pair.style.width = '100%';
  pair.style.maxWidth = '100%';
  pair.style.margin = '0 0 8pt';
  const text = pair.querySelector(':scope > .mhws-img-text');
  if (text) {
    text.contentEditable = 'true';
    text.style.flex = '1 1 auto';
    text.style.minWidth = '0';
    text.style.display = 'flex';
    text.style.flexDirection = 'column';
    text.style.justifyContent = align;
  }
}

export function ensureImagePair(imgWrap, valign) {
  if (!imgWrap) return null;
  let pair = imgWrap.closest('.mhws-img-pair');
  if (pair) {
    applyPairValign(pair, valign);
    return pair;
  }
  pair = document.createElement('span');
  pair.className = 'mhws-img-pair';
  pair.contentEditable = 'false';
  const text = document.createElement('span');
  text.className = 'mhws-img-text';
  text.contentEditable = 'true';
  const moved = [];
  let sib = imgWrap.nextSibling;
  while (sib) {
    const next = sib.nextSibling;
    if (sib.nodeType === Node.ELEMENT_NODE && (sib.classList.contains('mhws-img') || sib.classList.contains('mhws-img-pair'))) break;
    moved.push(sib);
    sib = next;
  }
  imgWrap.replaceWith(pair);
  pair.append(imgWrap);
  moved.forEach((node) => text.append(node));
  if (!String(text.textContent || '').replace(/\u200b/g, '').trim()) {
    text.innerHTML = '<p><br></p>';
  } else if (![...text.children].some((el) => /^(P|H2|H3|H4|DIV|UL|OL)$/.test(el.tagName))) {
    const p = document.createElement('p');
    while (text.firstChild) p.append(text.firstChild);
    text.append(p);
  }
  pair.append(text);
  applyPairValign(pair, valign);
  return pair;
}

export function unwrapImagePair(imgWrap) {
  const pair = imgWrap?.closest('.mhws-img-pair');
  if (!pair) return;
  const parent = pair.parentNode;
  if (!parent) return;
  const text = pair.querySelector(':scope > .mhws-img-text');
  parent.insertBefore(imgWrap, pair);
  if (text) {
    while (text.firstChild) parent.insertBefore(text.firstChild, pair);
  }
  pair.remove();
}

export function applyImageLayout(wrap, width, flt, valign) {
  if (!wrap) return;
  const pct = Math.max(10, Math.min(100, Number(width) || 40));
  const flow = ['left', 'right', 'center'].includes(flt) ? flt : 'none';
  wrap.dataset.width = String(pct);
  wrap.dataset.float = flow;
  wrap.setAttribute('style', imageFloatStyle(pct, flow));
  wrap.contentEditable = 'false';
  const img = wrap.querySelector('img');
  if (img) {
    img.removeAttribute('width');
    img.removeAttribute('height');
    img.draggable = false;
    img.style.width = '100%';
    img.style.height = 'auto';
    img.style.display = 'block';
  }
  if (flow === 'none') ensureImagePair(wrap, valign);
  else unwrapImagePair(wrap);
}

export function wrappedImageHtml(src, spec = {}) {
  const width = spec.width || 40;
  const flt = spec.float || 'none';
  const valign = spec.valign || 'top';
  const esc = String(src || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '');
  const img = `<span class="mhws-img" contenteditable="false" data-width="${width}" data-float="${flt}" style="${imageFloatStyle(width, flt)}"><img src="${esc}" alt="" draggable="false" style="width:100%;height:auto;display:block"></span>`;
  if (flt !== 'none') return `${img}&nbsp;`;
  return `<span class="mhws-img-pair" contenteditable="false" data-valign="${valign}" style="display:flex;align-items:stretch;gap:10pt;width:100%;max-width:100%;margin:0 0 8pt"><span class="mhws-img" contenteditable="false" data-width="${width}" data-float="none" style="${imageFloatStyle(width, 'none')}"><img src="${esc}" alt="" draggable="false" style="width:100%;height:auto;display:block"></span><span class="mhws-img-text" contenteditable="true" style="flex:1 1 auto;min-width:0;display:flex;flex-direction:column;justify-content:flex-start"><p><br></p></span></span>`;
}

function closestCell(root) {
  let node = currentBlock(root);
  while (node && node !== root) {
    if (node.tagName === 'TD' || node.tagName === 'TH') return node;
    node = node.parentElement;
  }
  return null;
}

export function tableContext(root) {
  const cell = closestCell(root);
  if (!cell) return null;
  const row = cell.parentElement;
  const table = cell.closest('table');
  if (!row || !table || !root.contains(table)) return null;
  return {
    table,
    cell,
    row,
    rowIndex: row.rowIndex,
    colIndex: cell.cellIndex,
  };
}

function focusCell(cell) {
  if (!cell) return;
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(cell);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function ensureColgroup(table) {
  const n = table.rows[0] ? table.rows[0].cells.length : 0;
  let group = table.querySelector(':scope > colgroup');
  if (!group) {
    group = document.createElement('colgroup');
    table.insertBefore(group, table.firstChild);
  }
  while (group.children.length < n) {
    const col = document.createElement('col');
    group.appendChild(col);
  }
  while (group.children.length > n) group.lastElementChild.remove();
  return group;
}

export function freezeColWidths(table) {
  const group = ensureColgroup(table);
  const row = table.rows[0];
  if (!row) return group;
  [...row.cells].forEach((cell, i) => {
    const w = Math.max(24, Math.round(cell.getBoundingClientRect().width));
    group.children[i].style.width = `${w}px`;
  });
  table.style.tableLayout = 'fixed';
  table.style.width = `${Math.max(48, Math.round(table.getBoundingClientRect().width))}px`;
  table.classList.add('mhws-table');
  return group;
}

export function applyColWidth(table, index, widthPx) {
  const group = ensureColgroup(table);
  if (!group.children[index]) return;
  group.children[index].style.width = `${Math.max(24, Math.round(widthPx))}px`;
  let sum = 0;
  [...group.children].forEach((col) => {
    sum += Number.parseFloat(col.style.width) || 80;
  });
  table.style.tableLayout = 'fixed';
  table.style.width = `${Math.round(sum)}px`;
}

export function applyRowHeight(table, index, heightPx) {
  const row = table.rows[index];
  if (!row) return;
  const h = `${Math.max(22, Math.round(heightPx))}px`;
  row.style.height = h;
  [...row.cells].forEach((cell) => {
    cell.style.height = h;
  });
}

function clampPt(value, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(48, Math.round(n * 10) / 10));
}

function clampBorderPt(value, fallback = 0.6) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(8, Math.round(n * 2) / 2));
}

function normalizeHex(raw, fallback = '#0b2a56') {
  const s = String(raw || '').trim();
  if (/^#[0-9a-f]{3}$/i.test(s)) {
    return `#${s[1]}${s[1]}${s[2]}${s[2]}${s[3]}${s[3]}`.toLowerCase();
  }
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  const m = s.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (m) {
    return `#${[m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`;
  }
  if (s === 'transparent' || s === 'none') return '';
  return fallback;
}

function styleScopeOf(ctx, spec = {}) {
  const asked = spec.scope;
  if (asked === 'cell' || asked === 'row' || asked === 'col' || asked === 'table') return asked;
  if (ctx.table?.querySelector('tr.is-row-pick')) return 'row';
  if (ctx.table?.querySelector('td.is-col-pick, th.is-col-pick')) return 'col';
  return 'cell';
}

function cellsForStyle(ctx, spec = {}) {
  const table = ctx.table;
  if (!table) return [];
  const scope = styleScopeOf(ctx, spec);
  if (scope === 'cell' && ctx.cell) return [ctx.cell];
  if (scope === 'row' && ctx.row) return [...ctx.row.cells];
  if (scope === 'col') {
    return [...table.rows].map((r) => r.cells[ctx.colIndex]).filter(Boolean);
  }
  return [...table.querySelectorAll('th, td')];
}

export function applyTableBorders(ctx, spec = {}) {
  const cells = cellsForStyle(ctx, spec);
  if (!cells.length) return false;
  const sample = cells[0];
  const width = spec.width === '' || spec.width == null
    ? clampBorderPt(Number.parseFloat(sample.style.borderWidth) || 0.6)
    : clampBorderPt(spec.width, 0);
  const color = normalizeHex(spec.color, sample.style.borderColor || '#0b2a56') || '#0b2a56';
  const border = width <= 0 ? 'none' : `${width}pt solid ${color}`;
  cells.forEach((cell) => {
    cell.style.border = border;
    if (width <= 0) {
      cell.style.borderWidth = '0';
      cell.style.borderStyle = 'none';
      cell.style.borderColor = 'transparent';
    }
  });
  if (ctx.table) {
    ctx.table.dataset.mhwsBw = String(width);
    ctx.table.dataset.mhwsBc = color;
    if (styleScopeOf(ctx, spec) === 'table') {
      ctx.table.classList.toggle('mhws-table-noborder', width <= 0);
    } else if (width > 0) {
      ctx.table.classList.remove('mhws-table-noborder');
    }
  }
  return true;
}

export function applyTableFill(ctx, spec = {}) {
  const cells = cellsForStyle(ctx, spec);
  if (!cells.length) return false;
  const clear = spec.clear || spec.color === 'none' || spec.color === 'transparent';
  if (clear) {
    cells.forEach((cell) => {
      cell.style.backgroundColor = 'transparent';
    });
    return true;
  }
  const color = normalizeHex(spec.color, '#eef2f8');
  if (!color) return false;
  cells.forEach((cell) => {
    cell.style.backgroundColor = color;
  });
  return true;
}

export function applyTableTextColor(ctx, spec = {}) {
  const cells = cellsForStyle(ctx, spec);
  if (!cells.length) return false;
  const color = normalizeHex(spec.color, '#12233f') || '#12233f';
  cells.forEach((cell) => {
    cell.style.color = color;
  });
  return true;
}

export function applyCellMargins(ctx, spec = {}) {
  const cells = cellsForStyle(ctx, spec);
  if (!cells.length) return false;
  const sample = cells[0];
  const cur = {
    top: clampPt(spec.top, Number.parseFloat(sample.style.paddingTop) || 4),
    right: clampPt(spec.right, Number.parseFloat(sample.style.paddingRight) || 6),
    bottom: clampPt(spec.bottom, Number.parseFloat(sample.style.paddingBottom) || 4),
    left: clampPt(spec.left, Number.parseFloat(sample.style.paddingLeft) || 6),
  };
  const pad = `${cur.top}pt ${cur.right}pt ${cur.bottom}pt ${cur.left}pt`;
  cells.forEach((cell) => {
    cell.style.padding = pad;
  });
  return true;
}

export function applyTableMargins(table, spec = {}) {
  if (!table) return false;
  const cur = {
    top: clampPt(spec.top, Number.parseFloat(table.style.marginTop) || 8),
    right: clampPt(spec.right, Number.parseFloat(table.style.marginRight) || 0),
    bottom: clampPt(spec.bottom, Number.parseFloat(table.style.marginBottom) || 8),
    left: clampPt(spec.left, Number.parseFloat(table.style.marginLeft) || 0),
  };
  table.style.margin = `${cur.top}pt ${cur.right}pt ${cur.bottom}pt ${cur.left}pt`;
  return true;
}

function insertRowAt(ctx, where) {
  const { table, row, colIndex } = ctx;
  if (!table || !row) return false;
  const count = row.cells.length;
  const tr = document.createElement('tr');
  const useTh = row.parentElement?.tagName === 'THEAD' && where === 'above';
  for (let i = 0; i < count; i += 1) {
    const cell = document.createElement(useTh ? 'th' : 'td');
    cell.innerHTML = '&nbsp;';
    copyCellChrome(row.cells[i], cell);
    tr.appendChild(cell);
  }
  if (where === 'above') {
    row.parentNode.insertBefore(tr, row);
  } else if (row.parentElement?.tagName === 'THEAD') {
    let body = table.tBodies[0];
    if (!body) {
      body = document.createElement('tbody');
      table.appendChild(body);
    }
    body.insertBefore(tr, body.firstChild);
  } else {
    row.parentNode.insertBefore(tr, row.nextSibling);
  }
  focusCell(tr.cells[Math.min(colIndex, tr.cells.length - 1)]);
  return true;
}

function insertColAt(ctx, where) {
  const { table, colIndex } = ctx;
  if (!table || colIndex == null) return false;
  const group = ensureColgroup(table);
  const at = where === 'left' ? colIndex : colIndex + 1;
  [...table.rows].forEach((r) => {
    const neighbor = r.cells[colIndex] || r.cells[0];
    const ref = r.cells[at] || null;
    const cell = document.createElement(neighbor?.tagName === 'TH' ? 'th' : 'td');
    cell.innerHTML = '&nbsp;';
    copyCellChrome(neighbor, cell);
    r.insertBefore(cell, ref);
  });
  const col = document.createElement('col');
  col.style.width = '80px';
  group.insertBefore(col, group.children[at] || null);
  if (table.style.width && table.style.width.endsWith('px')) {
    table.style.width = `${(Number.parseFloat(table.style.width) || 0) + 80}px`;
  }
  const row = table.rows[ctx.rowIndex] || table.rows[0];
  focusCell(row?.cells[at]);
  return true;
}

function deleteRowAt(ctx) {
  const { table, row, rowIndex, colIndex } = ctx;
  if (table.rows.length <= 1) {
    table.remove();
    return true;
  }
  row.remove();
  const next = table.rows[Math.min(rowIndex, table.rows.length - 1)];
  focusCell(next?.cells[Math.min(colIndex, (next?.cells.length || 1) - 1)]);
  return true;
}

function deleteColAt(ctx) {
  const { table, colIndex, rowIndex } = ctx;
  const n = table.rows[0]?.cells.length || 0;
  if (n <= 1) {
    table.remove();
    return true;
  }
  [...table.rows].forEach((r) => r.cells[colIndex]?.remove());
  const group = table.querySelector(':scope > colgroup');
  group?.children[colIndex]?.remove();
  const row = table.rows[Math.min(rowIndex, table.rows.length - 1)];
  const nextCol = Math.min(colIndex, (row?.cells.length || 1) - 1);
  focusCell(row?.cells[nextCol]);
  return true;
}

function moveTableCell(ctx, delta) {
  const { table, rowIndex, colIndex } = ctx;
  const cols = table.rows[0]?.cells.length || 0;
  if (!cols) return false;
  let i = rowIndex * cols + colIndex + delta;
  if (i < 0) i = 0;
  if (i >= table.rows.length * cols) {
    insertRowAt({
      table,
      row: table.rows[table.rows.length - 1],
      colIndex: cols - 1,
      rowIndex: table.rows.length - 1,
    }, 'below');
    return true;
  }
  const r = Math.floor(i / cols);
  const c = i % cols;
  focusCell(table.rows[r]?.cells[c]);
  return true;
}

function ensurePaperWrap(host) {
  if (host.parentElement?.classList.contains('mhws-composer-paper-wrap')) {
    return host.parentElement;
  }
  const wrap = document.createElement('div');
  wrap.className = 'mhws-composer-paper-wrap';
  host.before(wrap);
  wrap.append(host);
  return wrap;
}

export function createDomDriver(host) {
  if (!host) throw new Error('Composer host element required');
  const wrap = ensurePaperWrap(host);
  host.setAttribute('contenteditable', 'true');
  host.setAttribute('role', 'textbox');
  host.setAttribute('aria-multiline', 'true');
  host.spellcheck = true;
  applyPageMargins(host, DEFAULT_PAGE_MARGINS);

  let savedRange = null;

  function saveSelection() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (rangeInHost(host, range)) savedRange = range.cloneRange();
  }

  function restoreSelection() {
    if (!savedRange) return false;
    if (!rangeInHost(host, savedRange)) return false;
    const sel = window.getSelection();
    sel.removeAllRanges();
    try {
      sel.addRange(savedRange);
      return true;
    } catch {
      return false;
    }
  }

  function focus() {
    host.focus({ preventScroll: true });
    restoreSelection();
  }

  function onKeydown(event) {
    if (event.key === 'Backspace') {
      handleBackspace(host, event);
      return;
    }
    if (event.key !== 'Tab' || event.altKey || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    event.stopPropagation();
    const ctx = tableContext(host);
    if (ctx) {
      moveTableCell(ctx, event.shiftKey ? -1 : 1);
      emitInput(host);
      return;
    }
    if (event.shiftKey) {
      if (!deleteTabBeforeCaret(host)) indentBlock(host, true);
      return;
    }
    insertTabAtCaret(host);
  }
  host.addEventListener('keydown', onKeydown, true);
  document.addEventListener('selectionchange', saveSelection);

  function getHTML() {
    const box = document.createElement('div');
    box.innerHTML = host.innerHTML || '<p></p>';
    box.querySelectorAll('.mhws-page-spacer, .mhws-page-chrome, .mhws-page-frames').forEach((el) => el.remove());
    const inner = stripPageMargins(box.innerHTML || '<p></p>');
    const m = readPageMargins(host);
    return `<!--mhws-margins:${m.top},${m.right},${m.bottom},${m.left}-->${inner}`;
  }

  function setHTML(html) {
    const raw = String(html || '');
    applyPageMargins(host, parsePageMargins(raw));
    const inner = stripPageMargins(raw).trim();
    host.innerHTML = inner || '<p></p>';
    savedRange = null;
  }

  function withTable(fn, spec = {}) {
    const ctx = spec.table ? spec : tableContext(host);
    if (!ctx || !ctx.table) return false;
    const ok = fn(ctx, spec);
    if (ok) emitInput(host);
    return ok;
  }

  const commands = {
    undo: () => exec('undo'),
    redo: () => exec('redo'),
    copy: () => {
      focus();
      if (exec('copy')) return true;
      const text = window.getSelection()?.toString() || '';
      if (text && navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).catch(() => {});
        return true;
      }
      return false;
    },
    cut: () => {
      focus();
      if (exec('cut')) {
        emitInput(host);
        return true;
      }
      const sel = window.getSelection();
      if (!sel || !sel.rangeCount || sel.isCollapsed) return false;
      const text = sel.toString();
      const range = sel.getRangeAt(0);
      const finish = () => {
        range.deleteContents();
        emitInput(host);
        return true;
      };
      if (text && navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(finish).catch(() => {});
        return true;
      }
      return finish();
    },
    paste: () => false,
    bold: () => exec('bold'),
    italic: () => exec('italic'),
    underline: () => exec('underline'),
    strike: () => exec('strikeThrough'),
    superscript: () => exec('superscript'),
    subscript: () => exec('subscript'),
    bulletList: () => exec('insertUnorderedList'),
    orderedList: () => exec('insertOrderedList'),
    indent: () => indentBlock(host, false),
    outdent: () => indentBlock(host, true),
    alignLeft: () => exec('justifyLeft'),
    alignCenter: () => exec('justifyCenter'),
    alignRight: () => exec('justifyRight'),
    alignJustify: () => exec('justifyFull'),
    paragraph: () => applyBlockStyle(host, 'paragraph'),
    h2: () => applyBlockStyle(host, 'h2'),
    h3: () => applyBlockStyle(host, 'h3'),
    blockquote: () => applyBlockStyle(host, 'blockquote'),
    blockStyle: (kind) => applyBlockStyle(host, kind),
    lineHeight: (value) => applyLineHeight(host, value),
    hr: () => exec('insertHorizontalRule'),
    removeFormat: () => exec('removeFormat'),
    fontFamily: (name) => {
      const family = String(name || '').trim();
      if (!family) return false;
      return applyInlineStyles(host, { fontFamily: family });
    },
    fontSize: (pt) => {
      const size = normalizeFontSize(pt);
      if (!size) return false;
      return applyInlineStyles(host, { fontSize: size });
    },
    color: (hex) => exec('foreColor', hex),
    highlight: (hex) => exec('hiliteColor', hex) || exec('backColor', hex),
    insertTable: (spec = {}) => {
      if (!spec || spec.rows == null || spec.cols == null) return false;
      return exec('insertHTML', tableHtml(spec.rows, spec.cols));
    },
    insertImage: (src) => {
      if (!src) return false;
      return exec('insertHTML', wrappedImageHtml(src));
    },
    insertHTML: (html) => exec('insertHTML', html),
    link: (href) => {
      const url = String(href || '').trim();
      if (!url) {
        exec('unlink');
        return true;
      }
      return exec('createLink', url);
    },
    tableInsertRow: (spec = {}) => withTable((ctx) => insertRowAt(ctx, spec.where === 'above' ? 'above' : 'below'), spec),
    tableInsertCol: (spec = {}) => withTable((ctx) => insertColAt(ctx, spec.where === 'left' ? 'left' : 'right'), spec),
    tableDeleteRow: (spec = {}) => withTable((ctx) => deleteRowAt(ctx), spec),
    tableDeleteCol: (spec = {}) => withTable((ctx) => deleteColAt(ctx), spec),
    tableDelete: (spec = {}) => withTable((ctx) => {
      ctx.table.remove();
      return true;
    }, spec),
    tableSetColWidth: (spec = {}) => withTable((ctx) => {
      applyColWidth(ctx.table, spec.index, spec.width);
      return true;
    }, spec),
    tableSetRowHeight: (spec = {}) => withTable((ctx) => {
      applyRowHeight(ctx.table, spec.index, spec.height);
      return true;
    }, spec),
    tableCellMargins: (spec = {}) => withTable((ctx) => {
      applyCellMargins(ctx, spec);
      return true;
    }, spec),
    tableMargins: (spec = {}) => withTable((ctx) => {
      applyTableMargins(ctx.table, spec);
      return true;
    }, spec),
    tableBorders: (spec = {}) => withTable((ctx) => {
      applyTableBorders(ctx, spec);
      return true;
    }, spec),
    tableFill: (spec = {}) => withTable((ctx) => {
      applyTableFill(ctx, spec);
      return true;
    }, spec),
    tableTextColor: (spec = {}) => withTable((ctx) => {
      applyTableTextColor(ctx, spec);
      return true;
    }, spec),
  };

  function run(commandId, payload) {
    restoreSelection();
    if (document.activeElement !== host && !host.contains(document.activeElement)) {
      host.focus({ preventScroll: true });
      restoreSelection();
    }
    const fn = commands[commandId];
    if (!fn) return false;
    const ok = fn(payload) !== false;
    saveSelection();
    return ok;
  }

  return {
    kind: 'dom',
    host,
    wrap,
    mount() {},
    focus,
    saveSelection,
    restoreSelection,
    getHTML,
    setHTML,
    run,
    currentBlock: () => currentBlock(host),
    tableContext: () => tableContext(host),
    getPageMargins: () => readPageMargins(host),
    setPageMargins(spec) {
      applyPageMargins(host, spec);
      emitInput(host);
      return true;
    },
    destroy() {
      host.removeEventListener('keydown', onKeydown, true);
      document.removeEventListener('selectionchange', saveSelection);
      host.removeAttribute('contenteditable');
    },
  };
}
