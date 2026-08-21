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
  host.style.padding = `${next.top}mm ${next.right}mm ${next.bottom}mm ${next.left}mm`;
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

function wrapInline(styles) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  const range = sel.getRangeAt(0);
  if (range.collapsed) {
    const span = document.createElement('span');
    Object.assign(span.style, styles);
    span.appendChild(document.createTextNode('\u200b'));
    range.insertNode(span);
    const next = document.createRange();
    next.setStart(span.firstChild, 1);
    next.collapse(true);
    sel.removeAllRanges();
    sel.addRange(next);
    return;
  }
  const span = document.createElement('span');
  Object.assign(span.style, styles);
  try {
    range.surroundContents(span);
  } catch {
    const frag = range.extractContents();
    span.appendChild(frag);
    range.insertNode(span);
  }
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

function tableHtml(rows, cols) {
  const r = Math.min(20, Math.max(1, Number(rows) || 3));
  const c = Math.min(12, Math.max(1, Number(cols) || 3));
  const w = `${(100 / c).toFixed(4)}%`;
  const colgroup = `<colgroup>${`<col style="width:${w}">`.repeat(c)}</colgroup>`;
  const cell = '<td>&nbsp;</td>';
  const header = `<tr>${'<th>&nbsp;</th>'.repeat(c)}</tr>`;
  const body = Array.from({ length: r - 1 }, () => `<tr>${cell.repeat(c)}</tr>`).join('');
  return `<table class="mhws-table" style="table-layout:fixed;width:100%">${colgroup}<thead>${header}</thead><tbody>${body}</tbody></table><p></p>`;
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

function cellsForMargin(ctx, spec = {}) {
  const table = ctx.table;
  if (!table) return [];
  if (spec.scope === 'cell' && ctx.cell) return [ctx.cell];
  if (spec.scope === 'row' && ctx.row) return [...ctx.row.cells];
  if (spec.scope === 'col') {
    return [...table.rows].map((r) => r.cells[ctx.colIndex]).filter(Boolean);
  }
  if (table.querySelector('tr.is-row-pick')) {
    return [...table.querySelector('tr.is-row-pick').cells];
  }
  const colCell = table.querySelector('td.is-col-pick, th.is-col-pick');
  if (colCell) {
    const i = colCell.cellIndex;
    return [...table.rows].map((r) => r.cells[i]).filter(Boolean);
  }
  return [...table.querySelectorAll('th, td')];
}

export function applyCellMargins(ctx, spec = {}) {
  const cells = cellsForMargin(ctx, spec);
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
    const ref = r.cells[at] || null;
    const cell = document.createElement(r.cells[0]?.tagName === 'TH' ? 'th' : 'td');
    cell.innerHTML = '&nbsp;';
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

  function focus() {
    host.focus();
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
    indentBlock(host, event.shiftKey);
  }
  host.addEventListener('keydown', onKeydown, true);

  function getHTML() {
    const inner = stripPageMargins(host.innerHTML || '<p></p>');
    const m = readPageMargins(host);
    return `<!--mhws-margins:${m.top},${m.right},${m.bottom},${m.left}-->${inner}`;
  }

  function setHTML(html) {
    const raw = String(html || '');
    applyPageMargins(host, parsePageMargins(raw));
    const inner = stripPageMargins(raw).trim();
    host.innerHTML = inner || '<p></p>';
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
    paragraph: () => exec('formatBlock', 'p'),
    h2: () => exec('formatBlock', 'h2'),
    h3: () => exec('formatBlock', 'h3'),
    blockquote: () => exec('formatBlock', 'blockquote'),
    hr: () => exec('insertHorizontalRule'),
    removeFormat: () => exec('removeFormat'),
    fontFamily: (name) => exec('fontName', name),
    fontSize: (pt) => {
      const size = String(pt || '').trim();
      if (!size) return false;
      if (/^[1-7]$/.test(size)) {
        exec('fontSize', size);
        host.querySelectorAll('font[size]').forEach((el) => {
          const mapped = FONT_SIZE_MAP[el.getAttribute('size')] || size;
          const span = document.createElement('span');
          span.style.fontSize = mapped.includes('pt') || mapped.includes('px') ? mapped : `${mapped}pt`;
          span.innerHTML = el.innerHTML;
          el.replaceWith(span);
        });
        return true;
      }
      wrapInline({ fontSize: size.includes('pt') || size.includes('px') ? size : `${size}pt` });
      return true;
    },
    color: (hex) => exec('foreColor', hex),
    highlight: (hex) => exec('hiliteColor', hex) || exec('backColor', hex),
    insertTable: (spec = {}) => {
      if (!spec || spec.rows == null || spec.cols == null) return false;
      return exec('insertHTML', tableHtml(spec.rows, spec.cols));
    },
    insertImage: (src) => {
      if (!src) return false;
      return exec('insertImage', src);
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
  };

  function run(commandId, payload) {
    focus();
    const fn = commands[commandId];
    if (!fn) return false;
    return fn(payload) !== false;
  }

  return {
    kind: 'dom',
    host,
    wrap,
    mount() {},
    focus,
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
      host.removeAttribute('contenteditable');
    },
  };
}
