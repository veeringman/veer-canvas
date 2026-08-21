const PRESETS = [
  { id: 'narrow', label: 'Narrow', top: 10, right: 10, bottom: 10, left: 10 },
  { id: 'normal', label: 'Normal', top: 16, right: 16, bottom: 16, left: 16 },
  { id: 'wide', label: 'Wide', top: 25, right: 25, bottom: 25, left: 25 },
];

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (v == null || v === false) return;
    if (k === 'className') node.className = v;
    else node.setAttribute(k, String(v));
  });
  children.forEach((c) => {
    if (c != null) node.append(c);
  });
  return node;
}

function field(side, value) {
  const lab = el('label', { className: `mhws-margin-field is-${side}` });
  lab.append(el('span', {}, [side[0].toUpperCase() + side.slice(1)]));
  const input = el('input', {
    type: 'number',
    min: '0',
    max: '50',
    step: '1',
    value: String(value),
    'data-margin-side': side,
    'aria-label': `${side} margin millimetres`,
  });
  lab.append(input);
  lab.append(el('span', { className: 'mhws-margin-unit' }, ['mm']));
  return lab;
}

let openPop = null;

function closePop() {
  if (!openPop) return;
  openPop.remove();
  openPop = null;
  document.removeEventListener('mousedown', onDoc, true);
  document.removeEventListener('keydown', onEsc, true);
}

function onDoc(event) {
  if (openPop && !openPop.contains(event.target) && !event.target.closest('[data-page-margins]')) {
    closePop();
  }
}

function onEsc(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closePop();
  }
}

export function bindPageMarginsButton(btn, driver) {
  btn.setAttribute('data-page-margins', '1');
  btn.addEventListener('mousedown', (event) => event.preventDefault());
  btn.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (openPop) {
      closePop();
      return;
    }
    const cur = driver.getPageMargins ? driver.getPageMargins() : { top: 16, right: 16, bottom: 16, left: 16 };
    const pop = el('div', {
      className: 'mhws-margin-picker',
      role: 'dialog',
      'aria-label': 'Page margins',
    });
    pop.append(el('p', { className: 'mhws-table-picker-label' }, ['Page margins']));
    const presets = el('div', { className: 'mhws-margin-presets' });
    PRESETS.forEach((p) => {
      const b = el('button', { type: 'button', className: 'mhws-margin-preset' }, [p.label]);
      b.addEventListener('click', () => {
        driver.setPageMargins(p);
        closePop();
      });
      presets.append(b);
    });
    pop.append(presets);
    const grid = el('div', { className: 'mhws-margin-grid' });
    grid.append(
      field('top', cur.top),
      field('left', cur.left),
      field('right', cur.right),
      field('bottom', cur.bottom),
    );
    pop.append(grid);
    pop.append(el('p', { className: 'mhws-table-picker-hint' }, ['Left / right and top / bottom. Click away to close.']));
    grid.addEventListener('change', () => {
      const next = {};
      grid.querySelectorAll('[data-margin-side]').forEach((input) => {
        next[input.getAttribute('data-margin-side')] = input.value;
      });
      driver.setPageMargins(next);
    });
    document.body.append(pop);
    const br = btn.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(br.left, window.innerWidth - 260))}px`;
    pop.style.top = `${Math.min(br.bottom + 4, window.innerHeight - 280)}px`;
    openPop = pop;
    document.addEventListener('mousedown', onDoc, true);
    document.addEventListener('keydown', onEsc, true);
  });
}
