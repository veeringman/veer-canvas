import { iconSvg } from './icons.js';
import { wrappedImageHtml, applyImageLayout } from './driver-dom.js';

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
    'data-img-act': action,
  });
  btn.append(iconSvg(icon) || document.createTextNode(title));
  return btn;
}

function sizeBtn(pct) {
  const btn = el('button', {
    type: 'button',
    className: 'mhws-composer-btn mhws-img-size',
    title: `${pct}% of page width`,
    'aria-label': `${pct} percent width`,
    'data-img-act': `size-${pct}`,
  });
  btn.textContent = String(pct);
  return btn;
}

const CORNERS = ['nw', 'ne', 'sw', 'se'];

export function ensureImageWrap(img) {
  if (!img || img.tagName !== 'IMG') return null;
  const existing = img.closest('.mhws-img');
  if (existing) return existing;
  const wrap = document.createElement('span');
  wrap.className = 'mhws-img';
  wrap.contentEditable = 'false';
  wrap.dataset.width = '40';
  wrap.dataset.float = 'none';
  img.removeAttribute('width');
  img.removeAttribute('height');
  img.draggable = false;
  img.replaceWith(wrap);
  wrap.append(img);
  applyImageLayout(wrap, 40, 'none');
  return wrap;
}

function widthOf(wrap) {
  const n = Number.parseInt(wrap?.dataset.width || '40', 10);
  return Number.isFinite(n) ? Math.max(10, Math.min(100, n)) : 40;
}

export function attachImageUi({ host, toolbar, driver, onChange }) {
  if (!host || !toolbar || !driver) {
    return { destroy() {} };
  }
  const wrap = driver.wrap || host.parentElement;
  const tools = el('div', {
    className: 'mhws-img-tools',
    hidden: true,
    role: 'toolbar',
    'aria-label': 'Image',
  });
  tools.append(
    el('span', { className: 'mhws-img-tools-label' }, ['Image']),
    sizeBtn(25),
    sizeBtn(40),
    sizeBtn(60),
    sizeBtn(100),
    toolBtn('alignLeft', 'Float left', 'float-left'),
    toolBtn('alignCenter', 'Centre on line', 'float-center'),
    toolBtn('alignRight', 'Float right', 'float-right'),
    toolBtn('imageInline', 'In line with text', 'float-none'),
    toolBtn('tableDelete', 'Delete image', 'delete'),
  );
  toolbar.after(tools);

  const overlay = el('div', { className: 'mhws-img-overlay', hidden: true });
  wrap.append(overlay);

  let active = null;
  let drag = null;

  function notify() {
    if (typeof onChange === 'function') onChange();
  }

  function hide() {
    active?.classList.remove('is-selected');
    active = null;
    overlay.hidden = true;
    overlay.innerHTML = '';
    tools.hidden = true;
  }

  function layout() {
    if (!active || !host.contains(active)) {
      hide();
      return;
    }
    const wrapRect = wrap.getBoundingClientRect();
    const r = active.getBoundingClientRect();
    overlay.hidden = false;
    tools.hidden = false;
    overlay.style.left = `${r.left - wrapRect.left + wrap.scrollLeft}px`;
    overlay.style.top = `${r.top - wrapRect.top + wrap.scrollTop}px`;
    overlay.style.width = `${r.width}px`;
    overlay.style.height = `${r.height}px`;
    overlay.innerHTML = '';
    CORNERS.forEach((corner) => {
      overlay.append(el('div', {
        className: `mhws-img-handle is-${corner}`,
        'data-corner': corner,
        title: 'Resize',
      }));
    });
  }

  function showFor(node) {
    if (!node) {
      hide();
      return;
    }
    if (active && active !== node) active.classList.remove('is-selected');
    active = node;
    active.classList.add('is-selected');
    layout();
    window.requestAnimationFrame(layout);
  }

  function apply(pct, flt) {
    if (!active) return;
    applyImageLayout(active, pct, flt);
    layout();
    notify();
  }

  tools.addEventListener('mousedown', (event) => event.preventDefault());
  tools.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-img-act]');
    if (!btn || !active) return;
    const act = btn.getAttribute('data-img-act') || '';
    if (act.startsWith('size-')) {
      apply(Number(act.slice(5)), active.dataset.float || 'none');
      return;
    }
    if (act === 'delete') {
      const next = active.nextSibling;
      active.remove();
      hide();
      notify();
      if (next) {
        const range = document.createRange();
        range.setStart(next, 0);
        range.collapse(true);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      return;
    }
    if (act.startsWith('float-')) {
      apply(widthOf(active), act.slice(6));
    }
  });

  function caretRange(x, y) {
    if (document.caretRangeFromPoint) return document.caretRangeFromPoint(x, y);
    const pos = document.caretPositionFromPoint?.(x, y);
    if (!pos) return null;
    const range = document.createRange();
    range.setStart(pos.offsetNode, pos.offset);
    range.collapse(true);
    return range;
  }

  function onPointerMove(event) {
    if (!drag) return;
    if (drag.kind === 'resize') {
      const hostW = Math.max(1, host.clientWidth);
      const dx = event.clientX - drag.startX;
      const sign = (drag.corner === 'ne' || drag.corner === 'se') ? 1 : -1;
      const px = Math.max(hostW * 0.1, Math.min(hostW, drag.startW + sign * dx));
      const pct = Math.round((px / hostW) * 100);
      applyImageLayout(drag.node, pct, drag.node.dataset.float || 'none');
      layout();
      return;
    }
    if (drag.kind === 'move') {
      const dist = Math.abs(event.clientX - drag.startX) + Math.abs(event.clientY - drag.startY);
      if (dist > 4) drag.moved = true;
      drag.node.classList.toggle('is-dragging', drag.moved);
    }
  }

  function onPointerUp(event) {
    if (!drag) return;
    const current = drag;
    drag = null;
    document.removeEventListener('pointermove', onPointerMove);
    document.removeEventListener('pointerup', onPointerUp);
    document.body.classList.remove('mhws-img-resizing');
    current.node.classList.remove('is-dragging');
    if (current.kind === 'resize') {
      notify();
      layout();
      return;
    }
    if (current.kind === 'move' && current.moved) {
      const range = caretRange(event.clientX, event.clientY);
      if (range && host.contains(range.commonAncestorContainer) && !current.node.contains(range.commonAncestorContainer)) {
        try {
          range.insertNode(current.node);
        } catch (_err) {
          /* ignore invalid insert */
        }
      }
      notify();
    }
    showFor(host.contains(current.node) ? current.node : null);
  }

  function startDrag(kind, event, node, corner) {
    event.preventDefault();
    event.stopPropagation();
    drag = {
      kind,
      node,
      corner,
      startX: event.clientX,
      startY: event.clientY,
      startW: node.getBoundingClientRect().width,
      moved: false,
    };
    if (kind === 'resize') document.body.classList.add('mhws-img-resizing');
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
  }

  overlay.addEventListener('pointerdown', onOverlayPointerDown);
  host.addEventListener('pointerdown', onHostPointerDown);
  host.addEventListener('click', onHostClick);

  host.querySelectorAll('img').forEach((img) => {
    if (!img.closest('.mhws-img') && !img.classList.contains('wm')) {
      ensureImageWrap(img);
    }
  });

  function imageNodeFromEvent(event) {
    const t = event.target;
    if (!(t instanceof Element) || !host.contains(t)) return null;
    const wrapEl = t.closest('.mhws-img');
    if (wrapEl && host.contains(wrapEl)) return wrapEl;
    const img = t.closest('img');
    if (img && host.contains(img) && !img.classList.contains('wm')) {
      return ensureImageWrap(img);
    }
    return null;
  }

  function onOverlayPointerDown(event) {
    const handle = event.target.closest('.mhws-img-handle');
    if (handle && active) {
      startDrag('resize', event, active, handle.getAttribute('data-corner') || 'se');
    }
  }

  function onHostPointerDown(event) {
    const node = imageNodeFromEvent(event);
    if (!node) return;
    showFor(node);
    startDrag('move', event, node, '');
  }

  function onHostClick(event) {
    const node = imageNodeFromEvent(event);
    if (node) {
      showFor(node);
      return;
    }
    if (!event.target.closest('.mhws-img') && !event.target.closest('.mhws-img-overlay')) {
      hide();
    }
  }

  function onKey(event) {
    if (!active || !host.contains(active)) return;
    if (event.key !== 'Backspace' && event.key !== 'Delete') return;
    event.preventDefault();
    event.stopPropagation();
    active.remove();
    hide();
    notify();
  }

  wrap.addEventListener('scroll', layout);
  window.addEventListener('resize', layout);
  host.addEventListener('keydown', onKey, true);

  return {
    destroy() {
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
      overlay.removeEventListener('pointerdown', onOverlayPointerDown);
      host.removeEventListener('pointerdown', onHostPointerDown);
      host.removeEventListener('click', onHostClick);
      host.removeEventListener('keydown', onKey, true);
      wrap.removeEventListener('scroll', layout);
      window.removeEventListener('resize', layout);
      tools.remove();
      overlay.remove();
      document.body.classList.remove('mhws-img-resizing');
    },
  };
}

export { wrappedImageHtml };
