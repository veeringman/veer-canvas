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

function numField(label, key, unit, title) {
  const lab = el('label', { className: 'mhws-table-num', title: title || label });
  lab.append(el('span', {}, [label]));
  const input = el('input', {
    type: 'number',
    min: '0',
    max: '48',
    step: '1',
    value: '0',
    'data-margin-key': key,
    'aria-label': title || label,
  });
  lab.append(input);
  lab.append(el('span', { className: 'mhws-margin-unit' }, [unit]));
  return { lab, input };
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
  tools.append(
    el('span', { className: 'mhws-table-tools-label' }, ['Table']),
    toolBtn('tableRowAdd', 'Insert row below', 'rowBelow'),
    toolBtn('tableRowAddAbove', 'Insert row above', 'rowAbove'),
    toolBtn('tableRowDel', 'Delete this row', 'rowDel'),
    toolBtn('tableColAdd', 'Insert column right', 'colRight'),
    toolBtn('tableColAddLeft', 'Insert column left', 'colLeft'),
    toolBtn('tableColDel', 'Delete this column', 'colDel'),
    toolBtn('tableDelete', 'Delete table', 'tableDel'),
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
  let drag = null;

  function notify() {
    if (typeof onChange === 'function') onChange();
  }

  function hide() {
    activeTable = null;
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
    if (ctx) return ctx;
    if (!activeTable) return null;
    const rowEl = activeTable.querySelector('tr.is-row-pick');
    const colEl = activeTable.querySelector('td.is-col-pick, th.is-col-pick');
    const row = rowEl || activeTable.rows[0];
    const colIndex = colEl ? colEl.cellIndex : 0;
    return {
      table: activeTable,
      row,
      cell: row?.cells[colIndex],
      rowIndex: row?.rowIndex || 0,
      colIndex,
    };
  }

  tools.addEventListener('mousedown', (event) => {
    if (event.target.closest('input')) return;
    event.preventDefault();
  });
  tools.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-table-act]');
    if (!btn) return;
    const act = btn.getAttribute('data-table-act');
    const ctx = contextFromPick();
    driver.focus();
    const spec = ctx || {};
    if (act === 'rowBelow') driver.run('tableInsertRow', { ...spec, where: 'below' });
    if (act === 'rowAbove') driver.run('tableInsertRow', { ...spec, where: 'above' });
    if (act === 'rowDel') driver.run('tableDeleteRow', spec);
    if (act === 'colRight') driver.run('tableInsertCol', { ...spec, where: 'right' });
    if (act === 'colLeft') driver.run('tableInsertCol', { ...spec, where: 'left' });
    if (act === 'colDel') driver.run('tableDeleteCol', spec);
    if (act === 'tableDel') driver.run('tableDelete', spec);
    const next = driver.tableContext();
    showFor(next?.table || (host.contains(activeTable) ? activeTable : null));
    notify();
  });

  function fillMarginFields(table) {
    const ctx = contextFromPick() || { table };
    const cell = ctx.cell || table.querySelector('td, th');
    const cs = cell ? window.getComputedStyle(cell) : null;
    const pt = (px) => Math.round((Number.parseFloat(px) || 0) * 72 / 96);
    if (cs) {
      cellFields.top.input.value = String(pt(cs.paddingTop));
      cellFields.right.input.value = String(pt(cs.paddingRight));
      cellFields.bottom.input.value = String(pt(cs.paddingBottom));
      cellFields.left.input.value = String(pt(cs.paddingLeft));
    }
    const ts = window.getComputedStyle(table);
    tableFields.top.input.value = String(pt(ts.marginTop));
    tableFields.right.input.value = String(pt(ts.marginRight));
    tableFields.bottom.input.value = String(pt(ts.marginBottom));
    tableFields.left.input.value = String(pt(ts.marginLeft));
  }

  function onCellMarginChange() {
    const ctx = contextFromPick();
    if (!ctx) return;
    driver.run('tableCellMargins', {
      ...ctx,
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

  Object.values(cellFields).forEach(({ input }) => input.addEventListener('change', onCellMarginChange));
  Object.values(tableFields).forEach(({ input }) => input.addEventListener('change', onTableMarginChange));

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
