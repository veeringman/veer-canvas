/**
 * Original / panel / full-window chrome. Any shell can attach this;
 * only one composer is expanded at a time.
 */

const LABELS = {
  original: 'Original layout',
  panel: 'Panel mode',
  window: 'Full window',
};

const ICON = {
  original: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="6" width="16" height="12" rx="1.5"/><path d="M8 10h8M8 14h5"/></svg>',
  panel: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M15 5v14"/></svg>',
  window: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4H5v4"/><path d="M15 4h4v4"/><path d="M9 20H5v-4"/><path d="M15 20h4v-4"/></svg>',
  windowExit: '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 8H5V4"/><path d="M15 8h4V4"/><path d="M9 16H5v4"/><path d="M15 16h4v4"/></svg>',
};

const bound = new Map();
let expandedShell = null;
let escapeBound = false;

function ensureBackdrop() {
  let node = document.getElementById('mhwsComposeBackdrop');
  if (node) return node;
  node = document.createElement('button');
  node.type = 'button';
  node.id = 'mhwsComposeBackdrop';
  node.className = 'mhws-composer-backdrop';
  node.hidden = true;
  node.setAttribute('aria-label', 'Restore original composer layout');
  node.addEventListener('click', () => {
    if (expandedShell) setShellLayout(expandedShell, 'original');
  });
  document.body.appendChild(node);
  return node;
}

function ensureEscape() {
  if (escapeBound) return;
  escapeBound = true;
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !expandedShell) return;
    if (document.getElementById('docViewerDialog')?.open) return;
    event.preventDefault();
    setShellLayout(expandedShell, 'original');
  });
}

function persist(key, mode) {
  if (!key) return;
  try {
    localStorage.setItem(key, mode);
  } catch {
    /* ignore */
  }
}

function readSaved(key) {
  if (!key) return '';
  try {
    const raw = localStorage.getItem(key) || '';
    return LABELS[raw] ? raw : '';
  } catch {
    return '';
  }
}

function ensureChrome(shell, { langForm } = {}) {
  let chrome = shell.querySelector(':scope > .mhws-composer-chrome');
  if (chrome) return chrome;
  chrome = document.createElement('div');
  chrome.className = 'mhws-composer-chrome';
  chrome.setAttribute('role', 'toolbar');
  chrome.setAttribute('aria-label', 'Composer layout');
  chrome.innerHTML = `
    <span class="mhws-composer-chrome-title sr-only">Original layout</span>
    <div class="mhws-composer-chrome-actions">
      ${langForm ? `
        <div class="mhws-composer-lang-group" role="group" aria-label="Writing language">
          <button type="button" class="mhws-composer-btn mhws-composer-lang-btn is-active" data-compose-lang="en" title="English">EN</button>
          <button type="button" class="mhws-composer-btn mhws-composer-lang-btn" data-compose-lang="hi" title="Hindi">हिं</button>
        </div>` : ''}
      <div class="mhws-composer-layout-group">
        <button type="button" class="mhws-composer-btn" data-compose-layout="original" title="Restore original layout" aria-label="Restore original layout">${ICON.original}</button>
        <button type="button" class="mhws-composer-btn" data-compose-layout="panel" title="Panel mode" aria-label="Panel mode">${ICON.panel}</button>
        <button type="button" class="mhws-composer-btn" data-compose-layout="window" title="Full window" aria-label="Full window">${ICON.window}</button>
      </div>
    </div>
  `;
  shell.prepend(chrome);
  return chrome;
}

function syncChrome(shell, mode) {
  const chrome = shell.querySelector(':scope > .mhws-composer-chrome');
  const title = chrome?.querySelector('.mhws-composer-chrome-title');
  if (title) title.textContent = LABELS[mode] || LABELS.original;
  chrome?.querySelectorAll('[data-compose-layout]').forEach((btn) => {
    const kind = btn.getAttribute('data-compose-layout');
    const on = kind === mode;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (kind === 'window') {
      btn.innerHTML = on ? ICON.windowExit : ICON.window;
      btn.title = on ? 'Exit full window' : 'Full window';
      btn.setAttribute('aria-label', btn.title);
    } else if (kind === 'panel') {
      btn.title = on ? 'Exit panel mode' : 'Panel mode';
      btn.setAttribute('aria-label', btn.title);
    }
  });
}

function ensureAnchor(shell) {
  const existingId = shell.dataset.anchorId;
  if (existingId) {
    const found = document.getElementById(existingId);
    if (found) return found;
  }
  const anchor = document.createElement('div');
  anchor.id = `mhws-composer-anchor-${Math.random().toString(36).slice(2, 9)}`;
  anchor.className = 'mhws-composer-anchor';
  anchor.setAttribute('aria-hidden', 'true');
  shell.dataset.anchorId = anchor.id;
  shell.parentNode.insertBefore(anchor, shell);
  return anchor;
}

function parkShell(shell) {
  const anchor = ensureAnchor(shell);
  if (shell.parentElement !== document.body) {
    document.body.appendChild(shell);
  }
  return anchor;
}

function restoreShell(shell) {
  const anchor = shell.dataset.anchorId ? document.getElementById(shell.dataset.anchorId) : null;
  if (anchor && anchor.parentNode) {
    anchor.parentNode.insertBefore(shell, anchor.nextSibling);
  }
}

function applyDom(shell, mode) {
  const overlay = mode === 'panel' || mode === 'window';
  if (overlay) parkShell(shell);
  else restoreShell(shell);
  shell.classList.remove('is-layout-panel', 'is-layout-window');
  shell.dataset.layout = mode;
  if (mode === 'panel') shell.classList.add('is-layout-panel');
  if (mode === 'window') shell.classList.add('is-layout-window');
  document.documentElement.classList.toggle('mhws-compose-overlay', overlay && expandedShell === shell);
  document.documentElement.classList.toggle('mhws-compose-panel', mode === 'panel' && expandedShell === shell);
  document.documentElement.classList.toggle('mhws-compose-window', mode === 'window' && expandedShell === shell);
  const back = ensureBackdrop();
  back.hidden = !overlay;
  if (overlay) {
    window.requestAnimationFrame(() => {
      const paper = shell.querySelector('[data-author-pane]:not([hidden]) .mhws-composer-paper')
        || shell.querySelector('.mhws-composer-paper');
      paper?.focus();
    });
  }
}

function setShellLayout(shell, mode, { skipPersist } = {}) {
  const next = LABELS[mode] ? mode : 'original';
  const rec = bound.get(shell);
  if (next !== 'original' && expandedShell && expandedShell !== shell) {
    setShellLayout(expandedShell, 'original', { skipPersist: true });
  }
  expandedShell = next === 'original' ? null : shell;
  applyDom(shell, next);
  syncChrome(shell, next);
  if (rec && !skipPersist) persist(rec.storageKey, next);
  if (rec?.onChange) rec.onChange(next);
}

export function attachLayout(shell, opts = {}) {
  if (!shell) {
    return { setLayout() {}, getLayout: () => 'original', destroy() {} };
  }
  const storageKey = opts.storageKey || '';
  const chrome = ensureChrome(shell, { langForm: opts.langForm });
  ensureBackdrop();
  ensureEscape();

  if (!shell.dataset.layoutBound) {
    shell.dataset.layoutBound = '1';
    chrome.addEventListener('click', (event) => {
      const layoutBtn = event.target.closest('[data-compose-layout]');
      if (layoutBtn) {
        const requested = layoutBtn.getAttribute('data-compose-layout');
        const current = shell.dataset.layout || 'original';
        const next = requested && requested === current && requested !== 'original'
          ? 'original'
          : requested;
        setShellLayout(shell, next);
        return;
      }
      const langBtn = event.target.closest('[data-compose-lang]');
      if (langBtn && opts.langForm) {
        const lang = langBtn.getAttribute('data-compose-lang');
        document.querySelector(
          `.author-lang-toggle[data-author-form="${opts.langForm}"] [data-author-lang="${lang}"]`,
        )?.click();
      }
    });
  }

  bound.set(shell, { storageKey, onChange: opts.onChange || null });
  const saved = opts.applySaved === false ? '' : readSaved(storageKey);
  setShellLayout(shell, saved || 'original', { skipPersist: !saved });
  return {
    setLayout(mode, extra) {
      setShellLayout(shell, mode, extra);
    },
    applySaved() {
      const next = readSaved(storageKey);
      if (next) setShellLayout(shell, next);
    },
    getLayout() {
      return shell.dataset.layout || 'original';
    },
    destroy() {
      if (expandedShell === shell) setShellLayout(shell, 'original', { skipPersist: true });
      bound.delete(shell);
    },
  };
}

export function collapseAll() {
  if (expandedShell) setShellLayout(expandedShell, 'original', { skipPersist: true });
}

export function extractBody(html) {
  const raw = String(html || '').trim();
  if (!raw) return '<p></p>';
  if (typeof DOMParser === 'undefined') return raw;
  const doc = new DOMParser().parseFromString(raw, 'text/html');
  const content = doc.querySelector('.body-area')
    || doc.querySelector('main.body')
    || doc.querySelector('.content')
    || doc.querySelector('main')
    || doc.body;
  const inner = (content && content.innerHTML.trim()) || raw;
  const mark = raw.match(/<!--\s*mhws-margins:[^>]*-->/i);
  if (mark && inner && !/mhws-margins:/.test(inner)) {
    return `${mark[0]}${inner}` || '<p></p>';
  }
  return inner || '<p></p>';
}
