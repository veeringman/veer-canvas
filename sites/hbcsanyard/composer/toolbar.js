import { registry } from './registry.js';
import { iconSvg } from './icons.js';
import { bindInsertTableButton } from './table-ui.js';
import { bindPageMarginsButton } from './page-margins.js';

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

function iconOrText(ext) {
  return iconSvg(ext.icon || ext.id) || document.createTextNode(ext.label || '');
}

export function renderToolbar(toolbarEl, driver, { onImageFile } = {}) {
  if (!toolbarEl) return;
  toolbarEl.innerHTML = '';
  toolbarEl.classList.add('mhws-composer-toolbar');
  toolbarEl.setAttribute('role', 'toolbar');
  toolbarEl.setAttribute('aria-label', 'Document formatting');

  const keepSel = (event) => {
    if (event) event.preventDefault();
    if (typeof driver.saveSelection === 'function') driver.saveSelection();
  };

  registry.groups().forEach((group) => {
    const wrap = el('div', { className: 'mhws-composer-group' });
    wrap.dataset.group = group;
    registry.extensions.filter((x) => (x.group || 'more') === group).forEach((ext) => {
      const kind = ext.kind || 'button';
      if (kind === 'select') {
        const cluster = el('label', { className: 'mhws-composer-cluster', title: ext.title || ext.id });
        cluster.append(iconOrText(ext));
        const select = el('select', {
          className: 'mhws-composer-select',
          title: ext.title || ext.id,
          'aria-label': ext.title || ext.id,
        });
        select.dataset.command = ext.command || ext.id;
        (ext.options || []).forEach((opt, i) => {
          const o = document.createElement('option');
          o.value = opt.value;
          o.textContent = opt.label;
          if (i === 0) o.selected = true;
          select.append(o);
        });
        select.addEventListener('mousedown', () => {
          if (typeof driver.saveSelection === 'function') driver.saveSelection();
        });
        select.addEventListener('change', () => {
          const value = select.value;
          if (ext.command) driver.run(ext.command, value);
          else if (ext.run) ext.run(driver, value);
        });
        cluster.append(select);
        wrap.append(cluster);
        return;
      }
      if (kind === 'color') {
        const cluster = el('label', { className: 'mhws-composer-color-wrap', title: ext.title || ext.id });
        cluster.append(iconOrText(ext));
        const input = el('input', {
          type: 'color',
          className: 'mhws-composer-color',
          title: ext.title || ext.id,
          value: ext.value || '#12233f',
          'aria-label': ext.title || ext.id,
        });
        input.addEventListener('mousedown', (event) => {
          keepSel(event);
          if (typeof driver.saveSelection === 'function') driver.saveSelection();
        });
        input.addEventListener('input', () => {
          driver.run(ext.command, input.value);
        });
        cluster.append(input);
        wrap.append(cluster);
        return;
      }
      if (kind === 'file') {
        const btn = el('button', {
          type: 'button',
          className: 'mhws-composer-btn',
          title: ext.title || ext.id,
          'aria-label': ext.title || ext.id,
        });
        btn.append(iconOrText(ext));
        btn.addEventListener('mousedown', keepSel);
        btn.addEventListener('click', () => onImageFile && onImageFile(ext));
        wrap.append(btn);
        return;
      }
      const btn = el('button', {
        type: 'button',
        className: 'mhws-composer-btn',
        title: ext.title || ext.id,
        'aria-label': ext.title || ext.id,
      });
      btn.append(iconOrText(ext));
      btn.addEventListener('mousedown', keepSel);
      if (ext.id === 'insertTable') {
        bindInsertTableButton(btn, driver);
        wrap.append(btn);
        return;
      }
      if (ext.id === 'pageMargins') {
        bindPageMarginsButton(btn, driver);
        wrap.append(btn);
        return;
      }
      btn.addEventListener('click', () => {
        if (ext.run) ext.run(driver);
        else if (ext.command) driver.run(ext.command);
      });
      wrap.append(btn);
    });
    toolbarEl.append(wrap);
  });
}
