import { iconSvg } from './icons.js';
import { freezeColWidths, ensureColgroup, applyColWidth, applyRowHeight } from './driver-dom.js';

const GRID_ROWS = 8;
const GRID_COLS = 10;

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (v == null || v === false) return;
    if (k === 'className') node.className = v;
    else if (k === 'hidden') node.hidden = !!v;
    else node.setAttribute(k, String(v));
  });
  children.forEach((c) => {
    if (c != null) node.append(c);
  });
  return node;
}

function toolBtn(icon, title, action) {
  const btn = el('button', {
    type: 'button',
    className: 'mhws-composer-btn',
    title,
    'aria-label': title,
    'data-table-act': action,
  });
  btn.append(iconSvg(icon) || document.createTextNode(title));
  return btn;
}

function numField(label, key, unit, title, extra = {}) {
  const lab = el('label', { className: 'mhws-table-num', title: title || label });
  lab.append(el('span', {}, [label]));
  const input = el('input', {
    type: 'number',
    min: extra.min != null ? String(extra.min) : '0',
    max: extra.max != null ? String(extra.max) : '48',
    step: extra.step != null ? String(extra.step) : '1',
    value: extra.value != null ? String(extra.value) : '0',
    'data-margin-key': key,
    'aria-label': title || label,
  });
  lab.append(input);
  lab.append(el('span', { className: 'mhws-margin-unit' }, [unit]));
  return { lab, input };
}

function colorField(label, title, value) {
  const wrap = el('label', { className: 'mhws-table-color', title });
  wrap.append(el('span', {}, [label]));
  const input = el('input', {
    type: 'color',
    title,
    value: value || '#0b2a56',
    'aria-label': title,
  });
  wrap.append(input);
  return { lab: wrap, input };
}

function cssColorToHex(c, fallback = '#0b2a56') {
  const s = String(c || '').trim();
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(s)) {
    return `#${s[1]}${s[1]}${s[2]}${s[2]}${s[3]}${s[3]}`.toLowerCase();
  }
  const m = s.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (m) {
    const a = s.startsWith('rgba') ? Number((s.match(/,\s*([0-9.]+)\s*\)$/) || [])[1]) : 1;
    if (a === 0) return '';
    return `#${[m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('')}`;
  }
  if (s === 'transparent' || s === 'none') return '';
  return fallback;
}

let openPicker = null;

function closePicker() {
  if (!openPicker) return;
  openPicker.remove();
  openPicker = null;
  document.removeEventListener('mousedown', onDocPicker, true);
  document.removeEventListener('keydown', onEscPicker, true);
}

function onDocPicker(event) {
  if (openPicker && !openPicker.contains(event.target) && !event.target.closest('[data-insert-table]')) {
    closePicker();
  }
}

function onEscPicker(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closePicker();
  }
}

export function bindInsertTableButton(btn, driver) {
  btn.setAttribute('data-insert-table', '1');
  btn.addEventListener('mousedown', (event) => event.preventDefault());
  btn.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (openPicker) {
      closePicker();
      return;
    }
    const pop = el('div', {
      className: 'mhws-table-picker',
      role: 'dialog',
      'aria-label': 'Insert table',
    });
    const label = el('p', { className: 'mhws-table-picker-label' });
    label.textContent = 'Cancel';
    const grid = el('div', { className: 'mhws-table-picker-grid' });
    const cells = [];
    for (let r = 1; r <= GRID_ROWS; r += 1) {
      for (let c = 1; c <= GRID_COLS; c += 1) {
        const cell = el('button', {
          type: 'button',
          className: 'mhws-table-picker-cell',
          'data-r': String(r),
          'data-c': String(c),
          'aria-label': `${r} by ${c}`,
        });
        cells.push(cell);
        grid.append(cell);
      }
    }
    function paint(rows, cols) {
      cells.forEach((cell) => {
        const r = Number(cell.dataset.r);
        const c = Number(cell.dataset.c);
        cell.classList.toggle('is-on', r <= rows && c <= cols);
      });
      label.textContent = rows && cols ? `${rows} × ${cols}` : 'Cancel';
    }
    grid.addEventListener('mouseover', (ev) => {
      const cell = ev.target.closest('.mhws-table-picker-cell');
      if (!cell) return;
      paint(Number(cell.dataset.r), Number(cell.dataset.c));
    });
    grid.addEventListener('mouseleave', () => paint(0, 0));
    grid.addEventListener('mousedown', (ev) => ev.preventDefault());
    grid.addEventListener('click', (ev) => {
      const cell = ev.target.closest('.mhws-table-picker-cell');
      if (!cell) return;
      const rows = Number(cell.dataset.r);
      const cols = Number(cell.dataset.c);
      closePicker();
      driver.focus();
      driver.run('insertTable', { rows, cols });
    });
    pop.append(label, grid);
    const hint = el('p', { className: 'mhws-table-picker-hint' });
    hint.textContent = 'Click a size. Click away to cancel.';
    pop.append(hint);
    document.body.append(pop);
    const br = btn.getBoundingClientRect();
    const left = Math.min(br.left, window.innerWidth - 220);
    pop.style.left = `${Math.max(8, left)}px`;
    pop.style.top = `${Math.min(br.bottom + 4, window.innerHeight - 220)}px`;
    openPicker = pop;
    document.addEventListener('mousedown', onDocPicker, true);
    document.addEventListener('keydown', onEscPicker, true);
    paint(0, 0);
  });
}

function clearPicks(table) {
  table?.querySelectorAll('.is-row-pick, .is-col-pick').forEach((n) => {
    n.classList.remove('is-row-pick', 'is-col-pick');
  });
}

function pickRow(table, index) {
  clearPicks(table);
  const row = table.rows[index];
  if (row) row.classList.add('is-row-pick');
}

function pickCol(table, index) {
  clearPicks(table);
  [...table.rows].forEach((row) => {
    row.cells[index]?.classList.add('is-col-pick');
  });
}

export function attachTableUi({ host, toolbar, driver, onChange }) {
  if (!host || !toolbar || !driver) {
    return { destroy() {} };
  }
  const wrap = driver.wrap || host.parentElement;
  const tools = el('div', {
    className: 'mhws-table-tools',
    hidden: true,
    role: 'toolbar',
    'aria-label': 'Table',
  });
  const cellFields = {
    top: numField('T', 'cell-top', 'pt', 'Cell top margin'),
    bottom: numField('B', 'cell-bottom', 'pt', 'Cell bottom margin'),
    left: numField('L', 'cell-left', 'pt', 'Cell left margin'),
    right: numField('R', 'cell-right', 'pt', 'Cell right margin'),
  };
  const tableFields = {
    top: numField('T', 'table-top', 'pt', 'Table top margin'),
    bottom: numField('B', 'table-bottom', 'pt', 'Table bottom margin'),
    left: numField('L', 'table-left', 'pt', 'Table left margin'),
    right: numField('R', 'table-right', 'pt', 'Table right margin'),
  };
  const borderWidth = numField('Line', 'border-w', 'pt', 'Border thickness — 0 hides the line', {
    min: 0, max: 8, step: 0.5, value: 0.6,
  });
  const borderColor = colorField('', 'Border colour', '#0b2a56');
  const fillColor = colorField('Fill', 'Cell / row / column background', '#eef2f8');
  const textColor = colorField('Text', 'Cell text colour', '#12233f');
  const fillNone = toolBtn('clear', 'No fill', 'fillNone');
  let styleScope = 'table';
  const scopeWrap = el('span', { className: 'mhws-table-scope', role: 'group', 'aria-label': 'Apply to' });
  const scopeBtns = {};
  [['cell', 'Cell'], ['row', 'Row'], ['col', 'Col'], ['table', 'Table']].forEach(([id, label]) => {
    const btn = el('button', {
      type: 'button',
      className: id === 'table' ? 'is-on' : '',
      title: `Apply to ${label.toLowerCase()}`,
      'data-scope': id,
    });
    btn.textContent = label;
    scopeBtns[id] = btn;
    scopeWrap.append(btn);
  });
  function setScope(next) {
    styleScope = next;
    Object.entries(scopeBtns).forEach(([id, btn]) => {
      btn.classList.toggle('is-on', id === next);
    });
  }
  tools.append(
    el('span', { className: 'mhws-table-tools-label' }, ['Table']),
    toolBtn('tableRowAdd', 'Insert row below', 'rowBelow'),
    toolBtn('tableRowAddAbove', 'Insert row above', 'rowAbove'),
    toolBtn('tableRowDel', 'Delete this row', 'rowDel'),
    toolBtn('tableColAdd', 'Insert column right', 'colRight'),
    toolBtn('tableColAddLeft', 'Insert column left', 'colLeft'),
    toolBtn('tableColDel', 'Delete this column', 'colDel'),
    toolBtn('tableDelete', 'Delete table', 'tableDel'),
    el('span', { className: 'mhws-table-tools-label' }, ['Apply']),
    scopeWrap,
    el('span', { className: 'mhws-table-tools-label' }, ['Line']),
    borderWidth.lab,
    borderColor.lab,
    fillColor.lab,
    fillNone,
    textColor.lab,
    el('span', { className: 'mhws-table-tools-label' }, ['Cell']),
    cellFields.top.lab,
    cellFields.bottom.lab,
    cellFields.left.lab,
    cellFields.right.lab,
    el('span', { className: 'mhws-table-tools-label' }, ['Outer']),
    tableFields.top.lab,
    tableFields.bottom.lab,
    tableFields.left.lab,
    tableFields.right.lab,
  );
  toolbar.after(tools);

  const overlay = el('div', { className: 'mhws-table-overlay', hidden: true });
  wrap.append(overlay);

  let activeTable = null;
  let lastCell = null;
  let drag = null;

  function notify() {
    if (typeof onChange === 'function') onChange();
  }

  function hide() {
    activeTable = null;
    lastCell = null;
    overlay.hidden = true;
    overlay.innerHTML = '';
    tools.hidden = true;
  }

  function layout() {
    if (!activeTable || !host.contains(activeTable)) {
      hide();
      return;
    }
    const wrapRect = wrap.getBoundingClientRect();
    const tRect = activeTable.getBoundingClientRect();
    overlay.hidden = false;
    tools.hidden = false;
    overlay.style.left = `${tRect.left - wrapRect.left + wrap.scrollLeft}px`;
    overlay.style.top = `${tRect.top - wrapRect.top + wrap.scrollTop}px`;
    overlay.style.width = `${tRect.width}px`;
    overlay.style.height = `${tRect.height}px`;
    overlay.innerHTML = '';

    const rows = [...activeTable.rows];
    if (!rows.length) return;
    const cols = rows[0].cells.length;

    for (let c = 0; c < cols; c += 1) {
      const cell = rows[0].cells[c];
      const cr = cell.getBoundingClientRect();
      const x = cr.left - tRect.left;
      const gutter = el('button', {
        type: 'button',
        className: 'mhws-table-col-gutter',
        title: 'Select column',
        'aria-label': `Select column ${c + 1}`,
        'data-col': String(c),
      });
      gutter.style.left = `${x}px`;
      gutter.style.width = `${cr.width}px`;
      overlay.append(gutter);

      const resizer = el('div', {
        className: 'mhws-table-col-resizer',
        title: 'Resize this column',
        'data-col': String(c),
      });
      resizer.style.left = `${x + cr.width}px`;
      overlay.append(resizer);
    }

    rows.forEach((row, r) => {
      const rr = row.getBoundingClientRect();
      const y = rr.top - tRect.top;
      const gutter = el('button', {
        type: 'button',
        className: 'mhws-table-row-gutter',
        title: 'Select row',
        'aria-label': `Select row ${r + 1}`,
        'data-row': String(r),
      });
      gutter.style.top = `${y}px`;
      gutter.style.height = `${rr.height}px`;
      overlay.append(gutter);

      const resizer = el('div', {
        className: 'mhws-table-row-resizer',
        title: 'Resize this row',
        'data-row': String(r),
      });
      resizer.style.top = `${y + rr.height}px`;
      overlay.append(resizer);
    });
  }

  function showFor(table) {
    if (!table) {
      hide();
      return;
    }
    activeTable = table;
    layout();
    fillMarginFields(table);
  }

  function contextFromPick() {
    const ctx = driver.tableContext();
    if (ctx) {
      lastCell = ctx.cell;
      return ctx;
    }
    if (!activeTable) return null;
    const rowEl = activeTable.querySelector('tr.is-row-pick');
    const colEl = activeTable.querySelector('td.is-col-pick, th.is-col-pick');
    const row = rowEl || (lastCell && activeTable.contains(lastCell) ? lastCell.parentElement : null) || activeTable.rows[0];
    const colIndex = colEl
      ? colEl.cellIndex
      : (lastCell && activeTable.contains(lastCell) ? lastCell.cellIndex : 0);
    return {
      table: activeTable,
      row,
      cell: lastCell && activeTable.contains(lastCell) ? lastCell : row?.cells[colIndex],
      rowIndex: row?.rowIndex || 0,
      colIndex,
    };
  }

  tools.addEventListener('mousedown', (event) => {
    if (event.target.closest('input')) return;
    event.preventDefault();
  });
  tools.addEventListener('click', (event) => {
    const scopeBtn = event.target.closest('[data-scope]');
    if (scopeBtn) {
      setScope(scopeBtn.getAttribute('data-scope'));
      return;
    }
    const btn = event.target.closest('[data-table-act]');
    if (!btn) return;
    const act = btn.getAttribute('data-table-act');
    const ctx = contextFromPick();
    driver.focus();
    const spec = { ...(ctx || {}), scope: styleScope };
    if (act === 'rowBelow') driver.run('tableInsertRow', { ...spec, where: 'below' });
    if (act === 'rowAbove') driver.run('tableInsertRow', { ...spec, where: 'above' });
    if (act === 'rowDel') driver.run('tableDeleteRow', spec);
    if (act === 'colRight') driver.run('tableInsertCol', { ...spec, where: 'right' });
    if (act === 'colLeft') driver.run('tableInsertCol', { ...spec, where: 'left' });
    if (act === 'colDel') driver.run('tableDeleteCol', spec);
    if (act === 'tableDel') driver.run('tableDelete', spec);
    if (act === 'fillNone') driver.run('tableFill', { ...spec, clear: true });
    const next = driver.tableContext();
    showFor(next?.table || (host.contains(activeTable) ? activeTable : null));
    notify();
  });

  function fillMarginFields(table) {
    const ctx = contextFromPick() || { table };
    const cell = ctx.cell || table.querySelector('td, th');
    const cs = cell ? window.getComputedStyle(cell) : null;
    const pt = (px) => Math.round((Number.parseFloat(px) || 0) * 72 / 96);
    const ptHalf = (px) => Math.round((Number.parseFloat(px) || 0) * 72 / 96 * 2) / 2;
    if (cs) {
      cellFields.top.input.value = String(pt(cs.paddingTop));
      cellFields.right.input.value = String(pt(cs.paddingRight));
      cellFields.bottom.input.value = String(pt(cs.paddingBottom));
      cellFields.left.input.value = String(pt(cs.paddingLeft));
      const bw = ptHalf(cs.borderTopWidth);
      borderWidth.input.value = String(cs.borderTopStyle === 'none' ? 0 : bw);
      const lineHex = cssColorToHex(cs.borderTopColor, '#0b2a56');
      if (lineHex) borderColor.input.value = lineHex;
      const fillHex = cssColorToHex(cs.backgroundColor, '');
      fillColor.input.value = fillHex || '#ffffff';
      const textHex = cssColorToHex(cs.color, '#12233f');
      if (textHex) textColor.input.value = textHex;
    }
    const ts = window.getComputedStyle(table);
    tableFields.top.input.value = String(pt(ts.marginTop));
    tableFields.right.input.value = String(pt(ts.marginRight));
    tableFields.bottom.input.value = String(pt(ts.marginBottom));
    tableFields.left.input.value = String(pt(ts.marginLeft));
  }

  function styleSpec() {
    return { ...(contextFromPick() || {}), scope: styleScope };
  }

  function onCellMarginChange() {
    const ctx = contextFromPick();
    if (!ctx) return;
    driver.run('tableCellMargins', {
      ...ctx,
      scope: styleScope,
      top: cellFields.top.input.value,
      right: cellFields.right.input.value,
      bottom: cellFields.bottom.input.value,
      left: cellFields.left.input.value,
    });
    notify();
  }

  function onTableMarginChange() {
    const ctx = contextFromPick();
    if (!ctx) return;
    driver.run('tableMargins', {
      ...ctx,
      top: tableFields.top.input.value,
      right: tableFields.right.input.value,
      bottom: tableFields.bottom.input.value,
      left: tableFields.left.input.value,
    });
    notify();
  }

  function onBorderChange() {
    if (!contextFromPick() && !activeTable) return;
    driver.run('tableBorders', {
      ...styleSpec(),
      width: borderWidth.input.value,
      color: borderColor.input.value,
    });
    notify();
    layout();
  }

  function onFillChange() {
    if (!contextFromPick() && !activeTable) return;
    driver.run('tableFill', { ...styleSpec(), color: fillColor.input.value });
    notify();
  }

  function onTextColorChange() {
    if (!contextFromPick() && !activeTable) return;
    driver.run('tableTextColor', { ...styleSpec(), color: textColor.input.value });
    notify();
  }

  Object.values(cellFields).forEach(({ input }) => input.addEventListener('change', onCellMarginChange));
  Object.values(tableFields).forEach(({ input }) => input.addEventListener('change', onTableMarginChange));
  borderWidth.input.addEventListener('change', onBorderChange);
  borderColor.input.addEventListener('input', onBorderChange);
  fillColor.input.addEventListener('input', onFillChange);
  textColor.input.addEventListener('input', onTextColorChange);

  overlay.addEventListener('mousedown', (event) => {
    const colR = event.target.closest('.mhws-table-col-resizer');
    const rowR = event.target.closest('.mhws-table-row-resizer');
    const colG = event.target.closest('.mhws-table-col-gutter');
    const rowG = event.target.closest('.mhws-table-row-gutter');
    if (colG && activeTable) {
      event.preventDefault();
      pickCol(activeTable, Number(colG.dataset.col));
      const cell = activeTable.rows[0]?.cells[Number(colG.dataset.col)];
      if (cell) {
        driver.focus();
        const range = document.createRange();
        range.selectNodeContents(cell);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      fillMarginFields(activeTable);
      setScope('col');
      return;
    }
    if (rowG && activeTable) {
      event.preventDefault();
      pickRow(activeTable, Number(rowG.dataset.row));
      const cell = activeTable.rows[Number(rowG.dataset.row)]?.cells[0];
      if (cell) {
        driver.focus();
        const range = document.createRange();
        range.selectNodeContents(cell);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      fillMarginFields(activeTable);
      setScope('row');
      return;
    }
    if (!activeTable || (!colR && !rowR)) return;
    event.preventDefault();
    event.stopPropagation();
    freezeColWidths(activeTable);
    ensureColgroup(activeTable);
    if (colR) {
      const index = Number(colR.dataset.col);
      const col = activeTable.querySelector(':scope > colgroup')?.children[index];
      drag = {
        kind: 'col',
        index,
        startX: event.clientX,
        startW: Number.parseFloat(col?.style.width) || activeTable.rows[0].cells[index].getBoundingClientRect().width,
      };
    } else {
      const index = Number(rowR.dataset.row);
      const row = activeTable.rows[index];
      drag = {
        kind: 'row',
        index,
        startY: event.clientY,
        startH: row.getBoundingClientRect().height,
      };
    }
    document.body.classList.add('mhws-table-resizing', drag.kind === 'col' ? 'mhws-table-resizing-col' : 'mhws-table-resizing-row');
  });

  function onMove(event) {
    if (!drag || !activeTable) return;
    if (drag.kind === 'col') {
      applyColWidth(activeTable, drag.index, drag.startW + (event.clientX - drag.startX));
    } else {
      applyRowHeight(activeTable, drag.index, drag.startH + (event.clientY - drag.startY));
    }
  }

  function onUp() {
    if (!drag) return;
    drag = null;
    document.body.classList.remove('mhws-table-resizing', 'mhws-table-resizing-col', 'mhws-table-resizing-row');
    notify();
    layout();
  }

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);

  function syncFromSelection() {
    const ctx = driver.tableContext();
    if (ctx?.table) {
      if (ctx.table !== activeTable) clearPicks(ctx.table);
      showFor(ctx.table);
    } else if (!drag) {
      hide();
    }
  }

  const onSel = () => {
    window.requestAnimationFrame(syncFromSelection);
  };
  document.addEventListener('selectionchange', onSel);
  host.addEventListener('click', onSel);
  wrap.addEventListener('scroll', layout);
  window.addEventListener('resize', layout);

  return {
    destroy() {
      closePicker();
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('selectionchange', onSel);
      host.removeEventListener('click', onSel);
      wrap.removeEventListener('scroll', layout);
      window.removeEventListener('resize', layout);
      tools.remove();
      overlay.remove();
      document.body.classList.remove('mhws-table-resizing', 'mhws-table-resizing-col', 'mhws-table-resizing-row');
    },
  };
}
