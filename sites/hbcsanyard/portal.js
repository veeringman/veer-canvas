(() => {
  const state = {
    session: null,
    pendingHouse: '',
    pendingMemberId: '',
    pendingContact: false,
    missingEmail: false,
    missingPhone: false,
    authbuddyLinked: false,
    authbuddyReachable: false,
    preferAuthbuddy: false,
    authbuddyUsername: '',
    authbuddyHasPasskey: false,
    pendingMemberName: '',
    pendingEmailMasked: '',
    msgThreads: [],
    msgActiveThreadId: null,
    msgActiveThread: null,
    msgCanModerate: false,
    msgCanCleanup: false,
    msgCanManage: false,
    msgCanLeave: false,
    msgCanEscalate: false,
    msgPollTimer: null,
    msgAttachFiles: [],
    msgLastId: null,
    msgIsAiThread: false,
    msgSending: false,
    msgCreateSelected: [],
    msgManageThreadId: null,
    parkingOcr: null,
  };
  let rosterCache = [];
  const notifyState = { pending: [], recent: [], items: [], chatUnread: 0, unreadCount: 0, timer: null };
  const MSG_EMOJI = ['😀', '😁', '😂', '😊', '😍', '🤔', '👍', '👏', '🙏', '❤️', '🎉', '✅', '❌', '🙂', '😅', '🙌', '💪', '🌹', '🏠', '☀️'];
  const MSG_ATTACH_MAX_BYTES = 5 * 1024 * 1024;
  const MSG_ATTACH_MAX_FILES = 3;
  const MSG_ATTACH_HINT_DEFAULT = 'Images or PDF · max 5 MB each · up to 3';
  const MSG_ATTACH_TYPES = new Set([
    'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf',
  ]);

  let publicOriginCache = '';
  async function publicSiteOrigin() {
    if (publicOriginCache) return publicOriginCache;
    const tag = document.querySelector('meta[name="public-origin"]');
    if (tag && tag.content) {
      publicOriginCache = String(tag.content).replace(/\/$/, '');
      return publicOriginCache;
    }
    try {
      const meta = await fetch('site-meta.json', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : {}));
      const origin = meta.publicOrigin || meta.publicUrl;
      if (origin) {
        publicOriginCache = String(origin).replace(/\/$/, '');
        return publicOriginCache;
      }
    } catch (_e) { /* ignore */ }
    publicOriginCache = window.location.origin;
    return publicOriginCache;
  }

  function msgAttachAllowed(file) {
    const name = (file?.name || '').toLowerCase();
    const type = (file?.type || '').toLowerCase();
    if (MSG_ATTACH_TYPES.has(type)) return true;
    return /\.(jpe?g|png|webp|gif|pdf)$/.test(name);
  }

  function formatMsgAttachSize(n) {
    const num = Number(n) || 0;
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(0)} KB`;
    return `${(num / (1024 * 1024)).toFixed(1)} MB`;
  }

  function setMsgAttachHint(text, { isError = false } = {}) {
    const hint = el('msgAttachHint');
    if (!hint) return;
    hint.textContent = text || MSG_ATTACH_HINT_DEFAULT;
    hint.classList.toggle('is-error', Boolean(isError));
  }

  function syncMsgAttachFiles(fileList) {
    const picked = Array.from(fileList || []);
    const accepted = [];
    const problems = [];
    for (const f of picked) {
      if (!msgAttachAllowed(f)) {
        problems.push(`${f.name}: use JPG, PNG, WebP, GIF, or PDF`);
        continue;
      }
      if ((f.size || 0) > MSG_ATTACH_MAX_BYTES) {
        problems.push(`${f.name}: over 5 MB (${formatMsgAttachSize(f.size)})`);
        continue;
      }
      accepted.push(f);
      if (accepted.length >= MSG_ATTACH_MAX_FILES) break;
    }
    if (picked.length > MSG_ATTACH_MAX_FILES) {
      problems.push(`Only the first ${MSG_ATTACH_MAX_FILES} files were kept`);
    }
    state.msgAttachFiles = accepted;
    if (accepted.length) {
      const names = accepted.map((f) => `${f.name} (${formatMsgAttachSize(f.size)})`).join(', ');
      setMsgAttachHint(problems.length ? `${names} · ${problems[0]}` : names, { isError: problems.length > 0 });
    } else if (problems.length) {
      setMsgAttachHint(problems[0], { isError: true });
    } else {
      setMsgAttachHint(MSG_ATTACH_HINT_DEFAULT);
    }
    return accepted;
  }

  const el = (id) => document.getElementById(id);

  const IST_TZ = 'Asia/Kolkata';

  /** Format an ISO / Date value as date+time in IST (Asia/Kolkata). */
  function formatIstDateTime(iso, { withSeconds = false } = {}) {
    if (!iso) return '';
    try {
      const d = iso instanceof Date ? iso : new Date(iso);
      if (Number.isNaN(d.getTime())) return String(iso);
      return d.toLocaleString('en-IN', {
        timeZone: IST_TZ,
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        ...(withSeconds ? { second: '2-digit' } : {}),
        hour12: true,
      });
    } catch (_e) {
      return String(iso);
    }
  }

  /** Format a calendar date or timestamp as a date in IST. */
  function formatIstDate(iso) {
    if (!iso) return '';
    const s = String(iso).trim();
    try {
      if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
        const d = new Date(`${s}T12:00:00+05:30`);
        return d.toLocaleDateString('en-IN', {
          timeZone: IST_TZ,
          day: '2-digit',
          month: 'short',
          year: 'numeric',
        });
      }
      const d = new Date(s);
      if (Number.isNaN(d.getTime())) return s.slice(0, 10);
      return d.toLocaleDateString('en-IN', {
        timeZone: IST_TZ,
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      });
    } catch (_e) {
      return s.slice(0, 10);
    }
  }

  /** Today's calendar date in IST as YYYY-MM-DD (for date inputs). */
  function todayIstDate() {
    return new Date().toLocaleDateString('en-CA', { timeZone: IST_TZ });
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const RWA_TOKEN_KEY = 'hbcsanyard_rwa_token';
  const LAST_HOUSE_KEY = 'hbcsanyard_last_house';

  function loadStoredToken() {
    try { return localStorage.getItem(RWA_TOKEN_KEY) || ''; } catch (_e) { return ''; }
  }

  function saveStoredToken(token) {
    try {
      if (token) localStorage.setItem(RWA_TOKEN_KEY, String(token));
      else localStorage.removeItem(RWA_TOKEN_KEY);
    } catch (_e) { /* ignore */ }
  }

  function loadLastHouseId() {
    try { return localStorage.getItem(LAST_HOUSE_KEY) || ''; } catch (_e) { return ''; }
  }

  function saveLastHouseId(houseId) {
    const id = String(houseId || '').trim();
    if (!id || id.startsWith('__')) return;
    try { localStorage.setItem(LAST_HOUSE_KEY, id); } catch (_e) { /* ignore */ }
  }

  function clearPersistedAuth() {
    saveStoredToken('');
  }

  async function api(path, options = {}) {
    const isForm = options.body instanceof FormData;
    const headers = { ...(options.headers || {}) };
    if (!isForm) headers['Content-Type'] = 'application/json';
    const token = state.session?.token || loadStoredToken();
    if (token) headers['X-RWA-Token'] = token;
    let res;
    try {
      res = await fetch(path, {
        credentials: 'same-origin',
        ...options,
        headers,
      });
    } catch (_err) {
      throw new Error('Could not reach the server. Try again.');
    }
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_err) {
      data = {};
    }
    if (res.status === 401 && path.startsWith('/api/rwa/') && path !== '/api/rwa/login' && !path.includes('/otp/')) {
      clearPersistedAuth();
    }
    if (!res.ok) throw new Error(friendlyApiError(res, data));
    return data;
  }

  async function apiBinary(path, options = {}) {
    const isForm = options.body instanceof FormData;
    const headers = { ...(options.headers || {}) };
    if (!isForm) headers['Content-Type'] = 'application/json';
    const token = state.session?.token || loadStoredToken();
    if (token) headers['X-RWA-Token'] = token;
    let res;
    try {
      res = await fetch(path, {
        credentials: 'same-origin',
        ...options,
        headers,
      });
    } catch (_err) {
      throw new Error('Could not reach the server. Try again.');
    }
    if (!res.ok) {
      let data = {};
      try {
        data = JSON.parse(await res.text() || '{}');
      } catch (_err) {
        data = {};
      }
      if (res.status === 401 && path.startsWith('/api/rwa/')) clearPersistedAuth();
      throw new Error(friendlyApiError(res, data));
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    let filename = 'document';
    try {
      filename = decodeURIComponent((star && star[1]) || (plain && plain[1]) || filename);
    } catch (_err) {
      filename = (plain && plain[1]) || filename;
    }
    return { blob, filename, mime: res.headers.get('Content-Type') || blob.type };
  }

  function triggerBlobDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'document';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2500);
  }

  function friendlyApiError(res, data) {
    const status = Number(res?.status) || 0;
    const raw = String((data && (data.error || data.message)) || '').trim();
    const mapped = {
      400: 'That could not be saved.',
      401: 'Please sign in again.',
      403: "You don't have access to that.",
      404: 'That was not found.',
      405: 'That action is not available.',
      408: 'That took too long. Try again.',
      409: 'That conflicts with existing data.',
      413: 'That file is too large.',
      415: 'That file type is not supported.',
      422: 'Please check the details and try again.',
      429: 'Too many tries. Wait a moment.',
      500: 'Something went wrong. Try again.',
      502: 'Service is busy. Try again.',
      503: 'Service is restarting. Try again.',
      504: 'That took too long. Try again.',
    };
    const looksTech = !raw
      || raw.length > 120
      || /internal server error|traceback|exception|werkzeug|nginx|bad gateway|method not allowed|not found|failed to fetch|http\s*\d|sql(ite)?|typeerror/i.test(raw);
    if (status >= 500) {
      if (raw && !looksTech) return raw;
      return mapped[status] || mapped[500];
    }
    if (raw && !looksTech) return raw;
    return mapped[status] || 'Something went wrong. Try again.';
  }

  let docViewerObjectUrl = '';
  let docViewerStreamUrl = '';
  let docViewerTemplateId = '';
  // Non-modal doc viewer sits under modal top-layer dialogs (vault). Park them while viewing.
  let docViewerResumeVaultHouseId = '';
  let docViewerProtectActive = false;
  let infoCentreProtectBound = false;
  let infoWatermarkTimer = 0;

  const INFO_IFRAME_PROTECT_CSS = `
html,body{-webkit-user-select:none!important;user-select:none!important;-webkit-touch-callout:none!important}
@media print{body{visibility:hidden!important}body::before{content:"Printing Information Centre documents is not allowed.";visibility:visible;display:block;padding:2rem;font:600 1rem/1.4 system-ui,sans-serif}}
#ic-protect-shield{position:fixed;inset:0;z-index:99999;display:none;align-items:center;justify-content:center;padding:1.5rem;text-align:center;background:#0e182c;color:#f3f1ea;font:600 1rem/1.45 system-ui,sans-serif}
html.is-capture-guard #ic-protect-shield{display:flex}
html.is-capture-guard body>*:not(#ic-protect-shield){visibility:hidden!important}
#ic-reader-watermark{position:fixed;inset:0;z-index:99990;pointer-events:none;overflow:hidden;opacity:.28}
#ic-reader-watermark .tiles{position:absolute;inset:-12%;display:grid;grid-template-columns:repeat(3,1fr);gap:2.2rem 1rem;transform:rotate(-28deg);color:#0e182c;font:700 12px/1.35 system-ui,sans-serif;text-align:center}
#ic-reader-watermark .tiles span{white-space:nowrap}
`;

  function infoProtectMarkText() {
    const r = state.session?.resident || {};
    const plot = String(r.houseId || r.plotNo || (r.superAdmin ? 'EC' : 'member')).trim();
    const name = String(r.name || '').trim();
    const when = new Date().toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
    return `Himuda Housing Colony Sanyard · Plot ${plot}${name ? ` · ${name}` : ''} · ${when} · view only`;
  }

  function fillWatermarkNode(node, mark) {
    if (!node) return;
    const text = mark || infoProtectMarkText();
    node.setAttribute('data-mark', text);
    const tiles = Array.from({ length: 24 }, () => `<span>${escapeHtml(text)}</span>`).join('');
    node.innerHTML = `<div class="doc-viewer-watermark-tiles tiles">${tiles}</div>`;
  }

  function clearInfoWatermarks() {
    if (infoWatermarkTimer) {
      window.clearInterval(infoWatermarkTimer);
      infoWatermarkTimer = 0;
    }
    const panel = el('panel-info');
    panel?.classList.remove('is-watermarked');
    const panelWm = el('panelInfoWatermark');
    if (panelWm) {
      panelWm.innerHTML = '';
      panelWm.removeAttribute('data-mark');
    }
    const docWm = el('docViewerWatermark');
    if (docWm) {
      docWm.hidden = true;
      docWm.innerHTML = '';
      docWm.removeAttribute('data-mark');
      docWm.setAttribute('aria-hidden', 'true');
    }
    el('docViewerDialog')?.classList.remove('is-content-protected', 'is-capture-guard');
    try {
      const frame = el('docViewerFrame');
      const doc = frame?.contentDocument;
      const iframeWm = doc?.getElementById('ic-reader-watermark');
      if (iframeWm) iframeWm.remove();
      doc?.documentElement?.classList.remove('is-capture-guard');
    } catch (_err) { /* ignore */ }
  }

  function refreshInfoWatermarks() {
    if (!isInfoCentreProtectEnforced()) {
      clearInfoWatermarks();
      return;
    }
    const mark = infoProtectMarkText();
    fillWatermarkNode(el('docViewerWatermark'), mark);
    const panelWm = el('panelInfoWatermark');
    const panel = el('panel-info');
    if (panelWm && panel && !panel.hidden) {
      fillWatermarkNode(panelWm, mark);
      panel.classList.add('is-watermarked');
    }
    try {
      const frame = el('docViewerFrame');
      const doc = frame && !frame.hidden ? frame.contentDocument : null;
      const iframeWm = doc?.getElementById('ic-reader-watermark');
      if (iframeWm) {
        const tiles = Array.from({ length: 24 }, () => `<span>${escapeHtml(mark)}</span>`).join('');
        iframeWm.innerHTML = `<div class="tiles">${tiles}</div>`;
      }
    } catch (_err) { /* ignore */ }
  }

  function startInfoWatermarkClock() {
    if (!isInfoCentreProtectEnforced()) {
      clearInfoWatermarks();
      return;
    }
    refreshInfoWatermarks();
    if (infoWatermarkTimer) window.clearInterval(infoWatermarkTimer);
    infoWatermarkTimer = window.setInterval(refreshInfoWatermarks, 60_000);
  }

  function stopInfoWatermarkClockIfIdle() {
    if (!isInfoCentreProtectEnforced()) {
      clearInfoWatermarks();
      return;
    }
    const infoOpen = Boolean(el('panel-info') && !el('panel-info').hidden);
    if (infoOpen || docViewerProtectActive) {
      refreshInfoWatermarks();
      return;
    }
    clearInfoWatermarks();
  }

  function isInfoCentreProtectEnforced() {
    return Boolean(state.session?.features?.infoCentreProtect);
  }

  function setInfoCentreProtectFeature(on) {
    if (!state.session) return;
    state.session.features = { ...(state.session.features || {}), infoCentreProtect: Boolean(on) };
    applyInfoCentreProtectMode();
  }

  function applyInfoCentreProtectMode() {
    const on = isInfoCentreProtectEnforced();
    document.body.classList.toggle('info-protect-enforced', on);
    if (!on) {
      document.body.classList.remove('is-info-capture-guard');
      docViewerProtectActive = false;
      clearInfoWatermarks();
      return;
    }
    if (el('panel-info') && !el('panel-info').hidden) startInfoWatermarkClock();
    syncInfoCentreCaptureGuard();
  }

  function syncInfoCentreCaptureGuard() {
    if (!isInfoCentreProtectEnforced()) {
      document.body.classList.remove('is-info-capture-guard');
      el('docViewerDialog')?.classList.remove('is-capture-guard');
      const shield = el('docViewerProtectShield');
      if (shield) {
        shield.hidden = true;
        shield.setAttribute('aria-hidden', 'true');
      }
      return;
    }
    const infoOpen = Boolean(el('panel-info') && !el('panel-info').hidden);
    const viewerProtected = Boolean(
      docViewerProtectActive && el('docViewerDialog')?.open,
    );
    // Only when the browser tab is actually hidden — not on blur/iframe focus
    // (iframes steal parent focus and were blanking the page while reading).
    const away = document.visibilityState !== 'visible';
    document.body.classList.toggle('is-info-capture-guard', infoOpen && away && !viewerProtected);
    const dialog = el('docViewerDialog');
    if (dialog) {
      dialog.classList.toggle('is-capture-guard', viewerProtected && away);
    }
    const shield = el('docViewerProtectShield');
    if (shield) {
      const show = viewerProtected && away;
      shield.hidden = !show;
      shield.setAttribute('aria-hidden', show ? 'false' : 'true');
    }
  }

  function injectInfoIframeProtect(frame) {
    if (!isInfoCentreProtectEnforced()) return;
    try {
      const doc = frame?.contentDocument;
      if (!doc?.documentElement) return;
      if (!doc.getElementById('ic-portal-protect-style')) {
        const style = doc.createElement('style');
        style.id = 'ic-portal-protect-style';
        style.textContent = INFO_IFRAME_PROTECT_CSS;
        (doc.head || doc.documentElement).appendChild(style);
      }
      if (!doc.getElementById('ic-protect-shield')) {
        const shield = doc.createElement('div');
        shield.id = 'ic-protect-shield';
        shield.setAttribute('aria-hidden', 'true');
        shield.textContent = 'Return to this screen to continue reading.';
        doc.body?.appendChild(shield);
      }
      let wm = doc.getElementById('ic-reader-watermark');
      if (!wm) {
        wm = doc.createElement('div');
        wm.id = 'ic-reader-watermark';
        wm.setAttribute('aria-hidden', 'true');
        doc.body?.appendChild(wm);
      }
      const mark = infoProtectMarkText();
      const tiles = Array.from({ length: 24 }, () => `<span>${escapeHtml(mark)}</span>`).join('');
      wm.innerHTML = `<div class="tiles">${tiles}</div>`;
      const arm = (on) => {
        doc.documentElement.classList.toggle('is-capture-guard', Boolean(on));
        const s = doc.getElementById('ic-protect-shield');
        if (s) s.setAttribute('aria-hidden', on ? 'false' : 'true');
      };
      const sync = () => arm(doc.visibilityState !== 'visible');
      if (!doc.documentElement.dataset.icProtectBound) {
        doc.documentElement.dataset.icProtectBound = '1';
        doc.addEventListener('visibilitychange', sync);
        doc.addEventListener('contextmenu', (e) => e.preventDefault());
        doc.addEventListener('copy', (e) => e.preventDefault());
        doc.addEventListener('cut', (e) => e.preventDefault());
        doc.addEventListener('dragstart', (e) => e.preventDefault());
        doc.defaultView?.addEventListener('beforeprint', () => arm(true));
        doc.defaultView?.addEventListener('afterprint', sync);
        doc.addEventListener('keydown', (e) => {
          const key = String(e.key || '').toLowerCase();
          const mod = e.metaKey || e.ctrlKey;
          if (mod && (key === 'p' || key === 's')) e.preventDefault();
        });
      }
      sync();
    } catch (_err) {
      /* cross-origin or unavailable */
    }
  }

  function setDocViewerProtected(on) {
    docViewerProtectActive = Boolean(on) && isInfoCentreProtectEnforced();
    const dialog = el('docViewerDialog');
    dialog?.classList.toggle('is-content-protected', docViewerProtectActive);
    const wm = el('docViewerWatermark');
    if (wm) {
      wm.hidden = !docViewerProtectActive;
      wm.setAttribute('aria-hidden', docViewerProtectActive ? 'false' : 'true');
    }
    if (!docViewerProtectActive) {
      dialog?.classList.remove('is-capture-guard');
      const shield = el('docViewerProtectShield');
      if (shield) {
        shield.hidden = true;
        shield.setAttribute('aria-hidden', 'true');
      }
      stopInfoWatermarkClockIfIdle();
    } else {
      startInfoWatermarkClock();
    }
    syncInfoCentreCaptureGuard();
  }

  function bindInfoCentreProtectOnce() {
    if (infoCentreProtectBound) return;
    infoCentreProtectBound = true;
    document.addEventListener('visibilitychange', syncInfoCentreCaptureGuard);
    window.addEventListener('beforeprint', () => {
      if (!isInfoCentreProtectEnforced()) return;
      if ((el('panel-info') && !el('panel-info').hidden) || docViewerProtectActive) {
        document.body.classList.add('is-printing-info');
        syncInfoCentreCaptureGuard();
      }
    });
    window.addEventListener('afterprint', () => {
      document.body.classList.remove('is-printing-info');
      syncInfoCentreCaptureGuard();
    });
    const isComposerTarget = (node) => Boolean(
      node?.closest?.('.mhws-composer-paper, .mhws-composer-toolbar, .mhws-composer-shell [contenteditable="true"]'),
    );
    document.addEventListener('contextmenu', (event) => {
      if (!isInfoCentreProtectEnforced()) return;
      if (!docViewerProtectActive && !(el('panel-info') && !el('panel-info').hidden)) return;
      const t = event.target;
      if (isComposerTarget(t)) return;
      if (t?.closest?.('#panel-info, #docViewerDialog')) event.preventDefault();
    });
    document.addEventListener('copy', (event) => {
      if (!isInfoCentreProtectEnforced()) return;
      if (!docViewerProtectActive && !(el('panel-info') && !el('panel-info').hidden)) return;
      const t = event.target;
      if (isComposerTarget(t)) return;
      if (t?.closest?.('#panel-info, #docViewerDialog') || docViewerProtectActive) {
        event.preventDefault();
      }
    });
    document.addEventListener('cut', (event) => {
      if (!isInfoCentreProtectEnforced()) return;
      if (!docViewerProtectActive && !(el('panel-info') && !el('panel-info').hidden)) return;
      const t = event.target;
      if (isComposerTarget(t)) return;
      if (t?.closest?.('#panel-info, #docViewerDialog') || docViewerProtectActive) {
        event.preventDefault();
      }
    });
    document.addEventListener('keydown', (event) => {
      if (!isInfoCentreProtectEnforced()) return;
      if (!docViewerProtectActive && !(el('panel-info') && !el('panel-info').hidden)) return;
      const key = String(event.key || '').toLowerCase();
      const mod = event.metaKey || event.ctrlKey;
      if (mod && (key === 'p' || key === 's')) event.preventDefault();
    });
  }
  function parkModalsForDocViewer() {
    const vault = el('vaultDialog');
    if (vault?.open) {
      docViewerResumeVaultHouseId = vaultActiveHouseId
        || state.session?.resident?.houseId
        || docViewerResumeVaultHouseId
        || '';
      try { vault.close(); } catch (_err) { /* ignore */ }
    }
  }

  function resumeModalsAfterDocViewer() {
    const houseId = (docViewerResumeVaultHouseId || '').trim();
    docViewerResumeVaultHouseId = '';
    if (!houseId) return;
    // Defer so the viewer finishes leaving the top layer before reopening vault.
    window.setTimeout(() => {
      if (typeof openVault === 'function') {
        openVault(houseId).catch(console.error);
      }
    }, 0);
  }

  function closeDocViewer() {
    const dialog = el('docViewerDialog');
    if (dialog?.open) dialog.close();
    const frame = el('docViewerFrame');
    const img = el('docViewerImage');
    const embed = el('docViewerEmbed');
    const fallback = el('docViewerFallback');
    const loading = el('docViewerLoading');
    if (frame) {
      frame.hidden = true;
      frame.removeAttribute('src');
      frame.removeAttribute('sandbox');
      frame.onload = null;
    }
    if (embed) {
      embed.hidden = true;
      embed.removeAttribute('src');
    }
    if (img) {
      img.hidden = true;
      img.removeAttribute('src');
    }
    if (fallback) fallback.hidden = true;
    if (loading) loading.hidden = true;
    const dl = el('docViewerDownloadBtn');
    if (dl) {
      dl.hidden = true;
      dl.removeAttribute('href');
      dl.removeAttribute('download');
    }
    const printBtn = el('docViewerPrintBtn');
    if (printBtn) printBtn.hidden = true;
    [el('docViewerEditComposeBtn'), el('docViewerMobileEditComposeBtn')].forEach((btn) => {
      if (btn) btn.hidden = true;
    });
    docViewerTemplateId = '';
    const mobileDl = el('docViewerMobileDownloadBtn');
    if (mobileDl) {
      mobileDl.hidden = true;
      mobileDl.removeAttribute('href');
      mobileDl.removeAttribute('download');
    }
    const mobilePrint = el('docViewerMobilePrintBtn');
    if (mobilePrint) mobilePrint.hidden = true;
    const nt = el('docViewerNewTabBtn');
    if (nt) {
      nt.hidden = true;
      nt.removeAttribute('href');
    }
    if (docViewerObjectUrl) {
      URL.revokeObjectURL(docViewerObjectUrl);
      docViewerObjectUrl = '';
    }
    docViewerStreamUrl = '';
    setDocViewerProtected(false);
    resumeModalsAfterDocViewer();
  }

  function openDocViewerDialog(dialog) {
    if (!dialog || dialog.open) return;
    parkModalsForDocViewer();
    // Non-modal fullscreen sheet: Chrome PDF/HTML scroll works more reliably than showModal().
    try {
      if (typeof dialog.show === 'function') dialog.show();
      else dialog.showModal();
    } catch (_err) {
      try {
        dialog.showModal();
      } catch (_e2) {
        resumeModalsAfterDocViewer();
      }
    }
  }

  function resolveDocLinkUrl(raw) {
    const text = String(raw || '').trim();
    if (!text) return '';
    try {
      return new URL(text, window.location.origin).href;
    } catch (_err) {
      return text;
    }
  }

  function setDocViewerNewTab(url) {
    const nt = el('docViewerNewTabBtn');
    if (!nt) return;
    // Mobile / installed PWA: opening PDF in a new tab often has no path back into the app.
    const narrow = window.matchMedia('(max-width: 820px)').matches;
    const standalone = window.matchMedia('(display-mode: standalone)').matches
      || window.matchMedia('(display-mode: fullscreen)').matches
      || Boolean(window.navigator.standalone);
    if (!url || narrow || standalone) {
      nt.hidden = true;
      nt.removeAttribute('href');
      return;
    }
    nt.hidden = false;
    nt.href = url;
  }

  function authDocUrl(url, extraParams = {}) {
    const u = new URL(url, window.location.origin);
    if (state.session?.token && !u.searchParams.has('token')) {
      u.searchParams.set('token', state.session.token);
    }
    Object.entries(extraParams || {}).forEach(([k, v]) => {
      if (v == null || v === '') u.searchParams.delete(k);
      else u.searchParams.set(k, String(v));
    });
    return `${u.pathname}${u.search}${u.hash}`;
  }

  function docViewerMimeGuess(mime, filename, title) {
    const nameHint = `${filename || ''} ${title || ''}`;
    let effectiveMime = String(mime || '').toLowerCase();
    if (effectiveMime.includes(';')) effectiveMime = effectiveMime.split(';')[0].trim();
    const isImage = effectiveMime.startsWith('image/')
      || /\.(jpe?g|png|webp|gif)$/i.test(nameHint);
    const isPdf = effectiveMime === 'application/pdf'
      || effectiveMime.includes('pdf')
      || /\.pdf$/i.test(nameHint);
    const isHtml = effectiveMime.includes('html')
      || /\.html?$/i.test(nameHint)
      || effectiveMime === 'text/plain'
      || (!isPdf && !isImage && /\/documents\/|\.veerlabs\.|\/$/i.test(nameHint) && !/\.\w{2,5}(\?|#|$)/.test(nameHint));
    if (!effectiveMime) {
      if (isPdf) effectiveMime = 'application/pdf';
      else if (isHtml) effectiveMime = 'text/html';
      else if (isImage) effectiveMime = 'image/*';
    }
    return { effectiveMime, isImage, isPdf, isHtml };
  }

  function syncDocViewerActionButtons({
    canDownload = false,
    downloadUrl = '',
    filename = '',
    canPrint = false,
    canEditCompose = false,
  } = {}) {
    const saveName = filename || 'document';
    const dlButtons = [el('docViewerDownloadBtn'), el('docViewerMobileDownloadBtn')];
    dlButtons.forEach((dl) => {
      if (!dl) return;
      if (!canDownload || !downloadUrl) {
        dl.hidden = true;
        dl.removeAttribute('href');
        dl.removeAttribute('download');
        return;
      }
      dl.hidden = false;
      dl.href = downloadUrl;
      dl.setAttribute('download', saveName);
    });
    const printButtons = [el('docViewerPrintBtn'), el('docViewerMobilePrintBtn')];
    printButtons.forEach((btn) => {
      if (!btn) return;
      btn.hidden = !canPrint;
    });
    [el('docViewerEditComposeBtn'), el('docViewerMobileEditComposeBtn')].forEach((btn) => {
      if (btn) btn.hidden = !canEditCompose;
    });
  }

  async function downloadDocViewerContent(event) {
    if (event) event.preventDefault();
    const dl = el('docViewerDownloadBtn');
    const href = dl?.getAttribute('href') || '';
    if (!href || dl?.hidden) {
      window.alert('Download is not available for this document.');
      return;
    }
    const filename = dl.getAttribute('download')
      || el('docViewerTitle')?.textContent
      || 'document';
    const headers = {};
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    try {
      if (href.startsWith('blob:')) {
        const a = document.createElement('a');
        a.href = href;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        return;
      }
      const res = await fetch(href, { credentials: 'same-origin', headers });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    } catch (err) {
      window.alert(err?.message || 'Download failed');
    }
  }

  function showDocViewerSource(srcUrl, {
    title = 'Document',
    mime = '',
    filename = '',
    isBlob = false,
    downloadUrl = '',
    keepLoading = false,
    newTabUrl = '',
    protectContent = false,
    canPrint = true,
    canDownload = true,
    canEditCompose = false,
    templateId = '',
    printAfterOpen = false,
  } = {}) {
    const dialog = el('docViewerDialog');
    if (!dialog) return;
    if (docViewerObjectUrl && docViewerObjectUrl !== srcUrl) {
      URL.revokeObjectURL(docViewerObjectUrl);
      docViewerObjectUrl = '';
    }
    if (isBlob) docViewerObjectUrl = srcUrl;
    else docViewerStreamUrl = srcUrl;
    docViewerTemplateId = String(templateId || '');

    if (el('docViewerTitle')) el('docViewerTitle').textContent = title || filename || 'Document';
    if (el('docViewerMeta')) {
      el('docViewerMeta').textContent = filename && filename !== title ? filename : (mime || 'Preview');
    }
    const frame = el('docViewerFrame');
    const img = el('docViewerImage');
    const embed = el('docViewerEmbed');
    const fallback = el('docViewerFallback');
    const loading = el('docViewerLoading');
    const { isImage, isPdf, isHtml } = docViewerMimeGuess(mime, filename || srcUrl, title);
    const showFrame = isPdf || isHtml;
    const protectedView = Boolean(protectContent);

    if (loading) {
      if (keepLoading) {
        loading.hidden = false;
        loading.textContent = isPdf ? 'Opening PDF…' : 'Loading document…';
      } else {
        loading.hidden = true;
      }
    }
    if (embed) {
      embed.hidden = true;
      embed.removeAttribute('src');
    }
    if (frame) {
      frame.hidden = !showFrame;
      frame.classList.toggle('is-html-doc', Boolean(isHtml && showFrame));
      frame.onload = null;
      if (showFrame) {
        // HTML pages (authored or linked) need scripts/fonts; PDF stays unsandboxed.
        if (isHtml) {
          frame.setAttribute(
            'sandbox',
            'allow-same-origin allow-scripts allow-popups allow-popups-to-escape-sandbox allow-forms allow-modals',
          );
        } else {
          frame.removeAttribute('sandbox');
        }
        frame.onload = () => {
          if (loading) loading.hidden = true;
          if (protectedView && isHtml) injectInfoIframeProtect(frame);
          if (printAfterOpen) {
            window.setTimeout(() => printDocViewerContent(), 250);
          }
        };
        if (frame.getAttribute('src') === srcUrl) {
          frame.removeAttribute('src');
        }
        frame.src = srcUrl;
        window.setTimeout(() => {
          if (loading && !loading.hidden) loading.hidden = true;
          if (protectedView && isHtml) injectInfoIframeProtect(frame);
        }, 4000);
      } else {
        frame.removeAttribute('src');
        frame.classList.remove('is-html-doc');
      }
    }
    if (img) {
      img.hidden = !isImage;
      if (isImage) {
        img.onload = () => {
          if (printAfterOpen) window.setTimeout(() => printDocViewerContent(), 200);
        };
        img.src = srcUrl;
      } else {
        img.onload = null;
        img.removeAttribute('src');
      }
    }
    if (fallback) {
      fallback.hidden = Boolean(showFrame || isImage);
      if (!fallback.hidden) {
        fallback.innerHTML = protectedView
          ? 'Preview is not available for this file type in Information Centre.'
          : 'Preview is not available for this file type. Use <strong>Open in new tab</strong>, Download, or Print after opening externally, then return with Close.';
      }
    }
    setDocViewerProtected(protectedView);
    syncDocViewerActionButtons({
      canDownload: canDownload !== false && !protectedView && Boolean(downloadUrl),
      downloadUrl: downloadUrl || '',
      filename: filename || title || 'document',
      canPrint: !protectedView && Boolean(canPrint) && Boolean(showFrame || isImage),
      canEditCompose: Boolean(canEditCompose) && Boolean(docViewerTemplateId),
    });
    if (protectedView) setDocViewerNewTab('');
    else setDocViewerNewTab(newTabUrl || downloadUrl || (!isBlob ? srcUrl : ''));
    openDocViewerDialog(dialog);
  }

  function printDocViewerContent() {
    const frame = el('docViewerFrame');
    const img = el('docViewerImage');
    try {
      if (frame && !frame.hidden && frame.contentWindow) {
        frame.contentWindow.focus();
        frame.contentWindow.print();
        return;
      }
    } catch (_err) {
      /* cross-origin or unavailable */
    }
    if (img && !img.hidden && img.src) {
      const w = window.open('', '_blank', 'noopener,noreferrer');
      if (!w) {
        window.alert('Allow pop-ups to print this image, or use Download.');
        return;
      }
      const src = img.src;
      w.document.write(
        `<!DOCTYPE html><html><head><title>Print</title>`
        + `<style>html,body{margin:0;padding:0}img{max-width:100%;height:auto;display:block;margin:0 auto}</style>`
        + `</head><body><img src="${src.replace(/"/g, '&quot;')}" onload="window.focus();window.print();"></body></html>`,
      );
      w.document.close();
      return;
    }
    window.alert('Print is not available for this file type. Use Download or Open in new tab.');
  }

  function showDocViewerBlob(objectUrl, { title = 'Document', mime = '', filename = '', downloadUrl = '', protectContent = false } = {}) {
    showDocViewerSource(objectUrl, {
      title,
      mime,
      filename,
      isBlob: true,
      downloadUrl,
      protectContent,
    });
  }

  function prepareDocViewerShell({ title = 'Document', filename = '', mime = '', downloadUrl = '', newTabUrl = '', protectContent = false } = {}) {
    const dialog = el('docViewerDialog');
    if (!dialog) return;
    if (el('docViewerTitle')) el('docViewerTitle').textContent = title || filename || 'Document';
    if (el('docViewerMeta')) {
      el('docViewerMeta').textContent = filename && filename !== title ? filename : (mime || 'Preview');
    }
    const frame = el('docViewerFrame');
    const img = el('docViewerImage');
    const embed = el('docViewerEmbed');
    const fallback = el('docViewerFallback');
    const loading = el('docViewerLoading');
    const { isPdf } = docViewerMimeGuess(mime, filename, title);
    if (frame) {
      frame.hidden = true;
      frame.removeAttribute('src');
      frame.onload = null;
    }
    if (embed) {
      embed.hidden = true;
      embed.removeAttribute('src');
    }
    if (img) {
      img.hidden = true;
      img.removeAttribute('src');
    }
    if (fallback) fallback.hidden = true;
    if (loading) {
      loading.hidden = false;
      loading.textContent = isPdf ? 'Opening PDF…' : 'Loading document…';
    }
    setDocViewerProtected(Boolean(protectContent));
    syncDocViewerActionButtons({
      canDownload: !protectContent && Boolean(downloadUrl),
      downloadUrl: downloadUrl || '',
      filename: filename || title || 'document',
      canPrint: false,
    });
    if (protectContent) setDocViewerNewTab('');
    else setDocViewerNewTab(newTabUrl || downloadUrl || '');
    openDocViewerDialog(dialog);
  }

  async function openDocViewerFromAuthUrl(url, { title = 'Document', filename = '', mime = '', protectContent = false } = {}) {
    if (!url) throw new Error('Document URL missing');
    const { effectiveMime, isPdf, isHtml, isImage } = docViewerMimeGuess(mime, filename, title);
    const downloadUrl = protectContent ? '' : authDocUrl(url, { download: '1' });

    // HTML can stream in the iframe (same-origin page). PDFs must use an authenticated
    // blob URL: Chrome's PDF viewer often stays blank for http(s) src inside <dialog>,
    // and iframe navigations do not send X-RWA-Token.
    if (isHtml && !isPdf) {
      showDocViewerSource(authDocUrl(url), {
        title,
        filename: filename || title,
        mime: effectiveMime || 'text/html',
        isBlob: false,
        downloadUrl,
        protectContent,
      });
      return;
    }

    prepareDocViewerShell({
      title,
      filename: filename || title,
      mime: effectiveMime || (isPdf ? 'application/pdf' : mime),
      downloadUrl,
      protectContent,
    });

    const headers = {};
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    let res;
    try {
      res = await fetch(url, { credentials: 'same-origin', headers });
    } catch (err) {
      const loading = el('docViewerLoading');
      if (loading) loading.hidden = true;
      throw new Error(err?.message || 'Could not open document');
    }
    if (!res.ok) {
      const loading = el('docViewerLoading');
      if (loading) loading.hidden = true;
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || res.statusText || 'Could not open document');
    }
    let blob = await res.blob();
    let resolvedMime = effectiveMime || blob.type || res.headers.get('Content-Type') || '';
    if (resolvedMime.includes(';')) resolvedMime = resolvedMime.split(';')[0].trim();
    if (isPdf) resolvedMime = 'application/pdf';
    else if (!resolvedMime && isImage) resolvedMime = blob.type || 'image/*';
    if (resolvedMime && blob.type !== resolvedMime) {
      blob = new Blob([blob], { type: resolvedMime });
    }
    const objectUrl = URL.createObjectURL(blob);
    showDocViewerBlob(objectUrl, {
      title,
      filename: filename || title,
      mime: resolvedMime || blob.type || '',
      downloadUrl,
      protectContent,
    });
  }

  el('docViewerBackBtn')?.addEventListener('click', () => closeDocViewer());
  el('docViewerMobileBackBtn')?.addEventListener('click', () => closeDocViewer());
  el('docViewerPrintBtn')?.addEventListener('click', () => printDocViewerContent());
  el('docViewerMobilePrintBtn')?.addEventListener('click', () => printDocViewerContent());
  el('docViewerDownloadBtn')?.addEventListener('click', (event) => {
    downloadDocViewerContent(event);
  });
  el('docViewerMobileDownloadBtn')?.addEventListener('click', (event) => {
    downloadDocViewerContent(event);
  });
  const onEditComposeFromViewer = () => {
    const id = docViewerTemplateId;
    if (!id) return;
    beginEditComposedTemplate(id).catch((err) => {
      window.alert(err?.message || 'Could not open composer');
    });
  };
  el('docViewerEditComposeBtn')?.addEventListener('click', onEditComposeFromViewer);
  el('docViewerMobileEditComposeBtn')?.addEventListener('click', onEditComposeFromViewer);
  window.addEventListener('message', (event) => {
    // Templates inside the doc-viewer iframe can ask the portal to show a PDF
    // in-app (keeps mobile / PWA users from getting trapped in system PDF chrome).
    const data = event?.data;
    if (!data || typeof data !== 'object') return;
    if (data.type !== 'rwa-open-pdf' || !data.url) return;
    const frame = el('docViewerFrame');
    if (!frame || frame.hidden) return;
    try {
      if (event.source && frame.contentWindow && event.source !== frame.contentWindow) return;
    } catch (_err) {
      return;
    }
    showDocViewerSource(String(data.url), {
      title: data.title || 'PDF',
      filename: data.filename || 'document.pdf',
      mime: 'application/pdf',
      isBlob: false,
      downloadUrl: data.downloadUrl || String(data.url),
      newTabUrl: '',
      canPrint: true,
    });
  });
  el('docViewerDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeDocViewer();
  });
  el('docViewerDialog')?.addEventListener('close', () => {
    // Ensure blob URLs are released even if closed via Esc after cancel handler.
    if (!el('docViewerDialog')?.open) {
      const frame = el('docViewerFrame');
      const img = el('docViewerImage');
      const loading = el('docViewerLoading');
      if (frame) {
        frame.removeAttribute('src');
        frame.onload = null;
      }
      if (img) img.removeAttribute('src');
      if (loading) loading.hidden = true;
      if (docViewerObjectUrl) {
        URL.revokeObjectURL(docViewerObjectUrl);
        docViewerObjectUrl = '';
      }
      docViewerStreamUrl = '';
      setDocViewerProtected(false);
    }
  });
  document.addEventListener('click', (event) => {
    const btn = event.target.closest('.doc-open');
    if (!btn) return;
    event.preventDefault();
    event.stopPropagation();
    const url = btn.getAttribute('data-url') || '';
    if (!url || url === '#') return;
    openDocViewerFromAuthUrl(url, {
      title: btn.getAttribute('data-title') || 'Document',
      filename: btn.getAttribute('data-filename') || '',
      mime: btn.getAttribute('data-mime') || '',
    }).catch((err) => {
      closeDocViewer();
      window.alert(err.message || 'Could not open document');
    });
  });

  function inr(n) {
    const num = Number(n) || 0;
    const formatted = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(num);
    // Explicit ₹ + Noto Sans fallback (Sora/Fraunces lack U+20B9 → black tofu boxes).
    return `\u20B9${formatted}`;
  }

  function showError(msg) {
    const box = el('loginError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function isSuperAdmin(r = state.session?.resident) {
    return Boolean(r?.superAdmin);
  }

  function hasEntitlement(key, r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly) return false;
    // Pass · general: every signed-in resident (request + limited validate)
    if (key === 'pass_general') return true;
    if (r.holdsEcSeat === false) return false;
    const ents = r.entitlements;
    if (Array.isArray(ents) && ents.length) return ents.includes(key);
    // Fallback for older sessions: EC admin role implies all
    return r.role === 'admin' && r.holdsEcSeat !== false;
  }

  function isEcAdmin(r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly || r.holdsEcSeat === false) return false;
    if (typeof r.isEcAdmin === 'boolean') return r.isEcAdmin;
    return r.role === 'admin';
  }

  function isEcMember(r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly || r.holdsEcSeat === false) return false;
    if (isEcAdmin(r)) return true;
    if (r.isEcMember || r.isOfficeBearer) return true;
    return Boolean(String(r.officialTitle || '').trim());
  }

  function canOpenEcDesk(r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly || r.holdsEcSeat === false) return false;
    if (isEcAdmin(r)) return true;
    const ents = (r.entitlements || []).filter((k) => k !== 'pass_general');
    return Array.isArray(ents) && ents.length > 0;
  }

  function applyEntitlementVisibility() {
    document.querySelectorAll('[data-entitlement]').forEach((node) => {
      const key = node.getAttribute('data-entitlement');
      const allowed = hasEntitlement(key);
      node.hidden = !allowed;
    });
    const delegateBlock = el('ecDelegateBlock');
    if (delegateBlock) delegateBlock.hidden = !isEcAdmin();
    const charterBlock = el('ecCharterBlock');
    if (charterBlock) {
      charterBlock.hidden = !(hasEntitlement('manage_roles') || hasEntitlement('sensitive_ops'));
    }
    prepareMobileSections();
    if (typeof syncBoardTabs === 'function') syncBoardTabs();
  }

  function isViewOnly(r = state.session?.resident) {
    return Boolean(r?.viewOnly) && !isSuperAdmin(r);
  }

  async function loadAuthImage(imgEl, placeholderEl, photoUrl) {
    if (!imgEl) return;
    if (!photoUrl) {
      imgEl.hidden = true;
      imgEl.removeAttribute('src');
      if (placeholderEl) placeholderEl.hidden = false;
      return;
    }
    try {
      const token = state.session?.token || '';
      const res = await fetch(`${photoUrl}?t=${Date.now()}`, {
        credentials: 'same-origin',
        headers: token ? { 'X-RWA-Token': token } : {},
      });
      if (!res.ok) throw new Error('no photo');
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const prev = imgEl.dataset.objectUrl;
      if (prev) URL.revokeObjectURL(prev);
      imgEl.dataset.objectUrl = objectUrl;
      imgEl.src = objectUrl;
      imgEl.hidden = false;
      if (placeholderEl) placeholderEl.hidden = true;
    } catch (_) {
      imgEl.hidden = true;
      imgEl.removeAttribute('src');
      if (placeholderEl) placeholderEl.hidden = false;
    }
  }

  function renderUserAvatars(r = state.session?.resident) {
    const url = r?.photoUrl || '';
    loadAuthImage(el('userChipAvatarImg'), el('userChipAvatarPlaceholder'), url).catch(() => {});
    loadAuthImage(el('profileAvatarImg'), el('profileAvatarPlaceholder'), url).catch(() => {});
    const removeBtn = el('profilePhotoRemoveBtn');
    if (removeBtn) removeBtn.hidden = !url || Boolean(r?.superAdmin) || isViewOnly(r);
    const pickBtn = el('profilePhotoPickBtn');
    if (pickBtn) {
      pickBtn.disabled = Boolean(r?.superAdmin) || isViewOnly(r) || !r?.memberId;
      pickBtn.textContent = url ? 'Change photo' : 'Upload photo';
    }
    const block = el('profilePhotoBlock');
    if (block) block.hidden = Boolean(r?.superAdmin) || !r?.memberId;
  }

  const photoCrop = {
    objectUrl: '',
    naturalW: 0,
    naturalH: 0,
    scale: 1,
    minScale: 1,
    offsetX: 0,
    offsetY: 0,
    dragging: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
  };

  function photoCropViewportSize() {
    const vp = el('photoCropViewport');
    const w = vp?.clientWidth || 0;
    return w > 0 ? w : 280;
  }

  function applyPhotoCropTransform() {
    const img = el('photoCropImg');
    if (!img || !photoCrop.naturalW) return;
    const size = photoCropViewportSize();
    const drawW = photoCrop.naturalW * photoCrop.scale;
    const drawH = photoCrop.naturalH * photoCrop.scale;
    const maxX = Math.max(0, (drawW - size) / 2);
    const maxY = Math.max(0, (drawH - size) / 2);
    photoCrop.offsetX = Math.max(-maxX, Math.min(maxX, photoCrop.offsetX));
    photoCrop.offsetY = Math.max(-maxY, Math.min(maxY, photoCrop.offsetY));
    img.style.width = `${drawW}px`;
    img.style.height = `${drawH}px`;
    img.style.transform = `translate(-50%, -50%) translate(${photoCrop.offsetX}px, ${photoCrop.offsetY}px)`;
  }

  function initPhotoCropFromImage() {
    const img = el('photoCropImg');
    if (!img?.naturalWidth) return;
    photoCrop.naturalW = img.naturalWidth;
    photoCrop.naturalH = img.naturalHeight;
    const size = photoCropViewportSize();
    photoCrop.minScale = Math.max(size / photoCrop.naturalW, size / photoCrop.naturalH);
    if (!Number.isFinite(photoCrop.minScale) || photoCrop.minScale <= 0) {
      photoCrop.minScale = 1;
    }
    photoCrop.scale = photoCrop.minScale;
    photoCrop.offsetX = 0;
    photoCrop.offsetY = 0;
    const zoom = el('photoCropZoom');
    if (zoom) {
      zoom.min = String(photoCrop.minScale);
      zoom.max = String(photoCrop.minScale * 3);
      zoom.step = '0.01';
      zoom.value = String(photoCrop.scale);
    }
    applyPhotoCropTransform();
  }

  function closePhotoCrop() {
    const dialog = el('photoCropDialog');
    if (dialog?.open) dialog.close();
    if (photoCrop.objectUrl) {
      URL.revokeObjectURL(photoCrop.objectUrl);
      photoCrop.objectUrl = '';
    }
    const img = el('photoCropImg');
    if (img) {
      img.onload = null;
      img.onerror = null;
      img.removeAttribute('src');
      img.removeAttribute('style');
    }
    photoCrop.naturalW = 0;
    photoCrop.naturalH = 0;
    photoCrop.scale = 1;
    photoCrop.minScale = 1;
    photoCrop.offsetX = 0;
    photoCrop.offsetY = 0;
    photoCrop.dragging = false;
    if (el('profilePhotoFile')) el('profilePhotoFile').value = '';
    if (el('photoCropError')) {
      el('photoCropError').hidden = true;
      el('photoCropError').textContent = '';
    }
  }

  function openPhotoCrop(file) {
    if (!file) return;
    const type = String(file.type || '').toLowerCase();
    const name = String(file.name || '').toLowerCase();
    const looksImage = type.startsWith('image/')
      || /\.(jpe?g|png|webp|gif|heic|heif)$/.test(name);
    if (!looksImage) {
      if (el('profilePhotoStatus')) el('profilePhotoStatus').textContent = 'Choose a JPG, PNG, or WebP image.';
      return;
    }
    if (file.size > 8_000_000) {
      if (el('profilePhotoStatus')) el('profilePhotoStatus').textContent = 'Image must be under 8 MB.';
      return;
    }
    closePhotoCrop();
    const objectUrl = URL.createObjectURL(file);
    photoCrop.objectUrl = objectUrl;
    const img = el('photoCropImg');
    const dialog = el('photoCropDialog');
    if (!img || !dialog) return;

    const reveal = () => {
      // Dialog must be open before measuring — closed dialogs report clientWidth 0.
      if (typeof dialog.showModal === 'function') {
        if (!dialog.open) dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
      requestAnimationFrame(() => {
        initPhotoCropFromImage();
        requestAnimationFrame(() => initPhotoCropFromImage());
      });
    };

    img.onload = () => reveal();
    img.onerror = () => {
      closePhotoCrop();
      if (el('profilePhotoStatus')) {
        el('profilePhotoStatus').textContent = 'Could not read that image. Try JPG or PNG.';
      }
    };
    img.src = objectUrl;
    if (img.complete && img.naturalWidth) reveal();
  }

  function exportCroppedPhotoBlob() {
    return new Promise((resolve, reject) => {
      const img = el('photoCropImg');
      if (!img?.complete || !photoCrop.naturalW) {
        reject(new Error('Image not ready'));
        return;
      }
      const outSize = 320;
      const size = photoCropViewportSize();
      const drawW = photoCrop.naturalW * photoCrop.scale;
      const drawH = photoCrop.naturalH * photoCrop.scale;
      // Image center in viewport coords is (size/2 + offset)
      const srcCenterX = (size / 2 - photoCrop.offsetX) / photoCrop.scale;
      const srcCenterY = (size / 2 - photoCrop.offsetY) / photoCrop.scale;
      const srcSide = size / photoCrop.scale;
      const sx = srcCenterX - srcSide / 2;
      const sy = srcCenterY - srcSide / 2;
      const canvas = document.createElement('canvas');
      canvas.width = outSize;
      canvas.height = outSize;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#f6f1e6';
      ctx.fillRect(0, 0, outSize, outSize);
      ctx.drawImage(img, sx, sy, srcSide, srcSide, 0, 0, outSize, outSize);
      canvas.toBlob((blob) => {
        if (!blob) reject(new Error('Could not encode photo'));
        else resolve(blob);
      }, 'image/jpeg', 0.82);
    });
  }

  async function uploadProfilePhotoBlob(blob) {
    const status = el('profilePhotoStatus');
    const headers = {};
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    const body = new FormData();
    body.append('photo', blob, 'profile.jpg');
    const res = await fetch('/api/rwa/profile/photo', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || 'Upload failed');
    if (data.resident) {
      state.session.resident = data.resident;
      setAuthed(state.session);
    }
    if (status) status.textContent = 'Photo saved.';
  }

  const AVATAR_PLACEHOLDER_SVG = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="8" r="3.2"/><path d="M5.8 18.8c1.5-2.6 3.4-3.9 6.2-3.9s4.7 1.3 6.2 3.9"/></svg>`;
  const AI_AVATAR_URL = '/assets/rwa-assistant-avatar.svg';

  function personAvatarHtml(person = {}, { size = 'sm', className = '' } = {}) {
    const url = person.photoUrl || '';
    const cls = ['person-avatar', size === 'md' ? 'is-md' : (size === 'lg' ? 'is-lg' : 'is-sm'), className].filter(Boolean).join(' ');
    const attrs = url ? ` data-photo-url="${escapeHtml(url)}"` : '';
    return `<span class="${cls}"${attrs} aria-hidden="true"><span class="person-avatar-fallback">${AVATAR_PLACEHOLDER_SVG}</span></span>`;
  }

  function aiAvatarHtml({ size = 'sm', className = '' } = {}) {
    const cls = ['person-avatar', 'is-ai-avatar', size === 'md' ? 'is-md' : (size === 'lg' ? 'is-lg' : 'is-sm'), className].filter(Boolean).join(' ');
    return `<span class="${cls}" title="RWA Assistant" aria-hidden="true"><img class="ai-avatar-img" src="${AI_AVATAR_URL}" alt=""></span>`;
  }

  function hhAvatarHtml(m) {
    return personAvatarHtml(m, { size: 'md', className: 'hh-avatar' });
  }

  async function hydrateAvatars(root = document) {
    if (!root?.querySelectorAll) return;
    const nodes = root.querySelectorAll('.person-avatar[data-photo-url], .hh-avatar[data-photo-url]');
    for (const node of nodes) {
      if (node.querySelector('img')) continue;
      const url = node.getAttribute('data-photo-url');
      if (!url) continue;
      try {
        const token = state.session?.token || '';
        const res = await fetch(`${url}?t=${Date.now()}`, {
          credentials: 'same-origin',
          headers: token ? { 'X-RWA-Token': token } : {},
        });
        if (!res.ok) continue;
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        node.innerHTML = `<img src="${objectUrl}" alt="">`;
      } catch (_) { /* keep placeholder */ }
    }
  }

  async function hydrateHhAvatars(root) {
    return hydrateAvatars(root);
  }

  function canManageHousehold(r = state.session?.resident) {
    return Boolean(r?.canManageHousehold || r?.isPrimary) && !isViewOnly(r);
  }

  const sectionLang = { notices: 'en', concerns: 'en', info: 'en' };
  let mailboxCache = [];
  const translateMem = new Map();

  function translateCacheKey(text, source, target) {
    return `${source}|${target}|${String(text || '').trim()}`;
  }

  async function translateTexts(texts, { source = 'en', target = 'hi' } = {}) {
    const list = (texts || []).map((t) => String(t || ''));
    const out = new Array(list.length).fill('');
    const pendingIdx = [];
    const pendingTexts = [];
    list.forEach((text, i) => {
      const trimmed = text.trim();
      if (!trimmed) {
        out[i] = '';
        return;
      }
      if (source === target) {
        out[i] = trimmed;
        return;
      }
      const key = translateCacheKey(trimmed, source, target);
      if (translateMem.has(key)) {
        out[i] = translateMem.get(key);
        return;
      }
      pendingIdx.push(i);
      pendingTexts.push(trimmed);
    });
    if (!pendingTexts.length) return out;
    // Batch in chunks of 20
    for (let offset = 0; offset < pendingTexts.length; offset += 20) {
      const slice = pendingTexts.slice(offset, offset + 20);
      const data = await api('/api/rwa/translate', {
        method: 'POST',
        body: JSON.stringify({ texts: slice, source, target }),
      });
      const translations = data.translations || [];
      slice.forEach((src, j) => {
        const translated = String(translations[j] || '').trim();
        const idx = pendingIdx[offset + j];
        if (translated) {
          translateMem.set(translateCacheKey(src, source, target), translated);
          out[idx] = translated;
        } else {
          out[idx] = '';
        }
      });
    }
    return out;
  }

  async function hiOrAuto(en, hi) {
    const saved = String(hi || '').trim();
    if (saved) return { text: saved, auto: false };
    const src = String(en || '').trim();
    if (!src) return { text: '', auto: false };
    try {
      const [t] = await translateTexts([src], { source: 'en', target: 'hi' });
      if (t) return { text: t, auto: true };
    } catch (_) { /* fall through */ }
    return { text: src, auto: false, failed: true };
  }

  function setAuthorFormLang(formKey, lang) {
    const next = lang === 'hi' ? 'hi' : 'en';
    document.querySelectorAll(`.author-lang-toggle[data-author-form="${formKey}"] .lang-btn`).forEach((btn) => {
      const active = btn.getAttribute('data-author-lang') === next;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    document.querySelectorAll(`[data-author-pane="${formKey}"]`).forEach((pane) => {
      pane.hidden = pane.getAttribute('data-lang') !== next;
    });
    document.querySelectorAll('.mhws-composer-lang-btn').forEach((btn) => {
      const on = btn.getAttribute('data-compose-lang') === next;
      btn.classList.toggle('is-active', on);
    });
    if (next === 'hi') {
      autofillAuthorFromEnglish(formKey).catch(() => {});
    }
  }

  async function autofillAuthorFromEnglish(formKey) {
    const pairs = [];
    if (formKey === 'notice') {
      pairs.push(['noticeTitleInput', 'noticeTitleHiInput'], ['noticeBodyInput', 'noticeBodyHiInput']);
    } else if (formKey === 'grievance') {
      pairs.push(['grievanceSubject', 'grievanceSubjectHi'], ['grievanceBody', 'grievanceBodyHi']);
    } else if (formKey === 'info') {
      syncInfoComposerInputs();
      pairs.push(
        ['infoTitleInput', 'infoTitleHiInput'],
        ['infoSummaryInput', 'infoSummaryHiInput'],
        ['infoHtmlInput', 'infoHtmlHiInput'],
      );
    } else if (formKey.startsWith('reply-')) {
      const form = document.querySelector(`.mailbox-reply .author-lang-toggle[data-author-form="${formKey}"]`)?.closest('form');
      if (!form) return;
      const en = form.querySelector('textarea[name="body"]');
      const hi = form.querySelector('textarea[name="bodyHi"]');
      if (en && hi && !String(hi.value || '').trim() && String(en.value || '').trim()) {
        const [t] = await translateTexts([en.value], { source: 'en', target: 'hi' });
        if (t) hi.value = t;
      }
      return;
    }
    const need = [];
    pairs.forEach(([enId, hiId]) => {
      const enEl = el(enId);
      const hiEl = el(hiId);
      if (!enEl || !hiEl) return;
      if (String(hiEl.value || '').trim()) return;
      if (!String(enEl.value || '').trim()) return;
      need.push({ enEl, hiEl, text: enEl.value });
    });
    if (!need.length) return;
    const translated = await translateTexts(need.map((n) => n.text), { source: 'en', target: 'hi' });
    need.forEach((n, i) => {
      if (translated[i] && !String(n.hiEl.value || '').trim()) {
        n.hiEl.value = translated[i];
        if (n.hiEl.id === 'infoHtmlHiInput' && infoComposeHi) {
          infoComposeHi.setHTML(translated[i]);
        }
      }
    });
  }

  function pickText(en, hi, lang) {
    if (lang === 'hi') return String(hi || '').trim() || '';
    return String(en || '').trim() || '';
  }

  function autoBadge(auto) {
    return auto ? '<span class="lang-auto-badge" title="Machine translation">स्वतः · Auto</span>' : '';
  }

  async function renderNoticesOverlay() {
    const box = el('noticesLangOverlayBody');
    if (!box) return;
    if (!noticesCache.length) {
      box.innerHTML = '<p class="lang-overlay-empty">कोई सूचना नहीं · No notices yet.</p>';
      return;
    }
    box.innerHTML = '<p class="muted">अनुवाद हो रहा है… Translating…</p>';
    const cards = [];
    for (const n of noticesCache) {
      const title = await hiOrAuto(n.title, n.titleHi);
      const body = await hiOrAuto(n.body, n.bodyHi);
      const failed = title.failed && body.failed;
      cards.push(`
        <article class="lang-overlay-card">
          <h4>${escapeHtml(title.text || n.title || 'Untitled')} ${autoBadge(title.auto || body.auto)}</h4>
          <span class="meta">${escapeHtml(n.category || 'general')}${n.publishedAt ? ` · ${escapeHtml(formatIstDate(n.publishedAt))}` : ''}</span>
          ${failed
            ? '<p class="lang-missing">अनुवाद उपलब्ध नहीं · Could not auto-translate.</p>'
            : `<div class="body">${formatNoticeBody(body.text || n.body || '')}</div>`}
        </article>`);
    }
    if (sectionLang.notices === 'hi') box.innerHTML = cards.join('');
  }

  async function renderConcernsOverlay() {
    const box = el('concernsLangOverlayBody');
    if (!box) return;
    if (!mailboxCache.length) {
      box.innerHTML = '<p class="lang-overlay-empty">कोई चिंता नहीं · No concerns yet.</p>';
      return;
    }
    box.innerHTML = '<p class="muted">अनुवाद हो रहा है… Translating…</p>';
    const cards = [];
    for (const g of mailboxCache) {
      const subject = await hiOrAuto(g.subject, g.subjectHi);
      const msgBits = [];
      let anyAuto = subject.auto;
      for (const m of (g.messages || [])) {
        const body = await hiOrAuto(m.body, m.bodyHi);
        anyAuto = anyAuto || body.auto;
        msgBits.push(`<p><strong>${escapeHtml(m.authorName || (m.authorRole === 'ec' ? 'EC' : 'Resident'))}:</strong> ${escapeHtml(body.text || m.body || '')}${body.auto ? ' <span class="lang-auto-badge">स्वतः</span>' : ''}</p>`);
      }
      cards.push(`
        <article class="lang-overlay-card">
          <h4>${escapeHtml(subject.text || g.subject || '')} ${autoBadge(anyAuto)}</h4>
          <span class="meta">${escapeHtml(g.categoryLabel || g.category || '')} · plot ${escapeHtml(g.houseId || '')}</span>
          <div class="body">${msgBits.join('') || '<p class="lang-missing">No messages.</p>'}</div>
        </article>`);
    }
    if (sectionLang.concerns === 'hi') box.innerHTML = cards.join('');
  }

  async function renderInfoOverlay() {
    const box = el('infoLangOverlayBody');
    if (!box) return;
    if (!infoDocsCache.length) {
      box.innerHTML = '<p class="lang-overlay-empty">कोई दस्तावेज़ नहीं · No documents yet.</p>';
      return;
    }
    box.innerHTML = '<p class="muted">अनुवाद हो रहा है… Translating…</p>';
    const cards = [];
    for (const d of infoDocsCache) {
      const title = await hiOrAuto(d.title, d.titleHi);
      const summary = await hiOrAuto(d.summary, d.summaryHi);
      const folderLabel = d.folderTitle
        ? await hiOrAuto(d.folderTitle, d.folderTitleHi)
        : null;
      const openBtn = d.docType === 'html' && d.hasHtmlHi
        ? `<button type="button" class="btn primary compact info-doc-open-hi" data-id="${escapeHtml(d.id)}">Open Hindi HTML</button>`
        : (d.docType === 'html'
          ? `<button type="button" class="btn secondary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open English HTML</button>`
          : `<button type="button" class="btn secondary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open file</button>`);
      const metaParts = [
        folderLabel?.text || '',
        d.categoryLabel || d.category || '',
        d.docType === 'html' ? 'HTML' : 'File',
      ].filter(Boolean);
      cards.push(`
        <article class="lang-overlay-card">
          <h4>${escapeHtml(title.text || d.title || 'Untitled')} ${autoBadge(title.auto || summary.auto || folderLabel?.auto)}</h4>
          <span class="meta">${escapeHtml(metaParts.join(' · '))}</span>
          ${summary.text ? `<p class="body">${escapeHtml(summary.text)}</p>` : ''}
          <div class="btn-row" style="margin-top:0.5rem">${openBtn}</div>
        </article>`);
    }
    if (sectionLang.info === 'hi') box.innerHTML = cards.join('');
  }

  function setSectionLang(section, lang) {
    const next = lang === 'hi' ? 'hi' : 'en';
    sectionLang[section] = next;
    document.querySelectorAll(`.lang-toggle[data-lang-section="${section}"] .lang-btn`).forEach((btn) => {
      const active = btn.getAttribute('data-lang') === next;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const overlayId = section === 'notices'
      ? 'noticesLangOverlay'
      : (section === 'concerns' ? 'concernsLangOverlay' : 'infoLangOverlay');
    const overlay = el(overlayId);
    if (!overlay) return;
    if (next === 'hi') {
      overlay.hidden = false;
      const run = section === 'notices'
        ? renderNoticesOverlay()
        : (section === 'concerns' ? renderConcernsOverlay() : renderInfoOverlay());
      run.catch((err) => {
        const body = overlay.querySelector('.lang-overlay-body');
        if (body) body.innerHTML = `<p class="error">${escapeHtml(err.message || 'Translation failed')}</p>`;
      });
    } else {
      overlay.hidden = true;
    }
  }

  document.addEventListener('click', (event) => {
    const langBtn = event.target.closest?.('.lang-toggle .lang-btn');
    if (langBtn) {
      const section = langBtn.closest('.lang-toggle')?.getAttribute('data-lang-section');
      const lang = langBtn.getAttribute('data-lang');
      if (section && lang) setSectionLang(section, lang);
      return;
    }
    const closeBtn = event.target.closest?.('[data-lang-close]');
    if (closeBtn) {
      const section = closeBtn.getAttribute('data-lang-close');
      if (section) setSectionLang(section, 'en');
      return;
    }
    const authorBtn = event.target.closest?.('.author-lang-toggle .lang-btn');
    if (authorBtn) {
      const formKey = authorBtn.closest('.author-lang-toggle')?.getAttribute('data-author-form');
      const lang = authorBtn.getAttribute('data-author-lang');
      if (formKey && lang) setAuthorFormLang(formKey, lang);
      return;
    }
    const openHi = event.target.closest?.('.info-doc-open-hi');
    if (openHi) {
      const id = openHi.getAttribute('data-id');
      const doc = infoDocsCache.find((d) => d.id === id);
      if (doc) openInfoDocument(doc, { lang: 'hi' }).catch((err) => alert(err.message || 'Open failed'));
    }
  });

  const MOBILE_MQ = window.matchMedia('(max-width: 900px)');

  function isMobileLayout() {
    return MOBILE_MQ.matches;
  }

  function applyMobileListLimit(container, itemSelector, limit = 5) {
    if (!container) return;
    const mount = container.closest('.table-wrap') || container.closest('.mobile-list') || container;
    mount.parentElement?.querySelector(':scope > .list-show-more')?.remove();
    const items = [...container.querySelectorAll(itemSelector)];
    items.forEach((item) => item.classList.remove('is-list-hidden'));
    if (!isMobileLayout() || items.length <= limit) return;
    items.forEach((item, i) => {
      if (i >= limit) item.classList.add('is-list-hidden');
    });
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn ghost compact list-show-more';
    btn.textContent = `Show all ${items.length} (${items.length - limit} more)`;
    btn.addEventListener('click', () => {
      items.forEach((item) => item.classList.remove('is-list-hidden'));
      btn.remove();
    }, { once: true });
    mount.insertAdjacentElement('afterend', btn);
  }

  function prepareMobileSections(root = document) {
    const blocks = root.querySelectorAll([
      '#panel-admin > .roster-block',
      '#panel-admin > .settings-block',
      '#panel-dues .roster-block',
      '#panel-dues #adminDues',
      '#panel-observability .roster-block',
      '#panel-info > .roster-block',
      '#panel-works > .roster-block',
      '#panel-proceedings > .roster-block',
      '#panel-parking > .roster-block',
      '#panel-concerns .desk-tablet',
      '#panel-profile > .roster-block',
    ].join(', '));
    let openByPanel = new Set();
    blocks.forEach((block) => {
      if (block.dataset.mobileSectionReady) return;
      // Skip nested roster-blocks inside already-prepared parents (e.g. sensitive ops)
      if (block.parentElement?.closest('.mobile-section')) return;
      block.dataset.mobileSectionReady = '1';
      block.classList.add('mobile-section', 'desk-tablet');
      const toolbar = block.querySelector(
        ':scope > .roster-toolbar, :scope > .panel-head, :scope > .ledger-toolbar, :scope > .mailbox-toolbar, :scope > .info-toolbar, :scope > .works-toolbar'
      );
      if (!toolbar) return;

      const bodyNodes = [];
      let node = toolbar.nextElementSibling;
      while (node) {
        bodyNodes.push(node);
        node = node.nextElementSibling;
      }
      if (!bodyNodes.length) return;

      const body = document.createElement('div');
      body.className = 'mobile-section-body desk-section-body';
      bodyNodes.forEach((n) => body.appendChild(n));
      block.appendChild(body);

      const heading = toolbar.querySelector('h3, h2');
      if (heading && !toolbar.querySelector('.mobile-section-toggle, .desk-section-toggle')) {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'mobile-section-toggle desk-section-toggle';
        toggle.setAttribute('aria-label', 'Expand or collapse section');
        toggle.innerHTML = '<span class="mobile-section-chevron desk-section-chevron" aria-hidden="true"></span>';
        const titleHost = heading.closest('.panel-head') || heading.parentElement || toolbar;
        titleHost.insertBefore(toggle, heading);
      }

      const panel = block.closest('.panel');
      const panelKey = panel?.id || 'page';
      const isVisible = !block.hidden
        && !block.hasAttribute('hidden')
        && getComputedStyle(block).display !== 'none';
      const startOpen = isVisible && !openByPanel.has(panelKey);
      if (startOpen) openByPanel.add(panelKey);
      const toggleBtn = block.querySelector('.mobile-section-toggle, .desk-section-toggle');
      if (!startOpen) block.classList.add('is-section-collapsed');
      if (toggleBtn) toggleBtn.setAttribute('aria-expanded', startOpen ? 'true' : 'false');
    });
  }

  function toggleDeskSection(section, { preferOpen } = {}) {
    if (!section) return;
    const collapsed = section.classList.contains('is-section-collapsed');
    const shouldOpen = preferOpen == null ? collapsed : preferOpen;
    section.classList.toggle('is-section-collapsed', !shouldOpen);
    const toggle = section.querySelector('.mobile-section-toggle, .desk-section-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
    if (shouldOpen) scrollBelowAppHeader(section.querySelector('.mobile-section-body') || section);
  }

  function refreshMobileListUi() {
    if (isMobileLayout()) applyMobileListLimit(el('ledgerCards'), '.ledger-card', 5);
    else applyMobileListLimit(el('ledgerRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('rosterRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('revisionRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('obsRecentRows'), 'tr:not(.is-empty-row)', 8);
    applyMobileListLimit(el('noticeList'), '.notice.mobile-fold', 4);
    applyMobileListLimit(el('mailboxList'), '.grievance-card.mobile-fold', 4);
    applyMobileListLimit(el('ecGrievanceList'), '.grievance-card.mobile-fold', 4);
    applyMobileListLimit(el('infoDocList'), '.info-doc-card', 5);
    applyMobileListLimit(el('noticeDraftList'), '.notice-draft-card.mobile-fold', 4);
    applyMobileListLimit(el('worksList'), '.works-card.mobile-fold', 5);
  }

  function updateAppTopOffset() {
    const top = document.querySelector('.app-top');
    if (!top) return;
    document.documentElement.style.setProperty('--app-top-offset', `${Math.ceil(top.offsetHeight)}px`);
  }

  function scrollBelowAppHeader(target) {
    if (!target || !isMobileLayout()) return;
    const main = document.querySelector('.app-main');
    if (main) {
      const mainRect = main.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const y = main.scrollTop + (targetRect.top - mainRect.top) - 8;
      main.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
      return;
    }
    updateAppTopOffset();
    const topBar = document.querySelector('.app-top');
    const offset = (topBar?.offsetHeight || 118) + 10;
    const y = target.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  }

  function scrollMainToTop() {
    const main = document.querySelector('.app-main');
    if (main && isMobileLayout()) {
      main.scrollTo({ top: 0, behavior: 'instant' in main.scrollTo ? 'instant' : 'auto' });
      return;
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  let landingLoaded = false;

  const LANDING_BOARD_HASHES = new Set([
    'landing-board',
    'landing-news',
    'landing-services',
    'landing-ads',
    'landing-committee',
  ]);

  function isLandingBoardHash(hash) {
    const key = (hash || '').replace(/^#/, '');
    return LANDING_BOARD_HASHES.has(key);
  }

  function openLandingBoard({ scrollTo = 'landing-news', updateHash = true } = {}) {
    const shell = el('landingView');
    const board = el('landing-board');
    const connect = el('landing-connect-band');
    if (!shell || !board) return;
    shell.classList.add('board-open');
    board.hidden = false;
    if (connect) connect.hidden = false;
    if (!landingLoaded) loadLanding().catch(() => {});
    const targetId = scrollTo || 'landing-news';
    if (updateHash) {
      const nextHash = `#${targetId}`;
      if (location.hash !== nextHash) {
        history.pushState(null, '', `${location.pathname}${location.search}${nextHash}`);
      }
    }
    requestAnimationFrame(() => {
      const node = document.getElementById(targetId);
      if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function closeLandingBoard({ scrollTop = true } = {}) {
    const shell = el('landingView');
    const board = el('landing-board');
    const connect = el('landing-connect-band');
    if (!shell) return;
    shell.classList.remove('board-open');
    if (board) board.hidden = true;
    if (connect) connect.hidden = true;
    if (scrollTop) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    const hash = (location.hash || '').replace(/^#/, '');
    if (isLandingBoardHash(hash)) {
      history.replaceState(null, '', `${location.pathname}${location.search}`);
    }
  }

  function bindLandingBoardReveal() {
    const shell = el('landingView');
    if (!shell || shell.dataset.boardBound === '1') return;
    shell.dataset.boardBound = '1';

    shell.querySelectorAll('a[href^="#landing"]').forEach((link) => {
      link.addEventListener('click', (event) => {
        const target = (link.getAttribute('href') || '').replace(/^#/, '');
        if (!isLandingBoardHash(target)) return;
        if (!shell.classList.contains('board-open')) {
          event.preventDefault();
          openLandingBoard({ scrollTo: target });
        }
      });
    });

    shell.querySelector('.landing-scroll-hint')?.addEventListener('click', (event) => {
      if (!shell.classList.contains('board-open')) {
        event.preventDefault();
        openLandingBoard({ scrollTo: 'landing-news' });
      }
    });

    shell.querySelector('.landing-top-brand')?.addEventListener('click', (event) => {
      if (shell.classList.contains('board-open')) {
        event.preventDefault();
        closeLandingBoard();
      }
    });
  }

  function applyLandingBoardHash() {
    const hash = (location.hash || '').replace(/^#/, '');
    if (isLandingBoardHash(hash)) {
      openLandingBoard({ scrollTo: hash, updateHash: false });
      return true;
    }
    return false;
  }

  function showLanding() {
    document.body.classList.remove('is-members-gate');
    const landing = el('landingView');
    const gate = el('gateView');
    if (landing) landing.hidden = false;
    if (gate) gate.hidden = true;
    const hash = (location.hash || '').replace(/^#/, '');
    if (hash === 'members' || hash === 'login') {
      history.replaceState(null, '', `${location.pathname}${location.search}`);
      closeLandingBoard({ scrollTop: false });
    } else if (!applyLandingBoardHash()) {
      closeLandingBoard({ scrollTop: false });
    }
    bindLandingBoardReveal();
  }

  function showMembersGate({ pushHash = true } = {}) {
    document.body.classList.add('is-members-gate');
    const landing = el('landingView');
    const gate = el('gateView');
    if (landing) landing.hidden = true;
    if (gate) gate.hidden = false;
    if (pushHash) {
      const hash = (location.hash || '').replace(/^#/, '');
      if (hash !== 'members') {
        history.replaceState(null, '', `${location.pathname}${location.search}#members`);
      }
    }
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  function applyPreLoginRoute() {
    if (state.session?.resident) return;
    const hash = (location.hash || '').replace(/^#/, '');
    if (hash === 'members' || hash === 'login') {
      showMembersGate({ pushHash: false });
      return;
    }
    showLanding();
  }

  async function showLandingCampaignDetail(campaignId) {
    document.body.classList.remove('is-members-gate');
    const landing = el('landingView');
    const gate = el('gateView');
    if (landing) landing.hidden = false;
    if (gate) gate.hidden = true;
    state._landingCampaignFocus = campaignId;
    try {
      const data = await fetch(`/api/rwa/public/campaigns/${encodeURIComponent(campaignId)}`).then((r) => r.json());
      if (!data.ok || !data.campaign) { delete state._landingCampaignFocus; loadLanding(); return; }
      const c = data.campaign;
      const cover = c.imageUrl ? `${c.imageUrl}?v=1` : '';
      const pledged = c.pledgedAmount || 0;
      const raised = c.raisedAmount || 0;
      const target = c.targetAmount;
      const pctPledge = target ? Math.min(100, Math.round(100 * pledged / target)) : 0;
      const pctRaised = target ? Math.min(100, Math.round(100 * raised / target)) : 0;
      const section = el('landingCampaignsSection');
      const campaignsEl = el('landingCampaignsList');
      if (section) section.hidden = false;
      if (campaignsEl) {
        campaignsEl.innerHTML = `
          <div class="landing-campaign-detail">
            ${cover ? `<img class="landing-campaign-hero" src="${escapeHtml(cover)}" alt="">` : ''}
            <h3>${escapeHtml(c.title || '')}</h3>
            ${c.summary ? `<p>${escapeHtml(c.summary)}</p>` : ''}
            ${c.details ? `<div class="campaign-desc">${formatNoticeBody(c.details)}</div>` : ''}
            <div class="campaign-stat-grid">
              ${pledged ? `<div class="campaign-stat-card is-pledged"><strong>${formatRupee(pledged)}</strong><span>Pledged · ${c.pledgerCount || 0} members</span></div>` : ''}
              ${raised ? `<div class="campaign-stat-card is-raised"><strong>${formatRupee(raised)}</strong><span>Raised · ${c.contributorCount || 0} payments</span></div>` : ''}
              ${target ? `<div class="campaign-stat-card"><strong>${formatRupee(target)}</strong><span>Target</span></div>` : ''}
            </div>
            ${target ? `<div class="campaign-dual-progress">
              ${pledged ? `<div><label>Pledged</label><div class="campaign-progress-bar"><div class="campaign-progress-fill" style="width:${pctPledge}%"></div></div></div>` : ''}
              ${raised ? `<div><label>Raised</label><div class="campaign-progress-bar"><div class="campaign-progress-fill" style="width:${pctRaised}%"></div></div></div>` : ''}
            </div>` : ''}
            ${c.location ? `<p class="landing-meta">📍 ${escapeHtml(c.location)}</p>` : ''}
            ${c.eventDate ? `<p class="landing-meta">📅 ${escapeHtml(c.eventDate)}</p>` : ''}
            ${c.deadline ? `<p class="landing-meta">⏳ Deadline ${escapeHtml(c.deadline)}</p>` : ''}
            ${c.paymentInstructions ? `<div class="campaign-payment-info"><strong>Payment info:</strong> ${escapeHtml(c.paymentInstructions)}</div>` : ''}
            <div class="public-pledge-form" id="publicPledgeForm">
              <h4>${c.canPledge ? '✋ Pledge your support' : '💰 Contribute'}</h4>
              <div class="form-row">
                <input type="text" id="pubPledgeName" placeholder="Your name" required>
                <input type="text" id="pubPledgeHouse" placeholder="House / Plot No." required>
              </div>
              <div class="form-row">
                <input type="number" id="pubPledgeAmount" placeholder="${c.fixedPledgeAmount ? 'Amount: ₹' + c.fixedPledgeAmount : 'Amount (₹)'}" min="1" ${c.fixedPledgeAmount ? `value="${c.fixedPledgeAmount}" readonly` : ''}>
              </div>
              <button type="button" id="pubPledgeSubmit">${c.canPledge ? 'Submit Pledge' : 'Submit Contribution'}</button>
              <p id="pubPledgeMsg" class="muted" style="margin-top:0.5rem" hidden></p>
            </div>
          </div>`;
        setTimeout(() => {
          const btn = document.getElementById('pubPledgeSubmit');
          if (btn) btn.addEventListener('click', async () => {
            const name = document.getElementById('pubPledgeName')?.value?.trim();
            const house = document.getElementById('pubPledgeHouse')?.value?.trim();
            const amount = parseInt(document.getElementById('pubPledgeAmount')?.value, 10);
            const msg = document.getElementById('pubPledgeMsg');
            if (!name || !house || !amount || amount <= 0) {
              if (msg) { msg.textContent = 'Please fill all fields.'; msg.hidden = false; }
              return;
            }
            btn.disabled = true;
            btn.textContent = 'Submitting…';
            try {
              const endpoint = c.canPledge
                ? `/api/rwa/public/campaigns/${encodeURIComponent(campaignId)}/pledges`
                : `/api/rwa/public/campaigns/${encodeURIComponent(campaignId)}/contributions`;
              const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, house, amount })
              });
              const result = await res.json();
              if (result.ok) {
                if (msg) { msg.textContent = '✅ Thank you! Your submission has been recorded.'; msg.hidden = false; msg.style.color = '#1a6b45'; }
                btn.textContent = 'Done!';
              } else {
                if (msg) { msg.textContent = result.error || 'Something went wrong.'; msg.hidden = false; }
                btn.disabled = false;
                btn.textContent = c.canPledge ? 'Submit Pledge' : 'Submit Contribution';
              }
            } catch (e) {
              if (msg) { msg.textContent = 'Network error. Please try again.'; msg.hidden = false; }
              btn.disabled = false;
              btn.textContent = c.canPledge ? 'Submit Pledge' : 'Submit Contribution';
            }
          });
        }, 0);
      }
    } catch (e) {
      delete state._landingCampaignFocus;
      loadLanding();
    }
  }

  async function loadLanding() {
    const updatesEl = el('landingUpdatesList');
    const adsEl = el('landingAdsList');
    const bizEl = el('landingBusinessList');
    const needsEl = el('landingNeedsList');
    const needsWrap = el('landingNeedsWrap');
    const committeeEl = el('landingCommitteeList');
    if (!updatesEl && !committeeEl && !bizEl) return;

    function listingImageHtml(item) {
      if (!item.imageUrl) return '';
      const v = item.updatedAt || item.publishedAt || '';
      const src = `${item.imageUrl}${v ? `?v=${encodeURIComponent(v)}` : ''}`;
      return `<img class="landing-card-photo" src="${escapeHtml(src)}" alt="" loading="lazy">`;
    }

    function listingContactHtml(item, { phone = true } = {}) {
      const parts = [];
      if (phone && item.phone) {
        parts.push(`<p class="landing-phone"><a href="tel:${escapeHtml(item.phone)}">${escapeHtml(item.phone)}</a></p>`);
      }
      if (item.email) {
        parts.push(`<p class="landing-contact"><a href="mailto:${escapeHtml(item.email)}">${escapeHtml(item.email)}</a></p>`);
      }
      if (item.website) {
        const href = /^https?:\/\//i.test(item.website) ? item.website : `https://${item.website}`;
        parts.push(`<p class="landing-contact"><a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">Website</a></p>`);
      }
      return parts.join('');
    }

    function landingCard(item, { phone = true, featured = false, interest = false } = {}) {
      const meta = [item.regNo, item.categoryLabel || item.category, item.area]
        .filter(Boolean).join(' · ');
      const when = formatIstDate(item.publishedAt || item.createdAt || '') || '';
      const id = item.id || '';
      const interestHtml = interest && id ? `
          <button type="button" class="btn ghost compact landing-interest-toggle" data-need-id="${escapeHtml(id)}">I'm interested</button>
          <form class="landing-interest-form stack" data-need-id="${escapeHtml(id)}" hidden>
            <label>Your name
              <input name="name" maxlength="80" required autocomplete="name">
            </label>
            <label>Mobile <span class="muted">(or email)</span>
              <input name="phone" maxlength="15" inputmode="tel" autocomplete="tel">
            </label>
            <label>Email <span class="muted">(or mobile)</span>
              <input name="email" type="email" maxlength="120" autocomplete="email">
            </label>
            <button type="submit" class="btn secondary compact">Send contact</button>
            <p class="muted landing-interest-status"></p>
          </form>` : '';
      return `
        <article class="landing-card${featured ? ' is-featured' : ''}">
          ${listingImageHtml(item)}
          <strong>${escapeHtml(item.title || 'Listing')}</strong>
          <span class="landing-meta">${escapeHtml([meta, when].filter(Boolean).join(' · '))}${item.pinned ? ' · Pinned' : ''}</span>
          ${item.description || item.body ? `<p>${escapeHtml(item.description || item.body)}</p>` : ''}
          ${listingContactHtml(item, { phone })}
          ${interestHtml}
        </article>`;
    }

    try {
      const data = await api('/api/rwa/public/landing');
      landingLoaded = true;
      if (el('landingEyebrow') && data.eyebrow) {
        el('landingEyebrow').textContent = data.eyebrow;
      }
      if (el('landingHeroTitle') && data.colonyName) {
        el('landingHeroTitle').textContent = data.colonyName;
      }
      if (el('landingGreeting')) {
        el('landingGreeting').textContent = data.greeting
          || 'Unity · Harmony · Progress — the colony’s public face for residents and the city.';
      }
      if (updatesEl) {
        const updates = data.news || data.updates || [];
        updatesEl.innerHTML = updates.length
          ? updates.map((u, idx) => {
            const meta = [formatIstDate(u.publishedAt) || '', u.pinned ? 'Pinned' : '']
              .filter(Boolean).join(' · ');
            const body = (u.body || '').trim();
            const img = u.imageUrl && u.id
              ? `<img class="landing-card-photo" src="/api/rwa/public/notices/${encodeURIComponent(u.id)}/image?v=${encodeURIComponent(u.publishedAt || '')}" alt="" loading="lazy">`
              : '';
            return `
            <article class="landing-card landing-news-row${idx === 0 ? ' is-featured' : ''}">
              <div class="landing-news-head">
                <strong>${escapeHtml(u.title || 'Update')}</strong>
                ${meta ? `<span class="landing-meta">${escapeHtml(meta)}</span>` : ''}
              </div>
              <div class="landing-news-content">
                ${img}
                ${body ? `<p>${escapeHtml(body)}</p>` : ''}
              </div>
            </article>`;
          }).join('')
          : '<p class="muted">No public news yet.</p>';
      }
      if (adsEl) {
        const ads = data.ads || [];
        adsEl.innerHTML = ads.length
          ? ads.map((a) => landingCard(a, {
            phone: false,
            // Marketplace ads only (notice-board ads have no interest inbox).
            interest: Boolean(a.acceptsInterest) || (String(a.id || '').startsWith('mk_') && a.kind === 'ad'),
          })).join('')
          : '<p class="muted">No ads right now.</p>';
      }
      if (bizEl) {
        const businesses = data.businesses || [];
        bizEl.innerHTML = businesses.length
          ? businesses.map((b) => landingCard(b)).join('')
          : '<p class="muted">No published businesses yet. <a href="/gate-pass.html#register">Register one</a>.</p>';
      }
      if (needsEl && needsWrap) {
        const needs = data.serviceNeeds || [];
        if (needs.length) {
          needsWrap.hidden = false;
          needsEl.innerHTML = needs.map((n) => landingCard(n, { phone: false, interest: true })).join('');
        } else {
          needsWrap.hidden = true;
          needsEl.innerHTML = '';
        }
      }
      bindLandingInterestOnce();
      if (committeeEl) {
        const bearers = data.officeBearers || [];
        if (!bearers.length) {
          committeeEl.innerHTML = '<p class="muted">Office bearers will appear here when published by the society.</p>';
        } else {
          committeeEl.innerHTML = bearers.map((b) => `
            <div class="landing-bearer">
              <span class="landing-title">${escapeHtml(b.officialTitle || '')}</span>
              <span class="landing-name">${escapeHtml(b.name || '')}</span>
            </div>`).join('');
        }
      }
    } catch (err) {
      if (updatesEl && !landingLoaded) {
        updatesEl.innerHTML = `<p class="muted">${escapeHtml(err.message || 'Could not load news.')}</p>`;
      }
      if (adsEl && !landingLoaded) adsEl.innerHTML = '<p class="muted">Ads unavailable right now.</p>';
      if (bizEl && !landingLoaded) bizEl.innerHTML = '<p class="muted">Businesses unavailable right now.</p>';
      if (committeeEl && !landingLoaded) {
        committeeEl.innerHTML = '<p class="muted">Committee details unavailable right now.</p>';
      }
    }
  }

  function bindLandingInterestOnce() {
    if (bindLandingInterestOnce.done) return;
    bindLandingInterestOnce.done = true;
    document.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : event.target?.parentElement;
      const btn = target?.closest?.('.landing-interest-toggle');
      if (!btn) return;
      event.preventDefault();
      const card = btn.closest('article') || btn.parentElement;
      const form = card?.querySelector?.('.landing-interest-form')
        || document.querySelector(`.landing-interest-form[data-need-id="${btn.getAttribute('data-need-id')}"]`);
      if (!form) return;
      form.hidden = !form.hidden;
      if (!form.hidden) {
        form.querySelector('input')?.focus?.();
      }
    });
    document.addEventListener('submit', async (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const form = target?.closest?.('.landing-interest-form')
        || (target?.classList?.contains('landing-interest-form') ? target : null);
      if (!form) return;
      event.preventDefault();
      const id = form.getAttribute('data-need-id');
      const status = form.querySelector('.landing-interest-status');
      const btn = form.querySelector('button[type="submit"]');
      const name = (form.querySelector('[name="name"]')?.value || '').trim();
      const phone = (form.querySelector('[name="phone"]')?.value || '').trim();
      const email = (form.querySelector('[name="email"]')?.value || '').trim();
      if (!phone && !email) {
        if (status) status.textContent = 'Provide a mobile number or email.';
        return;
      }
      if (btn) btn.disabled = true;
      if (status) status.textContent = 'Sending…';
      try {
        const res = await fetch(`/api/rwa/public/marketplace/${encodeURIComponent(id)}/interest`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ contactName: name, phone, email }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) throw new Error(data.error || 'Could not send');
        if (status) status.textContent = 'Sent. The resident can now connect with you.';
        form.querySelectorAll('input').forEach((i) => { i.value = ''; });
      } catch (err) {
        if (status) status.textContent = err.message || 'Could not send';
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  function setAuthed(session) {
    state.session = session;
    if (session?.token) saveStoredToken(session.token);
    else if (!session) clearPersistedAuth();
    if (session?.resident?.houseId) saveLastHouseId(session.resident.houseId);
    const isAuthed = Boolean(session?.resident);
    document.body.classList.toggle('is-authed', isAuthed);
    applyInfoCentreProtectMode();
    const landing = el('landingView');
    const gate = el('gateView');
    const app = el('appView');
    if (app) app.hidden = !isAuthed;

    if (!isAuthed) {
      stopMsgPolling();
      stopNotifyPolling();
      updateMessagesBadge(0);
      updateNotifyBell(0);
      document.querySelectorAll('.admin-only, .superadmin-only').forEach((node) => {
        node.hidden = true;
      });
      const duesTab = el('duesTab') || document.querySelector('.tab[data-panel="dues"]');
      if (duesTab) duesTab.hidden = false;
      applyPreLoginRoute();
      return;
    }

    document.body.classList.remove('is-members-gate');
    if (landing) landing.hidden = true;
    if (gate) gate.hidden = true;

    const r = session.resident;
    const chip = el('userChip');
    if (chip) {
      const tag = r.superAdmin
        ? ' · Super admin'
        : (r.role === 'admin' ? ' · EC' : (r.viewOnly ? ' · View only' : (r.isPrimary ? '' : ` · ${r.relationLabel || 'Delegate'}`)));
      const label = r.superAdmin ? 'admin' : r.houseId;
      const titleBit = (r.officialTitle && r.role === 'admin') ? ` (${r.officialTitle})` : '';
      chip.textContent = `${label} · ${r.name}${titleBit}${tag}`;
      chip.title = chip.textContent;
    }
    renderUserAvatars(r);
    const deskChip = el('ecDeskRoleChip');
    if (deskChip) {
      if (canOpenEcDesk(r)) {
        const parts = [committeeRoleLabel(r)];
        if (r.officialTitle) parts.push(r.officialTitle);
        deskChip.textContent = parts.join(' · ');
        deskChip.hidden = false;
      } else {
        deskChip.textContent = '';
        deskChip.hidden = true;
      }
    }

    // Role chrome only — never unhide .panel sections here (that made EC desk
    // stack under Home). Panel visibility is owned by switchPanel().
    document.querySelectorAll('.admin-only').forEach((node) => {
      if (node.classList.contains('panel') || /^panel-/.test(node.id || '')) {
        if (!canOpenEcDesk(r)) {
          node.hidden = true;
          node.classList.remove('is-active');
        }
        return;
      }
      node.hidden = !canOpenEcDesk(r);
    });
    document.querySelectorAll('.ec-only').forEach((node) => {
      if (node.classList.contains('panel') || /^panel-/.test(node.id || '')) {
        if (!isEcMember(r)) {
          node.hidden = true;
          node.classList.remove('is-active');
        }
        return;
      }
      node.hidden = !isEcMember(r);
    });
    applyEntitlementVisibility();
    document.querySelectorAll('.superadmin-only').forEach((node) => {
      if (node.classList.contains('panel') || /^panel-/.test(node.id || '')) {
        if (!isSuperAdmin(r)) {
          node.hidden = true;
          node.classList.remove('is-active');
        }
        return;
      }
      node.hidden = !isSuperAdmin(r);
    });

    // Super admin has no personal dues / ledger view.
    const duesTab = el('duesTab') || document.querySelector('.tab[data-panel="dues"]');
    if (duesTab) duesTab.hidden = isSuperAdmin(r);
    if (isSuperAdmin(r) && el('panel-dues')) {
      el('panel-dues').hidden = true;
      el('panel-dues').classList.remove('is-active');
    }

    const officialWrap = el('profileOfficialTitleWrap');
    if (officialWrap) officialWrap.hidden = !(isEcAdmin(r) && !r.superAdmin);

    const meta = el('profileMemberMeta');
    if (meta) {
      if (r.superAdmin) {
        meta.hidden = true;
      } else {
        const bits = [
          r.relationLabel || (r.isPrimary ? 'Owner' : 'Delegate'),
          r.viewOnly ? 'view only' : null,
          r.householdName && r.householdName !== r.name ? `plot: ${r.householdName}` : null,
        ].filter(Boolean);
        meta.hidden = false;
        meta.textContent = bits.join(' · ');
      }
    }
    const profWrap = el('profileProfessionWrap');
    const empWrap = el('profileEmploymentWrap');
    const canEditPlotFields = Boolean(r.isPrimary || r.canManageHousehold) && !isViewOnly(r);
    if (profWrap) profWrap.hidden = !canEditPlotFields && !r.superAdmin;
    if (empWrap) empWrap.hidden = !canEditPlotFields && !r.superAdmin;
    if (el('profileName')) el('profileName').disabled = isViewOnly(r);
    if (el('profileTitle')) el('profileTitle').disabled = isViewOnly(r);

    if (el('profileHouse')) el('profileHouse').value = r.houseId || '';
    if (el('profileTitle')) el('profileTitle').value = r.title || '';
    if (el('profileName')) el('profileName').value = r.name || '';
    if (el('profileProfession')) el('profileProfession').value = r.profession || '';
    if (el('profileEmployment')) el('profileEmployment').value = r.employmentStatus || 'unknown';
    if (el('profileOfficialTitle')) el('profileOfficialTitle').value = r.officialTitle || '';
    if (el('profileEmail')) el('profileEmail').value = r.email || '';
    if (el('profilePhone')) el('profilePhone').value = r.phone || '';

    document.body.classList.toggle('is-view-only', isViewOnly(r));
    const grievanceForm = el('grievanceForm');
    if (grievanceForm) grievanceForm.hidden = isViewOnly(r);
    loadHouseholdMembers().catch(() => {});
    loadHouseholdTenants().catch(() => {});
    refreshMsgThreads().catch(() => {});
    refreshProfileAuthbuddyCard().catch(() => {});
    refreshNotificationInbox().catch(() => {});
    startNotifyPolling();
  }

  function activePanelName() {
    return document.querySelector('.tab.is-active')?.dataset?.panel || 'home';
  }

  function ensurePanelVisibility(preferred) {
    let name = preferred || activePanelName() || 'home';
    if (name === 'admin' && !canOpenEcDesk()) name = 'home';
    if (name === 'proceedings' && !isEcMember()) name = 'home';
    if (name === 'observability' && !isSuperAdmin()) name = 'home';
    if (name === 'dues' && isSuperAdmin()) name = 'home';
    switchPanel(name);
  }

  async function refreshSession() {
    const data = await api('/api/rwa/session');
    if (data.authenticated) {
      if (data.token) saveStoredToken(data.token);
      const preferred = activePanelName();
      setAuthed(data);
      const hash = (location.hash || '').replace(/^#/, '');
      if (infoDeepLink || hash === 'messages' || hash.startsWith('messages/') || hash === 'dues' || hash === 'concerns'
        || hash === 'profile' || hash === 'directory' || hash === 'parking' || hash.startsWith('parking?')
        || hash === 'info' || hash.startsWith('info/')
        || hash === 'works' || hash === 'admin'
        || hash === 'alerts' || hash === 'notifications') {
        applyRouteHash();
      } else {
        ensurePanelVisibility(preferred);
      }
    } else {
      clearPersistedAuth();
      setAuthed(null);
    }
  }

  function formatNoticeBody(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    const paragraphs = raw.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
    const blocks = paragraphs.length ? paragraphs : [raw];
    return blocks.map((block) => {
      const lines = block.split('\n').map((line) => {
        const escaped = escapeHtml(line);
        return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      });
      // A lone **Heading** line becomes a notice subhead
      if (lines.length === 1 && /^\*\*.+\*\*$/.test(block.trim())) {
        return `<p class="notice-subhead">${lines[0]}</p>`;
      }
      if (lines.length >= 2 && /^\*\*.+\*\*$/.test(block.split('\n')[0].trim())) {
        return `<p class="notice-subhead">${lines[0]}</p><p>${lines.slice(1).join('<br>')}</p>`;
      }
      return `<p>${lines.join('<br>')}</p>`;
    }).join('');
  }

  const WELCOME_NOTICE_ID = 'n_welcome';
  const RECENT_NOTICE_MS = 7 * 24 * 60 * 60 * 1000;

  function isRecentNotice(n) {
    const raw = n?.publishedAt;
    if (!raw) return false;
    const ts = Date.parse(raw);
    if (Number.isNaN(ts)) return false;
    return (Date.now() - ts) <= RECENT_NOTICE_MS;
  }

  function isWelcomeNotice(n) {
    return Boolean(n?.fixedTop) || n?.id === WELCOME_NOTICE_ID;
  }

  function noticeActionIcon(kind) {
    const icons = {
      up: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 14l6-6 6 6"/></svg>',
      down: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 10l6 6 6-6"/></svg>',
      edit: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
      pin: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 3h6l1 7 3 2v2H5v-2l3-2 1-7z"/></svg>',
      unpin: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 3h6l1 7 3 2v2H5v-2l3-2 1-7z"/></svg>',
      trash: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 14h10l1-14"/></svg>',
    };
    return `<span class="notice-action-icon" aria-hidden="true">${icons[kind] || ''}</span>`;
  }

  function renderNoticeCard(n, { canMoveUp = false, canMoveDown = false } = {}) {
    const date = n.publishedAt ? formatIstDate(n.publishedAt) : '';
    const welcome = isWelcomeNotice(n);
    const recent = isRecentNotice(n);
    const likeCount = Number(n.likeCount || 0);
    const commentCount = Number(n.commentCount || 0);
    const liked = Boolean(n.likedByMe);
    const viewOnly = isViewOnly();
    const engageDisabled = viewOnly ? ' disabled title="View-only access"' : '';
    const moveActions = (hasEntitlement('manage_notices') && n.pinned && !welcome) ? `
        <button type="button" class="notice-action-btn notice-move-up" data-id="${escapeHtml(n.id)}" ${canMoveUp ? '' : 'disabled'} title="Move up" aria-label="Move up">${noticeActionIcon('up')}</button>
        <button type="button" class="notice-action-btn notice-move-down" data-id="${escapeHtml(n.id)}" ${canMoveDown ? '' : 'disabled'} title="Move down" aria-label="Move down">${noticeActionIcon('down')}</button>` : '';
    const pinDelete = welcome
      ? ''
      : `
        <button type="button" class="notice-action-btn notice-pin${n.pinned ? ' is-active' : ''}" data-id="${escapeHtml(n.id)}" data-pinned="${n.pinned ? '1' : '0'}" title="${n.pinned ? 'Unpin' : 'Pin'}" aria-label="${n.pinned ? 'Unpin' : 'Pin'}">${noticeActionIcon(n.pinned ? 'unpin' : 'pin')}</button>
        <button type="button" class="notice-action-btn notice-delete" data-id="${escapeHtml(n.id)}" title="Delete" aria-label="Delete">${noticeActionIcon('trash')}</button>`;
    const actions = hasEntitlement('manage_notices') ? `
      <div class="notice-actions">
        ${moveActions}
        <button type="button" class="notice-action-btn notice-edit" data-id="${escapeHtml(n.id)}" title="Edit" aria-label="Edit">${noticeActionIcon('edit')}</button>
        ${pinDelete}
      </div>` : '';
    const badges = [
      welcome ? '<span class="notice-welcome-badge">Welcome</span>' : '',
      recent ? '<span class="notice-new-badge">New</span>' : '',
      (n.pinned && !welcome) ? '<span class="notice-pin-badge">Pinned</span>' : '',
    ].filter(Boolean).join('');
    return `
      <article class="notice mobile-fold ${n.pinned ? 'is-pinned' : ''} ${welcome ? 'is-welcome' : ''} ${recent ? 'is-recent' : ''}" data-id="${escapeHtml(n.id)}">
        <button type="button" class="mobile-fold-head" aria-expanded="false">
          <span class="mobile-fold-head-main">
            <span class="notice-head">
              <span class="notice-title">${escapeHtml(n.title)}</span>
              ${badges ? `<span class="notice-badges">${badges}</span>` : ''}
            </span>
            <span class="meta">${escapeHtml(n.category || 'general')}${date ? ` · ${escapeHtml(date)}` : ''}${recent ? ' · past week' : ''}</span>
          </span>
          <span class="mobile-fold-chevron" aria-hidden="true"></span>
        </button>
        <div class="mobile-fold-body">
          ${n.imageUrl ? `<img class="notice-photo" src="${escapeHtml(n.imageUrl)}?v=${encodeURIComponent(n.publishedAt || '')}" alt="" loading="lazy">` : ''}
          <div class="notice-body">${formatNoticeBody(n.body)}</div>
          ${actions}
        </div>
        <div class="notice-engage">
          <button type="button" class="notice-engage-btn notice-like${liked ? ' is-active' : ''}" data-id="${escapeHtml(n.id)}" aria-pressed="${liked ? 'true' : 'false'}" title="${viewOnly ? 'View-only access' : (liked ? 'Unlike' : 'Like')}"${engageDisabled}>
            <span class="notice-engage-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="${liked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-4.35-9.5-8.1C.7 10.1 1.5 6.8 4.4 5.4 6.5 4.4 9 5 12 7.4c3-2.4 5.5-3 7.6-2 2.9 1.4 3.7 4.7 1.9 7.5C19 16.65 12 21 12 21z"/></svg>
            </span>
            <span class="notice-like-count">${likeCount}</span>
            <span class="sr-only">Like</span>
          </button>
          <button type="button" class="notice-engage-btn notice-comment-toggle" data-id="${escapeHtml(n.id)}" aria-expanded="false" title="Comments">
            <span class="notice-engage-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 5h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/></svg>
            </span>
            <span class="notice-comment-count">${commentCount}</span>
            <span class="sr-only">Comments</span>
          </button>
        </div>
        <div class="notice-comments" data-id="${escapeHtml(n.id)}" hidden>
          <div class="notice-comments-list"><p class="muted">Loading comments…</p></div>
          ${viewOnly ? '<p class="muted">View-only access — you can read comments but not post.</p>' : `<form class="notice-comment-form stack" data-id="${escapeHtml(n.id)}">
            <label>
              <span class="sr-only">Add a comment</span>
              <textarea name="body" rows="2" maxlength="1000" placeholder="Write a comment…" required></textarea>
            </label>
            <button type="submit" class="btn secondary compact">Post comment</button>
          </form>`}
        </div>
      </article>`;
  }

  let noticesCache = [];
  let draftsCache = [];
  let ecMembersCache = null;

  async function loadHome() {
    const notices = await api('/api/rwa/notices');
    const list = el('noticeList');
    if (!list) return;
    noticesCache = (notices.notices || []).filter((n) => (n.status || 'published') === 'published');
    // Reorderable pinned notices exclude the fixed welcome notice.
    const pinnedIds = noticesCache
      .filter((n) => n.pinned && !isWelcomeNotice(n))
      .map((n) => n.id);
    list.innerHTML = noticesCache.length
      ? noticesCache.map((n) => {
          const pIdx = (n.pinned && !isWelcomeNotice(n)) ? pinnedIds.indexOf(n.id) : -1;
          return renderNoticeCard(n, {
            canMoveUp: pIdx > 0,
            canMoveDown: pIdx >= 0 && pIdx < pinnedIds.length - 1,
          });
        }).join('')
      : '<p class="muted">No notices yet.</p>';
    refreshMobileListUi();
    if (sectionLang.notices === 'hi') renderNoticesOverlay();
    syncBoardTabs();
    await loadColonyServices();
    refreshNotificationInbox().catch(() => {});
  }

  function updateNotifyBell(pendingCount) {
    const btn = el('notifyBellBtn');
    const mark = el('notifyBellMark');
    const n = Number(pendingCount) || 0;
    if (btn) {
      btn.classList.toggle('has-unread', n > 0);
      btn.setAttribute('aria-label', n > 0
        ? `Notifications, ${n} unresponded alert${n === 1 ? '' : 's'}`
        : 'Notifications');
    }
    if (mark) {
      mark.hidden = n < 1;
      mark.textContent = '';
    }
  }

  const NOTIFY_KIND_LABELS = {
    notice: 'Notice',
    concern: 'Mailbox',
    dues: 'Dues',
    treasury: 'Treasury',
    no_dues: 'No Dues',
    no_objection: 'No Objection',
    parking: 'Parking',
    adhoc: 'Gate',
    staff: 'Staff',
    message: 'Chat',
  };

  function notifyKindLabel(eventType) {
    return NOTIFY_KIND_LABELS[eventType] || 'Alert';
  }

  function renderNotificationInbox(data) {
    const body = el('notifyDialogBody');
    const lead = el('notifyDialogLead');
    const pending = data?.pending || [];
    const recent = (data?.recent || []).slice(0, 6);
    const items = data?.items || [];
    const chatUnread = (state.msgThreads || []).reduce((n, thread) => n + (Number(thread.unread) || 0), 0);
    const unreadCount = Number(data?.unreadCount);
    notifyState.pending = pending;
    notifyState.recent = recent;
    notifyState.items = items;
    notifyState.chatUnread = chatUnread;
    notifyState.unreadCount = Number.isFinite(unreadCount)
      ? unreadCount
      : pending.length + items.filter((item) => !item.readAt).length;
    updateNotifyBell(notifyState.unreadCount);
    if (lead) {
      lead.textContent = notifyState.unreadCount
        ? `${notifyState.unreadCount} unresponded alert${notifyState.unreadCount === 1 ? '' : 's'} for this plot.`
        : 'Alerts for this plot — notices, dues, mailbox, parking, and votes.';
    }
    if (!body) return;
    if (!pending.length && !items.length && !recent.length && chatUnread < 1) {
      body.innerHTML = '<p class="notify-empty">You are all caught up. Notices, dues, mailbox, parking, and votes will appear here.</p>';
      return;
    }
    const pendingHtml = pending.length
      ? `<div class="resolution-votes-list">${pending.map((item) => `
          <article class="resolution-vote-card" data-ballot-id="${escapeHtml(item.ballotId)}" data-vote-id="${escapeHtml(item.voteId)}">
            <p class="notify-alert-kind">Resolution vote</p>
            <h4>Resolution ${escapeHtml(item.resolutionNo || '')}</h4>
            <p class="muted">${escapeHtml(item.meetingTypeLabel || '')}${item.meetingTitle ? ' · ' + escapeHtml(item.meetingTitle) : ''}${item.meetingDate ? ' · ' + escapeHtml(formatIstDate(item.meetingDate) || item.meetingDate) : ''}</p>
            <p class="vote-text">${escapeHtml(item.resolutionText || '')}</p>
            ${item.deadline ? `<p class="muted">Deadline ${escapeHtml(formatIstDate(String(item.deadline).slice(0, 10)) || String(item.deadline).slice(0, 10))}</p>` : ''}
            ${item.note ? `<p class="muted">${escapeHtml(item.note)}</p>` : ''}
            <div class="btn-row">
              <button type="button" class="btn primary compact" data-cast="accept">Accept</button>
              <button type="button" class="btn ghost compact" data-cast="reject">Reject</button>
            </div>
          </article>`).join('')}</div>`
      : '';
    const chatHtml = chatUnread > 0
      ? `<button type="button" class="notify-alert-card is-unread" data-notify-hash="messages">
          <p class="notify-alert-kind">Chat</p>
          <h4>Unread messages</h4>
          <p class="muted">${chatUnread} new message${chatUnread === 1 ? '' : 's'} in Chat.</p>
        </button>`
      : '';
    const alertsHtml = items.length
      ? `${pending.length || chatUnread ? '<p class="muted">Alerts</p>' : ''}
        <div class="notify-alerts-list">${items.map((item) => `
          <button type="button" class="notify-alert-card${item.readAt ? '' : ' is-unread'}" data-notify-id="${escapeHtml(item.id)}" data-notify-url="${escapeHtml(item.url || '/#home')}">
            <p class="notify-alert-kind">${escapeHtml(notifyKindLabel(item.eventType))}</p>
            <h4>${escapeHtml(item.title || 'Alert')}</h4>
            ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ''}
            ${item.createdAt ? `<p class="muted">${escapeHtml(formatIstDateTime(item.createdAt) || item.createdAt)}</p>` : ''}
          </button>`).join('')}</div>`
      : '';
    const recentHtml = recent.length
      ? `<p class="muted">Recent votes</p>
        <div class="resolution-votes-list">${recent.map((item) => `
          <article class="resolution-vote-card">
            <h4>Resolution ${escapeHtml(item.resolutionNo || '')}</h4>
            <p class="muted">${escapeHtml(item.meetingTitle || '')}${item.meetingDate ? ' · ' + escapeHtml(formatIstDate(item.meetingDate) || item.meetingDate) : ''}</p>
            <p class="vote-recorded">${item.choice === 'accept' ? 'You accepted' : (item.choice === 'reject' ? 'You rejected' : escapeHtml(item.statusLabel || 'Recorded'))}${item.status && item.status !== 'open' ? ' · ' + escapeHtml(item.statusLabel) : ''}</p>
          </article>`).join('')}</div>`
      : '';
    body.innerHTML = pendingHtml + chatHtml + alertsHtml + recentHtml;
  }

  async function refreshNotificationInbox() {
    if (!state.session?.resident || isSuperAdmin()) {
      notifyState.pending = [];
      notifyState.recent = [];
      notifyState.items = [];
      notifyState.chatUnread = 0;
      notifyState.unreadCount = 0;
      updateNotifyBell(0);
      const body = el('notifyDialogBody');
      if (body && el('notifyDialog')?.open) {
        body.innerHTML = '<p class="notify-empty">No alerts for this account.</p>';
      }
      return;
    }
    try {
      const data = await api('/api/rwa/notifications');
      renderNotificationInbox(data);
      if (el('notifyDialog')?.open) {
        await markNotificationsSeen();
      }
    } catch (_e) {
      updateNotifyBell(notifyState.unreadCount || notifyState.pending.length);
    }
  }

  async function markNotificationsSeen() {
    if (!state.session?.resident || isSuperAdmin()) return;
    if (!notifyState.items.some((item) => !item.readAt)) return;
    try {
      const data = await api('/api/rwa/notifications/read', {
        method: 'POST',
        body: JSON.stringify({}),
      });
      notifyState.items = (data.items || notifyState.items).map((item) => ({
        ...item,
        readAt: item.readAt || 'seen',
      }));
      notifyState.unreadCount = Number(data.unreadCount) || notifyState.pending.length;
      updateNotifyBell(notifyState.unreadCount);
      if (el('notifyDialogLead') && !notifyState.unreadCount) {
        el('notifyDialogLead').textContent = 'Alerts for this plot — notices, dues, mailbox, parking, and votes.';
      }
    } catch (_e) {
      /* keep unread mark if mark-read fails */
    }
  }

  function startNotifyPolling() {
    stopNotifyPolling();
    notifyState.timer = setInterval(() => {
      if (!state.session?.resident) return;
      refreshNotificationInbox().catch(() => {});
    }, 60000);
  }

  function stopNotifyPolling() {
    if (notifyState.timer) {
      clearInterval(notifyState.timer);
      notifyState.timer = null;
    }
  }

  async function openNotificationsDialog() {
    const dlg = el('notifyDialog');
    const btn = el('notifyBellBtn');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    await refreshNotificationInbox();
    dlg?.showModal();
    await markNotificationsSeen();
  }

  function closeNotificationsDialog() {
    const dlg = el('notifyDialog');
    const btn = el('notifyBellBtn');
    if (dlg?.open) dlg.close();
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function openNotifyAlert(card) {
    const hash = card.getAttribute('data-notify-hash');
    const url = card.getAttribute('data-notify-url') || '';
    closeNotificationsDialog();
    if (hash) {
      location.hash = hash;
      applyRouteHash();
      return;
    }
    const raw = String(url || '').trim();
    if (!raw || raw === '/' || raw === '/#') {
      location.hash = 'home';
      applyRouteHash();
      return;
    }
    if (raw.startsWith('/#') || raw.startsWith('#')) {
      location.hash = raw.replace(/^\/?#/, '');
      applyRouteHash();
      return;
    }
    if (raw.startsWith('/') && !raw.startsWith('//')) {
      location.assign(raw);
      return;
    }
    location.hash = 'home';
    applyRouteHash();
  }

  async function castMyResolutionVote(card, choice) {
    const voteId = card.getAttribute('data-vote-id');
    const ballotId = card.getAttribute('data-ballot-id');
    await api('/api/rwa/my-votes', {
      method: 'POST',
      body: JSON.stringify({ voteId, ballotId, choice }),
    });
    await refreshNotificationInbox();
  }

  const boardState = { tab: 'notices' };

  function syncBoardTabs() {
    const tab = boardState.tab === 'services' ? 'services' : 'notices';
    document.querySelectorAll('.board-panel-tab').forEach((btn) => {
      const on = btn.dataset.boardTab === tab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const noticesPane = el('boardTabNotices');
    const servicesPane = el('boardTabServices');
    if (noticesPane) noticesPane.hidden = tab !== 'notices';
    if (servicesPane) servicesPane.hidden = tab !== 'services';
    const lead = el('boardPanelLead');
    if (lead) {
      lead.textContent = tab === 'services'
        ? 'Staff, helplines, and recurring schedules.'
        : 'EC notices and pinned updates.';
    }
    const langToggle = el('boardLangToggle');
    const editBtn = el('colonyServicesEditBtn');
    if (langToggle) langToggle.hidden = tab !== 'notices';
    if (editBtn && hasEntitlement('manage_notices')) editBtn.hidden = tab !== 'services';
  }

  function setBoardTab(tab, { updateHash = true } = {}) {
    boardState.tab = tab === 'services' ? 'services' : 'notices';
    syncBoardTabs();
    if (updateHash && state.session?.resident) {
      const nextHash = boardState.tab === 'services' ? '#home/services' : '#home';
      if (location.hash !== nextHash) {
        history.replaceState(null, '', `${location.pathname}${location.search}${nextHash}`);
      }
    }
    if (boardState.tab === 'services') {
      loadColonyServices().catch(console.error);
    }
  }

  function applyBoardRouteHash() {
    const hash = (location.hash || '').replace(/^#/, '');
    if (hash === 'home/services' || hash.startsWith('home/services/')) {
      setBoardTab('services', { updateHash: false });
      return true;
    }
    if (hash === 'home' || hash.startsWith('home/')) {
      setBoardTab('notices', { updateHash: false });
      return true;
    }
    return false;
  }

  let colonyServicesCache = null;
  let colonyServicesEditing = false;

  function colonyServicesPhoneHtml(phone) {
    if (!phone) return '';
    const digits = String(phone).replace(/[^\d+]/g, '');
    if (!digits) return escapeHtml(phone);
    return `<a href="tel:${escapeHtml(digits)}">${escapeHtml(phone)}</a>`;
  }

  function colonyServicesFieldDefs(kind) {
    if (kind === 'staff') {
      return [
        { key: 'name', label: 'Name', placeholder: 'Staff name' },
        { key: 'role', label: 'Role', placeholder: 'Watchman, gardener…' },
        { key: 'responsibility', label: 'Responsibility', placeholder: 'What they handle', multiline: true },
        { key: 'phone', label: 'Phone', placeholder: 'Mobile or gate phone' },
        { key: 'hours', label: 'Hours / shift', placeholder: 'Timing' },
        { key: 'notes', label: 'Notes', placeholder: 'Optional', multiline: true },
      ];
    }
    if (kind === 'contacts') {
      return [
        { key: 'department', label: 'Department', placeholder: 'Water, electricity…' },
        { key: 'forIssues', label: 'For issues', placeholder: 'When residents should call', multiline: true },
        { key: 'contactName', label: 'Contact / office', placeholder: 'Person or helpline name' },
        { key: 'phone', label: 'Phone', placeholder: 'Primary number' },
        { key: 'altPhone', label: 'Alt phone', placeholder: 'Backup number' },
        { key: 'hours', label: 'Hours', placeholder: 'Availability' },
        { key: 'notes', label: 'Notes', placeholder: 'Optional', multiline: true },
      ];
    }
    return [
      { key: 'activity', label: 'Activity', placeholder: 'Water tanker, waste pickup…' },
      { key: 'detail', label: 'Details', placeholder: 'What happens', multiline: true },
      { key: 'when', label: 'When', placeholder: 'Day / time' },
      { key: 'where', label: 'Where', placeholder: 'Location' },
      { key: 'contact', label: 'Contact', placeholder: 'Who coordinates' },
      { key: 'notes', label: 'Notes', placeholder: 'Optional', multiline: true },
    ];
  }

  function colonyServicesEditorTarget(kind) {
    return ({
      staff: el('colonyStaffEditor'),
      contacts: el('colonyContactsEditor'),
      schedule: el('colonyScheduleEditor'),
    })[kind];
  }

  function renderColonyServicesEditorRow(kind, row, idx) {
    const fields = colonyServicesFieldDefs(kind);
    const inputs = fields.map((f) => {
      const val = escapeHtml(row[f.key] || '');
      if (f.multiline) {
        return `<label><span>${escapeHtml(f.label)}</span><textarea data-cs-field="${f.key}" rows="2" placeholder="${escapeHtml(f.placeholder || '')}">${val}</textarea></label>`;
      }
      return `<label><span>${escapeHtml(f.label)}</span><input data-cs-field="${f.key}" type="text" value="${val}" placeholder="${escapeHtml(f.placeholder || '')}"></label>`;
    }).join('');
    return `
      <article class="colony-services-edit-row" data-cs-kind="${kind}" data-cs-id="${escapeHtml(row.id || '')}" data-cs-idx="${idx}">
        <div class="colony-services-edit-fields">${inputs}</div>
        <button type="button" class="btn ghost compact colony-services-remove" data-cs-remove="${kind}">Remove</button>
      </article>`;
  }

  function renderColonyServicesEditor(data) {
    ['staff', 'contacts', 'schedule'].forEach((kind) => {
      const box = colonyServicesEditorTarget(kind);
      if (!box) return;
      const rows = Array.isArray(data[kind]) ? data[kind] : [];
      box.innerHTML = rows.length
        ? rows.map((row, idx) => renderColonyServicesEditorRow(kind, row, idx)).join('')
        : '<p class="muted">No rows yet — add one.</p>';
    });
  }

  function colonyServicesBlankRow(kind) {
    const row = { id: `${kind}_${Math.random().toString(16).slice(2, 10)}` };
    colonyServicesFieldDefs(kind).forEach((f) => { row[f.key] = ''; });
    return row;
  }

  function readColonyServicesEditor() {
    const out = { staff: [], contacts: [], schedule: [] };
    ['staff', 'contacts', 'schedule'].forEach((kind) => {
      const box = colonyServicesEditorTarget(kind);
      if (!box) return;
      box.querySelectorAll('.colony-services-edit-row').forEach((node) => {
        const row = { id: node.getAttribute('data-cs-id') || '' };
        node.querySelectorAll('[data-cs-field]').forEach((input) => {
          row[input.getAttribute('data-cs-field')] = input.value.trim();
        });
        out[kind].push(row);
      });
    });
    return out;
  }

  function setColonyServicesEditing(on) {
    colonyServicesEditing = on;
    const view = el('colonyServicesView');
    const editor = el('colonyServicesEditor');
    const editBtn = el('colonyServicesEditBtn');
    if (view) view.hidden = on;
    if (editor) editor.hidden = !on;
    if (editBtn) editBtn.textContent = on ? 'Done' : 'Edit';
  }

  function renderColonyServicesView(data) {
    const box = el('colonyServicesView');
    if (!box || !data) return;
    const staffCards = (data.staff || []).map((s) => `
      <article class="colony-service-card">
        <header class="colony-service-card-head">
          <strong>${escapeHtml(s.role || 'Staff')}</strong>
          ${s.name ? `<span class="colony-service-name">${escapeHtml(s.name)}</span>` : ''}
        </header>
        ${s.responsibility ? `<p>${escapeHtml(s.responsibility)}</p>` : ''}
        <dl class="colony-service-meta">
          ${s.phone ? `<div><dt>Phone</dt><dd>${colonyServicesPhoneHtml(s.phone)}</dd></div>` : ''}
          ${s.hours ? `<div><dt>Hours</dt><dd>${escapeHtml(s.hours)}</dd></div>` : ''}
        </dl>
        ${s.notes ? `<p class="muted colony-service-notes">${escapeHtml(s.notes)}</p>` : ''}
      </article>
    `).join('');
    const contactCards = (data.contacts || []).map((c) => `
      <article class="colony-service-card">
        <header class="colony-service-card-head">
          <strong>${escapeHtml(c.department || 'Contact')}</strong>
        </header>
        ${c.forIssues ? `<p class="colony-service-issue">${escapeHtml(c.forIssues)}</p>` : ''}
        ${c.contactName ? `<p>${escapeHtml(c.contactName)}</p>` : ''}
        <dl class="colony-service-meta">
          ${c.phone ? `<div><dt>Phone</dt><dd>${colonyServicesPhoneHtml(c.phone)}</dd></div>` : ''}
          ${c.altPhone ? `<div><dt>Alt</dt><dd>${colonyServicesPhoneHtml(c.altPhone)}</dd></div>` : ''}
          ${c.hours ? `<div><dt>Hours</dt><dd>${escapeHtml(c.hours)}</dd></div>` : ''}
        </dl>
        ${c.notes ? `<p class="muted colony-service-notes">${escapeHtml(c.notes)}</p>` : ''}
      </article>
    `).join('');
    const scheduleCards = (data.schedule || []).map((s) => `
      <article class="colony-service-card">
        <header class="colony-service-card-head">
          <strong>${escapeHtml(s.activity || 'Activity')}</strong>
          ${s.when ? `<span class="colony-service-when">${escapeHtml(s.when)}</span>` : ''}
        </header>
        ${s.detail ? `<p>${escapeHtml(s.detail)}</p>` : ''}
        <dl class="colony-service-meta">
          ${s.where ? `<div><dt>Where</dt><dd>${escapeHtml(s.where)}</dd></div>` : ''}
          ${s.contact ? `<div><dt>Contact</dt><dd>${escapeHtml(s.contact)}</dd></div>` : ''}
        </dl>
        ${s.notes ? `<p class="muted colony-service-notes">${escapeHtml(s.notes)}</p>` : ''}
      </article>
    `).join('');
    box.innerHTML = `
      <section class="colony-services-column">
        <h4 class="colony-services-column-title">Society staff</h4>
        <div class="colony-services-cards">${staffCards || '<p class="muted">No staff listed yet.</p>'}</div>
      </section>
      <section class="colony-services-column">
        <h4 class="colony-services-column-title">Who to call</h4>
        <div class="colony-services-cards">${contactCards || '<p class="muted">No contacts listed yet.</p>'}</div>
      </section>
      <section class="colony-services-column">
        <h4 class="colony-services-column-title">Schedule</h4>
        <div class="colony-services-cards">${scheduleCards || '<p class="muted">No schedule posted yet.</p>'}</div>
      </section>`;
    const status = el('colonyServicesStatus');
    if (status) {
      if (data.updatedAt) {
        const by = data.updatedBy ? ` · ${data.updatedBy}` : '';
        status.textContent = `Last updated ${formatIstDateTime(data.updatedAt)}${by}`;
      } else {
        status.textContent = '';
      }
    }
  }

  async function loadColonyServices() {
    const view = el('colonyServicesView');
    if (!view || !state.session) return;
    try {
      const data = await api('/api/rwa/colony-services');
      colonyServicesCache = data.colonyServices || null;
      renderColonyServicesView(colonyServicesCache);
      if (colonyServicesEditing && colonyServicesCache) {
        renderColonyServicesEditor(colonyServicesCache);
      }
    } catch (err) {
      view.innerHTML = `<p class="muted">${escapeHtml(err.message || 'Could not load services')}</p>`;
    }
  }

  async function saveColonyServices() {
    const status = el('colonyServicesStatus');
    if (status) status.textContent = 'Saving…';
    try {
      const payload = readColonyServicesEditor();
      const data = await api('/api/rwa/colony-services', { method: 'PUT', body: JSON.stringify(payload) });
      colonyServicesCache = data.colonyServices;
      setColonyServicesEditing(false);
      renderColonyServicesView(colonyServicesCache);
      if (status) status.textContent = 'Saved.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Save failed';
    }
  }

  function addColonyServicesRow(kind) {
    const box = colonyServicesEditorTarget(kind);
    if (!box) return;
    const row = colonyServicesBlankRow(kind);
    const empty = box.querySelector('.muted');
    if (empty && !box.querySelector('.colony-services-edit-row')) {
      box.innerHTML = '';
    }
    const idx = box.querySelectorAll('.colony-services-edit-row').length;
    box.insertAdjacentHTML('beforeend', renderColonyServicesEditorRow(kind, row, idx));
  }

  let marketplaceCategories = {
    business: [
      { id: 'auto_hire', label: 'Auto for hire' },
      { id: 'cab_rent', label: 'Car / cab for rent' },
      { id: 'maid', label: 'Maid / domestic help' },
      { id: 'cook', label: 'Cook' },
      { id: 'other', label: 'Other' },
    ],
    service_need: [
      { id: 'auto_hire', label: 'Need auto / taxi' },
      { id: 'maid', label: 'Need maid / domestic help' },
      { id: 'cook', label: 'Need cook' },
      { id: 'other', label: 'Other need' },
    ],
    ad: [],
  };
  let adsCache = [];
  let listingsCache = [];

  function marketplaceStatusLabel(status, kind) {
    if (status === 'archived') return kind === 'ad' ? 'Disabled' : 'Suspended';
    return {
      pending: 'Pending',
      published: 'Published',
      rejected: 'Rejected',
    }[status] || status || '';
  }

  function marketplaceListingPhotoHtml(item) {
    if (!item?.imageUrl) return '';
    const v = item.updatedAt || item.publishedAt || '';
    const src = `${item.imageUrl}${v ? `?v=${encodeURIComponent(v)}` : ''}`;
    return `<img class="landing-card-photo" src="${escapeHtml(src)}" alt="" loading="lazy">`;
  }

  async function loadMarketplaceModeration() {
    const box = el('marketplacePendingList');
    if (!box || !hasEntitlement('manage_notices')) return;
    const filter = el('marketplaceModerateStatusFilter')?.value || 'pending';
    try {
      const data = await api(`/api/rwa/marketplace?status=${encodeURIComponent(filter)}&limit=80`);
      if (data.categories) marketplaceCategories = data.categories;
      listingsCache = (data.items || []).filter((i) => i.kind !== 'ad');
      const items = listingsCache;
      if (!items.length) {
        const empty = filter === 'pending'
          ? 'No pending city listings.'
          : filter === 'archived'
            ? 'No suspended listings.'
            : 'No city listings in this view.';
        box.innerHTML = `<p class="muted">${empty}</p>`;
        return;
      }
      box.innerHTML = items.map((i) => {
        const actions = [
          '<button type="button" class="btn secondary compact" data-mk-action="edit">Edit</button>',
        ];
        if (i.status === 'archived') {
          actions.push('<button type="button" class="btn secondary compact" data-mk-action="published">Enable</button>');
        } else if (i.status !== 'published') {
          actions.push('<button type="button" class="btn secondary compact" data-mk-action="published">Publish</button>');
        }
        if (i.status === 'pending' || i.status === 'published') {
          actions.push('<button type="button" class="btn ghost compact" data-mk-action="rejected">Reject</button>');
        }
        if (i.status !== 'archived') {
          actions.push('<button type="button" class="btn ghost compact" data-mk-action="archived">Suspend</button>');
        }
        actions.push('<button type="button" class="btn ghost compact" data-mk-action="delete">Remove</button>');
        const reg = i.regNo ? `${escapeHtml(i.regNo)} · ` : '';
        return `
        <article class="landing-update" data-mk-id="${escapeHtml(i.id)}">
          ${marketplaceListingPhotoHtml(i)}
          <strong>${escapeHtml(i.title)}</strong>
          <span class="landing-meta">${reg}${escapeHtml(i.kindLabel || i.kind)} · ${escapeHtml(marketplaceStatusLabel(i.status, i.kind))} · ${escapeHtml(i.categoryLabel || '')} · ${escapeHtml(i.contactName || '')} · ${escapeHtml(i.phone || '')}${i.area ? ' · ' + escapeHtml(i.area) : ''}</span>
          ${i.description ? `<p>${escapeHtml(i.description)}</p>` : ''}
          <div class="btn-row" style="margin-top:0.45rem">${actions.join('')}</div>
        </article>`;
      }).join('');
    } catch (err) {
      box.innerHTML = `<p class="muted">${escapeHtml(err.message || 'Could not load pending listings')}</p>`;
      listingsCache = [];
    }
  }

  function fillMarketplaceListingCategories(kind, selected) {
    const sel = el('marketplaceListingCategory');
    if (!sel) return;
    const opts = marketplaceCategories[kind] && marketplaceCategories[kind].length
      ? marketplaceCategories[kind]
      : [{ id: 'other', label: 'Other' }];
    sel.innerHTML = opts.map((o) => `<option value="${escapeHtml(o.id)}">${escapeHtml(o.label)}</option>`).join('');
    if (selected) sel.value = selected;
  }

  function resetMarketplaceListingForm() {
    const form = el('marketplaceListingForm');
    if (form) form.reset();
    if (form) form.hidden = true;
    if (el('marketplaceListingEditId')) el('marketplaceListingEditId').value = '';
    if (el('marketplaceListingFormTitle')) el('marketplaceListingFormTitle').textContent = 'Edit listing';
    if (el('marketplaceListingMeta')) el('marketplaceListingMeta').textContent = '';
    if (el('marketplaceListingImagePreview')) {
      el('marketplaceListingImagePreview').hidden = true;
      el('marketplaceListingImagePreview').removeAttribute('src');
    }
    if (el('marketplaceListingStatus')) el('marketplaceListingStatus').textContent = '';
  }

  function startMarketplaceListingEdit(item) {
    if (!item) return;
    const form = el('marketplaceListingForm');
    if (form) form.hidden = false;
    if (el('marketplaceListingEditId')) el('marketplaceListingEditId').value = item.id || '';
    if (el('marketplaceListingTitle')) el('marketplaceListingTitle').value = item.title || '';
    fillMarketplaceListingCategories(item.kind || 'business', item.category || 'other');
    if (el('marketplaceListingDesc')) el('marketplaceListingDesc').value = item.description || '';
    if (el('marketplaceListingName')) el('marketplaceListingName').value = item.contactName || '';
    if (el('marketplaceListingPhone')) el('marketplaceListingPhone').value = item.phone || '';
    if (el('marketplaceListingEmail')) el('marketplaceListingEmail').value = item.email || '';
    if (el('marketplaceListingWebsite')) el('marketplaceListingWebsite').value = item.website || '';
    if (el('marketplaceListingArea')) el('marketplaceListingArea').value = item.area || '';
    const webWrap = el('marketplaceListingWebsiteWrap');
    if (webWrap) webWrap.hidden = item.kind !== 'business';
    if (el('marketplaceListingImage')) el('marketplaceListingImage').value = '';
    const preview = el('marketplaceListingImagePreview');
    if (preview) {
      if (item.imageUrl) {
        preview.src = `${item.imageUrl}?v=${encodeURIComponent(item.updatedAt || item.publishedAt || '')}`;
        preview.hidden = false;
      } else {
        preview.hidden = true;
        preview.removeAttribute('src');
      }
    }
    const bits = [item.regNo, marketplaceStatusLabel(item.status, item.kind), item.kindLabel || item.kind].filter(Boolean);
    if (el('marketplaceListingMeta')) el('marketplaceListingMeta').textContent = bits.join(' · ');
    if (el('marketplaceListingFormTitle')) el('marketplaceListingFormTitle').textContent = item.kind === 'business' ? 'Edit business' : 'Edit listing';
    if (el('marketplaceListingStatus')) el('marketplaceListingStatus').textContent = '';
    form?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function resetMarketplaceAdForm() {
    const form = el('marketplaceAdForm');
    if (form) form.reset();
    if (el('marketplaceAdEditId')) el('marketplaceAdEditId').value = '';
    if (el('marketplaceAdFormTitle')) el('marketplaceAdFormTitle').textContent = 'New ad';
    if (el('marketplaceAdSubmitBtn')) el('marketplaceAdSubmitBtn').textContent = 'Publish ad';
    if (el('marketplaceAdCancelBtn')) el('marketplaceAdCancelBtn').hidden = true;
    if (el('marketplaceShareCityInput')) el('marketplaceShareCityInput').checked = false;
    const shareLabel = el('marketplaceShareCityInput')?.closest('label');
    if (shareLabel) shareLabel.hidden = false;
    if (el('marketplaceAdImagePreview')) {
      el('marketplaceAdImagePreview').hidden = true;
      el('marketplaceAdImagePreview').removeAttribute('src');
    }
    if (el('marketplaceAdStatus')) el('marketplaceAdStatus').textContent = '';
  }

  function startMarketplaceAdEdit(item) {
    if (!item) return;
    switchPanel('concerns');
    if (el('marketplaceAdEditId')) el('marketplaceAdEditId').value = item.id || '';
    if (el('marketplaceAdTitle')) el('marketplaceAdTitle').value = item.title || '';
    if (el('marketplaceAdCategory')) el('marketplaceAdCategory').value = item.category || 'colony';
    if (el('marketplaceAdDesc')) el('marketplaceAdDesc').value = item.description || '';
    if (el('marketplaceAdName')) el('marketplaceAdName').value = item.contactName || '';
    if (el('marketplaceAdPhone')) el('marketplaceAdPhone').value = item.phone || '';
    if (el('marketplaceShareCityInput')) el('marketplaceShareCityInput').checked = false;
    const shareLabel = el('marketplaceShareCityInput')?.closest('label');
    if (shareLabel) shareLabel.hidden = true;
    if (el('marketplaceAdImage')) el('marketplaceAdImage').value = '';
    const preview = el('marketplaceAdImagePreview');
    if (preview) {
      if (item.imageUrl) {
        preview.src = `${item.imageUrl}?v=${encodeURIComponent(item.updatedAt || item.publishedAt || '')}`;
        preview.hidden = false;
      } else {
        preview.hidden = true;
        preview.removeAttribute('src');
      }
    }
    if (el('marketplaceAdFormTitle')) el('marketplaceAdFormTitle').textContent = 'Edit ad';
    if (el('marketplaceAdSubmitBtn')) el('marketplaceAdSubmitBtn').textContent = 'Save ad';
    if (el('marketplaceAdCancelBtn')) el('marketplaceAdCancelBtn').hidden = false;
    if (el('marketplaceAdStatus')) el('marketplaceAdStatus').textContent = `Editing ${item.id}`;
    el('marketplaceAdForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadMarketplaceAds() {
    const box = el('marketplaceAdsList');
    if (!box || !hasEntitlement('manage_notices')) return;
    const filter = el('marketplaceAdsStatusFilter')?.value || 'published';
    try {
      const data = await api(`/api/rwa/marketplace?kind=ad&status=${encodeURIComponent(filter)}&limit=80`);
      if (data.categories) marketplaceCategories = data.categories;
      adsCache = data.items || [];
      if (!adsCache.length) {
        const empty = filter === 'archived' ? 'No disabled ads.' : 'No ads in this view.';
        box.innerHTML = `<p class="muted">${empty}</p>`;
        return;
      }
      box.innerHTML = adsCache.map((i) => {
        const actions = [
          `<button type="button" class="btn secondary compact" data-ad-action="edit">Edit</button>`,
        ];
        if (i.status === 'published') {
          actions.push('<button type="button" class="btn ghost compact" data-ad-action="archived">Disable</button>');
        } else {
          actions.push('<button type="button" class="btn secondary compact" data-ad-action="published">Enable</button>');
        }
        actions.push('<button type="button" class="btn ghost compact" data-ad-action="delete">Remove</button>');
        return `
        <article class="landing-update" data-ad-id="${escapeHtml(i.id)}">
          ${marketplaceListingPhotoHtml(i)}
          <strong>${escapeHtml(i.title)}</strong>
          <span class="landing-meta">${escapeHtml(marketplaceStatusLabel(i.status, i.kind))} · ${escapeHtml(i.categoryLabel || '')} · ${escapeHtml(i.contactName || '')} · ${escapeHtml(i.phone || '')}</span>
          ${i.description ? `<p>${escapeHtml(i.description)}</p>` : ''}
          <div class="btn-row" style="margin-top:0.45rem">${actions.join('')}</div>
        </article>`;
      }).join('');
    } catch (err) {
      adsCache = [];
      box.innerHTML = `<p class="muted">${escapeHtml(err.message || 'Could not load ads')}</p>`;
    }
  }

  function draftShareSummary(n) {
    const shares = n.sharedWith || [];
    if (n.sharedWithMe) {
      return n.canEdit
        ? 'Shared with you · edit until published'
        : 'Shared with you · view only';
    }
    if (!shares.length) return n.isOwner ? 'Private to you' : '';
    const editors = shares.filter((s) => s.canEdit).length;
    const viewers = shares.length - editors;
    const names = shares.map((s) => {
      const label = s.label || s.name || s.houseId;
      return `${label} (${s.canEdit ? 'edit' : 'view'})`;
    }).slice(0, 2);
    const more = shares.length > 2 ? ` +${shares.length - 2}` : '';
    const mix = viewers
      ? `${editors} edit · ${viewers} view`
      : `${editors} can edit`;
    return `Shared with ${names.join(', ')}${more} · ${mix}`;
  }

  function renderDraftList() {
    const box = el('noticeDraftList');
    const stats = el('noticeDraftStats');
    if (!box) return;
    if (!draftsCache.length) {
      box.innerHTML = '<p class="muted">No drafts yet. Write a notice below, or wait for another EC member to share one with you.</p>';
      if (stats) stats.textContent = 'Write, save drafts, share with EC, and publish to the colony board.';
      return;
    }
    if (stats) {
      stats.textContent = `${draftsCache.length} draft${draftsCache.length === 1 ? '' : 's'} · share as edit (default) or view only`;
    }
    box.innerHTML = draftsCache.map((n) => {
      const excerpt = String(n.body || '').trim() || 'No body yet.';
      const short = excerpt.length > 160 ? `${excerpt.slice(0, 157)}…` : excerpt;
      const when = formatIstDateTime(n.publishedAt || n.updatedAt);
      const canEdit = n.canEdit !== false;
      const isOwner = Boolean(n.isOwner);
      const shareLine = draftShareSummary(n);
      const badges = [
        '<span class="notice-draft-badge">Draft</span>',
        n.sharedWithMe ? '<span class="notice-draft-badge">Shared with you</span>' : '',
        !canEdit ? '<span class="notice-draft-badge">View only</span>' : '',
      ].filter(Boolean).join('');
      const actions = [];
      if (canEdit) {
        actions.push(`<button type="button" class="btn secondary compact notice-draft-edit" data-id="${escapeHtml(n.id)}">Continue editing</button>`);
        actions.push(`<button type="button" class="btn primary compact notice-draft-publish" data-id="${escapeHtml(n.id)}">Publish</button>`);
      } else {
        actions.push(`<button type="button" class="btn secondary compact notice-draft-edit" data-id="${escapeHtml(n.id)}">View draft</button>`);
      }
      if (isOwner) {
        actions.push(`<button type="button" class="btn ghost compact notice-draft-share" data-id="${escapeHtml(n.id)}">Share</button>`);
        actions.push(`<button type="button" class="btn ghost compact notice-draft-delete" data-id="${escapeHtml(n.id)}">Delete</button>`);
      }
      return `
        <article class="notice-draft-card mobile-fold${canEdit ? '' : ' is-view-only'}" data-id="${escapeHtml(n.id)}">
          <button type="button" class="mobile-fold-head" aria-expanded="false">
            <span class="mobile-fold-head-main">
              <span class="notice-badges">${badges}</span>
              <span class="notice-draft-card-title">${escapeHtml(n.title || 'Untitled draft')}</span>
              <span class="meta">${escapeHtml(n.category || 'general')}${when ? ` · saved ${escapeHtml(when)}` : ''}</span>
            </span>
            <span class="mobile-fold-chevron" aria-hidden="true"></span>
          </button>
          <div class="mobile-fold-body">
            ${shareLine ? `<p class="draft-share-line">${escapeHtml(shareLine)}</p>` : ''}
            <p class="draft-excerpt">${escapeHtml(short)}</p>
            <div class="btn-row">${actions.join('')}</div>
          </div>
        </article>`;
    }).join('');
    refreshMobileListUi();
  }

  async function loadNoticeDrafts() {
    if (!hasEntitlement('manage_notices')) return;
    const data = await api('/api/rwa/notices?status=draft');
    draftsCache = data.notices || [];
    renderDraftList();
  }

  async function loadEcMembers() {
    if (ecMembersCache) return ecMembersCache;
    const data = await api('/api/rwa/ec-members');
    ecMembersCache = data.members || [];
    return ecMembersCache;
  }

  function closeDraftShareDialog() {
    const dialog = el('draftShareDialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  function syncShareRowState(row) {
    if (!row) return;
    const checked = row.querySelector('input[name="shareHouse"]')?.checked === true;
    const access = row.querySelector('select[name="shareAccess"]');
    row.classList.toggle('is-selected', checked);
    if (access) access.disabled = !checked;
  }

  async function openDraftShareDialog(notice) {
    if (!notice?.id) return;
    const dialog = el('draftShareDialog');
    const list = el('draftShareMemberList');
    const err = el('draftShareError');
    if (!dialog || !list) return;
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (el('draftShareNoticeId')) el('draftShareNoticeId').value = notice.id;
    if (el('draftShareSubtitle')) {
      el('draftShareSubtitle').textContent =
        `Share “${notice.title || 'Untitled draft'}” — set Edit or View per member (change anytime).`;
    }
    const shares = notice.sharedWith || [];
    const accessByHouse = new Map(shares.map((s) => [s.houseId, s.canEdit !== false]));
    list.innerHTML = '<p class="muted">Loading EC members…</p>';
    showDialog(dialog);
    try {
      const members = await loadEcMembers();
      if (!members.length) {
        list.innerHTML = '<p class="muted">No other EC members on the roster yet.</p>';
        return;
      }
      list.innerHTML = members.map((m) => {
        const selected = accessByHouse.has(m.houseId);
        const canEdit = selected ? accessByHouse.get(m.houseId) : true;
        return `
          <div class="draft-share-row${selected ? ' is-selected' : ''}" data-house="${escapeHtml(m.houseId)}">
            <input type="checkbox" name="shareHouse" value="${escapeHtml(m.houseId)}"${selected ? ' checked' : ''}>
            ${personAvatarHtml(m)}
            <span class="share-member-text">
              ${escapeHtml(m.label || m.name || m.houseId)}
              <span class="share-member-meta">${escapeHtml(m.houseId)}</span>
            </span>
            <select name="shareAccess" class="share-access"${selected ? '' : ' disabled'}>
              <option value="edit"${canEdit ? ' selected' : ''}>Edit</option>
              <option value="view"${canEdit ? '' : ' selected'}>View only</option>
            </select>
          </div>`;
      }).join('');
      await hydrateAvatars(list);
    } catch (e) {
      list.innerHTML = `<p class="error">${escapeHtml(e.message || 'Could not load members')}</p>`;
    }
  }

  async function saveDraftShares(event) {
    event.preventDefault();
    const noticeId = String(el('draftShareNoticeId')?.value || '').trim();
    const err = el('draftShareError');
    const saveBtn = el('draftShareSaveBtn');
    if (!noticeId) return;
    const shares = Array.from(document.querySelectorAll('#draftShareMemberList .draft-share-row'))
      .filter((row) => row.querySelector('input[name="shareHouse"]')?.checked)
      .map((row) => ({
        houseId: row.querySelector('input[name="shareHouse"]').value,
        canEdit: row.querySelector('select[name="shareAccess"]')?.value !== 'view',
      }));
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
    if (saveBtn) saveBtn.disabled = true;
    try {
      await api(`/api/rwa/notices/${encodeURIComponent(noticeId)}/shares`, {
        method: 'PUT',
        body: JSON.stringify({ shares }),
      });
      closeDraftShareDialog();
      await loadNoticeDrafts();
    } catch (e) {
      if (err) {
        err.hidden = false;
        err.textContent = e.message || 'Could not update sharing';
      } else {
        alert(e.message || 'Could not update sharing');
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function syncNoticeFormMode(notice) {
    const isDraft = (notice?.status || el('noticeEditStatus')?.value) === 'draft';
    const editing = Boolean(notice?.id || el('noticeEditId')?.value);
    const canEdit = notice ? notice.canEdit !== false : true;
    if (el('noticeEditStatus')) el('noticeEditStatus').value = notice?.status || (isDraft ? 'draft' : 'published');
    if (el('noticeFormTitle')) {
      el('noticeFormTitle').textContent = editing
        ? (isDraft ? (canEdit ? 'Edit draft' : 'View draft') : 'Update notice')
        : 'New notice';
    }
    if (el('noticeSubmitBtn')) {
      el('noticeSubmitBtn').textContent = isDraft || !editing ? 'Publish notice' : 'Save changes';
      el('noticeSubmitBtn').hidden = !canEdit;
    }
    if (el('noticeDraftBtn')) {
      el('noticeDraftBtn').textContent = isDraft || !editing ? 'Save draft' : 'Save as draft';
      el('noticeDraftBtn').hidden = isWelcomeNotice(notice) || !canEdit;
    }
    if (el('noticeCancelEditBtn')) el('noticeCancelEditBtn').hidden = !editing;
    if (el('noticeBodyInput')) el('noticeBodyInput').required = !isDraft;
    ['noticeTitleInput', 'noticeBodyInput', 'noticeCategoryInput', 'noticePinnedInput', 'noticePublicLandingInput', 'noticeShareCityInput'].forEach((id) => {
      const field = el(id);
      if (field) field.disabled = editing && !canEdit;
    });
  }

  function resetNoticeForm() {
    const form = el('noticeForm');
    if (!form) return;
    form.reset();
    if (el('noticeEditId')) el('noticeEditId').value = '';
    if (el('noticeEditStatus')) el('noticeEditStatus').value = 'published';
    if (el('noticePinnedInput')) el('noticePinnedInput').disabled = false;
    if (el('noticePublicLandingInput')) el('noticePublicLandingInput').checked = false;
    if (el('noticeShareCityInput')) {
      el('noticeShareCityInput').checked = false;
      el('noticeShareCityInput').disabled = false;
    }
    const pinLabel = el('noticePinnedInput')?.closest('label');
    if (pinLabel) pinLabel.title = '';
    if (el('noticeBodyInput')) el('noticeBodyInput').required = true;
    ['noticeTitleInput', 'noticeBodyInput', 'noticeCategoryInput', 'noticePinnedInput', 'noticePublicLandingInput', 'noticeShareCityInput'].forEach((id) => {
      const field = el(id);
      if (field) field.disabled = false;
    });
    syncNoticeFormMode(null);
    setAuthorFormLang('notice', 'en');
    if (el('noticeTitleHiInput')) el('noticeTitleHiInput').value = '';
    if (el('noticeBodyHiInput')) el('noticeBodyHiInput').value = '';
    if (el('noticeImageInput')) el('noticeImageInput').value = '';
    if (el('noticeImagePreview')) {
      el('noticeImagePreview').hidden = true;
      el('noticeImagePreview').removeAttribute('src');
    }
    if (el('noticeFormStatus')) el('noticeFormStatus').textContent = '';
  }

  function startNoticeEdit(notice) {
    if (!notice) return;
    switchPanel('admin');
    if (el('noticeEditId')) el('noticeEditId').value = notice.id || '';
    if (el('noticeEditStatus')) el('noticeEditStatus').value = notice.status || 'published';
    if (el('noticeTitleInput')) el('noticeTitleInput').value = notice.title || '';
    if (el('noticeBodyInput')) el('noticeBodyInput').value = notice.body || '';
    if (el('noticeTitleHiInput')) el('noticeTitleHiInput').value = notice.titleHi || '';
    if (el('noticeBodyHiInput')) el('noticeBodyHiInput').value = notice.bodyHi || '';
    if (el('noticeCategoryInput')) el('noticeCategoryInput').value = notice.category || 'general';
    setAuthorFormLang('notice', 'en');
    if (el('noticePinnedInput')) {
      el('noticePinnedInput').checked = Boolean(notice.pinned);
      el('noticePinnedInput').disabled = isWelcomeNotice(notice) || notice.status === 'draft' || notice.canEdit === false;
    }
    if (el('noticePublicLandingInput')) {
      el('noticePublicLandingInput').checked = (notice.audience || 'members') === 'public';
      el('noticePublicLandingInput').disabled = notice.canEdit === false;
    }
    if (el('noticeShareCityInput')) {
      el('noticeShareCityInput').checked = false;
      el('noticeShareCityInput').disabled = notice.canEdit === false;
    }
    const preview = el('noticeImagePreview');
    if (preview) {
      if (notice.imageUrl) {
        preview.src = `${notice.imageUrl}?v=${encodeURIComponent(notice.publishedAt || '')}`;
        preview.hidden = false;
      } else {
        preview.hidden = true;
        preview.removeAttribute('src');
      }
    }
    if (el('noticeImageInput')) el('noticeImageInput').value = '';
    const pinLabel = el('noticePinnedInput')?.closest('label');
    if (pinLabel) {
      pinLabel.title = isWelcomeNotice(notice)
        ? 'Welcome notice stays fixed at the top of the board'
        : (notice.status === 'draft' ? 'Pin applies when you publish' : '');
    }
    syncNoticeFormMode(notice);
    if (el('noticeFormStatus')) {
      if (notice.status === 'draft' && notice.canEdit === false) {
        el('noticeFormStatus').textContent = 'View only — ask the owner for edit access.';
      } else if (notice.status === 'draft') {
        el('noticeFormStatus').textContent = notice.sharedWithMe
          ? `Editing shared draft ${notice.id}`
          : `Editing draft ${notice.id}`;
      } else {
        el('noticeFormStatus').textContent = `Editing ${notice.id}`;
      }
    }
    el('noticeForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function shareToCityHub({ type, id } = {}) {
    if (!type || !id) return { ok: false };
    return api('/api/rwa/city-hub/share', {
      method: 'POST',
      body: JSON.stringify({ type, id }),
    });
  }

  async function saveNotice({ asDraft = false } = {}) {
    const form = el('noticeForm');
    if (!form) return;
    const noticeId = String(el('noticeEditId')?.value || '').trim();
    const title = String(el('noticeTitleInput')?.value || '').trim();
    const body = String(el('noticeBodyInput')?.value || '').trim();
    const titleHi = String(el('noticeTitleHiInput')?.value || '').trim();
    const bodyHi = String(el('noticeBodyHiInput')?.value || '').trim();
    const statusLine = el('noticeFormStatus');
    const publishBtn = el('noticeSubmitBtn');
    const draftBtn = el('noticeDraftBtn');

    if (asDraft) {
      if (!title) {
        if (statusLine) statusLine.textContent = 'Add a title to save a draft.';
        setAuthorFormLang('notice', 'en');
        el('noticeTitleInput')?.focus();
        return;
      }
    } else if (!form.reportValidity()) {
      setAuthorFormLang('notice', 'en');
      return;
    }

    if (publishBtn) publishBtn.disabled = true;
    if (draftBtn) draftBtn.disabled = true;
    if (statusLine) statusLine.textContent = asDraft ? 'Saving draft…' : (noticeId ? 'Saving…' : 'Publishing…');

    try {
      const payload = {
        title,
        body,
        titleHi,
        bodyHi,
        category: el('noticeCategoryInput')?.value || 'general',
        pinned: !asDraft && el('noticePinnedInput')?.checked === true,
        audience: el('noticePublicLandingInput')?.checked ? 'public' : 'members',
        status: asDraft ? 'draft' : 'published',
      };
      let savedId = noticeId;
      if (noticeId) {
        const out = await api(`/api/rwa/notices/${encodeURIComponent(noticeId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        savedId = out.notice?.id || noticeId;
      } else {
        const out = await api('/api/rwa/notices', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        savedId = out.notice?.id || '';
      }
      const imageInput = el('noticeImageInput');
      const imageFile = imageInput?.files?.[0];
      if (savedId && imageFile) {
        const fd = new FormData();
        fd.append('image', imageFile);
        await api(`/api/rwa/notices/${encodeURIComponent(savedId)}/image`, {
          method: 'POST',
          body: fd,
        });
      }
      const shareCity = !asDraft && el('noticeShareCityInput')?.checked === true;
      resetNoticeForm();
      await loadNoticeDrafts().catch(console.error);
      if (asDraft) {
        if (statusLine) statusLine.textContent = 'Draft saved. Continue anytime from the list above.';
        switchPanel('admin');
      } else {
        let cityNote = '';
        if (shareCity && savedId) {
          try {
            await shareToCityHub({ type: 'notice', id: savedId });
            cityNote = 'Shared to City of Mandi for review.';
          } catch (shareErr) {
            cityNote = `Colony notice is live. City of Mandi share failed: ${shareErr.message || 'try again later'}.`;
          }
        }
        await loadHome();
        switchPanel('home');
        if (statusLine && cityNote) statusLine.textContent = cityNote;
      }
    } catch (err) {
      if (statusLine) statusLine.textContent = err.message || (asDraft ? 'Draft save failed' : 'Publish failed');
      else alert(err.message || 'Save failed');
    } finally {
      if (publishBtn) publishBtn.disabled = false;
      if (draftBtn) draftBtn.disabled = false;
    }
  }

  async function loadDues() {
    const data = await api('/api/rwa/payments/me');
    const card = el('duesCard');
    const p = data.payment;
    if (card) {
      if (!p) {
        card.innerHTML = '<p class="muted">No ledger row for this plot yet.</p>';
      } else {
        const pending = Number(p.pendingDues ?? p.balanceOutstanding ?? 0);
        card.innerHTML = `
          <article class="dues-bill${pending <= 0 ? ' is-cleared' : ''}">
            <header class="dues-bill-head">
              <span>${pending <= 0 ? 'Dues' : 'Pending / dues'}</span>
              <strong>${inr(p.pendingDues ?? p.balanceOutstanding)}</strong>
            </header>
            <dl class="dues-bill-metrics">
              <div><dt>Previous total</dt><dd>${inr(p.previousTotal ?? p.balancePrev)}</dd></div>
              <div><dt>Previous paid</dt><dd>${inr(p.previousPaid ?? 0)}</dd></div>
              <div><dt>Previous pending</dt><dd>${inr(p.previousPending ?? p.balancePrev)}</dd></div>
              <div><dt>Year total</dt><dd>${inr(p.currentYearTotal ?? p.feeAmount)}</dd></div>
            </dl>
            <footer class="dues-bill-meta">
              <span>Treasury</span>
              ${treasuryStatusIcon(p)}
            </footer>
          </article>`;
      }
    }
    const bank = el('bankCard');
    if (bank) {
      renderPayCard(bank, data.summary?.bank, { showEdit: isEcAdmin(), hideTitle: true });
    }

    const houseWrap = el('paymentRecordHouseWrap');
    if (houseWrap) houseWrap.hidden = !hasEntitlement('manage_dues');
    const payForm = el('paymentRecordForm');
    if (payForm) payForm.hidden = isViewOnly() || isSuperAdmin();
    if (el('paymentRecordFeeYear') && !el('paymentRecordFeeYear').value) {
      el('paymentRecordFeeYear').value = String(new Date().getFullYear());
    }
    if (el('paymentRecordPaidOn') && !el('paymentRecordPaidOn').value) {
      el('paymentRecordPaidOn').value = todayIstDate();
    }
    syncPaymentRecordFormKind();
    if (hasEntitlement('manage_dues') || hasEntitlement('issue_no_dues') || hasEntitlement('issue_no_objection')) {
      populatePaymentHouseList().catch(() => {});
    }
    await loadPaymentRecords().catch((e) => {
      if (el('paymentRecordsStatus')) el('paymentRecordsStatus').textContent = e.message || 'Could not load payments';
    });
    await loadResidentNoDues().catch((e) => {
      if (el('noDuesResidentStatus')) el('noDuesResidentStatus').textContent = e.message || 'Could not load certificate status';
    });
    await loadResidentNoObjection().catch((e) => {
      if (el('noObjectionResidentStatus')) el('noObjectionResidentStatus').textContent = e.message || 'Could not load certificate status';
    });

    if (hasEntitlement('manage_dues')) {
      await loadLedger();
    }
  }

  async function populatePaymentHouseList() {
    const list = el('paymentRecordHouseList');
    if (!list) return;
    if (!rosterCache.length) {
      try {
        if (hasEntitlement('manage_roster') || hasEntitlement('sensitive_ops')) {
          const data = await api('/api/rwa/residents');
          rosterCache = data.residents || [];
        } else {
          const data = await api('/api/rwa/directory');
          rosterCache = (data.residents || data.directory || []).map((r) => ({
            houseId: r.houseId || r.plotNo || r.id,
            name: r.name || '',
          }));
        }
      } catch (_e) { /* ignore */ }
    }
    list.innerHTML = rosterCache.map((r) =>
      `<option value="${escapeHtml(r.houseId)}">${escapeHtml(r.houseId)} — ${escapeHtml(r.name || '')}</option>`
    ).join('');
  }

  const PAYMENT_CATEGORIES = [
    { value: 'annual_dues', label: 'Annual dues' },
    { value: 'special_levy', label: 'Special levy' },
    { value: 'other', label: 'Other payment' },
  ];
  const REIMBURSEMENT_CATEGORIES = [
    { value: 'colony_work', label: 'Colony work / labour' },
    { value: 'supplies', label: 'Supplies / materials' },
    { value: 'travel', label: 'Travel / logistics' },
    { value: 'event', label: 'Event / function' },
    { value: 'other_expense', label: 'Other expense' },
  ];

  function syncPaymentRecordFormKind() {
    const kind = el('paymentRecordKind')?.value || 'payment';
    const isClaim = kind === 'reimbursement';
    const cat = el('paymentRecordCategory');
    if (cat) {
      const opts = isClaim ? REIMBURSEMENT_CATEGORIES : PAYMENT_CATEGORIES;
      const prev = cat.value;
      cat.innerHTML = opts.map((o) =>
        `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`
      ).join('');
      if (opts.some((o) => o.value === prev)) cat.value = prev;
    }
    if (el('paymentRecordPaidOnText')) {
      el('paymentRecordPaidOnText').textContent = isClaim ? 'Spent on' : 'Paid on';
    }
    const feeWrap = el('paymentRecordFeeYearWrap');
    if (feeWrap) feeWrap.hidden = isClaim;
    const feeInput = el('paymentRecordFeeYear');
    if (feeInput) feeInput.required = !isClaim;
    const methodWrap = el('paymentRecordMethodWrap');
    if (methodWrap) methodWrap.hidden = false;
    const note = el('paymentRecordNote');
    if (note) {
      note.placeholder = isClaim
        ? 'What was purchased / work done'
        : 'Optional UPI ref or remark';
    }
    syncPaymentCashNoteUi();
    const btn = el('paymentRecordSubmitBtn');
    if (btn && !el('paymentRecordForm')?.dataset?.editId) {
      btn.textContent = isClaim ? 'Submit claim' : 'Upload payment';
    }
  }

  function syncPaymentCashNoteUi() {
    const method = el('paymentRecordMethod')?.value || 'upi';
    const kind = el('paymentRecordKind')?.value || 'payment';
    const isClaim = kind === 'reimbursement';
    const isCash = method === 'cash';
    const box = el('paymentCashNoteBox');
    if (box) box.hidden = !isCash;
    if (el('paymentCashNoteHint')) {
      el('paymentCashNoteHint').textContent = isClaim
        ? 'For cash expenses: generate a Cash Payment Voucher, upload it as proof, then EC verifies / reimburses.'
        : 'For cash dues: the recipient generates a Cash Received Note, uploads it as proof, then another EC member verifies.';
    }
    if (el('paymentCashNoteBtn')) {
      el('paymentCashNoteBtn').textContent = isClaim
        ? 'Generate Cash Payment Voucher (PDF)'
        : 'Generate Received Note (PDF)';
    }
    if (el('paymentRecordFilesText')) {
      if (isCash) {
        el('paymentRecordFilesText').textContent = isClaim
          ? 'Upload signed Cash Payment Voucher (JPG/PNG/PDF, max 3)'
          : 'Upload signed Cash Received Note (JPG/PNG/PDF, max 3)';
      } else {
        el('paymentRecordFilesText').textContent = isClaim
          ? 'Expense proof (JPG/PNG/WebP/PDF, max 3)'
          : 'Receipt files (JPG/PNG/WebP/PDF, max 3)';
      }
    }
    if (el('paymentCashReceiver') && !el('paymentCashReceiver').value) {
      el('paymentCashReceiver').value = state.session?.resident?.name || '';
    }
  }

  function paymentStatusBadge(status) {
    const s = status || 'submitted';
    const labels = {
      submitted: 'submitted',
      verified: 'verified',
      rejected: 'rejected',
      reimbursed: 'reimbursed',
    };
    return `<span class="payment-status is-${escapeHtml(s)}">${escapeHtml(labels[s] || s)}</span>`;
  }

  function treasuryStatusIcon(rec, { showLabel = true } = {}) {
    const st = (rec && (rec.treasuryStatus || rec.treasury_status)) || 'pending';
    const labels = {
      pending: 'Pending',
      validated: 'Validated',
      confirmed: 'Confirmed',
    };
    const label = (rec && rec.treasuryStatusLabel) || labels[st] || st;
    const title = escapeHtml(label);
    return `<span class="treasury-seal is-${escapeHtml(st)}" title="Treasury: ${title}" aria-label="Treasury: ${title}">
      <span class="treasury-seal-icon" aria-hidden="true"></span>
      ${showLabel ? `<span class="treasury-seal-label">${escapeHtml(label)}</span>` : ''}
    </span>`;
  }

  function promptRejectionReason(label = 'Reason for rejection (required):') {
    const note = (window.prompt(label) || '').trim();
    if (!note) {
      window.alert('A rejection reason is required.');
      return null;
    }
    return note.slice(0, 500);
  }

  function treasuryActionButtons(kind, id, status, { compact = true } = {}) {
    if (!hasEntitlement('treasury') || !id) return '';
    const st = status || 'pending';
    const cls = compact ? 'btn ghost compact' : 'btn secondary compact';
    const actions = [];
    if (st === 'pending') {
      actions.push(`<button type="button" class="${cls} treasury-validate" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(id)}">Validate</button>`);
    }
    if (st === 'validated') {
      actions.push(`<button type="button" class="btn secondary compact treasury-confirm" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(id)}">Confirm</button>`);
    }
    if (st === 'validated' || st === 'confirmed') {
      actions.push(`<button type="button" class="btn ghost compact treasury-revert" data-kind="${escapeHtml(kind)}" data-id="${escapeHtml(id)}">Revert Treasury</button>`);
    }
    return actions.join('');
  }

  async function runTreasuryAction(kind, id, action) {
    const paths = {
      payment: `/api/rwa/treasury/payments/${encodeURIComponent(id)}/${action}`,
      ledger: `/api/rwa/treasury/ledger/${encodeURIComponent(id)}/${action}`,
      no_dues: `/api/rwa/treasury/no-dues/${encodeURIComponent(id)}/${action}`,
      no_objection: `/api/rwa/treasury/no-objection/${encodeURIComponent(id)}/${action}`,
    };
    const url = paths[kind];
    if (!url) throw new Error('Unknown treasury kind');
    return api(url, { method: 'POST', body: JSON.stringify({}) });
  }

  async function handleTreasuryClick(event) {
    const btn = event.target.closest('.treasury-validate, .treasury-confirm, .treasury-revert');
    if (!btn) return false;
    const kind = btn.getAttribute('data-kind');
    const id = btn.getAttribute('data-id');
    const action = btn.classList.contains('treasury-validate')
      ? 'validate'
      : btn.classList.contains('treasury-confirm')
        ? 'confirm'
        : 'revert';
    if (action === 'revert' && !window.confirm('Revert Treasury status to pending?')) return true;
    btn.disabled = true;
    try {
      await runTreasuryAction(kind, id, action);
      if (hasEntitlement('treasury')) await loadEcTreasuryQueue().catch(() => {});
      if (hasEntitlement('manage_dues')) {
        await loadEcPaymentRecords().catch(() => {});
        await loadLedger().catch(() => {});
      }
      if (hasEntitlement('issue_no_dues')) await loadEcNoDuesRequests().catch(() => {});
      if (hasEntitlement('issue_no_objection')) await loadEcNoObjectionRequests().catch(() => {});
      await loadPaymentRecords().catch(() => {});
      await loadResidentNoDues().catch(() => {});
      await loadResidentNoObjection().catch(() => {});
      await loadDues().catch(() => {});
    } catch (err) {
      window.alert(err.message || 'Treasury action failed');
    } finally {
      btn.disabled = false;
    }
    return true;
  }

  function renderPaymentRecordCard(rec, { ecMode = false } = {}) {
    const isClaim = (rec.kind || 'payment') === 'reimbursement';
    const files = (rec.files || []).map((f) => {
      const label = escapeHtml(f.originalName || f.filename || 'Receipt');
      return `<button type="button" class="btn ghost compact doc-open" data-url="${escapeHtml(f.url)}" data-title="${label}" data-filename="${label}" data-mime="${escapeHtml(f.mime || '')}">${label}</button>`;
    }).join(' · ') || '<span class="muted">No files</span>';
    const canDelete = ecMode
      ? (rec.status !== 'reimbursed' && (rec.status !== 'verified' || !rec.ledgerApplied))
      : (rec.status === 'submitted' && !isViewOnly());
    const canEdit = !isViewOnly() && (rec.status === 'submitted' || rec.status === 'rejected')
      && (ecMode || true);
    const actions = [];
    if (ecMode && rec.status === 'submitted') {
      const approveLabel = isClaim ? 'Approve' : 'Verify';
      actions.push(`<button type="button" class="btn secondary compact pay-verify" data-id="${escapeHtml(rec.id)}">${approveLabel}</button>`);
      actions.push(`<button type="button" class="btn ghost compact pay-reject" data-id="${escapeHtml(rec.id)}">Reject</button>`);
    }
    if (ecMode && isClaim && rec.status === 'verified') {
      actions.push(`<button type="button" class="btn secondary compact pay-reimburse" data-id="${escapeHtml(rec.id)}">Mark reimbursed</button>`);
    }
    if (ecMode && (rec.status === 'verified' || rec.status === 'rejected' || rec.status === 'reimbursed')) {
      actions.push(`<button type="button" class="btn ghost compact pay-revert" data-id="${escapeHtml(rec.id)}">Revert</button>`);
    }
    if ((ecMode || hasEntitlement('treasury')) && (rec.status === 'verified' || rec.status === 'reimbursed')) {
      const tActs = treasuryActionButtons('payment', rec.id, rec.treasuryStatus);
      if (tActs) actions.push(tActs);
    }
    if (canEdit) {
      actions.push(`<button type="button" class="btn ghost compact pay-edit" data-id="${escapeHtml(rec.id)}">Edit / re-upload</button>`);
    }
    if (canDelete) {
      actions.push(`<button type="button" class="btn ghost compact pay-delete" data-id="${escapeHtml(rec.id)}">Delete</button>`);
    }
    const dateLabel = isClaim ? 'spent' : 'paid';
    const kindBit = isClaim ? ' · claim' : ' · payment';
    const cashBit = (rec.method || '') === 'cash' ? ' · cash note' : '';
    const showTreasury = rec.status === 'verified' || rec.status === 'reimbursed' || rec.treasuryStatus;
    return `
      <article class="payment-record-card" data-id="${escapeHtml(rec.id)}" data-kind="${escapeHtml(rec.kind || 'payment')}">
        <div class="payment-record-head">
          <strong>${escapeHtml(rec.kindLabel || rec.kind || 'Payment')} · ${escapeHtml(rec.categoryLabel || rec.category)} · ${inr(rec.amount)}</strong>
          ${paymentStatusBadge(rec.status)}
          ${showTreasury ? treasuryStatusIcon(rec) : ''}
        </div>
        <p class="muted">
          Plot <code>${escapeHtml(rec.plotNo || rec.houseId)}</code>
          ${rec.residentName ? ` · ${escapeHtml(rec.residentName)}` : ''}
          · ${dateLabel} ${escapeHtml(rec.paidOn || '')}
          · ${escapeHtml(rec.methodLabel || rec.method || '')}
          ${isClaim ? '' : ` · year ${escapeHtml(String(rec.feeYear || ''))}`}
          ${kindBit}${cashBit}
          ${rec.uploadedByRole === 'ec' ? ' · uploaded by EC' : ''}
          ${rec.reimbursedAt ? ` · reimbursed ${escapeHtml(formatIstDate(rec.reimbursedAt))}` : ''}
        </p>
        ${(rec.method || '') === 'cash' && rec.status === 'submitted'
          ? '<p class="muted">Cash proof uploaded — awaiting EC verification / approval.</p>'
          : ''}
        ${rec.note ? `<p>${escapeHtml(rec.note)}</p>` : ''}
        ${rec.reviewNote ? `<p class="muted">Review: ${escapeHtml(rec.reviewNote)}</p>` : ''}
        <div class="payment-files">${files}</div>
        ${actions.length ? `<div class="btn-row">${actions.join('')}</div>` : ''}
      </article>`;
  }

  function clearPaymentRecordEditMode() {
    const form = el('paymentRecordForm');
    if (form) delete form.dataset.editId;
    const files = el('paymentRecordFiles');
    if (files) files.required = true;
    if (el('paymentRecordFilesText')) {
      const isClaim = (el('paymentRecordKind')?.value || 'payment') === 'reimbursement';
      el('paymentRecordFilesText').textContent = isClaim
        ? 'Expense proof (JPG/PNG/WebP/PDF, max 3)'
        : 'Receipt files (JPG/PNG/WebP/PDF, max 3)';
    }
    syncPaymentRecordFormKind();
    const cancel = el('paymentRecordCancelEditBtn');
    if (cancel) cancel.hidden = true;
  }

  async function beginPaymentRecordEdit(recordId) {
    const data = await api('/api/rwa/payments/records');
    const rec = (data.records || []).find((r) => r.id === recordId)
      || (hasEntitlement('manage_dues')
        ? ((await api(`/api/rwa/payments/records?status=all&limit=200`)).records || []).find((r) => r.id === recordId)
        : null);
    if (!rec) throw new Error('Record not found');
    const form = el('paymentRecordForm');
    if (!form) return;
    form.dataset.editId = rec.id;
    if (el('paymentRecordHouse')) el('paymentRecordHouse').value = rec.houseId || '';
    if (el('paymentRecordKind')) el('paymentRecordKind').value = rec.kind || 'payment';
    syncPaymentRecordFormKind();
    if (el('paymentRecordAmount')) el('paymentRecordAmount').value = String(rec.amount || '');
    if (el('paymentRecordPaidOn')) el('paymentRecordPaidOn').value = rec.paidOn || '';
    if (el('paymentRecordFeeYear')) el('paymentRecordFeeYear').value = String(rec.feeYear || new Date().getFullYear());
    if (el('paymentRecordCategory')) el('paymentRecordCategory').value = rec.category || '';
    if (el('paymentRecordMethod')) el('paymentRecordMethod').value = rec.method || 'upi';
    if (el('paymentRecordTitle')) el('paymentRecordTitle').value = '';
    if (el('paymentRecordNote')) el('paymentRecordNote').value = rec.note || '';
    const files = el('paymentRecordFiles');
    if (files) {
      files.value = '';
      files.required = !(rec.files && rec.files.length);
    }
    if (el('paymentRecordFilesText')) {
      el('paymentRecordFilesText').textContent = (rec.files && rec.files.length)
        ? 'Replace receipts (optional — leave empty to keep existing)'
        : 'Receipt files required (JPG/PNG/WebP/PDF, max 3)';
    }
    const btn = el('paymentRecordSubmitBtn');
    if (btn) btn.textContent = 'Save changes';
    const cancel = el('paymentRecordCancelEditBtn');
    if (cancel) cancel.hidden = false;
    if (el('paymentRecordFormStatus')) {
      el('paymentRecordFormStatus').textContent = `Editing ${rec.kindLabel || rec.kind} for plot ${rec.plotNo || rec.houseId}.`;
    }
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function loadPaymentRecords() {
    const list = el('paymentRecordsList');
    if (!list) return;
    list.innerHTML = '<p class="muted">Loading…</p>';
    const data = await api('/api/rwa/payments/records');
    const rows = data.records || [];
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No payments or claims uploaded yet.</p>';
      return;
    }
    list.innerHTML = rows.map((r) => renderPaymentRecordCard(r, { ecMode: false })).join('');
  }

  async function loadEcPaymentRecords() {
    if (!hasEntitlement('manage_dues')) return;
    const list = el('ecPaymentList');
    if (!list) return;
    const status = el('ecPaymentStatusFilter')?.value || 'submitted';
    const kind = el('ecPaymentKindFilter')?.value || 'all';
    list.innerHTML = '<p class="muted">Loading…</p>';
    const qs = new URLSearchParams({ status, limit: '150' });
    if (kind && kind !== 'all') qs.set('kind', kind);
    const data = await api(`/api/rwa/payments/records?${qs.toString()}`);
    const rows = data.records || [];
    if (el('ecPaymentStats')) {
      const submitted = rows.filter((r) => r.status === 'submitted').length;
      el('ecPaymentStats').textContent = status === 'submitted'
        ? `${rows.length} awaiting review`
        : `${rows.length} item(s) · filter: ${status}`;
      if (status === 'all') el('ecPaymentStats').textContent = `${rows.length} item(s)${submitted ? ` · ${submitted} submitted` : ''}`;
    }
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No items match this filter.</p>';
      return;
    }
    list.innerHTML = rows.map((r) => renderPaymentRecordCard(r, { ecMode: true })).join('');
  }

  async function downloadNoDuesRequest(requestId, variant = 'digital') {
    if (!requestId) throw new Error('Request required');
    const v = variant === 'print' ? 'print' : 'digital';
    const label = v === 'print' ? 'No Dues certificate (paper print)' : 'No Dues certificate (digital)';
    const suffix = v === 'print' ? '-print' : '';
    await openDocViewerFromAuthUrl(
      `/api/rwa/payments/no-dues-requests/${encodeURIComponent(requestId)}/download?variant=${encodeURIComponent(v)}`,
      {
        title: label,
        filename: `no-dues-${requestId}${suffix}.pdf`,
        mime: 'application/pdf',
      },
    );
  }

  let pendingNoDuesDownloadId = '';

  function openNoDuesDownloadChooser(requestId) {
    pendingNoDuesDownloadId = requestId || '';
    const dialog = el('noDuesDownloadDialog');
    if (!dialog || !pendingNoDuesDownloadId) {
      return downloadNoDuesRequest(requestId, 'digital');
    }
    if (!dialog.open) dialog.showModal();
    return Promise.resolve();
  }

  function renderNoDuesRequestCard(item, { issuer = false } = {}) {
    const actions = [];
    if (issuer && item.status === 'requested') {
      actions.push(`<button type="button" class="btn secondary compact nd-issue" data-id="${escapeHtml(item.id)}">Issue</button>`);
      actions.push(`<button type="button" class="btn ghost compact nd-reject" data-id="${escapeHtml(item.id)}">Reject</button>`);
      actions.push(`<button type="button" class="btn ghost compact nd-cancel" data-id="${escapeHtml(item.id)}">Cancel</button>`);
    }
    if (!issuer && item.status === 'requested') {
      actions.push(`<button type="button" class="btn ghost compact nd-cancel" data-id="${escapeHtml(item.id)}">Cancel request</button>`);
    }
    if (issuer && (item.status === 'issued' || item.status === 'rejected')) {
      actions.push(`<button type="button" class="btn ghost compact nd-revert" data-id="${escapeHtml(item.id)}">Revert to pending</button>`);
    }
    if (item.status === 'issued') {
      const tActs = treasuryActionButtons('no_dues', item.id, item.treasuryStatus);
      if (tActs) actions.push(tActs);
    }
    if (item.status === 'issued' && item.downloadUrl) {
      actions.push(`<button type="button" class="btn secondary compact nd-download" data-id="${escapeHtml(item.id)}">Download</button>`);
    } else if (item.status === 'issued' && item.downloadLocked) {
      actions.push('<span class="muted">Download locked until Treasury confirms</span>');
    }
    return `
      <article class="payment-record-card" data-id="${escapeHtml(item.id)}">
        <div class="payment-record-head">
          <strong>Plot <code>${escapeHtml(item.plotNo || item.houseId)}</code>${item.residentName ? ` · ${escapeHtml(item.residentName)}` : ''}</strong>
          <span class="payment-status is-${escapeHtml(item.status || '')}">${escapeHtml(item.statusLabel || item.status)}</span>
          ${item.status === 'issued' ? treasuryStatusIcon(item) : ''}
        </div>
        <p class="muted">Requested ${escapeHtml(formatIstDate(item.createdAt) || '—')}${item.issuedAt ? ` · issued ${escapeHtml(formatIstDate(item.issuedAt))}` : ''}</p>
        ${item.purpose ? `<p><strong>Purpose:</strong> ${escapeHtml(item.purpose)}${item.sentBack ? ' <span class="muted">(sent back — editable)</span>' : ''}</p>` : ''}
        ${item.requestNote ? `<p>${escapeHtml(item.requestNote)}</p>` : ''}
        ${item.reviewNote ? `<p class="muted">Note: ${escapeHtml(item.reviewNote)}</p>` : ''}
        ${actions.length ? `<div class="btn-row">${actions.join('')}</div>` : ''}
      </article>`;
  }

  async function loadResidentNoDues() {
    const block = el('noDuesResidentBlock');
    if (!block) return;
    if (isSuperAdmin() || isViewOnly()) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const own = state.session?.resident?.houseId || '';
    const qs = own ? `?houseId=${encodeURIComponent(own)}` : '';
    const data = await api(`/api/rwa/payments/no-dues-requests${qs}`);
    const rows = data.requests || [];
    const elig = data.eligibility || {};
    const pending = rows.find((r) => r.status === 'requested');
    const latestIssued = rows.find((r) => r.status === 'issued');
    const reqBtn = el('noDuesRequestBtn');
    const dlBtn = el('noDuesDownloadBtn');
    const status = el('noDuesResidentStatus');
    const purposeInput = el('noDuesPurpose');
    const purposeWrap = el('noDuesPurposeWrap');
    const purposeSave = el('noDuesPurposeSaveBtn');
    const purposeLockedHint = el('noDuesPurposeLockedHint');
    const canEditSentBack = Boolean(pending?.canEditPurpose) && !isViewOnly();
    const canNewRequest = Boolean(elig.eligible) && !pending && !isViewOnly();
    if (purposeWrap) {
      // Show for new request, locked pending (read-only), or sent-back edit.
      purposeWrap.hidden = isViewOnly() || (!canNewRequest && !pending);
    }
    if (purposeInput) {
      if (pending) {
        purposeInput.value = pending.purpose || elig.defaultPurpose || 'Official / banking / transfer purposes';
        purposeInput.readOnly = !canEditSentBack;
        purposeInput.dataset.touched = canEditSentBack ? (purposeInput.dataset.touched || '') : '';
      } else {
        purposeInput.readOnly = false;
        if (!purposeInput.dataset.touched) {
          purposeInput.value = elig.defaultPurpose || 'Official / banking / transfer purposes';
        }
      }
    }
    if (purposeSave) {
      purposeSave.hidden = !canEditSentBack;
      purposeSave.dataset.requestId = canEditSentBack ? (pending.id || '') : '';
    }
    if (purposeLockedHint) {
      purposeLockedHint.hidden = !(pending && !canEditSentBack);
    }
    if (reqBtn) {
      reqBtn.hidden = !canNewRequest;
      reqBtn.dataset.requestId = '';
    }
    if (dlBtn) {
      const canDl = latestIssued && latestIssued.downloadUrl && !latestIssued.downloadLocked;
      dlBtn.hidden = !canDl;
      dlBtn.dataset.requestId = canDl ? (latestIssued.id || '') : '';
    }
    if (status) {
      if (pending?.sentBack) status.textContent = 'Request sent back — update the purpose if needed, then wait for re-issue.';
      else if (pending) status.textContent = 'Request submitted — waiting for a No Dues Issuer to approve. Purpose is locked.';
      else if (latestIssued && latestIssued.downloadLocked) {
        status.textContent = `Certificate issued — awaiting Treasury ${latestIssued.treasuryStatus === 'validated' ? 'confirmation' : 'validation'} before download.`;
      } else if (latestIssued) status.textContent = 'Certificate issued and Treasury-confirmed — you can download it below.';
      else if (elig.eligible) status.textContent = 'Your ledger is clear. You can request a No Dues Certificate.';
      else status.textContent = elig.reason || 'Not eligible yet.';
    }
    const list = el('noDuesResidentList');
    if (list) {
      list.innerHTML = rows.length
        ? rows.map((r) => renderNoDuesRequestCard(r)).join('')
        : '<p class="muted">No certificate requests yet.</p>';
    }
  }

  async function loadEcNoDuesRequests() {
    if (!hasEntitlement('issue_no_dues')) return;
    const list = el('ecNoDuesList');
    if (!list) return;
    const statusFilter = el('ecNoDuesStatusFilter')?.value || 'requested';
    list.innerHTML = '<p class="muted">Loading…</p>';
    const qs = new URLSearchParams({ status: statusFilter, limit: '150' });
    const data = await api(`/api/rwa/payments/no-dues-requests?${qs.toString()}`);
    const rows = data.requests || [];
    if (el('ecNoDuesStats')) {
      el('ecNoDuesStats').textContent = statusFilter === 'requested'
        ? `${rows.length} awaiting issue`
        : `${rows.length} request(s) · filter: ${statusFilter}`;
    }
    list.innerHTML = rows.length
      ? rows.map((r) => renderNoDuesRequestCard(r, { issuer: true })).join('')
      : '<p class="muted">No requests match this filter.</p>';
  }

  async function issueNoDuesForHouse(houseId) {
    const data = await api('/api/rwa/payments/no-dues-certificate', {
      method: 'POST',
      body: JSON.stringify({ houseId }),
    });
    return data.request;
  }

  el('paymentRecordCancelEditBtn')?.addEventListener('click', () => {
    clearPaymentRecordEditMode();
    el('paymentRecordForm')?.reset();
    syncPaymentRecordFormKind();
    if (el('paymentRecordFeeYear')) el('paymentRecordFeeYear').value = String(new Date().getFullYear());
    if (el('paymentRecordPaidOn')) el('paymentRecordPaidOn').value = todayIstDate();
    if (el('paymentRecordFormStatus')) el('paymentRecordFormStatus').textContent = '';
  });

  el('paymentRecordForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isViewOnly()) return;
    const status = el('paymentRecordFormStatus');
    const btn = el('paymentRecordSubmitBtn');
    const editId = el('paymentRecordForm')?.dataset?.editId || '';
    const docTitle = (el('paymentRecordTitle')?.value || '').trim();
    if (!docTitle) {
      if (status) status.textContent = 'Add a document title (like a cash note).';
      return;
    }
    if (status) status.textContent = editId ? 'Saving…' : 'Uploading…';
    if (btn) btn.disabled = true;
    try {
      const fd = new FormData();
      const house = (el('paymentRecordHouse')?.value || '').trim()
        || (state.session?.resident?.houseId || '');
      if (!editId) fd.append('houseId', house);
      fd.append('kind', el('paymentRecordKind')?.value || 'payment');
      fd.append('amount', el('paymentRecordAmount')?.value || '');
      fd.append('paidOn', el('paymentRecordPaidOn')?.value || '');
      fd.append('feeYear', el('paymentRecordFeeYear')?.value || String(new Date().getFullYear()));
      fd.append('category', el('paymentRecordCategory')?.value || 'annual_dues');
      fd.append('method', el('paymentRecordMethod')?.value || 'upi');
      fd.append('note', el('paymentRecordNote')?.value || '');
      fd.append('docTitle', docTitle);
      fd.append('docDescription', el('paymentRecordNote')?.value || '');
      const files = el('paymentRecordFiles')?.files || [];
      Array.from(files).slice(0, 3).forEach((f) => fd.append('files', f));
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const url = editId
        ? `/api/rwa/payments/records/${encodeURIComponent(editId)}`
        : '/api/rwa/payments/records';
      const res = await fetch(url, {
        method: editId ? 'PATCH' : 'POST',
        credentials: 'same-origin',
        headers,
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText || (editId ? 'Save failed' : 'Upload failed'));
      const submittedKind = el('paymentRecordKind')?.value || 'payment';
      el('paymentRecordForm')?.reset();
      clearPaymentRecordEditMode();
      if (el('paymentRecordKind')) el('paymentRecordKind').value = submittedKind;
      syncPaymentRecordFormKind();
      if (el('paymentRecordFeeYear')) el('paymentRecordFeeYear').value = String(new Date().getFullYear());
      if (el('paymentRecordPaidOn')) el('paymentRecordPaidOn').value = todayIstDate();
      if (status) {
        status.textContent = editId
          ? 'Saved — awaiting EC review.'
          : (submittedKind === 'reimbursement'
            ? 'Claim submitted — awaiting EC approval.'
            : 'Payment uploaded — awaiting EC verification.');
      }
      await loadPaymentRecords();
      if (hasEntitlement('manage_dues')) await loadEcPaymentRecords().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Upload failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  async function handlePaymentListClick(event, { refreshEc = false } = {}) {
    if (await handleTreasuryClick(event)) return;
    const verify = event.target.closest('.pay-verify');
    const reject = event.target.closest('.pay-reject');
    const reimburse = event.target.closest('.pay-reimburse');
    const revert = event.target.closest('.pay-revert');
    const edit = event.target.closest('.pay-edit');
    const del = event.target.closest('.pay-delete');
    const id = (verify || reject || reimburse || revert || edit || del)?.getAttribute('data-id');
    if (!id) return;
    try {
      if (edit) {
        await beginPaymentRecordEdit(id);
        return;
      }
      if (verify) {
        const note = window.prompt('Optional review note:') || '';
        await api(`/api/rwa/payments/records/${encodeURIComponent(id)}/verify`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (reject) {
        const note = promptRejectionReason();
        if (!note) return;
        await api(`/api/rwa/payments/records/${encodeURIComponent(id)}/reject`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (reimburse) {
        const note = window.prompt('Optional payout note (UPI ref, etc.):') || '';
        await api(`/api/rwa/payments/records/${encodeURIComponent(id)}/reimburse`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (revert) {
        if (!window.confirm('Revert this item so it can be edited / reviewed again?')) return;
        const note = window.prompt('Optional revert note:') || '';
        await api(`/api/rwa/payments/records/${encodeURIComponent(id)}/revert`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (del) {
        if (!window.confirm('Delete this item?')) return;
        await api(`/api/rwa/payments/records/${encodeURIComponent(id)}`, { method: 'DELETE' });
      }
      await loadPaymentRecords().catch(() => {});
      if (refreshEc) await loadEcPaymentRecords().catch(() => {});
      if (verify || revert) await loadDues().catch(() => {});
    } catch (err) {
      window.alert(err.message || 'Action failed');
    }
  }

  el('paymentRecordKind')?.addEventListener('change', () => syncPaymentRecordFormKind());
  el('paymentRecordMethod')?.addEventListener('change', () => syncPaymentCashNoteUi());
  el('paymentCashNoteBtn')?.addEventListener('click', async () => {
    const status = el('paymentRecordFormStatus');
    const amount = el('paymentRecordAmount')?.value || '';
    const paidOn = el('paymentRecordPaidOn')?.value || '';
    const receiver = (el('paymentCashReceiver')?.value || '').trim();
    if (!amount || !paidOn) {
      if (status) status.textContent = 'Enter amount and date before generating the note.';
      return;
    }
    if (!receiver) {
      if (status) status.textContent = 'Enter who received the cash.';
      return;
    }
    const kind = el('paymentRecordKind')?.value || 'payment';
    if (kind === 'payment' && !hasEntitlement('manage_dues')) {
      if (status) status.textContent = 'Cash Received Notes for dues must be generated by the EC member who received the cash.';
      return;
    }
    if (status) status.textContent = 'Generating PDF…';
    try {
      const headers = { 'Content-Type': 'application/json' };
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const house = (el('paymentRecordHouse')?.value || '').trim()
        || (state.session?.resident?.houseId || '');
      const res = await fetch('/api/rwa/payments/cash-received-note', {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        body: JSON.stringify({
          kind,
          houseId: house,
          amount,
          paidOn,
          category: el('paymentRecordCategory')?.value || '',
          note: el('paymentRecordNote')?.value || '',
          receiverName: receiver,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || res.statusText || 'Could not generate note');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = kind === 'reimbursement' ? 'cash-payment-voucher.pdf' : 'cash-received-note.pdf';
      a.click();
      URL.revokeObjectURL(url);
      if (status) {
        status.textContent = 'PDF downloaded — sign if needed, then upload it below as proof for EC verification.';
      }
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not generate note';
    }
  });
  el('paymentRecordsList')?.addEventListener('click', (event) => {
    handlePaymentListClick(event, { refreshEc: hasEntitlement('manage_dues') }).catch(console.error);
  });
  el('ecPaymentList')?.addEventListener('click', (event) => {
    handlePaymentListClick(event, { refreshEc: true }).catch(console.error);
  });
  el('ecPaymentRefreshBtn')?.addEventListener('click', () => loadEcPaymentRecords().catch(console.error));
  el('ecPaymentStatusFilter')?.addEventListener('change', () => loadEcPaymentRecords().catch(console.error));
  el('ecPaymentKindFilter')?.addEventListener('change', () => loadEcPaymentRecords().catch(console.error));

  el('noDuesPurpose')?.addEventListener('input', () => {
    if (el('noDuesPurpose') && !el('noDuesPurpose').readOnly) el('noDuesPurpose').dataset.touched = '1';
  });

  el('noDuesPurposeSaveBtn')?.addEventListener('click', async () => {
    const id = el('noDuesPurposeSaveBtn')?.dataset?.requestId;
    const status = el('noDuesResidentStatus');
    const btn = el('noDuesPurposeSaveBtn');
    if (!id) return;
    if (btn) btn.disabled = true;
    try {
      await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/purpose`, {
        method: 'POST',
        body: JSON.stringify({ purpose: (el('noDuesPurpose')?.value || '').trim() }),
      });
      if (status) status.textContent = 'Purpose updated.';
      await loadResidentNoDues();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save purpose';
      window.alert(err.message || 'Could not save purpose');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noDuesRequestBtn')?.addEventListener('click', async () => {
    const status = el('noDuesResidentStatus');
    const btn = el('noDuesRequestBtn');
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Submitting request…';
    try {
      const purpose = (el('noDuesPurpose')?.value || '').trim();
      await api('/api/rwa/payments/no-dues-requests', {
        method: 'POST',
        body: JSON.stringify({ purpose }),
      });
      if (el('noDuesPurpose')) el('noDuesPurpose').dataset.touched = '';
      await loadResidentNoDues();
    } catch (err) {
      if (status) status.textContent = err.message || 'Request failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noDuesDownloadBtn')?.addEventListener('click', async () => {
    const id = el('noDuesDownloadBtn')?.dataset?.requestId;
    const status = el('noDuesResidentStatus');
    try {
      await openNoDuesDownloadChooser(id);
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
    }
  });

  el('noDuesDownloadCancelBtn')?.addEventListener('click', () => {
    el('noDuesDownloadDialog')?.close();
    pendingNoDuesDownloadId = '';
  });
  el('noDuesDlDigitalBtn')?.addEventListener('click', async () => {
    const id = pendingNoDuesDownloadId;
    el('noDuesDownloadDialog')?.close();
    const status = el('noDuesResidentStatus');
    try {
      await downloadNoDuesRequest(id, 'digital');
      if (status) status.textContent = 'Digital certificate opened — use Close to return, or Download to save.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
      window.alert(err.message || 'Download failed');
    } finally {
      pendingNoDuesDownloadId = '';
    }
  });
  el('noDuesDlPrintBtn')?.addEventListener('click', async () => {
    const id = pendingNoDuesDownloadId;
    el('noDuesDownloadDialog')?.close();
    const status = el('noDuesResidentStatus');
    try {
      await downloadNoDuesRequest(id, 'print');
      if (status) status.textContent = 'Print version opened — print on RWA letterhead paper.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
      window.alert(err.message || 'Download failed');
    } finally {
      pendingNoDuesDownloadId = '';
    }
  });

  el('noDuesResidentList')?.addEventListener('click', async (event) => {
    if (await handleTreasuryClick(event)) return;
    const dl = event.target.closest('.nd-download');
    const cancel = event.target.closest('.nd-cancel');
    const id = (dl || cancel)?.getAttribute('data-id');
    if (!id) return;
    try {
      if (cancel) {
        if (!window.confirm('Cancel this certificate request?')) return;
        await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/cancel`, {
          method: 'POST',
          body: '{}',
        });
        await loadResidentNoDues();
        return;
      }
      await openNoDuesDownloadChooser(id);
    } catch (err) {
      window.alert(err.message || 'Action failed');
    }
  });

  async function loadEcTreasuryQueue() {
    if (!hasEntitlement('treasury')) return;
    const list = el('ecTreasuryList');
    if (!list) return;
    const kind = el('ecTreasuryKindFilter')?.value || 'all';
    const status = el('ecTreasuryStatusFilter')?.value || 'attention';
    list.innerHTML = '<p class="muted">Loading…</p>';
    if (el('ecTreasuryStatus')) el('ecTreasuryStatus').textContent = '';
    try {
      const qs = new URLSearchParams({ kind, status, limit: '120' });
      const data = await api(`/api/rwa/treasury/queue?${qs.toString()}`);
      const payments = data.payments || [];
      const ledger = data.ledger || [];
      const noDues = data.noDues || [];
      const noObjection = data.noObjection || [];
      const n = payments.length + ledger.length + noDues.length + noObjection.length;
      if (el('ecTreasuryStats')) {
        el('ecTreasuryStats').textContent =
          `${n} item${n === 1 ? '' : 's'} · validate then confirm · ledger amounts may already show after EC verify`;
      }
      if (!n) {
        list.innerHTML = '<p class="muted">Nothing in this Treasury queue.</p>';
        return;
      }
      const parts = [];
      if (payments.length) {
        parts.push(`<div class="treasury-queue-section"><h4>Payments &amp; claims (${payments.length})</h4>
          ${payments.map((r) => renderPaymentRecordCard(r, { ecMode: true })).join('')}</div>`);
      }
      if (ledger.length) {
        parts.push(`<div class="treasury-queue-section"><h4>Ledger rows (${ledger.length})</h4>
          ${ledger.map((r) => `
            <article class="payment-record-card" data-house="${escapeHtml(r.houseId)}">
              <div class="payment-record-head">
                <strong>Plot <code>${escapeHtml(r.plotNo || r.houseId)}</code>${r.name ? ` · ${escapeHtml(r.name)}` : ''}</strong>
                ${treasuryStatusIcon(r)}
              </div>
              <p class="muted">Pending / dues ${inr(r.pendingDues ?? r.balanceOutstanding)} · received ${inr(r.amountReceived)}</p>
              <div class="btn-row">${treasuryActionButtons('ledger', r.houseId, r.treasuryStatus)}</div>
            </article>`).join('')}</div>`);
      }
      if (noDues.length) {
        parts.push(`<div class="treasury-queue-section"><h4>No Dues (${noDues.length})</h4>
          ${noDues.map((r) => renderNoDuesRequestCard(r, { issuer: false })).join('')}</div>`);
      }
      if (noObjection.length) {
        parts.push(`<div class="treasury-queue-section"><h4>No Objection (${noObjection.length})</h4>
          ${noObjection.map((r) => renderNoObjectionRequestCard(r, { issuer: false })).join('')}</div>`);
      }
      list.innerHTML = parts.join('');
    } catch (err) {
      list.innerHTML = '';
      if (el('ecTreasuryStatus')) el('ecTreasuryStatus').textContent = err.message || 'Treasury queue failed';
    }
  }

  el('ecTreasuryRefreshBtn')?.addEventListener('click', () => loadEcTreasuryQueue().catch(console.error));
  el('ecTreasuryKindFilter')?.addEventListener('change', () => loadEcTreasuryQueue().catch(console.error));
  el('ecTreasuryStatusFilter')?.addEventListener('change', () => loadEcTreasuryQueue().catch(console.error));
  el('ecTreasuryList')?.addEventListener('click', (event) => {
    const ndDl = event.target.closest('.nd-download');
    if (ndDl) {
      openNoDuesDownloadChooser(ndDl.getAttribute('data-id')).catch((err) => {
        window.alert(err.message || 'Download failed');
      });
      return;
    }
    const nocDl = event.target.closest('.noc-download');
    if (nocDl) {
      openNoObjectionDownloadChooser(nocDl.getAttribute('data-id')).catch((err) => {
        window.alert(err.message || 'Download failed');
      });
      return;
    }
    handleTreasuryClick(event).catch(console.error);
  });

  el('ecNoDuesList')?.addEventListener('click', async (event) => {
    if (await handleTreasuryClick(event)) return;
    const issue = event.target.closest('.nd-issue');
    const reject = event.target.closest('.nd-reject');
    const revert = event.target.closest('.nd-revert');
    const cancel = event.target.closest('.nd-cancel');
    const dl = event.target.closest('.nd-download');
    const id = (issue || reject || revert || cancel || dl)?.getAttribute('data-id');
    if (!id) return;
    try {
      if (issue) {
        await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/issue`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      } else if (reject) {
        const note = promptRejectionReason();
        if (!note) return;
        await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/reject`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (revert) {
        if (!window.confirm('Revert this request to pending? The issued PDF (if any) will be removed.')) return;
        const note = window.prompt('Optional revert note:') || '';
        await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/revert`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (cancel) {
        if (!window.confirm('Cancel this pending request?')) return;
        await api(`/api/rwa/payments/no-dues-requests/${encodeURIComponent(id)}/cancel`, {
          method: 'POST',
          body: '{}',
        });
      } else if (dl) {
        await openNoDuesDownloadChooser(id);
        return;
      }
      await loadEcNoDuesRequests().catch(() => {});
      await loadResidentNoDues().catch(() => {});
    } catch (err) {
      window.alert(err.message || 'Action failed');
    }
  });

  el('ecNoDuesRefreshBtn')?.addEventListener('click', () => loadEcNoDuesRequests().catch(console.error));
  el('ecNoDuesStatusFilter')?.addEventListener('change', () => loadEcNoDuesRequests().catch(console.error));

  el('ecNoDuesCertBtn')?.addEventListener('click', async () => {
    if (!hasEntitlement('issue_no_dues')) {
      window.alert('No Dues Issuer entitlement required');
      return;
    }
    const house = (el('ecNoDuesHouse')?.value || '').trim();
    const status = el('ecNoDuesCertStatus');
    if (!house) {
      if (status) status.textContent = 'Enter a plot number.';
      return;
    }
    const btn = el('ecNoDuesCertBtn');
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Issuing…';
    try {
      await issueNoDuesForHouse(house);
      if (status) status.textContent = `Certificate issued for plot ${house}. Use Download on the request card when needed.`;
      await loadEcNoDuesRequests().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  async function downloadNoObjectionRequest(requestId, variant = 'digital') {
    if (!requestId) throw new Error('Request required');
    const v = variant === 'print' ? 'print' : 'digital';
    const label = v === 'print' ? 'No Objection certificate (paper print)' : 'No Objection certificate (digital)';
    const suffix = v === 'print' ? '-print' : '';
    await openDocViewerFromAuthUrl(
      `/api/rwa/no-objection-requests/${encodeURIComponent(requestId)}/download?variant=${encodeURIComponent(v)}`,
      {
        title: label,
        filename: `no-objection-${requestId}${suffix}.pdf`,
        mime: 'application/pdf',
      },
    );
  }

  let pendingNoObjectionDownloadId = '';

  function openNoObjectionDownloadChooser(requestId) {
    pendingNoObjectionDownloadId = requestId || '';
    const dialog = el('noObjectionDownloadDialog');
    if (!dialog || !pendingNoObjectionDownloadId) {
      return downloadNoObjectionRequest(requestId, 'digital');
    }
    if (!dialog.open) dialog.showModal();
    return Promise.resolve();
  }

  function renderNoObjectionRequestCard(item, { issuer = false } = {}) {
    const actions = [];
    if (issuer && item.status === 'requested') {
      actions.push(`<button type="button" class="btn secondary compact noc-issue" data-id="${escapeHtml(item.id)}">Issue</button>`);
      actions.push(`<button type="button" class="btn ghost compact noc-reject" data-id="${escapeHtml(item.id)}">Reject</button>`);
      actions.push(`<button type="button" class="btn ghost compact noc-cancel" data-id="${escapeHtml(item.id)}">Cancel</button>`);
    }
    if (!issuer && item.status === 'requested') {
      actions.push(`<button type="button" class="btn ghost compact noc-cancel" data-id="${escapeHtml(item.id)}">Cancel request</button>`);
    }
    if (issuer && (item.status === 'issued' || item.status === 'rejected')) {
      actions.push(`<button type="button" class="btn ghost compact noc-revert" data-id="${escapeHtml(item.id)}">Revert to pending</button>`);
    }
    if (item.status === 'issued') {
      const tActs = treasuryActionButtons('no_objection', item.id, item.treasuryStatus);
      if (tActs) actions.push(tActs);
    }
    if (item.status === 'issued' && item.downloadUrl) {
      actions.push(`<button type="button" class="btn secondary compact noc-download" data-id="${escapeHtml(item.id)}">Download</button>`);
    } else if (item.status === 'issued' && item.downloadLocked) {
      actions.push('<span class="muted">Download locked until Treasury confirms</span>');
    }
    const pf = item.plotFinance || null;
    let plotFinanceHtml = '';
    if (issuer && pf) {
      const ledgerFake = {
        treasuryStatus: pf.ledgerTreasuryStatus || 'pending',
        treasuryStatusLabel: pf.ledgerTreasuryStatusLabel || 'Treasury pending',
      };
      plotFinanceHtml = `
        <div class="noc-plot-finance">
          <p><strong>Plot / ledger:</strong> ${escapeHtml(pf.summary || '—')}
            ${pf.outstanding != null ? ` · Outstanding <code>₹${escapeHtml(String(pf.outstanding))}</code>` : ''}
          </p>
          <p class="muted">Ledger treasury ${treasuryStatusIcon(ledgerFake)}${
            item.status === 'requested'
              ? (
                (pf.ledgerTreasuryStatus || '') === 'confirmed'
                  ? ' · Ledger already Treasury-confirmed — issuing unlocks download immediately.'
                  : ' · After issue, this certificate still needs Treasury validate → confirm before download.'
              )
              : ''
          }</p>
        </div>`;
    }
    const certTreasuryHint =
      issuer && item.status === 'issued' && item.downloadLocked
        ? `<p class="muted">Certificate treasury ${treasuryStatusIcon(item)} — validate then confirm to unlock download.</p>`
        : '';
    return `
      <article class="payment-record-card" data-id="${escapeHtml(item.id)}">
        <div class="payment-record-head">
          <strong>Plot <code>${escapeHtml(item.plotNo || item.houseId)}</code>${item.residentName ? ` · ${escapeHtml(item.residentName)}` : ''}</strong>
          <span class="payment-status is-${escapeHtml(item.status || '')}">${escapeHtml(item.statusLabel || item.status)}</span>
          ${item.status === 'issued' ? treasuryStatusIcon(item) : ''}
        </div>
        <p class="muted">Requested ${escapeHtml(formatIstDate(item.createdAt) || '—')}${item.issuedAt ? ` · issued ${escapeHtml(formatIstDate(item.issuedAt))}` : ''}</p>
        ${plotFinanceHtml}
        ${certTreasuryHint}
        ${item.purpose ? `<p><strong>Purpose:</strong> ${escapeHtml(item.purpose)}${item.sentBack ? ' <span class="muted">(sent back — editable)</span>' : ''}</p>` : ''}
        ${item.requestNote ? `<p>${escapeHtml(item.requestNote)}</p>` : ''}
        ${item.reviewNote ? `<p class="muted">Note: ${escapeHtml(item.reviewNote)}</p>` : ''}
        ${actions.length ? `<div class="btn-row">${actions.join('')}</div>` : ''}
      </article>`;
  }

  async function loadResidentNoObjection() {
    const block = el('noObjectionResidentBlock');
    if (!block) return;
    if (isSuperAdmin() || isViewOnly()) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    const own = state.session?.resident?.houseId || '';
    const qs = own ? `?houseId=${encodeURIComponent(own)}` : '';
    const data = await api(`/api/rwa/no-objection-requests${qs}`);
    const rows = data.requests || [];
    const elig = data.eligibility || {};
    const pending = rows.find((r) => r.status === 'requested');
    const latestIssued = rows.find((r) => r.status === 'issued');
    const reqBtn = el('noObjectionRequestBtn');
    const dlBtn = el('noObjectionDownloadBtn');
    const status = el('noObjectionResidentStatus');
    const purposeInput = el('noObjectionPurpose');
    const purposeWrap = el('noObjectionPurposeWrap');
    const purposeSave = el('noObjectionPurposeSaveBtn');
    const purposeLockedHint = el('noObjectionPurposeLockedHint');
    const canEditSentBack = Boolean(pending?.canEditPurpose) && !isViewOnly();
    const canNewRequest = Boolean(elig.eligible) && !pending && !isViewOnly();
    if (purposeWrap) {
      purposeWrap.hidden = isViewOnly() || (!canNewRequest && !pending);
    }
    if (purposeInput) {
      if (pending) {
        purposeInput.value = pending.purpose || elig.defaultPurpose || 'Property transfer / sale / mortgage / official purposes';
        purposeInput.readOnly = !canEditSentBack;
        purposeInput.dataset.touched = canEditSentBack ? (purposeInput.dataset.touched || '') : '';
      } else {
        purposeInput.readOnly = false;
        if (!purposeInput.dataset.touched) {
          purposeInput.value = elig.defaultPurpose || 'Property transfer / sale / mortgage / official purposes';
        }
      }
    }
    if (purposeSave) {
      purposeSave.hidden = !canEditSentBack;
      purposeSave.dataset.requestId = canEditSentBack ? (pending.id || '') : '';
    }
    if (purposeLockedHint) {
      purposeLockedHint.hidden = !(pending && !canEditSentBack);
    }
    if (reqBtn) {
      reqBtn.hidden = !canNewRequest;
      reqBtn.dataset.requestId = '';
    }
    if (dlBtn) {
      const canDl = latestIssued && latestIssued.downloadUrl && !latestIssued.downloadLocked;
      dlBtn.hidden = !canDl;
      dlBtn.dataset.requestId = canDl ? (latestIssued.id || '') : '';
    }
    if (status) {
      if (pending?.sentBack) status.textContent = 'Request sent back — update the purpose if needed, then wait for re-issue.';
      else if (pending) status.textContent = 'Request submitted — waiting for a No Objection Issuer to approve. Purpose is locked.';
      else if (latestIssued && latestIssued.downloadLocked) {
        status.textContent = `Certificate issued — awaiting Treasury ${latestIssued.treasuryStatus === 'validated' ? 'confirmation' : 'validation'} before download.`;
      } else if (latestIssued) status.textContent = 'Certificate issued and Treasury-confirmed — you can download it below.';
      else if (elig.eligible) status.textContent = 'You can request a No Objection Certificate.';
      else status.textContent = elig.reason || 'Not eligible yet.';
    }
    const list = el('noObjectionResidentList');
    if (list) {
      list.innerHTML = rows.length
        ? rows.map((r) => renderNoObjectionRequestCard(r)).join('')
        : '<p class="muted">No certificate requests yet.</p>';
    }
  }

  async function loadEcNoObjectionRequests() {
    if (!hasEntitlement('issue_no_objection')) return;
    const list = el('ecNoObjectionList');
    if (!list) return;
    const statusFilter = el('ecNoObjectionStatusFilter')?.value || 'requested';
    list.innerHTML = '<p class="muted">Loading…</p>';
    const qs = new URLSearchParams({ status: statusFilter, limit: '150' });
    const data = await api(`/api/rwa/no-objection-requests?${qs.toString()}`);
    const rows = data.requests || [];
    if (el('ecNoObjectionStats')) {
      el('ecNoObjectionStats').textContent = statusFilter === 'requested'
        ? `${rows.length} awaiting issue`
        : `${rows.length} request(s) · filter: ${statusFilter}`;
    }
    list.innerHTML = rows.length
      ? rows.map((r) => renderNoObjectionRequestCard(r, { issuer: true })).join('')
      : '<p class="muted">No requests match this filter.</p>';
  }

  async function issueNoObjectionForHouse(houseId) {
    const data = await api('/api/rwa/no-objection-certificate', {
      method: 'POST',
      body: JSON.stringify({ houseId }),
    });
    return data.request;
  }

  el('noObjectionPurpose')?.addEventListener('input', () => {
    if (el('noObjectionPurpose') && !el('noObjectionPurpose').readOnly) el('noObjectionPurpose').dataset.touched = '1';
  });

  el('noObjectionPurposeSaveBtn')?.addEventListener('click', async () => {
    const id = el('noObjectionPurposeSaveBtn')?.dataset?.requestId;
    const status = el('noObjectionResidentStatus');
    const btn = el('noObjectionPurposeSaveBtn');
    if (!id) return;
    if (btn) btn.disabled = true;
    try {
      await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/purpose`, {
        method: 'POST',
        body: JSON.stringify({ purpose: (el('noObjectionPurpose')?.value || '').trim() }),
      });
      if (status) status.textContent = 'Purpose updated.';
      await loadResidentNoObjection();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save purpose';
      window.alert(err.message || 'Could not save purpose');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noObjectionRequestBtn')?.addEventListener('click', async () => {
    const status = el('noObjectionResidentStatus');
    const btn = el('noObjectionRequestBtn');
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Submitting request…';
    try {
      const purpose = (el('noObjectionPurpose')?.value || '').trim();
      await api('/api/rwa/no-objection-requests', {
        method: 'POST',
        body: JSON.stringify({ purpose }),
      });
      if (el('noObjectionPurpose')) el('noObjectionPurpose').dataset.touched = '';
      await loadResidentNoObjection();
    } catch (err) {
      if (status) status.textContent = err.message || 'Request failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noObjectionDownloadBtn')?.addEventListener('click', async () => {
    const id = el('noObjectionDownloadBtn')?.dataset?.requestId;
    const status = el('noObjectionResidentStatus');
    try {
      await openNoObjectionDownloadChooser(id);
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
    }
  });

  el('noObjectionDownloadCancelBtn')?.addEventListener('click', () => {
    el('noObjectionDownloadDialog')?.close();
    pendingNoObjectionDownloadId = '';
  });
  el('noObjectionDlDigitalBtn')?.addEventListener('click', async () => {
    const id = pendingNoObjectionDownloadId;
    el('noObjectionDownloadDialog')?.close();
    const status = el('noObjectionResidentStatus');
    try {
      await downloadNoObjectionRequest(id, 'digital');
      if (status) status.textContent = 'Digital certificate opened — use Close to return, or Download to save.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
      window.alert(err.message || 'Download failed');
    } finally {
      pendingNoObjectionDownloadId = '';
    }
  });
  el('noObjectionDlPrintBtn')?.addEventListener('click', async () => {
    const id = pendingNoObjectionDownloadId;
    el('noObjectionDownloadDialog')?.close();
    const status = el('noObjectionResidentStatus');
    try {
      await downloadNoObjectionRequest(id, 'print');
      if (status) status.textContent = 'Print version opened — print on RWA letterhead paper.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Download failed';
      window.alert(err.message || 'Download failed');
    } finally {
      pendingNoObjectionDownloadId = '';
    }
  });

  el('noObjectionResidentList')?.addEventListener('click', async (event) => {
    if (await handleTreasuryClick(event)) return;
    const dl = event.target.closest('.noc-download');
    const cancel = event.target.closest('.noc-cancel');
    const id = (dl || cancel)?.getAttribute('data-id');
    if (!id) return;
    try {
      if (cancel) {
        if (!window.confirm('Cancel this certificate request?')) return;
        await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/cancel`, {
          method: 'POST',
          body: '{}',
        });
        await loadResidentNoObjection();
        return;
      }
      await openNoObjectionDownloadChooser(id);
    } catch (err) {
      window.alert(err.message || 'Action failed');
    }
  });

  el('ecNoObjectionList')?.addEventListener('click', async (event) => {
    if (await handleTreasuryClick(event)) return;
    const issue = event.target.closest('.noc-issue');
    const reject = event.target.closest('.noc-reject');
    const revert = event.target.closest('.noc-revert');
    const cancel = event.target.closest('.noc-cancel');
    const dl = event.target.closest('.noc-download');
    const id = (issue || reject || revert || cancel || dl)?.getAttribute('data-id');
    if (!id) return;
    try {
      if (issue) {
        await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/issue`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      } else if (reject) {
        const note = promptRejectionReason();
        if (!note) return;
        await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/reject`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (revert) {
        if (!window.confirm('Revert this request to pending? The issued PDF (if any) will be removed.')) return;
        const note = window.prompt('Optional revert note:') || '';
        await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/revert`, {
          method: 'POST',
          body: JSON.stringify({ reviewNote: note }),
        });
      } else if (cancel) {
        if (!window.confirm('Cancel this pending request?')) return;
        await api(`/api/rwa/no-objection-requests/${encodeURIComponent(id)}/cancel`, {
          method: 'POST',
          body: '{}',
        });
      } else if (dl) {
        await openNoObjectionDownloadChooser(id);
        return;
      }
      await loadEcNoObjectionRequests().catch(() => {});
      await loadResidentNoObjection().catch(() => {});
    } catch (err) {
      window.alert(err.message || 'Action failed');
    }
  });

  el('ecNoObjectionRefreshBtn')?.addEventListener('click', () => loadEcNoObjectionRequests().catch(console.error));
  el('ecNoObjectionStatusFilter')?.addEventListener('change', () => loadEcNoObjectionRequests().catch(console.error));

  el('ecNoObjectionCertBtn')?.addEventListener('click', async () => {
    if (!hasEntitlement('issue_no_objection')) {
      window.alert('No Objection Issuer entitlement required');
      return;
    }
    const house = (el('ecNoObjectionHouse')?.value || '').trim();
    const status = el('ecNoObjectionCertStatus');
    if (!house) {
      if (status) status.textContent = 'Enter a plot number.';
      return;
    }
    const btn = el('ecNoObjectionCertBtn');
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Issuing…';
    try {
      await issueNoObjectionForHouse(house);
      if (status) status.textContent = `Certificate issued for plot ${house}. Use Download on the request card when needed.`;
      await loadEcNoObjectionRequests().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  function qrImgUrl(bank) {
    if (!bank?.hasQr && !bank?.qrUrl) return '';
    const base = bank.qrUrl || '/api/rwa/bank/qr';
    return `${base}?t=${encodeURIComponent(bank.qrFilename || bank.updatedAt || Date.now())}`;
  }

  function renderPayCard(target, bank, { showEdit = false, hideTitle = false } = {}) {
    if (!target) return;
    const b = bank || {};
    const name = b.bankName || b.bank_name || 'Bank of Baroda — Mandi';
    const account = b.accountNo || b.account_no || '09640100004511';
    const ifsc = b.ifsc || 'BARB0MANDIX';
    const upiId = b.upiId || '';
    const upiName = b.upiName || '';
    const qr = qrImgUrl(b);
    const label = b.label || 'Society Dues Bank Details';
    const titleHtml = hideTitle ? '' : `<h3>${escapeHtml(label)}</h3>`;
    target.innerHTML = `
      <div class="pay-card-body">
        <div>
          ${titleHtml}
          <p class="pay-meta">
            <span><strong>${escapeHtml(name)}</strong></span>
            <span>A/C ${escapeHtml(account)}</span>
            <span>IFSC ${escapeHtml(ifsc)}</span>
            ${upiId ? `<span>UPI ${escapeHtml(upiId)}${upiName ? ` · ${escapeHtml(upiName)}` : ''}</span>` : '<span class="muted">No UPI ID set yet</span>'}
          </p>
          ${showEdit ? '<div class="btn-row"><button type="button" class="btn secondary compact js-edit-bank">Edit bank &amp; UPI</button></div>' : ''}
        </div>
        ${qr ? `<img class="pay-qr" src="${escapeHtml(qr)}" alt="UPI QR code" width="168" height="168">` : '<p class="muted">UPI QR not uploaded yet.</p>'}
      </div>`;
  }

  function renderEcBankPreview(bank) {
    const box = el('ecBankPreview');
    if (!box) return;
    renderPayCard(box, bank, { showEdit: false });
  }

  function setBankEditError(msg) {
    const box = el('bankEditError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function fillBankEditForm(bank) {
    const b = bank || {};
    if (el('bankEditLabel')) el('bankEditLabel').value = b.label || 'Society Dues Bank Details';
    if (el('bankEditBankName')) el('bankEditBankName').value = b.bankName || b.bank_name || '';
    if (el('bankEditAccountNo')) el('bankEditAccountNo').value = b.accountNo || b.account_no || '';
    if (el('bankEditIfsc')) el('bankEditIfsc').value = b.ifsc || '';
    if (el('bankEditUpiId')) el('bankEditUpiId').value = b.upiId || '';
    if (el('bankEditUpiName')) el('bankEditUpiName').value = b.upiName || '';
    if (el('bankEditQrFile')) el('bankEditQrFile').value = '';
    const preview = el('bankEditQrPreview');
    const qr = qrImgUrl(b);
    if (preview) {
      if (qr) {
        preview.hidden = false;
        preview.innerHTML = `<img src="${escapeHtml(qr)}" alt="Current UPI QR" width="120" height="120"><span class="muted">Current QR on file</span>`;
      } else {
        preview.hidden = true;
        preview.innerHTML = '';
      }
    }
  }

  async function loadBankDetails() {
    const data = await api('/api/rwa/bank');
    renderEcBankPreview(data.bank);
    return data.bank;
  }

  function showDialog(dialog) {
    if (!dialog) return false;
    try {
      if (typeof dialog.showModal === 'function') {
        if (!dialog.open) dialog.showModal();
        return true;
      }
    } catch (err) {
      console.warn('showModal failed', err);
    }
    dialog.setAttribute('open', '');
    return true;
  }

  async function openBankEdit(bank) {
    const dialog = el('bankEditDialog');
    if (!dialog) {
      alert('Bank editor is missing from the page. Try Refresh app.');
      return;
    }
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Loading…';
    let current = bank || null;
    try {
      current = await loadBankDetails();
    } catch (err) {
      if (!current) {
        setBankEditError(err.message || 'Could not load bank details');
        if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
        showDialog(dialog);
        return;
      }
    }
    fillBankEditForm(current || {});
    if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    showDialog(dialog);
  }

  function closeBankEdit() {
    const dialog = el('bankEditDialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  async function saveBankDetails(event) {
    event.preventDefault();
    setBankEditError('');
    const btn = el('bankEditSaveBtn');
    if (btn) btn.disabled = true;
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Saving…';
    try {
      const payload = {
        label: el('bankEditLabel')?.value.trim() || 'RWA collection',
        bankName: el('bankEditBankName')?.value.trim() || '',
        accountNo: el('bankEditAccountNo')?.value.trim() || '',
        ifsc: el('bankEditIfsc')?.value.trim() || '',
        upiId: el('bankEditUpiId')?.value.trim() || '',
        upiName: el('bankEditUpiName')?.value.trim() || '',
      };
      const data = await api('/api/rwa/bank', { method: 'PATCH', body: JSON.stringify(payload) });
      const file = el('bankEditQrFile')?.files?.[0];
      let bank = data.bank;
      if (file) bank = await uploadBankQr(file);
      renderEcBankPreview(bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: hasEntitlement('manage_bank'), hideTitle: true });
      fillBankEditForm(bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Saved.';
    } catch (err) {
      setBankEditError(err.message || 'Save failed');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function uploadBankQr(file) {
    const body = new FormData();
    body.append('qr', file);
    const headers = {};
    const token = state.session?.token;
    if (token) headers['X-RWA-Token'] = token;
    const res = await fetch('/api/rwa/bank/qr', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    return data.bank;
  }

  async function uploadBankQrOnly() {
    const file = el('bankEditQrFile')?.files?.[0];
    if (!file) {
      setBankEditError('Choose a QR image first');
      return;
    }
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Uploading QR…';
    try {
      const bank = await uploadBankQr(file);
      renderEcBankPreview(bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: hasEntitlement('manage_bank'), hideTitle: true });
      fillBankEditForm(bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'QR uploaded.';
    } catch (err) {
      setBankEditError(err.message || 'QR upload failed');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    }
  }

  async function clearBankQr() {
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Removing QR…';
    try {
      const data = await api('/api/rwa/bank/qr', { method: 'DELETE', body: '{}' });
      renderEcBankPreview(data.bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), data.bank, { showEdit: hasEntitlement('manage_bank'), hideTitle: true });
      fillBankEditForm(data.bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'QR removed.';
    } catch (err) {
      setBankEditError(err.message || 'Could not remove QR');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    }
  }

  let ledgerCache = [];
  let ledgerAutoRecalc = true;

  let vaultActiveHouseId = '';

  function vaultFileUrl(doc) {
    const base = doc?.downloadUrl || (doc?.id ? `/api/rwa/vault/${encodeURIComponent(doc.id)}/file` : '');
    if (!base) return '#';
    const token = state.session?.token || '';
    if (!token) return base;
    return `${base}${base.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
  }

  function renderVaultDocCard(doc, caps) {
    const actions = [];
    actions.push(`<button type="button" class="btn ghost compact doc-open" data-url="/api/rwa/vault/${escapeHtml(doc.id)}/file" data-title="${escapeHtml(doc.title || doc.originalName || 'Document')}" data-filename="${escapeHtml(doc.originalName || doc.title || 'document')}" data-mime="${escapeHtml(doc.mime || '')}">Open</button>`);
    if (caps?.canShare && doc.visibility === 'private') {
      actions.push(`<button type="button" class="btn secondary compact vault-share" data-id="${escapeHtml(doc.id)}" data-visibility="shared_ec">Share with EC</button>`);
    }
    if (caps?.canShare && doc.visibility === 'shared_ec' && doc.sourceKind === 'vault_upload') {
      actions.push(`<button type="button" class="btn ghost compact vault-share" data-id="${escapeHtml(doc.id)}" data-visibility="private">Make private</button>`);
    }
    if (caps?.canVerify && doc.visibility === 'shared_ec' && doc.status !== 'verified') {
      actions.push(`<button type="button" class="btn secondary compact vault-verify" data-id="${escapeHtml(doc.id)}" data-status="verified">Verify</button>`);
    }
    if (caps?.canVerify && doc.visibility === 'shared_ec' && doc.status !== 'rejected' && doc.status !== 'verified') {
      actions.push(`<button type="button" class="btn ghost compact vault-verify" data-id="${escapeHtml(doc.id)}" data-status="rejected">Reject</button>`);
    }
    if (doc.canDelete) {
      actions.push(`<button type="button" class="btn ghost compact vault-delete" data-id="${escapeHtml(doc.id)}">Delete</button>`);
    }
    return `
      <article class="vault-doc-card" data-id="${escapeHtml(doc.id)}">
        <header>
          <strong>${escapeHtml(doc.title || doc.originalName || 'Document')}</strong>
          <span class="vault-badge is-${escapeHtml(doc.docType)}">${escapeHtml(doc.docTypeLabel || doc.docType)}</span>
          <span class="vault-badge is-${escapeHtml(doc.visibility)}">${escapeHtml(doc.visibilityLabel || doc.visibility)}</span>
          <span class="vault-badge is-${escapeHtml(doc.status)}">${escapeHtml(doc.statusLabel || doc.status)}</span>
        </header>
        ${doc.description ? `<p>${escapeHtml(doc.description)}</p>` : ''}
        <p class="muted">
          ${escapeHtml(formatIstDateTime(doc.createdAt) || '')}
          ${doc.linkedPaymentRecordId ? ` · payment ${escapeHtml(doc.linkedPaymentRecordId)}` : ''}
          ${doc.linkedNoDuesId ? ` · no-dues ${escapeHtml(doc.linkedNoDuesId)}` : ''}
          ${doc.linkedNoObjectionId ? ` · no-objection ${escapeHtml(doc.linkedNoObjectionId)}` : ''}
        </p>
        ${doc.verifyNote ? `<p class="muted">Note: ${escapeHtml(doc.verifyNote)}</p>` : ''}
        <div class="btn-row">${actions.join('')}</div>
      </article>`;
  }

  function renderVaultDialog(data) {
    const caps = data.capabilities || {};
    if (el('vaultDialogTitle')) {
      el('vaultDialogTitle').textContent = `Documents vault · plot ${data.plotNo || data.houseId || ''}`;
    }
    if (el('vaultDialogSubtitle')) {
      el('vaultDialogSubtitle').textContent = data.residentName
        ? `${data.residentName} — receipts, cash notes, certificates (one copy, role-based view).`
        : 'Receipts, cash notes, and certificates for this plot.';
    }
    const strip = el('vaultLedgerStrip');
    if (strip) {
      const ledger = data.ledger;
      if (ledger) {
        const tActs = caps.canTreasury
          ? treasuryActionButtons('ledger', data.houseId, ledger.treasuryStatus)
          : '';
        strip.hidden = false;
        strip.innerHTML = `
          <span>Ledger treasury ${treasuryStatusIcon(ledger)}</span>
          ${tActs || ''}`;
      } else {
        strip.hidden = true;
        strip.innerHTML = '';
      }
    }
    const uploadWrap = el('vaultUploadWrap');
    if (uploadWrap) uploadWrap.hidden = !caps.canUpload || isViewOnly();
    const list = el('vaultDocList');
    if (list) {
      const docs = data.documents || [];
      list.innerHTML = docs.length
        ? docs.map((d) => renderVaultDocCard(d, caps)).join('')
        : '<p class="muted">No documents in this vault yet.</p>';
    }
    if (el('vaultDialogError')) {
      el('vaultDialogError').hidden = true;
      el('vaultDialogError').textContent = '';
    }
    if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = '';
  }

  async function openVault(houseId) {
    const hid = (houseId || state.session?.resident?.houseId || '').trim();
    if (!hid) return;
    vaultActiveHouseId = hid;
    const dialog = el('vaultDialog');
    if (!dialog) return;
    if (el('vaultDocList')) el('vaultDocList').innerHTML = '<p class="muted">Loading…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      const data = await api(`/api/rwa/vault?houseId=${encodeURIComponent(hid)}`);
      renderVaultDialog(data);
    } catch (err) {
      if (el('vaultDialogError')) {
        el('vaultDialogError').hidden = false;
        el('vaultDialogError').textContent = err.message || 'Could not open vault';
      }
      if (el('vaultDocList')) el('vaultDocList').innerHTML = '';
    }
  }

  async function refreshVaultIfOpen() {
    if (!vaultActiveHouseId || !el('vaultDialog')?.open) return;
    await openVault(vaultActiveHouseId);
  }

  el('vaultOpenMineBtn')?.addEventListener('click', () => {
    openVault(state.session?.resident?.houseId).catch(console.error);
  });
  el('vaultDialogCloseBtn')?.addEventListener('click', () => el('vaultDialog')?.close());
  el('vaultUploadBtn')?.addEventListener('click', async () => {
    const input = el('vaultUploadFiles');
    const files = Array.from(input?.files || []);
    if (!files.length || !vaultActiveHouseId) {
      if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = 'Choose at least one file.';
      return;
    }
    const title = (el('vaultUploadTitle')?.value || '').trim();
    if (!title) {
      if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = 'Add a title for this document.';
      return;
    }
    const fd = new FormData();
    fd.append('houseId', vaultActiveHouseId);
    fd.append('title', title);
    fd.append('description', (el('vaultUploadDescription')?.value || '').trim());
    fd.append('docType', el('vaultUploadDocType')?.value || 'other');
    fd.append('shareWithEc', el('vaultShareWithEc')?.checked ? '1' : '0');
    files.slice(0, 5).forEach((f) => fd.append('files', f));
    const headers = {};
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    if (el('vaultUploadBtn')) el('vaultUploadBtn').disabled = true;
    if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = 'Uploading…';
    try {
      const res = await fetch('/api/rwa/vault', { method: 'POST', credentials: 'same-origin', headers, body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText || 'Upload failed');
      if (input) input.value = '';
      if (el('vaultUploadTitle')) el('vaultUploadTitle').value = '';
      if (el('vaultUploadDescription')) el('vaultUploadDescription').value = '';
      if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = `Uploaded ${(data.documents || []).length} file(s).`;
      await refreshVaultIfOpen();
    } catch (err) {
      if (el('vaultUploadStatus')) el('vaultUploadStatus').textContent = err.message || 'Upload failed';
    } finally {
      if (el('vaultUploadBtn')) el('vaultUploadBtn').disabled = false;
    }
  });
  el('vaultDocList')?.addEventListener('click', async (event) => {
    const shareBtn = event.target.closest('.vault-share');
    const verifyBtn = event.target.closest('.vault-verify');
    const deleteBtn = event.target.closest('.vault-delete');
    if (shareBtn) {
      try {
        await api(`/api/rwa/vault/${encodeURIComponent(shareBtn.getAttribute('data-id'))}/share`, {
          method: 'POST',
          body: JSON.stringify({ visibility: shareBtn.getAttribute('data-visibility') }),
        });
        await refreshVaultIfOpen();
      } catch (err) {
        window.alert(err.message || 'Share update failed');
      }
      return;
    }
    if (verifyBtn) {
      try {
        const status = verifyBtn.getAttribute('data-status');
        const body = { status };
        if (status === 'rejected') {
          const note = promptRejectionReason();
          if (!note) return;
          body.note = note;
        }
        await api(`/api/rwa/vault/${encodeURIComponent(verifyBtn.getAttribute('data-id'))}/verify`, {
          method: 'POST',
          body: JSON.stringify(body),
        });
        await refreshVaultIfOpen();
      } catch (err) {
        window.alert(err.message || 'Verify failed');
      }
      return;
    }
    if (deleteBtn) {
      if (!window.confirm('Delete this document from the vault?')) return;
      try {
        await api(`/api/rwa/vault/${encodeURIComponent(deleteBtn.getAttribute('data-id'))}`, {
          method: 'DELETE',
          body: '{}',
        });
        await refreshVaultIfOpen();
      } catch (err) {
        window.alert(err.message || 'Delete failed');
      }
    }
  });
  el('vaultLedgerStrip')?.addEventListener('click', (event) => {
    handleTreasuryClick(event).then((handled) => {
      if (handled) refreshVaultIfOpen().catch(() => {});
    }).catch(console.error);
  });

  function renderLedgerSummary(sum) {
    if (!el('ledgerSummary') || !sum) return;
    el('ledgerSummary').textContent =
      `${sum.households || 0} households · due ${inr(sum.totalDue)} · received ${inr(sum.totalReceived)} · outstanding ${inr(sum.totalOutstanding)}`;
  }

  function renderLedgerRows() {
    const tbody = el('ledgerRows');
    const cards = el('ledgerCards');
    if (!tbody && !cards) return;
    const q = (el('ledgerSearch')?.value || '').trim().toLowerCase();
    const rows = ledgerCache.filter((r) => {
      if (!q) return true;
      return `${r.houseId} ${r.plotNo || ''} ${r.name || ''} ${r.householdCode || ''} ${r.section || ''} ${r.remarks || ''}`.toLowerCase().includes(q);
    });
    if (!rows.length) {
      if (tbody) tbody.innerHTML = '<tr class="is-empty-row"><td colspan="10" class="muted">No matching ledger rows.</td></tr>';
      if (cards) cards.innerHTML = '<p class="muted ledger-cards-empty">No matching ledger rows.</p>';
      refreshMobileListUi();
      return;
    }
    const canTreasury = hasEntitlement('treasury');
    const vaultBtn = (houseId) => `
          <button type="button" class="btn ghost compact vault-open" data-vault-house="${escapeHtml(houseId)}" title="Documents vault">
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 7.5V19a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9.5a2 2 0 0 0-2-2H12L9.5 5H5a2 2 0 0 0-2 2.5z"/>
            </svg>
            Vault
          </button>`;
    if (tbody) {
      tbody.innerHTML = rows.map((r) => {
        const tActs = canTreasury ? treasuryActionButtons('ledger', r.houseId, r.treasuryStatus) : '';
        return `
      <tr data-house="${escapeHtml(r.houseId)}">
        <td class="ledger-plot" data-label="Plot"><code>${escapeHtml(r.houseId)}</code></td>
        <td class="ledger-name" data-label="Name">${escapeHtml(r.name || '')}</td>
        <td class="ledger-amt" data-label="Prev total">${inr(r.previousTotal ?? r.balancePrev)}</td>
        <td class="ledger-amt" data-label="Prev paid">${inr(r.previousPaid ?? 0)}</td>
        <td class="ledger-amt" data-label="Prev pending">${inr(r.previousPending ?? r.balancePrev)}</td>
        <td class="ledger-amt" data-label="Year total">${inr(r.currentYearTotal ?? r.feeAmount)}</td>
        <td class="ledger-due" data-label="Pending / dues">${inr(r.pendingDues ?? r.balanceOutstanding)}</td>
        <td class="ledger-hh" data-label="HH code"><code class="hh-code">${escapeHtml(r.householdCode || '—')}</code></td>
        <td class="ledger-treas" data-label="Treasury">${treasuryStatusIcon(r, { showLabel: false })}</td>
        <td data-label="Actions" class="row-actions">
          ${vaultBtn(r.houseId)}
          <button type="button" class="btn secondary compact ledger-edit" data-house="${escapeHtml(r.houseId)}">Edit</button>
          ${tActs}
        </td>
      </tr>`;
      }).join('');
    }
    if (cards) {
      cards.innerHTML = rows.map((r) => {
        const pending = Number(r.pendingDues ?? r.balanceOutstanding ?? 0);
        const tActs = canTreasury ? treasuryActionButtons('ledger', r.houseId, r.treasuryStatus) : '';
        const hh = (r.householdCode || '').trim();
        return `
      <article class="ledger-card${pending <= 0 ? ' is-cleared' : ''}" data-house="${escapeHtml(r.houseId)}">
        <header class="ledger-card-head">
          <div class="ledger-card-who">
            <p class="ledger-card-plot"><code>${escapeHtml(r.houseId)}</code></p>
            <p class="ledger-card-name">${escapeHtml(r.name || '—')}</p>
          </div>
          <div class="ledger-card-due">
            <span>${pending <= 0 ? 'Cleared' : 'Pending'}</span>
            <strong>${inr(r.pendingDues ?? r.balanceOutstanding)}</strong>
          </div>
        </header>
        <dl class="ledger-card-metrics">
          <div><dt>Prev total</dt><dd>${inr(r.previousTotal ?? r.balancePrev)}</dd></div>
          <div><dt>Prev paid</dt><dd>${inr(r.previousPaid ?? 0)}</dd></div>
          <div><dt>Prev pending</dt><dd>${inr(r.previousPending ?? r.balancePrev)}</dd></div>
          <div><dt>Year total</dt><dd>${inr(r.currentYearTotal ?? r.feeAmount)}</dd></div>
        </dl>
        <div class="ledger-card-meta">
          ${hh ? `<code class="hh-code">HH ${escapeHtml(hh)}</code>` : '<span class="muted">No HH code</span>'}
          ${treasuryStatusIcon(r)}
        </div>
        <div class="ledger-card-actions row-actions">
          ${vaultBtn(r.houseId)}
          <button type="button" class="btn secondary compact ledger-edit" data-house="${escapeHtml(r.houseId)}">Edit</button>
          ${tActs}
        </div>
      </article>`;
      }).join('');
    }
    refreshMobileListUi();
  }

  async function loadLedger() {
    const all = await api('/api/rwa/payments');
    ledgerCache = all.rows || [];
    renderLedgerSummary(all.summary || {});
    renderLedgerRows();
  }

  function setLedgerEditError(msg) {
    const box = el('ledgerEditError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function syncLedgerDerivedPreview() {
    const prev = Number(el('ledgerEditPrevTotal')?.value || 0);
    const year = Number(el('ledgerEditYearTotal')?.value || 0);
    const received = Number(el('ledgerEditReceived')?.value || 0);
    const totalDue = Number(el('ledgerEditTotalDue')?.value || (prev + year));
    const pending = Number(el('ledgerEditPending')?.value || (totalDue - received));
    const prevPaid = Math.min(Math.max(received, 0), Math.max(prev, 0));
    const prevPending = Math.max(0, prev - prevPaid);
    if (el('ledgerEditDerived')) {
      el('ledgerEditDerived').textContent =
        `Preview · previous paid ${inr(prevPaid)} · previous pending ${inr(prevPending)} · pending/dues ${inr(pending)}`;
    }
  }

  function recalcLedgerTotalsFromInputs() {
    if (!ledgerAutoRecalc) return;
    const prev = Number(el('ledgerEditPrevTotal')?.value || 0);
    const year = Number(el('ledgerEditYearTotal')?.value || 0);
    const received = Number(el('ledgerEditReceived')?.value || 0);
    if (el('ledgerEditTotalDue')) el('ledgerEditTotalDue').value = String(prev + year);
    if (el('ledgerEditPending')) el('ledgerEditPending').value = String(prev + year - received);
    syncLedgerDerivedPreview();
  }

  function openLedgerEdit(houseId) {
    const row = ledgerCache.find((r) => r.houseId === houseId);
    const dialog = el('ledgerEditDialog');
    if (!row || !dialog) return;
    ledgerAutoRecalc = true;
    setLedgerEditError('');
    el('ledgerEditHouseId').value = row.houseId;
    el('ledgerEditTitle').textContent = `Edit · plot ${row.houseId}`;
    el('ledgerEditSubtitle').textContent = `${row.name || 'Resident'}${row.section ? ` · ${row.section}` : ''}`;
    el('ledgerEditPrevTotal').value = String(row.previousTotal ?? row.balancePrev ?? 0);
    el('ledgerEditFeeYear').value = String(row.feeYear || 2026);
    el('ledgerEditYearTotal').value = String(row.currentYearTotal ?? row.feeAmount ?? 0);
    el('ledgerEditReceived').value = String(row.amountReceived ?? 0);
    el('ledgerEditTotalDue').value = String(row.totalDue ?? 0);
    el('ledgerEditPending').value = String(row.pendingDues ?? row.balanceOutstanding ?? 0);
    el('ledgerEditRemarks').value = row.remarks || '';
    syncLedgerDerivedPreview();
    showDialog(dialog);
  }

  function closeLedgerEdit() {
    const dialog = el('ledgerEditDialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  async function saveLedgerEdit(event) {
    event.preventDefault();
    const houseId = el('ledgerEditHouseId')?.value?.trim();
    if (!houseId) return;
    const payload = {
      previousTotal: Number(el('ledgerEditPrevTotal').value),
      feeYear: Number(el('ledgerEditFeeYear').value),
      currentYearTotal: Number(el('ledgerEditYearTotal').value),
      amountReceived: Number(el('ledgerEditReceived').value),
      totalDue: Number(el('ledgerEditTotalDue').value),
      pendingDues: Number(el('ledgerEditPending').value),
      remarks: el('ledgerEditRemarks').value.trim(),
    };
    setLedgerEditError('');
    const btn = el('ledgerEditSaveBtn');
    if (btn) btn.disabled = true;
    if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = `Saving ${houseId}…`;
    try {
      const data = await api(`/api/rwa/payments/${encodeURIComponent(houseId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const updated = data.payment || {};
      const idx = ledgerCache.findIndex((r) => r.houseId === houseId);
      if (idx >= 0) ledgerCache[idx] = { ...ledgerCache[idx], ...updated };
      renderLedgerSummary(data.summary || {});
      renderLedgerRows();
      closeLedgerEdit();
      if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = `Saved plot ${houseId}`;
      // Refresh personal dues card if EC is viewing own plot or just keep summary fresh
      loadDues().catch(() => {});
    } catch (err) {
      setLedgerEditError(err.message || 'Save failed');
      if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = '';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('ledgerSearch')?.addEventListener('input', () => renderLedgerRows());
  el('ledgerList')?.addEventListener('click', async (event) => {
    const vaultBtn = event.target.closest('[data-vault-house]');
    if (vaultBtn) {
      openVault(vaultBtn.getAttribute('data-vault-house')).catch(console.error);
      return;
    }
    if (await handleTreasuryClick(event)) {
      refreshVaultIfOpen().catch(() => {});
      return;
    }
    const btn = event.target.closest('.ledger-edit');
    if (!btn) return;
    openLedgerEdit(btn.getAttribute('data-house'));
  });
  el('ledgerEditCancelBtn')?.addEventListener('click', () => closeLedgerEdit());
  el('ledgerEditForm')?.addEventListener('submit', saveLedgerEdit);
  ['ledgerEditPrevTotal', 'ledgerEditYearTotal', 'ledgerEditReceived'].forEach((id) => {
    el(id)?.addEventListener('input', () => recalcLedgerTotalsFromInputs());
  });
  ['ledgerEditTotalDue', 'ledgerEditPending'].forEach((id) => {
    el(id)?.addEventListener('input', () => {
      ledgerAutoRecalc = false;
      syncLedgerDerivedPreview();
    });
  });
  el('ledgerEditDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeLedgerEdit();
  });

  el('ecEditBankBtn')?.addEventListener('click', () => { openBankEdit().catch(console.error); });
  document.addEventListener('click', (event) => {
    const btn = event.target.closest?.('.js-edit-bank');
    if (btn) {
      event.preventDefault();
      openBankEdit().catch(console.error);
    }
  });
  el('bankEditCancelBtn')?.addEventListener('click', () => closeBankEdit());
  el('bankEditForm')?.addEventListener('submit', saveBankDetails);
  el('bankEditQrOnlyBtn')?.addEventListener('click', () => uploadBankQrOnly());
  el('bankEditClearQrBtn')?.addEventListener('click', () => clearBankQr());
  el('bankEditDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeBankEdit();
  });

  function committeeRoleLabel(r) {
    if (!r) return 'Resident';
    if (r.role === 'admin' || r.isEcAdmin) return 'EC Admin';
    if (r.isOfficeBearer) return 'Office Bearer';
    if (r.isEcMember) return 'EC Member';
    return 'Resident';
  }

  let directoryCache = [];
  let directoryCanViewOccupancy = false;

  async function loadDirectory() {
    const data = await api('/api/rwa/directory');
    directoryCache = data.residents || [];
    directoryCanViewOccupancy = Boolean(data.canViewOccupancy) && isEcAdmin();
    renderDirectory();
  }

  function directoryCanShowHouseholdCode(r) {
    if (isEcAdmin()) return true;
    const own = String(state.session?.resident?.houseId || '').trim();
    return Boolean(own) && own === String(r?.houseId || '').trim();
  }

  function directorySearchHay(r) {
    const delegates = (r.delegates || []).map((d) => [d.name, d.phone, d.identityLabel].join(' ')).join(' ');
    const extra = directoryCanViewOccupancy
      ? [
          (r.tenants || []).map((t) => t.name || '').join(' '),
          (r.vehicles || []).map((v) => [v.plate, v.kindLabel, v.vehicleTypeLabel].join(' ')).join(' '),
        ]
      : [];
    const hh = directoryCanShowHouseholdCode(r) ? (r.householdCode || '') : '';
    return [
      r.houseId, r.plotNo, r.section, hh,
      r.ownerName, r.name, r.primaryDelegateName, r.displayName,
      r.phone, r.email, r.officialTitle, committeeRoleLabel(r),
      r.ecSeatHolderName, delegates, ...extra,
    ].map((v) => String(v || '').toLowerCase()).join(' ');
  }

  function directoryFoldHtml(title, count, rowsHtml, emptyText) {
    const n = Number(count) || 0;
    return `
      <details class="dir-fold">
        <summary>
          <span>${escapeHtml(title)}</span>
          <span class="dir-count">${n}</span>
        </summary>
        ${n ? `<ul class="dir-fold-list">${rowsHtml}</ul>` : `<p class="muted dir-fold-empty">${escapeHtml(emptyText)}</p>`}
      </details>`;
  }

  function indiaMobileDigits(raw) {
    let d = String(raw || '').replace(/\D/g, '');
    if (!d) return '';
    if (d.startsWith('00')) d = d.slice(2);
    if (d.startsWith('91') && d.length >= 12) return d.slice(0, 12);
    if (d.length === 11 && d.startsWith('0')) d = d.slice(1);
    if (d.length === 10) return `91${d}`;
    return d;
  }

  function directoryPhoneHtml(phone) {
    const display = String(phone || '').trim();
    if (!display) return '<span class="muted">—</span>';
    const digits = indiaMobileDigits(display);
    if (digits.length < 10) return escapeHtml(display);
    return `<button type="button" class="dir-contact dir-contact-phone" data-phone="${escapeHtml(display)}" data-digits="${escapeHtml(digits)}" aria-label="Call or WhatsApp ${escapeHtml(display)}">${escapeHtml(display)}</button>`;
  }

  function directoryEmailHtml(email) {
    const addr = String(email || '').trim();
    if (!addr) return '<span class="muted">—</span>';
    if (!addr.includes('@')) return escapeHtml(addr);
    return `<a class="dir-contact dir-contact-email" href="mailto:${escapeHtml(addr)}">${escapeHtml(addr)}</a>`;
  }

  function openDirectoryHref(href) {
    if (!href) return;
    const standalone = window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true;
    if (standalone || href.startsWith('tel:') || href.startsWith('mailto:')) {
      window.location.href = href;
      return;
    }
    const opened = window.open(href, '_blank', 'noopener,noreferrer');
    if (!opened) window.location.href = href;
  }

  function closeDirectoryContactSheet() {
    const sheet = el('dirContactSheet');
    if (sheet?.open) sheet.close();
  }

  function openDirectoryPhoneSheet(display, digits) {
    const sheet = el('dirContactSheet');
    if (!sheet || !digits) return;
    const title = el('dirContactSheetTitle');
    const callBtn = el('dirContactCall');
    const waBtn = el('dirContactWhatsApp');
    if (title) title.textContent = display || `+${digits}`;
    if (callBtn) {
      callBtn.href = `tel:+${digits}`;
      callBtn.dataset.href = `tel:+${digits}`;
    }
    if (waBtn) {
      waBtn.href = `https://wa.me/${digits}`;
      waBtn.dataset.href = `https://wa.me/${digits}`;
    }
    if (typeof sheet.showModal === 'function') sheet.showModal();
    else sheet.setAttribute('open', '');
  }

  function renderDirectory() {
    const box = el('directoryList');
    const meta = el('directoryLookupMeta');
    const lookup = el('directoryLookup');
    if (lookup) {
      lookup.placeholder = directoryCanViewOccupancy
        ? 'Look up plot, owner, delegate, phone, tenant, vehicle…'
        : 'Look up plot, owner, delegate, phone…';
    }
    if (!box) return;
    const q = (el('directoryLookup')?.value || '').trim().toLowerCase();
    const rows = !q
      ? directoryCache
      : directoryCache.filter((r) => directorySearchHay(r).includes(q));
    if (meta) {
      if (!directoryCache.length) meta.textContent = '';
      else if (!q) meta.textContent = `${directoryCache.length} household${directoryCache.length === 1 ? '' : 's'}`;
      else meta.textContent = `${rows.length} of ${directoryCache.length} household${directoryCache.length === 1 ? '' : 's'}`;
    }
    if (!directoryCache.length) {
      box.innerHTML = '<p class="muted">No active plots in the directory.</p>';
      return;
    }
    if (!rows.length) {
      box.innerHTML = '<p class="muted">No households match that lookup.</p>';
      return;
    }
    box.innerHTML = rows.map((r) => {
      const roleLabel = committeeRoleLabel(r);
      const ownerName = (r.ownerName || r.name || '').trim() || '—';
      const delegateName = (r.primaryDelegateName || '').trim();
      const phone = (r.phone || '').trim();
      const email = (r.email || '').trim();
      const hhCode = directoryCanShowHouseholdCode(r) ? (r.householdCode || '').trim() : '';
      const titleBit = r.officialTitle ? ` · ${escapeHtml(r.officialTitle)}` : '';
      const seatBit = (r.isEcMember || r.isOfficeBearer || r.isEcAdmin) && r.ecSeatHolderName
        ? `<p class="dir-seat">EC seat: ${escapeHtml(r.ecSeatHolderName)}</p>`
        : '';
      const phoneHtml = directoryPhoneHtml(phone);
      const emailHtml = directoryEmailHtml(email);
      const delegates = r.delegates || [];
      const tenants = r.tenants || [];
      const vehicles = r.vehicles || [];
      const delegateRows = delegates.map((d) => {
        const label = d.identityLabel || 'Delegate';
        const phone = (d.phone || '').trim();
        const phoneBit = phone ? ` · ${directoryPhoneHtml(phone)}` : '';
        return `<li><strong>${escapeHtml(d.name || '—')}</strong><span class="muted"> · ${escapeHtml(label)}</span>${phoneBit}</li>`;
      }).join('');
      const tenantRows = tenants.map((t) => `<li>${escapeHtml(t.name || 'Tenant')}</li>`).join('');
      const vehicleRows = vehicles.map((v) => {
        const bits = [v.plate, v.vehicleTypeLabel, v.kindLabel].filter(Boolean);
        return `<li><span class="dir-plate">${escapeHtml(v.plate || '')}</span>${bits.length > 1 ? `<span class="muted"> · ${escapeHtml(bits.slice(1).join(' · '))}</span>` : ''}</li>`;
      }).join('');
      const folds = [
        directoryFoldHtml('Delegates', delegates.length, delegateRows, 'No household members recorded for this plot.'),
      ];
      if (directoryCanViewOccupancy) {
        folds.push(
          directoryFoldHtml('Tenants', tenants.length, tenantRows, 'No tenants recorded for this plot.'),
          directoryFoldHtml('Vehicles', vehicles.length, vehicleRows, 'No member or tenant vehicles registered.'),
        );
      }
      return `
      <article class="dir-card" data-house-id="${escapeHtml(r.houseId)}">
        <header class="dir-card-head">
          ${personAvatarHtml(r, { size: 'md' })}
          <div class="dir-card-head-copy">
            <p class="dir-plot"><code>${escapeHtml(r.houseId)}</code>${hhCode ? `<span class="dir-hh">HH ${escapeHtml(hhCode)}</span>` : ''}</p>
            <p class="dir-role">${escapeHtml(roleLabel)}${titleBit}</p>
          </div>
        </header>
        <dl class="dir-fields">
          <div class="dir-field">
            <dt>Owner</dt>
            <dd class="dir-name">${escapeHtml(ownerName)}</dd>
          </div>
          ${delegateName ? `<div class="dir-field"><dt>Primary delegate</dt><dd class="dir-name">${escapeHtml(delegateName)}</dd></div>` : ''}
          <div class="dir-field">
            <dt>Phone</dt>
            <dd>${phoneHtml}</dd>
          </div>
          <div class="dir-field">
            <dt>Email</dt>
            <dd>${emailHtml}</dd>
          </div>
        </dl>
        ${seatBit}
        <div class="dir-folds">${folds.join('')}</div>
      </article>`;
    }).join('');
    hydrateAvatars(box).catch(() => {});
  }

  let infoCategoriesCache = [];
  let infoFoldersCache = [];
  let infoDocsCache = [];
  let infoComposeEn = null;
  let infoComposeHi = null;
  let infoComposeLayout = null;
  let infoDeepLink = null;
  let infoAccessCandidatesCache = null;
  let infoFolderAccessEditId = '';
  const PENDING_INFO_KEY = 'hbc_pending_info';

  function whenComposerReady() {
    if (window.MhwsComposer) return Promise.resolve(window.MhwsComposer);
    return new Promise((resolve) => {
      const done = () => resolve(window.MhwsComposer || null);
      window.addEventListener('mhws-composer-ready', done, { once: true });
      window.setTimeout(done, 5000);
    });
  }

  function syncInfoComposerInputs() {
    if (infoComposeEn && el('infoHtmlInput')) el('infoHtmlInput').value = infoComposeEn.getHTML();
    if (infoComposeHi && el('infoHtmlHiInput')) el('infoHtmlHiInput').value = infoComposeHi.getHTML();
  }

  function infoComposerHtml(lang) {
    const session = lang === 'hi' ? infoComposeHi : infoComposeEn;
    if (session) return session.isEmpty() ? '' : session.getHTML();
    return String(el(lang === 'hi' ? 'infoHtmlHiInput' : 'infoHtmlInput')?.value || '').trim();
  }

  let infoComposeMountPromise = null;

  async function mountInfoComposers() {
    if (infoComposeEn && infoComposeHi && infoComposeLayout) return;
    if (infoComposeMountPromise) return infoComposeMountPromise;
    infoComposeMountPromise = (async () => {
      const C = await whenComposerReady();
      if (!C) return;
      const shell = el('infoHtmlPane');
      if (shell && !infoComposeLayout) {
        infoComposeLayout = C.attachLayout(shell, {
          storageKey: 'mhws-composer-layout-info',
          langForm: 'info',
          applySaved: false,
        });
      }
      if (!infoComposeEn && el('infoComposeEditorEn') && el('infoComposeToolbarEn')) {
        infoComposeEn = C.mount({
          host: el('infoComposeEditorEn'),
          toolbar: el('infoComposeToolbarEn'),
          imageInput: el('infoComposeImageEn'),
          textarea: el('infoHtmlInput'),
        });
      }
      if (!infoComposeHi && el('infoComposeEditorHi') && el('infoComposeToolbarHi')) {
        infoComposeHi = C.mount({
          host: el('infoComposeEditorHi'),
          toolbar: el('infoComposeToolbarHi'),
          imageInput: el('infoComposeImageHi'),
          textarea: el('infoHtmlHiInput'),
        });
      }
    })();
    try {
      await infoComposeMountPromise;
    } finally {
      infoComposeMountPromise = null;
    }
  }

  async function fetchInfoDocHtml(docId, lang) {
    const extra = lang === 'hi' ? { lang: 'hi' } : {};
    const url = authDocUrl(`/api/rwa/info-centre/${encodeURIComponent(docId)}/file`, extra);
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) return '';
    const html = await res.text();
    return window.MhwsComposer?.extractBody ? window.MhwsComposer.extractBody(html) : html;
  }

  async function loadInfoHtmlIntoComposer(doc) {
    await mountInfoComposers();
    if (!doc || doc.docType !== 'html') {
      infoComposeEn?.setHTML('<p></p>');
      infoComposeHi?.setHTML('<p></p>');
      syncInfoComposerInputs();
      return;
    }
    try {
      infoComposeEn?.setHTML((await fetchInfoDocHtml(doc.id, 'en')) || '<p></p>');
      if (doc.hasHtmlHi) {
        infoComposeHi?.setHTML((await fetchInfoDocHtml(doc.id, 'hi')) || '<p></p>');
      } else {
        infoComposeHi?.setHTML('<p></p>');
      }
    } catch (_err) {
      /* keep whatever is in the editor */
    }
    syncInfoComposerInputs();
  }

  function rememberPendingInfo(link) {
    if (!link || !link.type || !link.id) return;
    try {
      localStorage.setItem(PENDING_INFO_KEY, JSON.stringify({
        type: link.type,
        id: link.id,
        t: Date.now(),
      }));
    } catch (_err) { /* ignore */ }
  }

  function readPendingInfo({ consume = false } = {}) {
    try {
      const raw = localStorage.getItem(PENDING_INFO_KEY);
      if (!raw) return null;
      const o = JSON.parse(raw);
      if (!o || !o.type || !o.id) return null;
      if (Date.now() - Number(o.t || 0) > 7 * 24 * 60 * 60 * 1000) {
        localStorage.removeItem(PENDING_INFO_KEY);
        return null;
      }
      if (consume) localStorage.removeItem(PENDING_INFO_KEY);
      return { type: o.type, id: String(o.id) };
    } catch (_err) {
      return null;
    }
  }

  function parseInfoDeepLink(hash) {
    const h = String(hash || '').replace(/^#/, '');
    const docM = h.match(/^info\/doc\/(.+)$/);
    if (docM) return { type: 'doc', id: decodeURIComponent(docM[1]) };
    const folderM = h.match(/^info\/folder\/(.+)$/);
    if (folderM) return { type: 'folder', id: decodeURIComponent(folderM[1]) };
    if (h === 'info') return { type: 'panel' };
    return null;
  }

  function captureShareQueryDeepLink() {
    try {
      const params = new URLSearchParams(location.search || '');
      const raw = String(params.get('info') || '').trim();
      const m = raw.match(/^(doc|folder)\.(.+)$/i);
      if (!m) {
        const fromHash = parseInfoDeepLink(location.hash);
        if (fromHash && fromHash.type !== 'panel') {
          infoDeepLink = fromHash;
          rememberPendingInfo(fromHash);
        } else if (!infoDeepLink) {
          infoDeepLink = readPendingInfo({ consume: false });
        }
        return;
      }
      const type = m[1].toLowerCase();
      const id = decodeURIComponent(m[2]);
      if (!id) return;
      infoDeepLink = { type, id };
      rememberPendingInfo(infoDeepLink);
      const hash = type === 'folder'
        ? `#info/folder/${encodeURIComponent(id)}`
        : `#info/doc/${encodeURIComponent(id)}`;
      const next = new URL(location.href);
      next.searchParams.delete('info');
      if (!next.searchParams.get('source')) next.searchParams.set('source', 'pwa');
      const q = next.searchParams.toString();
      history.replaceState(null, '', `${next.pathname}${q ? `?${q}` : ''}${hash}`);
    } catch (_err) {
      /* ignore */
    }
  }
  captureShareQueryDeepLink();

  if ('launchQueue' in window) {
    try {
      window.launchQueue.setConsumer((params) => {
        const target = params && params.targetURL;
        if (!target) return;
        try {
          const u = new URL(target, location.origin);
          const raw = String(u.searchParams.get('info') || '').trim();
          const m = raw.match(/^(doc|folder)\.(.+)$/i);
          if (m) {
            infoDeepLink = { type: m[1].toLowerCase(), id: decodeURIComponent(m[2]) };
            rememberPendingInfo(infoDeepLink);
          } else {
            const fromHash = parseInfoDeepLink(u.hash);
            if (fromHash && fromHash.type !== 'panel') {
              infoDeepLink = fromHash;
              rememberPendingInfo(fromHash);
            }
          }
          if (state.session) applyRouteHash();
        } catch (_err) { /* ignore */ }
      });
    } catch (_err) { /* ignore */ }
  }

  function formatBytes(n) {
    const num = Number(n) || 0;
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
    return `${(num / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function infoShareUrl({ folderId = '', docId = '' } = {}) {
    const origin = await publicSiteOrigin();
    // Static nginx HTML + cache-bust query so WhatsApp scrapes a fresh OG card.
    if (docId) return `${origin}/share/doc/${encodeURIComponent(docId)}.html?v=wa1`;
    if (folderId) return `${origin}/share/folder/${encodeURIComponent(folderId)}.html?v=wa1`;
    return `${origin}/#info`;
  }

  async function copyInfoShareLink({ folderId = '', docId = '', label = 'Link' } = {}) {
    const url = await infoShareUrl({ folderId, docId });
    // Warm / write the nginx static OG card (deploy used to wipe /share/; Flask /s/ recreates it).
    try {
      const warm = docId
        ? `/s/doc/${encodeURIComponent(docId)}`
        : (folderId ? `/s/folder/${encodeURIComponent(folderId)}` : '');
      if (warm) await fetch(warm, { credentials: 'omit', cache: 'no-store' });
    } catch (_err) { /* still copy the URL; nginx falls back to /s/ */ }
    try {
      await navigator.clipboard.writeText(url);
      window.alert(
        `${label} copied.\n\nChat apps show a title preview for this link.\nRecipients still must sign in to open the document.\n\n${url}`
      );
    } catch (_err) {
      window.prompt('Copy this link (recipients must sign in):', url);
    }
  }

  function infoFoldersSortedTree() {
    const byParent = new Map();
    for (const f of infoFoldersCache) {
      const pid = f.parentId || '';
      if (!byParent.has(pid)) byParent.set(pid, []);
      byParent.get(pid).push(f);
    }
    for (const list of byParent.values()) {
      list.sort((a, b) => {
        const so = (a.sortOrder || 100) - (b.sortOrder || 100);
        if (so) return so;
        return String(a.title || '').localeCompare(String(b.title || ''), undefined, { sensitivity: 'base' });
      });
    }
    const out = [];
    const walk = (parentId, depth) => {
      for (const f of (byParent.get(parentId) || [])) {
        out.push({ ...f, depth });
        walk(f.id, depth + 1);
      }
    };
    walk('', 0);
    const seen = new Set(out.map((f) => f.id));
    for (const f of infoFoldersCache) {
      if (!seen.has(f.id)) out.push({ ...f, depth: 0 });
    }
    return out;
  }

  function infoFolderOptionLabel(f, { withCount = false } = {}) {
    const depth = Number(f.depth || 0);
    const indent = depth > 0 ? `${'· '.repeat(depth)}` : '';
    const path = f.pathLabel || f.title || 'Folder';
    const count = withCount && f.docCount != null ? ` (${f.docCount})` : '';
    return `${indent}${path}${count}`;
  }

  function fillInfoFolderParentSelect(selectEl, { excludeId = '', selected = '' } = {}) {
    if (!selectEl) return;
    const tree = infoFoldersSortedTree();
    let blocked = new Set();
    if (excludeId) {
      const kids = new Map();
      for (const f of infoFoldersCache) {
        const pid = f.parentId || '';
        if (!kids.has(pid)) kids.set(pid, []);
        kids.get(pid).push(f.id);
      }
      const stack = [excludeId];
      while (stack.length) {
        const cur = stack.pop();
        blocked.add(cur);
        for (const k of (kids.get(cur) || [])) stack.push(k);
      }
    }
    const opts = tree
      .filter((f) => !blocked.has(f.id))
      .map((f) => `<option value="${escapeHtml(f.id)}">${escapeHtml(infoFolderOptionLabel(f))}</option>`)
      .join('');
    selectEl.innerHTML = `<option value="">Top level</option>${opts}`;
    if (selected && [...selectEl.options].some((o) => o.value === selected)) selectEl.value = selected;
    else selectEl.value = '';
  }

  function infoAudienceBadgeClass(audience) {
    if (audience === 'ec') return 'is-ec';
    if (audience === 'restricted') return 'is-restricted';
    return 'is-all';
  }

  async function ensureInfoAccessCandidates() {
    if (infoAccessCandidatesCache) return infoAccessCandidatesCache;
    if (!hasEntitlement('manage_info')) {
      infoAccessCandidatesCache = [];
      return infoAccessCandidatesCache;
    }
    try {
      const data = await api('/api/rwa/info-centre/access-candidates');
      infoAccessCandidatesCache = data.members || [];
    } catch (_err) {
      infoAccessCandidatesCache = [];
    }
    return infoAccessCandidatesCache;
  }

  function selectedInfoAccessIds(listEl) {
    if (!listEl) return [];
    return [...listEl.querySelectorAll('input[type="checkbox"][data-member-id]:checked')]
      .map((cb) => cb.getAttribute('data-member-id'))
      .filter(Boolean);
  }

  function setInfoAccessPickerVisibility(pickerEl, audience) {
    if (!pickerEl) return;
    pickerEl.hidden = audience !== 'restricted';
  }

  async function renderInfoAccessList(listEl, {
    selectedIds = [],
    search = '',
  } = {}) {
    if (!listEl) return;
    const members = await ensureInfoAccessCandidates();
    const selected = new Set((selectedIds || []).map(String));
    const q = String(search || '').trim().toLowerCase();
    const filtered = !q
      ? members
      : members.filter((m) => {
        const hay = `${m.houseId || ''} ${m.name || ''} ${m.relationLabel || ''} ${m.label || ''}`.toLowerCase();
        return hay.includes(q);
      });
    if (!filtered.length) {
      listEl.innerHTML = `<p class="muted">${members.length ? 'No matches.' : 'No household members found.'}</p>`;
      return;
    }
    listEl.innerHTML = filtered.map((m) => {
      const id = String(m.id || '');
      const checked = selected.has(id) ? ' checked' : '';
      const label = m.label || `${m.houseId || ''} — ${m.name || ''}`;
      return `<label class="info-access-option">
        <input type="checkbox" data-member-id="${escapeHtml(id)}"${checked}>
        <span>${escapeHtml(label)}</span>
      </label>`;
    }).join('');
  }

  function syncInfoDocAccessPicker() {
    const audience = el('infoAudienceInput')?.value || 'all';
    setInfoAccessPickerVisibility(el('infoDocAccessPicker'), audience);
  }

  function syncInfoFolderNewAccessPicker() {
    const audience = el('infoFolderNewAudience')?.value || 'all';
    setInfoAccessPickerVisibility(el('infoFolderNewAccessPicker'), audience);
  }

  async function editInfoFolderAccess(folderId) {
    if (!hasEntitlement('manage_info') || !folderId) return;
    const folder = infoFoldersCache.find((f) => f.id === folderId);
    if (!folder) return;
    infoFolderAccessEditId = folderId;
    const panel = el('infoFolderEditAccess');
    if (!panel) return;
    panel.hidden = false;
    if (el('infoFolderEditAccessTitle')) {
      el('infoFolderEditAccessTitle').textContent = `Access · ${folder.title}`;
    }
    if (el('infoFolderEditAudience')) el('infoFolderEditAudience').value = folder.audience || 'all';
    setInfoAccessPickerVisibility(
      el('infoFolderEditAccessPicker'),
      folder.audience || 'all'
    );
    if (el('infoFolderEditAccessSearch')) el('infoFolderEditAccessSearch').value = '';
    await renderInfoAccessList(el('infoFolderEditAccessList'), {
      selectedIds: folder.allowedMemberIds || [],
    });
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function saveInfoFolderAccessEdit() {
    if (!hasEntitlement('manage_info') || !infoFolderAccessEditId) return;
    const audience = el('infoFolderEditAudience')?.value || 'all';
    const payload = { audience };
    if (audience === 'restricted') {
      payload.allowedMemberIds = selectedInfoAccessIds(el('infoFolderEditAccessList'));
    } else {
      payload.allowedMemberIds = [];
    }
    const status = el('infoFolderManageStatus');
    try {
      await api(`/api/rwa/info-centre/folders/${encodeURIComponent(infoFolderAccessEditId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      infoFolderAccessEditId = '';
      if (el('infoFolderEditAccess')) el('infoFolderEditAccess').hidden = true;
      if (status) status.textContent = 'Folder access updated.';
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      alert(err.message || 'Could not update folder access');
    }
  }

  function fillInfoCategorySelects(categories) {
    infoCategoriesCache = categories || [];
    const filter = el('infoCategoryFilter');
    const formSel = el('infoCategoryInput');
    const opts = infoCategoriesCache.map((c) =>
      `<option value="${escapeHtml(c.id)}">${escapeHtml(c.label)}</option>`
    ).join('');
    if (filter) {
      const cur = filter.value;
      filter.innerHTML = `<option value="">All categories</option>${opts}`;
      filter.value = cur;
    }
    if (formSel) {
      const cur = formSel.value || 'general';
      formSel.innerHTML = opts || '<option value="general">General</option>';
      formSel.value = cur;
    }
  }

  function fillInfoFolderSelects(folders) {
    infoFoldersCache = folders || [];
    const tree = infoFoldersSortedTree();
    const filter = el('infoFolderFilter');
    const formSel = el('infoFolderInput');
    const opts = tree.map((f) =>
      `<option value="${escapeHtml(f.id)}">${escapeHtml(infoFolderOptionLabel(f, { withCount: true }))}</option>`
    ).join('');
    if (filter) {
      const cur = filter.value;
      filter.innerHTML = `<option value="">All folders</option><option value="unfiled">Unfiled</option>${opts}`;
      if ([...filter.options].some((o) => o.value === cur)) filter.value = cur;
    }
    if (formSel) {
      const cur = formSel.value || '';
      formSel.innerHTML = `<option value="">Unfiled</option>${tree.map((f) =>
        `<option value="${escapeHtml(f.id)}">${escapeHtml(infoFolderOptionLabel(f))}</option>`
      ).join('')}`;
      if ([...formSel.options].some((o) => o.value === cur)) formSel.value = cur;
    }
    fillInfoFolderParentSelect(el('infoFolderNewParent'));
    renderInfoFolderManageList();
  }

  function renderInfoFolderManageList() {
    const box = el('infoFolderManageList');
    if (!box) return;
    if (!hasEntitlement('manage_info')) {
      box.innerHTML = '';
      return;
    }
    const tree = infoFoldersSortedTree();
    if (!tree.length) {
      box.innerHTML = '<p class="muted">No folders yet.</p>';
      return;
    }
    box.innerHTML = tree.map((f) => `
      <div class="info-folder-manage-row ${f.depth ? 'is-nested' : ''}" data-id="${escapeHtml(f.id)}" style="--info-depth:${Number(f.depth) || 0}">
        <div>
          <strong>${escapeHtml(f.title)}</strong>
          <span class="muted">${f.docCount || 0} doc${(f.docCount || 0) === 1 ? '' : 's'}${f.pathLabel && f.pathLabel !== f.title ? ` · ${escapeHtml(f.pathLabel)}` : ''}${f.summary ? ` · ${escapeHtml(f.summary)}` : ''}</span>
          <span class="info-doc-badge ${infoAudienceBadgeClass(f.audience)}">${escapeHtml(f.audienceLabel || 'All members')}</span>
        </div>
        <div class="btn-row">
          <button type="button" class="btn ghost compact info-folder-share" data-id="${escapeHtml(f.id)}">Copy link</button>
          <button type="button" class="btn ghost compact info-folder-access" data-id="${escapeHtml(f.id)}">Access</button>
          <button type="button" class="btn ghost compact info-folder-add-child" data-id="${escapeHtml(f.id)}">Add subfolder</button>
          <button type="button" class="btn ghost compact info-folder-move" data-id="${escapeHtml(f.id)}">Move</button>
          <button type="button" class="btn ghost compact info-folder-rename" data-id="${escapeHtml(f.id)}">Rename</button>
          <button type="button" class="btn ghost compact info-folder-delete" data-id="${escapeHtml(f.id)}">Delete</button>
        </div>
      </div>
    `).join('');
  }

  function syncInfoSourcePanes() {
    const source = document.querySelector('input[name="infoSource"]:checked')?.value || 'file';
    if (el('infoFilePane')) el('infoFilePane').hidden = source !== 'file';
    if (el('infoHtmlPane')) el('infoHtmlPane').hidden = source !== 'html';
    if (el('infoLinkPane')) el('infoLinkPane').hidden = source !== 'link';
    if (el('infoFileInput')) el('infoFileInput').required = false;
    if (el('infoLinkInput')) el('infoLinkInput').required = false;
    if (source === 'html') {
      mountInfoComposers()
        .then(() => infoComposeLayout?.applySaved())
        .catch(() => {});
    } else {
      infoComposeLayout?.setLayout('original', { skipPersist: true });
    }
  }

  function resetInfoForm() {
    const form = el('infoDocForm');
    if (!form) return;
    form.reset();
    if (el('infoEditId')) el('infoEditId').value = '';
    if (el('infoStatusInput')) el('infoStatusInput').value = 'published';
    if (el('infoAudienceInput')) el('infoAudienceInput').value = 'all';
    if (el('infoDocAccessSearch')) el('infoDocAccessSearch').value = '';
    renderInfoAccessList(el('infoDocAccessList'), { selectedIds: [] }).catch(() => {});
    syncInfoDocAccessPicker();
    if (el('infoFormTitle')) el('infoFormTitle').textContent = 'Publish a document';
    if (el('infoSaveBtn')) el('infoSaveBtn').textContent = 'Publish';
    if (el('infoCancelEditBtn')) el('infoCancelEditBtn').hidden = true;
    if (el('infoFormStatus')) el('infoFormStatus').textContent = '';
    const fileRadio = document.querySelector('input[name="infoSource"][value="file"]');
    if (fileRadio) fileRadio.checked = true;
    if (el('infoTitleHiInput')) el('infoTitleHiInput').value = '';
    if (el('infoSummaryHiInput')) el('infoSummaryHiInput').value = '';
    if (el('infoHtmlHiInput')) el('infoHtmlHiInput').value = '';
    if (el('infoHtmlInput')) el('infoHtmlInput').value = '';
    infoComposeEn?.setHTML('<p></p>');
    infoComposeHi?.setHTML('<p></p>');
    if (el('infoLinkInput')) el('infoLinkInput').value = '';
    setAuthorFormLang('info', 'en');
    syncInfoSourcePanes();
  }

  function startInfoEdit(doc) {
    if (!doc || !hasEntitlement('manage_info')) return;
    if (el('infoEditId')) el('infoEditId').value = doc.id || '';
    if (el('infoTitleInput')) el('infoTitleInput').value = doc.title || '';
    if (el('infoTitleHiInput')) el('infoTitleHiInput').value = doc.titleHi || '';
    if (el('infoSummaryInput')) el('infoSummaryInput').value = doc.summary || '';
    if (el('infoSummaryHiInput')) el('infoSummaryHiInput').value = doc.summaryHi || '';
    if (el('infoCategoryInput')) el('infoCategoryInput').value = doc.category || 'general';
    if (el('infoFolderInput')) el('infoFolderInput').value = doc.folderId || '';
    if (el('infoStatusInput')) el('infoStatusInput').value = doc.status || 'draft';
    if (el('infoAudienceInput')) el('infoAudienceInput').value = doc.audience || 'all';
    syncInfoDocAccessPicker();
    renderInfoAccessList(el('infoDocAccessList'), {
      selectedIds: doc.allowedMemberIds || [],
    }).catch(() => {});
    const htmlRadio = document.querySelector('input[name="infoSource"][value="html"]');
    const fileRadio = document.querySelector('input[name="infoSource"][value="file"]');
    const linkRadio = document.querySelector('input[name="infoSource"][value="link"]');
    if (doc.docType === 'html' && htmlRadio) htmlRadio.checked = true;
    else if (doc.docType === 'link' && linkRadio) linkRadio.checked = true;
    else if (fileRadio) fileRadio.checked = true;
    syncInfoSourcePanes();
    if (el('infoLinkInput')) el('infoLinkInput').value = doc.externalUrl || '';
    if (el('infoHtmlInput') && doc.docType !== 'html') el('infoHtmlInput').value = '';
    if (el('infoHtmlHiInput') && doc.docType !== 'html') el('infoHtmlHiInput').value = '';
    if (doc.docType === 'html') {
      loadInfoHtmlIntoComposer(doc).catch(() => {});
    } else {
      infoComposeEn?.setHTML('<p></p>');
      infoComposeHi?.setHTML('<p></p>');
    }
    setAuthorFormLang('info', 'en');
    if (el('infoFormTitle')) el('infoFormTitle').textContent = 'Update document';
    if (el('infoSaveBtn')) el('infoSaveBtn').textContent = 'Save changes';
    if (el('infoCancelEditBtn')) el('infoCancelEditBtn').hidden = false;
    if (el('infoFormStatus')) {
      if (doc.fileMissing && doc.docType === 'link') {
        el('infoFormStatus').textContent = 'Web link missing — paste the URL again and Save.';
      } else if (doc.fileMissing) {
        el('infoFormStatus').textContent = 'File missing on server — choose the file again and Save to restore it.';
      } else if (doc.docType === 'html') {
        el('infoFormStatus').textContent = 'Editing document — switch EN/हिं for bilingual content. Leave the page blank to keep existing.';
      } else if (doc.docType === 'link') {
        el('infoFormStatus').textContent = `Editing web link — ${doc.externalUrl || 'no URL yet'}.`;
      } else {
        el('infoFormStatus').textContent = `Editing ${doc.originalName || doc.id} — Hindi title/summary optional; file uploads stay single-language.`;
      }
    }
    const details = el('infoManageDetails');
    if (details) details.open = true;
    el('infoManageBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function confirmInfoPublish(title, audience) {
    if (audience === 'ec') {
      return window.confirm(
        `Are you sure you want to publish “${title}” to EC members only?\n\nRegular residents will not see this document.`
      );
    }
    if (audience === 'restricted') {
      return window.confirm(
        `Are you sure you want to publish “${title}” to specific members only?\n\nOnly the selected people (and Info managers) will see it.`
      );
    }
    return window.confirm(
      `Are you sure you want to publish “${title}” to ALL members?\n\nThis will be visible to every signed-in resident.`
    );
  }

  function renderInfoDocCard(d) {
    const when = formatIstDate(d.publishedAt || d.updatedAt);
    const typeLabel = d.docType === 'html' ? 'HTML' : (d.docType === 'link' ? 'Link' : 'File');
    const typeClass = d.docType === 'html' ? 'is-html' : (d.docType === 'link' ? 'is-link' : 'is-file');
    const mark = d.docType === 'html'
      ? 'HTML'
      : (d.docType === 'link'
        ? 'LINK'
        : (/\.pdf$/i.test(d.originalName || d.filename || d.externalUrl || '') || String(d.mimeType || '').includes('pdf') ? 'PDF' : 'FILE'));
    const badges = [
      d.folderTitle ? `<span class="info-doc-badge is-folder">${escapeHtml(d.folderTitle)}</span>` : '',
      `<span class="info-doc-badge">${escapeHtml(d.categoryLabel || d.category || 'general')}</span>`,
      `<span class="info-doc-badge ${typeClass}">${typeLabel}</span>`,
      d.fileMissing ? `<span class="info-doc-badge is-draft">${d.docType === 'link' ? 'Link missing' : 'File missing'}</span>` : '',
      d.status === 'published'
        ? `<span class="info-doc-badge ${infoAudienceBadgeClass(d.audience)}">${escapeHtml(d.audienceLabel || (d.audience === 'ec' ? 'EC only' : d.audience === 'restricted' ? 'Restricted' : 'All members'))}</span>`
        : '',
      d.status === 'draft' ? '<span class="info-doc-badge is-draft">Draft</span>' : '',
    ].filter(Boolean).join('');
    const metaBits = [
      d.sizeBytes ? formatBytes(d.sizeBytes) : '',
      when || '',
    ].filter(Boolean).join(' · ');
    const primary = [];
    if (!d.fileMissing) {
      primary.push(`<button type="button" class="btn primary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open</button>`);
    }
    const more = [];
    more.push(`<button type="button" class="btn ghost compact info-doc-share" data-id="${escapeHtml(d.id)}">Copy link</button>`);
    if (hasEntitlement('manage_info')) {
      more.push(`<button type="button" class="btn secondary compact info-doc-edit" data-id="${escapeHtml(d.id)}">${d.fileMissing ? (d.docType === 'link' ? 'Fix link' : 'Re-upload file') : 'Edit'}</button>`);
      more.push(`<button type="button" class="btn ghost compact info-doc-move" data-id="${escapeHtml(d.id)}">Move</button>`);
      if (d.status !== 'published') {
        more.push(`<button type="button" class="btn ghost compact info-doc-publish" data-id="${escapeHtml(d.id)}" data-audience="all">Publish to all</button>`);
        more.push(`<button type="button" class="btn ghost compact info-doc-publish" data-id="${escapeHtml(d.id)}" data-audience="ec">Publish to EC</button>`);
      } else {
        more.push(`<button type="button" class="btn ghost compact info-doc-unpublish" data-id="${escapeHtml(d.id)}">Unpublish</button>`);
      }
      more.push(`<button type="button" class="btn ghost compact info-doc-delete" data-id="${escapeHtml(d.id)}">Delete</button>`);
    }
    const detailsBits = [
      badges ? `<div class="info-doc-badges">${badges}</div>` : '',
      metaBits ? `<p class="meta">${escapeHtml(metaBits)}</p>` : '',
    ].filter(Boolean).join('');
    return `
      <article class="info-doc-card" data-id="${escapeHtml(d.id)}" data-doc-type="${escapeHtml(d.docType || 'file')}" title="Double-click for more actions">
        <div class="info-doc-card-row">
          <span class="info-doc-tablet-mark" aria-hidden="true">${mark}</span>
          <h4 class="info-doc-card-title">${escapeHtml(d.title || 'Untitled')}</h4>
          ${detailsBits ? `<button type="button" class="info-doc-info-btn" data-id="${escapeHtml(d.id)}" aria-expanded="false" aria-label="Show document details" title="Details">i</button>` : ''}
          <div class="info-doc-card-actions-inline">
            <div class="btn-row info-doc-actions-primary">${primary.join('') || '<span class="muted">Unavailable</span>'}</div>
          </div>
        </div>
        ${detailsBits ? `<div class="info-doc-card-details" hidden>${detailsBits}</div>` : ''}
        <div class="btn-row info-doc-actions-more" hidden>${more.join('')}</div>
      </article>`;
  }

  function renderInfoFolderSection(folder, docsByFolder, depth) {
    const docs = docsByFolder.get(folder.id) || [];
    const kids = infoFoldersCache
      .filter((f) => (f.parentId || '') === folder.id)
      .sort((a, b) => {
        const so = (a.sortOrder || 100) - (b.sortOrder || 100);
        if (so) return so;
        return String(a.title || '').localeCompare(String(b.title || ''), undefined, { sensitivity: 'base' });
      });
    const childHtml = kids.map((k) => renderInfoFolderSection(k, docsByFolder, depth + 1)).join('');
    if (!docs.length && !childHtml) return '';
    return `
      <section class="info-folder-section ${depth ? 'is-nested' : ''}" data-folder="${escapeHtml(folder.id)}" style="--info-depth:${depth}">
        <header class="info-folder-head">
          <div class="info-folder-head-row">
            <h3>${escapeHtml(folder.title)}</h3>
            <div class="btn-row">
              <button type="button" class="btn ghost compact info-folder-share" data-id="${escapeHtml(folder.id)}">Copy link</button>
            </div>
          </div>
          ${folder.summary ? `<p class="muted">${escapeHtml(folder.summary)}</p>` : ''}
          <p class="muted">${docs.length} document${docs.length === 1 ? '' : 's'}${kids.length ? ` · ${kids.length} subfolder${kids.length === 1 ? '' : 's'}` : ''}</p>
        </header>
        ${docs.length ? `<div class="info-folder-docs">${docs.map(renderInfoDocCard).join('')}</div>` : ''}
        ${childHtml}
      </section>`;
  }

  function renderInfoDocs() {
    const box = el('infoDocList');
    const status = el('infoListStatus');
    if (!box) return;
    if (!infoDocsCache.length && !infoFoldersCache.length) {
      box.classList.remove('is-cards');
      box.innerHTML = '<p class="muted">No documents yet. EC can publish circulars, bye-laws, forms, and guides here — group them in folders such as Society Registration.</p>';
      if (status) status.textContent = '';
      return;
    }
    if (status) {
      status.textContent = `${infoDocsCache.length} document${infoDocsCache.length === 1 ? '' : 's'}`;
    }
    const folderFilter = el('infoFolderFilter')?.value || '';
    const docsByFolder = new Map();
    const unfiled = [];
    for (const d of infoDocsCache) {
      if (!d.folderId) {
        unfiled.push(d);
        continue;
      }
      if (!docsByFolder.has(d.folderId)) docsByFolder.set(d.folderId, []);
      docsByFolder.get(d.folderId).push(d);
    }

    if (folderFilter === 'unfiled') {
      box.classList.add('is-cards');
      box.innerHTML = unfiled.length
        ? unfiled.map(renderInfoDocCard).join('')
        : '<p class="muted">No unfiled documents.</p>';
      refreshMobileListUi();
      return;
    }

    if (folderFilter) {
      const root = infoFoldersCache.find((f) => f.id === folderFilter);
      box.classList.remove('is-cards');
      if (!root) {
        box.classList.add('is-cards');
        box.innerHTML = infoDocsCache.map(renderInfoDocCard).join('') || '<p class="muted">No documents in this folder.</p>';
        refreshMobileListUi();
        return;
      }
      const html = renderInfoFolderSection(root, docsByFolder, 0);
      box.innerHTML = html || '<p class="muted">No documents in this folder.</p>';
      refreshMobileListUi();
      return;
    }

    box.classList.remove('is-cards');
    const roots = infoFoldersSortedTree().filter((f) => !f.parentId);
    const sections = roots.map((f) => renderInfoFolderSection(f, docsByFolder, 0)).filter(Boolean);
    const known = new Set(infoFoldersCache.map((f) => f.id));
    const orphans = infoDocsCache.filter((d) => d.folderId && !known.has(d.folderId));
    if (unfiled.length || orphans.length) {
      sections.push(`
        <section class="info-folder-section" data-folder="unfiled">
          <header class="info-folder-head">
            <div class="info-folder-head-row">
              <h3>Unfiled</h3>
            </div>
            <p class="muted">${unfiled.length + orphans.length} document${(unfiled.length + orphans.length) === 1 ? '' : 's'}</p>
          </header>
          <div class="info-folder-docs">${[...unfiled, ...orphans].map(renderInfoDocCard).join('')}</div>
        </section>`);
    }
    box.innerHTML = sections.join('') || '<p class="muted">No documents yet.</p>';
    refreshMobileListUi();
  }

  async function consumeInfoDeepLink() {
    const link = infoDeepLink || parseInfoDeepLink(location.hash) || readPendingInfo({ consume: false });
    infoDeepLink = null;
    if (!link || link.type === 'panel') return;
    if (link.type === 'folder') {
      const filter = el('infoFolderFilter');
      if (filter && [...filter.options].some((o) => o.value === link.id)) {
        if (filter.value !== link.id) {
          filter.value = link.id;
          await loadInfoCentre({ skipDeepLink: true });
        }
      }
      const section = document.querySelector(`.info-folder-section[data-folder="${CSS.escape(link.id)}"]`);
      section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      readPendingInfo({ consume: true });
      return;
    }
    if (link.type === 'doc') {
      let doc = infoDocsCache.find((d) => d.id === link.id);
      if (!doc) {
        try {
          const data = await api(`/api/rwa/info-centre/${encodeURIComponent(link.id)}`);
          doc = data.document || data.doc || null;
        } catch (_err) {
          doc = null;
        }
      }
      if (!doc) {
        window.alert('Document not found or not available to your account.');
        return;
      }
      try {
        await openInfoDocument(doc);
        readPendingInfo({ consume: true });
      } catch (err) {
        window.alert(err.message || 'Could not open document');
      }
    }
  }

  async function loadInfoCentre(opts = {}) {
    if (el('infoManageBlock')) el('infoManageBlock').hidden = !hasEntitlement('manage_info');
    if (hasEntitlement('manage_info')) {
      ensureInfoAccessCandidates().then(() => {
        syncInfoDocAccessPicker();
        syncInfoFolderNewAccessPicker();
        if (el('infoDocAccessList') && !(el('infoDocAccessList').children || []).length) {
          renderInfoAccessList(el('infoDocAccessList'), { selectedIds: [] }).catch(() => {});
        }
        if (el('infoFolderNewAccessList') && !(el('infoFolderNewAccessList').children || []).length) {
          renderInfoAccessList(el('infoFolderNewAccessList'), { selectedIds: [] }).catch(() => {});
        }
      }).catch(() => {});
    }
    const status = hasEntitlement('manage_info')
      ? (el('infoStatusFilter')?.value || 'published')
      : 'published';
    const category = el('infoCategoryFilter')?.value || '';
    const folder = el('infoFolderFilter')?.value || '';
    const qs = new URLSearchParams({ status });
    if (category) qs.set('category', category);
    if (folder) qs.set('folderId', folder);
    const data = await api(`/api/rwa/info-centre?${qs.toString()}`);
    fillInfoCategorySelects(data.categories || []);
    fillInfoFolderSelects(data.folders || []);
    if (folder && el('infoFolderFilter') && [...el('infoFolderFilter').options].some((o) => o.value === folder)) {
      el('infoFolderFilter').value = folder;
    }
    infoDocsCache = data.documents || [];
    if (data.features && typeof data.features.infoCentreProtect === 'boolean') {
      setInfoCentreProtectFeature(data.features.infoCentreProtect);
    }
    renderInfoDocs();
    if (sectionLang.info === 'hi') renderInfoOverlay();
    if (!opts.skipDeepLink) await consumeInfoDeepLink();
  }

  async function openInfoDocument(doc, { lang = 'en' } = {}) {
    if (!doc?.id) return;
    const protect = isInfoCentreProtectEnforced();
    if (protect) bindInfoCentreProtectOnce();

    // Web-link documents: load the URL inline in the portal viewer (HTML/PDF/image).
    if (doc.docType === 'link') {
      const linkRaw = String(doc.externalUrl || '').trim();
      if (!linkRaw) throw new Error('Web link missing');
      const abs = resolveDocLinkUrl(linkRaw);
      const mime = doc.mimeType
        || (/\.pdf(\?|#|$)/i.test(abs) ? 'application/pdf'
          : /\.(jpe?g|png|webp|gif)(\?|#|$)/i.test(abs) ? 'image/*'
            : 'text/html');
      const { isHtml, isPdf, isImage, effectiveMime } = docViewerMimeGuess(
        mime,
        abs,
        doc.title || '',
      );
      const sameOrigin = abs.startsWith(window.location.origin);
      const fileApi = `/api/rwa/info-centre/${encodeURIComponent(doc.id)}/file`;
      // Same-site HTML: iframe the page itself for layout; use file API when protect is on
      // so download can be refused for members.
      const viewUrl = (isHtml && sameOrigin && !protect)
        ? abs
        : (sameOrigin ? authDocUrl(fileApi) : abs);
      showDocViewerSource(viewUrl, {
        title: doc.title || 'Document',
        filename: doc.originalName || linkRaw,
        mime: effectiveMime || mime,
        isBlob: false,
        downloadUrl: protect ? '' : (sameOrigin ? authDocUrl(fileApi, { download: '1' }) : abs),
        newTabUrl: protect ? '' : abs,
        keepLoading: true,
        protectContent: protect,
      });
      return;
    }

    const qs = lang === 'hi' ? '?lang=hi' : '';
    const url = `/api/rwa/info-centre/${encodeURIComponent(doc.id)}/file${qs}`;
    const isHtml = doc.docType === 'html'
      || String(doc.mimeType || '').toLowerCase().includes('html')
      || /\.html?$/i.test(doc.originalName || doc.filename || '');
    const filename = doc.originalName
      || (isHtml ? `${doc.title || 'document'}.html` : `${doc.title || 'document'}.pdf`);
    // HTML (authored or uploaded file): always stream into the iframe as a live page.
    if (isHtml) {
      const viewUrl = authDocUrl(url);
      showDocViewerSource(viewUrl, {
        title: doc.title || doc.originalName || 'Document',
        filename,
        mime: 'text/html',
        isBlob: false,
        downloadUrl: protect ? '' : authDocUrl(url, { download: '1' }),
        newTabUrl: protect ? '' : viewUrl,
        keepLoading: true,
        protectContent: protect,
      });
      return;
    }
    await openDocViewerFromAuthUrl(url, {
      title: doc.title || doc.originalName || 'Document',
      filename,
      mime: doc.mimeType || 'application/pdf',
      protectContent: protect,
    });
  }

  async function saveInfoDocument(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_info')) return;
    const statusLine = el('infoFormStatus');
    const saveBtn = el('infoSaveBtn');
    const title = String(el('infoTitleInput')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title required.';
      return;
    }
    const source = document.querySelector('input[name="infoSource"]:checked')?.value || 'file';
    const editId = String(el('infoEditId')?.value || '').trim();
    const statusVal = el('infoStatusInput')?.value || 'published';
    const audienceVal = el('infoAudienceInput')?.value || 'all';
    const allowedMemberIds = audienceVal === 'restricted'
      ? selectedInfoAccessIds(el('infoDocAccessList'))
      : [];
    if (audienceVal === 'restricted' && !allowedMemberIds.length) {
      if (statusLine) statusLine.textContent = 'Select at least one member for restricted access.';
      return;
    }
    if (statusVal === 'published') {
      if (!confirmInfoPublish(title, audienceVal)) return;
    }
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      let doc;
      const commonFields = {
        title,
        titleHi: el('infoTitleHiInput')?.value.trim() || '',
        summary: el('infoSummaryInput')?.value.trim() || '',
        summaryHi: el('infoSummaryHiInput')?.value.trim() || '',
        category: el('infoCategoryInput')?.value || 'general',
        folderId: el('infoFolderInput')?.value || '',
        status: statusVal,
        audience: audienceVal,
        allowedMemberIds,
      };
      if (source === 'html') {
        const htmlBody = infoComposerHtml('en');
        if (!htmlBody && !editId) {
          if (statusLine) statusLine.textContent = 'Write the document, or switch to file upload / web link.';
          return;
        }
        const payload = { ...commonFields, docType: 'html' };
        if (htmlBody) payload.htmlBody = htmlBody;
        const htmlBodyHi = infoComposerHtml('hi');
        if (htmlBodyHi || el('infoHtmlHiInput')?.value === '' || (infoComposeHi && infoComposeHi.isEmpty())) {
          if (htmlBodyHi || editId) payload.htmlBodyHi = htmlBodyHi;
        }
        if (editId) {
          doc = (await api(`/api/rwa/info-centre/${encodeURIComponent(editId)}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
          })).document;
        } else {
          doc = (await api('/api/rwa/info-centre', {
            method: 'POST',
            body: JSON.stringify(payload),
          })).document;
        }
      } else if (source === 'link') {
        const externalUrl = String(el('infoLinkInput')?.value || '').trim();
        if (!externalUrl && !editId) {
          if (statusLine) statusLine.textContent = 'Paste a web link (HTML, PDF, or image URL).';
          return;
        }
        const payload = { ...commonFields, docType: 'link' };
        if (externalUrl) payload.externalUrl = externalUrl;
        if (editId) {
          doc = (await api(`/api/rwa/info-centre/${encodeURIComponent(editId)}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
          })).document;
        } else {
          doc = (await api('/api/rwa/info-centre', {
            method: 'POST',
            body: JSON.stringify(payload),
          })).document;
        }
      } else {
        const file = el('infoFileInput')?.files?.[0];
        if (!file && !editId) {
          if (statusLine) statusLine.textContent = 'Choose a file to upload.';
          return;
        }
        if (file) {
          const body = new FormData();
          body.append('file', file);
          body.append('title', title);
          body.append('summary', el('infoSummaryInput')?.value.trim() || '');
          body.append('titleHi', el('infoTitleHiInput')?.value.trim() || '');
          body.append('summaryHi', el('infoSummaryHiInput')?.value.trim() || '');
          body.append('category', el('infoCategoryInput')?.value || 'general');
          body.append('folderId', el('infoFolderInput')?.value || '');
          body.append('status', statusVal);
          body.append('audience', audienceVal);
          body.append('allowedMemberIds', JSON.stringify(allowedMemberIds));
          body.append('docType', 'file');
          if (editId) body.append('id', editId);
          const headers = {};
          if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
          const path = editId
            ? `/api/rwa/info-centre/${encodeURIComponent(editId)}`
            : '/api/rwa/info-centre';
          const res = await fetch(path, {
            method: editId ? 'PATCH' : 'POST',
            credentials: 'same-origin',
            headers,
            body,
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(data.error || res.statusText || 'Upload failed');
          doc = data.document;
        } else {
          doc = (await api(`/api/rwa/info-centre/${encodeURIComponent(editId)}`, {
            method: 'PATCH',
            body: JSON.stringify(commonFields),
          })).document;
        }
      }
      resetInfoForm();
      if (statusLine) {
        const aud = doc?.audience || audienceVal;
        statusLine.textContent = doc?.status === 'published'
          ? (aud === 'ec'
            ? 'Published to EC only.'
            : aud === 'restricted'
              ? 'Published to selected members.'
              : 'Published to all members.')
          : 'Saved as draft.';
      }
      await loadInfoCentre();
    } catch (err) {
      if (statusLine) statusLine.textContent = err.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function createInfoFolder({ parentId = '', title: titleArg = '' } = {}) {
    if (!hasEntitlement('manage_info')) return;
    const title = String(titleArg || el('infoFolderNewTitle')?.value || '').trim();
    const parent = String(parentId || el('infoFolderNewParent')?.value || '').trim();
    const audience = el('infoFolderNewAudience')?.value || 'all';
    const allowedMemberIds = audience === 'restricted'
      ? selectedInfoAccessIds(el('infoFolderNewAccessList'))
      : [];
    const status = el('infoFolderManageStatus');
    if (title.length < 2) {
      if (status) status.textContent = 'Folder name required.';
      return;
    }
    if (audience === 'restricted' && !allowedMemberIds.length) {
      if (status) status.textContent = 'Select at least one member for restricted folder access.';
      return;
    }
    if (status) status.textContent = 'Creating…';
    try {
      await api('/api/rwa/info-centre/folders', {
        method: 'POST',
        body: JSON.stringify({
          title,
          parentId: parent || null,
          audience,
          allowedMemberIds,
        }),
      });
      if (el('infoFolderNewTitle')) el('infoFolderNewTitle').value = '';
      if (el('infoFolderNewParent')) el('infoFolderNewParent').value = '';
      if (el('infoFolderNewAudience')) el('infoFolderNewAudience').value = 'all';
      if (el('infoFolderNewAccessSearch')) el('infoFolderNewAccessSearch').value = '';
      syncInfoFolderNewAccessPicker();
      renderInfoAccessList(el('infoFolderNewAccessList'), { selectedIds: [] }).catch(() => {});
      if (status) status.textContent = parent ? 'Subfolder created.' : 'Folder created.';
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not create folder';
    }
  }

  async function renameInfoFolder(folderId) {
    if (!hasEntitlement('manage_info') || !folderId) return;
    const folder = infoFoldersCache.find((f) => f.id === folderId);
    const next = prompt('Rename folder', folder?.title || '');
    if (next == null) return;
    const title = String(next).trim();
    if (title.length < 2) {
      alert('Folder name required.');
      return;
    }
    const status = el('infoFolderManageStatus');
    try {
      await api(`/api/rwa/info-centre/folders/${encodeURIComponent(folderId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      });
      if (status) status.textContent = 'Folder renamed.';
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      alert(err.message || 'Rename failed');
    }
  }

  async function moveInfoFolder(folderId) {
    if (!hasEntitlement('manage_info') || !folderId) return;
    const folder = infoFoldersCache.find((f) => f.id === folderId);
    if (!folder) return;
    const tree = infoFoldersSortedTree().filter((f) => f.id !== folderId);
    // Exclude self + descendants from choices (server also validates)
    const blocked = new Set([folderId]);
    const kids = new Map();
    for (const f of infoFoldersCache) {
      const pid = f.parentId || '';
      if (!kids.has(pid)) kids.set(pid, []);
      kids.get(pid).push(f.id);
    }
    const stack = [folderId];
    while (stack.length) {
      const cur = stack.pop();
      for (const k of (kids.get(cur) || [])) {
        blocked.add(k);
        stack.push(k);
      }
    }
    const choices = [{ id: '', label: 'Top level' }].concat(
      tree.filter((f) => !blocked.has(f.id)).map((f) => ({ id: f.id, label: f.pathLabel || f.title }))
    );
    const labels = choices.map((c, i) => `${i}: ${c.label}`).join('\n');
    const pick = prompt(
      `Move “${folder.title}” under which folder?\nEnter number:\n${labels}`,
      '0'
    );
    if (pick == null) return;
    const idx = Number(pick);
    if (!Number.isInteger(idx) || idx < 0 || idx >= choices.length) {
      alert('Invalid choice.');
      return;
    }
    const parentId = choices[idx].id || null;
    const status = el('infoFolderManageStatus');
    try {
      await api(`/api/rwa/info-centre/folders/${encodeURIComponent(folderId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ parentId }),
      });
      if (status) status.textContent = 'Folder moved.';
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      alert(err.message || 'Move failed');
    }
  }

  async function moveInfoDocument(docId) {
    if (!hasEntitlement('manage_info') || !docId) return;
    const doc = infoDocsCache.find((d) => d.id === docId);
    if (!doc) return;
    const tree = infoFoldersSortedTree();
    const choices = [{ id: '', label: 'Unfiled' }].concat(
      tree.map((f) => ({ id: f.id, label: f.pathLabel || f.title }))
    );
    const labels = choices.map((c, i) => `${i}: ${c.label}`).join('\n');
    const pick = prompt(
      `Move “${doc.title}” to which folder?\nEnter number:\n${labels}`,
      '0'
    );
    if (pick == null) return;
    const idx = Number(pick);
    if (!Number.isInteger(idx) || idx < 0 || idx >= choices.length) {
      alert('Invalid choice.');
      return;
    }
    try {
      await api(`/api/rwa/info-centre/${encodeURIComponent(docId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ folderId: choices[idx].id || '' }),
      });
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      alert(err.message || 'Move failed');
    }
  }

  async function deleteInfoFolder(folderId) {
    if (!hasEntitlement('manage_info') || !folderId) return;
    const folder = infoFoldersCache.find((f) => f.id === folderId);
    const n = folder?.docCount || 0;
    const childCount = infoFoldersCache.filter((f) => (f.parentId || '') === folderId).length;
    const msg = [
      `Delete folder “${folder?.title || folderId}”?`,
      n ? `Its ${n} document${n === 1 ? '' : 's'} will move to the parent folder (or Unfiled).` : '',
      childCount ? `Its ${childCount} subfolder${childCount === 1 ? '' : 's'} will move up one level.` : '',
    ].filter(Boolean).join('\n');
    if (!confirm(msg)) return;
    const status = el('infoFolderManageStatus');
    try {
      await api(`/api/rwa/info-centre/folders/${encodeURIComponent(folderId)}`, {
        method: 'DELETE',
      });
      if (status) status.textContent = 'Folder deleted.';
      const filter = el('infoFolderFilter');
      if (filter && filter.value === folderId) filter.value = '';
      await loadInfoCentre({ skipDeepLink: true });
    } catch (err) {
      alert(err.message || 'Delete failed');
    }
  }

  function trackPanel(name) {
    if (!state.session?.token || !name) return;
    // Fire-and-forget; do not block navigation if logging fails.
    api('/api/rwa/observability/event', {
      method: 'POST',
      body: JSON.stringify({ panel: name }),
    }).catch(() => {});
  }

  function scrollActiveTabIntoView() {
    const nav = document.querySelector('.tabs');
    const active = nav?.querySelector('.tab.is-active');
    if (!nav || !active) return;
    const navRect = nav.getBoundingClientRect();
    const tabRect = active.getBoundingClientRect();
    if (tabRect.left < navRect.left + 4 || tabRect.right > navRect.right - 4) {
      active.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
    }
  }

  function stopMsgPolling() {
    if (state.msgPollTimer) {
      clearInterval(state.msgPollTimer);
      state.msgPollTimer = null;
    }
  }

  function updateMessagesBadge(total) {
    const badge = el('messagesTabBadge');
    if (!badge) return;
    const n = Number(total) || 0;
    if (n > 0) {
      badge.hidden = false;
      badge.textContent = n > 99 ? '99+' : String(n);
    } else {
      badge.hidden = true;
      badge.textContent = '';
    }
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function refreshPushUi() {
    const statusEl = el('pushStatusText');
    const enableBtn = el('pushEnableBtn');
    const disableBtn = el('pushDisableBtn');
    const testBtn = el('pushTestBtn');
    if (!state.session) return;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      if (statusEl) statusEl.textContent = 'Push is not supported in this browser.';
      if (enableBtn) enableBtn.hidden = true;
      return;
    }
    try {
      const data = await api('/api/rwa/push/status');
      const perm = Notification.permission;
      if (statusEl) {
        statusEl.textContent = data.subscribed
          ? `Push enabled on ${data.deviceCount} device(s). Browser permission: ${perm}.`
          : `Push not enabled on this device. Browser permission: ${perm}.`;
      }
      if (enableBtn) enableBtn.hidden = Boolean(data.subscribed) && perm === 'granted';
      if (disableBtn) disableBtn.hidden = !data.subscribed;
      if (testBtn) testBtn.hidden = !data.subscribed;
      const prefs = data.prefs || {};
      document.querySelectorAll('#pushPrefsFields [data-pref]').forEach((input) => {
        const key = input.getAttribute('data-pref');
        input.checked = prefs[key] !== false;
      });
      const hint = el('pushCertPrefsHint');
      if (hint) {
        const issuesNd = hasEntitlement('issue_no_dues');
        const issuesNoc = hasEntitlement('issue_no_objection');
        if (issuesNd || issuesNoc) {
          const bits = [];
          if (issuesNd) bits.push('No Dues');
          if (issuesNoc) bits.push('No Objection');
          hint.textContent =
            `You can issue ${bits.join(' and ')} certificates — keep those alert types on so you are notified when a resident raises a request. Residents are alerted when a certificate is issued, rejected, or sent back.`;
        } else {
          hint.textContent =
            'Issuers with the No Dues / No Objection entitlement are alerted when a resident raises a request. Residents are alerted when a certificate is issued, rejected, or sent back.';
        }
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = e.message || 'Could not load push status';
    }
  }

  async function enablePush() {
    const statusEl = el('pushStatusText');
    try {
      if (!('Notification' in window) || !('serviceWorker' in navigator)) {
        throw new Error('Push is not supported here');
      }
      const perm = await Notification.requestPermission();
      if (perm !== 'granted') throw new Error('Notification permission denied');
      const keyData = await api('/api/rwa/push/vapid-public-key');
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(keyData.publicKey),
        });
      }
      await api('/api/rwa/push/subscribe', {
        method: 'POST',
        body: JSON.stringify({ subscription: sub.toJSON() }),
      });
      if (statusEl) statusEl.textContent = 'Push enabled on this device.';
      await refreshPushUi();
    } catch (e) {
      if (statusEl) statusEl.textContent = e.message || 'Could not enable push';
    }
  }

  async function disablePush() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api('/api/rwa/push/unsubscribe', {
          method: 'POST',
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      } else {
        await api('/api/rwa/push/unsubscribe', { method: 'POST', body: JSON.stringify({}) });
      }
      await refreshPushUi();
    } catch (e) {
      if (el('pushStatusText')) el('pushStatusText').textContent = e.message || 'Could not disable';
    }
  }

  async function savePushPrefs() {
    const prefs = {};
    document.querySelectorAll('#pushPrefsFields [data-pref]').forEach((input) => {
      prefs[input.getAttribute('data-pref')] = Boolean(input.checked);
    });
    try {
      await api('/api/rwa/push/prefs', { method: 'PUT', body: JSON.stringify({ prefs }) });
      if (el('pushPrefsStatus')) el('pushPrefsStatus').textContent = 'Preferences saved.';
    } catch (e) {
      if (el('pushPrefsStatus')) el('pushPrefsStatus').textContent = e.message || 'Save failed';
    }
  }

  async function refreshMsgThreads() {
    const data = await api('/api/rwa/messages/threads');
    state.msgThreads = data.threads || [];
    updateMessagesBadge(data.unreadTotal);
    renderMsgThreadList();
  }

  function renderMsgThreadList() {
    const box = el('msgThreadList');
    if (!box) return;
    if (!state.msgThreads.length) {
      box.innerHTML = '<p class="muted">No conversations yet.</p>';
      return;
    }
    box.innerHTML = state.msgThreads.map((t) => {
      const active = t.id === state.msgActiveThreadId ? ' is-active' : '';
      const unread = t.unread ? `<span class="msg-unread">${t.unread} new</span>` : '';
      let preview = 'No messages yet';
      if (t.lastMessage) {
        preview = `${escapeHtml(t.lastMessage.authorName || '')}: ${escapeHtml(t.lastMessage.body || '')}`;
      } else if (t.kind === 'colony') {
        preview = 'Colony channel';
      } else if (t.kind === 'ai') {
        preview = 'Private assistant';
      } else if (t.kind === 'group') {
        const n = Number(t.memberCount || 0);
        preview = `Private channel · ${n} ${n === 1 ? 'person' : 'people'}`;
      }
      const official = t.kind === 'group' && t.isOfficial
        ? '<span class="msg-official-badge">Official</span>'
        : '';
      let avatarPerson = { photoUrl: '' };
      if (t.kind === 'dm' && t.peerPhotoUrl) avatarPerson = { photoUrl: t.peerPhotoUrl };
      else if (t.lastMessage?.photoUrl) avatarPerson = { photoUrl: t.lastMessage.photoUrl };
      let avatar;
      if (t.kind === 'ai') {
        avatar = aiAvatarHtml({ size: 'sm', className: 'msg-thread-avatar' });
      } else if (t.kind === 'group' && t.iconUrl) {
        avatar = `<img class="msg-thread-avatar msg-group-icon" src="${escapeHtml(t.iconUrl)}" alt="">`;
      } else if (t.kind === 'group') {
        avatar = `<span class="msg-thread-avatar msg-group-avatar" aria-hidden="true">${escapeHtml((t.title || 'C').slice(0, 1).toUpperCase())}</span>`;
      } else {
        avatar = personAvatarHtml(avatarPerson, { size: 'sm', className: 'msg-thread-avatar' });
      }
      return `<button type="button" class="msg-thread-item${active}${t.kind === 'ai' ? ' is-ai-thread' : ''}${t.kind === 'group' ? ' is-group-thread' : ''}" data-thread-id="${escapeHtml(t.id)}">
        ${avatar}
        <span class="msg-thread-copy">
          <strong>${official}${escapeHtml(t.title || t.id)}</strong>
          <span class="msg-preview">${preview}</span>
          ${unread}
        </span>
      </button>`;
    }).join('');
    hydrateAvatars(box).catch(() => {});
  }

  function msgThemeIconSvg(theme) {
    const icons = {
      notice: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><circle cx="12" cy="16.5" r="0.8" fill="currentColor" stroke="none"/></svg>',
      urgent: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 3l9 16H3L12 3z"/><path d="M12 10v4"/><circle cx="12" cy="16.5" r="0.8" fill="currentColor" stroke="none"/></svg>',
      celebrate: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01M15 9h.01"/><circle cx="12" cy="12" r="9"/></svg>',
      official: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 2l2.2 4.5 5 .7-3.6 3.5.9 5L12 13.8 7.5 15.7l.9-5L4.8 7.2l5-.7L12 2z"/></svg>',
      thanks: '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 21s-7-4.35-9.5-8.1C.7 10.1 1.5 6.8 4.4 5.4 6.5 4.4 9 5 12 7.4c3-2.4 5.5-3 7.6-2 2.9 1.4 3.7 4.7 1.9 7.5C19 16.65 12 21 12 21z"/></svg>',
    };
    return icons[theme] || '';
  }

  function setMsgCardTheme(theme) {
    const next = (theme || 'plain').trim() || 'plain';
    const input = el('msgCardTheme');
    if (input) input.value = next;
    document.querySelectorAll('#msgCardThemeWrap .msg-theme-chip').forEach((btn) => {
      const on = btn.getAttribute('data-theme') === next;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function renderMsgHeadAvatar(thread) {
    const box = el('msgHeadAvatar');
    if (!box) return;
    if (!thread || !thread.kind) {
      box.hidden = true;
      box.innerHTML = '';
      box.classList.remove('is-round');
      return;
    }
    box.hidden = false;
    box.classList.toggle('is-round', thread.kind === 'dm' || thread.kind === 'ai');
    if (thread.kind === 'ai') {
      box.innerHTML = aiAvatarHtml({ size: 'sm', className: 'msg-head-ai' });
      return;
    }
    if (thread.kind === 'group' && thread.iconUrl) {
      box.innerHTML = `<img src="${escapeHtml(thread.iconUrl)}" alt="">`;
      return;
    }
    if (thread.kind === 'group') {
      box.textContent = String(thread.title || 'C').slice(0, 1).toUpperCase();
      return;
    }
    if (thread.kind === 'dm') {
      if (thread.peerPhotoUrl) {
        box.innerHTML = personAvatarHtml({ photoUrl: thread.peerPhotoUrl }, { size: 'sm', className: 'msg-head-peer' });
        hydrateAvatars(box).catch(() => {});
      } else {
        box.textContent = String(thread.title || '?').slice(0, 1).toUpperCase();
      }
      return;
    }
    if (thread.kind === 'colony') {
      box.textContent = 'C';
      return;
    }
    box.textContent = String(thread.title || '?').slice(0, 1).toUpperCase();
  }

  function renderMsgFeed(messages, { append = false } = {}) {
    const feed = el('msgFeed');
    if (!feed) return;
    let list = messages || [];
    if (append) {
      const seen = new Set(
        [...feed.querySelectorAll('.msg-row[data-msg-id]')].map((n) => n.getAttribute('data-msg-id'))
      );
      list = list.filter((m) => m && m.id && !seen.has(m.id));
      if (!list.length) return;
    }
    const myHouse = state.session?.resident?.houseId;
    const myMember = state.session?.resident?.memberId;
    const canEditBoard = !isViewOnly() && !state.msgIsAiThread;
    const html = list.map((m) => {
      if (m.hidden && !state.msgCanModerate) {
        return `<article class="msg-row is-hidden" data-msg-id="${escapeHtml(m.id)}"><div class="msg-bubble is-hidden"><div class="msg-body">Message hidden by moderators</div></div></article>`;
      }
      const mine = (m.authorMemberId && m.authorMemberId === myMember)
        || (!m.authorMemberId && m.houseId === myHouse && !m.isAi);
      const isAi = Boolean(m.isAi);
      const atts = (m.attachments || []).map((a) => {
        const label = escapeHtml(a.originalName || 'Attachment');
        const mime = escapeHtml(a.mime || '');
        if ((a.mime || '').startsWith('image/')) {
          return `<button type="button" class="msg-att-open is-image doc-open" data-url="${escapeHtml(a.url)}" data-title="${label}" data-filename="${label}" data-mime="${mime}"><img src="${escapeHtml(a.url)}" alt=""></button>`;
        }
        return `<button type="button" class="btn ghost compact doc-open" data-url="${escapeHtml(a.url)}" data-title="${label}" data-filename="${label}" data-mime="${mime}">${label}</button>`;
      }).join('');
      let mods = '';
      if (state.msgCanModerate && !m.hidden && !isAi) {
        mods = `<div class="msg-mod-actions">
          <button type="button" class="btn ghost compact msg-mod" data-action="hide" data-id="${escapeHtml(m.id)}">Hide</button>
          <button type="button" class="btn ghost compact msg-mod" data-action="pin" data-id="${escapeHtml(m.id)}">Pin</button>
          <button type="button" class="btn ghost compact msg-mod" data-action="delete" data-id="${escapeHtml(m.id)}">Delete</button>
        </div>`;
      } else if (state.msgCanModerate && m.hidden) {
        mods = `<div class="msg-mod-actions">
          <button type="button" class="btn ghost compact msg-mod" data-action="unhide" data-id="${escapeHtml(m.id)}">Unhide</button>
        </div>`;
      }
      const authorActions = (mine && canEditBoard && !m.hidden && !isAi)
        ? `<div class="msg-author-actions">
            <button type="button" class="btn ghost compact msg-edit" data-msg-edit="${escapeHtml(m.id)}">Edit</button>
            <button type="button" class="btn ghost compact msg-delete-own" data-msg-delete="${escapeHtml(m.id)}">Delete</button>
          </div>`
        : '';
      const likeCount = Number(m.likeCount || 0);
      const liked = Boolean(m.likedByMe);
      const likeBtn = (!isAi && !m.hidden)
        ? `<button type="button" class="msg-like${liked ? ' is-active' : ''}" data-msg-like="${escapeHtml(m.id)}" aria-pressed="${liked ? 'true' : 'false'}" title="${isViewOnly() ? 'View-only' : (liked ? 'Unlike' : 'Like')}"${isViewOnly() ? ' disabled' : ''}>
            <svg viewBox="0 0 24 24" width="15" height="15" fill="${liked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-4.35-9.5-8.1C.7 10.1 1.5 6.8 4.4 5.4 6.5 4.4 9 5 12 7.4c3-2.4 5.5-3 7.6-2 2.9 1.4 3.7 4.7 1.9 7.5C19 16.65 12 21 12 21z"/></svg>
            <span class="msg-like-count">${likeCount}</span>
          </button>`
        : '';
      const avatar = isAi
        ? aiAvatarHtml({ size: 'sm', className: 'msg-avatar' })
        : personAvatarHtml({ photoUrl: m.photoUrl || '' }, { size: 'sm', className: 'msg-avatar' });
      const editedBit = m.editedAt ? ' · edited' : '';
      const who = isAi
        ? 'RWA Assistant · only you see this'
        : `${escapeHtml(m.houseId || '')} · ${escapeHtml(m.authorName || '')}`;
      const theme = (m.cardTheme || '').trim();
      const themeClass = theme && theme !== 'plain' ? ` theme-${escapeHtml(theme)}` : '';
      const themeLabel = escapeHtml(m.cardThemeLabel || theme || '');
      const themeBadge = (theme && theme !== 'plain' && msgThemeIconSvg(theme))
        ? `<span class="msg-card-theme-badge" title="${themeLabel}" aria-label="${themeLabel}">${msgThemeIconSvg(theme)}</span>`
        : '';
      return `<article class="msg-row${mine ? ' is-mine' : ''}${isAi ? ' is-ai' : ''}" data-msg-id="${escapeHtml(m.id)}">
        ${avatar}
        <div class="msg-bubble${mine ? ' is-mine' : ''}${m.hidden ? ' is-hidden' : ''}${isAi ? ' is-ai' : ''}${themeClass}">
          ${themeBadge}
          <div class="msg-meta">${who} · ${escapeHtml(formatIstDateTime(m.createdAt))}${editedBit}</div>
          <div class="msg-body">${escapeHtml(m.body || '')}</div>
          ${atts ? `<div class="msg-attachments">${atts}</div>` : ''}
          <div class="msg-footer">${likeBtn}${authorActions}${mods}</div>
        </div>
      </article>`;
    }).join('');
    if (append) feed.insertAdjacentHTML('beforeend', html);
    else feed.innerHTML = html || '<p class="muted">No messages yet. Say hello.</p>';
    feed.scrollTop = feed.scrollHeight;
    hydrateAvatars(feed).catch(() => {});
  }

  async function openMsgThread(threadId, { skipHash = false } = {}) {
    if (!threadId) return;
    state.msgActiveThreadId = threadId;
    el('msgLayout')?.classList.add('is-thread-open');
    if (el('msgBackBtn')) el('msgBackBtn').hidden = false;
    if (el('msgLeaveBar')) el('msgLeaveBar').hidden = false;
    if (el('msgComposeForm')) el('msgComposeForm').hidden = isViewOnly();
    renderMsgThreadList();
    const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(threadId)}?limit=80`);
    state.msgCanModerate = Boolean(data.canModerate);
    state.msgCanCleanup = Boolean(data.canCleanup);
    state.msgCanManage = Boolean(data.canManage);
    state.msgCanLeave = Boolean(data.canLeave);
    state.msgCanEscalate = Boolean(data.canEscalate);
    state.msgIsAiThread = Boolean(data.isAi || (data.thread && data.thread.kind === 'ai'));
    const thread = data.thread || {};
    state.msgActiveThread = thread;
    renderMsgHeadAvatar(thread);
    if (el('msgConversationTitle')) {
      el('msgConversationTitle').textContent = thread.title || 'Conversation';
    }
    const chip = el('msgOfficialChip');
    if (chip) {
      chip.hidden = !(thread.kind === 'group' && thread.isOfficial);
    }
    if (el('msgConversationMeta')) {
      if (thread.kind === 'ai') {
        el('msgConversationMeta').textContent = 'Private to you — answers are not shared with the colony';
      } else if (thread.kind === 'colony') {
        el('msgConversationMeta').textContent = 'Visible to all residents';
      } else if (thread.kind === 'group') {
        const n = Number(thread.memberCount || 0);
        const arch = thread.archivedAt ? ' · Archived' : '';
        el('msgConversationMeta').textContent = `Private channel · ${n} ${n === 1 ? 'person' : 'people'}${arch}`;
      } else {
        el('msgConversationMeta').textContent = `Private · plots ${thread.houseA || ''} & ${thread.houseB || ''}`;
      }
    }
    const tools = el('msgChannelTools');
    if (tools) {
      const showTools = state.msgCanCleanup || state.msgCanManage || state.msgCanLeave || state.msgCanEscalate;
      tools.hidden = !showTools;
      const moreMenu = el('msgMoreMenu');
      if (moreMenu) moreMenu.open = false;
      const setHidden = (id, hidden) => {
        if (el(id)) el(id).hidden = hidden;
      };
      setHidden('msgQuickMembersBtn', !state.msgCanManage);
      setHidden('msgQuickLookBtn', !state.msgCanManage);
      setHidden('msgManageRenameBtn', !state.msgCanManage);
      setHidden('msgManageOfficialBtn', !state.msgCanManage);
      setHidden('msgManageMembersBtn', !state.msgCanManage);
      setHidden('msgManageIconBtn', !state.msgCanManage);
      setHidden('msgManageBgBtn', !state.msgCanManage);
      setHidden('msgManageArchiveBtn', !state.msgCanManage);
      setHidden('msgLeaveChannelBtn', !state.msgCanLeave);
      setHidden('msgEscalateBtn', !state.msgCanEscalate || state.msgIsAiThread);
      if (el('msgManageOfficialBtn')) {
        el('msgManageOfficialBtn').textContent = thread.isOfficial ? 'Remove Official' : 'Mark Official';
      }
      if (el('msgManageArchiveBtn')) {
        el('msgManageArchiveBtn').textContent = thread.archivedAt ? 'Unarchive channel' : 'Archive channel';
      }
      const cleanupBtns = tools.querySelectorAll('[data-cleanup]');
      cleanupBtns.forEach((btn) => {
        const action = btn.getAttribute('data-cleanup');
        if (action === 'clear_hidden') {
          btn.hidden = !state.msgCanCleanup || thread.kind !== 'colony';
        } else {
          btn.hidden = !state.msgCanCleanup;
        }
      });
      const showCleanup = state.msgCanCleanup;
      setHidden('msgCleanupDivider', !showCleanup);
      setHidden('msgCleanupLabel', !showCleanup);
    }
    if (el('msgComposeForm')) {
      el('msgComposeForm').hidden = isViewOnly() || Boolean(thread.archivedAt && thread.kind === 'group');
    }
    const themeWrap = el('msgCardThemeWrap');
    if (themeWrap) {
      themeWrap.hidden = Boolean(state.msgIsAiThread) || thread.kind === 'dm';
      if (!themeWrap.hidden) setMsgCardTheme('plain');
    }
    applyMsgFeedBackground(thread);
    const attachLabel = document.querySelector('.msg-attach-label');
    if (attachLabel) attachLabel.hidden = Boolean(state.msgIsAiThread);
    if (el('msgAttachHint')) {
      el('msgAttachHint').hidden = Boolean(state.msgIsAiThread);
      if (!state.msgIsAiThread && !state.msgAttachFiles.length) setMsgAttachHint(MSG_ATTACH_HINT_DEFAULT);
    }
    if (el('msgEmojiBtn')) el('msgEmojiBtn').hidden = false;
    if (el('msgBodyInput')) {
      el('msgBodyInput').placeholder = state.msgIsAiThread
        ? 'Ask about your dues, EC members, concerns, notices…'
        : 'Write a message…';
    }
    const pin = el('msgPinned');
    if (pin) {
      if (data.pinned && data.pinned.body) {
        pin.hidden = false;
        pin.textContent = `Pinned: ${data.pinned.body}`;
      } else {
        pin.hidden = true;
        pin.textContent = '';
      }
    }
    renderMsgFeed(data.messages || []);
    const msgs = data.messages || [];
    state.msgLastId = msgs.length ? msgs[msgs.length - 1].id : null;
    await api(`/api/rwa/messages/threads/${encodeURIComponent(threadId)}/read`, {
      method: 'POST',
      body: JSON.stringify({ messageId: state.msgLastId }),
    }).catch(() => {});
    await refreshMsgThreads().catch(() => {});
    if (!skipHash) {
      history.replaceState(null, '', `#messages/${threadId}`);
    }
    stopMsgPolling();
    state.msgPollTimer = setInterval(() => pollMsgThread().catch(() => {}), 4000);
  }

  async function pollMsgThread() {
    if (!state.msgActiveThreadId || state.msgSending) return;
    const q = state.msgLastId ? `?since=${encodeURIComponent(state.msgLastId)}&limit=50` : '?limit=50';
    const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}${q}`);
    const msgs = data.messages || [];
    if (!msgs.length) return;
    if (state.msgLastId) renderMsgFeed(msgs, { append: true });
    else renderMsgFeed(msgs);
    state.msgLastId = msgs[msgs.length - 1].id;
    await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/read`, {
      method: 'POST',
      body: JSON.stringify({ messageId: state.msgLastId }),
    }).catch(() => {});
    await refreshMsgThreads().catch(() => {});
  }

  async function loadMessagesPanel() {
    if (el('msgNewChannelBtn')) el('msgNewChannelBtn').hidden = isViewOnly();
    await refreshMsgThreads();
    const hash = (location.hash || '').replace(/^#/, '');
    const m = hash.match(/^messages\/(.+)$/);
    if (m) {
      await openMsgThread(decodeURIComponent(m[1]), { skipHash: true });
    } else if (state.msgThreads[0]) {
      // Desktop: show colony by default; mobile stays on list until pick
      if (window.matchMedia('(min-width: 821px)').matches) {
        await openMsgThread(state.msgThreads[0].id, { skipHash: true });
      } else {
        el('msgLayout')?.classList.remove('is-thread-open');
        if (el('msgBackBtn')) el('msgBackBtn').hidden = true;
        if (el('msgLeaveBar')) el('msgLeaveBar').hidden = true;
        if (el('msgComposeForm')) el('msgComposeForm').hidden = true;
      }
    }
    refreshPushUi().catch(() => {});
  }

  async function sendMsgCompose(event) {
    event.preventDefault();
    if (state.msgSending) return;
    const status = el('msgComposeStatus');
    const body = (el('msgBodyInput')?.value || '').trim();
    if (!state.msgActiveThreadId) return;
    if (isViewOnly()) {
      if (status) status.textContent = 'View-only access cannot post.';
      return;
    }
    if (!body && !(state.msgAttachFiles || []).length) {
      if (status) status.textContent = state.msgIsAiThread ? 'Ask a question.' : 'Write a message or attach a file.';
      return;
    }
    state.msgSending = true;
    if (el('msgSendBtn')) el('msgSendBtn').disabled = true;
    try {
      if (status) status.textContent = state.msgIsAiThread ? 'Thinking…' : 'Sending…';
      const fd = new FormData();
      fd.append('body', body);
      const theme = (el('msgCardTheme')?.value || 'plain').trim();
      if (!state.msgIsAiThread && theme && theme !== 'plain') {
        fd.append('cardTheme', theme);
      }
      if (!state.msgIsAiThread) {
        for (const f of state.msgAttachFiles) fd.append('files', f);
      }
      const token = state.session?.token;
      const res = await fetch(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/messages`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: token ? { 'X-RWA-Token': token } : {},
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Send failed');
      if (el('msgBodyInput')) el('msgBodyInput').value = '';
      state.msgAttachFiles = [];
      if (el('msgAttachInput')) el('msgAttachInput').value = '';
      setMsgAttachHint(MSG_ATTACH_HINT_DEFAULT);
      if (el('msgEmojiPicker')) el('msgEmojiPicker').hidden = true;
      // Full refresh avoids poll race that duplicated AI replies
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      if (status) status.textContent = '';
    } catch (e) {
      if (status) status.textContent = e.message || 'Send failed';
    } finally {
      state.msgSending = false;
      if (el('msgSendBtn')) el('msgSendBtn').disabled = false;
    }
  }

  function formatRupee(amount) {
    const n = Number(amount);
    if (!Number.isFinite(n)) return '—';
    return `₹${n.toLocaleString('en-IN')}`;
  }

  const worksState = {
    meta: null,
    items: [],
    expandedId: null,
    editingId: null,
    quotesByWork: {},
    inviteWorkId: null,
  };

  const campaignsState = {
    meta: null,
    items: [],
    selected: null,
    tab: 'works',
    editingId: null,
  };

  function syncWorksPanelTabs() {
    const tab = campaignsState.tab || 'works';
    document.querySelectorAll('.works-panel-tab').forEach((btn) => {
      const on = btn.dataset.worksTab === tab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const worksPane = el('worksTabWorks');
    const campaignsPane = el('worksTabCampaigns');
    if (worksPane) worksPane.hidden = tab !== 'works';
    if (campaignsPane) campaignsPane.hidden = tab !== 'campaigns';
  }

  function fillWorksMetaSelects(meta) {
    const kindFilter = el('worksKindFilter');
    const kindInput = el('worksKindInput');
    const catInput = el('worksCategoryInput');
    const statusInput = el('worksStatusInput');
    if (kindFilter && meta?.kinds) {
      kindFilter.innerHTML = '<option value="">All types</option>'
        + meta.kinds.map((k) => `<option value="${escapeHtml(k.id)}">${escapeHtml(k.label)}</option>`).join('');
    }
    if (kindInput && meta?.kinds) {
      kindInput.innerHTML = meta.kinds.map((k) => `<option value="${escapeHtml(k.id)}">${escapeHtml(k.label)}</option>`).join('');
    }
    if (statusInput && meta?.statuses) {
      statusInput.innerHTML = meta.statuses.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.label)}</option>`).join('');
    }
    const kind = el('worksKindInput')?.value || meta?.kinds?.[0]?.id || 'maintenance';
    if (catInput && meta?.categories) {
      const cats = meta.categories[kind] || [];
      catInput.innerHTML = cats.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.label)}</option>`).join('');
    }
  }

  function fillWorksFundingRow(data = {}) {
    const sources = worksState.meta?.fundingSources || [];
    const row = document.createElement('div');
    row.className = 'works-row works-funding-row';
    row.innerHTML = `
      <label>Source
        <select class="wf-source">${sources.map((s) => `<option value="${escapeHtml(s.id)}"${s.id === (data.source || 'rwa_fund') ? ' selected' : ''}>${escapeHtml(s.label)}</option>`).join('')}</select>
      </label>
      <label>Amount (₹)
        <input class="wf-amount" type="number" min="0" step="1" value="${escapeHtml(String(data.amount ?? ''))}">
      </label>
      <label>Notes
        <input class="wf-notes" maxlength="240" value="${escapeHtml(data.notes || '')}">
      </label>
      <button type="button" class="btn ghost compact wf-remove">Remove</button>`;
    return row;
  }

  function fillWorksMilestoneRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'works-row works-milestone-row';
    row.innerHTML = `
      <label>Date <input class="wm-date" type="date" value="${escapeHtml(data.date || '')}"></label>
      <label class="span-2">Milestone <input class="wm-title" maxlength="160" value="${escapeHtml(data.title || '')}"></label>
      <label><input class="wm-done" type="checkbox"${data.done ? ' checked' : ''}> Done</label>
      <button type="button" class="btn ghost compact wm-remove">Remove</button>`;
    return row;
  }

  function collectWorksFunding() {
    return Array.from(document.querySelectorAll('.works-funding-row')).map((row) => ({
      source: row.querySelector('.wf-source')?.value || 'other',
      amount: row.querySelector('.wf-amount')?.value || '',
      notes: row.querySelector('.wf-notes')?.value.trim() || '',
    })).filter((f) => f.amount || f.notes);
  }

  function collectWorksMilestones() {
    return Array.from(document.querySelectorAll('.works-milestone-row')).map((row) => ({
      date: row.querySelector('.wm-date')?.value || '',
      title: row.querySelector('.wm-title')?.value.trim() || '',
      done: Boolean(row.querySelector('.wm-done')?.checked),
    })).filter((m) => m.title);
  }

  function resetWorksForm() {
    worksState.editingId = null;
    el('worksForm')?.reset();
    if (el('worksEditId')) el('worksEditId').value = '';
    if (el('worksFormTitle')) el('worksFormTitle').textContent = 'Initiate work / event';
    if (el('worksCancelEditBtn')) el('worksCancelEditBtn').hidden = true;
    if (el('worksCloseBtn')) el('worksCloseBtn').hidden = true;
    if (el('worksFundingList')) el('worksFundingList').innerHTML = '';
    if (el('worksMilestonesList')) el('worksMilestonesList').innerHTML = '';
    if (el('worksFormStatus')) el('worksFormStatus').textContent = '';
    fillWorksMetaSelects(worksState.meta || {});
  }

  function fillWorksForm(work) {
    if (!work) return;
    worksState.editingId = work.id;
    if (el('worksEditId')) el('worksEditId').value = work.id;
    if (el('worksFormTitle')) el('worksFormTitle').textContent = 'Edit work / event';
    if (el('worksCancelEditBtn')) el('worksCancelEditBtn').hidden = false;
    if (el('worksCloseBtn')) el('worksCloseBtn').hidden = !['in_progress', 'approved', 'planned', 'on_hold'].includes(work.status);
    if (el('worksTitleInput')) el('worksTitleInput').value = work.title || '';
    if (el('worksKindInput')) el('worksKindInput').value = work.kind || 'maintenance';
    fillWorksMetaSelects(worksState.meta || {});
    if (el('worksCategoryInput')) el('worksCategoryInput').value = work.category || 'other';
    if (el('worksStatusInput')) el('worksStatusInput').value = work.status || 'planned';
    if (el('worksVisibilityInput')) el('worksVisibilityInput').value = work.visibility || 'published';
    if (el('worksSummaryInput')) el('worksSummaryInput').value = work.summary || '';
    if (el('worksDetailsInput')) el('worksDetailsInput').value = work.details || '';
    if (el('worksBenefitsInput')) el('worksBenefitsInput').value = work.benefits || '';
    if (el('worksLocationInput')) el('worksLocationInput').value = work.location || '';
    if (el('worksAssignedInput')) el('worksAssignedInput').value = work.assignedTo || '';
    if (el('worksStartInput')) el('worksStartInput').value = work.startDate || '';
    if (el('worksEndInput')) el('worksEndInput').value = work.endDate || '';
    if (el('worksEventInput')) el('worksEventInput').value = work.eventDate || '';
    if (el('worksTimelineInput')) el('worksTimelineInput').value = work.timelineNotes || '';
    if (el('worksEstCostInput')) el('worksEstCostInput').value = work.estimatedCost ?? '';
    if (el('worksActCostInput')) el('worksActCostInput').value = work.actualCost ?? '';
    if (el('worksCostNotesInput')) el('worksCostNotesInput').value = work.costNotes || '';
    if (el('worksContractorNameInput')) el('worksContractorNameInput').value = work.contractorName || '';
    if (el('worksContractorContactInput')) el('worksContractorContactInput').value = work.contractorContact || '';
    if (el('worksContractorDetailsInput')) el('worksContractorDetailsInput').value = work.contractorDetails || '';
    const fundList = el('worksFundingList');
    if (fundList) {
      fundList.innerHTML = '';
      (work.funding || []).forEach((f) => fundList.appendChild(fillWorksFundingRow(f)));
    }
    const msList = el('worksMilestonesList');
    if (msList) {
      msList.innerHTML = '';
      (work.milestones || []).forEach((m) => msList.appendChild(fillWorksMilestoneRow(m)));
    }
    el('worksManageBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderWorksQuotesBlock(workId) {
    if (!hasEntitlement('manage_works')) return '';
    const pack = worksState.quotesByWork[workId];
    const loading = pack === undefined;
    const invites = pack?.invites || [];
    const responses = pack?.responses || [];
    const counts = pack?.counts || {};
    const responseRows = responses.length
      ? `<ul class="works-quote-list">${responses.map((r) => `
          <li>
            <strong>${escapeHtml(r.vendorName || r.vendorEmail || 'Vendor')}</strong>
            <span class="muted">${escapeHtml(r.vendorEmail || '')}${r.vendorPhone ? ' · ' + escapeHtml(r.vendorPhone) : ''}</span>
            ${r.amount != null ? `<span>${formatRupee(r.amount)}</span>` : ''}
            ${r.timeline ? `<span class="muted">${escapeHtml(r.timeline)}</span>` : ''}
            ${r.notes ? `<p>${escapeHtml(r.notes)}</p>` : ''}
          </li>`).join('')}</ul>`
      : '<p class="muted">No quotes received yet.</p>';
    const inviteRows = invites.length
      ? `<ul class="works-quote-invites muted">${invites.slice(0, 8).map((i) => `
          <li>${escapeHtml(i.vendorEmail)} · ${escapeHtml(i.status)}${i.emailError ? ' · send issue' : ''}</li>
        `).join('')}</ul>`
      : '';
    return `
      <div class="detail-block works-quotes-block" data-work-quotes="${escapeHtml(workId)}">
        <div class="roster-toolbar" style="margin:0 0 0.45rem">
          <strong>Quotes</strong>
          <button type="button" class="btn primary compact" data-work-invite-quotes="${escapeHtml(workId)}">Invite quotes</button>
        </div>
        <p class="muted" style="margin:0 0 0.45rem">
          ${loading ? 'Loading quotes…' : `${counts.responded || 0} response${(counts.responded || 0) === 1 ? '' : 's'} · ${counts.pending || 0} pending invite${(counts.pending || 0) === 1 ? '' : 's'}`}
        </p>
        ${loading ? '' : responseRows}
        ${loading ? '' : inviteRows}
      </div>`;
  }

  async function loadWorkQuotes(workId) {
    if (!workId || !hasEntitlement('manage_works')) return;
    try {
      const data = await api(`/api/rwa/works/${encodeURIComponent(workId)}/quotes`);
      worksState.quotesByWork[workId] = {
        invites: data.invites || [],
        responses: data.responses || [],
        counts: data.counts || {},
      };
    } catch (e) {
      worksState.quotesByWork[workId] = { invites: [], responses: [], counts: {}, error: e.message };
    }
    if (worksState.expandedId === workId) renderWorksList();
  }

  function openWorksQuoteInvite(workId) {
    const work = worksState.items.find((w) => w.id === workId);
    if (!work) return;
    worksState.inviteWorkId = workId;
    const dialog = el('worksQuoteInviteDialog');
    if (el('worksQuoteInviteWorkTitle')) {
      el('worksQuoteInviteWorkTitle').textContent = work.title || 'Work item';
    }
    if (el('worksQuoteInviteEmails')) el('worksQuoteInviteEmails').value = '';
    if (el('worksQuoteInviteMessage')) el('worksQuoteInviteMessage').value = '';
    if (el('worksQuoteInviteStatus')) el('worksQuoteInviteStatus').textContent = '';
    dialog?.showModal();
  }

  async function submitWorksQuoteInvite(event) {
    event.preventDefault();
    const workId = worksState.inviteWorkId;
    if (!workId) return;
    const statusLine = el('worksQuoteInviteStatus');
    const btn = el('worksQuoteInviteSubmitBtn');
    const emails = el('worksQuoteInviteEmails')?.value || '';
    const message = el('worksQuoteInviteMessage')?.value.trim() || '';
    if (btn) btn.disabled = true;
    if (statusLine) statusLine.textContent = 'Sending invites…';
    try {
      const data = await api(`/api/rwa/works/${encodeURIComponent(workId)}/quotes/invite`, {
        method: 'POST',
        body: JSON.stringify({ emails, message }),
      });
      worksState.quotesByWork[workId] = data.quotes || {
        invites: data.invites || [],
        responses: [],
        counts: {},
      };
      const sent = (data.invites || []).length;
      const failed = (data.invites || []).filter((i) => i.emailError || (i.emailDelivery && !i.emailDelivery.ok)).length;
      if (statusLine) {
        statusLine.textContent = failed
          ? `Invited ${sent}; ${failed} email(s) had delivery issues (link still created).`
          : `Sent ${sent} invite${sent === 1 ? '' : 's'}.`;
      }
      worksState.expandedId = workId;
      renderWorksList();
      setTimeout(() => el('worksQuoteInviteDialog')?.close(), 900);
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Invite failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function renderWorksList() {
    const list = el('worksList');
    const statusLine = el('worksListStatus');
    if (!list) return;
    const items = worksState.items || [];
    if (!items.length) {
      list.innerHTML = '<p class="muted">No works or events match these filters.</p>';
      if (statusLine) statusLine.textContent = '';
      return;
    }
    list.innerHTML = items.map((w) => {
      const expanded = worksState.expandedId === w.id;
      const milestones = (w.milestones || []).slice(0, 6);
      const canQuotes = hasEntitlement('manage_works') && ['maintenance', 'development'].includes(w.kind);
      return `
        <article class="works-card mobile-fold${expanded ? ' is-expanded' : ''}" data-work-id="${escapeHtml(w.id)}">
          <div class="meta">
            <span class="works-badge">${escapeHtml(w.kindLabel || w.kind || '')}</span>
            <span class="works-badge is-status-${escapeHtml(w.status || '')}">${escapeHtml(w.statusLabel || w.status || '')}</span>
            ${w.visibility === 'draft' ? '<span class="works-badge is-draft">Draft</span>' : ''}
            ${w.location ? ` · ${escapeHtml(w.location)}` : ''}
          </div>
          <h3>${escapeHtml(w.title || '')}</h3>
          ${w.summary ? `<p class="summary">${escapeHtml(w.summary)}</p>` : ''}
          ${expanded ? `
            ${w.details ? `<div class="detail-block"><strong>Details</strong>${escapeHtml(w.details)}</div>` : ''}
            ${w.benefits ? `<div class="detail-block"><strong>Benefits</strong>${escapeHtml(w.benefits)}</div>` : ''}
            ${w.estimatedCost != null ? `<div class="detail-block"><strong>Estimated cost</strong>${formatRupee(w.estimatedCost)}</div>` : ''}
            ${milestones.length ? `<div class="detail-block"><strong>Milestones</strong><ul class="works-milestone-list">${milestones.map((m) => `<li class="${m.done ? 'done' : ''}">${escapeHtml(m.date || '')} — ${escapeHtml(m.title || '')}</li>`).join('')}</ul></div>` : ''}
            ${canQuotes || hasEntitlement('manage_works') ? renderWorksQuotesBlock(w.id) : ''}
          ` : ''}
          <div class="btn-row">
            <button type="button" class="btn ghost compact" data-work-toggle="${escapeHtml(w.id)}">${expanded ? 'Less' : 'Details'}</button>
            ${hasEntitlement('manage_works') ? `<button type="button" class="btn secondary compact" data-work-edit="${escapeHtml(w.id)}">Edit</button>` : ''}
            ${hasEntitlement('manage_works') ? `<button type="button" class="btn primary compact" data-work-invite-quotes="${escapeHtml(w.id)}">Invite quotes</button>` : ''}
          </div>
        </article>`;
    }).join('');
    if (statusLine) statusLine.textContent = `${items.length} item${items.length === 1 ? '' : 's'}`;
    applyMobileListLimit(list, '.works-card.mobile-fold', 5);
  }

  async function loadWorks() {
    syncWorksPanelTabs();
    if (el('worksManageBlock')) {
      el('worksManageBlock').hidden = !hasEntitlement('manage_works');
    }
    const qs = new URLSearchParams();
    const kind = el('worksKindFilter')?.value || '';
    const status = el('worksStatusFilter')?.value ?? 'active';
    if (kind) qs.set('kind', kind);
    if (status) qs.set('status', status);
    if (hasEntitlement('manage_works')) {
      const visibility = el('worksVisibilityFilter')?.value || '';
      if (visibility) qs.set('visibility', visibility);
    }
    const statusLine = el('worksListStatus');
    if (statusLine) statusLine.textContent = 'Loading works…';
    const data = await api(`/api/rwa/works?${qs.toString()}`);
    worksState.meta = {
      kinds: data.kinds,
      categories: data.categories,
      statuses: data.statuses,
      fundingSources: data.fundingSources,
    };
    worksState.items = data.works || [];
    fillWorksMetaSelects(worksState.meta);
    renderWorksList();
    if (campaignsState.tab === 'campaigns') await loadCampaigns();
  }

  async function saveWorksForm(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_works')) return;
    const statusLine = el('worksFormStatus');
    const saveBtn = el('worksSaveBtn');
    const title = String(el('worksTitleInput')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title is required.';
      return;
    }
    const payload = {
      title,
      kind: el('worksKindInput')?.value || 'maintenance',
      category: el('worksCategoryInput')?.value || 'other',
      status: el('worksStatusInput')?.value || 'planned',
      visibility: el('worksVisibilityInput')?.value || 'published',
      summary: el('worksSummaryInput')?.value.trim() || '',
      details: el('worksDetailsInput')?.value.trim() || '',
      benefits: el('worksBenefitsInput')?.value.trim() || '',
      location: el('worksLocationInput')?.value.trim() || '',
      assignedTo: el('worksAssignedInput')?.value.trim() || '',
      startDate: el('worksStartInput')?.value || '',
      endDate: el('worksEndInput')?.value || '',
      eventDate: el('worksEventInput')?.value || '',
      timelineNotes: el('worksTimelineInput')?.value.trim() || '',
      estimatedCost: el('worksEstCostInput')?.value || '',
      actualCost: el('worksActCostInput')?.value || '',
      costNotes: el('worksCostNotesInput')?.value.trim() || '',
      contractorName: el('worksContractorNameInput')?.value.trim() || '',
      contractorContact: el('worksContractorContactInput')?.value.trim() || '',
      contractorDetails: el('worksContractorDetailsInput')?.value.trim() || '',
      funding: collectWorksFunding(),
      milestones: collectWorksMilestones(),
    };
    const editId = String(el('worksEditId')?.value || '').trim();
    if (editId) payload.id = editId;
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      const data = editId
        ? await api(`/api/rwa/works/${encodeURIComponent(editId)}`, { method: 'PATCH', body: JSON.stringify(payload) })
        : await api('/api/rwa/works', { method: 'POST', body: JSON.stringify(payload) });
      resetWorksForm();
      await loadWorks();
      if (statusLine) statusLine.textContent = 'Saved.';
      if (data.work?.id) worksState.expandedId = data.work.id;
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function fillCampaignMetaSelects(meta) {
    const kindFilter = el('campaignsKindFilter');
    const kindInput = el('campaignsKindInput');
    const statusInput = el('campaignsStatusInput');
    const methodInput = el('campaignContributeMethod');
    const fill = (sel, items, allLabel) => {
      if (!sel || !items) return;
      const cur = sel.value;
      sel.innerHTML = (allLabel ? `<option value="">${allLabel}</option>` : '')
        + items.map((i) => `<option value="${escapeHtml(i.id)}">${escapeHtml(i.label)}</option>`).join('');
      if (cur) sel.value = cur;
    };
    fill(kindFilter, meta?.kinds, 'All types');
    fill(kindInput, meta?.kinds, null);
    fill(statusInput, meta?.statuses, null);
    fill(methodInput, meta?.contributionMethods, null);
    syncCampaignFormMode();
  }

  function syncCampaignFormMode() {
    const mode = el('campaignsModeInput')?.value || 'both';
    const pledgeType = el('campaignsPledgeAmountTypeInput')?.value || 'discretionary';
    const showPledge = mode === 'pledge' || mode === 'both';
    const showFunding = mode === 'funding' || mode === 'both';
    if (el('campaignsPledgeAmountTypeWrap')) el('campaignsPledgeAmountTypeWrap').hidden = !showPledge;
    if (el('campaignsFixedPledgeWrap')) {
      el('campaignsFixedPledgeWrap').hidden = !showPledge || pledgeType !== 'fixed';
    }
    if (el('campaignsPaymentWrap')) el('campaignsPaymentWrap').hidden = !showFunding;
  }

  function campaignCoverSrc(campaign) {
    if (!campaign?.imageUrl) return '';
    const v = campaign.updatedAt ? encodeURIComponent(String(campaign.updatedAt)) : '1';
    return `${campaign.imageUrl}?v=${v}`;
  }

  function campaignKindEmoji(kind) {
    return ({ plantation: '🌱', maintenance: '🔧', development: '🏗️', welfare: '🤝', event: '🎉', general: '💚' })[kind] || '💚';
  }

  function campaignStatCardsHtml(c) {
    const mode = c.mode || 'both';
    const cards = [];
    if (mode === 'pledge' || mode === 'both') {
      cards.push(`<div class="campaign-stat-card is-pledged"><strong>${formatRupee(c.pledgedAmount || 0)}</strong><span>Total pledged · ${c.pledgerCount || 0} member${(c.pledgerCount || 0) === 1 ? '' : 's'}</span></div>`);
    }
    if (mode === 'funding' || mode === 'both') {
      cards.push(`<div class="campaign-stat-card is-raised"><strong>${formatRupee(c.raisedAmount || 0)}</strong><span>Total raised · ${c.contributorCount || 0} payment${(c.contributorCount || 0) === 1 ? '' : 's'}</span></div>`);
    }
    if (c.targetAmount) {
      cards.push(`<div class="campaign-stat-card"><strong>${formatRupee(c.targetAmount)}</strong><span>Fundraising target</span></div>`);
    }
    return cards.length ? `<div class="campaign-stat-grid">${cards.join('')}</div>` : '';
  }

  function campaignProgressBarsHtml(c) {
    const target = c.targetAmount;
    if (!target) return '';
    const mode = c.mode || 'both';
    const bars = [];
    if (mode === 'pledge' || mode === 'both') {
      const pct = Math.min(100, Math.round(100 * (c.pledgedAmount || 0) / target));
      bars.push(`<div><label>Pledged progress</label><div class="campaign-progress-bar"><div class="campaign-progress-fill" style="width:${pct}%"></div></div></div>`);
    }
    if (mode === 'funding' || mode === 'both') {
      const pct = Math.min(100, Math.round(100 * (c.raisedAmount || 0) / target));
      bars.push(`<div><label>Raised progress</label><div class="campaign-progress-bar"><div class="campaign-progress-fill" style="width:${pct}%"></div></div></div>`);
    }
    return bars.length ? `<div class="campaign-dual-progress">${bars.join('')}</div>` : '';
  }

  function campaignProgressHtml(c) {
    return `${campaignStatCardsHtml(c)}${campaignProgressBarsHtml(c)}`;
  }

  function renderCampaignsList() {
    const list = el('campaignsList');
    const statusLine = el('campaignsListStatus');
    const detail = el('campaignDetail');
    if (!list) return;
    if (campaignsState.selected) {
      list.hidden = true;
      if (detail) detail.hidden = false;
      if (statusLine) statusLine.textContent = '';
      return;
    }
    if (detail) detail.hidden = true;
    list.hidden = false;
    const items = campaignsState.items || [];
    if (!items.length) {
      list.innerHTML = '<p class="muted">No funding drives match these filters. EC can launch a plantation or community drive below.</p>';
      if (statusLine) statusLine.textContent = '';
      return;
    }
    list.innerHTML = items.map((c) => {
      const cover = campaignCoverSrc(c);
      const thumb = cover
        ? `<img class="campaign-card-thumb" src="${escapeHtml(cover)}" alt="">`
        : `<div class="campaign-card-thumb-placeholder" aria-hidden="true">${campaignKindEmoji(c.kind)}</div>`;
      return `
      <article class="campaign-card has-thumb" data-campaign-id="${escapeHtml(c.id)}" tabindex="0">
        ${thumb}
        <div>
          <div class="campaign-card-head">
            <div class="campaign-badges">
              <span class="campaign-badge">${escapeHtml(c.kindLabel || '')}</span>
              <span class="campaign-badge is-${escapeHtml(c.status || '')}">${escapeHtml(c.statusLabel || '')}</span>
              <span class="campaign-badge">${escapeHtml(c.modeLabel || '')}</span>
              ${c.pendingContributions ? `<span class="campaign-badge is-paused">${c.pendingContributions} pending</span>` : ''}
            </div>
          </div>
          <h3>${escapeHtml(c.title || '')}</h3>
          ${c.summary ? `<p class="summary">${escapeHtml(c.summary)}</p>` : ''}
          ${campaignProgressHtml(c)}
          <div class="campaign-stats">
            ${c.deadline ? `<span>Deadline ${escapeHtml(formatIstDate(c.deadline) || c.deadline)}</span>` : ''}
            ${c.location ? `<span>${escapeHtml(c.location)}</span>` : ''}
          </div>
        </div>
      </article>`;
    }).join('');
    if (statusLine) statusLine.textContent = `${items.length} drive${items.length === 1 ? '' : 's'}`;
    applyMobileListLimit(list, '.campaign-card', 6);
  }

  function renderCampaignPledges(pledges, campaign) {
    const block = el('campaignPledgesBlock');
    const list = el('campaignPledgesList');
    if (!block || !list) return;
    const mode = campaign?.mode || 'both';
    block.hidden = mode === 'funding';
    if (block.hidden) return;
    const isAdmin = hasEntitlement('manage_works');
    if (!pledges?.length) {
      list.innerHTML = '<p class="muted">No pledges yet — be the first to commit.</p>';
      return;
    }
    list.innerHTML = pledges.map((p) => `
      <div class="campaign-participant-row">
        <div>
          <strong>${escapeHtml(p.contributorName || 'Member')}</strong>
          <div class="meta">Plot ${escapeHtml(p.houseId || '—')}${p.note ? ` · ${escapeHtml(p.note)}` : ''}</div>
        </div>
        <div>
          <div class="amt">${formatRupee(p.amount)}</div>
          ${isAdmin ? `<button type="button" class="btn ghost compact" data-cmp-del-pledge="${escapeHtml(p.id)}" title="Remove pledge">Remove</button>` : ''}
        </div>
      </div>`).join('');
  }

  function renderCampaignContributions(contributions, campaign) {
    const block = el('campaignContributionsBlock');
    const list = el('campaignContributionsList');
    if (!block || !list) return;
    const mode = campaign?.mode || 'both';
    block.hidden = mode === 'pledge';
    if (block.hidden) return;
    if (!contributions?.length) {
      list.innerHTML = '<p class="muted">No contributions yet — be the first to support this drive.</p>';
      return;
    }
    const isAdmin = hasEntitlement('manage_works');
    const myHouse = state.session?.resident?.houseId || '';
    list.innerHTML = contributions.map((c) => {
      const pending = c.status === 'pending';
      const canReview = isAdmin && pending;
      const label = c.contributorName || 'Member';
      return `
        <div class="campaign-participant-row is-${escapeHtml(c.status || '')}">
          <div>
            <strong>${escapeHtml(label)}</strong>
            <div class="meta">Plot ${escapeHtml(c.houseId || '—')}${c.methodLabel ? ` · ${escapeHtml(c.methodLabel)}` : ''}${c.paidOn ? ` · ${escapeHtml(formatIstDate(c.paidOn) || c.paidOn)}` : ''}${c.note ? ` · ${escapeHtml(c.note)}` : ''}${c.status !== 'verified' ? ` · ${escapeHtml(c.status)}` : ''}</div>
          </div>
          <div>
            <div class="amt">${formatRupee(c.amount)}</div>
            ${canReview ? `<div class="btn-row"><button type="button" class="btn secondary compact" data-cmp-verify="${escapeHtml(c.id)}">Verify</button><button type="button" class="btn ghost compact" data-cmp-reject="${escapeHtml(c.id)}">Reject</button></div>` : ''}
            ${isAdmin && !canReview ? `<button type="button" class="btn ghost compact" data-cmp-del-contrib="${escapeHtml(c.id)}" title="Remove record">Remove</button>` : ''}
          </div>
        </div>`;
    }).join('');
  }

  function renderCampaignSuggestions(suggestions, campaign) {
    const block = el('campaignSuggestionsBlock');
    const list = el('campaignSuggestionsList');
    if (!block || !list) return;
    block.hidden = !campaign?.canSuggest;
    if (block.hidden) return;
    const isAdmin = hasEntitlement('manage_works');
    if (!suggestions?.length) {
      list.innerHTML = '<p class="muted">No suggestions yet — share an idea for this drive.</p>';
      return;
    }
    list.innerHTML = suggestions.map((s) => `
      <div class="campaign-participant-row">
        <div>
          <strong>${escapeHtml(s.contributorName || 'Member')}</strong>
          <div class="meta">Plot ${escapeHtml(s.houseId || '—')}${s.createdAt ? ` · ${escapeHtml(formatIstDate(s.createdAt) || '')}` : ''}</div>
          <p>${escapeHtml(s.text || '')}</p>
        </div>
        <div>
          ${isAdmin ? `<button type="button" class="btn ghost compact" data-cmp-del-suggest="${escapeHtml(s.id)}" title="Remove suggestion">Remove</button>` : ''}
        </div>
      </div>`).join('');
  }

  function renderCampaignDetail(campaign, pledges, contributions, suggestions) {
    campaignsState.selected = campaign;
    renderCampaignsList();
    const body = el('campaignDetailBody');
    if (!body || !campaign) return;
    const cover = campaignCoverSrc(campaign);
    const heroClass = cover ? 'campaign-showcase-hero has-image' : 'campaign-showcase-hero';
    body.innerHTML = `
      <div class="${heroClass}">
        ${cover ? `<img src="${escapeHtml(cover)}" alt="">` : ''}
        <div class="campaign-showcase-hero-overlay">
          <div class="campaign-badges">
            <span class="campaign-badge">${escapeHtml(campaign.kindLabel || '')}</span>
            <span class="campaign-badge">${escapeHtml(campaign.modeLabel || '')}</span>
            <span class="campaign-badge">${escapeHtml(campaign.statusLabel || '')}</span>
          </div>
          <h2>${escapeHtml(campaign.title || '')}</h2>
        </div>
      </div>
      <div class="campaign-showcase-body">
        ${campaign.summary ? `<p class="campaign-showcase-summary">${escapeHtml(campaign.summary)}</p>` : ''}
        ${campaignProgressHtml(campaign)}
        ${campaign.details ? `<div class="detail-section"><strong>About this drive</strong>${escapeHtml(campaign.details)}</div>` : ''}
        ${campaign.paymentInstructions && campaign.mode !== 'pledge' ? `<div class="detail-section"><strong>How to pay</strong>${escapeHtml(campaign.paymentInstructions)}</div>` : ''}
        <div class="campaign-stats">
          ${campaign.location ? `<span>📍 ${escapeHtml(campaign.location)}</span>` : ''}
          ${campaign.eventDate ? `<span>📅 ${escapeHtml(formatIstDate(campaign.eventDate) || campaign.eventDate)}</span>` : ''}
          ${campaign.deadline ? `<span>⏳ Deadline ${escapeHtml(formatIstDate(campaign.deadline) || campaign.deadline)}</span>` : ''}
          ${campaign.pledgeAmountType === 'fixed' && campaign.fixedPledgeAmount ? `<span>Fixed pledge ${formatRupee(campaign.fixedPledgeAmount)}</span>` : ''}
        </div>
      </div>`;
    renderCampaignPledges(pledges || [], campaign);
    renderCampaignContributions(contributions || [], campaign);
    renderCampaignSuggestions(suggestions || [], campaign);
    const pledgeBtn = el('campaignPledgeBtn');
    const contributeBtn = el('campaignContributeBtn');
    const suggestBtn = el('campaignSuggestBtn');
    if (pledgeBtn) pledgeBtn.hidden = isViewOnly() || !campaign.canPledge;
    if (contributeBtn) contributeBtn.hidden = isViewOnly() || !campaign.canContribute;
    if (suggestBtn) suggestBtn.hidden = isViewOnly() || !campaign.canSuggest;
    const shareBtn = el('campaignShareBtn');
    if (shareBtn) shareBtn.hidden = campaign.audience !== 'public';
    if (el('campaignEditBtn')) el('campaignEditBtn').hidden = !hasEntitlement('manage_works');
    if (el('campaignDeleteBtn')) el('campaignDeleteBtn').hidden = !hasEntitlement('manage_works');
  }

  function showCampaignList() {
    campaignsState.selected = null;
    if (el('campaignDetail')) el('campaignDetail').hidden = true;
    renderCampaignsList();
  }

  async function openCampaignDetail(campaignId) {
    const data = await api(`/api/rwa/campaigns/${encodeURIComponent(campaignId)}`);
    renderCampaignDetail(data.campaign, data.pledges || [], data.contributions || [], data.suggestions || []);
    el('campaignDetail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function resetCampaignsForm() {
    campaignsState.editingId = null;
    el('campaignsForm')?.reset();
    if (el('campaignsEditId')) el('campaignsEditId').value = '';
    if (el('campaignsFormTitle')) el('campaignsFormTitle').textContent = 'New funding drive';
    if (el('campaignsCancelEditBtn')) el('campaignsCancelEditBtn').hidden = true;
    if (el('campaignsFormStatus')) el('campaignsFormStatus').textContent = '';
    if (el('campaignsImageHint')) el('campaignsImageHint').textContent = 'JPEG, PNG or WebP — auto-optimized for fast loading on the public page';
    fillCampaignMetaSelects(campaignsState.meta || {});
  }

  function fillCampaignsForm(campaign) {
    if (!campaign) return;
    campaignsState.editingId = campaign.id;
    if (el('campaignsEditId')) el('campaignsEditId').value = campaign.id;
    if (el('campaignsFormTitle')) el('campaignsFormTitle').textContent = 'Edit funding drive';
    if (el('campaignsCancelEditBtn')) el('campaignsCancelEditBtn').hidden = false;
    if (el('campaignsTitleInput')) el('campaignsTitleInput').value = campaign.title || '';
    if (el('campaignsKindInput')) el('campaignsKindInput').value = campaign.kind || 'general';
    if (el('campaignsStatusInput')) el('campaignsStatusInput').value = campaign.status || 'draft';
    if (el('campaignsModeInput')) el('campaignsModeInput').value = campaign.mode || 'both';
    if (el('campaignsAudienceInput')) el('campaignsAudienceInput').value = campaign.audience || 'members';
    if (el('campaignsPledgeAmountTypeInput')) el('campaignsPledgeAmountTypeInput').value = campaign.pledgeAmountType || 'discretionary';
    if (el('campaignsFixedPledgeInput')) el('campaignsFixedPledgeInput').value = campaign.fixedPledgeAmount ?? '';
    if (el('campaignsTargetInput')) el('campaignsTargetInput').value = campaign.targetAmount ?? '';
    if (el('campaignsDeadlineInput')) el('campaignsDeadlineInput').value = campaign.deadline || '';
    if (el('campaignsEventInput')) el('campaignsEventInput').value = campaign.eventDate || '';
    if (el('campaignsLocationInput')) el('campaignsLocationInput').value = campaign.location || '';
    if (el('campaignsSummaryInput')) el('campaignsSummaryInput').value = campaign.summary || '';
    if (el('campaignsDetailsInput')) el('campaignsDetailsInput').value = campaign.details || '';
    if (el('campaignsPaymentInput')) el('campaignsPaymentInput').value = campaign.paymentInstructions || '';
    if (el('campaignsImageHint')) {
      el('campaignsImageHint').textContent = campaign.imageUrl
        ? 'Current illustration is saved — upload a new file to replace it.'
        : 'JPEG, PNG or WebP — shown on the drive page';
    }
    syncCampaignFormMode();
    el('campaignsManageBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadCampaigns() {
    syncWorksPanelTabs();
    if (el('campaignsManageBlock')) {
      el('campaignsManageBlock').hidden = !hasEntitlement('manage_works');
    }
    const qs = new URLSearchParams();
    const kind = el('campaignsKindFilter')?.value || '';
    const status = el('campaignsStatusFilter')?.value ?? 'active';
    if (kind) qs.set('kind', kind);
    if (status) qs.set('status', status);
    if (hasEntitlement('manage_works')) {
      const audience = el('campaignsAudienceFilter')?.value || '';
      if (audience) qs.set('audience', audience);
    }
    const statusLine = el('campaignsListStatus');
    if (statusLine && !campaignsState.selected) statusLine.textContent = 'Loading drives…';
    const data = await api(`/api/rwa/campaigns?${qs.toString()}`);
    campaignsState.meta = {
      kinds: data.kinds,
      statuses: data.statuses,
      audiences: data.audiences,
      modes: data.modes,
      pledgeAmountTypes: data.pledgeAmountTypes,
      contributionMethods: data.contributionMethods,
    };
    campaignsState.items = data.campaigns || [];
    fillCampaignMetaSelects(campaignsState.meta);
    if (campaignsState.selected) {
      const fresh = campaignsState.items.find((c) => c.id === campaignsState.selected.id);
      if (fresh) {
        await openCampaignDetail(fresh.id);
        return;
      }
      showCampaignList();
    }
    renderCampaignsList();
  }

  async function saveCampaignsForm(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_works')) return;
    const statusLine = el('campaignsFormStatus');
    const saveBtn = el('campaignsSaveBtn');
    const title = String(el('campaignsTitleInput')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title is required.';
      return;
    }
    const mode = el('campaignsModeInput')?.value || 'both';
    const fd = new FormData();
    fd.append('title', title);
    fd.append('kind', el('campaignsKindInput')?.value || 'general');
    fd.append('status', el('campaignsStatusInput')?.value || 'draft');
    fd.append('mode', mode);
    fd.append('audience', el('campaignsAudienceInput')?.value || 'members');
    if (mode !== 'funding') {
      fd.append('pledgeAmountType', el('campaignsPledgeAmountTypeInput')?.value || 'discretionary');
      const fixed = el('campaignsFixedPledgeInput')?.value || '';
      if (fixed) fd.append('fixedPledgeAmount', fixed);
    }
    fd.append('targetAmount', el('campaignsTargetInput')?.value || '');
    fd.append('deadline', el('campaignsDeadlineInput')?.value || '');
    fd.append('eventDate', el('campaignsEventInput')?.value || '');
    fd.append('location', el('campaignsLocationInput')?.value.trim() || '');
    fd.append('summary', el('campaignsSummaryInput')?.value.trim() || '');
    fd.append('details', el('campaignsDetailsInput')?.value.trim() || '');
    fd.append('paymentInstructions', el('campaignsPaymentInput')?.value.trim() || '');
    const image = el('campaignsImageInput')?.files?.[0];
    if (image) fd.append('image', image);
    const editId = String(el('campaignsEditId')?.value || '').trim();
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const url = editId ? `/api/rwa/campaigns/${encodeURIComponent(editId)}` : '/api/rwa/campaigns';
      const res = await fetch(url, {
        method: editId ? 'PATCH' : 'POST',
        credentials: 'same-origin',
        headers,
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText || 'Save failed');
      resetCampaignsForm();
      campaignsState.tab = 'campaigns';
      syncWorksPanelTabs();
      await loadCampaigns();
      if (data.campaign?.id) await openCampaignDetail(data.campaign.id);
      if (statusLine) statusLine.textContent = 'Saved.';
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function prefillCampaignParticipantFields(prefix) {
    const resident = state.session?.resident || {};
    const nameEl = el(`${prefix}Name`);
    const houseEl = el(`${prefix}House`);
    if (nameEl && !nameEl.value) nameEl.value = resident.name || '';
    if (houseEl && !houseEl.value) houseEl.value = resident.houseId || '';
  }

  function openCampaignPledgeDialog() {
    const c = campaignsState.selected;
    if (!c || !c.canPledge || isViewOnly()) return;
    if (el('campaignPledgeTitle')) el('campaignPledgeTitle').textContent = `Pledge — ${c.title || 'Drive'}`;
    if (el('campaignPledgeLead')) {
      el('campaignPledgeLead').textContent = c.pledgeAmountType === 'fixed' && c.fixedPledgeAmount
        ? `Fixed pledge of ${formatRupee(c.fixedPledgeAmount)} per member. Enter your name and plot number.`
        : 'Record your commitment — name, plot number, and pledged amount.';
    }
    prefillCampaignParticipantFields('campaignPledge');
    const amountWrap = el('campaignPledgeAmountWrap');
    const amountInput = el('campaignPledgeAmount');
    if (c.pledgeAmountType === 'fixed' && c.fixedPledgeAmount) {
      if (amountInput) {
        amountInput.value = String(c.fixedPledgeAmount);
        amountInput.readOnly = true;
      }
      if (amountWrap) amountWrap.hidden = false;
    } else if (amountInput) {
      amountInput.value = '';
      amountInput.readOnly = false;
    }
    if (el('campaignPledgeNote')) el('campaignPledgeNote').value = '';
    if (el('campaignPledgeStatus')) el('campaignPledgeStatus').textContent = '';
    el('campaignPledgeDialog')?.showModal();
  }

  async function submitCampaignPledge(event) {
    event.preventDefault();
    const c = campaignsState.selected;
    if (!c || isViewOnly()) return;
    const statusLine = el('campaignPledgeStatus');
    const btn = el('campaignPledgeSubmitBtn');
    const name = el('campaignPledgeName')?.value.trim() || '';
    const house = el('campaignPledgeHouse')?.value.trim() || '';
    if (!name || !house) {
      if (statusLine) statusLine.textContent = 'Name and house / plot number are required.';
      return;
    }
    const payload = {
      contributorName: name,
      houseId: house,
      note: el('campaignPledgeNote')?.value.trim() || '',
    };
    if (!(c.pledgeAmountType === 'fixed' && c.fixedPledgeAmount)) {
      payload.amount = el('campaignPledgeAmount')?.value || '';
    }
    if (btn) btn.disabled = true;
    if (statusLine) statusLine.textContent = 'Submitting pledge…';
    try {
      await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/pledges`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      el('campaignPledgeDialog')?.close();
      await openCampaignDetail(c.id);
      await loadCampaigns();
      if (statusLine) statusLine.textContent = 'Pledge recorded — thank you!';
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Submit failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openCampaignSuggestDialog() {
    const c = campaignsState.selected;
    if (!c || !c.canSuggest || isViewOnly()) return;
    if (el('campaignSuggestTitle')) el('campaignSuggestTitle').textContent = `Suggestion — ${c.title || 'Drive'}`;
    prefillCampaignParticipantFields('campaignSuggest');
    if (el('campaignSuggestText')) el('campaignSuggestText').value = '';
    if (el('campaignSuggestStatus')) el('campaignSuggestStatus').textContent = '';
    el('campaignSuggestDialog')?.showModal();
  }

  async function submitCampaignSuggestion(event) {
    event.preventDefault();
    const c = campaignsState.selected;
    if (!c || isViewOnly()) return;
    const statusLine = el('campaignSuggestStatus');
    const btn = el('campaignSuggestSubmitBtn');
    const name = el('campaignSuggestName')?.value.trim() || '';
    const house = el('campaignSuggestHouse')?.value.trim() || '';
    const text = el('campaignSuggestText')?.value.trim() || '';
    if (!name || !house || !text) {
      if (statusLine) statusLine.textContent = 'Name, house, and suggestion are required.';
      return;
    }
    if (btn) btn.disabled = true;
    if (statusLine) statusLine.textContent = 'Submitting…';
    try {
      await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/suggestions`, {
        method: 'POST',
        body: JSON.stringify({ contributorName: name, houseId: house, text }),
      });
      el('campaignSuggestDialog')?.close();
      await openCampaignDetail(c.id);
      await loadCampaigns();
      if (statusLine) statusLine.textContent = 'Suggestion recorded — thank you!';
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Submit failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function removeCampaignSuggestion(suggestionId) {
    const c = campaignsState.selected;
    if (!c || !hasEntitlement('manage_works')) return;
    if (!window.confirm('Remove this suggestion?')) return;
    await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/suggestions/${encodeURIComponent(suggestionId)}`, {
      method: 'DELETE',
    });
    await openCampaignDetail(c.id);
    await loadCampaigns();
  }

  function openCampaignContributeDialog() {
    const c = campaignsState.selected;
    if (!c || !c.canContribute || isViewOnly()) return;
    if (el('campaignContributeTitle')) el('campaignContributeTitle').textContent = `Contribute — ${c.title || 'Drive'}`;
    if (el('campaignContributeLead')) {
      el('campaignContributeLead').textContent = c.paymentInstructions
        ? `Pay as instructed on the drive page, then record your contribution here.`
        : 'Record your payment after transfer — EC will verify and update totals.';
    }
    fillCampaignMetaSelects(campaignsState.meta || {});
    prefillCampaignParticipantFields('campaignContribute');
    if (el('campaignContributePaidOn')) el('campaignContributePaidOn').value = todayIstDate();
    if (el('campaignContributeAmount')) el('campaignContributeAmount').value = '';
    if (el('campaignContributeNote')) el('campaignContributeNote').value = '';
    if (el('campaignContributeFiles')) el('campaignContributeFiles').value = '';
    if (el('campaignContributeStatus')) el('campaignContributeStatus').textContent = '';
    el('campaignContributeDialog')?.showModal();
  }

  async function submitCampaignContribution(event) {
    event.preventDefault();
    const c = campaignsState.selected;
    if (!c || isViewOnly()) return;
    const statusLine = el('campaignContributeStatus');
    const btn = el('campaignContributeSubmitBtn');
    const name = el('campaignContributeName')?.value.trim() || '';
    const house = el('campaignContributeHouse')?.value.trim() || '';
    const amount = el('campaignContributeAmount')?.value || '';
    if (!name || !house) {
      if (statusLine) statusLine.textContent = 'Name and house / plot number are required.';
      return;
    }
    if (!amount || Number(amount) <= 0) {
      if (statusLine) statusLine.textContent = 'Enter a valid amount.';
      return;
    }
    if (btn) btn.disabled = true;
    if (statusLine) statusLine.textContent = 'Submitting…';
    try {
      const fd = new FormData();
      fd.append('amount', amount);
      fd.append('contributorName', name);
      fd.append('houseId', house);
      fd.append('method', el('campaignContributeMethod')?.value || 'upi');
      fd.append('paidOn', el('campaignContributePaidOn')?.value || todayIstDate());
      fd.append('note', el('campaignContributeNote')?.value.trim() || '');
      const files = el('campaignContributeFiles')?.files || [];
      Array.from(files).slice(0, 3).forEach((f) => fd.append('files', f));
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const res = await fetch(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/contributions`, {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText || 'Submit failed');
      el('campaignContributeDialog')?.close();
      await openCampaignDetail(c.id);
      await loadCampaigns();
      if (statusLine) statusLine.textContent = 'Submitted — awaiting EC verification.';
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Submit failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function reviewCampaignContribution(contributionId, action) {
    const c = campaignsState.selected;
    if (!c || !hasEntitlement('manage_works')) return;
    let reason = '';
    if (action === 'reject') {
      reason = window.prompt('Reason for rejection (optional):') || '';
      if (reason === null) return;
    }
    await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/contributions/${encodeURIComponent(contributionId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ action, reason }),
    });
    await openCampaignDetail(c.id);
    await loadCampaigns();
  }

  async function removeCampaignPledge(pledgeId) {
    const c = campaignsState.selected;
    if (!c || !hasEntitlement('manage_works')) return;
    if (!window.confirm('Remove this pledge record?')) return;
    await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/pledges/${encodeURIComponent(pledgeId)}`, {
      method: 'DELETE',
    });
    await openCampaignDetail(c.id);
    await loadCampaigns();
  }

  async function removeCampaignContribution(contributionId) {
    const c = campaignsState.selected;
    if (!c || !hasEntitlement('manage_works')) return;
    if (!window.confirm('Remove this contribution record?')) return;
    await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}/contributions/${encodeURIComponent(contributionId)}`, {
      method: 'DELETE',
    });
    await openCampaignDetail(c.id);
    await loadCampaigns();
  }

  const proceedingsState = {
    type: 'gh',
    meta: null,
    items: [],
    selected: null,
    searchTimer: null,
  };

  function proceedingsSubtypeOptions(type) {
    return proceedingsState.meta?.subtypes?.[type || proceedingsState.type] || [];
  }

  function fillProceedingsSubtypeSelect(type, selected) {
    const sel = el('proceedingsSubtypeInput');
    if (!sel) return;
    const opts = proceedingsSubtypeOptions(type || proceedingsState.type);
    sel.innerHTML = opts.map((o) => `<option value="${escapeHtml(o.id)}">${escapeHtml(o.label)}</option>`).join('');
    if (selected) sel.value = selected;
  }

  function syncProceedingsQuorumField() {
    const type = el('proceedingsTypeInput')?.value || proceedingsState.type;
    document.querySelectorAll('.proceedings-quorum-field').forEach((node) => {
      node.hidden = type !== 'gh';
    });
  }

  function syncProceedingsRegisterTabs() {
    document.querySelectorAll('.proceedings-register-tab').forEach((btn) => {
      const on = btn.dataset.proceedingsType === proceedingsState.type;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const link = el('proceedingsTemplateLink');
    if (link) {
      link.href = proceedingsState.type === 'ec'
        ? '/documents/proceedings-ec-mom-pad.html'
        : '/documents/proceedings-gh-mom-pad.html';
    }
    if (el('proceedingsTypeInput')) el('proceedingsTypeInput').value = proceedingsState.type;
    fillProceedingsSubtypeSelect(proceedingsState.type);
    syncProceedingsQuorumField();
  }

  function fillProceedingsYearFilter(items) {
    const sel = el('proceedingsYearFilter');
    if (!sel) return;
    const years = new Set();
    const now = String(new Date().getFullYear());
    years.add(now);
    (items || []).forEach((p) => {
      if (p.registerYear) years.add(String(p.registerYear));
      else if (p.meetingDate) years.add(String(p.meetingDate).slice(0, 4));
    });
    const sorted = [...years].sort((a, b) => Number(b) - Number(a));
    const cur = sel.value;
    sel.innerHTML = ['<option value="">All years</option>']
      .concat(sorted.map((y) => `<option value="${escapeHtml(y)}">${escapeHtml(y)}</option>`))
      .join('');
    if (cur && sorted.includes(cur)) sel.value = cur;
    else if (!cur && sorted.includes(now)) sel.value = now;
  }

  function proceedingsStatusBadge(p) {
    const st = p.status || 'draft';
    const cls = st === 'published' ? 'is-published' : (st === 'archived' ? 'is-archived' : 'is-draft');
    return `<span class="proceedings-badge ${cls}">${escapeHtml(p.statusLabel || st)}</span>`;
  }

  function proceedingsMultiline(text) {
    if (!text) return '<p class="muted">—</p>';
    return `<div class="proceedings-multiline">${String(text).split('\n').map((line) => escapeHtml(line)).join('<br>')}</div>`;
  }

  const MOM_ASSETS = {
    wm: '/assets/mhws-logo/mhws-logo-watermark.png?v=20260811wm9',
    seal: '/assets/mhws-logo/mhws-logo-seal-cert.png?v=20260822logo1',
  };

  function momText(text) {
    if (!text) return '&nbsp;';
    return escapeHtml(String(text)).replace(/\n/g, '<br>');
  }

  function momResolutionsTableRows(resolutions) {
    const items = resolutions || [];
    const rows = items.map((r) => `
      <tr>
        <td>${escapeHtml(r.no || '')}</td>
        <td>${escapeHtml(r.text || '')}${r.votesFor != null ? `<br><span style="font-size:7pt;color:#5a6a80">For: ${r.votesFor}, Against: ${r.votesAgainst ?? 0}, Abstain: ${r.abstain ?? 0}</span>` : ''}${r.vote ? `<br><span style="font-size:7pt;color:#1a4f7a">${escapeHtml(r.vote.statusLabel || r.vote.status || '')}${r.vote.status === 'open' ? ` · ${r.vote.votesFor || 0} for / ${r.vote.votesAgainst || 0} against / ${r.vote.pendingCount || 0} pending` : ''}</span>` : ''}${r.passed === false && !r.vote ? ' · <em>Not passed</em>' : ''}</td>
        <td style="text-align:center">${r.passed === false ? 'No' : 'Yes'}</td>
      </tr>`);
    while (rows.length < 4) {
      rows.push('<tr><td>&nbsp;</td><td style="height:9mm"></td><td></td></tr>');
    }
    return rows.join('');
  }

  function momActionsTableRows(actions) {
    const items = actions || [];
    const rows = items.map((a) => `
      <tr>
        <td>${escapeHtml(a.item || '')}${a.done ? ' ✓' : ''}</td>
        <td>${escapeHtml(a.owner || '')}</td>
        <td>${escapeHtml(formatIstDate(a.dueDate) || a.dueDate || '')}</td>
        <td style="text-align:center">${a.done ? 'Yes' : ''}</td>
      </tr>`);
    while (rows.length < 6) {
      rows.push('<tr><td style="height:10mm"></td><td></td><td></td><td></td></tr>');
    }
    return rows.join('');
  }

  function buildProceedingsMomHtml(p) {
    if (!p) return '';
    const isGh = p.meetingType === 'gh';
    const reg = escapeHtml(p.registerLabel || '');
    const date = escapeHtml(formatIstDate(p.meetingDate) || '');
    const time = escapeHtml(p.meetingTime || '');
    const venue = escapeHtml(p.venue || '');
    const chair = escapeHtml(p.chairPerson || '');
    const subtype = escapeHtml(p.meetingSubtypeLabel || '');
    const quorum = p.quorumMet === true ? 'Yes' : (p.quorumMet === false ? 'No' : '');
    const presentLabel = isGh ? 'Members present' : 'EC members present';
    const banner1 = isGh ? 'General House Meeting' : 'Executive Committee Meeting';
    const addr1 = isGh
      ? 'Housing Colony Sanyard, Mandi HP 175001'
      : 'Housing Colony Sanyard, Mandi HP 175001 · Executive Committee';
    const addr2 = isGh ? 'General House MOM — continued' : 'Executive Committee MOM — continued';
    const foot2 = isGh
      ? 'General House Proceedings Register · Himuda Housing Colony Sanyard · housingcolonysanyard.in'
      : 'Executive Committee Proceedings Register · Himuda Housing Colony Sanyard · housingcolonysanyard.in';
    const nextLabel = isGh ? 'Next GH meeting date' : 'Next EC meeting date';
    const body = p.proceedingsBody || '';
    const bodySplit = body.length > 600;
    const bodyP1 = bodySplit ? `${body.slice(0, 597)}…` : body;
    const bodyP2 = bodySplit ? body.slice(597).trimStart() : '';

    const page1MetaGh = isGh ? `
        <div class="field"><label>Quorum met (Yes / No)</label><div class="ruled">${escapeHtml(quorum) || '&nbsp;'}</div></div>` : '';

    const sheetHead = (pageTag, addr) => `
      <div class="accent-edge" aria-hidden="true"><span class="n"></span><span class="g"></span><span class="e"></span></div>
      <div class="accent-edge-thin" aria-hidden="true"></div>
      <img class="wm" src="${MOM_ASSETS.wm}" alt="" aria-hidden="true">
      <span class="page-tag">${pageTag}</span>
      <div class="pad">
        <header class="brand">
          <img class="logo" src="${MOM_ASSETS.seal}" alt="Himuda Housing Colony Sanyard">
          <div>
            <h1>Mandi Housing Welfare Society</h1>
            <p class="colony">Himuda Housing Colony Sanyard</p>
            <p class="addr">${addr}</p>
          </div>
          <div class="reg-box">
            <strong>Register No.</strong>
            <div class="line">${reg || '&nbsp;'}</div>
            <strong style="margin-top:1.5mm">Meeting date</strong>
            <div class="line">${date || '&nbsp;'}</div>
          </div>
        </header>`;

    return `<div class="mom-print-root">
      <div class="sheet" aria-label="MOM page 1">
        ${sheetHead('Page 1 of 2', addr1)}
        <div class="banner">${banner1} <span class="sep">·</span> Minutes of Meeting</div>
        <div class="meta-grid">
          <div class="field"><label>Meeting type</label><div class="ruled">${subtype || '&nbsp;'}</div></div>
          <div class="field"><label>Time</label><div class="ruled">${time || '&nbsp;'}</div></div>
          <div class="field span-2"><label>Venue</label><div class="ruled">${venue || '&nbsp;'}</div></div>
          <div class="field${isGh ? '' : ' span-2'}"><label>Chair / presiding</label><div class="ruled">${chair || '&nbsp;'}</div></div>
          ${page1MetaGh}
        </div>
        <div class="section">
          <h2>${presentLabel}</h2>
          <div class="ruled-block md">${momText(p.membersPresent)}</div>
        </div>
        <div class="section">
          <h2>Members absent / regrets</h2>
          <div class="ruled-block sm">${momText(p.membersAbsent)}</div>
        </div>
        <div class="section">
          <h2>Agenda</h2>
          <div class="ruled-block lg">${momText(p.agenda)}</div>
        </div>
        <div class="section grow">
          <h2>Proceedings / minutes${bodySplit ? ' (continued on page 2)' : ''}</h2>
          <div class="ruled-block xl">${momText(bodyP1)}</div>
          ${bodySplit ? '<p class="cont-note">→ Continue detailed proceedings on page 2</p>' : ''}
        </div>
        <div class="foot-bar">Unity<span class="sep">·</span>Harmony<span class="sep">·</span>Progress · housingcolonysanyard.in</div>
      </div></div>

      <div class="sheet" aria-label="MOM page 2">
        ${sheetHead('Page 2 of 2', addr2)}
        <div class="banner">Proceedings continued <span class="sep">·</span> ${isGh ? 'Resolutions &amp; Actions' : 'Decisions &amp; Actions'}</div>
        <div class="section grow">
          <h2>Proceedings / minutes (continued)</h2>
          <div class="ruled-block xxl">${momText(bodyP2)}</div>
        </div>
        <div class="section">
          <h2>Resolutions / decisions</h2>
          <table class="res-table">
            <thead><tr><th style="width:8mm">No.</th><th>Resolution / decision</th><th style="width:18mm">Passed</th></tr></thead>
            <tbody>${momResolutionsTableRows(p.resolutions)}</tbody>
          </table>
        </div>
        <div class="section">
          <h2>Action items</h2>
          <table class="res-table">
            <thead><tr><th>Item</th><th style="width:32mm">Owner</th><th style="width:24mm">Due date</th><th style="width:14mm">Done</th></tr></thead>
            <tbody>${momActionsTableRows(p.actionItems)}</tbody>
          </table>
        </div>
        <div class="meta-grid" style="margin-top:3mm">
          <div class="field"><label>${nextLabel}</label><div class="ruled">${escapeHtml(formatIstDate(p.nextMeetingDate) || '') || '&nbsp;'}</div></div>
          <div class="field"><label>Signed / approved by</label><div class="ruled">${escapeHtml(p.signedBy || '') || '&nbsp;'}</div></div>
        </div>
        <div class="sign-row">
          <div class="sig">President / Chairman</div>
          <div class="sig">General Secretary</div>
        </div>
        <div class="foot-bar" style="margin-top:4mm">${foot2}</div>
      </div></div>
    </div>`;
  }

  function renderProceedingsList() {
    const mount = el('proceedingsList');
    const statusLine = el('proceedingsListStatus');
    if (!mount) return;
    const items = proceedingsState.items || [];
    if (!items.length) {
      mount.innerHTML = '<p class="proceedings-empty">No entries in this register yet.</p>';
      if (statusLine) statusLine.textContent = 'Register empty for selected filters.';
      return;
    }
    const typeLabel = proceedingsState.type === 'ec' ? 'EC' : 'GH';
    mount.innerHTML = `
      <div class="proceedings-ledger-head" aria-hidden="true">
        <span>S.No.</span><span>Date</span><span>Subject</span><span>Chair</span><span>Status</span>
      </div>
      ${items.map((p) => `
        <button type="button" class="proceedings-ledger-row" data-proceedings-id="${escapeHtml(p.id)}">
          <span class="reg-no">${escapeHtml(p.registerLabel || '—')}</span>
          <span class="reg-date">${escapeHtml(formatIstDate(p.meetingDate))}</span>
          <span class="reg-title">${escapeHtml(p.title)}</span>
          <span class="reg-chair">${escapeHtml(p.chairPerson || '—')}</span>
          <span class="reg-status">${proceedingsStatusBadge(p)}${p.openVoteCount ? ' <span class="proceedings-badge is-draft">Voting</span>' : ''}</span>
        </button>
      `).join('')}`;
    if (statusLine) {
      statusLine.textContent = `${items.length} ${typeLabel} entr${items.length === 1 ? 'y' : 'ies'} shown.`;
    }
  }

  function renderProceedingsDetail(p) {
    const body = el('proceedingsDetailBody');
    if (!body || !p) return;
    body.innerHTML = buildProceedingsMomHtml(p);
    renderProceedingsVoteBar(p);
  }

  function proceedingsVoteSummary(vote) {
    if (!vote) return '';
    if (vote.status === 'open') {
      return `Open · ${vote.votesFor || 0} accept · ${vote.votesAgainst || 0} reject · ${vote.pendingCount || 0} pending`;
    }
    if (vote.status === 'passed' || vote.status === 'rejected') {
      return `${vote.statusLabel} · ${vote.votesFor || 0} accept · ${vote.votesAgainst || 0} reject of ${vote.eligibleCount || 0} invited`;
    }
    return vote.statusLabel || vote.status || '';
  }

  function renderProceedingsVoteBar(p) {
    const bar = el('proceedingsVoteBar');
    if (!bar) return;
    const canManage = hasEntitlement('manage_proceedings');
    bar.hidden = !canManage || !p;
    if (!canManage || !p) {
      bar.innerHTML = '';
      return;
    }
    const resolutions = p.resolutions || [];
    if (!resolutions.length) {
      bar.innerHTML = '<h3>Resolution voting</h3><p class="muted">Add resolutions to this entry, save, then send a voting request.</p>';
      return;
    }
    bar.innerHTML = `<h3>Resolution voting</h3>
      <p class="muted">Send accept/reject requests by email and to the members area. One vote per plot; first response is recorded.</p>
      ${resolutions.map((r) => {
        const vote = r.vote || null;
        const open = vote && vote.status === 'open';
        return `<div class="proceedings-vote-item">
          <p><strong>Resolution ${escapeHtml(r.no || '')}</strong> — ${escapeHtml((r.text || '').slice(0, 180))}${(r.text || '').length > 180 ? '…' : ''}</p>
          <p class="proceedings-vote-meta">${vote ? escapeHtml(proceedingsVoteSummary(vote)) : 'Not circulated yet'}${vote?.deadline ? ` · deadline ${escapeHtml(formatIstDate(String(vote.deadline).slice(0, 10)) || String(vote.deadline).slice(0, 10))}` : ''}</p>
          <div class="btn-row">
            ${open
              ? `<button type="button" class="btn secondary compact" data-vote-close="${escapeHtml(vote.id)}">Close &amp; tally</button>
                 <button type="button" class="btn ghost compact" data-vote-withdraw="${escapeHtml(vote.id)}">Withdraw</button>`
              : `<button type="button" class="btn primary compact" data-vote-send="${escapeHtml(r.id || '')}" data-vote-no="${escapeHtml(r.no || '')}">Send voting request</button>`}
            ${vote ? `<button type="button" class="btn ghost compact" data-vote-tally="${escapeHtml(vote.id)}">Tally</button>` : ''}
          </div>
        </div>`;
      }).join('')}`;
  }

  const proceedingsVoteState = { resolution: null, voters: [] };

  function defaultVoteDeadline() {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  }

  async function previewProceedingsVoteAudience() {
    const p = proceedingsState.selected;
    const status = el('proceedingsVotePreviewStatus');
    const list = el('proceedingsVoteVoterList');
    if (!p?.id) return;
    const audience = el('proceedingsVoteAudience')?.value || 'members';
    if (status) status.textContent = 'Loading who will be invited…';
    try {
      const data = await api(`/api/rwa/proceedings/${encodeURIComponent(p.id)}/vote-preview`, {
        method: 'POST',
        body: JSON.stringify({ audience }),
      });
      proceedingsVoteState.voters = data.voters || [];
      if (status) {
        status.textContent = `${data.count || 0} plot${data.count === 1 ? '' : 's'} · ${data.withEmail || 0} with email. Plots without email still vote in the members area.`;
      }
      if (list) {
        const showPick = audience === 'attendees';
        list.hidden = !showPick;
        if (showPick) {
          list.innerHTML = (data.voters || []).map((v) => `
            <label class="check compact">
              <input type="checkbox" class="pv-house" value="${escapeHtml(v.houseId)}" checked>
              ${escapeHtml(v.plotLabel || v.houseId)} · ${escapeHtml(v.name || 'Member')}${v.hasEmail ? '' : ' · no email'}
            </label>`).join('') || '<p class="muted">No matching attendees. Edit members present, or choose All members.</p>';
        }
      }
    } catch (e) {
      if (status) status.textContent = e.message || 'Could not load audience';
    }
  }

  async function openProceedingsVoteDialog(resolution) {
    const p = proceedingsState.selected;
    if (!p?.id || !resolution) return;
    proceedingsVoteState.resolution = resolution;
    const dlg = el('proceedingsVoteDialog');
    if (el('proceedingsVoteResolutionText')) {
      el('proceedingsVoteResolutionText').textContent = `Resolution ${resolution.no || ''}: ${resolution.text || ''}`;
    }
    if (el('proceedingsVoteAudience')) {
      el('proceedingsVoteAudience').value = p.meetingType === 'ec' ? 'attendees' : 'members';
    }
    if (el('proceedingsVoteCriteria')) el('proceedingsVoteCriteria').value = 'simple_majority';
    if (el('proceedingsVoteDeadline')) el('proceedingsVoteDeadline').value = defaultVoteDeadline();
    if (el('proceedingsVoteNote')) el('proceedingsVoteNote').value = '';
    if (el('proceedingsVoteStatus')) el('proceedingsVoteStatus').textContent = '';
    await previewProceedingsVoteAudience();
    dlg?.showModal();
  }

  async function submitProceedingsVoteForm(event) {
    event.preventDefault();
    const p = proceedingsState.selected;
    const resolution = proceedingsVoteState.resolution;
    const status = el('proceedingsVoteStatus');
    const btn = el('proceedingsVoteSubmitBtn');
    if (!p?.id || !resolution) return;
    const audience = el('proceedingsVoteAudience')?.value || 'members';
    const houseIds = audience === 'attendees'
      ? [...(el('proceedingsVoteVoterList')?.querySelectorAll('.pv-house:checked') || [])].map((n) => n.value)
      : [];
    if (audience === 'attendees' && !houseIds.length) {
      if (status) status.textContent = 'Select at least one attendee, or choose All members.';
      return;
    }
    const payload = {
      resolutionId: resolution.id || '',
      resolutionNo: resolution.no || '',
      audience,
      criteria: el('proceedingsVoteCriteria')?.value || 'simple_majority',
      deadline: el('proceedingsVoteDeadline')?.value || '',
      note: el('proceedingsVoteNote')?.value.trim() || '',
    };
    if (houseIds.length) payload.houseIds = houseIds;
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Sending voting requests…';
    try {
      const data = await api(`/api/rwa/proceedings/${encodeURIComponent(p.id)}/votes`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (data.proceeding) {
        proceedingsState.selected = data.proceeding;
        renderProceedingsDetail(data.proceeding);
      }
      const bits = [
        `Invited ${data.invited || 0}`,
        `emailed ${data.emailed || 0}`,
      ];
      if (data.skippedNoEmail) bits.push(`${data.skippedNoEmail} without email`);
      if (data.emailFailed) bits.push(`${data.emailFailed} email failed`);
      if (status) status.textContent = bits.join(' · ') + '.';
      el('proceedingsVoteDialog')?.close();
    } catch (e) {
      if (status) status.textContent = e.message || 'Could not send voting request';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function closeProceedingsVote(voteId, withdraw) {
    const label = withdraw ? 'Withdraw this voting request?' : 'Close voting and apply the pass criteria now?';
    if (!confirm(label)) return;
    const data = await api(`/api/rwa/votes/${encodeURIComponent(voteId)}/close`, {
      method: 'POST',
      body: JSON.stringify({ withdraw: Boolean(withdraw) }),
    });
    if (data.proceeding) {
      proceedingsState.selected = data.proceeding;
      renderProceedingsDetail(data.proceeding);
    }
  }

  async function showProceedingsVoteTally(voteId) {
    const data = await api(`/api/rwa/votes/${encodeURIComponent(voteId)}`);
    const vote = data.vote || {};
    const lines = (vote.ballots || []).map((b) => {
      const mark = b.choice === 'accept' ? 'Accept' : (b.choice === 'reject' ? 'Reject' : 'Pending');
      return `${b.plotLabel || b.houseId} · ${b.name || ''} · ${mark}`;
    });
    window.alert(
      `${vote.statusLabel || vote.status || 'Vote'}\n${proceedingsVoteSummary(vote)}\n\n${lines.join('\n') || 'No ballots'}`
    );
  }

  function showProceedingsDetail(show) {
    const shell = document.querySelector('.proceedings-register-shell');
    const detail = el('proceedingsDetail');
    const manage = el('proceedingsManageBlock');
    if (shell) shell.hidden = show;
    if (detail) detail.hidden = !show;
    if (manage) manage.hidden = show || !hasEntitlement('manage_proceedings');
    if (!show) {
      const bar = el('proceedingsVoteBar');
      if (bar) {
        bar.hidden = true;
        bar.innerHTML = '';
      }
    }
    scrollMainToTop();
  }

  async function openProceedingsDetail(id) {
    const data = await api(`/api/rwa/proceedings/${encodeURIComponent(id)}`);
    proceedingsState.selected = data.proceeding;
    renderProceedingsDetail(data.proceeding);
    showProceedingsDetail(true);
  }

  function addProceedingsResolutionRow(data = {}) {
    const list = el('proceedingsResolutionsList');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'proceedings-row works-row';
    row.innerHTML = `
      <input type="hidden" class="pr-id" value="${escapeHtml(data.id || '')}">
      <label>No <input type="text" class="pr-no" maxlength="12" value="${escapeHtml(data.no || '')}"></label>
      <label class="span-2">Resolution <textarea class="pr-text" rows="2">${escapeHtml(data.text || '')}</textarea></label>
      <label>For <input type="number" class="pr-for" min="0" value="${data.votesFor ?? ''}"></label>
      <label>Against <input type="number" class="pr-against" min="0" value="${data.votesAgainst ?? ''}"></label>
      <label>Abstain <input type="number" class="pr-abstain" min="0" value="${data.abstain ?? ''}"></label>
      <label class="check compact"><input type="checkbox" class="pr-passed" ${data.passed !== false ? 'checked' : ''}> Passed</label>
      <button type="button" class="btn ghost compact pr-remove">Remove</button>`;
    list.appendChild(row);
  }

  function addProceedingsActionRow(data = {}) {
    const list = el('proceedingsActionsList');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'proceedings-row works-row';
    row.innerHTML = `
      <label class="span-2">Action <input type="text" class="pa-item" maxlength="800" value="${escapeHtml(data.item || '')}"></label>
      <label>Owner <input type="text" class="pa-owner" maxlength="120" value="${escapeHtml(data.owner || '')}"></label>
      <label>Due date <input type="date" class="pa-due" value="${escapeHtml((data.dueDate || '').slice(0, 10))}"></label>
      <label class="check compact"><input type="checkbox" class="pa-done" ${data.done ? 'checked' : ''}> Done</label>
      <button type="button" class="btn ghost compact pa-remove">Remove</button>`;
    list.appendChild(row);
  }

  function collectProceedingsResolutions() {
    return [...(el('proceedingsResolutionsList')?.querySelectorAll('.proceedings-row') || [])].map((row, i) => ({
      id: row.querySelector('.pr-id')?.value.trim() || '',
      no: row.querySelector('.pr-no')?.value.trim() || String(i + 1),
      text: row.querySelector('.pr-text')?.value.trim() || '',
      votesFor: row.querySelector('.pr-for')?.value || null,
      votesAgainst: row.querySelector('.pr-against')?.value || null,
      abstain: row.querySelector('.pr-abstain')?.value || null,
      passed: row.querySelector('.pr-passed')?.checked !== false,
    })).filter((r) => r.text);
  }

  function collectProceedingsActions() {
    return [...(el('proceedingsActionsList')?.querySelectorAll('.proceedings-row') || [])].map((row) => ({
      item: row.querySelector('.pa-item')?.value.trim() || '',
      owner: row.querySelector('.pa-owner')?.value.trim() || '',
      dueDate: row.querySelector('.pa-due')?.value || '',
      done: row.querySelector('.pa-done')?.checked || false,
    })).filter((a) => a.item);
  }

  function resetProceedingsForm() {
    if (el('proceedingsEditId')) el('proceedingsEditId').value = '';
    if (el('proceedingsFormTitle')) el('proceedingsFormTitle').textContent = 'New register entry';
    if (el('proceedingsDateInput')) el('proceedingsDateInput').value = todayIstDate();
    ['proceedingsTimeInput', 'proceedingsTitleInput', 'proceedingsVenueInput', 'proceedingsChairInput',
      'proceedingsPresentInput', 'proceedingsAbsentInput', 'proceedingsAgendaInput', 'proceedingsBodyInput',
      'proceedingsSignedInput', 'proceedingsNextDateInput'].forEach((id) => {
      const node = el(id);
      if (node) node.value = '';
    });
    if (el('proceedingsQuorumInput')) el('proceedingsQuorumInput').value = '';
    if (el('proceedingsStatusInput')) el('proceedingsStatusInput').value = 'draft';
    if (el('proceedingsTypeInput')) el('proceedingsTypeInput').value = proceedingsState.type;
    fillProceedingsSubtypeSelect(proceedingsState.type, 'regular');
    syncProceedingsQuorumField();
    if (el('proceedingsResolutionsList')) el('proceedingsResolutionsList').innerHTML = '';
    if (el('proceedingsActionsList')) el('proceedingsActionsList').innerHTML = '';
    if (el('proceedingsCancelEditBtn')) el('proceedingsCancelEditBtn').hidden = true;
    if (el('proceedingsFormStatus')) el('proceedingsFormStatus').textContent = '';
  }

  function fillProceedingsForm(p) {
    if (!p) return;
    if (el('proceedingsEditId')) el('proceedingsEditId').value = p.id || '';
    if (el('proceedingsFormTitle')) el('proceedingsFormTitle').textContent = `Edit register entry ${p.registerLabel || ''}`.trim();
    if (el('proceedingsTypeInput')) el('proceedingsTypeInput').value = p.meetingType || proceedingsState.type;
    fillProceedingsSubtypeSelect(p.meetingType || proceedingsState.type, p.meetingSubtype || 'regular');
    syncProceedingsQuorumField();
    if (el('proceedingsDateInput')) el('proceedingsDateInput').value = (p.meetingDate || '').slice(0, 10);
    if (el('proceedingsTimeInput')) el('proceedingsTimeInput').value = p.meetingTime || '';
    if (el('proceedingsTitleInput')) el('proceedingsTitleInput').value = p.title || '';
    if (el('proceedingsVenueInput')) el('proceedingsVenueInput').value = p.venue || '';
    if (el('proceedingsChairInput')) el('proceedingsChairInput').value = p.chairPerson || '';
    if (el('proceedingsPresentInput')) el('proceedingsPresentInput').value = p.membersPresent || '';
    if (el('proceedingsAbsentInput')) el('proceedingsAbsentInput').value = p.membersAbsent || '';
    if (el('proceedingsQuorumInput')) {
      el('proceedingsQuorumInput').value = p.quorumMet === true ? '1' : (p.quorumMet === false ? '0' : '');
    }
    if (el('proceedingsStatusInput')) el('proceedingsStatusInput').value = p.status || 'draft';
    if (el('proceedingsAgendaInput')) el('proceedingsAgendaInput').value = p.agenda || '';
    if (el('proceedingsBodyInput')) el('proceedingsBodyInput').value = p.proceedingsBody || '';
    if (el('proceedingsNextDateInput')) el('proceedingsNextDateInput').value = (p.nextMeetingDate || '').slice(0, 10);
    if (el('proceedingsSignedInput')) el('proceedingsSignedInput').value = p.signedBy || '';
    if (el('proceedingsResolutionsList')) {
      el('proceedingsResolutionsList').innerHTML = '';
      (p.resolutions || []).forEach((r) => addProceedingsResolutionRow(r));
    }
    if (el('proceedingsActionsList')) {
      el('proceedingsActionsList').innerHTML = '';
      (p.actionItems || []).forEach((a) => addProceedingsActionRow(a));
    }
    if (el('proceedingsCancelEditBtn')) el('proceedingsCancelEditBtn').hidden = false;
    if (el('proceedingsFormStatus')) el('proceedingsFormStatus').textContent = '';
    showProceedingsDetail(false);
    el('proceedingsManageBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadProceedings() {
    if (el('proceedingsManageBlock')) {
      el('proceedingsManageBlock').hidden = !hasEntitlement('manage_proceedings');
    }
    syncProceedingsRegisterTabs();
    const qs = new URLSearchParams({ meetingType: proceedingsState.type });
    const year = el('proceedingsYearFilter')?.value || '';
    const search = el('proceedingsSearchInput')?.value.trim() || '';
    if (year) qs.set('year', year);
    if (search) qs.set('search', search);
    if (hasEntitlement('manage_proceedings')) {
      const status = el('proceedingsStatusFilter')?.value || '';
      if (status) qs.set('status', status);
    }
    const statusLine = el('proceedingsListStatus');
    if (statusLine) statusLine.textContent = 'Loading register…';
    const data = await api(`/api/rwa/proceedings?${qs.toString()}`);
    proceedingsState.meta = {
      meetingTypes: data.meetingTypes,
      subtypes: data.subtypes,
      statuses: data.statuses,
    };
    proceedingsState.items = data.proceedings || [];
    fillProceedingsYearFilter(proceedingsState.items);
    renderProceedingsList();
    showProceedingsDetail(false);
  }

  async function saveProceedingsForm(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_proceedings')) return;
    const statusLine = el('proceedingsFormStatus');
    const saveBtn = el('proceedingsSaveBtn');
    const title = String(el('proceedingsTitleInput')?.value || '').trim();
    const meetingDate = el('proceedingsDateInput')?.value || '';
    if (!title || !meetingDate) {
      if (statusLine) statusLine.textContent = 'Title and meeting date are required.';
      return;
    }
    const meetingType = el('proceedingsTypeInput')?.value || proceedingsState.type;
    const quorumVal = el('proceedingsQuorumInput')?.value;
    const payload = {
      title,
      meetingDate,
      meetingType,
      meetingSubtype: el('proceedingsSubtypeInput')?.value || 'regular',
      meetingTime: el('proceedingsTimeInput')?.value.trim() || '',
      venue: el('proceedingsVenueInput')?.value.trim() || '',
      chairPerson: el('proceedingsChairInput')?.value.trim() || '',
      membersPresent: el('proceedingsPresentInput')?.value.trim() || '',
      membersAbsent: el('proceedingsAbsentInput')?.value.trim() || '',
      agenda: el('proceedingsAgendaInput')?.value.trim() || '',
      proceedingsBody: el('proceedingsBodyInput')?.value.trim() || '',
      nextMeetingDate: el('proceedingsNextDateInput')?.value || '',
      signedBy: el('proceedingsSignedInput')?.value.trim() || '',
      status: el('proceedingsStatusInput')?.value || 'draft',
      resolutions: collectProceedingsResolutions(),
      actionItems: collectProceedingsActions(),
    };
    if (meetingType === 'gh' && quorumVal !== '') payload.quorumMet = quorumVal === '1';
    const editId = String(el('proceedingsEditId')?.value || '').trim();
    if (editId) payload.id = editId;
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving to register…';
    try {
      const data = editId
        ? await api(`/api/rwa/proceedings/${encodeURIComponent(editId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })
        : await api('/api/rwa/proceedings', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      resetProceedingsForm();
      proceedingsState.type = data.proceeding?.meetingType || meetingType;
      syncProceedingsRegisterTabs();
      await loadProceedings();
      if (data.proceeding?.id) await openProceedingsDetail(data.proceeding.id);
      if (statusLine) statusLine.textContent = 'Saved.';
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function printProceedingsDetail() {
    const p = proceedingsState.selected;
    if (!p) {
      window.alert('Open a register entry first, then print.');
      return;
    }
    const html = buildProceedingsMomHtml(p);
    const paperRaw = (el('proceedingsPaperSize')?.value || 'a4').toLowerCase();
    const paperMap = {
      a4: 'A4 portrait',
      a5: 'A5 portrait',
      letter: 'letter portrait',
      legal: 'legal portrait',
    };
    const paper = paperMap[paperRaw] ? paperRaw : 'a4';
    try { localStorage.setItem('mhws-mom-paper', paper); } catch (_) {}

    const docHtml = `<!DOCTYPE html><html lang="en" class="pad-mom" data-paper="${paper}"><head><meta charset="utf-8">
      <title>${escapeHtml(p.title || 'Proceedings')}</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Source+Sans+3:wght@500;600;700&display=swap" rel="stylesheet">
      <link rel="stylesheet" href="${location.origin}/documents/proceedings-mom-print.css?v=20260817pad4">
      <link rel="stylesheet" href="${location.origin}/documents/print-pad-common.css?v=20260817pad4">
      <style>@page { size: ${paperMap[paper]}; margin: 10mm; }</style>
      </head><body>${html}
      <script>
        (function(){
          function go(){ try { window.focus(); window.print(); } catch(e) {} }
          var links = Array.prototype.slice.call(document.querySelectorAll('link[rel=stylesheet]'));
          if (!links.length) { setTimeout(go, 200); return; }
          var left = links.length;
          function done(){ if (--left <= 0) setTimeout(go, 120); }
          links.forEach(function(l){ l.addEventListener('load', done); l.addEventListener('error', done); });
          setTimeout(go, 1800);
        })();
      <\/script>
      </body></html>`;

    // Prefer iframe print — avoids popup blockers and window.open(...,'noopener') returning null
    try {
      const iframe = document.createElement('iframe');
      iframe.setAttribute('title', 'Print proceedings');
      iframe.setAttribute('aria-hidden', 'true');
      iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;';
      document.body.appendChild(iframe);
      const idoc = iframe.contentWindow?.document;
      if (!idoc) throw new Error('iframe unavailable');
      idoc.open();
      idoc.write(docHtml);
      idoc.close();
      const cleanup = () => { try { iframe.remove(); } catch (_) {} };
      iframe.contentWindow?.addEventListener?.('afterprint', cleanup);
      setTimeout(cleanup, 120000);
      return;
    } catch (err) {
      console.warn('iframe print failed, trying popup', err);
    }

    // Fallback: popup without noopener (noopener makes window.open return null)
    const w = window.open('about:blank', '_blank');
    if (!w) {
      window.alert('Pop-up blocked. Allow pop-ups for this site, or use the blank MOM pad Print button.');
      return;
    }
    w.document.open();
    w.document.write(docHtml);
    w.document.close();
  }

  function parkingRouteQuery() {
    const raw = (location.hash || '').replace(/^#/, '');
    if (!raw.startsWith('parking')) return {};
    const q = raw.includes('?') ? raw.slice(raw.indexOf('?') + 1) : '';
    return Object.fromEntries(new URLSearchParams(q));
  }

  function parkingIsIdentityKind(kind) {
    return kind === 'adhoc' || kind === 'staff';
  }

  function parkingCardHtml(item, { ec = false } = {}) {
    const status = item.status || 'expired';
    const kind = item.kind || 'visitor';
    const identity = parkingIsIdentityKind(kind);
    const cls = [
      'parking-card',
      kind === 'member' ? 'is-member' : '',
      kind === 'tenant' ? 'is-tenant' : '',
      kind === 'visitor' ? 'is-visitor' : '',
      kind === 'adhoc' ? 'is-adhoc' : '',
      kind === 'staff' ? 'is-staff' : '',
      status === 'expired' ? 'is-expired' : '',
      status === 'pending_renewal' ? 'is-pending' : '',
      status === 'revoked' ? 'is-revoked' : '',
    ].filter(Boolean).join(' ');
    const who = item.tenantName || item.visitorName || item.memberName || '';
    const valid = item.permanent ? 'Permanent' : (item.expiresAtLabel || '—');
    const photo = item.hasPhoto && item.photoUrl
      ? `<img class="parking-card-face" src="${escapeHtml(item.photoUrl)}" alt="">`
      : '';
    const qr = item.qrDataUrl
      ? `<img class="parking-card-qr" src="${item.qrDataUrl}" alt="Pass QR">`
      : '';
    const plateLine = identity
      ? (item.categoryLabel || item.staffCategoryLabel || item.adhocCategoryLabel || item.kindLabel || 'Pass')
      : (item.plateDisplay || item.plate || '');
    const plotLine = kind === 'adhoc' ? 'Main gate' : `Plot ${escapeHtml(item.plotNo || item.houseId || '')}`;
    const extras = identity
      ? ''
      : (item.colour || item.vehicleTypeLabel ? ` · ${escapeHtml([item.vehicleTypeLabel, item.colour].filter(Boolean).join(' · '))}` : '');
    const removeLabel = kind === 'staff' ? 'End staff pass' : 'Remove vehicle';
    const title = escapeHtml(item.kindLabel || 'Pass');
    const titleBlock = identity && photo
      ? `<div class="parking-card-title-row"><p class="parking-card-title">${title}</p>${photo}</div>`
      : `<p class="parking-card-title">${title}</p>`;
    return `
      <article class="${cls}" data-id="${escapeHtml(item.id || '')}">
        <div class="parking-card-stripe"></div>
        <div class="parking-card-top">
          <div>
            <div class="parking-card-brand">Himuda Housing Colony Sanyard</div>
            ${titleBlock}
          </div>
          <div class="parking-card-chip" aria-hidden="true"></div>
        </div>
        <div class="parking-card-badge">${escapeHtml(item.statusLabel || status)}</div>
        <div class="parking-card-plate">${escapeHtml(plateLine)}</div>
        <div class="parking-card-meta">
          <div>
            <strong>${escapeHtml(who || '—')}</strong>
            ${plotLine}${extras}
            <span>Valid ${escapeHtml(valid)}</span>
            <span>${escapeHtml(item.code || '')}</span>
          </div>
          ${qr}
        </div>
      </article>
      <div class="parking-card-actions">
        ${item.canRenew ? `<button type="button" class="btn secondary compact parking-renew" data-id="${escapeHtml(item.id)}">${item.needsEcApproval ? 'Request EC renewal' : 'Renew pass'}</button>` : ''}
        ${parkingWalletLinks(item)}
        ${item.id ? `<button type="button" class="btn ghost compact parking-save-photo" data-id="${escapeHtml(item.id)}" data-code="${escapeHtml(item.code || '')}">Save photo</button>` : ''}
        ${item.canRemove ? `<button type="button" class="btn ghost compact parking-remove" data-id="${escapeHtml(item.id)}" data-kind="${escapeHtml(kind)}">${removeLabel}</button>` : ''}
        ${ec && status === 'pending_renewal' ? `<button type="button" class="btn primary compact parking-approve" data-id="${escapeHtml(item.id)}">Approve</button><button type="button" class="btn ghost compact parking-reject" data-id="${escapeHtml(item.id)}">Decline</button>` : ''}
        ${ec && (status === 'active' || status === 'pending_renewal') ? `<button type="button" class="btn ghost compact parking-revoke" data-id="${escapeHtml(item.id)}">Revoke</button>` : ''}
      </div>
      ${ec ? parkingUpgradeStaffPanelHtml(item) : ''}`;
  }

  function parkingDetailHtml(item) {
    if (!item) return '<p class="muted">No pass found.</p>';
    if (item.detailLevel === 'general' && !parkingIsIdentityKind(item.kind)) {
      const valid = Boolean(item.valid);
      return `<div class="parking-detail parking-detail-general ${valid ? 'is-valid' : 'is-invalid'}">
        <p class="parking-validity-flag">${valid ? 'Valid' : 'Not valid'}</p>
        <dl>
          <dt>Type</dt><dd>${escapeHtml(item.kindLabel || item.kind || 'Pass')}</dd>
          <dt>Validity</dt><dd>${escapeHtml(item.statusLabel || (valid ? 'Valid' : 'Not valid'))}${item.expiresAtLabel && item.expiresAtLabel !== '—' ? ` · ${escapeHtml(item.expiresAtLabel)}` : ''}</dd>
          <dt>Code</dt><dd>${escapeHtml(item.code || item.id || '—')}</dd>
        </dl>
      </div>`;
    }
    const identity = parkingIsIdentityKind(item.kind);
    const catLabel = item.categoryLabel || item.staffCategoryLabel || item.adhocCategoryLabel || '';
    const rows = [
      ['Kind', item.kindLabel],
      ['Status', item.statusLabel],
      identity ? ['Role', catLabel || '—'] : ['Vehicle', item.plateDisplay],
      identity ? null : ['Type / colour', [item.vehicleTypeLabel, item.colour].filter(Boolean).join(' · ') || '—'],
      ['Plot', item.kind === 'adhoc' ? 'Main gate' : (item.plotNo || item.houseId)],
      identity ? ['Sponsored by', item.memberName] : ['Registered by', item.memberName],
      ['Name', item.tenantName || item.visitorName || '—'],
      item.kind === 'tenant' ? ['Tenant phone', item.tenantPhone || '—'] : null,
      item.kind === 'staff' && item.tenantPhone ? ['Mobile', item.tenantPhone] : null,
      item.kind === 'tenant' ? ['Tenant email', item.tenantEmail || '—'] : null,
      item.kind === 'tenant' ? ['Note', item.tenantNote || '—'] : null,
      ['Pass code', item.code],
      ['Issued', item.issuedAtLabel],
      ['Valid until', item.expiresAtLabel],
    ].filter(Boolean);
    const face = item.hasPhoto && item.photoUrl
      ? `<img class="parking-detail-face" src="${escapeHtml(item.photoUrl)}" alt="">`
      : '';
    const title = identity
      ? (item.visitorName || item.kindLabel || 'Pass')
      : (item.plateDisplay || item.plate || 'Pass');
    return `<div class="parking-detail">
      ${face}
      <h4>${escapeHtml(title)}</h4>
      <dl>${rows.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || '—')}</dd>`).join('')}</dl>
      ${parkingWalletLinks(item) ? `<div class="parking-card-actions">${parkingWalletLinks(item)}</div>` : ''}
    </div>`;
  }

  function isAndroidDevice() {
    return /Android/i.test(navigator.userAgent || '');
  }

  function isAppleMobileDevice() {
    const ua = navigator.userAgent || '';
    return /iPhone|iPad|iPod/i.test(ua)
      || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  function parkingWalletHref(path) {
    if (!path) return '';
    const url = new URL(path, window.location.origin);
    const standalone = Boolean(window.navigator.standalone)
      || window.matchMedia('(display-mode: standalone)').matches;
    if (standalone) {
      const token = state.session?.token || loadStoredToken();
      if (token) url.searchParams.set('token', token);
    }
    return url.pathname + url.search;
  }

  function parkingWalletLinks(item) {
    const bits = [];
    if (item?.walletEnabled && item.walletUrl && !isAndroidDevice()) {
      const href = parkingWalletHref(item.walletUrl);
      if (href) bits.push(`<a class="btn compact parking-wallet" href="${escapeHtml(href)}">Add to iPhone Wallet</a>`);
    }
    if (item?.googleWalletEnabled && item.googleWalletUrl && !isAppleMobileDevice()) {
      const href = parkingWalletHref(item.googleWalletUrl);
      if (href) bits.push(`<a class="btn compact parking-wallet-google" href="${escapeHtml(href)}">Add to Google Wallet</a>`);
    }
    return bits.join('');
  }

  function fillParkingTenantSelect(tenants) {
    const sel = el('parkingTenantSelect');
    if (!sel) return;
    const current = sel.value;
    const active = (tenants || []).filter((t) => t.status !== 'ended');
    sel.innerHTML = '<option value="">Select a registered tenant</option>'
      + active.map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}${t.phone ? ` · ${escapeHtml(t.phone)}` : ''}</option>`).join('');
    if (current && [...sel.options].some((o) => o.value === current)) sel.value = current;
    const hint = el('parkingTenantHint');
    if (hint) {
      hint.innerHTML = active.length
        ? '<a href="#profile">Manage tenants in Profile</a> — occupancy records, not household logins.'
        : 'No current tenants. <a href="#profile">Add them in Profile → Tenants of this plot</a> first.';
    }
  }

  function fillParkingStaffCategories(categories) {
    if (Array.isArray(categories) && categories.length) {
      parkingStaffCategoriesCache = categories;
    }
    const sel = el('parkingStaffCategory');
    if (!sel || !Array.isArray(categories) || !categories.length) return;
    const current = sel.value || 'maid';
    sel.innerHTML = categories.map((c) => {
      const id = c.id || c;
      const label = c.label || String(id);
      return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
    }).join('');
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
  }

  let parkingStaffCategoriesCache = [];

  function parkingUpgradeStaffPanelHtml(item) {
    if (!item || item.kind !== 'adhoc') return '';
    if (!hasEntitlement('pass_upgrade_staff')) return '';
    const status = (item.status || '').toLowerCase();
    if (status !== 'active' && status !== 'expired') return '';
    const cats = parkingStaffCategoriesCache.length
      ? parkingStaffCategoriesCache
      : [
          { id: 'maid', label: 'Maid' },
          { id: 'cook', label: 'Cook' },
          { id: 'gardener', label: 'Gardener' },
          { id: 'driver', label: 'Driver' },
          { id: 'caretaker', label: 'Caretaker' },
          { id: 'other', label: 'Other' },
        ];
    const guess = String(item.category || item.adhocCategory || 'other').toLowerCase();
    const catOpts = cats.map((c) => {
      const id = c.id || c;
      const label = c.label || String(id);
      const sel = id === guess || (guess === 'delivery' && id === 'other') ? ' selected' : '';
      return `<option value="${escapeHtml(id)}"${sel}>${escapeHtml(label)}</option>`;
    }).join('');
    const pid = escapeHtml(item.id || '');
    return `
      <details class="parking-upgrade-staff">
        <summary>Convert to staff pass</summary>
        <form class="parking-upgrade-staff-form" data-pass-id="${pid}">
          <label>Plot / house id
            <input name="houseId" required autocomplete="off" placeholder="e.g. A-12 or house id">
          </label>
          <label>Role
            <select name="category">${catOpts}</select>
          </label>
          <label>Valid for
            <select name="months">
              <option value="1">1 month</option>
              <option value="3" selected>3 months</option>
              <option value="6">6 months</option>
              <option value="12">12 months</option>
            </select>
          </label>
          <label>Mobile <span class="muted">(optional)</span>
            <input name="phone" maxlength="16" inputmode="tel" autocomplete="tel" placeholder="10-digit number">
          </label>
          <button type="submit" class="btn primary compact">Upgrade to staff</button>
          <p class="muted parking-upgrade-staff-status" aria-live="polite"></p>
        </form>
      </details>`;
  }

  async function loadParkingPanel() {
    const list = el('parkingCardList');
    const status = el('parkingListStatus');
    const canManage = hasEntitlement('pass_manage');
    const hint = el('parkingValidateHint');
    if (hint) {
      hint.textContent = canManage
        ? 'Type a number, or scan the vehicle plate / QR. Pass · manage shows full details for every plot.'
        : 'Type a number, or scan the vehicle plate / QR. Everyone sees type, validity, and code; full details only for vehicles on your plot.';
    }
    if (status) status.textContent = 'Loading…';
    try {
      const data = await api('/api/rwa/parking/passes');
      if (el('parkingHours') && data.defaultHours) el('parkingHours').value = String(data.defaultHours);
      if (el('parkingDefaultHours') && data.defaultHours) el('parkingDefaultHours').value = String(data.defaultHours);
      if (el('parkingTenantMonths') && data.defaultMonths) el('parkingTenantMonths').value = String(data.defaultMonths);
      if (el('parkingStaffMonths') && (data.defaultStaffMonths || data.defaultMonths)) {
        el('parkingStaffMonths').value = String(data.defaultStaffMonths || data.defaultMonths);
      }
      fillParkingStaffCategories(data.staffCategories);
      fillParkingOcrSettings(data.ocr);
      fillParkingTenantSelect(data.tenants || []);
      const passes = data.passes || [];
      if (list) {
        list.innerHTML = passes.length
          ? passes.map((p) => parkingCardHtml(p)).join('')
          : '<p class="muted">No passes yet. Register a member vehicle, issue a visitor pass, or add household staff.</p>';
      }
      if (status) status.textContent = passes.length ? `${passes.length} pass(es)` : '';
      const pendingWrap = el('parkingPendingList');
      if (pendingWrap && canManage) {
        const pending = data.pending || [];
        pendingWrap.innerHTML = pending.length
          ? `<h4>Awaiting 2nd renewal</h4>${pending.map((p) => parkingCardHtml(p, { ec: true })).join('')}`
          : '';
      } else if (pendingWrap) {
        pendingWrap.innerHTML = '';
      }
      const adhocWrap = el('parkingAdhocList');
      if (adhocWrap && canManage) {
        const adhoc = data.adhoc || [];
        adhocWrap.innerHTML = adhoc.length
          ? `<h4>Recent ad-hoc gate passes</h4>${adhoc.map((p) => parkingCardHtml(p, { ec: true })).join('')}`
          : '';
      } else if (adhocWrap) {
        adhocWrap.innerHTML = '';
      }
      if (canManage) {
        loadParkingGatePoster().catch(() => {});
      }
      const q = parkingRouteQuery();
      const lookup = q.pass || q.q;
      if (lookup && hasEntitlement('pass_general')) {
        if (el('parkingLookupInput')) el('parkingLookupInput').value = lookup;
        await lookupParkingPass(lookup);
      }
    } catch (err) {
      if (list) list.innerHTML = `<p class="error">${escapeHtml(err.message || 'Could not load passes')}</p>`;
      if (status) status.textContent = err.message || 'Failed';
    }
  }

  let parkingGateMeta = { url: '/gate-pass.html#needs', qrDataUrl: '' };

  async function loadParkingGatePoster() {
    const img = el('parkingGateQrImg');
    const urlEl = el('parkingGateUrl');
    const openLink = el('parkingGateOpenLink');
    const shareBtn = el('parkingGateShareBtn');
    try {
      const data = await api('/api/rwa/parking/gate');
      const url = data.url || `${window.location.origin}/gate-pass.html#needs`;
      parkingGateMeta = { url, qrDataUrl: data.qrDataUrl || '' };
      if (urlEl) urlEl.textContent = url;
      if (openLink) openLink.href = url;
      if (img && data.qrDataUrl) {
        img.src = data.qrDataUrl;
        img.hidden = false;
      }
      if (shareBtn) shareBtn.hidden = !(navigator.share || navigator.clipboard);
    } catch (_err) {
      parkingGateMeta = { url: `${window.location.origin}/gate-pass.html#needs`, qrDataUrl: '' };
      if (urlEl) urlEl.textContent = parkingGateMeta.url;
      if (openLink) openLink.href = parkingGateMeta.url;
    }
  }

  function printParkingGatePoster() {
    const url = parkingGateMeta.url || `${window.location.origin}/gate-pass.html#needs`;
    const qr = parkingGateMeta.qrDataUrl || el('parkingGateQrImg')?.src || '';
    if (!qr) {
      window.alert('Connect QR is still loading. Try again in a moment.');
      return;
    }
    const win = window.open('', '_blank', 'noopener,noreferrer,width=720,height=960');
    if (!win) {
      window.alert('Allow pop-ups to print the connect poster.');
      return;
    }
    win.document.write(`<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Connect QR — Himuda Housing Colony Sanyard</title>
<style>
  @page { margin: 12mm; }
  body { margin: 0; font-family: Georgia, "Times New Roman", serif; color: #15233f; background: #fff; }
  .sheet { max-width: 180mm; margin: 0 auto; padding: 10mm 8mm; text-align: center; }
  h1 { font-size: 26pt; margin: 0 0 4mm; line-height: 1.15; }
  h2 { font-size: 15pt; font-weight: 600; margin: 0 0 8mm; color: #5c564e; }
  .hi { font-family: "Noto Sans Devanagari", "Mangal", sans-serif; }
  img.qr { width: 105mm; height: 105mm; object-fit: contain; border: 1px solid #ddd; padding: 4mm; background: #fff; }
  .steps { text-align: left; margin: 8mm auto 0; max-width: 145mm; font-size: 11.5pt; line-height: 1.45; }
  .steps li { margin: 2mm 0; }
  .url { margin-top: 7mm; font-size: 10pt; word-break: break-all; color: #5c564e; }
  .foot { margin-top: 6mm; font-size: 9pt; color: #7a7368; }
</style></head><body>
  <div class="sheet">
    <h1>Connect with Housing Colony Sanyard</h1>
    <h2 class="hi">हाउसिंग कॉलोनी सनयार्ड से जुड़ें</h2>
    <img class="qr" src="${qr}" alt="Connect QR">
    <ol class="steps">
      <li><strong>Service needs</strong> — see what residents need; leave your contact.</li>
      <li class="hi"><strong>सेवा आवश्यकताएँ</strong> — निवासियों की ज़रूरत देखें; संपर्क छोड़ें।</li>
      <li><strong>Businesses</strong> — register a service for the colony.</li>
      <li class="hi"><strong>व्यवसाय</strong> — कॉलोनी के लिए सेवा दर्ज करें।</li>
      <li><strong>Gate pass</strong> — selfie + name for short visitors (max 9 hours).</li>
      <li class="hi"><strong>गेट पास</strong> — सेल्फी + नाम (अधिकतम 9 घंटे)।</li>
    </ol>
    <p class="url">${url.replace(/</g, '&lt;')}</p>
    <p class="foot">Himuda Housing Colony Sanyard · Mandi · housingcolonysanyard.in</p>
  </div>
  <script>
    window.onload = function () {
      setTimeout(function () { window.print(); }, 250);
    };
  <\/script>
</body></html>`);
    win.document.close();
  }

  async function shareParkingGateLink() {
    const url = parkingGateMeta.url || `${window.location.origin}/gate-pass.html#needs`;
    const title = 'Connect with Housing Colony Sanyard';
    const text = 'Service needs · register a business · gate pass — Himuda Housing Colony Sanyard';
    try {
      if (navigator.share) {
        await navigator.share({ title, text, url });
        return;
      }
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        window.alert('Connect page link copied.');
        return;
      }
    } catch (err) {
      if (err && err.name === 'AbortError') return;
    }
    window.prompt('Copy this connect link:', url);
  }

  async function saveParkingCardPhoto(id, code) {
    const token = state.session?.token || loadStoredToken();
    const url = new URL(`/api/rwa/parking/passes/${encodeURIComponent(id)}/card.png`, window.location.origin);
    if (code) url.searchParams.set('code', code);
    const standalone = Boolean(window.navigator.standalone)
      || window.matchMedia('(display-mode: standalone)').matches;
    if (standalone && token) url.searchParams.set('token', token);
    const res = await fetch(url.pathname + url.search, {
      credentials: 'same-origin',
      headers: token ? { 'X-RWA-Token': token } : {},
    });
    if (!res.ok) {
      let data = {};
      try { data = await res.json(); } catch (_e) { data = {}; }
      throw new Error(friendlyApiError(res, data));
    }
    const blob = await res.blob();
    const filename = `${String(code || 'sanyard-pass').replace(/[^\w.-]+/g, '-')}.png`;
    const file = new File([blob], filename, { type: 'image/png' });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: 'Pass card' });
        return;
      } catch (err) {
        if (err && err.name === 'AbortError') return;
      }
    }
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 4000);
  }

  async function issueParkingPass(payload, statusEl) {
    if (statusEl) statusEl.textContent = 'Issuing…';
    const data = await api('/api/rwa/parking/passes', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    const mailed = data.pass?.emailDelivery?.channel === 'email';
    if (statusEl) {
      statusEl.textContent = mailed
        ? 'Pass issued and emailed. It is listed below.'
        : (data.pass?.emailDelivery?.reason === 'no_email'
          ? 'Pass issued. Add an email on Profile to receive a copy.'
          : 'Pass issued and listed below.');
    }
    await loadParkingPanel();
    return data.pass;
  }

  async function lookupParkingPass(query, extra = {}) {
    const status = el('parkingLookupStatus');
    if (status) status.textContent = 'Looking up…';
    try {
      const params = new URLSearchParams({ q: String(query || '').trim() });
      if (extra.ocr && parkingOcr().fuzzy) params.set('ocr', '1');
      const cands = (extra.candidates || []).map((c) => String(c || '').trim()).filter(Boolean);
      if (cands.length) params.set('candidates', cands.slice(0, 8).join(','));
      const data = await api(`/api/rwa/parking/lookup?${params.toString()}`);
      applyParkingLookupResult(data, query);
    } catch (err) {
      applyParkingLookupError(err);
    }
  }

  function applyParkingLookupError(err) {
    const status = el('parkingLookupStatus');
    const box = el('parkingLookupResult');
    if (status) status.textContent = err.message || 'Lookup failed';
    if (box) box.innerHTML = `<p class="error">${escapeHtml(err.message || 'Lookup failed')}</p>`;
  }

  function applyParkingLookupResult(data, query) {
    const status = el('parkingLookupStatus');
    const box = el('parkingLookupResult');
    const match = data.match || {};
    const fuzzy = match.kind && match.kind !== 'exact';
    if (status) {
      if (!data.pass) status.textContent = data.error || 'No pass found.';
      else if (fuzzy) status.textContent = `Closest registered plate: ${data.pass.plateDisplay || match.plate || query}. Confirm visually.`;
      else status.textContent = 'Match found.';
    }
    if (box) {
      if (!data.pass) {
        box.innerHTML = `<p class="muted">${escapeHtml(data.error || 'No pass found.')}</p>`;
      } else {
        const note = fuzzy
          ? `<p class="parking-ocr-note">OCR was not exact — confirm this is <strong>${escapeHtml(data.pass.plateDisplay || match.plate || '')}</strong> before waving through.</p>`
          : '';
        if (data.pass.detailLevel === 'general') {
          box.innerHTML = `${note}${parkingDetailHtml(data.pass)}${parkingUpgradeStaffPanelHtml(data.pass)}`;
        } else if (data.pass.detailLevel === 'manage') {
          box.innerHTML = `${note}${parkingDetailHtml(data.pass)}${parkingCardHtml(data.pass, { ec: true })}`;
        } else {
          box.innerHTML = `${note}${parkingDetailHtml(data.pass)}${parkingCardHtml(data.pass, { ec: false })}${parkingUpgradeStaffPanelHtml(data.pass)}`;
        }
      }
    }
  }

  function extractIndianPlates(text) {
    let compact = String(text || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    compact = compact.replace(/INDIA/g, '').replace(/IND/g, '');
    const patterns = [
      /([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{3,4})/g,
      /(\d{2}BH\d{4}[A-Z]{1,2})/g,
      /([A-Z]{2})(\d{2})(\d{4})/g,
    ];
    const found = [];
    const seen = new Set();
    const add = (plate) => {
      const key = String(plate || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (key.length >= 6 && key.length <= 12 && !seen.has(key)) {
        seen.add(key);
        found.push(key);
      }
    };
    for (const re of patterns) {
      let m;
      while ((m = re.exec(compact)) !== null) add(m[0]);
    }
    if (compact.length >= 6 && compact.length <= 12) add(compact);
    found.sort((a, b) => b.length - a.length);
    return found.filter((plate, _i, all) => !all.some((keep) => keep !== plate && keep.startsWith(plate)));
  }

  function extractIndianPlate(text) {
    return extractIndianPlates(text)[0] || '';
  }

  function parseParkingQrPayload(raw) {
    let q = String(raw || '').trim();
    if (!q) return '';
    try {
      const url = new URL(q, window.location.origin);
      const hash = (url.hash || '').replace(/^#/, '');
      if (hash.startsWith('parking')) {
        const qs = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '';
        const params = new URLSearchParams(qs);
        q = params.get('pass') || params.get('q') || q;
      } else {
        const params = new URLSearchParams(url.search);
        q = params.get('pass') || params.get('q') || q;
      }
    } catch (_e) {
      /* plain text QR */
    }
    const code = q.match(/(MP|VP|TP|AP)-[A-Z0-9]+/i);
    if (code) return code[0].toUpperCase();
    const plate = extractIndianPlate(q);
    return plate || q;
  }

  const PARKING_OCR_DEFAULTS = {
    phone: true,
    live: true,
    fuzzy: true,
    server: true,
    rust: false,
    engines: { tesseract: false, rust: false },
  };

  function parkingOcr() {
    return { ...PARKING_OCR_DEFAULTS, ...(state.parkingOcr || {}) };
  }

  function parkingOcrServerEnabled() {
    const ocr = parkingOcr();
    return Boolean(ocr.server || ocr.rust);
  }

  function fillParkingOcrSettings(ocr) {
    if (!ocr || typeof ocr !== 'object') return;
    const on = (v, fallback) => {
      if (v === undefined || v === null) return fallback;
      return v === true || v === 1 || v === '1' || v === 'true' || v === 'yes' || v === 'on';
    };
    const opts = {
      ...PARKING_OCR_DEFAULTS,
      phone: on(ocr.phone, PARKING_OCR_DEFAULTS.phone),
      live: on(ocr.live, PARKING_OCR_DEFAULTS.live),
      fuzzy: on(ocr.fuzzy, PARKING_OCR_DEFAULTS.fuzzy),
      server: on(ocr.server, PARKING_OCR_DEFAULTS.server),
      rust: on(ocr.rust, PARKING_OCR_DEFAULTS.rust),
      engines: { ...PARKING_OCR_DEFAULTS.engines, ...(ocr.engines || {}) },
    };
    state.parkingOcr = opts;
    const setCheck = (id, value) => {
      const box = el(id);
      if (box) box.checked = Boolean(value);
    };
    setCheck('parkingOcrPhone', opts.phone);
    setCheck('parkingOcrLive', opts.live);
    setCheck('parkingOcrFuzzy', opts.fuzzy);
    setCheck('parkingOcrServer', opts.server);
    setCheck('parkingOcrRust', opts.rust);
    const engines = opts.engines || {};
    const serverAvail = el('parkingOcrServerAvail');
    if (serverAvail) {
      serverAvail.textContent = engines.tesseract ? '(installed)' : '(not installed on server yet)';
    }
    const rustAvail = el('parkingOcrRustAvail');
    if (rustAvail) {
      rustAvail.textContent = engines.rust
        ? '(binary ready at data/bin/plate-ocr)'
        : '(build plate-ocr and copy to data/bin/plate-ocr)';
    }
  }

  function readParkingOcrForm() {
    return {
      phone: Boolean(el('parkingOcrPhone')?.checked),
      live: Boolean(el('parkingOcrLive')?.checked),
      fuzzy: Boolean(el('parkingOcrFuzzy')?.checked),
      server: Boolean(el('parkingOcrServer')?.checked),
      rust: Boolean(el('parkingOcrRust')?.checked),
    };
  }

  let parkingTesseractPromise = null;
  let parkingOcrWorker = null;
  let parkingScan = {
    mode: 'plate',
    stream: null,
    timer: 0,
    busy: false,
    lastPlate: '',
    hits: 0,
    variant: 0,
    votes: {},
    ticks: 0,
    serverTried: false,
  };

  async function loadParkingTesseract() {
    if (window.Tesseract?.createWorker || window.Tesseract?.recognize) return window.Tesseract;
    if (parkingTesseractPromise) return parkingTesseractPromise;
    parkingTesseractPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-parking-ocr="1"]');
      if (existing && (window.Tesseract?.createWorker || window.Tesseract?.recognize)) {
        resolve(window.Tesseract);
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js';
      script.async = true;
      script.dataset.parkingOcr = '1';
      script.onload = () => {
        if (window.Tesseract?.createWorker || window.Tesseract?.recognize) resolve(window.Tesseract);
        else reject(new Error('Plate reader failed to load'));
      };
      script.onerror = () => reject(new Error('Could not load plate reader. Check network, or type the number.'));
      document.head.appendChild(script);
    });
    return parkingTesseractPromise;
  }

  async function getParkingOcrWorker() {
    if (parkingOcrWorker) return parkingOcrWorker;
    const Tesseract = await loadParkingTesseract();
    if (typeof Tesseract.createWorker === 'function') {
      parkingOcrWorker = await Tesseract.createWorker('eng', 1, { logger() {} });
      await parkingOcrWorker.setParameters({
        tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
        tessedit_pageseg_mode: '7',
        user_defined_dpi: '300',
      });
      return parkingOcrWorker;
    }
    return Tesseract;
  }

  function setParkingScanLive(text) {
    const live = el('parkingScanLive');
    if (live) live.textContent = text || '';
  }

  function stopParkingScanner() {
    if (parkingScan.timer) {
      clearInterval(parkingScan.timer);
      parkingScan.timer = 0;
    }
    parkingScan.busy = false;
    parkingScan.lastPlate = '';
    parkingScan.hits = 0;
    parkingScan.votes = {};
    parkingScan.ticks = 0;
    parkingScan.serverTried = false;
    const video = el('parkingScanVideo');
    if (video) {
      video.pause();
      video.srcObject = null;
    }
    if (parkingScan.stream) {
      parkingScan.stream.getTracks().forEach((t) => t.stop());
      parkingScan.stream = null;
    }
    const dialog = el('parkingScanDialog');
    if (dialog?.open) dialog.close();
  }

  function scalePlateCanvas(src, minHeight) {
    const h = Math.max(minHeight, src.height || 0);
    const scale = h / Math.max(1, src.height || 1);
    const w = Math.max(32, Math.round((src.width || 1) * scale));
    const out = document.createElement('canvas');
    out.width = w;
    out.height = h;
    const ctx = out.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(src, 0, 0, w, h);
    return out;
  }

  function otsuThreshold(gray) {
    const hist = new Array(256).fill(0);
    for (let i = 0; i < gray.length; i += 1) hist[gray[i]] += 1;
    const total = gray.length || 1;
    let sum = 0;
    for (let i = 0; i < 256; i += 1) sum += i * hist[i];
    let sumB = 0;
    let wB = 0;
    let max = 0;
    let thresh = 128;
    for (let t = 0; t < 256; t += 1) {
      wB += hist[t];
      if (!wB) continue;
      const wF = total - wB;
      if (!wF) break;
      sumB += t * hist[t];
      const mB = sumB / wB;
      const mF = (sum - sumB) / wF;
      const between = wB * wF * (mB - mF) * (mB - mF);
      if (between > max) {
        max = between;
        thresh = t;
      }
    }
    return thresh;
  }

  function rotatePlateCanvas(src, degrees) {
    if (!degrees) return src;
    const rad = (degrees * Math.PI) / 180;
    const sin = Math.abs(Math.sin(rad));
    const cos = Math.abs(Math.cos(rad));
    const w = src.width;
    const h = src.height;
    const out = document.createElement('canvas');
    out.width = Math.max(32, Math.round(w * cos + h * sin));
    out.height = Math.max(16, Math.round(w * sin + h * cos));
    const ctx = out.getContext('2d', { willReadFrequently: true });
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.translate(out.width / 2, out.height / 2);
    ctx.rotate(rad);
    ctx.drawImage(src, -w / 2, -h / 2);
    return out;
  }

  function binarizePlateCanvas(src, { invert = false, threshold = 0 } = {}) {
    const canvas = document.createElement('canvas');
    canvas.width = src.width;
    canvas.height = src.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(src, 0, 0);
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const d = img.data;
    let min = 255;
    let max = 0;
    const gray = new Uint8Array(d.length / 4);
    for (let i = 0, p = 0; i < d.length; i += 4, p += 1) {
      const g = Math.round(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]);
      gray[p] = g;
      if (g < min) min = g;
      if (g > max) max = g;
    }
    const span = Math.max(1, max - min);
    const cut = threshold || otsuThreshold(gray);
    for (let p = 0, i = 0; p < gray.length; p += 1, i += 4) {
      let v = ((gray[p] - min) / span) * 255;
      v = v > cut ? 255 : 0;
      if (invert) v = 255 - v;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
    ctx.putImageData(img, 0, 0);
    return canvas;
  }

  function cropParkingGuideFrame(video, canvas, mode, bandShift = 0) {
    const vw = video.videoWidth || 0;
    const vh = video.videoHeight || 0;
    if (!vw || !vh) return null;
    let sx; let sy; let sw; let sh;
    if (mode === 'qr') {
      sw = Math.floor(vw * 0.55);
      sh = Math.floor(vh * 0.45);
      sx = Math.floor((vw - sw) / 2);
      sy = Math.floor((vh - sh) / 2);
    } else {
      sw = Math.floor(vw * 0.88);
      sh = Math.floor(sw / 4.4);
      sx = Math.floor((vw - sw) / 2);
      sy = Math.floor((vh - sh) * (0.48 + bandShift));
      sy = Math.max(0, Math.min(vh - sh, sy));
    }
    canvas.width = sw;
    canvas.height = sh;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
    return canvas;
  }

  async function ocrPlateCanvas(canvas, { allVariants = false } = {}) {
    if (!parkingOcr().phone) return [];
    const worker = await getParkingOcrWorker();
    const scaled = scalePlateCanvas(canvas, 144);
    const bases = allVariants
      ? [scaled, rotatePlateCanvas(scaled, -4), rotatePlateCanvas(scaled, 4)]
      : [parkingScan.variant % 3 === 1 ? rotatePlateCanvas(scaled, -4)
        : parkingScan.variant % 3 === 2 ? rotatePlateCanvas(scaled, 4)
        : scaled];
    const variants = [];
    bases.forEach((img) => {
      variants.push(binarizePlateCanvas(img));
      if (allVariants || parkingScan.variant % 2 === 1) {
        variants.push(binarizePlateCanvas(img, { invert: true }));
      }
    });
    parkingScan.variant += 1;
    const found = [];
    const seen = new Set();
    const add = (plate) => {
      if (plate && !seen.has(plate)) {
        seen.add(plate);
        found.push(plate);
      }
    };
    for (const variant of variants) {
      let text = '';
      if (worker.recognize && worker.setParameters) {
        const result = await worker.recognize(variant);
        text = result?.data?.text || '';
      } else {
        const Tesseract = await loadParkingTesseract();
        const result = await Tesseract.recognize(variant, 'eng');
        text = result?.data?.text || '';
      }
      extractIndianPlates(text).forEach(add);
      if (found.length && !allVariants) break;
    }
    return found;
  }

  function mergePlateCandidates(...lists) {
    const found = [];
    const seen = new Set();
    lists.flat().forEach((plate) => {
      const key = String(plate || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (key.length >= 6 && key.length <= 12 && !seen.has(key)) {
        seen.add(key);
        found.push(key);
      }
    });
    return found;
  }

  function canvasToJpegBlob(canvas, quality = 0.85) {
    return new Promise((resolve, reject) => {
      if (typeof canvas.toBlob !== 'function') {
        reject(new Error('Could not capture frame'));
        return;
      }
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Could not capture frame'));
      }, 'image/jpeg', quality);
    });
  }

  async function ocrPlateOnServer(blob, candidates = []) {
    if (!blob || !parkingOcrServerEnabled()) return null;
    const body = new FormData();
    body.append('image', blob, 'plate.jpg');
    if (candidates.length) body.append('candidates', candidates.slice(0, 8).join(','));
    try {
      return await api('/api/rwa/parking/ocr', { method: 'POST', body });
    } catch (_err) {
      return null;
    }
  }

  async function finishParkingScanFromOcr(data, fallbackQuery, candidates) {
    const q = (data?.candidates && data.candidates[0]) || fallbackQuery || '';
    if (data?.pass) {
      stopParkingScanner();
      if (el('parkingLookupInput') && q) el('parkingLookupInput').value = q;
      applyParkingLookupResult(data, q);
      return true;
    }
    if (q) {
      await finishParkingScan(q, { ocr: true, candidates: mergePlateCandidates(candidates, data?.candidates) });
      return true;
    }
    return false;
  }

  async function recognizePlateFromCanvas(canvas) {
    const plates = await ocrPlateCanvas(canvas);
    return plates[0] || '';
  }

  function parkingScanTopVotes() {
    return Object.entries(parkingScan.votes || {})
      .sort((a, b) => b[1] - a[1])
      .map(([plate]) => plate);
  }

  async function finishParkingScan(value, extra = {}) {
    const q = String(value || '').trim();
    if (!q) return;
    const fromQr = parkingScan.mode === 'qr';
    const candidates = extra.candidates || parkingScanTopVotes();
    const ocr = !fromQr || Boolean(extra.ocr);
    stopParkingScanner();
    if (el('parkingLookupInput')) el('parkingLookupInput').value = q;
    if (el('parkingLookupStatus')) {
      el('parkingLookupStatus').textContent = fromQr
        ? `QR read: ${q}. Looking up…`
        : `Plate read: ${q}. Looking up…`;
    }
    await lookupParkingPass(q, { ocr, candidates });
  }

  async function tickParkingScanner() {
    if (parkingScan.busy) return;
    const video = el('parkingScanVideo');
    const canvas = el('parkingScanCanvas');
    if (!video || !canvas || video.readyState < 2) return;
    parkingScan.busy = true;
    try {
      const frame = cropParkingGuideFrame(video, canvas, parkingScan.mode);
      if (!frame) return;
      if (parkingScan.mode === 'qr') {
        if (!('BarcodeDetector' in window)) {
          setParkingScanLive('QR not supported here — use photo or type the code.');
          return;
        }
        const detector = new BarcodeDetector({ formats: ['qr_code'] });
        const codes = await detector.detect(frame);
        const raw = (codes[0] && (codes[0].rawValue || codes[0].raw_value)) || '';
        if (raw) {
          const q = parseParkingQrPayload(raw);
          if (q) {
            setParkingScanLive(`Found ${q}`);
            await finishParkingScan(q);
          }
        } else {
          setParkingScanLive('Point at the QR on the pass card…');
        }
        return;
      }
      setParkingScanLive('Looking for number plate…');
      parkingScan.ticks = (parkingScan.ticks || 0) + 1;
      const shifts = [0, -0.08, 0.08];
      const shift = shifts[parkingScan.variant % shifts.length];
      const plateFrame = cropParkingGuideFrame(video, canvas, 'plate', shift) || frame;
      const plates = await ocrPlateCanvas(plateFrame);
      plates.forEach((plate) => {
        parkingScan.votes[plate] = (parkingScan.votes[plate] || 0) + 1;
      });
      const ranked = parkingScanTopVotes();
      const best = ranked[0];
      const votes = best ? (parkingScan.votes[best] || 0) : 0;
      if (best) setParkingScanLive(`Reading ${best}${votes < 2 ? ' — hold steady…' : ''}`);
      else setParkingScanLive('Align the plate in the yellow frame…');
      if (votes >= 2) {
        await finishParkingScan(best, { ocr: true, candidates: ranked });
        return;
      }
      if (!parkingScan.serverTried && parkingScan.ticks >= (parkingOcr().phone ? 5 : 2)) {
        parkingScan.serverTried = true;
        setParkingScanLive('Trying the server plate reader…');
        try {
          const blob = await canvasToJpegBlob(plateFrame);
          const server = await ocrPlateOnServer(blob, ranked);
          if (await finishParkingScanFromOcr(server, best, ranked)) return;
        } catch (_err) { /* keep scanning on device */ }
        setParkingScanLive(best ? `Reading ${best} — hold steady…` : 'Align the plate in the yellow frame…');
      }
    } catch (err) {
      setParkingScanLive(err.message || 'Scanner busy…');
    } finally {
      parkingScan.busy = false;
    }
  }

  async function openParkingScanner(mode) {
    parkingScan.mode = mode === 'qr' ? 'qr' : 'plate';
    const dialog = el('parkingScanDialog');
    const title = el('parkingScanTitle');
    const hint = el('parkingScanHint');
    const frame = el('parkingScanFrame');
    const video = el('parkingScanVideo');
    if (!dialog || !video) {
      if (mode === 'qr') el('parkingScanQrFile')?.click();
      else el('parkingScanPlateFile')?.click();
      return;
    }
    if (title) title.textContent = parkingScan.mode === 'qr' ? 'Scan pass QR' : 'Scan vehicle plate';
    if (hint) {
      const ocr = parkingOcr();
      if (parkingScan.mode === 'qr') {
        hint.textContent = 'Centre the QR from the pass card in the square. It will read automatically.';
      } else if (!ocr.phone && !parkingOcrServerEnabled()) {
        hint.textContent = 'Plate reading is turned off in Pass settings. Type the registration number instead.';
      } else if (!ocr.live) {
        hint.textContent = 'Align the number plate inside the yellow frame, then tap Read now.';
      } else if (!ocr.phone && parkingOcrServerEnabled()) {
        hint.textContent = 'Align the number plate. The server reader will identify the registration.';
      } else {
        hint.textContent = 'Align the number plate inside the yellow frame. The camera will identify the registration.';
      }
    }
    if (frame) frame.dataset.mode = parkingScan.mode;
    parkingScan.votes = {};
    parkingScan.variant = 0;
    parkingScan.hits = 0;
    parkingScan.lastPlate = '';
    parkingScan.ticks = 0;
    parkingScan.serverTried = false;
    setParkingScanLive('Starting camera…');
    if (!dialog.open) dialog.showModal();
    try {
      if (parkingScan.stream) {
        parkingScan.stream.getTracks().forEach((t) => t.stop());
        parkingScan.stream = null;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });
      parkingScan.stream = stream;
      try {
        const track = stream.getVideoTracks()[0];
        const caps = track?.getCapabilities?.() || {};
        const extra = {};
        if (caps.focusMode && caps.focusMode.includes('continuous')) extra.focusMode = 'continuous';
        if (Object.keys(extra).length) await track.applyConstraints(extra);
      } catch (_e) { /* torch/focus optional */ }
      video.srcObject = stream;
      await video.play();
      setParkingScanLive(parkingScan.mode === 'qr' ? 'Point at the QR…' : 'Align the number plate…');
      if (parkingScan.timer) clearInterval(parkingScan.timer);
      const ocr = parkingOcr();
      const livePlate = parkingScan.mode === 'plate' && ocr.live && (ocr.phone || parkingOcrServerEnabled());
      if (parkingScan.mode === 'qr' || livePlate) {
        parkingScan.timer = window.setInterval(
          () => { tickParkingScanner().catch(() => {}); },
          parkingScan.mode === 'qr' ? 650 : 900,
        );
      } else if (parkingScan.mode === 'plate') {
        setParkingScanLive('Align the plate, then tap Read now.');
      }
      if (parkingScan.mode === 'plate' && ocr.phone) getParkingOcrWorker().catch(() => {});
    } catch (err) {
      setParkingScanLive(err.message || 'Camera unavailable');
      if (el('parkingLookupStatus')) {
        el('parkingLookupStatus').textContent = 'Camera unavailable — use photo instead, or type the number.';
      }
    }
  }

  async function captureParkingScanNow() {
    const video = el('parkingScanVideo');
    const canvas = el('parkingScanCanvas');
    const status = el('parkingLookupStatus');
    if (!video || !canvas) return;
    setParkingScanLive(parkingScan.mode === 'qr' ? 'Reading QR…' : 'Reading plate…');
    const frame = cropParkingGuideFrame(video, canvas, parkingScan.mode);
    if (!frame) throw new Error('Camera not ready yet');
    if (parkingScan.mode === 'qr') {
      if (!('BarcodeDetector' in window)) throw new Error('QR not supported in this browser');
      const detector = new BarcodeDetector({ formats: ['qr_code'] });
      const codes = await detector.detect(frame);
      const raw = (codes[0] && (codes[0].rawValue || codes[0].raw_value)) || '';
      const q = parseParkingQrPayload(raw);
      if (!q) throw new Error('No QR found. Hold closer to the code.');
      await finishParkingScan(q);
      return;
    }
    const plates = await ocrPlateCanvas(frame, { allVariants: true });
    let server = null;
    try {
      const blob = await canvasToJpegBlob(frame);
      server = await ocrPlateOnServer(blob, plates);
    } catch (_err) { /* device OCR is enough */ }
    if (await finishParkingScanFromOcr(server, plates[0], plates)) return;
    if (!plates[0]) throw new Error('Could not read the plate. Move closer and tap Read now again.');
  }

  async function scanParkingPlateFile(file) {
    if (!file) return;
    const status = el('parkingLookupStatus');
    if (status) status.textContent = 'Reading plate from photo…';
    const bmp = await createImageBitmap(file);
    const bands = [0.55, 0.35, 0.7];
    const found = [];
    for (const pos of bands) {
      const canvas = document.createElement('canvas');
      const sw = bmp.width;
      const sh = Math.max(48, Math.floor(bmp.height * 0.32));
      const sy = Math.max(0, Math.min(bmp.height - sh, Math.floor((bmp.height - sh) * pos)));
      canvas.width = sw;
      canvas.height = sh;
      canvas.getContext('2d').drawImage(bmp, 0, sy, sw, sh, 0, 0, sw, sh);
      const plates = await ocrPlateCanvas(canvas, { allVariants: true });
      plates.forEach((p) => { if (!found.includes(p)) found.push(p); });
      if (found.length) break;
    }
    if (!found.length) {
      const full = document.createElement('canvas');
      full.width = bmp.width;
      full.height = bmp.height;
      full.getContext('2d').drawImage(bmp, 0, 0);
      const plates = await ocrPlateCanvas(full, { allVariants: true });
      plates.forEach((p) => { if (!found.includes(p)) found.push(p); });
    }
    const plate = found[0];
    if (el('parkingLookupInput') && plate) el('parkingLookupInput').value = plate;
    if (status) status.textContent = plate ? `Plate read: ${plate}. Looking up…` : 'Reading plate from photo…';
    let server = null;
    try {
      server = await ocrPlateOnServer(file, found);
    } catch (_err) { /* device OCR is enough */ }
    if (server?.pass) {
      applyParkingLookupResult(server, (server.candidates && server.candidates[0]) || plate);
      return;
    }
    const merged = mergePlateCandidates(found, server?.candidates);
    if (!merged[0]) throw new Error('Could not read a registration number. Retake closer to the plate, or type it.');
    if (el('parkingLookupInput')) el('parkingLookupInput').value = merged[0];
    await lookupParkingPass(merged[0], { ocr: true, candidates: merged });
  }

  async function scanParkingQrFile(file) {
    if (!file) return;
    if (!('BarcodeDetector' in window)) {
      throw new Error('This browser cannot scan QR. Type the pass code or vehicle number instead.');
    }
    const detector = new BarcodeDetector({ formats: ['qr_code'] });
    const bmp = await createImageBitmap(file);
    const codes = await detector.detect(bmp);
    const raw = (codes[0] && (codes[0].rawValue || codes[0].raw_value)) || '';
    if (!raw) throw new Error('No QR code found in that photo. Try again or type the pass code.');
    const q = parseParkingQrPayload(raw);
    if (el('parkingLookupInput')) el('parkingLookupInput').value = q;
    await lookupParkingPass(q);
  }

  function switchPanel(name) {
    if (name === 'admin' && !canOpenEcDesk()) name = 'home';
    if (name === 'proceedings' && !isEcMember()) name = 'home';
    if (name === 'observability' && !isSuperAdmin()) name = 'home';
    if (name === 'dues' && isSuperAdmin()) name = 'home';
    if (name !== 'messages') stopMsgPolling();
    window.MhwsComposer?.collapseAll?.();
    document.querySelectorAll('.tab').forEach((t) => {
      const isTab = t.dataset.panel === name;
      t.classList.toggle('is-active', isTab);
      t.setAttribute('aria-selected', isTab ? 'true' : 'false');
    });
    document.querySelectorAll('.panel').forEach((p) => {
      const on = p.id === `panel-${name}`;
      p.hidden = !on;
      p.classList.toggle('is-active', on);
    });
    // Nested EC ledger block belongs to Dues only (not for super admin)
    if (el('adminDues')) {
      el('adminDues').hidden = !(name === 'dues' && hasEntitlement('manage_dues') && !isSuperAdmin());
    }
    scrollActiveTabIntoView();
    updateAppTopOffset();
    scrollMainToTop();
    trackPanel(name);
    if (name === 'info') {
      if (isInfoCentreProtectEnforced()) {
        bindInfoCentreProtectOnce();
        startInfoWatermarkClock();
        syncInfoCentreCaptureGuard();
      } else {
        document.body.classList.remove('is-info-capture-guard');
        stopInfoWatermarkClockIfIdle();
      }
    } else {
      document.body.classList.remove('is-info-capture-guard');
      stopInfoWatermarkClockIfIdle();
    }
    if (name === 'home') {
      loadHome().catch(console.error);
      applyBoardRouteHash();
    }
    if (name === 'dues') loadDues().catch((e) => { el('duesCard').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
    if (name === 'concerns') {
      loadMailbox().catch((e) => {
        if (el('mailboxList')) el('mailboxList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
      });
      if (hasEntitlement('manage_notices')) {
        loadMarketplaceAds().catch(() => {});
      }
    }
    if (name === 'messages') loadMessagesPanel().catch((e) => {
      if (el('msgThreadList')) el('msgThreadList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'profile') {
      refreshPushUi().catch(() => {});
      refreshProfileAuthbuddyCard().catch(() => {});
    }
    if (name === 'directory') loadDirectory().catch((e) => {
      if (el('directoryList')) el('directoryList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'parking') loadParkingPanel().catch((e) => {
      if (el('parkingListStatus')) el('parkingListStatus').textContent = e.message || 'Pass list failed';
    });
    if (name === 'info') loadInfoCentre().catch((e) => {
      if (el('infoDocList')) el('infoDocList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'works') loadWorks().catch((e) => {
      if (el('worksList')) el('worksList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'proceedings') loadProceedings().catch((e) => {
      if (el('proceedingsList')) el('proceedingsList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
      if (el('proceedingsListStatus')) el('proceedingsListStatus').textContent = e.message || 'Proceedings failed';
    });
    if (name === 'admin') {
      prepareMobileSections();
      applyEntitlementVisibility();
      loadSmtpStatus();
      initReportsForm().catch(() => {});
      if (hasEntitlement('manage_templates')) {
        loadTemplates().catch((e) => {
          if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Templates failed';
        });
      }
      if (hasEntitlement('manage_notices')) {
        loadNoticeDrafts().catch((e) => {
          if (el('noticeDraftList')) el('noticeDraftList').innerHTML = `<p class="error">${escapeHtml(e.message || 'Drafts failed')}</p>`;
        });
        loadMarketplaceModeration().catch(() => {});
      }
      if (hasEntitlement('manage_bank')) {
        loadBankDetails().catch((e) => { if (el('ecBankPreview')) el('ecBankPreview').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
      }
      if (hasEntitlement('manage_concerns')) {
        loadEcGrievances().catch((e) => { if (el('ecGrievanceStatus')) el('ecGrievanceStatus').textContent = e.message || 'Concerns failed'; });
      }
      if (hasEntitlement('manage_dues')) {
        loadEcPaymentRecords().catch((e) => { if (el('ecPaymentStatus')) el('ecPaymentStatus').textContent = e.message || 'Payments failed'; });
      }
      if (hasEntitlement('treasury')) {
        loadEcTreasuryQueue().catch((e) => {
          if (el('ecTreasuryStatus')) el('ecTreasuryStatus').textContent = e.message || 'Treasury queue failed';
        });
      }
      if (hasEntitlement('manage_dues') || hasEntitlement('issue_no_dues') || hasEntitlement('issue_no_objection')) {
        populatePaymentHouseList().catch(() => {});
      }
      if (hasEntitlement('issue_no_dues')) {
        loadEcNoDuesRequests().catch((e) => {
          if (el('ecNoDuesListStatus')) el('ecNoDuesListStatus').textContent = e.message || 'No dues requests failed';
        });
      }
      if (hasEntitlement('issue_no_objection')) {
        loadEcNoObjectionRequests().catch((e) => {
          if (el('ecNoObjectionListStatus')) el('ecNoObjectionListStatus').textContent = e.message || 'No objection requests failed';
        });
      }
      if (hasEntitlement('manage_roster')) {
        loadRoster().catch((e) => { if (el('rosterStatus')) el('rosterStatus').textContent = e.message || 'Roster failed'; });
      } else if (isEcAdmin()) {
        populateEcDelegateHouseList().catch(() => {});
      }
      if (hasEntitlement('manage_roles') || hasEntitlement('sensitive_ops')) {
        loadEcCharterPanel().catch(() => {});
      }
      if (hasEntitlement('sensitive_ops')) {
        loadRolesPanel().catch(() => {});
        loadRevisions().catch((e) => { if (el('revisionStatus')) el('revisionStatus').textContent = e.message || 'History failed'; });
      }
      if (isSuperAdmin()) loadSettings().catch((e) => { if (el('settingsStatus')) el('settingsStatus').textContent = e.message || 'Settings failed'; });
    }
    if (name === 'observability' && isSuperAdmin()) {
      prepareMobileSections();
      loadObservability().catch((e) => {
        if (el('obsStatus')) el('obsStatus').textContent = e.message || 'Observability failed';
      });
    }
  }

  function switchGate(mode) {
    const plot = mode !== 'admin';
    if (el('plotLoginPane')) el('plotLoginPane').hidden = !plot;
    if (el('adminLoginPane')) el('adminLoginPane').hidden = plot;
    showError('');
  }

  // Hidden super-admin entry: triple-tap / triple-click the logo seal.
  let gateLogoTaps = 0;
  let gateLogoTapTimer = 0;
  function onGateLogoTap(event) {
    event.preventDefault();
    gateLogoTaps += 1;
    window.clearTimeout(gateLogoTapTimer);
    gateLogoTapTimer = window.setTimeout(() => { gateLogoTaps = 0; }, 900);
    if (gateLogoTaps < 3) return;
    gateLogoTaps = 0;
    const adminOpen = !el('adminLoginPane')?.hidden;
    switchGate(adminOpen ? 'plot' : 'admin');
  }
  el('gateSeal')?.addEventListener('click', onGateLogoTap);

  el('adminLoginForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    el('adminLoginBtn').disabled = true;
    try {
      const data = await api('/api/rwa/login', {
        method: 'POST',
        body: JSON.stringify({
          username: el('adminUserInput').value.trim(),
          password: el('adminPassInput').value,
          website: '',
        }),
      });
      el('adminPassInput').value = '';
      setAuthed(data);
      ensurePanelVisibility('admin');
      applyRouteHash();
    } catch (err) {
      showError(err.message || 'Sign-in failed');
    } finally {
      el('adminLoginBtn').disabled = false;
    }
  });

  function resetLoginForms() {
    el('otpRequestForm') && (el('otpRequestForm').hidden = false);
    el('otpMemberForm') && (el('otpMemberForm').hidden = true);
    el('otpContactForm') && (el('otpContactForm').hidden = true);
    el('otpVerifyForm') && (el('otpVerifyForm').hidden = true);
    if (el('authChoicePane')) el('authChoicePane').hidden = true;
    if (el('authbuddyPrimaryBlock')) el('authbuddyPrimaryBlock').hidden = true;
    if (el('emailPasscodePrimaryBlock')) el('emailPasscodePrimaryBlock').hidden = true;
    if (el('authbuddyContinueBtn')) el('authbuddyContinueBtn').hidden = false;
    if (el('authbuddySignInBtn')) el('authbuddySignInBtn').hidden = true;
    resetFaceIdGate();
    if (el('otpInput')) el('otpInput').value = '';
    if (el('otpContactEmail')) el('otpContactEmail').value = '';
    if (el('otpContactPhone')) el('otpContactPhone').value = '';
    if (el('otpHouseholdCode')) el('otpHouseholdCode').value = '';
    if (el('otpMemberList')) el('otpMemberList').innerHTML = '';
    state.pendingHouse = '';
    state.pendingMemberId = '';
    state.pendingContact = false;
    state.missingEmail = false;
    state.missingPhone = false;
    state.authbuddyLinked = false;
    state.authbuddyReachable = false;
    state.preferAuthbuddy = false;
    state.authbuddyUsername = '';
    state.pendingMemberName = '';
    state.pendingEmailMasked = '';
    showError('');
  }

  function hideGateStepsExcept(keepId) {
    ['otpRequestForm', 'otpMemberForm', 'otpContactForm', 'authChoicePane', 'otpVerifyForm'].forEach((id) => {
      if (!el(id)) return;
      el(id).hidden = id !== keepId;
    });
  }

  function showAuthChoicePane(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = data.memberId || state.pendingMemberId || '';
    state.pendingMemberName = data.memberName || data.name || '';
    state.pendingEmailMasked = data.emailMasked || '';
    state.authbuddyLinked = Boolean(data.authbuddyLinked);
    state.authbuddyReachable = Boolean(data.authbuddyReachable);
    state.preferAuthbuddy = Boolean(data.preferAuthbuddy);
    state.authbuddyUsername = data.authbuddyUsername || state.authbuddyUsername || '';

    hideGateStepsExcept('authChoicePane');
    const who = state.pendingMemberName ? ` · ${escapeHtml(state.pendingMemberName)}` : '';
    const hint = el('authChoiceHint');
    if (hint) {
      hint.innerHTML = `Plot <strong>${escapeHtml(state.pendingHouse)}</strong>${who}`;
    }

    const abBlock = el('authbuddyPrimaryBlock');
    const emailBlock = el('emailPasscodePrimaryBlock');
    const abHint = el('authbuddyGateHint');
    const emailHint = el('emailPasscodeHint');
    const signBtn = el('authbuddySignInBtn');
    resetFaceIdGate();

    if (state.preferAuthbuddy) {
      if (abBlock) abBlock.hidden = false;
      if (emailBlock) emailBlock.hidden = false;
      // Linked: AuthBuddy is primary; email is secondary ghost already in abBlock.
      if (emailBlock) emailBlock.hidden = true;
      if (abHint) {
        const uname = data.authbuddyUsername ? ` (${escapeHtml(data.authbuddyUsername)})` : '';
        abHint.innerHTML = `AuthBuddy is linked${uname}. Sign in with password, passkey, authenticator code, or QR approve — one factor is enough.`;
      }
      offerFaceIdOnGate();
    } else {
      if (abBlock) abBlock.hidden = true;
      if (emailBlock) emailBlock.hidden = false;
      if (signBtn) {
        // Unlinked plots must prove inbox ownership via email OTP before AuthBuddy
        // can be attached. Do not advertise AuthBuddy register as a portal login.
        signBtn.hidden = true;
      }
      if (emailHint) {
        const dest = state.pendingEmailMasked
          ? ` to ${escapeHtml(state.pendingEmailMasked)}`
          : '';
        emailHint.innerHTML = `A one-time code will be emailed${dest} only when you tap <strong>Send email passcode</strong>. After that you can link AuthBuddy (same email) for faster return visits.`;
      }
    }
  }

  function resetFaceIdGate() {
    const faceBtn = el('authbuddyFaceIdBtn');
    const continueBtn = el('authbuddyContinueBtn');
    state.authbuddyHasPasskey = false;
    if (faceBtn) {
      faceBtn.hidden = true;
      faceBtn.disabled = false;
    }
    if (continueBtn) {
      continueBtn.classList.add('primary');
      continueBtn.classList.remove('ghost');
    }
  }

  function offerFaceIdOnGate() {
    const faceBtn = el('authbuddyFaceIdBtn');
    const label = el('authbuddyFaceIdLabel');
    const continueBtn = el('authbuddyContinueBtn');
    const abHint = el('authbuddyGateHint');
    const username = state.authbuddyUsername;
    if (!faceBtn) return;
    state.authbuddyHasPasskey = false;
    const bio = (window.VeerAuth && window.VeerAuth.biometricContinueLabel && window.VeerAuth.biometricContinueLabel()) || 'Continue with Face ID';
    if (label) label.textContent = `Set up ${bio.replace(/^Continue with /i, '')}`;
    faceBtn.hidden = false;
    if (!username || !window.VeerAuth?.idpPost) return;
    window.VeerAuth.idpPost('/auth/login/options', { username })
      .then((options) => {
        if (state.authbuddyUsername !== username) return;
        const hasPasskey = Boolean(options && options.has_passkey);
        state.authbuddyHasPasskey = hasPasskey;
        if (label) label.textContent = hasPasskey ? bio : `Set up ${bio.replace(/^Continue with /i, '')}`;
        if (hasPasskey && continueBtn) {
          continueBtn.classList.remove('primary');
          continueBtn.classList.add('ghost');
        }
        if (abHint) {
          abHint.innerHTML = hasPasskey
            ? 'Use Face ID / fingerprint on this phone, or open AuthBuddy for password, authenticator, or QR. Email passcode still works.'
            : 'AuthBuddy is linked. Set up Face ID / fingerprint once (after password), then next visits can skip the password.';
        }
      })
      .catch(() => { /* button still offers setup via AuthBuddy page */ });
  }

  async function continueWithFaceId() {
    showError('');
    const faceBtn = el('authbuddyFaceIdBtn');
    const username = state.authbuddyUsername;
    if (!username) {
      window.location.href = authbuddyAuthUrl('login', { setup: 'passkey' });
      return;
    }
    if (!state.authbuddyHasPasskey) {
      window.location.href = authbuddyAuthUrl('login', { setup: 'passkey' });
      return;
    }
    if (faceBtn) faceBtn.disabled = true;
    try {
      await window.VeerAuth.authenticateWithPasskey(username);
      const sid = window.VeerAuth.savedSessionId();
      const data = await api('/api/rwa/authbuddy/session', {
        method: 'POST',
        body: JSON.stringify({
          houseId: state.pendingHouse,
          memberId: state.pendingMemberId || undefined,
          authbuddySessionId: sid,
        }),
      });
      if (!data.token) throw new Error(data.error || 'Could not open the portal');
      setAuthed(data);
      ensurePanelVisibility('home');
      applyRouteHash();
    } catch (err) {
      const msg = String(err && err.message || '');
      const name = String(err && err.name || '');
      const cancelled = name === 'NotAllowedError' || /not allowed|abort|cancel/i.test(msg);
      if (cancelled) return;
      const originIssue = name === 'SecurityError' || /origin|securityerror/i.test(msg);
      if (originIssue) {
        window.location.href = authbuddyAuthUrl('login');
        return;
      }
      showError(msg || 'Face ID failed — try AuthBuddy or email passcode.');
    } finally {
      if (faceBtn) faceBtn.disabled = false;
    }
  }

  async function resolveLogin(payload) {
    return api('/api/rwa/login/resolve', {
      method: 'POST',
      body: JSON.stringify({ website: '', ...payload }),
    });
  }

  async function handleLoginResolveResult(data, houseId) {
    state.pendingHouse = data.houseId || houseId;
    if (data.memberId) state.pendingMemberId = data.memberId;
    if (data.needsMemberPick) {
      showMemberPicker(data);
      return;
    }
    if (data.needsContact) {
      showContactForm(data);
      return;
    }
    if (data.ready) {
      showAuthChoicePane(data);
      return;
    }
    showError(data.message || 'Could not continue sign-in');
  }

  function authbuddyAuthUrl(purpose, extra) {
    const houseId = state.pendingHouse || (el('houseIdInput') && el('houseIdInput').value.trim()) || '';
    const memberId = state.pendingMemberId || '';
    const username = state.authbuddyUsername || '';
    const returnTo = new URL('index.html', window.location.href);
    returnTo.hash = 'home';
    const auth = new URL('auth.html', window.location.href);
    auth.searchParams.set('return_to', returnTo.href);
    auth.searchParams.set('purpose', purpose || 'login');
    if (houseId) auth.searchParams.set('houseId', houseId);
    if (memberId) auth.searchParams.set('memberId', memberId);
    if (username) auth.searchParams.set('username', username);
    if (extra && extra.setup) auth.searchParams.set('setup', extra.setup);
    if (extra && extra.mode) auth.searchParams.set('mode', extra.mode);
    const email = (extra && extra.email)
      || (state.session && state.session.resident && state.session.resident.email)
      || '';
    if (purpose === 'link' && email) auth.searchParams.set('email', email);
    return auth.href;
  }

  async function sendEmailPasscodeNow() {
    showError('');
    const payload = {
      houseId: state.pendingHouse || (el('houseIdInput') && el('houseIdInput').value.trim()) || '',
      memberId: state.pendingMemberId || undefined,
    };
    if (!payload.houseId) {
      showError('Enter your house / plot number first');
      return;
    }
    const data = await requestOtp(payload);
    if (data.needsMemberPick) {
      showMemberPicker(data);
      return;
    }
    if (data.needsContact) {
      showContactForm(data);
      return;
    }
    showVerifyForm(data);
  }

  const AUTHBUDDY_LINK_DISMISS_KEY = 'hbcsanyard_authbuddy_link_dismissed';

  function authbuddyLinkDismissed() {
    try { return sessionStorage.getItem(AUTHBUDDY_LINK_DISMISS_KEY) === '1'; } catch (_e) { return false; }
  }

  function setAuthbuddyLinkDismissed() {
    try { sessionStorage.setItem(AUTHBUDDY_LINK_DISMISS_KEY, '1'); } catch (_e) { /* ignore */ }
  }

  function clearAuthbuddyLinkDismissed() {
    try { sessionStorage.removeItem(AUTHBUDDY_LINK_DISMISS_KEY); } catch (_e) { /* ignore */ }
  }

  /** Modal (not noticeList) so loadHome() innerHTML cannot wipe the prompt. */
  async function offerAuthbuddyLinkBanner(opts = {}) {
    const force = Boolean(opts.force);
    const r = state.session?.resident;
    if (!r || r.authbuddyLinked || state.authbuddyLinked) return;
    if (!force && authbuddyLinkDismissed()) return;
    if (document.getElementById('authbuddyLinkModal')) return;

    // Confirm IdP is reachable before blocking the UI.
    try {
      const q = new URLSearchParams();
      if (r.houseId) q.set('houseId', r.houseId);
      if (r.memberId) q.set('memberId', r.memberId);
      const st = await api('/api/rwa/authbuddy/status?' + q.toString());
      if (st.linked) {
        state.authbuddyLinked = true;
        return;
      }
      if (st.reachable === false) return;
    } catch (_e) {
      return;
    }

    const modal = document.createElement('div');
    modal.id = 'authbuddyLinkModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'authbuddyLinkTitle');
    modal.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:10000',
      'display:flex', 'align-items:center', 'justify-content:center',
      'padding:1.25rem', 'background:rgba(12,28,36,0.45)',
      'backdrop-filter:blur(2px)',
    ].join(';');
    modal.innerHTML = `
      <div class="gate-card" style="max-width:32rem;width:100%;max-height:min(92vh,40rem);overflow:auto;margin:0;text-align:left">
        <h2 id="authbuddyLinkTitle" style="margin:0 0 0.4rem;font-size:1.2rem">Link AuthBuddy for faster sign-in</h2>
        <p style="margin:0 0 0.85rem;line-height:1.45">
          AuthBuddy is VeerLabs’ secure sign-in service.
          Linking it to this plot member lets you open the portal <strong>without waiting for an email passcode</strong>
          when the service is online — while plot + email OTP remains available anytime.
        </p>
        <p style="margin:0 0 0.35rem;font-weight:600;color:var(--navy)">Prerequisite — authenticator app</p>
        <p class="muted" style="margin:0 0 0.85rem;line-height:1.45;font-size:0.95rem">
          Install <strong>BuddyAuthenticator</strong> before (or while) linking for authenticator codes, QR / number match, and Hybrid PQC.
        </p>
        <p class="muted" style="margin:0 0 0.85rem;line-height:1.45;font-size:0.92rem">
          <strong>Web App (PWA):</strong> <a href="https://authbuddy.veerlabs.solutions/authenticator/" target="_blank" rel="noopener">Open the web app</a> and Add to Home Screen.
          <strong>Android:</strong> latest <code>.apk</code> on <a href="https://drive.google.com/drive/folders/1ywOGks8jBiIUDrV9pmi2NGDD_I0O06Ep?usp=share_link" data-authbuddy-apk-href target="_blank" rel="noopener">Google Drive</a>.
        </p>
        <p class="muted" style="margin:0 0 0.85rem;line-height:1.45;font-size:0.92rem">
          <strong>iOS:</strong> use the Web App (PWA), or <strong>Google Authenticator</strong> / <strong>Microsoft Authenticator</strong> from the App Store for TOTP codes only
          (not QR / number match, HOTP, or Hybrid PQC). Native iOS app is sideloaded for expert / inquisitive users — contact the society or VeerLabs admin.
        </p>
        <p style="margin:0 0 0.35rem;font-weight:600;color:var(--navy)">What you can use (one method is enough)</p>
        <ul style="margin:0 0 0.85rem;padding-left:1.15rem;line-height:1.5;font-size:0.95rem">
          <li><strong>Password</strong> — AuthBuddy account password in the browser.</li>
          <li><strong>Passkey</strong> — Face ID / fingerprint / device unlock (phishing-resistant).</li>
          <li><strong>Authenticator codes (TOTP / HOTP)</strong> — rotating codes in BuddyAuthenticator, or on iOS in Google/Microsoft Authenticator (TOTP only).</li>
          <li><strong>QR / number match</strong> — scan the login QR or match the two-digit number in BuddyAuthenticator → Approvals.</li>
          <li><strong>Hybrid PQC</strong> — stronger post-quantum-ready keys for advanced setups (via the app).</li>
        </ul>
        <p class="muted" style="margin:0 0 1rem;line-height:1.45;font-size:0.92rem">
          Already use AuthBuddy on VeerLabs? Sign in with the <strong>same email</strong> — we link this household member; you won’t need a second account.
          New to AuthBuddy? Create an account with this plot member’s email, then we link it.
          For HBC Sanyard only <strong>one factor</strong> is required right now. Skip anytime; nothing colony-side changes if you choose Not now.
        </p>
        <div data-authbuddy-manual-host style="margin:0 0 1rem"></div>
        <p style="margin:0;display:flex;gap:0.5rem;flex-wrap:wrap">
          <button type="button" class="btn primary" id="authbuddyLinkNowBtn">I already have AuthBuddy</button>
          <button type="button" class="btn secondary" id="authbuddyRegisterBtn">Create AuthBuddy account</button>
          <button type="button" class="btn ghost" id="authbuddyLinkDismissBtn">Not now</button>
        </p>
      </div>`;
    document.body.appendChild(modal);
    if (window.VeerAuth && typeof window.VeerAuth.bindAuthbuddyHelp === 'function') {
      window.VeerAuth.bindAuthbuddyHelp();
    }

    const close = () => { modal.remove(); };
    el('authbuddyLinkDismissBtn')?.addEventListener('click', () => {
      setAuthbuddyLinkDismissed();
      close();
      refreshProfileAuthbuddyCard().catch(() => {});
    });
    el('authbuddyLinkNowBtn')?.addEventListener('click', () => {
      state.pendingHouse = r.houseId || '';
      state.pendingMemberId = r.memberId || '';
      window.location.href = authbuddyAuthUrl('link');
    });
    el('authbuddyRegisterBtn')?.addEventListener('click', () => {
      state.pendingHouse = r.houseId || '';
      state.pendingMemberId = r.memberId || '';
      window.location.href = authbuddyAuthUrl('link', { mode: 'register' });
    });
  }

  async function refreshProfileAuthbuddyCard() {
    const block = el('profileAuthbuddyBlock');
    const status = el('profileAuthbuddyStatus');
    const hint = el('profileAuthbuddyHint');
    const linkBtn = el('profileAuthbuddyLinkBtn');
    const signBtn = el('profileAuthbuddySignInBtn');
    const help = el('profileAuthbuddyHelp');
    if (!block || !status) return;

    const r = state.session?.resident;
    if (!r || r.superAdmin) {
      block.hidden = true;
      return;
    }
    block.hidden = false;

    try {
      const q = new URLSearchParams();
      if (r.houseId) q.set('houseId', r.houseId);
      if (r.memberId) q.set('memberId', r.memberId);
      const st = await api('/api/rwa/authbuddy/status?' + q.toString());
      const linked = Boolean(st.linked || r.authbuddyLinked);
      state.authbuddyLinked = linked;
      if (r) r.authbuddyLinked = linked;

      if (st.reachable === false) {
        status.textContent = 'AuthBuddy is temporarily unreachable — use email passcode.';
        if (linkBtn) linkBtn.hidden = true;
        if (signBtn) signBtn.hidden = true;
        if (hint) hint.textContent = 'Instructions stay here for when the service is back online.';
        if (help) help.open = false;
        return;
      }

      if (linked) {
        const who = st.authbuddyUsername ? ` as ${st.authbuddyUsername}` : '';
        status.textContent = `Linked to AuthBuddy${who}.`;
        if (linkBtn) {
          linkBtn.hidden = false;
          linkBtn.textContent = 'Re-link / manage AuthBuddy';
        }
        if (signBtn) signBtn.hidden = false;
        if (hint) {
          hint.textContent = 'On the gate, use Continue with AuthBuddy after entering your plot. Email passcode still works.';
        }
        if (help) help.open = false;
      } else {
        status.textContent = 'Not linked yet — optional faster sign-in.';
        if (linkBtn) {
          linkBtn.hidden = false;
          linkBtn.textContent = 'Link AuthBuddy';
        }
        if (signBtn) signBtn.hidden = true;
        if (hint) {
          hint.textContent = 'Install BuddyAuthenticator first (or Google/Microsoft Authenticator on iOS for TOTP only), then tap Link.';
        }
        if (help) help.open = true;
      }
    } catch (_e) {
      status.textContent = 'Could not check AuthBuddy status.';
      if (linkBtn) linkBtn.hidden = false;
      if (signBtn) signBtn.hidden = true;
      if (hint) hint.textContent = 'You can still try linking; email passcode remains available.';
    }
  }

  function showMemberPicker(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = '';
    hideGateStepsExcept('otpMemberForm');
    const name = data.householdName ? ` (${escapeHtml(data.householdName)})` : '';
    el('otpMemberHint').innerHTML = data.message
      || `Who is signing in for plot <strong>${escapeHtml(state.pendingHouse)}</strong>${name}?`;
    const list = el('otpMemberList');
    list.innerHTML = (data.members || []).map((m) => {
      const ab = m.authbuddyLinked
        ? ' · <span class="gate-ab-badge"><img class="authbuddy-mark" src="assets/authbuddy/authbuddy-mark-64.png?v=20260812ab1" width="14" height="14" alt="" decoding="async"> AuthBuddy</span>'
        : '';
      return `
      <button type="button" class="member-pick-btn" data-member-id="${escapeHtml(m.id)}">
        ${personAvatarHtml({ ...m, photoUrl: '' }, { size: 'md' })}
        <span class="member-pick-text">
          <strong>${escapeHtml(m.name || 'Member')}</strong>
          <span class="muted">${escapeHtml(m.relationLabel || m.relation || '')}${m.viewOnly ? ' · view only' : ''}${m.emailMasked ? ` · ${escapeHtml(m.emailMasked)}` : ''}${ab}</span>
        </span>
      </button>`;
    }).join('');
  }

  function showContactForm(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = data.memberId || state.pendingMemberId;
    state.missingEmail = Boolean(data.missingEmail);
    state.missingPhone = Boolean(data.missingPhone);
    hideGateStepsExcept('otpContactForm');
    const name = data.name ? ` for ${data.name}` : '';
    el('otpContactHint').textContent = data.message
      || `Plot ${state.pendingHouse}${name} needs first-time registration. Enter the household code from your dues circular, plus email/phone. Contacts are saved only after you verify the emailed code.`;
    if (el('otpHouseholdCode')) {
      el('otpHouseholdCode').required = true;
      el('otpHouseholdCode').disabled = false;
    }
    if (el('otpContactEmailWrap')) el('otpContactEmailWrap').hidden = !state.missingEmail;
    if (el('otpContactPhoneWrap')) el('otpContactPhoneWrap').hidden = !state.missingPhone;
    if (el('otpContactEmail')) {
      el('otpContactEmail').required = state.missingEmail;
      el('otpContactEmail').disabled = !state.missingEmail;
    }
    if (el('otpContactPhone')) {
      el('otpContactPhone').required = state.missingPhone;
      el('otpContactPhone').disabled = !state.missingPhone;
    }
  }

  function showVerifyForm(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = data.memberId || state.pendingMemberId;
    state.pendingContact = Boolean(data.contactPending || data.pendingContact);
    hideGateStepsExcept('otpVerifyForm');
    const who = data.memberName ? ` · ${escapeHtml(data.memberName)}` : '';
    let hint = `Code sent for plot <strong>${escapeHtml(state.pendingHouse)}</strong>${who}`;
    if (data.emailMasked) hint += ` to ${escapeHtml(data.emailMasked)}`;
    if (data.devCode) hint += `. Dev code: <code>${escapeHtml(data.devCode)}</code>`;
    if (state.pendingContact) {
      hint += '. Enter the code to confirm — email/phone are saved only after verification.';
    }
    el('otpHint').innerHTML = hint;
  }

  async function requestOtp(payload) {
    return api('/api/rwa/otp/request', {
      method: 'POST',
      body: JSON.stringify({ website: '', ...payload }),
    });
  }

  async function handleOtpRequestResult(data, houseId) {
    state.pendingHouse = data.houseId || houseId;
    if (state.pendingHouse) saveLastHouseId(state.pendingHouse);
    if (data.memberId) state.pendingMemberId = data.memberId;
    if (data.needsMemberPick) {
      showMemberPicker(data);
      return;
    }
    if (data.needsContact) {
      showContactForm(data);
      return;
    }
    showVerifyForm(data);
  }

  el('otpRequestForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    const houseId = el('houseIdInput').value.trim();
    el('requestOtpBtn').disabled = true;
    try {
      const data = await resolveLogin({ houseId });
      await handleLoginResolveResult(data, houseId);
    } catch (err) {
      showError(err.message || 'Could not continue');
    } finally {
      el('requestOtpBtn').disabled = false;
    }
  });

  el('otpMemberList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('.member-pick-btn');
    if (!btn) return;
    showError('');
    const memberId = btn.getAttribute('data-member-id');
    btn.disabled = true;
    try {
      const data = await resolveLogin({
        houseId: state.pendingHouse,
        memberId,
      });
      await handleLoginResolveResult(data, state.pendingHouse);
    } catch (err) {
      showError(err.message || 'Could not continue');
      btn.disabled = false;
    }
  });

  el('otpMemberBackBtn')?.addEventListener('click', () => resetLoginForms());
  el('authChoiceBackBtn')?.addEventListener('click', () => resetLoginForms());

  el('useEmailPasscodeBtn')?.addEventListener('click', async () => {
    const btn = el('useEmailPasscodeBtn');
    if (btn) btn.disabled = true;
    try {
      await sendEmailPasscodeNow();
    } catch (err) {
      showError(err.message || 'Could not send code');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('sendEmailPasscodeBtn')?.addEventListener('click', async () => {
    const btn = el('sendEmailPasscodeBtn');
    if (btn) btn.disabled = true;
    try {
      await sendEmailPasscodeNow();
    } catch (err) {
      showError(err.message || 'Could not send code');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('otpContactForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    const btn = el('otpContactSubmitBtn');
    if (btn) btn.disabled = true;
    try {
      const payload = {
        houseId: state.pendingHouse || el('houseIdInput').value.trim(),
        memberId: state.pendingMemberId || undefined,
        householdCode: (el('otpHouseholdCode')?.value || '').trim(),
      };
      if (state.missingEmail) payload.email = el('otpContactEmail').value.trim();
      if (state.missingPhone) payload.phone = el('otpContactPhone').value.trim();
      const data = await requestOtp(payload);
      if (data.needsContact) {
        showContactForm(data);
        showError(data.message || 'Please complete the contact details');
        return;
      }
      await handleOtpRequestResult(data, payload.houseId);
    } catch (err) {
      showError(err.message || 'Could not send code');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('otpVerifyForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    el('verifyOtpBtn').disabled = true;
    try {
      const data = await api('/api/rwa/otp/verify', {
        method: 'POST',
        body: JSON.stringify({
          houseId: state.pendingHouse,
          memberId: state.pendingMemberId || undefined,
          code: el('otpInput').value.trim(),
        }),
      });
      clearAuthbuddyLinkDismissed();
      setAuthed(data);
      ensurePanelVisibility('home');
      applyRouteHash();
      if (data.contactUpdated) {
        const list = el('noticeList');
        if (list) {
          const note = document.createElement('p');
          note.className = 'muted';
          note.textContent = 'Your email/phone were verified and saved to the colony register.';
          list.prepend(note);
        }
      }
      // Wait a tick so loadHome can paint, then show a modal that survives notice re-renders.
      setTimeout(() => { offerAuthbuddyLinkBanner({ force: true }); }, 250);
    } catch (err) {
      showError(err.message || 'Invalid code');
    } finally {
      el('verifyOtpBtn').disabled = false;
    }
  });

  el('otpContactBackBtn')?.addEventListener('click', () => resetLoginForms());
  el('restartLoginBtn')?.addEventListener('click', () => resetLoginForms());
  el('authbuddyContinueBtn')?.addEventListener('click', () => {
    window.location.href = authbuddyAuthUrl('login');
  });
  el('authbuddyFaceIdBtn')?.addEventListener('click', () => {
    continueWithFaceId().catch((err) => showError(err.message || 'Face ID failed'));
  });
  el('authbuddySignInBtn')?.addEventListener('click', () => {
    const houseId = state.pendingHouse || (el('houseIdInput') && el('houseIdInput').value.trim()) || '';
    if (!houseId) {
      showError('Enter your house / plot number first');
      return;
    }
    state.pendingHouse = houseId;
    window.location.href = authbuddyAuthUrl(state.authbuddyLinked ? 'login' : 'login');
  });
  el('profileAuthbuddyLinkBtn')?.addEventListener('click', () => {
    const r = state.session?.resident;
    if (!r) return;
    state.pendingHouse = r.houseId || '';
    state.pendingMemberId = r.memberId || '';
    window.location.href = authbuddyAuthUrl('link');
  });
  el('profileAuthbuddySignInBtn')?.addEventListener('click', () => {
    const r = state.session?.resident;
    if (!r) return;
    state.pendingHouse = r.houseId || '';
    state.pendingMemberId = r.memberId || '';
    window.location.href = authbuddyAuthUrl('login');
  });

  el('msgThreadList')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-thread-id]');
    if (!btn) return;
    openMsgThread(btn.getAttribute('data-thread-id')).catch((e) => {
      if (el('msgFeed')) el('msgFeed').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
  });
  function leaveMsgThread() {
    el('msgLayout')?.classList.remove('is-thread-open');
    state.msgActiveThreadId = null;
    state.msgActiveThread = null;
    stopMsgPolling();
    if (el('msgBackBtn')) el('msgBackBtn').hidden = true;
    if (el('msgLeaveBar')) el('msgLeaveBar').hidden = true;
    if (el('msgComposeForm')) el('msgComposeForm').hidden = true;
    if (el('msgChannelTools')) el('msgChannelTools').hidden = true;
    history.replaceState(null, '', '#messages');
  }

  el('msgBackBtn')?.addEventListener('click', leaveMsgThread);
  el('msgBackBottomBtn')?.addEventListener('click', leaveMsgThread);
  el('msgRefreshThreadsBtn')?.addEventListener('click', () => refreshMsgThreads().catch(console.error));
  el('msgComposeForm')?.addEventListener('submit', sendMsgCompose);
  el('msgAttachInput')?.addEventListener('change', () => {
    const input = el('msgAttachInput');
    syncMsgAttachFiles(input?.files);
    // Clear native selection if nothing usable remains so re-picking same file works
    if (!state.msgAttachFiles.length && input) input.value = '';
  });
  el('msgEmojiBtn')?.addEventListener('click', () => {
    const picker = el('msgEmojiPicker');
    if (!picker) return;
    if (picker.hidden) {
      picker.innerHTML = MSG_EMOJI.map((e) => `<button type="button" data-emoji="${e}">${e}</button>`).join('');
      picker.hidden = false;
    } else {
      picker.hidden = true;
    }
  });
  el('msgEmojiPicker')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-emoji]');
    if (!btn || !el('msgBodyInput')) return;
    el('msgBodyInput').value += btn.getAttribute('data-emoji') || '';
    el('msgBodyInput').focus();
  });
  el('msgFeed')?.addEventListener('click', async (event) => {
    const likeBtn = event.target.closest('[data-msg-like]');
    if (likeBtn) {
      if (isViewOnly()) return;
      const id = likeBtn.getAttribute('data-msg-like');
      likeBtn.disabled = true;
      try {
        const data = await api(`/api/rwa/messages/${encodeURIComponent(id)}/like`, {
          method: 'POST',
          body: '{}',
        });
        likeBtn.classList.toggle('is-active', Boolean(data.likedByMe));
        likeBtn.setAttribute('aria-pressed', data.likedByMe ? 'true' : 'false');
        likeBtn.title = data.likedByMe ? 'Unlike' : 'Like';
        const countEl = likeBtn.querySelector('.msg-like-count');
        if (countEl) countEl.textContent = String(data.likeCount || 0);
        const svg = likeBtn.querySelector('svg');
        if (svg) svg.setAttribute('fill', data.likedByMe ? 'currentColor' : 'none');
      } catch (e) {
        if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Like failed';
      } finally {
        likeBtn.disabled = false;
      }
      return;
    }

    const editBtn = event.target.closest('[data-msg-edit]');
    if (editBtn) {
      if (isViewOnly()) return;
      const id = editBtn.getAttribute('data-msg-edit');
      const row = editBtn.closest('.msg-row');
      const bubble = row?.querySelector('.msg-bubble');
      const bodyEl = bubble?.querySelector('.msg-body');
      if (!bubble || !bodyEl || bubble.querySelector('.msg-edit-form')) return;
      const current = bodyEl.textContent || '';
      bodyEl.hidden = true;
      const form = document.createElement('form');
      form.className = 'msg-edit-form';
      form.innerHTML = `
        <textarea rows="3" maxlength="4000" aria-label="Edit message">${escapeHtml(current)}</textarea>
        <div class="btn-row">
          <button type="submit" class="btn primary compact">Save</button>
          <button type="button" class="btn ghost compact msg-edit-cancel">Cancel</button>
        </div>`;
      bodyEl.insertAdjacentElement('afterend', form);
      const ta = form.querySelector('textarea');
      ta?.focus();
      form.querySelector('.msg-edit-cancel')?.addEventListener('click', () => {
        form.remove();
        bodyEl.hidden = false;
      });
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const next = (ta?.value || '').trim();
        try {
          await api(`/api/rwa/messages/${encodeURIComponent(id)}`, {
            method: 'PATCH',
            body: JSON.stringify({ body: next }),
          });
          await openMsgThread(state.msgActiveThreadId, { skipHash: true });
        } catch (e) {
          if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Edit failed';
        }
      });
      return;
    }

    const delOwn = event.target.closest('[data-msg-delete]');
    if (delOwn) {
      if (isViewOnly()) return;
      const id = delOwn.getAttribute('data-msg-delete');
      if (!window.confirm('Delete your message?')) return;
      try {
        await api(`/api/rwa/messages/${encodeURIComponent(id)}`, { method: 'DELETE' });
        await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      } catch (e) {
        if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Delete failed';
      }
      return;
    }

    const btn = event.target.closest('.msg-mod');
    if (!btn) return;
    const id = btn.getAttribute('data-id');
    const action = btn.getAttribute('data-action');
    try {
      await api(`/api/rwa/messages/${encodeURIComponent(id)}/moderate`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      });
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
    } catch (e) {
      if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Moderation failed';
    }
  });

  el('msgChannelTools')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-cleanup]');
    if (!btn || !state.msgActiveThreadId) return;
    event.preventDefault();
    const action = btn.getAttribute('data-cleanup');
    const days = btn.getAttribute('data-days');
    const labels = {
      clear_all: 'Clear the entire channel? This removes all messages for everyone.',
      clear_hidden: 'Permanently remove all hidden messages?',
      older_than: `Delete messages older than ${days} days?`,
    };
    if (!window.confirm(labels[action] || 'Run cleanup?')) return;
    try {
      const payload = { action };
      if (action === 'older_than') payload.days = Number(days || 30);
      const data = await api(
        `/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/cleanup`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      const menu = el('msgMoreMenu');
      if (menu) menu.open = false;
      if (el('msgComposeStatus')) {
        el('msgComposeStatus').textContent = `Cleanup done — ${data.deleted || 0} message(s) removed.`;
      }
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      await refreshMsgThreads().catch(() => {});
    } catch (e) {
      if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Cleanup failed';
    }
  });
  let peerTimer = null;

  function clearMsgPeerSearch({ focusInput = false } = {}) {
    clearTimeout(peerTimer);
    if (el('msgPeerSearch')) el('msgPeerSearch').value = '';
    if (el('msgPeerResults')) {
      el('msgPeerResults').hidden = true;
      el('msgPeerResults').innerHTML = '';
    }
    if (el('msgPeerCancelBtn')) el('msgPeerCancelBtn').hidden = true;
    if (focusInput) el('msgPeerSearch')?.focus();
  }

  function setMsgPeerSearching(active) {
    if (el('msgPeerCancelBtn')) el('msgPeerCancelBtn').hidden = !active;
  }

  function renderMsgPeerResults(peers) {
    const box = el('msgPeerResults');
    if (!box) return;
    const head = `<div class="msg-peer-results-head">
      <span class="muted">Person-to-person chat</span>
      <button type="button" class="btn ghost compact" data-peer-dismiss>Cancel</button>
    </div>`;
    if (!peers.length) {
      box.innerHTML = `${head}<p class="muted msg-peer-empty">No people found</p>`;
      box.hidden = false;
      setMsgPeerSearching(true);
      return;
    }
    box.innerHTML = head + peers.map((p) => (
      `<button type="button" data-house-id="${escapeHtml(p.houseId)}">${escapeHtml(p.label)}</button>`
    )).join('');
    box.hidden = false;
    setMsgPeerSearching(true);
  }

  el('msgPeerSearch')?.addEventListener('input', () => {
    clearTimeout(peerTimer);
    const q = (el('msgPeerSearch')?.value || '').trim();
    setMsgPeerSearching(q.length > 0);
    peerTimer = setTimeout(async () => {
      const box = el('msgPeerResults');
      if (!box) return;
      if (q.length < 1) {
        clearMsgPeerSearch();
        return;
      }
      try {
        const data = await api(`/api/rwa/messages/peers?q=${encodeURIComponent(q)}`);
        renderMsgPeerResults(data.peers || []);
      } catch (_e) {
        box.hidden = true;
        box.innerHTML = '';
      }
    }, 200);
  });
  el('msgPeerSearch')?.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      clearMsgPeerSearch();
    }
  });
  el('msgPeerCancelBtn')?.addEventListener('click', () => clearMsgPeerSearch());
  el('msgPeerResults')?.addEventListener('click', async (event) => {
    if (event.target.closest('[data-peer-dismiss]')) {
      clearMsgPeerSearch();
      return;
    }
    const btn = event.target.closest('[data-house-id]');
    if (!btn) return;
    try {
      const data = await api('/api/rwa/messages/dm', {
        method: 'POST',
        body: JSON.stringify({ houseId: btn.getAttribute('data-house-id') }),
      });
      clearMsgPeerSearch();
      await refreshMsgThreads();
      await openMsgThread(data.thread.id);
    } catch (e) {
      if (el('msgComposeStatus')) el('msgComposeStatus').textContent = e.message || 'Could not open chat';
    }
  });
  document.addEventListener('pointerdown', (event) => {
    const wrap = el('msgSidebar')?.querySelector('.msg-new-dm');
    const box = el('msgPeerResults');
    if (!wrap || !box || box.hidden) return;
    if (wrap.contains(event.target)) return;
    clearMsgPeerSearch();
  });

  function applyMsgFeedBackground(thread) {
    const feed = el('msgFeed');
    if (!feed) return;
    feed.className = 'msg-feed';
    feed.style.backgroundImage = '';
    if (!thread || thread.kind !== 'group') return;
    const style = (thread.bgStyle || 'none').trim() || 'none';
    if (style && style !== 'none') {
      feed.classList.add(`msg-bg-${style}`, 'has-room-bg');
    }
    if (style === 'custom' && thread.bgUrl) {
      const url = String(thread.bgUrl).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
      // Light wash layered over the image so chat stays readable.
      feed.style.backgroundImage = `linear-gradient(rgba(255,252,246,0.42), rgba(255,250,242,0.52)), url("${url}")`;
    }
  }

  function peopleInviteKey(p) {
    if (p.kind === 'tenant' || p.tenantId) return `tenant:${p.tenantId}`;
    return `member:${p.memberId}`;
  }

  function renderSelectedPeople(boxId, selected) {
    const box = el(boxId);
    if (!box) return;
    if (!selected.length) {
      box.innerHTML = '<p class="muted">No one selected yet.</p>';
      return;
    }
    box.innerHTML = selected.map((p) => (
      `<button type="button" class="msg-chip" data-remove-invite="${escapeHtml(peopleInviteKey(p))}">${escapeHtml(p.label)} ✕</button>`
    )).join('');
  }

  function renderPeopleSearchResults(boxId, people, selectedKeys) {
    const box = el(boxId);
    if (!box) return;
    const filtered = (people || []).filter((p) => !selectedKeys.has(peopleInviteKey(p)));
    if (!filtered.length) {
      box.innerHTML = '<p class="muted msg-peer-empty">No people found</p>';
      box.hidden = false;
      return;
    }
    box.innerHTML = filtered.map((p) => {
      const key = peopleInviteKey(p);
      const note = p.kind === 'tenant' ? ' <span class="muted">(tenant listing)</span>' : '';
      return `<button type="button" data-invite-key="${escapeHtml(key)}" data-kind="${escapeHtml(p.kind || 'member')}" data-member-id="${escapeHtml(p.memberId || '')}" data-tenant-id="${escapeHtml(p.tenantId || '')}" data-label="${escapeHtml(p.label)}">${escapeHtml(p.label)}${note}</button>`;
    }).join('');
    box.hidden = false;
  }

  function invitePayloadFromSelected(selected) {
    return {
      memberIds: selected.filter((p) => p.kind !== 'tenant' && p.memberId).map((p) => p.memberId),
      tenantIds: selected.filter((p) => p.kind === 'tenant' || p.tenantId).map((p) => p.tenantId),
    };
  }

  function openChannelLookDialog() {
    const thread = state.msgActiveThread;
    if (!thread || thread.kind !== 'group') return;
    const preview = el('msgChannelIconPreview');
    const fallback = el('msgChannelIconFallback');
    if (preview && fallback) {
      if (thread.iconUrl) {
        preview.src = thread.iconUrl;
        preview.hidden = false;
        fallback.hidden = true;
      } else {
        preview.hidden = true;
        preview.removeAttribute('src');
        fallback.hidden = false;
        fallback.textContent = (thread.title || 'C').slice(0, 1).toUpperCase();
      }
    }
    const presets = el('msgChannelBgPresets');
    if (presets) {
      const styles = thread.bgStyles || [
        { id: 'none', label: 'None' },
        { id: 'soft', label: 'Soft wash' },
        { id: 'dots', label: 'Dots' },
        { id: 'grid', label: 'Grid' },
        { id: 'tiles', label: 'Tiles' },
        { id: 'diagonal', label: 'Diagonal' },
        { id: 'leaves', label: 'Leaves' },
        { id: 'custom', label: 'Custom image' },
      ];
      presets.innerHTML = styles.map((s) => (
        `<button type="button" class="msg-bg-preset${thread.bgStyle === s.id ? ' is-active' : ''}" data-bg-style="${escapeHtml(s.id)}">
          <span class="msg-bg-swatch msg-bg-${escapeHtml(s.id)}"></span>
          <span>${escapeHtml(s.label)}</span>
        </button>`
      )).join('');
    }
    if (el('msgChannelLookStatus')) el('msgChannelLookStatus').textContent = '';
    el('msgChannelLookDialog')?.showModal();
  }

  let createPeopleTimer = null;
  function openCreateChannelDialog() {
    if (isViewOnly()) {
      window.alert('View-only access cannot create channels');
      return;
    }
    state.msgCreateSelected = [];
    if (el('msgCreateChannelTitleInput')) el('msgCreateChannelTitleInput').value = '';
    if (el('msgCreateChannelOfficial')) el('msgCreateChannelOfficial').checked = false;
    if (el('msgCreateChannelPeopleSearch')) el('msgCreateChannelPeopleSearch').value = '';
    if (el('msgCreateChannelPeopleResults')) {
      el('msgCreateChannelPeopleResults').hidden = true;
      el('msgCreateChannelPeopleResults').innerHTML = '';
    }
    if (el('msgCreateChannelStatus')) el('msgCreateChannelStatus').textContent = '';
    renderSelectedPeople('msgCreateChannelSelected', state.msgCreateSelected);
    el('msgCreateChannelDialog')?.showModal();
  }

  el('msgNewChannelBtn')?.addEventListener('click', () => openCreateChannelDialog());
  el('msgCreateChannelCancel')?.addEventListener('click', () => el('msgCreateChannelDialog')?.close());
  el('msgCreateChannelSelected')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-remove-invite]');
    if (!btn) return;
    const key = btn.getAttribute('data-remove-invite');
    state.msgCreateSelected = state.msgCreateSelected.filter((p) => peopleInviteKey(p) !== key);
    renderSelectedPeople('msgCreateChannelSelected', state.msgCreateSelected);
  });
  el('msgCreateChannelPeopleSearch')?.addEventListener('input', () => {
    clearTimeout(createPeopleTimer);
    const q = (el('msgCreateChannelPeopleSearch')?.value || '').trim();
    createPeopleTimer = setTimeout(async () => {
      const box = el('msgCreateChannelPeopleResults');
      if (!box) return;
      if (q.length < 1) {
        box.hidden = true;
        box.innerHTML = '';
        return;
      }
      try {
        const data = await api(`/api/rwa/messages/people?q=${encodeURIComponent(q)}`);
        const selectedKeys = new Set(state.msgCreateSelected.map(peopleInviteKey));
        renderPeopleSearchResults('msgCreateChannelPeopleResults', data.people || [], selectedKeys);
      } catch (e) {
        box.innerHTML = `<p class="error">${escapeHtml(e.message || 'Search failed')}</p>`;
        box.hidden = false;
      }
    }, 200);
  });
  el('msgCreateChannelPeopleResults')?.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-invite-key]');
    if (!btn) return;
    const kind = btn.getAttribute('data-kind') || 'member';
    const memberId = btn.getAttribute('data-member-id') || '';
    const tenantId = btn.getAttribute('data-tenant-id') || '';
    const label = btn.getAttribute('data-label') || '';
    const person = { kind, memberId, tenantId, label };
    if (state.msgCreateSelected.some((p) => peopleInviteKey(p) === peopleInviteKey(person))) return;
    state.msgCreateSelected.push(person);
    renderSelectedPeople('msgCreateChannelSelected', state.msgCreateSelected);
    if (el('msgCreateChannelPeopleSearch')) el('msgCreateChannelPeopleSearch').value = '';
    if (el('msgCreateChannelPeopleResults')) {
      el('msgCreateChannelPeopleResults').hidden = true;
      el('msgCreateChannelPeopleResults').innerHTML = '';
    }
  });
  el('msgCreateChannelForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('msgCreateChannelStatus');
    const title = (el('msgCreateChannelTitleInput')?.value || '').trim();
    try {
      if (status) status.textContent = 'Creating…';
      const invites = invitePayloadFromSelected(state.msgCreateSelected);
      const data = await api('/api/rwa/messages/groups', {
        method: 'POST',
        body: JSON.stringify({
          title,
          memberIds: invites.memberIds,
          tenantIds: invites.tenantIds,
          isOfficial: Boolean(el('msgCreateChannelOfficial')?.checked),
        }),
      });
      el('msgCreateChannelDialog')?.close();
      await refreshMsgThreads();
      await openMsgThread(data.thread.id);
    } catch (e) {
      if (status) status.textContent = e.message || 'Could not create channel';
    }
  });

  async function patchActiveGroup(payload) {
    if (!state.msgActiveThreadId) return;
    const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    await openMsgThread(state.msgActiveThreadId, { skipHash: true });
    await refreshMsgThreads().catch(() => {});
    return data;
  }

  el('msgManageRenameBtn')?.addEventListener('click', async () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    const current = state.msgActiveThread?.title || '';
    const next = window.prompt('Channel name', current);
    if (next == null) return;
    try {
      await patchActiveGroup({ title: next.trim() });
    } catch (e) {
      window.alert(e.message || 'Rename failed');
    }
  });
  el('msgManageOfficialBtn')?.addEventListener('click', async () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    try {
      await patchActiveGroup({ isOfficial: !state.msgActiveThread?.isOfficial });
    } catch (e) {
      window.alert(e.message || 'Could not update Official');
    }
  });
  el('msgManageArchiveBtn')?.addEventListener('click', async () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    const archived = Boolean(state.msgActiveThread?.archivedAt);
    const ok = window.confirm(archived ? 'Unarchive this channel?' : 'Archive this channel? Members keep history but cannot post.');
    if (!ok) return;
    try {
      await patchActiveGroup({ archive: !archived });
    } catch (e) {
      window.alert(e.message || 'Archive failed');
    }
  });

  async function refreshManageMembersList() {
    const tid = state.msgManageThreadId || state.msgActiveThreadId;
    if (!tid) return;
    const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(tid)}/members`);
    const box = el('msgManageMembersList');
    if (!box) return;
    const members = data.members || [];
    if (!members.length) {
      box.innerHTML = '<p class="muted">No members.</p>';
      return;
    }
    box.innerHTML = members.map((m) => {
      const role = m.role === 'owner' ? ' · Owner' : (m.roleLabel ? ` · ${m.roleLabel}` : '');
      const canRemove = state.msgCanManage && m.role !== 'owner';
      const removeBtn = canRemove
        ? `<button type="button" class="btn ghost compact" data-remove-member-id="${escapeHtml(m.memberId)}">Remove</button>`
        : '';
      return `<div class="msg-member-row">
        <span>${escapeHtml(m.label || m.name)}${escapeHtml(role)}</span>
        ${removeBtn}
      </div>`;
    }).join('');
  }

  el('msgManageMembersBtn')?.addEventListener('click', async () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    state.msgManageThreadId = state.msgActiveThreadId;
    if (el('msgManageMembersSearch')) el('msgManageMembersSearch').value = '';
    if (el('msgManageMembersResults')) {
      el('msgManageMembersResults').hidden = true;
      el('msgManageMembersResults').innerHTML = '';
    }
    if (el('msgManageMembersStatus')) el('msgManageMembersStatus').textContent = '';
    try {
      await refreshManageMembersList();
      el('msgManageMembersDialog')?.showModal();
    } catch (e) {
      window.alert(e.message || 'Could not load members');
    }
  });
  el('msgManageMembersClose')?.addEventListener('click', () => el('msgManageMembersDialog')?.close());
  el('msgManageMembersList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-remove-member-id]');
    if (!btn || !state.msgManageThreadId) return;
    if (!window.confirm('Remove this person from the channel?')) return;
    try {
      await api(
        `/api/rwa/messages/threads/${encodeURIComponent(state.msgManageThreadId)}/members/${encodeURIComponent(btn.getAttribute('data-remove-member-id'))}`,
        { method: 'DELETE' },
      );
      await refreshManageMembersList();
      await openMsgThread(state.msgManageThreadId, { skipHash: true });
    } catch (e) {
      if (el('msgManageMembersStatus')) el('msgManageMembersStatus').textContent = e.message || 'Remove failed';
    }
  });
  let managePeopleTimer = null;
  el('msgManageMembersSearch')?.addEventListener('input', () => {
    clearTimeout(managePeopleTimer);
    const q = (el('msgManageMembersSearch')?.value || '').trim();
    managePeopleTimer = setTimeout(async () => {
      const box = el('msgManageMembersResults');
      if (!box) return;
      if (q.length < 1) {
        box.hidden = true;
        box.innerHTML = '';
        return;
      }
      try {
        const data = await api(`/api/rwa/messages/people?q=${encodeURIComponent(q)}`);
        renderPeopleSearchResults('msgManageMembersResults', data.people || [], new Set());
      } catch (e) {
        box.innerHTML = `<p class="error">${escapeHtml(e.message || 'Search failed')}</p>`;
        box.hidden = false;
      }
    }, 200);
  });
  el('msgManageMembersResults')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-invite-key]');
    if (!btn || !state.msgManageThreadId) return;
    const kind = btn.getAttribute('data-kind') || 'member';
    const memberId = btn.getAttribute('data-member-id') || '';
    const tenantId = btn.getAttribute('data-tenant-id') || '';
    try {
      const body = kind === 'tenant'
        ? { tenantIds: [tenantId] }
        : { memberIds: [memberId] };
      await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgManageThreadId)}/members`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (el('msgManageMembersSearch')) el('msgManageMembersSearch').value = '';
      if (el('msgManageMembersResults')) {
        el('msgManageMembersResults').hidden = true;
        el('msgManageMembersResults').innerHTML = '';
      }
      await refreshManageMembersList();
      await openMsgThread(state.msgManageThreadId, { skipHash: true });
    } catch (e) {
      if (el('msgManageMembersStatus')) el('msgManageMembersStatus').textContent = e.message || 'Add failed';
    }
  });

  el('msgQuickMembersBtn')?.addEventListener('click', () => {
    el('msgManageMembersBtn')?.click();
  });
  el('msgQuickLookBtn')?.addEventListener('click', () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    openChannelLookDialog();
  });
  el('msgCardThemeWrap')?.addEventListener('click', (event) => {
    const chip = event.target.closest('.msg-theme-chip');
    if (!chip) return;
    event.preventDefault();
    setMsgCardTheme(chip.getAttribute('data-theme') || 'plain');
  });
  el('msgManageIconBtn')?.addEventListener('click', () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    openChannelLookDialog();
  });
  el('msgManageBgBtn')?.addEventListener('click', () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    openChannelLookDialog();
  });
  el('msgChannelLookClose')?.addEventListener('click', () => el('msgChannelLookDialog')?.close());
  el('msgChannelIconFile')?.addEventListener('change', async () => {
    const file = el('msgChannelIconFile')?.files?.[0];
    if (!file || !state.msgActiveThreadId) return;
    const status = el('msgChannelLookStatus');
    try {
      if (status) status.textContent = 'Uploading icon…';
      const fd = new FormData();
      fd.append('file', file);
      const token = state.session?.token;
      const res = await fetch(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/icon`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: token ? { 'X-RWA-Token': token } : {},
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Icon upload failed');
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      openChannelLookDialog();
      if (status) status.textContent = 'Icon updated.';
    } catch (e) {
      if (status) status.textContent = e.message || 'Icon upload failed';
    } finally {
      if (el('msgChannelIconFile')) el('msgChannelIconFile').value = '';
    }
  });
  el('msgChannelIconClear')?.addEventListener('click', async () => {
    if (!state.msgActiveThreadId) return;
    try {
      await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/icon`, { method: 'DELETE' });
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      openChannelLookDialog();
    } catch (e) {
      if (el('msgChannelLookStatus')) el('msgChannelLookStatus').textContent = e.message || 'Could not remove icon';
    }
  });
  el('msgChannelBgPresets')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-bg-style]');
    if (!btn || !state.msgActiveThreadId) return;
    const style = btn.getAttribute('data-bg-style');
    const status = el('msgChannelLookStatus');
    try {
      if (style === 'custom' && !state.msgActiveThread?.hasCustomBg) {
        el('msgChannelBgFile')?.click();
        return;
      }
      if (status) status.textContent = 'Updating background…';
      const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/background`, {
        method: 'POST',
        body: JSON.stringify({ bgStyle: style }),
      });
      state.msgActiveThread = data.thread || state.msgActiveThread;
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      openChannelLookDialog();
      if (status) status.textContent = 'Background updated.';
    } catch (e) {
      if (status) status.textContent = e.message || 'Background update failed';
    }
  });
  el('msgChannelBgFile')?.addEventListener('change', async () => {
    const file = el('msgChannelBgFile')?.files?.[0];
    if (!file || !state.msgActiveThreadId) return;
    const status = el('msgChannelLookStatus');
    try {
      if (status) status.textContent = 'Uploading background…';
      const fd = new FormData();
      fd.append('file', file);
      const token = state.session?.token;
      const res = await fetch(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/background`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: token ? { 'X-RWA-Token': token } : {},
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Background upload failed');
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      openChannelLookDialog();
      if (status) status.textContent = 'Custom background set.';
    } catch (e) {
      if (status) status.textContent = e.message || 'Background upload failed';
    } finally {
      if (el('msgChannelBgFile')) el('msgChannelBgFile').value = '';
    }
  });
  el('msgChannelBgClear')?.addEventListener('click', async () => {
    if (!state.msgActiveThreadId) return;
    try {
      await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/background`, { method: 'DELETE' });
      await openMsgThread(state.msgActiveThreadId, { skipHash: true });
      openChannelLookDialog();
    } catch (e) {
      if (el('msgChannelLookStatus')) el('msgChannelLookStatus').textContent = e.message || 'Could not clear background';
    }
  });

  el('msgLeaveChannelBtn')?.addEventListener('click', async () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    if (!state.msgActiveThreadId) return;
    const isOwner = state.msgActiveThread?.myRole === 'owner'
      || state.msgActiveThread?.ownerMemberId === state.session?.resident?.memberId;
    let transferOwnerTo = null;
    if (isOwner && Number(state.msgActiveThread?.memberCount || 0) > 1) {
      try {
        const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/members`);
        const others = (data.members || []).filter((m) => (
          m.memberId !== state.session?.resident?.memberId && m.kind !== 'tenant' && m.role !== 'tenant'
        ));
        if (!others.length) {
          if (!window.confirm('You are the only other member left. Leaving will archive the channel. Continue?')) return;
        } else {
          const choice = window.prompt(
            `Transfer ownership before leaving. Enter 1–${others.length}:\n${others.map((m, i) => `${i + 1}. ${m.label}`).join('\n')}`,
          );
          if (choice == null) return;
          const idx = Number(choice) - 1;
          if (!Number.isInteger(idx) || idx < 0 || idx >= others.length) {
            window.alert('Invalid choice');
            return;
          }
          transferOwnerTo = others[idx].memberId;
        }
      } catch (e) {
        window.alert(e.message || 'Could not load members');
        return;
      }
    } else if (!window.confirm('Leave this private channel?')) {
      return;
    }
    try {
      await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/leave`, {
        method: 'POST',
        body: JSON.stringify({ transferOwnerTo }),
      });
      leaveMsgThread();
      await refreshMsgThreads();
    } catch (e) {
      window.alert(e.message || 'Could not leave channel');
    }
  });

  el('msgEscalateBtn')?.addEventListener('click', () => {
    if (el('msgMoreMenu')) el('msgMoreMenu').open = false;
    if (!state.msgActiveThreadId || state.msgIsAiThread) return;
    const title = state.msgActiveThread?.title || 'Chat';
    if (el('msgEscalateSubject')) el('msgEscalateSubject').value = `From Chat: ${title}`.slice(0, 160);
    if (el('msgEscalateNote')) el('msgEscalateNote').value = '';
    if (el('msgEscalateCategory')) el('msgEscalateCategory').value = 'other';
    if (el('msgEscalateStatus')) el('msgEscalateStatus').textContent = '';
    if (el('msgEscalatePreview')) {
      el('msgEscalatePreview').textContent = 'Recent messages in this conversation will be quoted on the concern.';
    }
    el('msgEscalateDialog')?.showModal();
  });
  el('msgEscalateCancel')?.addEventListener('click', () => el('msgEscalateDialog')?.close());
  el('msgEscalateForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.msgActiveThreadId) return;
    const status = el('msgEscalateStatus');
    try {
      if (status) status.textContent = 'Creating concern…';
      const data = await api(`/api/rwa/messages/threads/${encodeURIComponent(state.msgActiveThreadId)}/escalate`, {
        method: 'POST',
        body: JSON.stringify({
          subject: (el('msgEscalateSubject')?.value || '').trim(),
          category: el('msgEscalateCategory')?.value || 'other',
          body: (el('msgEscalateNote')?.value || '').trim(),
        }),
      });
      el('msgEscalateDialog')?.close();
      if (window.confirm('Concern created. Open Concerns mailbox now?')) {
        switchPanel('concerns');
      } else if (el('msgComposeStatus')) {
        el('msgComposeStatus').textContent = `Escalated — concern ${data.concernId || ''} created.`;
      }
    } catch (e) {
      if (status) status.textContent = e.message || 'Escalate failed';
    }
  });

  el('pushEnableBtn')?.addEventListener('click', () => enablePush());
  el('pushDisableBtn')?.addEventListener('click', () => disablePush());
  el('pushTestBtn')?.addEventListener('click', async () => {
    try {
      const data = await api('/api/rwa/push/test', { method: 'POST', body: '{}' });
      if (el('pushStatusText')) {
        el('pushStatusText').textContent = data.result?.sent
          ? `Test sent to ${data.result.sent} device(s).`
          : (data.result?.status === 'skipped'
            ? 'No subscription on this account yet — enable push first.'
            : `Test result: ${data.result?.status || 'unknown'}`);
      }
    } catch (e) {
      if (el('pushStatusText')) el('pushStatusText').textContent = e.message || 'Test failed';
    }
  });
  el('pushPrefsSaveBtn')?.addEventListener('click', () => savePushPrefs());
  el('directoryLookup')?.addEventListener('input', () => renderDirectory());
  el('directoryLookup')?.addEventListener('search', () => renderDirectory());
  el('directoryList')?.addEventListener('click', (event) => {
    const phoneBtn = event.target.closest?.('.dir-contact-phone');
    if (phoneBtn) {
      event.preventDefault();
      openDirectoryPhoneSheet(phoneBtn.dataset.phone, phoneBtn.dataset.digits);
      return;
    }
    const mail = event.target.closest?.('a.dir-contact-email');
    if (mail) {
      event.preventDefault();
      openDirectoryHref(mail.getAttribute('href'));
    }
  });
  el('dirContactCall')?.addEventListener('click', (event) => {
    event.preventDefault();
    const href = event.currentTarget.dataset.href || event.currentTarget.getAttribute('href');
    closeDirectoryContactSheet();
    window.setTimeout(() => openDirectoryHref(href), 80);
  });
  el('dirContactWhatsApp')?.addEventListener('click', (event) => {
    event.preventDefault();
    const href = event.currentTarget.dataset.href || event.currentTarget.getAttribute('href');
    closeDirectoryContactSheet();
    window.setTimeout(() => openDirectoryHref(href), 80);
  });
  el('dirContactCancel')?.addEventListener('click', () => closeDirectoryContactSheet());
  el('dirContactSheet')?.addEventListener('click', (event) => {
    if (event.target === event.currentTarget) closeDirectoryContactSheet();
  });

  el('parkingMemberForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('parkingMemberStatus');
    try {
      await issueParkingPass({
        kind: 'member',
        plate: el('parkingMemberPlate').value,
        colour: el('parkingMemberColour').value,
        vehicleType: el('parkingMemberType').value,
        driverName: el('parkingMemberDriver').value,
      }, status);
      el('parkingMemberForm').reset();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not register vehicle';
    }
  });

  el('parkingTenantForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('parkingTenantStatus');
    try {
      await issueParkingPass({
        kind: 'tenant',
        tenantId: el('parkingTenantSelect').value,
        plate: el('parkingTenantPlate').value,
        colour: el('parkingTenantColour').value,
        vehicleType: el('parkingTenantType').value,
        months: el('parkingTenantMonths').value,
      }, status);
      el('parkingTenantPlate').value = '';
      el('parkingTenantColour').value = '';
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not issue tenant pass';
    }
  });

  el('parkingRequestForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('parkingRequestStatus');
    try {
      await issueParkingPass({
        kind: 'visitor',
        plate: el('parkingPlate').value,
        colour: el('parkingColour').value,
        vehicleType: el('parkingVehicleType').value,
        hours: el('parkingHours').value,
        visitorName: el('parkingVisitor').value,
      }, status);
      el('parkingRequestForm').reset();
      if (el('parkingHours') && el('parkingDefaultHours')) {
        el('parkingHours').value = el('parkingDefaultHours').value || '24';
      }
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not issue visitor pass';
    }
  });

  let parkingStaffBlob = null;

  function resetParkingStaffSelfie() {
    parkingStaffBlob = null;
    const preview = el('parkingStaffPreview');
    const snap = el('parkingStaffSnap');
    const retake = el('parkingStaffRetakeBtn');
    const file = el('parkingStaffFile');
    if (preview) preview.hidden = true;
    if (snap) snap.removeAttribute('src');
    if (retake) retake.hidden = true;
    if (file) file.value = '';
  }

  function setParkingStaffSelfie(file) {
    if (!file) return;
    parkingStaffBlob = file;
    const snap = el('parkingStaffSnap');
    const preview = el('parkingStaffPreview');
    const retake = el('parkingStaffRetakeBtn');
    if (snap) snap.src = URL.createObjectURL(file);
    if (preview) preview.hidden = false;
    if (retake) retake.hidden = false;
  }

  el('parkingStaffCaptureBtn')?.addEventListener('click', () => {
    el('parkingStaffFile')?.click();
  });
  el('parkingStaffRetakeBtn')?.addEventListener('click', () => {
    resetParkingStaffSelfie();
    el('parkingStaffFile')?.click();
  });
  el('parkingStaffFile')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    if (file) setParkingStaffSelfie(file);
  });

  el('parkingStaffForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('parkingStaffStatus');
    if (!parkingStaffBlob) {
      if (status) status.textContent = 'Take a selfie of the staff member first.';
      return;
    }
    const name = (el('parkingStaffName')?.value || '').trim();
    if (name.length < 2) {
      if (status) status.textContent = 'Enter the staff member’s full name.';
      return;
    }
    try {
      if (status) status.textContent = 'Issuing…';
      const fd = new FormData();
      fd.append('name', name);
      fd.append('category', el('parkingStaffCategory')?.value || 'other');
      fd.append('months', el('parkingStaffMonths')?.value || '3');
      fd.append('phone', (el('parkingStaffPhone')?.value || '').trim());
      fd.append('photo', parkingStaffBlob, parkingStaffBlob.name || 'selfie.jpg');
      const data = await api('/api/rwa/parking/staff', { method: 'POST', body: fd });
      const mailed = data.pass?.emailDelivery?.channel === 'email';
      if (status) {
        status.textContent = mailed
          ? 'Staff pass issued and emailed. It is listed below.'
          : (data.pass?.emailDelivery?.reason === 'no_email'
            ? 'Staff pass issued. Add an email on Profile to receive a copy.'
            : 'Staff pass issued and listed below.');
      }
      el('parkingStaffForm').reset();
      resetParkingStaffSelfie();
      await loadParkingPanel();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not issue staff pass';
    }
  });

  el('parkingRefreshBtn')?.addEventListener('click', () => loadParkingPanel().catch(() => {}));

  el('parkingGatePrintBtn')?.addEventListener('click', () => printParkingGatePoster());
  el('parkingGateShareBtn')?.addEventListener('click', () => {
    shareParkingGateLink().catch(() => {});
  });

  el('marketplaceRefreshBtn')?.addEventListener('click', () => loadMarketplaceModeration().catch(() => {}));
  el('marketplaceModerateStatusFilter')?.addEventListener('change', () => loadMarketplaceModeration().catch(() => {}));
  el('marketplaceAdsRefreshBtn')?.addEventListener('click', () => loadMarketplaceAds().catch(() => {}));
  el('marketplaceAdsStatusFilter')?.addEventListener('change', () => loadMarketplaceAds().catch(() => {}));
  el('marketplaceAdCancelBtn')?.addEventListener('click', () => resetMarketplaceAdForm());
  el('marketplaceListingCancelBtn')?.addEventListener('click', () => resetMarketplaceListingForm());
  el('marketplaceListingForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('marketplaceListingStatus');
    const editId = (el('marketplaceListingEditId')?.value || '').trim();
    if (!editId) return;
    try {
      const fd = new FormData();
      fd.append('title', (el('marketplaceListingTitle')?.value || '').trim());
      fd.append('category', el('marketplaceListingCategory')?.value || 'other');
      fd.append('description', (el('marketplaceListingDesc')?.value || '').trim());
      fd.append('contactName', (el('marketplaceListingName')?.value || '').trim());
      fd.append('phone', (el('marketplaceListingPhone')?.value || '').trim());
      fd.append('email', (el('marketplaceListingEmail')?.value || '').trim());
      fd.append('website', (el('marketplaceListingWebsite')?.value || '').trim());
      fd.append('area', (el('marketplaceListingArea')?.value || '').trim());
      const imageFile = el('marketplaceListingImage')?.files?.[0];
      if (imageFile) fd.append('image', imageFile);
      await api(`/api/rwa/marketplace/${encodeURIComponent(editId)}`, { method: 'PATCH', body: fd });
      resetMarketplaceListingForm();
      if (status) status.textContent = 'Listing saved.';
      await loadMarketplaceModeration();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save listing';
    }
  });
  el('marketplaceAdForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('marketplaceAdStatus');
    const editId = (el('marketplaceAdEditId')?.value || '').trim();
    try {
      const fd = new FormData();
      fd.append('kind', 'ad');
      fd.append('title', (el('marketplaceAdTitle')?.value || '').trim());
      fd.append('category', el('marketplaceAdCategory')?.value || 'colony');
      fd.append('description', (el('marketplaceAdDesc')?.value || '').trim());
      fd.append('contactName', (el('marketplaceAdName')?.value || '').trim());
      fd.append('phone', (el('marketplaceAdPhone')?.value || '').trim());
      const imageFile = el('marketplaceAdImage')?.files?.[0];
      if (imageFile) fd.append('image', imageFile);
      const shareCity = !editId && el('marketplaceShareCityInput')?.checked === true;
      const out = editId
        ? await api(`/api/rwa/marketplace/${encodeURIComponent(editId)}`, { method: 'PATCH', body: fd })
        : await api('/api/rwa/marketplace', { method: 'POST', body: fd });
      const itemId = out.item?.id || editId;
      let cityNote = '';
      if (shareCity && itemId) {
        try {
          await shareToCityHub({ type: 'marketplace', id: itemId });
          cityNote = ' Shared to City of Mandi for review.';
        } catch (shareErr) {
          cityNote = ` City of Mandi share failed: ${shareErr.message || 'try again later'}.`;
        }
      }
      resetMarketplaceAdForm();
      if (status) status.textContent = editId ? `Ad saved.${cityNote}` : `Ad published on the homepage.${cityNote}`;
      await loadMarketplaceAds().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || (editId ? 'Could not save ad' : 'Could not publish ad');
    }
  });
  el('marketplacePendingList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-mk-action]');
    const card = event.target.closest('[data-mk-id]');
    if (!btn || !card) return;
    const id = card.getAttribute('data-mk-id');
    const action = btn.getAttribute('data-mk-action');
    const item = listingsCache.find((n) => n.id === id);
    if (action === 'edit') {
      startMarketplaceListingEdit(item);
      return;
    }
    if (action === 'delete') {
      if (!window.confirm(`Remove “${item?.title || 'this listing'}” permanently?`)) return;
      btn.disabled = true;
      try {
        await api(`/api/rwa/marketplace/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (el('marketplaceListingEditId')?.value === id) resetMarketplaceListingForm();
        await loadMarketplaceModeration();
      } catch (err) {
        alert(err.message || 'Remove failed');
        btn.disabled = false;
      }
      return;
    }
    if (action === 'archived' && !window.confirm(`Suspend “${item?.title || 'this listing'}”? It will be hidden from the homepage until it is enabled again.`)) return;
    btn.disabled = true;
    try {
      await api(`/api/rwa/marketplace/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: action }),
      });
      if (el('marketplaceListingEditId')?.value === id) resetMarketplaceListingForm();
      await loadMarketplaceModeration();
    } catch (err) {
      alert(err.message || 'Update failed');
      btn.disabled = false;
    }
  });
  el('marketplaceAdsList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-ad-action]');
    const card = event.target.closest('[data-ad-id]');
    if (!btn || !card) return;
    const id = card.getAttribute('data-ad-id');
    const action = btn.getAttribute('data-ad-action');
    const item = adsCache.find((n) => n.id === id);
    if (action === 'edit') {
      startMarketplaceAdEdit(item);
      return;
    }
    if (action === 'delete') {
      if (!window.confirm(`Remove “${item?.title || 'this ad'}” permanently? It will disappear from the homepage.`)) return;
      btn.disabled = true;
      try {
        await api(`/api/rwa/marketplace/${encodeURIComponent(id)}`, { method: 'DELETE' });
        if (el('marketplaceAdEditId')?.value === id) resetMarketplaceAdForm();
        await loadMarketplaceAds();
      } catch (err) {
        alert(err.message || 'Remove failed');
        btn.disabled = false;
      }
      return;
    }
    const nextStatus = action === 'archived' ? 'archived' : 'published';
    if (nextStatus === 'archived' && !window.confirm(`Disable “${item?.title || 'this ad'}”? It will be hidden from the homepage until you enable it again.`)) return;
    btn.disabled = true;
    try {
      await api(`/api/rwa/marketplace/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: nextStatus }),
      });
      await loadMarketplaceAds();
    } catch (err) {
      alert(err.message || 'Update failed');
      btn.disabled = false;
    }
  });

  el('parkingLookupForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    await lookupParkingPass(el('parkingLookupInput')?.value || '');
  });

  el('parkingScanPlateBtn')?.addEventListener('click', () => {
    const ocr = parkingOcr();
    if (!ocr.phone && !parkingOcrServerEnabled()) {
      const status = el('parkingLookupStatus');
      if (status) status.textContent = 'Plate reading is turned off in Pass settings. Type the registration, or enable a reader.';
      return;
    }
    openParkingScanner('plate').catch((err) => {
      const status = el('parkingLookupStatus');
      if (status) status.textContent = err.message || 'Could not open plate scanner';
    });
  });
  el('parkingScanQrBtn')?.addEventListener('click', () => {
    openParkingScanner('qr').catch((err) => {
      const status = el('parkingLookupStatus');
      if (status) status.textContent = err.message || 'Could not open QR scanner';
    });
  });

  el('parkingScanCloseBtn')?.addEventListener('click', () => stopParkingScanner());
  el('parkingScanCancelBtn')?.addEventListener('click', () => stopParkingScanner());
  el('parkingScanDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    stopParkingScanner();
  });
  el('parkingScanFallbackBtn')?.addEventListener('click', () => {
    const mode = parkingScan.mode;
    stopParkingScanner();
    if (mode === 'qr') el('parkingScanQrFile')?.click();
    else el('parkingScanPlateFile')?.click();
  });
  el('parkingScanCaptureBtn')?.addEventListener('click', async () => {
    const btn = el('parkingScanCaptureBtn');
    if (btn) btn.disabled = true;
    try {
      await captureParkingScanNow();
    } catch (err) {
      setParkingScanLive(err.message || 'Could not read');
      const status = el('parkingLookupStatus');
      if (status) status.textContent = err.message || 'Scan failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('parkingScanPlateFile')?.addEventListener('change', async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    const status = el('parkingLookupStatus');
    const btn = el('parkingScanPlateBtn');
    if (btn) btn.disabled = true;
    try {
      await scanParkingPlateFile(file);
    } catch (err) {
      if (status) status.textContent = err.message || 'Plate scan failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('parkingScanQrFile')?.addEventListener('change', async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    const status = el('parkingLookupStatus');
    const btn = el('parkingScanQrBtn');
    if (btn) btn.disabled = true;
    try {
      await scanParkingQrFile(file);
    } catch (err) {
      if (status) status.textContent = err.message || 'QR scan failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('parkingHoursForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('parkingHoursStatus');
    if (status) status.textContent = 'Saving…';
    try {
      const saved = await api('/api/rwa/parking/settings', {
        method: 'PATCH',
        body: JSON.stringify({
          defaultHours: Number(el('parkingDefaultHours').value),
          ocr: readParkingOcrForm(),
        }),
      });
      fillParkingOcrSettings(saved.ocr);
      if (status) status.textContent = saved.ocr?.rust
        ? 'Pass settings saved. Native Rust reader is on.'
        : 'Pass settings saved.';
      if (el('parkingHours')) el('parkingHours').value = el('parkingDefaultHours').value;
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save';
    }
  });

  el('parkingCardList')?.addEventListener('click', onParkingActionClick);
  el('parkingPendingList')?.addEventListener('click', onParkingActionClick);
  el('parkingAdhocList')?.addEventListener('click', onParkingActionClick);
  el('parkingLookupResult')?.addEventListener('click', onParkingActionClick);
  el('parkingAdhocList')?.addEventListener('submit', onParkingUpgradeStaffSubmit);
  el('parkingLookupResult')?.addEventListener('submit', onParkingUpgradeStaffSubmit);

  async function onParkingUpgradeStaffSubmit(event) {
    const form = event.target.closest('form.parking-upgrade-staff-form');
    if (!form) return;
    event.preventDefault();
    if (!hasEntitlement('pass_upgrade_staff')) {
      window.alert('Pass · upgrade to staff entitlement required');
      return;
    }
    const id = form.getAttribute('data-pass-id');
    if (!id) return;
    const fd = new FormData(form);
    const houseId = String(fd.get('houseId') || '').trim();
    const statusEl = form.querySelector('.parking-upgrade-staff-status');
    const btn = form.querySelector('button[type="submit"]');
    if (!houseId) {
      if (statusEl) statusEl.textContent = 'Enter the household plot or house id.';
      return;
    }
    if (!window.confirm(`Convert this ad-hoc pass to a staff pass for ${houseId}?`)) return;
    if (btn) btn.disabled = true;
    if (statusEl) statusEl.textContent = 'Upgrading…';
    try {
      const data = await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/upgrade-staff`, {
        method: 'POST',
        body: JSON.stringify({
          houseId,
          category: String(fd.get('category') || 'other'),
          months: Number(fd.get('months') || 3),
          phone: String(fd.get('phone') || '').trim(),
        }),
      });
      if (statusEl) statusEl.textContent = `Upgraded to staff · ${data.pass?.code || ''} · plot ${data.pass?.plotNo || houseId}`;
      await loadParkingPanel();
      if (data.pass) {
        applyParkingLookupResult({ pass: { ...data.pass, detailLevel: 'manage' }, match: { kind: 'exact' } }, data.pass.code || '');
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || 'Upgrade failed';
      else window.alert(err.message || 'Upgrade failed');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function onParkingActionClick(event) {
    const btn = event.target.closest('button[data-id]');
    if (!btn) return;
    const id = btn.getAttribute('data-id');
    if (!id) return;
    try {
      if (btn.classList.contains('parking-renew')) {
        if (!window.confirm(btn.textContent.includes('EC') ? 'Send this 2nd renewal to the EC for approval?' : 'Renew this pass now? EC will be notified.')) return;
        await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/renew`, { method: 'POST', body: '{}' });
        await loadParkingPanel();
      } else if (btn.classList.contains('parking-remove')) {
        const staff = btn.getAttribute('data-kind') === 'staff';
        if (!window.confirm(staff ? 'End this household staff pass?' : 'Remove this registered member vehicle?')) return;
        await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/remove`, { method: 'POST', body: '{}' });
        await loadParkingPanel();
      } else if (btn.classList.contains('parking-approve')) {
        await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/approve`, { method: 'POST', body: '{}' });
        await loadParkingPanel();
      } else if (btn.classList.contains('parking-reject')) {
        const note = window.prompt('Reason (optional)') || '';
        await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/reject`, {
          method: 'POST',
          body: JSON.stringify({ note }),
        });
        await loadParkingPanel();
      } else if (btn.classList.contains('parking-save-photo')) {
        btn.disabled = true;
        try {
          await saveParkingCardPhoto(id, btn.getAttribute('data-code') || '');
        } finally {
          btn.disabled = false;
        }
      } else if (btn.classList.contains('parking-revoke')) {
        if (!window.confirm('Revoke this pass?')) return;
        await api(`/api/rwa/parking/passes/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: '{}' });
        await loadParkingPanel();
      }
    } catch (err) {
      alert(err.message || 'Action failed');
    }
  }
  el('duesRemindPendingBtn')?.addEventListener('click', async () => {
    if (!confirm('Send a push dues reminder to all plots with outstanding balance?')) return;
    try {
      const data = await api('/api/rwa/dues/remind', {
        method: 'POST',
        body: JSON.stringify({ allPending: true, note: 'Please clear pending colony dues.' }),
      });
      if (el('ledgerEditStatus')) {
        el('ledgerEditStatus').textContent = `Reminder queued for ${data.count || 0} plot(s).`;
      }
    } catch (e) {
      if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = e.message || 'Remind failed';
    }
  });

  function applyRouteHash() {
    if (!state.session) {
      applyPreLoginRoute();
      return;
    }
    if (!infoDeepLink) {
      infoDeepLink = parseInfoDeepLink(location.hash) || readPendingInfo({ consume: false });
    }
    if (infoDeepLink) {
      switchPanel('info');
      return;
    }
    const hash = (location.hash || '').replace(/^#/, '');
    if (!hash) return;
    if (hash === 'members' || hash === 'login') {
      history.replaceState(null, '', `${location.pathname}${location.search}#home`);
      switchPanel('home');
      return;
    }
    if (hash === 'messages' || hash.startsWith('messages/')) {
      switchPanel('messages');
      return;
    }
    const infoLink = parseInfoDeepLink(hash);
    if (infoLink) {
      infoDeepLink = infoLink;
      switchPanel('info');
      return;
    }
    const panelName = hash.split(/[?/]/)[0];
    if (panelName === 'parking') {
      switchPanel('parking');
      return;
    }
    if (hash === 'dues' || hash === 'concerns' || hash === 'profile'
      || hash === 'directory' || hash === 'works' || hash === 'proceedings' || hash === 'admin') {
      switchPanel(hash);
      return;
    }
    if (hash === 'alerts' || hash === 'notifications') {
      openNotificationsDialog().catch(() => {});
      return;
    }
    if (hash === 'home' || hash === 'home/services' || hash.startsWith('home/')) {
      switchPanel('home');
      applyBoardRouteHash();
      return;
    }
  }
  window.addEventListener('hashchange', () => {
    if (state.session?.resident) {
      applyRouteHash();
      return;
    }
    if (isLandingBoardHash(location.hash)) {
      applyLandingBoardHash();
      return;
    }
    applyPreLoginRoute();
  });

  el('landingMembersBtn')?.addEventListener('click', () => {
    showMembersGate({ pushHash: true });
  });
  el('landingHeroSignInBtn')?.addEventListener('click', () => {
    showMembersGate({ pushHash: true });
  });
  (() => {
    const shell = el('landingView');
    if (!shell) return;
    const onScroll = () => {
      shell.classList.toggle('is-scrolled', window.scrollY > 28);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  })();
  el('gateBackToLandingBtn')?.addEventListener('click', () => {
    showLanding();
  });
  el('gateBackBrand')?.addEventListener('click', (event) => {
    event.preventDefault();
    showLanding();
  });

  el('logoutBtn')?.addEventListener('click', async () => {
    try { await api('/api/rwa/logout', { method: 'POST', body: '{}' }); } catch (_e) { /* ignore */ }
    clearPersistedAuth();
    clearAuthbuddyLinkDismissed();
    document.getElementById('authbuddyLinkModal')?.remove();
    // Colony Sign out must also end AuthBuddy SSO. Otherwise auth.html sees a
    // live /agent/v1/session cookie and auto-enters without a challenge.
    const returnTo = new URL('index.html', window.location.href).href;
    if (window.VeerAuth && typeof window.VeerAuth.logout === 'function') {
      window.VeerAuth.logout(returnTo);
      return;
    }
    try { localStorage.removeItem('hbcsanyard_authbuddy_session'); } catch (_e) { /* ignore */ }
    window.location.replace('/agent/v1/logout?return_to=' + encodeURIComponent(returnTo));
  });

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchPanel(tab.dataset.panel));
  });

  async function loadHouseholdMembers() {
    const block = el('householdBlock');
    const list = el('householdMemberList');
    const addForm = el('householdAddForm');
    if (!block || !list) return;
    const r = state.session?.resident;
    if (!r || r.superAdmin || !r.houseId) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    try {
      const data = await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/members`);
      const canManage = Boolean(data.canManage);
      if (addForm) addForm.hidden = !canManage;
      list.innerHTML = (data.members || []).map((m) => {
        const badges = [
          m.isPrimary ? 'Owner' : (m.isPrimaryDelegate ? 'Primary delegate' : (m.relationLabel || m.relation)),
          m.viewOnly ? 'View only' : null,
        ].filter(Boolean).join(' · ');
        const actions = canManage && !m.isPrimary ? `
          <div class="btn-row">
            <label class="check compact"><input type="checkbox" class="hh-primary-delegate" data-id="${escapeHtml(m.id)}" ${m.isPrimaryDelegate ? 'checked' : ''}> Primary delegate (EC-eligible)</label>
            <label class="check compact"><input type="checkbox" class="hh-view-only" data-id="${escapeHtml(m.id)}" ${m.viewOnly ? 'checked' : ''} ${m.isPrimaryDelegate ? 'disabled' : ''}> View only</label>
            <button type="button" class="btn ghost compact hh-remove" data-id="${escapeHtml(m.id)}">Remove</button>
          </div>` : (m.isPrimary
          ? '<p class="muted">Plot owner — unique login identity. EC access applies only if this person holds the plot’s EC seat.</p>'
          : '');
        return `
          <article class="household-member-card" data-id="${escapeHtml(m.id)}">
            ${hhAvatarHtml(m)}
            <strong>${escapeHtml(m.name)}</strong>
            <span class="muted">${escapeHtml(badges)}</span>
            <span class="muted">${escapeHtml(m.email || '—')} · ${escapeHtml(m.phone || '—')}</span>
            ${actions}
          </article>`;
      }).join('') || '<p class="muted">No household members yet.</p>';
      await hydrateHhAvatars(list);
    } catch (err) {
      list.innerHTML = `<p class="error">${escapeHtml(err.message || 'Could not load household')}</p>`;
    }
  }

  async function loadHouseholdTenants() {
    const block = el('householdTenantBlock');
    const list = el('householdTenantList');
    const addForm = el('householdTenantForm');
    if (!block || !list) return;
    const r = state.session?.resident;
    if (!r || r.superAdmin || !r.houseId) {
      block.hidden = true;
      return;
    }
    block.hidden = false;
    try {
      const data = await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/tenants`);
      const canManage = Boolean(data.canManage);
      if (addForm) addForm.hidden = !canManage;
      const tenants = data.tenants || [];
      list.innerHTML = tenants.length ? tenants.map((t) => {
        const ended = t.status === 'ended';
        const when = [t.occupancyStart, t.occupancyEnd].filter(Boolean).join(' → ') || 'Dates not set';
        const actions = canManage && !ended
          ? `<div class="btn-row"><button type="button" class="btn ghost compact ht-end" data-id="${escapeHtml(t.id)}">End occupancy</button></div>`
          : '';
        return `
          <article class="household-member-card${ended ? ' tenant-card-ended' : ''}" data-id="${escapeHtml(t.id)}">
            <strong>${escapeHtml(t.name)}</strong>
            <span class="muted">${ended ? 'Occupancy ended' : 'Current tenant'} · not a household login</span>
            <span class="muted">${escapeHtml(t.phone || '—')} · ${escapeHtml(t.email || '—')}</span>
            <span class="muted">${escapeHtml(when)}</span>
            ${t.note ? `<span class="muted">${escapeHtml(t.note)}</span>` : ''}
            ${actions}
          </article>`;
      }).join('') : '<p class="muted">No tenants recorded for this plot. Tenants are occupancy records only — they cannot sign in.</p>';
    } catch (err) {
      list.innerHTML = `<p class="error">${escapeHtml(err.message || 'Could not load tenants')}</p>`;
    }
  }

  el('householdAddForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const r = state.session?.resident;
    const status = el('householdStatus');
    if (!r?.houseId) return;
    if (status) status.textContent = 'Saving…';
    try {
      await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/members`, {
        method: 'POST',
        body: JSON.stringify({
          name: el('hhName').value.trim(),
          relation: el('hhRelation').value,
          email: el('hhEmail').value.trim(),
          phone: el('hhPhone').value.trim(),
          viewOnly: Boolean(el('hhViewOnly')?.checked),
          isPrimaryDelegate: Boolean(el('hhPrimaryDelegate')?.checked),
        }),
      });
      el('householdAddForm').reset();
      if (status) status.textContent = 'Delegate added.';
      await loadHouseholdMembers();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not add member';
    }
  });

  el('householdMemberList')?.addEventListener('change', async (event) => {
    const primaryDel = event.target.closest('.hh-primary-delegate');
    const box = event.target.closest('.hh-view-only');
    const r = state.session?.resident;
    if (primaryDel) {
      const id = primaryDel.getAttribute('data-id');
      if (!r?.houseId || !id) return;
      try {
        await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/members/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ isPrimaryDelegate: primaryDel.checked }),
        });
        await loadHouseholdMembers();
      } catch (err) {
        alert(err.message || 'Could not update primary delegate');
        primaryDel.checked = !primaryDel.checked;
      }
      return;
    }
    if (!box) return;
    const id = box.getAttribute('data-id');
    if (!r?.houseId || !id) return;
    try {
      await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/members/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ viewOnly: box.checked }),
      });
      await loadHouseholdMembers();
    } catch (err) {
      alert(err.message || 'Could not update access');
      box.checked = !box.checked;
    }
  });

  el('householdMemberList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('.hh-remove');
    if (!btn) return;
    const r = state.session?.resident;
    const id = btn.getAttribute('data-id');
    if (!r?.houseId || !id) return;
    if (!window.confirm('Remove this household login?')) return;
    try {
      await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/members/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        body: '{}',
      });
      await loadHouseholdMembers();
    } catch (err) {
      alert(err.message || 'Could not remove member');
    }
  });

  el('householdTenantForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const r = state.session?.resident;
    const status = el('householdTenantStatus');
    if (!r?.houseId) return;
    if (status) status.textContent = 'Saving…';
    try {
      await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/tenants`, {
        method: 'POST',
        body: JSON.stringify({
          name: el('htName').value.trim(),
          phone: el('htPhone').value.trim(),
          email: el('htEmail').value.trim(),
          note: el('htNote').value.trim(),
          occupancyStart: el('htFrom').value,
          occupancyEnd: el('htUntil').value,
        }),
      });
      el('householdTenantForm').reset();
      if (status) status.textContent = 'Tenant saved. Issue their vehicle pass from Pass.';
      await loadHouseholdTenants();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save tenant';
    }
  });

  el('householdTenantList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('.ht-end');
    if (!btn) return;
    const r = state.session?.resident;
    const id = btn.getAttribute('data-id');
    if (!r?.houseId || !id) return;
    if (!window.confirm('End this occupancy? The tenant will stay in history but cannot get a new pass until you add them again.')) return;
    try {
      await api(`/api/rwa/household/${encodeURIComponent(r.houseId)}/tenants/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        body: '{}',
      });
      await loadHouseholdTenants();
    } catch (err) {
      alert(err.message || 'Could not end occupancy');
    }
  });

  el('profileForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('profileStatus');
    status.textContent = 'Saving…';
    try {
      const body = {
        title: el('profileTitle')?.value.trim() || '',
        name: el('profileName').value.trim(),
        profession: el('profileProfession')?.value.trim() || '',
        employmentStatus: el('profileEmployment')?.value || 'unknown',
        email: el('profileEmail').value.trim(),
        phone: el('profilePhone').value.trim(),
      };
      if (isEcAdmin() && !isSuperAdmin()) {
        body.officialTitle = el('profileOfficialTitle')?.value.trim() || '';
      }
      const data = await api('/api/rwa/profile', {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      state.session.resident = data.resident;
      setAuthed(state.session);
      ensurePanelVisibility(activePanelName());
      status.textContent = 'Saved.';
    } catch (err) {
      status.textContent = err.message || 'Save failed';
    }
  });

  el('profilePhotoPickBtn')?.addEventListener('click', () => {
    if (isViewOnly() || !state.session?.resident?.memberId) return;
    el('profilePhotoFile')?.click();
  });
  el('profilePhotoFile')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    if (file) openPhotoCrop(file);
  });
  el('profilePhotoRemoveBtn')?.addEventListener('click', async () => {
    if (!window.confirm('Remove your profile photo?')) return;
    const status = el('profilePhotoStatus');
    if (status) status.textContent = 'Removing…';
    try {
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const res = await fetch('/api/rwa/profile/photo', {
        method: 'DELETE',
        credentials: 'same-origin',
        headers,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      if (data.resident) {
        state.session.resident = data.resident;
        setAuthed(state.session);
      }
      if (status) status.textContent = 'Photo removed.';
      await loadHouseholdMembers().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not remove photo';
    }
  });

  el('photoCropZoom')?.addEventListener('input', () => {
    photoCrop.scale = Number(el('photoCropZoom').value) || photoCrop.minScale;
    applyPhotoCropTransform();
  });

  (function bindPhotoCropDrag() {
    const vp = el('photoCropViewport');
    if (!vp) return;
    const onMove = (clientX, clientY) => {
      if (!photoCrop.dragging) return;
      photoCrop.offsetX = photoCrop.originX + (clientX - photoCrop.startX);
      photoCrop.offsetY = photoCrop.originY + (clientY - photoCrop.startY);
      applyPhotoCropTransform();
    };
    vp.addEventListener('pointerdown', (event) => {
      photoCrop.dragging = true;
      vp.classList.add('is-dragging');
      photoCrop.startX = event.clientX;
      photoCrop.startY = event.clientY;
      photoCrop.originX = photoCrop.offsetX;
      photoCrop.originY = photoCrop.offsetY;
      vp.setPointerCapture?.(event.pointerId);
    });
    vp.addEventListener('pointermove', (event) => onMove(event.clientX, event.clientY));
    const endDrag = () => {
      photoCrop.dragging = false;
      vp.classList.remove('is-dragging');
    };
    vp.addEventListener('pointerup', endDrag);
    vp.addEventListener('pointercancel', endDrag);
  })();

  el('photoCropCancelBtn')?.addEventListener('click', () => closePhotoCrop());
  el('photoCropDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closePhotoCrop();
  });
  el('photoCropForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const errEl = el('photoCropError');
    const btn = el('photoCropApplyBtn');
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = '';
    }
    if (btn) btn.disabled = true;
    try {
      const blob = await exportCroppedPhotoBlob();
      if (el('profilePhotoStatus')) el('profilePhotoStatus').textContent = 'Uploading…';
      await uploadProfilePhotoBlob(blob);
      closePhotoCrop();
      await loadHouseholdMembers().catch(() => {});
    } catch (err) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = err.message || 'Could not save photo';
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noticeImageInput')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    const preview = el('noticeImagePreview');
    if (!preview) return;
    if (!file) {
      preview.hidden = true;
      preview.removeAttribute('src');
      return;
    }
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });

  el('marketplaceAdImage')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    const preview = el('marketplaceAdImagePreview');
    if (!preview) return;
    if (!file) {
      preview.hidden = true;
      preview.removeAttribute('src');
      return;
    }
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });

  el('marketplaceListingImage')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    const preview = el('marketplaceListingImagePreview');
    if (!preview) return;
    if (!file) {
      preview.hidden = true;
      preview.removeAttribute('src');
      return;
    }
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });

  el('noticeForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    await saveNotice({ asDraft: false });
  });

  el('colonyServicesEditBtn')?.addEventListener('click', () => {
    if (!hasEntitlement('manage_notices') || !colonyServicesCache) return;
    setBoardTab('services');
    if (colonyServicesEditing) {
      setColonyServicesEditing(false);
      renderColonyServicesView(colonyServicesCache);
      return;
    }
    renderColonyServicesEditor(colonyServicesCache);
    setColonyServicesEditing(true);
  });
  el('colonyServicesSaveBtn')?.addEventListener('click', () => saveColonyServices().catch(console.error));
  el('colonyServicesCancelBtn')?.addEventListener('click', () => {
    setColonyServicesEditing(false);
    if (colonyServicesCache) renderColonyServicesView(colonyServicesCache);
    if (el('colonyServicesStatus')) el('colonyServicesStatus').textContent = '';
  });
  el('colonyServicesEditor')?.addEventListener('click', (event) => {
    const addBtn = event.target.closest('[data-cs-add]');
    if (addBtn) {
      addColonyServicesRow(addBtn.getAttribute('data-cs-add'));
      return;
    }
    const removeBtn = event.target.closest('[data-cs-remove]');
    if (!removeBtn) return;
    const row = removeBtn.closest('.colony-services-edit-row');
    const box = row?.parentElement;
    row?.remove();
    if (box && !box.querySelector('.colony-services-edit-row')) {
      box.innerHTML = '<p class="muted">No rows yet — add one.</p>';
    }
  });

  el('noticeDraftBtn')?.addEventListener('click', async () => {
    await saveNotice({ asDraft: true });
  });

  el('noticeCancelEditBtn')?.addEventListener('click', () => resetNoticeForm());
  el('noticeDraftRefreshBtn')?.addEventListener('click', () => loadNoticeDrafts().catch(console.error));
  el('draftShareForm')?.addEventListener('submit', saveDraftShares);
  el('draftShareCancelBtn')?.addEventListener('click', () => closeDraftShareDialog());
  el('draftShareMemberList')?.addEventListener('change', (event) => {
    const row = event.target.closest('.draft-share-row');
    if (!row) return;
    if (event.target.name === 'shareHouse') syncShareRowState(row);
  });

  el('noticeDraftList')?.addEventListener('click', async (event) => {
    const editBtn = event.target.closest('.notice-draft-edit');
    const pubBtn = event.target.closest('.notice-draft-publish');
    const delBtn = event.target.closest('.notice-draft-delete');
    const shareBtn = event.target.closest('.notice-draft-share');
    if (!isEcAdmin()) return;

    if (editBtn) {
      const notice = draftsCache.find((n) => n.id === editBtn.getAttribute('data-id'));
      if (notice) startNoticeEdit(notice);
      return;
    }

    if (shareBtn) {
      const notice = draftsCache.find((n) => n.id === shareBtn.getAttribute('data-id'));
      if (notice) openDraftShareDialog(notice).catch((e) => alert(e.message || 'Share failed'));
      return;
    }

    if (pubBtn) {
      const id = pubBtn.getAttribute('data-id');
      const notice = draftsCache.find((n) => n.id === id);
      if (!notice) return;
      if (notice.canEdit === false) {
        alert('View only — ask the owner for edit access.');
        return;
      }
      if (!String(notice.body || '').trim() || String(notice.body || '').trim().length < 3) {
        startNoticeEdit(notice);
        if (el('noticeFormStatus')) el('noticeFormStatus').textContent = 'Finish the body, then publish.';
        return;
      }
      if (!window.confirm(`Publish “${notice.title}” to the colony board?`)) return;
      pubBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({
            title: notice.title,
            body: notice.body,
            category: notice.category,
            pinned: false,
            status: 'published',
          }),
        });
        await loadNoticeDrafts();
        await loadHome();
        switchPanel('home');
      } catch (err) {
        alert(err.message || 'Publish failed');
        pubBtn.disabled = false;
      }
      return;
    }

    if (delBtn) {
      const id = delBtn.getAttribute('data-id');
      const notice = draftsCache.find((n) => n.id === id);
      if (!notice?.isOwner) {
        alert('Only the draft owner can delete this draft.');
        return;
      }
      if (!window.confirm(`Delete draft “${notice?.title || id}”?`)) return;
      delBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, { method: 'DELETE', body: '{}' });
        await loadNoticeDrafts();
      } catch (err) {
        alert(err.message || 'Delete failed');
        delBtn.disabled = false;
      }
    }
  });

  function updateNoticeEngageUi(noticeId, { likeCount, commentCount, likedByMe } = {}) {
    const card = el('noticeList')?.querySelector(`.notice[data-id="${CSS.escape(noticeId)}"]`);
    if (!card) return;
    const likeBtn = card.querySelector('.notice-like');
    const likeCountEl = card.querySelector('.notice-like-count');
    const commentCountEl = card.querySelector('.notice-comment-count');
    if (typeof likeCount === 'number' && likeCountEl) likeCountEl.textContent = String(likeCount);
    if (typeof commentCount === 'number' && commentCountEl) commentCountEl.textContent = String(commentCount);
    if (likeBtn && typeof likedByMe === 'boolean') {
      likeBtn.classList.toggle('is-active', likedByMe);
      likeBtn.setAttribute('aria-pressed', likedByMe ? 'true' : 'false');
      likeBtn.title = likedByMe ? 'Unlike' : 'Like';
      const svg = likeBtn.querySelector('svg');
      if (svg) svg.setAttribute('fill', likedByMe ? 'currentColor' : 'none');
    }
    const cached = noticesCache.find((n) => n.id === noticeId);
    if (cached) {
      if (typeof likeCount === 'number') cached.likeCount = likeCount;
      if (typeof commentCount === 'number') cached.commentCount = commentCount;
      if (typeof likedByMe === 'boolean') cached.likedByMe = likedByMe;
    }
  }

  function renderNoticeCommentsList(comments) {
    if (!comments?.length) {
      return '<p class="muted">No comments yet. Be the first.</p>';
    }
    const me = state.session?.resident?.houseId;
    return comments.map((c) => {
      const canDelete = c.houseId === me || isEcAdmin();
      const when = formatIstDateTime(c.createdAt);
      return `
        <div class="notice-comment" data-comment-id="${escapeHtml(c.id)}">
          <div class="notice-comment-head">
            ${personAvatarHtml(c)}
            <strong>${escapeHtml(c.authorName || c.houseId || 'Resident')}</strong>
            <span class="muted">${escapeHtml(when)}</span>
            ${canDelete ? `<button type="button" class="btn ghost compact notice-comment-delete" data-comment-id="${escapeHtml(c.id)}" title="Remove">Remove</button>` : ''}
          </div>
          <p>${escapeHtml(c.body || '')}</p>
        </div>`;
    }).join('');
  }

  async function loadNoticeComments(noticeId, panel) {
    const list = panel?.querySelector('.notice-comments-list');
    if (!list) return;
    list.innerHTML = '<p class="muted">Loading comments…</p>';
    try {
      const data = await api(`/api/rwa/notices/${encodeURIComponent(noticeId)}/comments`);
      list.innerHTML = renderNoticeCommentsList(data.comments || []);
      await hydrateAvatars(list);
      updateNoticeEngageUi(noticeId, data);
    } catch (err) {
      list.innerHTML = `<p class="error">${escapeHtml(err.message || 'Could not load comments')}</p>`;
    }
  }

  el('noticeList')?.addEventListener('click', async (event) => {
    const likeBtn = event.target.closest('.notice-like');
    const commentToggle = event.target.closest('.notice-comment-toggle');
    const commentDelete = event.target.closest('.notice-comment-delete');
    const editBtn = event.target.closest('.notice-edit');
    const pinBtn = event.target.closest('.notice-pin');
    const delBtn = event.target.closest('.notice-delete');
    const upBtn = event.target.closest('.notice-move-up');
    const downBtn = event.target.closest('.notice-move-down');

    if (likeBtn) {
      event.preventDefault();
      const id = likeBtn.getAttribute('data-id');
      likeBtn.disabled = true;
      try {
        const data = await api(`/api/rwa/notices/${encodeURIComponent(id)}/like`, {
          method: 'POST',
          body: '{}',
        });
        updateNoticeEngageUi(id, data);
      } catch (err) {
        alert(err.message || 'Could not update like');
      } finally {
        likeBtn.disabled = false;
      }
      return;
    }

    if (commentToggle) {
      event.preventDefault();
      const id = commentToggle.getAttribute('data-id');
      const card = commentToggle.closest('.notice');
      const panel = card?.querySelector('.notice-comments');
      if (!panel) return;
      const open = panel.hidden;
      panel.hidden = !open;
      commentToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        card?.classList.add('is-open');
        card?.querySelector('.mobile-fold-head')?.setAttribute('aria-expanded', 'true');
        await loadNoticeComments(id, panel);
        scrollBelowAppHeader(panel);
      }
      return;
    }

    if (commentDelete) {
      event.preventDefault();
      const card = commentDelete.closest('.notice');
      const id = card?.getAttribute('data-id');
      const commentId = commentDelete.getAttribute('data-comment-id');
      if (!id || !commentId) return;
      if (!window.confirm('Remove this comment?')) return;
      commentDelete.disabled = true;
      try {
        const data = await api(
          `/api/rwa/notices/${encodeURIComponent(id)}/comments/${encodeURIComponent(commentId)}`,
          { method: 'DELETE', body: '{}' },
        );
        updateNoticeEngageUi(id, data);
        const panel = card.querySelector('.notice-comments');
        await loadNoticeComments(id, panel);
      } catch (err) {
        alert(err.message || 'Could not remove comment');
        commentDelete.disabled = false;
      }
      return;
    }

    if (!isEcAdmin()) return;

    if (editBtn) {
      const id = editBtn.getAttribute('data-id');
      const notice = noticesCache.find((n) => n.id === id);
      if (notice) startNoticeEdit(notice);
      return;
    }

    if (upBtn || downBtn) {
      const btn = upBtn || downBtn;
      const id = btn.getAttribute('data-id');
      const move = upBtn ? 'up' : 'down';
      btn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ move }),
        });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Could not reorder notice');
        btn.disabled = false;
      }
      return;
    }

    if (pinBtn) {
      const id = pinBtn.getAttribute('data-id');
      const pinned = pinBtn.getAttribute('data-pinned') === '1';
      pinBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ pinned: !pinned }),
        });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Could not update pin');
      } finally {
        pinBtn.disabled = false;
      }
      return;
    }

    if (delBtn) {
      const id = delBtn.getAttribute('data-id');
      const notice = noticesCache.find((n) => n.id === id);
      if (!window.confirm(`Delete notice “${notice?.title || id}”?`)) return;
      delBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, { method: 'DELETE', body: '{}' });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Delete failed');
      } finally {
        delBtn.disabled = false;
      }
    }
  });

  el('noticeList')?.addEventListener('submit', async (event) => {
    const form = event.target.closest('.notice-comment-form');
    if (!form) return;
    event.preventDefault();
    const id = form.getAttribute('data-id');
    const body = form.querySelector('textarea')?.value?.trim() || '';
    const btn = form.querySelector('button[type="submit"]');
    if (!id || !body) return;
    if (btn) btn.disabled = true;
    try {
      const data = await api(`/api/rwa/notices/${encodeURIComponent(id)}/comments`, {
        method: 'POST',
        body: JSON.stringify({ body }),
      });
      form.querySelector('textarea').value = '';
      updateNoticeEngageUi(id, data);
      const panel = form.closest('.notice-comments');
      await loadNoticeComments(id, panel);
    } catch (err) {
      alert(err.message || 'Could not post comment');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  function statusLabel(status) {
    return ({
      open: 'Open',
      in_progress: 'In progress',
      resolved: 'Resolved',
      closed: 'Closed',
    })[status] || status || 'Open';
  }

  function formatWhen(iso) {
    return formatIstDateTime(iso);
  }

  function renderMessageTrail(messages) {
    const items = messages || [];
    if (!items.length) return '<p class="muted">No messages yet.</p>';
    return `<div class="msg-trail">${items.map((m) => `
      <article class="msg-bubble ${m.authorRole === 'ec' ? 'is-ec' : 'is-resident'}">
        <header>
          ${personAvatarHtml(m)}
          <strong>${escapeHtml(m.authorName || (m.authorRole === 'ec' ? 'EC' : 'Resident'))}</strong>
          <span>${m.authorRole === 'ec' ? 'EC' : 'Resident'}${m.authorHouseId ? ` · plot ${escapeHtml(m.authorHouseId)}` : ''}</span>
          <time>${escapeHtml(formatWhen(m.createdAt))}</time>
        </header>
        <p>${escapeHtml(m.body)}</p>
        ${m.bodyHi ? `<p class="muted" lang="hi">${escapeHtml(m.bodyHi)}</p>` : ''}
      </article>`).join('')}</div>`;
  }

  function renderMailboxCard(g, { ecMode = false } = {}) {
    const closed = g.status === 'closed';
    const replyId = `reply-${escapeHtml(g.id)}`;
    const replyBox = closed
      ? '<p class="muted">Thread closed.</p>'
      : `
        <form class="mailbox-reply" data-id="${escapeHtml(g.id)}">
          <div class="author-lang-toggle" data-author-form="${replyId}" role="group" aria-label="Reply language">
            <button type="button" class="lang-btn is-active" data-author-lang="en" aria-pressed="true">EN</button>
            <button type="button" class="lang-btn" data-author-lang="hi" aria-pressed="false">हिं</button>
          </div>
          <label data-author-pane="${replyId}" data-lang="en">
            <span class="sr-only">Reply</span>
            <textarea name="body" rows="2" required placeholder="${ecMode ? 'EC reply…' : 'Add a reply…'}"></textarea>
          </label>
          <label data-author-pane="${replyId}" data-lang="hi" hidden>
            <span class="sr-only">Hindi reply</span>
            <textarea name="bodyHi" rows="2" placeholder="हिंदी में जवाब…"></textarea>
          </label>
          ${ecMode ? `
            <label class="mailbox-status-pick">
              Status
              <select name="status">
                <option value="in_progress"${g.status === 'in_progress' ? ' selected' : ''}>In progress</option>
                <option value="open"${g.status === 'open' ? ' selected' : ''}>Open</option>
                <option value="resolved"${g.status === 'resolved' ? ' selected' : ''}>Resolved</option>
                <option value="closed"${g.status === 'closed' ? ' selected' : ''}>Closed</option>
              </select>
            </label>` : ''}
          <div class="btn-row">
            <button type="submit" class="btn secondary compact">${ecMode ? 'Reply as EC' : 'Reply'}</button>
          </div>
          <p class="muted row-status" hidden></p>
        </form>`;
    return `
      <article class="grievance-card mobile-fold" data-id="${escapeHtml(g.id)}">
        <button type="button" class="mobile-fold-head" aria-expanded="false">
          <span class="mobile-fold-head-main">
            <span class="grievance-card-head">
              ${personAvatarHtml(g, { size: 'md' })}
              <span class="grievance-card-title">${escapeHtml(g.subject)}</span>
              <span class="grievance-badge is-${escapeHtml(g.status)}">${escapeHtml(statusLabel(g.status))}</span>
            </span>
            <span class="grievance-meta">
              ${escapeHtml(g.categoryLabel || g.category)}
              · plot <code>${escapeHtml(g.houseId)}</code>
              ${g.name ? ` · ${escapeHtml(g.name)}` : ''}
              · ${escapeHtml(formatWhen(g.updatedAt || g.createdAt))}
              · ${(g.messages || []).length} message${(g.messages || []).length === 1 ? '' : 's'}
              ${g.subjectHi ? ' · हिं' : ''}
            </span>
          </span>
          <span class="mobile-fold-chevron" aria-hidden="true"></span>
        </button>
        <div class="mobile-fold-body">
          ${renderMessageTrail(g.messages)}
          ${replyBox}
        </div>
      </article>`;
  }

  async function loadMailbox() {
    const status = el('mailboxStatusFilter')?.value || 'all';
    const category = el('mailboxCategoryFilter')?.value || 'all';
    const qs = new URLSearchParams();
    if (status && status !== 'all') qs.set('status', status);
    if (category && category !== 'all') qs.set('category', category);
    const data = await api(`/api/rwa/grievances?${qs.toString()}`);
    const list = el('mailboxList');
    const stats = data.stats || {};
    if (el('mailboxStats')) {
      el('mailboxStats').textContent =
        `${stats.total || 0} threads · ${stats.open || 0} open · ${stats.inProgress || 0} in progress · ${stats.resolved || 0} resolved`;
    }
    const rows = data.grievances || [];
    mailboxCache = rows;
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No concerns in the mailbox yet. Post the first one above.</p>';
      if (sectionLang.concerns === 'hi') renderConcernsOverlay();
      return;
    }
    list.innerHTML = rows.map((g) => renderMailboxCard(g, { ecMode: isEcAdmin() })).join('');
    refreshMobileListUi();
    await hydrateAvatars(list);
    if (sectionLang.concerns === 'hi') renderConcernsOverlay();
  }

  async function loadEcGrievances() {
    if (!hasEntitlement('manage_concerns')) return;
    const status = el('ecGrievanceStatusFilter')?.value || 'open';
    const category = el('ecGrievanceCategoryFilter')?.value || 'all';
    const qs = new URLSearchParams();
    if (status && status !== 'all') qs.set('status', status);
    if (category && category !== 'all') qs.set('category', category);
    const data = await api(`/api/rwa/grievances?${qs.toString()}`);
    const stats = data.stats || {};
    if (el('ecGrievanceStats')) {
      el('ecGrievanceStats').textContent =
        `${stats.open || 0} open · ${stats.inProgress || 0} in progress · ${stats.resolved || 0} resolved · ${stats.total || 0} total`;
    }
    const list = el('ecGrievanceList');
    const rows = data.grievances || [];
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No concerns match this filter.</p>';
      return;
    }
    list.innerHTML = rows.map((g) => renderMailboxCard(g, { ecMode: true })).join('');
    if (el('ecGrievanceStatus')) el('ecGrievanceStatus').textContent = '';
    refreshMobileListUi();
    await hydrateAvatars(list);
  }

  async function submitMailboxReply(form) {
    const id = form.getAttribute('data-id');
    const body = form.querySelector('textarea[name="body"]')?.value.trim() || '';
    const bodyHi = form.querySelector('textarea[name="bodyHi"]')?.value.trim() || '';
    const status = form.querySelector('select[name="status"]')?.value;
    const statusEl = form.querySelector('.row-status');
    const btn = form.querySelector('button[type="submit"]');
    if (!id || !body) return;
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = 'Sending…';
    }
    if (btn) btn.disabled = true;
    try {
      const payload = { body, bodyHi };
      if (status) payload.status = status;
      if (isEcAdmin()) {
        await api(`/api/rwa/grievances/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ response: body, bodyHi, status: status || 'in_progress' }),
        });
      } else {
        await api(`/api/rwa/grievances/${encodeURIComponent(id)}/messages`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      form.querySelector('textarea[name="body"]').value = '';
      const hiBox = form.querySelector('textarea[name="bodyHi"]');
      if (hiBox) hiBox.value = '';
      await loadMailbox();
      if (isEcAdmin()) await loadEcGrievances().catch(() => {});
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || 'Reply failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('grievanceForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('grievanceFormStatus');
    const btn = el('grievanceSubmitBtn');
    if (status) status.textContent = 'Posting…';
    if (btn) btn.disabled = true;
    try {
      await api('/api/rwa/grievances', {
        method: 'POST',
        body: JSON.stringify({
          category: el('grievanceCategory').value,
          subject: el('grievanceSubject').value.trim(),
          body: el('grievanceBody').value.trim(),
          subjectHi: el('grievanceSubjectHi')?.value.trim() || '',
          bodyHi: el('grievanceBodyHi')?.value.trim() || '',
        }),
      });
      el('grievanceForm').reset();
      setAuthorFormLang('grievance', 'en');
      if (status) status.textContent = 'Posted to the colony mailbox.';
      await loadMailbox();
      if (isEcAdmin()) await loadEcGrievances().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not post';
      setAuthorFormLang('grievance', 'en');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('mailboxList')?.addEventListener('submit', (event) => {
    const form = event.target.closest('form.mailbox-reply');
    if (!form) return;
    event.preventDefault();
    submitMailboxReply(form);
  });
  el('ecGrievanceList')?.addEventListener('submit', (event) => {
    const form = event.target.closest('form.mailbox-reply');
    if (!form) return;
    event.preventDefault();
    submitMailboxReply(form);
  });
  el('mailboxRefreshBtn')?.addEventListener('click', () => loadMailbox().catch(console.error));
  el('mailboxStatusFilter')?.addEventListener('change', () => loadMailbox().catch(console.error));
  el('mailboxCategoryFilter')?.addEventListener('change', () => loadMailbox().catch(console.error));

  el('infoRefreshBtn')?.addEventListener('click', () => loadInfoCentre().catch(console.error));
  el('infoFolderFilter')?.addEventListener('change', () => loadInfoCentre().catch(console.error));
  el('infoCategoryFilter')?.addEventListener('change', () => loadInfoCentre().catch(console.error));
  el('infoStatusFilter')?.addEventListener('change', () => loadInfoCentre().catch(console.error));

  document.querySelectorAll('.board-panel-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      setBoardTab(btn.dataset.boardTab || 'notices');
    });
  });

  document.querySelectorAll('.works-panel-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      campaignsState.tab = btn.dataset.worksTab || 'works';
      syncWorksPanelTabs();
      if (campaignsState.tab === 'campaigns') {
        showCampaignList();
        loadCampaigns().catch(console.error);
      } else {
        loadWorks().catch(console.error);
      }
    });
  });
  el('worksRefreshBtn')?.addEventListener('click', () => loadWorks().catch(console.error));
  el('worksKindFilter')?.addEventListener('change', () => loadWorks().catch(console.error));
  el('worksStatusFilter')?.addEventListener('change', () => loadWorks().catch(console.error));
  el('worksVisibilityFilter')?.addEventListener('change', () => loadWorks().catch(console.error));
  el('worksKindInput')?.addEventListener('change', () => fillWorksMetaSelects(worksState.meta || {}));
  el('worksAddFundingBtn')?.addEventListener('click', () => {
    el('worksFundingList')?.appendChild(fillWorksFundingRow());
  });
  el('worksAddMilestoneBtn')?.addEventListener('click', () => {
    el('worksMilestonesList')?.appendChild(fillWorksMilestoneRow());
  });
  el('worksFundingList')?.addEventListener('click', (event) => {
    if (event.target.closest('.wf-remove')) event.target.closest('.works-funding-row')?.remove();
  });
  el('worksMilestonesList')?.addEventListener('click', (event) => {
    if (event.target.closest('.wm-remove')) event.target.closest('.works-milestone-row')?.remove();
  });
  el('worksForm')?.addEventListener('submit', saveWorksForm);
  el('worksCancelEditBtn')?.addEventListener('click', resetWorksForm);
  el('worksCloseBtn')?.addEventListener('click', async () => {
    if (!worksState.editingId) return;
    try {
      await api(`/api/rwa/works/${encodeURIComponent(worksState.editingId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'closed' }),
      });
      resetWorksForm();
      await loadWorks();
    } catch (e) {
      if (el('worksFormStatus')) el('worksFormStatus').textContent = e.message || 'Close failed';
    }
  });
  el('worksList')?.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-work-toggle]');
    const edit = event.target.closest('[data-work-edit]');
    const invite = event.target.closest('[data-work-invite-quotes]');
    if (toggle) {
      const id = toggle.getAttribute('data-work-toggle');
      worksState.expandedId = worksState.expandedId === id ? null : id;
      renderWorksList();
      if (worksState.expandedId && hasEntitlement('manage_works')) {
        loadWorkQuotes(worksState.expandedId).catch(console.error);
      }
      return;
    }
    if (invite) {
      openWorksQuoteInvite(invite.getAttribute('data-work-invite-quotes'));
      return;
    }
    if (edit) {
      const work = worksState.items.find((w) => w.id === edit.getAttribute('data-work-edit'));
      if (work) fillWorksForm(work);
    }
  });

  el('worksQuoteInviteForm')?.addEventListener('submit', submitWorksQuoteInvite);
  el('worksQuoteInviteCloseBtn')?.addEventListener('click', () => el('worksQuoteInviteDialog')?.close());
  el('worksQuoteInviteCancelBtn')?.addEventListener('click', () => el('worksQuoteInviteDialog')?.close());

  el('campaignsRefreshBtn')?.addEventListener('click', () => loadCampaigns().catch(console.error));
  el('campaignsKindFilter')?.addEventListener('change', () => loadCampaigns().catch(console.error));
  el('campaignsStatusFilter')?.addEventListener('change', () => loadCampaigns().catch(console.error));
  el('campaignsAudienceFilter')?.addEventListener('change', () => loadCampaigns().catch(console.error));
  el('campaignsForm')?.addEventListener('submit', saveCampaignsForm);
  el('campaignsCancelEditBtn')?.addEventListener('click', resetCampaignsForm);
  el('campaignsList')?.addEventListener('click', (event) => {
    const card = event.target.closest('[data-campaign-id]');
    if (!card) return;
    openCampaignDetail(card.getAttribute('data-campaign-id')).catch((e) => {
      if (el('campaignsListStatus')) el('campaignsListStatus').textContent = e.message || 'Open failed';
    });
  });
  el('campaignsList')?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const card = event.target.closest('[data-campaign-id]');
    if (!card) return;
    event.preventDefault();
    openCampaignDetail(card.getAttribute('data-campaign-id')).catch(console.error);
  });
  el('campaignBackBtn')?.addEventListener('click', showCampaignList);
  el('campaignPledgeBtn')?.addEventListener('click', openCampaignPledgeDialog);
  el('campaignContributeBtn')?.addEventListener('click', openCampaignContributeDialog);
  el('campaignSuggestBtn')?.addEventListener('click', openCampaignSuggestDialog);
  el('campaignShareBtn')?.addEventListener('click', async () => {
    const c = campaignsState.selected;
    if (!c) return;
    const origin = await publicSiteOrigin();
    const url = `${origin}/campaign.html?id=${encodeURIComponent(c.id)}`;
    if (navigator.share) {
      navigator.share({ title: c.title, url }).catch(() => {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        el('campaignShareBtn').textContent = 'Copied!';
        setTimeout(() => { el('campaignShareBtn').textContent = 'Share link'; }, 2000);
      });
    }
  });
  el('campaignsModeInput')?.addEventListener('change', syncCampaignFormMode);
  el('campaignsPledgeAmountTypeInput')?.addEventListener('change', syncCampaignFormMode);
  el('campaignPledgeForm')?.addEventListener('submit', submitCampaignPledge);
  el('campaignPledgeCloseBtn')?.addEventListener('click', () => el('campaignPledgeDialog')?.close());
  el('campaignPledgeCancelBtn')?.addEventListener('click', () => el('campaignPledgeDialog')?.close());
  el('campaignSuggestForm')?.addEventListener('submit', submitCampaignSuggestion);
  el('campaignSuggestCloseBtn')?.addEventListener('click', () => el('campaignSuggestDialog')?.close());
  el('campaignSuggestCancelBtn')?.addEventListener('click', () => el('campaignSuggestDialog')?.close());
  el('campaignSuggestionsList')?.addEventListener('click', (event) => {
    const delBtn = event.target.closest('[data-cmp-del-suggest]');
    if (delBtn) {
      removeCampaignSuggestion(delBtn.getAttribute('data-cmp-del-suggest')).catch((e) => {
        window.alert(e.message || 'Remove failed');
      });
    }
  });
  el('campaignEditBtn')?.addEventListener('click', () => {
    if (campaignsState.selected) fillCampaignsForm(campaignsState.selected);
  });
  el('campaignDeleteBtn')?.addEventListener('click', async () => {
    const c = campaignsState.selected;
    if (!c || !hasEntitlement('manage_works')) return;
    if (!window.confirm(`Delete funding drive “${c.title}”? This cannot be undone.`)) return;
    try {
      await api(`/api/rwa/campaigns/${encodeURIComponent(c.id)}`, { method: 'DELETE' });
      showCampaignList();
      await loadCampaigns();
    } catch (e) {
      window.alert(e.message || 'Delete failed');
    }
  });
  el('campaignPledgesList')?.addEventListener('click', (event) => {
    const delBtn = event.target.closest('[data-cmp-del-pledge]');
    if (delBtn) {
      removeCampaignPledge(delBtn.getAttribute('data-cmp-del-pledge')).catch((e) => {
        window.alert(e.message || 'Remove failed');
      });
    }
  });
  el('campaignContributionsList')?.addEventListener('click', (event) => {
    const verify = event.target.closest('[data-cmp-verify]');
    const reject = event.target.closest('[data-cmp-reject]');
    const delBtn = event.target.closest('[data-cmp-del-contrib]');
    if (verify) {
      reviewCampaignContribution(verify.getAttribute('data-cmp-verify'), 'verify').catch((e) => {
        window.alert(e.message || 'Verify failed');
      });
      return;
    }
    if (reject) {
      reviewCampaignContribution(reject.getAttribute('data-cmp-reject'), 'reject').catch((e) => {
        window.alert(e.message || 'Reject failed');
      });
      return;
    }
    if (delBtn) {
      removeCampaignContribution(delBtn.getAttribute('data-cmp-del-contrib')).catch((e) => {
        window.alert(e.message || 'Remove failed');
      });
    }
  });
  el('campaignContributeForm')?.addEventListener('submit', submitCampaignContribution);
  el('campaignContributeCloseBtn')?.addEventListener('click', () => el('campaignContributeDialog')?.close());
  el('campaignContributeCancelBtn')?.addEventListener('click', () => el('campaignContributeDialog')?.close());

  document.querySelectorAll('.proceedings-register-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      proceedingsState.type = btn.dataset.proceedingsType || 'gh';
      syncProceedingsRegisterTabs();
      loadProceedings().catch(console.error);
    });
  });
  el('proceedingsRefreshBtn')?.addEventListener('click', () => loadProceedings().catch(console.error));
  el('proceedingsYearFilter')?.addEventListener('change', () => loadProceedings().catch(console.error));
  el('proceedingsStatusFilter')?.addEventListener('change', () => loadProceedings().catch(console.error));
  el('proceedingsSearchInput')?.addEventListener('input', () => {
    clearTimeout(proceedingsState.searchTimer);
    proceedingsState.searchTimer = setTimeout(() => loadProceedings().catch(console.error), 320);
  });
  el('proceedingsList')?.addEventListener('click', (event) => {
    const row = event.target.closest('[data-proceedings-id]');
    if (!row) return;
    openProceedingsDetail(row.getAttribute('data-proceedings-id')).catch((e) => {
      if (el('proceedingsListStatus')) el('proceedingsListStatus').textContent = e.message || 'Open failed';
    });
  });
  el('proceedingsBackBtn')?.addEventListener('click', () => {
    proceedingsState.selected = null;
    showProceedingsDetail(false);
  });
  el('proceedingsEditBtn')?.addEventListener('click', () => {
    if (proceedingsState.selected) fillProceedingsForm(proceedingsState.selected);
  });
  el('proceedingsPrintBtn')?.addEventListener('click', printProceedingsDetail);
  try {
    const savedPaper = localStorage.getItem('mhws-mom-paper');
    if (savedPaper && el('proceedingsPaperSize')?.querySelector(`option[value="${savedPaper}"]`)) {
      el('proceedingsPaperSize').value = savedPaper;
    }
  } catch (_) {}
  el('proceedingsPaperSize')?.addEventListener('change', () => {
    try { localStorage.setItem('mhws-mom-paper', el('proceedingsPaperSize').value); } catch (_) {}
  });
  el('proceedingsForm')?.addEventListener('submit', saveProceedingsForm);
  el('proceedingsTypeInput')?.addEventListener('change', () => {
    fillProceedingsSubtypeSelect(el('proceedingsTypeInput').value);
    syncProceedingsQuorumField();
  });
  el('proceedingsAddResolutionBtn')?.addEventListener('click', () => addProceedingsResolutionRow());
  el('proceedingsAddActionBtn')?.addEventListener('click', () => addProceedingsActionRow());
  el('proceedingsResolutionsList')?.addEventListener('click', (event) => {
    if (event.target.closest('.pr-remove')) event.target.closest('.proceedings-row')?.remove();
  });
  el('proceedingsActionsList')?.addEventListener('click', (event) => {
    if (event.target.closest('.pa-remove')) event.target.closest('.proceedings-row')?.remove();
  });
  el('proceedingsCancelEditBtn')?.addEventListener('click', resetProceedingsForm);
  el('proceedingsVoteBar')?.addEventListener('click', (event) => {
    const send = event.target.closest('[data-vote-send]');
    const closeBtn = event.target.closest('[data-vote-close]');
    const withdraw = event.target.closest('[data-vote-withdraw]');
    const tally = event.target.closest('[data-vote-tally]');
    if (send) {
      const rid = send.getAttribute('data-vote-send');
      const rno = send.getAttribute('data-vote-no');
      const resolution = (proceedingsState.selected?.resolutions || []).find((r) => r.id === rid || r.no === rno);
      openProceedingsVoteDialog(resolution || { id: rid, no: rno, text: '' }).catch((e) => window.alert(e.message || 'Could not open'));
      return;
    }
    if (closeBtn) {
      closeProceedingsVote(closeBtn.getAttribute('data-vote-close'), false).catch((e) => window.alert(e.message || 'Close failed'));
      return;
    }
    if (withdraw) {
      closeProceedingsVote(withdraw.getAttribute('data-vote-withdraw'), true).catch((e) => window.alert(e.message || 'Withdraw failed'));
      return;
    }
    if (tally) {
      showProceedingsVoteTally(tally.getAttribute('data-vote-tally')).catch((e) => window.alert(e.message || 'Tally failed'));
    }
  });
  el('proceedingsVoteAudience')?.addEventListener('change', () => previewProceedingsVoteAudience().catch(console.error));
  el('proceedingsVoteForm')?.addEventListener('submit', submitProceedingsVoteForm);
  el('proceedingsVoteCloseBtn')?.addEventListener('click', () => el('proceedingsVoteDialog')?.close());
  el('proceedingsVoteCancelBtn')?.addEventListener('click', () => el('proceedingsVoteDialog')?.close());
  el('notifyBellBtn')?.addEventListener('click', () => {
    if (el('notifyDialog')?.open) {
      closeNotificationsDialog();
      return;
    }
    openNotificationsDialog().catch((e) => window.alert(e.message || 'Could not open notifications'));
  });
  el('notifyDialogCloseBtn')?.addEventListener('click', () => closeNotificationsDialog());
  el('notifyDialog')?.addEventListener('close', () => {
    const btn = el('notifyBellBtn');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  });
  el('notifyDialogBody')?.addEventListener('click', (event) => {
    const alertCard = event.target.closest('[data-notify-url], [data-notify-hash]');
    if (alertCard && !event.target.closest('[data-cast]')) {
      openNotifyAlert(alertCard);
      return;
    }
    const btn = event.target.closest('[data-cast]');
    if (!btn) return;
    const card = btn.closest('.resolution-vote-card');
    if (!card) return;
    btn.disabled = true;
    castMyResolutionVote(card, btn.getAttribute('data-cast')).catch((e) => {
      window.alert(e.message || 'Could not record vote');
      btn.disabled = false;
    });
  });

  el('infoDocForm')?.addEventListener('submit', saveInfoDocument);
  bindComposeUi();
  el('templatesRefreshBtn')?.addEventListener('click', () => loadTemplates().catch(console.error));
  el('templatesNewBtn')?.addEventListener('click', (event) => {
    event.preventDefault();
    openTemplatesNewPicker(el('templatesNewBtn'));
  });
  el('templatesUploadBtn')?.addEventListener('click', () => startUploadTemplate());
  el('templatesCompose')?.addEventListener('toggle', () => {
    if (!el('templatesCompose')?.open) return;
    if (el('templatesEditor')) el('templatesEditor').open = false;
    if (el('templatesStationery')) el('templatesStationery').open = false;
    mountComposeEditor().catch((e) => {
      if (el('tplComposeStatus')) {
        el('tplComposeStatus').textContent = e.message || 'Composer failed to load — hard refresh the page.';
      }
    });
  });
  el('templatesStationery')?.addEventListener('toggle', () => {
    if (!el('templatesStationery')?.open) return;
    if (el('templatesCompose')) el('templatesCompose').open = false;
    if (el('templatesEditor')) el('templatesEditor').open = false;
    ensureStationeryForm().then(() => paintStationeryDesk()).catch(() => {});
  });
  el('templatesEditor')?.addEventListener('toggle', () => {
    if (el('templatesEditor')?.open) {
      if (el('templatesCompose')) el('templatesCompose').open = false;
      if (el('templatesStationery')) el('templatesStationery').open = false;
    }
  });
  el('templatesCategoryFilter')?.addEventListener('change', () => loadTemplates().catch(console.error));
  el('templatesStatusFilter')?.addEventListener('change', () => loadTemplates().catch(console.error));
  el('templatesForm')?.addEventListener('submit', saveTemplate);
  el('templatesResetBtn')?.addEventListener('click', () => resetTemplatesForm());
  el('templatesPaperSizeInput')?.addEventListener('change', syncTemplatesCustomSizeFields);
  el('templateMailForm')?.addEventListener('submit', (event) => {
    submitTemplateMail(event).catch((e) => {
      if (el('templateMailStatus')) el('templateMailStatus').textContent = e.message || 'Mail failed';
    });
  });
  el('templateMailCloseBtn')?.addEventListener('click', () => closeTemplateMailDialog());
  el('templateMailCancelBtn')?.addEventListener('click', () => closeTemplateMailDialog());
  el('templateMailDialog')?.addEventListener('click', (event) => {
    if (event.target === el('templateMailDialog')) closeTemplateMailDialog();
  });
  el('templatesList')?.addEventListener('click', (event) => {
    const openBtn = event.target.closest('[data-tpl-open]');
    const downloadBtn = event.target.closest('[data-tpl-download]');
    const printBtn = event.target.closest('[data-tpl-print]');
    const mailBtn = event.target.closest('[data-tpl-mail]');
    const mailCatBtn = event.target.closest('[data-tpl-mail-category]');
    const editBtn = event.target.closest('[data-tpl-edit]');
    const composeEditBtn = event.target.closest('[data-tpl-compose-edit]');
    const stationeryEditBtn = event.target.closest('[data-tpl-stationery-edit]');
    const delBtn = event.target.closest('[data-tpl-delete]');
    if (openBtn) {
      openTemplate(openBtn.getAttribute('data-tpl-open')).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Open failed';
      });
      return;
    }
    if (downloadBtn) {
      downloadTemplate(downloadBtn.getAttribute('data-tpl-download')).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Download failed';
        else window.alert(e.message || 'Download failed');
      });
      return;
    }
    if (printBtn) {
      openTemplate(printBtn.getAttribute('data-tpl-print'), { printAfter: true }).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Print failed';
        else window.alert(e.message || 'Print failed');
      });
      return;
    }
    if (mailBtn) {
      openTemplateMailDialog({ templateId: mailBtn.getAttribute('data-tpl-mail') });
      return;
    }
    if (mailCatBtn) {
      openTemplateMailDialog({ category: mailCatBtn.getAttribute('data-tpl-mail-category') });
      return;
    }
    if (composeEditBtn) {
      beginEditComposedTemplate(composeEditBtn.getAttribute('data-tpl-compose-edit')).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Open composer failed';
        else window.alert(e.message || 'Open composer failed');
      });
      return;
    }
    if (stationeryEditBtn) {
      beginEditStationeryTemplate(stationeryEditBtn.getAttribute('data-tpl-stationery-edit')).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Open template designer failed';
        else window.alert(e.message || 'Open template designer failed');
      });
      return;
    }
    if (editBtn) {
      beginEditTemplate(editBtn.getAttribute('data-tpl-edit'));
      return;
    }
    if (delBtn) {
      deleteTemplate(delBtn.getAttribute('data-tpl-delete')).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Delete failed';
      });
    }
  });
  el('infoCancelEditBtn')?.addEventListener('click', () => resetInfoForm());
  el('infoFolderCreateBtn')?.addEventListener('click', () => createInfoFolder().catch(console.error));
  el('infoFolderNewTitle')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      createInfoFolder().catch(console.error);
    }
  });
  el('infoAudienceInput')?.addEventListener('change', () => {
    syncInfoDocAccessPicker();
    if ((el('infoAudienceInput')?.value || '') === 'restricted') {
      const selected = selectedInfoAccessIds(el('infoDocAccessList'));
      renderInfoAccessList(el('infoDocAccessList'), {
        selectedIds: selected,
        search: el('infoDocAccessSearch')?.value || '',
      }).catch(() => {});
    }
  });
  el('infoDocAccessSearch')?.addEventListener('input', () => {
    renderInfoAccessList(el('infoDocAccessList'), {
      selectedIds: selectedInfoAccessIds(el('infoDocAccessList')),
      search: el('infoDocAccessSearch')?.value || '',
    }).catch(() => {});
  });
  el('infoFolderNewAudience')?.addEventListener('change', () => {
    syncInfoFolderNewAccessPicker();
    if ((el('infoFolderNewAudience')?.value || '') === 'restricted') {
      renderInfoAccessList(el('infoFolderNewAccessList'), {
        selectedIds: selectedInfoAccessIds(el('infoFolderNewAccessList')),
        search: el('infoFolderNewAccessSearch')?.value || '',
      }).catch(() => {});
    }
  });
  el('infoFolderNewAccessSearch')?.addEventListener('input', () => {
    renderInfoAccessList(el('infoFolderNewAccessList'), {
      selectedIds: selectedInfoAccessIds(el('infoFolderNewAccessList')),
      search: el('infoFolderNewAccessSearch')?.value || '',
    }).catch(() => {});
  });
  el('infoFolderEditAudience')?.addEventListener('change', () => {
    const audience = el('infoFolderEditAudience')?.value || 'all';
    setInfoAccessPickerVisibility(el('infoFolderEditAccessPicker'), audience);
    if (audience === 'restricted') {
      renderInfoAccessList(el('infoFolderEditAccessList'), {
        selectedIds: selectedInfoAccessIds(el('infoFolderEditAccessList')),
        search: el('infoFolderEditAccessSearch')?.value || '',
      }).catch(() => {});
    }
  });
  el('infoFolderEditAccessSearch')?.addEventListener('input', () => {
    renderInfoAccessList(el('infoFolderEditAccessList'), {
      selectedIds: selectedInfoAccessIds(el('infoFolderEditAccessList')),
      search: el('infoFolderEditAccessSearch')?.value || '',
    }).catch(() => {});
  });
  el('infoFolderEditAccessSave')?.addEventListener('click', () => {
    saveInfoFolderAccessEdit().catch(console.error);
  });
  el('infoFolderEditAccessCancel')?.addEventListener('click', () => {
    infoFolderAccessEditId = '';
    if (el('infoFolderEditAccess')) el('infoFolderEditAccess').hidden = true;
  });
  el('infoFolderManageList')?.addEventListener('click', (event) => {
    const shareBtn = event.target.closest('.info-folder-share');
    const accessBtn = event.target.closest('.info-folder-access');
    const addChildBtn = event.target.closest('.info-folder-add-child');
    const moveBtn = event.target.closest('.info-folder-move');
    const renameBtn = event.target.closest('.info-folder-rename');
    const deleteBtn = event.target.closest('.info-folder-delete');
    if (shareBtn) {
      const id = shareBtn.getAttribute('data-id');
      const folder = infoFoldersCache.find((f) => f.id === id);
      copyInfoShareLink({ folderId: id, label: `Folder link for “${folder?.title || 'folder'}”` }).catch(console.error);
      return;
    }
    if (accessBtn) {
      editInfoFolderAccess(accessBtn.getAttribute('data-id')).catch(console.error);
      return;
    }
    if (addChildBtn) {
      const parentId = addChildBtn.getAttribute('data-id') || '';
      const parent = infoFoldersCache.find((f) => f.id === parentId);
      const title = prompt(`New subfolder inside “${parent?.title || 'folder'}”`, '');
      if (title == null) return;
      createInfoFolder({ parentId, title }).catch(console.error);
      return;
    }
    if (moveBtn) {
      moveInfoFolder(moveBtn.getAttribute('data-id')).catch(console.error);
      return;
    }
    if (renameBtn) {
      renameInfoFolder(renameBtn.getAttribute('data-id')).catch(console.error);
      return;
    }
    if (deleteBtn) {
      deleteInfoFolder(deleteBtn.getAttribute('data-id')).catch(console.error);
    }
  });
  // Folder share buttons also appear in the browse list headers.
  el('infoDocList')?.addEventListener('dblclick', (event) => {
    if (event.target.closest('button, a, input, select, textarea')) return;
    const card = event.target.closest('.info-doc-card');
    if (!card) return;
    event.preventDefault();
    const more = card.querySelector('.info-doc-actions-more');
    if (!more) return;
    const open = more.hasAttribute('hidden');
    // Close others so only one card shows extra actions.
    el('infoDocList')?.querySelectorAll('.info-doc-card.is-actions-open').forEach((other) => {
      if (other === card) return;
      other.classList.remove('is-actions-open');
      other.querySelector('.info-doc-actions-more')?.setAttribute('hidden', '');
    });
    if (open) {
      more.removeAttribute('hidden');
      card.classList.add('is-actions-open');
    } else {
      more.setAttribute('hidden', '');
      card.classList.remove('is-actions-open');
    }
  });
  el('infoDocList')?.addEventListener('click', async (event) => {
    const infoBtn = event.target.closest('.info-doc-info-btn');
    if (infoBtn) {
      const card = infoBtn.closest('.info-doc-card');
      const details = card?.querySelector('.info-doc-card-details');
      if (!details) return;
      const open = details.hasAttribute('hidden');
      el('infoDocList')?.querySelectorAll('.info-doc-card.is-details-open').forEach((other) => {
        if (other === card) return;
        other.classList.remove('is-details-open');
        other.querySelector('.info-doc-card-details')?.setAttribute('hidden', '');
        const otherBtn = other.querySelector('.info-doc-info-btn');
        if (otherBtn) {
          otherBtn.setAttribute('aria-expanded', 'false');
          otherBtn.setAttribute('aria-label', 'Show document details');
        }
      });
      if (open) {
        details.removeAttribute('hidden');
        card.classList.add('is-details-open');
        infoBtn.setAttribute('aria-expanded', 'true');
        infoBtn.setAttribute('aria-label', 'Hide document details');
      } else {
        details.setAttribute('hidden', '');
        card.classList.remove('is-details-open');
        infoBtn.setAttribute('aria-expanded', 'false');
        infoBtn.setAttribute('aria-label', 'Show document details');
      }
      return;
    }
    const folderShare = event.target.closest('.info-folder-share');
    if (folderShare) {
      const id = folderShare.getAttribute('data-id');
      const folder = infoFoldersCache.find((f) => f.id === id);
      await copyInfoShareLink({ folderId: id, label: `Folder link for “${folder?.title || 'folder'}”` });
      return;
    }
    const openBtn = event.target.closest('.info-doc-open');
    const shareBtn = event.target.closest('.info-doc-share');
    const editBtn = event.target.closest('.info-doc-edit');
    const moveBtn = event.target.closest('.info-doc-move');
    const pubBtn = event.target.closest('.info-doc-publish');
    const unpubBtn = event.target.closest('.info-doc-unpublish');
    const delBtn = event.target.closest('.info-doc-delete');
    const id = (openBtn || shareBtn || editBtn || moveBtn || pubBtn || unpubBtn || delBtn)?.getAttribute('data-id');
    const doc = infoDocsCache.find((d) => d.id === id);
    if (!id) return;

    if (shareBtn) {
      await copyInfoShareLink({ docId: id, label: `Document link for “${doc?.title || 'document'}”` });
      return;
    }
    if (!doc && !folderShare) return;

    if (openBtn) {
      openBtn.disabled = true;
      try {
        await openInfoDocument(doc);
      } catch (err) {
        alert(err.message || 'Could not open document');
      } finally {
        openBtn.disabled = false;
      }
      return;
    }
    if (!hasEntitlement('manage_info')) return;
    if (editBtn) {
      startInfoEdit(doc);
      return;
    }
    if (moveBtn) {
      await moveInfoDocument(id);
      return;
    }
    if (pubBtn || unpubBtn) {
      const next = pubBtn ? 'published' : 'draft';
      const btn = pubBtn || unpubBtn;
      if (pubBtn) {
        const audience = pubBtn.getAttribute('data-audience') || doc.audience || 'all';
        if (!confirmInfoPublish(doc.title || id, audience)) return;
      } else if (!window.confirm(`Unpublish “${doc.title}”? It will become a draft.`)) {
        return;
      }
      btn.disabled = true;
      try {
        const body = { status: next };
        if (pubBtn) body.audience = pubBtn.getAttribute('data-audience') || doc.audience || 'all';
        await api(`/api/rwa/info-centre/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        });
        await loadInfoCentre({ skipDeepLink: true });
      } catch (err) {
        alert(err.message || 'Update failed');
        btn.disabled = false;
      }
      return;
    }
    if (delBtn) {
      if (!window.confirm(`Delete “${doc.title}”? This cannot be undone.`)) return;
      delBtn.disabled = true;
      try {
        await api(`/api/rwa/info-centre/${encodeURIComponent(id)}`, { method: 'DELETE', body: '{}' });
        await loadInfoCentre({ skipDeepLink: true });
      } catch (err) {
        alert(err.message || 'Delete failed');
        delBtn.disabled = false;
      }
    }
  });

  // Placeholder removed — handlers bound above.
  document.querySelectorAll('input[name="infoSource"]').forEach((input) => {
    input.addEventListener('change', syncInfoSourcePanes);
  });

  el('ecGrievanceRefreshBtn')?.addEventListener('click', () => loadEcGrievances().catch(console.error));
  el('ecGrievanceStatusFilter')?.addEventListener('change', () => loadEcGrievances().catch(console.error));
  el('ecGrievanceCategoryFilter')?.addEventListener('change', () => loadEcGrievances().catch(console.error));

  let reportMeta = { reports: [], datasets: {} };
  let reportFieldDefs = [];

  function currentReportDef() {
    const id = el('reportTypeSelect')?.value || 'pending-dues';
    return (reportMeta.reports || []).find((r) => r.id === id) || null;
  }

  function renderReportFields(defs, selectedIds) {
    const box = el('reportFields');
    if (!box) return;
    reportFieldDefs = defs || [];
    const defaults = reportFieldDefs.filter((f) => f.default).map((f) => f.id);
    const selected = new Set(selectedIds || defaults);
    box.innerHTML = reportFieldDefs.map((f) => {
      const checked = selected.has(f.id) || f.id === 'sno';
      const disabled = f.id === 'sno' ? ' disabled' : '';
      return `<label class="check"><input type="checkbox" name="field" value="${escapeHtml(f.id)}"${checked ? ' checked' : ''}${disabled}> <span>${escapeHtml(f.label)}</span></label>`;
    }).join('');
  }

  function selectedReportFieldIds() {
    return Array.from(document.querySelectorAll('#reportFields input[name="field"]:checked')).map((i) => i.value);
  }

  function reportCustomColumnLabels() {
    return [el('reportCustomCol1'), el('reportCustomCol2')]
      .map((input) => (input?.value || '').trim())
      .filter(Boolean)
      .slice(0, 2);
  }

  function setReportCustomColumnLabels(raw) {
    const list = Array.isArray(raw) ? raw : [];
    const labels = list.map((item) => (typeof item === 'string' ? item : item?.label || '').trim()).filter(Boolean);
    if (el('reportCustomCol1')) el('reportCustomCol1').value = labels[0] || '';
    if (el('reportCustomCol2')) el('reportCustomCol2').value = labels[1] || '';
  }

  function reportStyleOptions() {
    const fontSize = Number.parseInt(el('reportFontSize')?.value || '12', 10);
    let color = (el('reportColor')?.value || 'black').trim().toLowerCase();
    if (color === 'dark' || color === 'warm') color = color === 'warm' ? 'brown' : 'black';
    const contrast = (el('reportContrast')?.value || 'hard').trim().toLowerCase();
    const allowed = ['black', 'navy', 'brown', 'blue', 'green', 'maroon'];
    return {
      fontSize: Number.isFinite(fontSize) ? fontSize : 12,
      color: allowed.includes(color) ? color : 'black',
      contrast: contrast === 'normal' ? 'normal' : 'hard',
    };
  }

  function setReportStyleOptions(raw) {
    const style = raw && typeof raw === 'object' ? raw : {};
    const fontSize = String(style.fontSize ?? style.font_size ?? 12);
    let color = String(style.color || 'black').toLowerCase();
    if (color === 'dark') color = 'black';
    if (color === 'warm') color = 'brown';
    const contrast = String(style.contrast || 'hard').toLowerCase();
    const allowed = ['black', 'navy', 'brown', 'blue', 'green', 'maroon'];
    if (el('reportFontSize')) {
      const opt = Array.from(el('reportFontSize').options).find((o) => o.value === fontSize);
      el('reportFontSize').value = opt ? fontSize : '12';
    }
    if (el('reportColor')) el('reportColor').value = allowed.includes(color) ? color : 'black';
    if (el('reportContrast')) el('reportContrast').value = contrast === 'normal' ? 'normal' : 'hard';
  }

  function syncReportUi() {
    const def = currentReportDef();
    const isCustom = def?.kind === 'custom' || def?.id === 'custom';
    const isTemplate = def?.kind === 'template';
    if (el('reportCustomControls')) el('reportCustomControls').hidden = !(isCustom || isTemplate);
    if (el('reportSaveTemplateBtn')) el('reportSaveTemplateBtn').hidden = !(isCustom || isTemplate);
    if (el('reportDeleteTemplateBtn')) el('reportDeleteTemplateBtn').hidden = !isTemplate;
    let dataset = 'dues';
    let fields = null;
    let filters = {};
    if (isCustom) {
      dataset = el('reportDatasetSelect')?.value || 'dues';
      const ds = reportMeta.datasets?.[dataset];
      fields = ds?.fields || [];
      filters = ds?.defaultFilters || {};
    } else if (isTemplate) {
      dataset = def.dataset || 'dues';
      if (el('reportDatasetSelect')) el('reportDatasetSelect').value = dataset;
      const ds = reportMeta.datasets?.[dataset];
      const catalog = ds?.fields || [];
      const selected = def.fields || [];
      fields = catalog.length ? catalog : selected.map((id) => ({ id, label: id, default: true }));
      filters = def.defaultFilters || {};
      renderReportFields(fields, Array.isArray(selected) && selected.length && typeof selected[0] === 'string' ? selected : selected.map((f) => f.id || f));
    } else {
      dataset = def?.dataset || 'dues';
      fields = def?.fields || reportMeta.datasets?.dues?.fields || [];
      filters = def?.defaultFilters || {};
      renderReportFields(fields, (fields || []).filter((f) => f.default).map((f) => f.id));
    }
    if (isCustom) {
      const ds = reportMeta.datasets?.[dataset];
      renderReportFields(ds?.fields || [], (ds?.fields || []).filter((f) => f.default).map((f) => f.id));
      filters = ds?.defaultFilters || {};
    }
    if (el('reportSection') && filters.section) el('reportSection').value = filters.section;
    if (el('reportSearch') && filters.search != null) el('reportSearch').value = filters.search || '';
    if (el('reportPendingOnly')) el('reportPendingOnly').checked = filters.pendingOnly !== false;
    if (el('reportPlots') && Array.isArray(filters.houseIds)) el('reportPlots').value = filters.houseIds.join(', ');
    if (el('reportConcernStatus') && filters.status && dataset === 'concerns') el('reportConcernStatus').value = filters.status;
    if (el('reportPassKind') && filters.kind) el('reportPassKind').value = filters.kind;
    if (el('reportPassStatus') && filters.status && (dataset === 'passes' || dataset === 'vehicles')) {
      el('reportPassStatus').value = filters.status;
    }
    if (el('reportTenantStatus') && filters.status && dataset === 'tenants') {
      el('reportTenantStatus').value = filters.status;
    }
    setReportCustomColumnLabels(filters.customColumns || []);
    setReportStyleOptions(filters.style || { fontSize: 12, color: 'black', contrast: 'hard' });
    const ui = reportMeta.datasets?.[dataset]?.filterUi || {};
    const duesLike = dataset === 'dues' || ui.pendingOnly;
    const concernsLike = dataset === 'concerns' || ui.concernStatus;
    if (el('reportPendingOnlyWrap')) el('reportPendingOnlyWrap').hidden = !duesLike;
    if (el('reportPlotsWrap')) el('reportPlotsWrap').hidden = ui.plots === false;
    if (el('reportConcernStatusWrap')) el('reportConcernStatusWrap').hidden = !concernsLike;
    if (el('reportPassKindWrap')) el('reportPassKindWrap').hidden = !ui.passKind;
    if (el('reportPassStatusWrap')) el('reportPassStatusWrap').hidden = !ui.passStatus;
    if (el('reportTenantStatusWrap')) el('reportTenantStatusWrap').hidden = !ui.tenantStatus;
    if (el('reportSection')?.closest('label')) {
      const sectionLabel = el('reportSection').closest('label');
      if (sectionLabel) sectionLabel.hidden = ui.section === false;
    }
  }

  let templatesCache = [];
  let templatesCategories = [];
  let templatesStarters = [];
  let templatesChromes = [];
  let composeSession = null;
  let composeDirty = false;
  let composePreviewUrl = '';
  let stationeryDirty = false;
  let stationerySpec = null;
  let stationeryPreviewUrl = '';
  let templatesNewPop = null;
  let stationeryBound = false;
  bindStationeryUi();
  const COMPOSE_LAYOUT_KEY = 'mhws-composer-layout';
  const COMPOSE_LAYOUTS = {
    original: 'Original layout',
    panel: 'Panel mode',
    window: 'Full window',
  };
  let templatesOptionDefaults = {
    paperSize: 'A4',
    orientation: 'portrait',
    background: 'watermark',
    customWidthCm: 22,
    customHeightCm: 10,
    colors: {
      heading: '#0b2a56',
      body: '#12233f',
      muted: '#5a6a80',
      accent: '#1a6b3a',
      gold: '#c9a227',
    },
  };

  function fillComposeStarterSelect() {
    const select = el('tplStarterSelect');
    if (!select) return;
    const prev = select.value;
    const opts = ['<option value="">Choose a starter…</option>']
      .concat((templatesStarters || []).map((s) => {
        const label = s.title || s.id;
        return `<option value="${escapeHtml(s.id)}">${escapeHtml(label)}</option>`;
      }));
    select.innerHTML = opts.join('');
    if (prev && [...select.options].some((o) => o.value === prev)) select.value = prev;
  }

  function syncComposeWatermarkField() {
    const select = el('tplComposeChrome');
    const wm = el('tplComposeWatermark');
    if (!wm) return;
    const opt = select?.selectedOptions?.[0];
    const hasWm = opt?.getAttribute('data-wm') === '1';
    const wasOff = wm.disabled;
    wm.hidden = !hasWm;
    wm.disabled = !hasWm;
    if (!hasWm) wm.value = '0';
    else if (wasOff) wm.value = '1';
  }

  function composeMarginsForChrome(chromeId) {
    if (chromeId === 'none') {
      return { top: 16, right: 16, bottom: 16, left: 16 };
    }
    return { top: 0, right: 16, bottom: 0, left: 16 };
  }

  function applyComposeChromeSettings(chromeId) {
    const id = chromeId || el('tplComposeChrome')?.value || 'simple';
    composeSession?.driver?.setPageMargins?.(composeMarginsForChrome(id));
    composeSession?.setChrome?.(id);
  }

  function fillComposeChromeSelect() {
    const select = el('tplComposeChrome');
    if (!select) return;
    const prev = select.value;
    const list = templatesChromes && templatesChromes.length
      ? templatesChromes
      : [
        { id: 'simple', title: 'Simple header & footer', hasWatermark: false },
        { id: 'none', title: 'No template', hasWatermark: false },
      ];
    select.innerHTML = list.map((c) => {
      const wm = c.hasWatermark ? '1' : '0';
      return `<option value="${escapeHtml(c.id)}" data-wm="${wm}">${escapeHtml(c.title)}</option>`;
    }).join('');
    if (prev && [...select.options].some((o) => o.value === prev)) select.value = prev;
    else if ([...select.options].some((o) => o.value === 'tpl-mhws-letterhead')) select.value = 'tpl-mhws-letterhead';
    syncComposeWatermarkField();
  }

  function composeExportPayload() {
    const starter = currentComposeStarter();
    return {
      title: String(el('tplComposeTitle')?.value || '').trim() || 'Document',
      category: el('tplComposeCategory')?.value || starter?.category || 'correspondence',
      status: el('tplComposeStatus')?.value || 'published',
      tags: (starter?.tags || ['compose']).join(', '),
      htmlBody: composeSession ? composeSession.getHTML() : '',
      chrome: el('tplComposeChrome')?.value || 'simple',
      watermark: el('tplComposeWatermark')?.value !== '0',
    };
  }

  async function mountComposeEditor() {
    const C = await whenComposerReady();
    if (!C) {
      if (el('tplComposeStatus')) {
        el('tplComposeStatus').textContent = 'Composer failed to load — hard refresh the page.';
      }
      return null;
    }
    const shell = el('tplComposeShell');
    const host = el('tplComposeEditor');
    const toolbar = el('tplComposeToolbar');
    if (!host || !toolbar) {
      if (el('tplComposeStatus')) el('tplComposeStatus').textContent = 'Composer markup is missing.';
      return null;
    }
    if (shell && !shell.dataset.layoutBound) {
      C.attachLayout(shell, { storageKey: 'mhws-composer-layout-templates' });
    }
    if (!composeSession) {
      composeSession = C.mount({
        host,
        toolbar,
        imageInput: el('tplComposeImageInput'),
        paper: 'A4',
        getChromeId: () => el('tplComposeChrome')?.value || 'simple',
        getChromeParts: () => {
          const id = el('tplComposeChrome')?.value || 'simple';
          return (templatesChromes || []).find((c) => c.id === id) || { id };
        },
        getWatermark: () => {
          const opt = el('tplComposeChrome')?.selectedOptions?.[0];
          return opt?.getAttribute('data-wm') === '1' && el('tplComposeWatermark')?.value !== '0';
        },
        onDirty: () => { composeDirty = true; },
      });
    }
    applyComposeChromeSettings(el('tplComposeChrome')?.value || 'simple');
    return composeSession;
  }

  function currentComposeStarter() {
    const id = el('tplStarterSelect')?.value || '';
    return (templatesStarters || []).find((s) => s.id === id) || null;
  }

  function applyComposeStarter(starter, { force } = {}) {
    if (!starter || !composeSession) return;
    if (composeDirty && !force && !window.confirm('Replace the current draft with this starter?')) {
      return;
    }
    composeSession.applyStarter(starter);
    if (el('tplComposeTitle') && (!el('tplComposeTitle').value || force)) {
      el('tplComposeTitle').value = starter.suggestedTitle || starter.title || '';
    }
    if (el('tplComposeCategory') && starter.category) {
      el('tplComposeCategory').value = starter.category;
    }
    if (el('tplStarterHint') && starter.description) {
      el('tplStarterHint').textContent = starter.description;
    }
    composeDirty = false;
  }

  function parseComposeMargins(html) {
    const match = String(html || '').match(/<!--\s*mhws-margins:([\d.]+),([\d.]+),([\d.]+),([\d.]+)\s*-->/i);
    const num = (i, fallback) => {
      const value = Number.parseFloat(match && match[i]);
      return Number.isFinite(value) && value >= 0 && value <= 50 ? value : fallback;
    };
    return { top: num(1, 16), right: num(2, 16), bottom: num(3, 16), left: num(4, 16) };
  }

  function wrapComposePreviewHtml(title, bodyHtml) {
    const heading = escapeHtml((title || 'Document').trim() || 'Document');
    const chrome = el('tplComposeChrome')?.value || 'simple';
    const margins = chrome === 'none'
      ? parseComposeMargins(bodyHtml)
      : composeMarginsForChrome(chrome);
    const pad = `${margins.top}mm ${margins.right}mm ${margins.bottom}mm ${margins.left}mm`;
    const none = chrome === 'none';
    const head = none ? '' : `<div class="mhws-run-header">
<header class="org">
<img src="/assets/mhws-logo/mhws-logo-seal-cert.png?v=20260822logo1" alt="">
<h1>Mandi Housing Welfare Society</h1>
<p class="sub">Himuda Housing Colony Sanyard</p>
<p class="meta">Housing Colony Sanyard, Mandi HP 175001 · Registration No. 467 dated 21/07/2012<br>
housingcolonysanyard@gmail.com · housingcolonysanyard.in</p>
</header>
<div class="rule" aria-hidden="true"><span class="pip"></span></div>
</div>`;
    const foot = none ? '' : `<div class="mhws-run-footer">
<footer class="foot">Unity · Harmony · Progress · Mandi Housing Welfare Society</footer>
</div>`;
    return `<!DOCTYPE html>
<html lang="en" class="mhws-compose-multipage"><head><meta charset="UTF-8"><title>${heading}</title>
<style>
@page { size: 210mm 297mm; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; width: 210mm; color: #12233f; font: 11pt/1.45 Georgia, serif; background: #fff; overflow: visible; }
.org { text-align: center; padding: 10mm 12mm 4pt; }
.org img { width: 18mm; height: auto; border: 0; outline: 0; box-shadow: none; background: transparent; }
.org h1 { margin: 4pt 0 0; font-size: 15pt; letter-spacing: 0.04em; text-transform: uppercase; color: #0b2a56; }
.org .sub { margin: 2pt 0 0; font-size: 10pt; font-weight: 600; color: #1a6b3a; }
.org .meta { margin: 2pt 0 0; font-size: 8.5pt; color: #5a6a80; }
.rule { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 3mm; margin: 0 0 2.2mm; width: 100%; }
.rule::before, .rule::after { content: ""; height: 0; border-top: 1pt solid #0b2a56; }
.rule .pip { width: 2.2mm; height: 2.2mm; background: #c9a227; transform: rotate(45deg); box-shadow: 0 0 0 1.2pt #fff, 0 0 0 1.7pt rgba(11, 42, 86, 0.35); }
.body { padding: ${pad}; }
.body p { margin: 0 0 8pt; }
.body h2 { margin: 0 0 8pt; font-size: 18pt; font-weight: 700; color: #0b2a56; }
.body h3 { margin: 0 0 6pt; font-size: 14pt; font-weight: 700; color: #143a6e; }
.body h2 span, .body h3 span { font-size: inherit; font-weight: inherit; color: inherit; }
.body .mhws-tab { white-space: pre; tab-size: 4; }
.body table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
.body th, .body td { border: 0.6pt solid #0b2a56; padding: 4pt 6pt; vertical-align: top; }
.body th { background: #eef2f8; }
.body table.mhws-table-noborder th,
.body table.mhws-table-noborder td { border: 0 !important; }
.body img { max-width: 100%; height: auto; }
.foot { padding: 6pt 12mm 10mm; border-top: 0.7pt solid rgba(11,42,86,0.35); font-size: 8pt; color: #5a6a80; text-align: center; }
</style></head><body>
${head}
<div class="body">${bodyHtml || '<p></p>'}</div>
${foot}
</body></html>`;
  }

  async function previewComposeDocument() {
    if (!composeSession) return;
    const title = String(el('tplComposeTitle')?.value || '').trim() || 'Document';
    const statusLine = el('tplComposeStatus');
    let html = '';
    try {
      const { blob } = await apiBinary('/api/rwa/templates/compose/preview', {
        method: 'POST',
        body: JSON.stringify(composeExportPayload()),
      });
      html = await blob.text();
      if (statusLine) statusLine.textContent = '';
    } catch (err) {
      if (statusLine) statusLine.textContent = err.message || 'Preview failed — letterhead could not be applied.';
      return;
    }
    if (composePreviewUrl) URL.revokeObjectURL(composePreviewUrl);
    composePreviewUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    const dialog = el('docViewerDialog');
    if (dialog) document.body.appendChild(dialog);
    showDocViewerSource(composePreviewUrl, {
      title,
      filename: `${title}.html`,
      mime: 'text/html',
      isBlob: true,
    });
    if (statusLine && !html) statusLine.textContent = 'Preview failed.';
  }

  function resetComposeFields() {
    if (el('tplComposeEditId')) el('tplComposeEditId').value = '';
    if (el('tplStarterSelect')) el('tplStarterSelect').value = '';
    if (el('tplComposeTitle')) el('tplComposeTitle').value = '';
    composeSession?.setHTML('<p></p>');
    applyComposeChromeSettings(el('tplComposeChrome')?.value || 'simple');
    composeDirty = false;
    if (el('tplComposeStatus')) el('tplComposeStatus').textContent = '';
    if (el('tplStarterHint')) {
      el('tplStarterHint').textContent = 'Resolution, forwarding letter, notice, MOM, circular, agenda, office note — add more starters in the catalogue without changing the editor.';
    }
  }

  function clearComposeDocument() {
    if (composeDirty && !window.confirm('Clear the current draft?')) return;
    resetComposeFields();
  }

  function closeComposeDocument() {
    if (composeDirty && !window.confirm('Close without saving? The current draft will be cleared.')) return;
    resetComposeFields();
    if (el('templatesCompose')) el('templatesCompose').open = false;
  }

  function showTemplatesWorkspace(mode) {
    const composeBox = el('templatesCompose');
    const stationeryBox = el('templatesStationery');
    const editor = el('templatesEditor');
    if (composeBox) composeBox.open = mode === 'compose';
    if (stationeryBox) stationeryBox.open = mode === 'stationery';
    if (editor) editor.open = mode === 'upload';
  }

  async function startNewComposeDocument() {
    if (composeDirty && !window.confirm('Start a new document? The current draft will be cleared.')) return;
    if (stationeryDirty && !window.confirm('Leave the letterhead designer? Unsaved template changes will be lost.')) return;
    resetComposeFields();
    resetStationeryFields();
    showTemplatesWorkspace('compose');
    const statusLine = el('tplComposeStatus');
    try {
      const session = await mountComposeEditor();
      el('tplComposeShell')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (!session) {
        if (statusLine) statusLine.textContent = 'Composer failed to load — hard refresh the page.';
        return;
      }
      session.driver?.focus?.();
      if (statusLine && !statusLine.textContent) {
        statusLine.textContent = 'New document — pick a starter or start writing.';
      }
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Could not open composer.';
    }
  }

  function startUploadTemplate() {
    resetTemplatesForm();
    showTemplatesWorkspace('upload');
    el('templatesForm')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function saveComposeDocument(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('tplComposeStatus');
    const saveBtn = el('tplComposeSaveBtn');
    const title = String(el('tplComposeTitle')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title required.';
      return;
    }
    if (!composeSession || composeSession.isEmpty()) {
      if (statusLine) statusLine.textContent = 'Write the document, or pick a starter.';
      return;
    }
    const starter = currentComposeStarter();
    const editId = String(el('tplComposeEditId')?.value || '').trim();
    const payload = composeExportPayload();
    payload.title = title;
    payload.category = el('tplComposeCategory')?.value || starter?.category || 'correspondence';
    payload.status = el('tplComposeStatus')?.value || 'published';
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      const doc = editId
        ? (await api(`/api/rwa/templates/${encodeURIComponent(editId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })).template
        : (await api('/api/rwa/templates', {
          method: 'POST',
          body: JSON.stringify(payload),
        })).template;
      composeDirty = false;
      if (el('tplComposeEditId') && doc?.id) el('tplComposeEditId').value = doc.id;
      await loadTemplates();
      if (statusLine) statusLine.textContent = `Saved “${doc?.title || title}”. Open it from the library to print or mail.`;
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function bindComposeUi() {
    if (el('templatesComposeForm')?.dataset.bound === '1') return;
    if (el('templatesComposeForm')) el('templatesComposeForm').dataset.bound = '1';
    el('templatesComposeForm')?.addEventListener('submit', (event) => {
      saveComposeDocument(event).catch((e) => {
        if (el('tplComposeStatus')) el('tplComposeStatus').textContent = e.message || 'Save failed';
      });
    });
    el('tplStarterSelect')?.addEventListener('change', () => {
      const starter = currentComposeStarter();
      if (starter) applyComposeStarter(starter);
    });
    el('tplComposePreviewBtn')?.addEventListener('click', () => previewComposeDocument());
    el('tplComposeClearBtn')?.addEventListener('click', () => clearComposeDocument());
    el('tplComposeCloseBtn')?.addEventListener('click', () => closeComposeDocument());
    el('tplComposeNewBtn')?.addEventListener('click', (event) => {
      event.preventDefault();
      openTemplatesNewPicker(el('tplComposeNewBtn'));
    });
    el('tplComposeTitle')?.addEventListener('input', () => { composeDirty = true; });
    el('tplComposeChrome')?.addEventListener('change', () => {
      syncComposeWatermarkField();
      applyComposeChromeSettings(el('tplComposeChrome')?.value || 'simple');
    });
    el('tplComposeWatermark')?.addEventListener('change', () => {
      applyComposeChromeSettings(el('tplComposeChrome')?.value || 'simple');
    });
    el('tplComposeDownloadBtn')?.addEventListener('click', (event) => {
      event.preventDefault();
      closeComposeImportPicker();
      openComposeDownloadPicker(el('tplComposeDownloadBtn'));
    });
    el('tplComposeImportBtn')?.addEventListener('click', (event) => {
      event.preventDefault();
      closeComposeDownloadPicker();
      openComposeImportPicker(el('tplComposeImportBtn'));
    });
    el('tplComposeImportInput')?.addEventListener('change', () => {
      const file = el('tplComposeImportInput')?.files && el('tplComposeImportInput').files[0];
      if (!file) return;
      importComposeFromLocal(file).finally(() => {
        if (el('tplComposeImportInput')) el('tplComposeImportInput').value = '';
      });
    });
  }

  let composeDownloadPop = null;
  let composeImportPop = null;

  function closeComposeDownloadPicker() {
    if (!composeDownloadPop) return;
    composeDownloadPop.remove();
    composeDownloadPop = null;
    document.removeEventListener('mousedown', onComposeDownloadDoc, true);
    document.removeEventListener('keydown', onComposeDownloadEsc, true);
  }

  function onComposeDownloadDoc(event) {
    if (composeDownloadPop && !composeDownloadPop.contains(event.target) && !event.target.closest('#tplComposeDownloadBtn')) {
      closeComposeDownloadPicker();
    }
  }

  function onComposeDownloadEsc(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeComposeDownloadPicker();
    }
  }

  function openComposeDownloadPicker(btn) {
    if (!btn) return;
    if (composeDownloadPop) {
      closeComposeDownloadPicker();
      return;
    }
    const pop = document.createElement('div');
    pop.className = 'mhws-download-picker';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Download document');
    pop.innerHTML = '<p>Download</p>';
    [
      { format: 'pdf', label: 'PDF', dest: 'download' },
      { format: 'docx', label: 'Word (.docx)', dest: 'download' },
      { format: 'txt', label: 'Text (.txt)', dest: 'download' },
    ].forEach((item) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = item.label;
      b.addEventListener('click', () => {
        closeComposeDownloadPicker();
        downloadComposeDocument(item.format, item.dest);
      });
      pop.append(b);
    });
    const driveHead = document.createElement('p');
    driveHead.textContent = 'Google Drive';
    pop.append(driveHead);
    [
      { format: 'pdf', label: 'PDF → Drive', dest: 'drive' },
      { format: 'docx', label: 'Word → Drive', dest: 'drive' },
      { format: 'txt', label: 'Text → Drive', dest: 'drive' },
    ].forEach((item) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = item.label;
      b.addEventListener('click', () => {
        closeComposeDownloadPicker();
        downloadComposeDocument(item.format, item.dest);
      });
      pop.append(b);
    });
    document.body.append(pop);
    const br = btn.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(br.left, window.innerWidth - 200))}px`;
    pop.style.top = `${Math.min(br.bottom + 4, window.innerHeight - 320)}px`;
    composeDownloadPop = pop;
    document.addEventListener('mousedown', onComposeDownloadDoc, true);
    document.addEventListener('keydown', onComposeDownloadEsc, true);
  }

  function closeComposeImportPicker() {
    if (!composeImportPop) return;
    composeImportPop.remove();
    composeImportPop = null;
    document.removeEventListener('mousedown', onComposeImportDoc, true);
    document.removeEventListener('keydown', onComposeImportEsc, true);
  }

  function onComposeImportDoc(event) {
    if (composeImportPop && !composeImportPop.contains(event.target) && !event.target.closest('#tplComposeImportBtn')) {
      closeComposeImportPicker();
    }
  }

  function onComposeImportEsc(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeComposeImportPicker();
    }
  }

  function composeImportKindLabel(file) {
    const name = String(file?.name || '').toLowerCase();
    const mime = String(file?.mime || '').toLowerCase();
    if (mime.includes('google-apps.document')) return 'Google Doc';
    if (name.endsWith('.pdf') || mime.includes('pdf')) return 'PDF';
    if (name.endsWith('.docx') || name.endsWith('.doc') || mime.includes('word') || mime.includes('msword')) return 'Word';
    if (name.endsWith('.pages') || mime.includes('pages')) return 'Pages';
    if (name.endsWith('.txt') || name.endsWith('.text') || mime.startsWith('text/')) return 'Text';
    return 'File';
  }

  function openComposeImportPicker(btn) {
    if (!btn) return;
    if (composeImportPop) {
      closeComposeImportPicker();
      return;
    }
    const pop = document.createElement('div');
    pop.className = 'mhws-download-picker is-wide';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Import document');
    pop.innerHTML = '<p>Import</p>';
    const localBtn = document.createElement('button');
    localBtn.type = 'button';
    localBtn.textContent = 'This device';
    localBtn.addEventListener('click', () => {
      closeComposeImportPicker();
      el('tplComposeImportInput')?.click();
    });
    pop.append(localBtn);
    const driveHead = document.createElement('p');
    driveHead.textContent = 'Google Drive';
    pop.append(driveHead);
    const driveHint = document.createElement('p');
    driveHint.className = 'is-muted';
    driveHint.textContent = 'Loading…';
    pop.append(driveHint);
    document.body.append(pop);
    const br = btn.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(br.left, window.innerWidth - 280))}px`;
    pop.style.top = `${Math.min(br.bottom + 4, window.innerHeight - 360)}px`;
    composeImportPop = pop;
    document.addEventListener('mousedown', onComposeImportDoc, true);
    document.addEventListener('keydown', onComposeImportEsc, true);
    loadComposeImportDriveList(pop, driveHint);
  }

  async function loadComposeImportDriveList(pop, hint) {
    try {
      const data = await api('/api/rwa/templates/compose/import/drive');
      if (composeImportPop !== pop) return;
      const files = Array.isArray(data.files) ? data.files : [];
      hint.remove();
      if (!files.length) {
        const empty = document.createElement('p');
        empty.className = 'is-muted';
        empty.textContent = 'No text, Word, Pages, or PDF files in Drive.';
        pop.append(empty);
        return;
      }
      files.slice(0, 20).forEach((file) => {
        const b = document.createElement('button');
        b.type = 'button';
        const name = String(file.name || 'Untitled');
        const short = name.length > 36 ? `${name.slice(0, 34)}…` : name;
        b.textContent = `${short} · ${composeImportKindLabel(file)}`;
        b.title = name;
        b.addEventListener('click', () => {
          closeComposeImportPicker();
          importComposeFromDrive(file.id);
        });
        pop.append(b);
      });
    } catch (e) {
      hint.className = 'is-muted';
      hint.textContent = e.message || 'Google Drive is not available.';
    }
  }

  async function applyComposeImport(result) {
    if (!result?.html) throw new Error('No extractable text in that file.');
    await mountComposeEditor();
    if (!composeSession) throw new Error('Composer is not ready.');
    if (composeDirty && !window.confirm('Replace the current draft with the imported text?')) {
      return false;
    }
    composeSession.setHTML(result.html);
    if (el('tplComposeTitle') && !String(el('tplComposeTitle').value || '').trim()) {
      el('tplComposeTitle').value = result.title || '';
    }
    composeDirty = true;
    const statusLine = el('tplComposeStatus');
    if (statusLine) {
      statusLine.textContent = `Imported “${result.sourceName || result.title || 'document'}”. Letterhead is applied when you save or download.`;
    }
    return true;
  }

  async function importComposeFromLocal(file) {
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('tplComposeStatus');
    if (statusLine) statusLine.textContent = 'Importing…';
    try {
      const body = new FormData();
      body.append('file', file, file.name);
      const result = await api('/api/rwa/templates/compose/import', { method: 'POST', body });
      await applyComposeImport(result);
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Import failed';
    }
  }

  async function importComposeFromDrive(fileId) {
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('tplComposeStatus');
    if (statusLine) statusLine.textContent = 'Importing from Google Drive…';
    try {
      const result = await api('/api/rwa/templates/compose/import', {
        method: 'POST',
        body: JSON.stringify({ fileId }),
      });
      await applyComposeImport(result);
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Drive import failed';
    }
  }

  async function downloadComposeDocument(format, destination = 'download') {
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('tplComposeStatus');
    const title = String(el('tplComposeTitle')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title required.';
      return;
    }
    if (!composeSession || composeSession.isEmpty()) {
      if (statusLine) statusLine.textContent = 'Write the document, or pick a starter.';
      return;
    }
    const toDrive = destination === 'drive' || destination === 'gdrive';
    if (statusLine) statusLine.textContent = toDrive ? 'Saving to Google Drive…' : 'Preparing download…';
    try {
      const payload = { ...composeExportPayload(), format, destination: toDrive ? 'drive' : 'download' };
      if (toDrive) {
        const data = await api('/api/rwa/templates/compose/export', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        const name = data.drive?.name || data.filename || title;
        const url = data.drive?.url || '';
        if (statusLine) {
          statusLine.textContent = url
            ? `Saved “${name}” to Google Drive.`
            : `Saved “${name}” to Google Drive.`;
        }
        if (url) {
          const a = document.createElement('a');
          a.href = url;
          a.target = '_blank';
          a.rel = 'noopener';
          a.textContent = ' Open';
          statusLine?.append(' ', a);
        }
        return;
      }
      const { blob, filename } = await apiBinary('/api/rwa/templates/compose/export', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      triggerBlobDownload(blob, filename);
      if (statusLine) statusLine.textContent = `Downloaded “${filename}”. Library save is separate.`;
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || (toDrive ? 'Drive save failed' : 'Download failed');
    }
  }

  function syncTemplatesCustomSizeFields() {
    const custom = el('templatesPaperSizeInput')?.value === 'CUSTOM';
    if (el('templatesCustomSizeWrap')) el('templatesCustomSizeWrap').hidden = !custom;
  }

  function readTemplateOptionsFromForm() {
    const colors = {
      heading: el('templatesColorHeading')?.value || templatesOptionDefaults.colors.heading,
      body: el('templatesColorBody')?.value || templatesOptionDefaults.colors.body,
      muted: el('templatesColorMuted')?.value || templatesOptionDefaults.colors.muted,
      accent: el('templatesColorAccent')?.value || templatesOptionDefaults.colors.accent,
      gold: templatesOptionDefaults.colors.gold,
    };
    return {
      paperSize: el('templatesPaperSizeInput')?.value || 'A4',
      orientation: templatesOptionDefaults.orientation || 'portrait',
      background: el('templatesBackgroundInput')?.value || 'watermark',
      customWidthCm: Number(el('templatesCustomW')?.value || templatesOptionDefaults.customWidthCm || 22),
      customHeightCm: Number(el('templatesCustomH')?.value || templatesOptionDefaults.customHeightCm || 10),
      colors,
    };
  }

  function applyTemplateOptionsToForm(options) {
    const opts = options && typeof options === 'object' ? options : templatesOptionDefaults;
    const colors = opts.colors || templatesOptionDefaults.colors;
    if (el('templatesPaperSizeInput')) el('templatesPaperSizeInput').value = opts.paperSize || 'A4';
    if (el('templatesCustomW')) el('templatesCustomW').value = opts.customWidthCm ?? templatesOptionDefaults.customWidthCm ?? 22;
    if (el('templatesCustomH')) el('templatesCustomH').value = opts.customHeightCm ?? templatesOptionDefaults.customHeightCm ?? 10;
    if (el('templatesBackgroundInput')) el('templatesBackgroundInput').value = opts.background || 'watermark';
    if (el('templatesColorHeading')) el('templatesColorHeading').value = colors.heading || '#0b2a56';
    if (el('templatesColorBody')) el('templatesColorBody').value = colors.body || '#12233f';
    if (el('templatesColorMuted')) el('templatesColorMuted').value = colors.muted || '#5a6a80';
    if (el('templatesColorAccent')) el('templatesColorAccent').value = colors.accent || '#1a6b3a';
    syncTemplatesCustomSizeFields();
  }

  function templateIsHtml(doc) {
    if (!doc) return false;
    const mime = String(doc.mimeType || '').toLowerCase();
    const name = `${doc.originalName || ''} ${doc.filename || ''} ${doc.staticPath || ''} ${doc.publicUrl || ''}`;
    return mime.includes('html') || /\.html?/i.test(name);
  }

  function fillTemplatesCategorySelects(cats) {
    templatesCategories = Array.isArray(cats) && cats.length
      ? cats
      : [
        { id: 'letterhead', label: 'Letterhead' },
        { id: 'envelope', label: 'Envelope' },
        { id: 'receipt', label: 'Cash receipt' },
        { id: 'correspondence', label: 'Letters & resolutions' },
        { id: 'notice', label: 'Notice' },
        { id: 'form', label: 'Form' },
        { id: 'certificate', label: 'Certificate' },
        { id: 'chart', label: 'Chart / roster' },
        { id: 'other', label: 'Other' },
      ];
    const opts = templatesCategories
      .map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.label)}</option>`)
      .join('');
    if (el('templatesCategoryInput')) {
      const prev = el('templatesCategoryInput').value;
      el('templatesCategoryInput').innerHTML = opts;
      if (prev && [...el('templatesCategoryInput').options].some((o) => o.value === prev)) {
        el('templatesCategoryInput').value = prev;
      }
    }
    if (el('templatesCategoryFilter')) {
      const prev = el('templatesCategoryFilter').value;
      el('templatesCategoryFilter').innerHTML = `<option value="">All</option>${opts}`;
      if (prev && [...el('templatesCategoryFilter').options].some((o) => o.value === prev)) {
        el('templatesCategoryFilter').value = prev;
      }
    }
    if (el('tplComposeCategory')) {
      const prev = el('tplComposeCategory').value;
      el('tplComposeCategory').innerHTML = opts;
      if (prev && [...el('tplComposeCategory').options].some((o) => o.value === prev)) {
        el('tplComposeCategory').value = prev;
      } else if ([...el('tplComposeCategory').options].some((o) => o.value === 'correspondence')) {
        el('tplComposeCategory').value = 'correspondence';
      }
    }
    if (el('tplStationeryCategory')) {
      const prev = el('tplStationeryCategory').value;
      el('tplStationeryCategory').innerHTML = opts;
      if (prev && [...el('tplStationeryCategory').options].some((o) => o.value === prev)) {
        el('tplStationeryCategory').value = prev;
      } else if ([...el('tplStationeryCategory').options].some((o) => o.value === 'letterhead')) {
        el('tplStationeryCategory').value = 'letterhead';
      }
    }
  }

  function resetTemplatesForm() {
    if (el('templatesEditId')) el('templatesEditId').value = '';
    if (el('templatesTitleInput')) el('templatesTitleInput').value = '';
    if (el('templatesDescInput')) el('templatesDescInput').value = '';
    if (el('templatesTagsInput')) el('templatesTagsInput').value = '';
    if (el('templatesStatusInput')) el('templatesStatusInput').value = 'published';
    if (el('templatesFileInput')) el('templatesFileInput').value = '';
    if (el('templatesCategoryInput') && templatesCategories[0]) {
      el('templatesCategoryInput').value = templatesCategories[0].id;
    }
    applyTemplateOptionsToForm(templatesOptionDefaults);
    if (el('templatesSaveBtn')) el('templatesSaveBtn').textContent = 'Save to library';
    if (el('templatesStatus')) el('templatesStatus').textContent = '';
    const printOpts = el('templatesEditor')?.querySelector('.templates-print-options');
    if (printOpts) printOpts.open = false;
  }

  function closeTemplatesNewPicker() {
    if (!templatesNewPop) return;
    templatesNewPop.remove();
    templatesNewPop = null;
    document.removeEventListener('mousedown', onTemplatesNewDoc, true);
    document.removeEventListener('keydown', onTemplatesNewEsc, true);
  }

  function onTemplatesNewDoc(event) {
    if (
      templatesNewPop
      && !templatesNewPop.contains(event.target)
      && !event.target.closest('#templatesNewBtn, #tplComposeNewBtn, #tplStationeryNewBtn')
    ) {
      closeTemplatesNewPicker();
    }
  }

  function onTemplatesNewEsc(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeTemplatesNewPicker();
    }
  }

  function openTemplatesNewPicker(btn) {
    if (!btn) return;
    if (templatesNewPop) {
      closeTemplatesNewPicker();
      return;
    }
    const pop = document.createElement('div');
    pop.className = 'mhws-download-picker';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Create new');
    pop.innerHTML = '<p>Create new</p>';
    [
      { id: 'document', label: 'Document' },
      { id: 'template', label: 'Template (letterhead)' },
    ].forEach((item) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = item.label;
      b.addEventListener('click', () => {
        closeTemplatesNewPicker();
        if (item.id === 'template') startNewStationeryTemplate();
        else startNewComposeDocument();
      });
      pop.append(b);
    });
    document.body.append(pop);
    const br = btn.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(br.left, window.innerWidth - 220))}px`;
    pop.style.top = `${Math.min(br.bottom + 4, window.innerHeight - 160)}px`;
    templatesNewPop = pop;
    document.addEventListener('mousedown', onTemplatesNewDoc, true);
    document.addEventListener('keydown', onTemplatesNewEsc, true);
  }

  function stationeryApi() {
    return window.MhwsComposer?.stationery || null;
  }

  async function ensureStationeryForm() {
    const C = await whenComposerReady();
    const apiSt = C?.stationery || stationeryApi();
    if (!apiSt) throw new Error('Template designer failed to load — hard refresh the page.');
    if (!stationerySpec) stationerySpec = apiSt.normalize(apiSt.defaultSpec());
    if (el('tplStPaper') && !el('tplStPaper').options.length) {
      el('tplStPaper').innerHTML = apiSt.papers
        .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`)
        .join('');
    }
    if (el('tplStBorder') && !el('tplStBorder').options.length) {
      el('tplStBorder').innerHTML = apiSt.borders
        .map((b) => `<option value="${escapeHtml(b.id)}">${escapeHtml(b.label)}</option>`)
        .join('');
    }
    if (el('tplStFootFont') && !el('tplStFootFont').options.length) {
      el('tplStFootFont').innerHTML = apiSt.fonts
        .map((f) => `<option value="${escapeHtml(f.id)}">${escapeHtml(f.label)}</option>`)
        .join('');
    }
    return apiSt;
  }

  function syncStationeryCustomFields() {
    const custom = el('tplStPaper')?.value === 'CUSTOM';
    document.querySelectorAll('.tpl-st-custom').forEach((node) => {
      node.hidden = !custom;
    });
  }

  function renderStationeryHeaderLines(lines) {
    const mount = el('tplStHeaderLines');
    const apiSt = stationeryApi();
    if (!mount || !apiSt) return;
    const fonts = apiSt.fonts;
    mount.innerHTML = (lines || []).map((line, index) => `
      <div class="mhws-stationery-line" data-line="${index}">
        <input type="text" data-field="text" value="${escapeHtml(line.text || '')}" placeholder="Header line ${index + 1}" aria-label="Header line ${index + 1}">
        <select data-field="font" aria-label="Font">
          ${fonts.map((f) => `<option value="${escapeHtml(f.id)}"${f.id === line.font ? ' selected' : ''}>${escapeHtml(f.label)}</option>`).join('')}
        </select>
        <input type="number" data-field="sizePt" min="6" max="36" step="0.5" value="${escapeHtml(String(line.sizePt || 11))}" aria-label="Size">
        <select data-field="weight" aria-label="Weight">
          ${['400', '500', '600', '700'].map((w) => `<option value="${w}"${String(line.weight) === w ? ' selected' : ''}>${w === '400' ? 'Regular' : w === '500' ? 'Medium' : w === '600' ? 'Semibold' : 'Bold'}</option>`).join('')}
        </select>
        <input type="color" data-field="color" value="${escapeHtml(line.color || '#0b2a56')}" aria-label="Colour">
        <select data-field="align" aria-label="Align">
          ${['left', 'center', 'right'].map((a) => `<option value="${a}"${line.align === a ? ' selected' : ''}>${a[0].toUpperCase()}${a.slice(1)}</option>`).join('')}
        </select>
        <button type="button" class="btn ghost compact" data-remove-line="${index}" title="Remove line" ${lines.length <= 1 ? 'disabled' : ''}>×</button>
      </div>
    `).join('');
  }

  function applyStationerySpecToForm(specIn) {
    const apiSt = stationeryApi();
    if (!apiSt) return;
    stationerySpec = apiSt.normalize(specIn || apiSt.defaultSpec());
    const spec = stationerySpec;
    if (el('tplStationeryTitle') && !el('tplStationeryEditId')?.value) {
      /* keep title when editing */
    }
    if (el('tplStPaper')) el('tplStPaper').value = spec.paper.id || 'A4';
    if (el('tplStOrientation')) el('tplStOrientation').value = spec.paper.orientation || 'portrait';
    if (el('tplStWidthMm')) el('tplStWidthMm').value = spec.paper.widthMm;
    if (el('tplStHeightMm')) el('tplStHeightMm').value = spec.paper.heightMm;
    if (el('tplStBg')) el('tplStBg').value = spec.backgroundColor || '#ffffff';
    if (el('tplStBorder')) el('tplStBorder').value = spec.border?.style || 'navy-rule';
    if (el('tplStLogoOn')) el('tplStLogoOn').checked = !!spec.logo?.enabled;
    if (el('tplStLogoW')) el('tplStLogoW').value = spec.logo?.widthMm || 18;
    if (el('tplStLogoAlign')) el('tplStLogoAlign').value = spec.logo?.align || 'center';
    if (el('tplStWmOn')) el('tplStWmOn').checked = !!spec.watermark?.enabled;
    if (el('tplStWmOpacity')) el('tplStWmOpacity').value = spec.watermark?.opacity ?? 0.72;
    if (el('tplStFootText')) el('tplStFootText').value = spec.footer?.text || '';
    if (el('tplStFootFont')) el('tplStFootFont').value = spec.footer?.font || 'noto';
    if (el('tplStFootSize')) el('tplStFootSize').value = spec.footer?.sizePt || 8;
    if (el('tplStFootWeight')) el('tplStFootWeight').value = spec.footer?.weight || '600';
    if (el('tplStFootColor')) el('tplStFootColor').value = spec.footer?.color || '#5a6a80';
    syncStationeryCustomFields();
    renderStationeryHeaderLines(spec.headerLines);
  }

  function readStationerySpecFromForm() {
    const apiSt = stationeryApi();
    if (!apiSt) return stationerySpec;
    const lines = [];
    el('tplStHeaderLines')?.querySelectorAll('.mhws-stationery-line').forEach((row) => {
      lines.push({
        text: row.querySelector('[data-field="text"]')?.value || '',
        font: row.querySelector('[data-field="font"]')?.value || 'noto',
        sizePt: row.querySelector('[data-field="sizePt"]')?.value || 11,
        weight: row.querySelector('[data-field="weight"]')?.value || '600',
        color: row.querySelector('[data-field="color"]')?.value || '#0b2a56',
        align: row.querySelector('[data-field="align"]')?.value || 'center',
      });
    });
    const prev = stationerySpec || apiSt.defaultSpec();
    stationerySpec = apiSt.normalize({
      paper: {
        id: el('tplStPaper')?.value || 'A4',
        widthMm: el('tplStWidthMm')?.value,
        heightMm: el('tplStHeightMm')?.value,
        orientation: el('tplStOrientation')?.value || 'portrait',
      },
      backgroundColor: el('tplStBg')?.value || '#ffffff',
      logo: {
        src: prev.logo?.src || '',
        enabled: !!el('tplStLogoOn')?.checked,
        widthMm: el('tplStLogoW')?.value || 18,
        align: el('tplStLogoAlign')?.value || 'center',
      },
      headerLines: lines,
      watermark: {
        src: prev.watermark?.src || '',
        enabled: !!el('tplStWmOn')?.checked,
        opacity: el('tplStWmOpacity')?.value || 0.72,
      },
      footer: {
        text: el('tplStFootText')?.value || '',
        font: el('tplStFootFont')?.value || 'noto',
        sizePt: el('tplStFootSize')?.value || 8,
        weight: el('tplStFootWeight')?.value || '600',
        color: el('tplStFootColor')?.value || '#5a6a80',
      },
      border: { style: el('tplStBorder')?.value || 'navy-rule' },
    });
    return stationerySpec;
  }

  function paintStationeryDesk() {
    const apiSt = stationeryApi();
    const host = el('tplStationeryPreview');
    if (!apiSt || !host) return;
    const spec = readStationerySpecFromForm();
    apiSt.paintPreview(host, spec);
  }

  function markStationeryDirty() {
    stationeryDirty = true;
    syncStationeryCustomFields();
    paintStationeryDesk();
  }

  function resetStationeryFields() {
    const apiSt = stationeryApi();
    if (el('tplStationeryEditId')) el('tplStationeryEditId').value = '';
    if (el('tplStationeryTitle')) el('tplStationeryTitle').value = '';
    if (el('tplStationeryStatus')) el('tplStationeryStatus').value = 'published';
    if (el('tplStationeryCategory') && [...(el('tplStationeryCategory').options || [])].some((o) => o.value === 'letterhead')) {
      el('tplStationeryCategory').value = 'letterhead';
    }
    if (el('tplStLogoFile')) el('tplStLogoFile').value = '';
    if (el('tplStWmFile')) el('tplStWmFile').value = '';
    stationerySpec = apiSt ? apiSt.normalize(apiSt.defaultSpec()) : null;
    if (stationerySpec) applyStationerySpecToForm(stationerySpec);
    stationeryDirty = false;
    if (el('tplStationeryStatus')) el('tplStationeryStatus').textContent = '';
  }

  async function startNewStationeryTemplate() {
    if (composeDirty && !window.confirm('Leave the document composer? Unsaved document changes will be lost.')) return;
    if (stationeryDirty && !window.confirm('Start a new letterhead? The current draft will be cleared.')) return;
    resetComposeFields();
    showTemplatesWorkspace('stationery');
    try {
      await ensureStationeryForm();
      resetStationeryFields();
      paintStationeryDesk();
      el('templatesStationery')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      el('tplStationeryTitle')?.focus();
      if (el('tplStationeryStatus')) {
        el('tplStationeryStatus').textContent = 'New letterhead — adjust chrome, then save. It appears in the document letterhead list.';
      }
    } catch (e) {
      if (el('tplStationeryStatus')) el('tplStationeryStatus').textContent = e.message || 'Could not open template designer.';
    }
  }

  function closeStationeryDesigner() {
    if (stationeryDirty && !window.confirm('Close without saving? Unsaved letterhead changes will be lost.')) return;
    resetStationeryFields();
    if (el('templatesStationery')) el('templatesStationery').open = false;
  }

  async function saveStationeryTemplate(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('tplStationeryStatus');
    const saveBtn = el('tplStationerySaveBtn');
    const title = String(el('tplStationeryTitle')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title required.';
      return;
    }
    try {
      await ensureStationeryForm();
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Designer not ready.';
      return;
    }
    const spec = readStationerySpecFromForm();
    const editId = String(el('tplStationeryEditId')?.value || '').trim();
    const payload = {
      title,
      category: el('tplStationeryCategory')?.value || 'letterhead',
      status: el('tplStationeryStatus')?.value || 'published',
      tags: 'stationery,letterhead',
      stationery: spec,
    };
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      const doc = editId
        ? (await api(`/api/rwa/templates/${encodeURIComponent(editId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })).template
        : (await api('/api/rwa/templates', {
          method: 'POST',
          body: JSON.stringify(payload),
        })).template;
      stationeryDirty = false;
      if (el('tplStationeryEditId') && doc?.id) el('tplStationeryEditId').value = doc.id;
      await loadTemplates();
      if (statusLine) {
        statusLine.textContent = `Saved “${doc?.title || title}”. Use it as letterhead when writing a document.`;
      }
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function previewStationeryTemplate() {
    try {
      await ensureStationeryForm();
    } catch (e) {
      if (el('tplStationeryStatus')) el('tplStationeryStatus').textContent = e.message || 'Designer not ready.';
      return;
    }
    const apiSt = stationeryApi();
    const title = String(el('tplStationeryTitle')?.value || '').trim() || 'Letterhead';
    const html = apiSt.renderDocument(readStationerySpecFromForm(), title);
    if (stationeryPreviewUrl) URL.revokeObjectURL(stationeryPreviewUrl);
    stationeryPreviewUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    const dialog = el('docViewerDialog');
    if (dialog) document.body.appendChild(dialog);
    showDocViewerSource(stationeryPreviewUrl, {
      title,
      filename: `${title}.html`,
      mime: 'text/html',
      isBlob: true,
    });
  }

  async function pickStationeryImage(kind, file) {
    const apiSt = await ensureStationeryForm();
    try {
      const src = await apiSt.readImageAsDataUrl(file);
      const spec = readStationerySpecFromForm();
      if (kind === 'logo') {
        spec.logo.src = src;
        spec.logo.enabled = true;
        if (el('tplStLogoOn')) el('tplStLogoOn').checked = true;
      } else {
        spec.watermark.src = src;
        spec.watermark.enabled = true;
        if (el('tplStWmOn')) el('tplStWmOn').checked = true;
      }
      stationerySpec = apiSt.normalize(spec);
      stationeryDirty = true;
      paintStationeryDesk();
    } catch (e) {
      if (el('tplStationeryStatus')) el('tplStationeryStatus').textContent = e.message || 'Image failed';
    }
  }

  function bindStationeryUi() {
    if (stationeryBound) return;
    stationeryBound = true;
    el('templatesStationeryForm')?.addEventListener('submit', (event) => {
      saveStationeryTemplate(event).catch((e) => {
        if (el('tplStationeryStatus')) el('tplStationeryStatus').textContent = e.message || 'Save failed';
      });
    });
    el('tplStationeryNewBtn')?.addEventListener('click', (event) => {
      event.preventDefault();
      openTemplatesNewPicker(el('tplStationeryNewBtn'));
    });
    el('tplStationeryPreviewBtn')?.addEventListener('click', () => previewStationeryTemplate());
    el('tplStationeryCloseBtn')?.addEventListener('click', () => closeStationeryDesigner());
    el('tplStationeryTitle')?.addEventListener('input', () => { stationeryDirty = true; });
    el('tplStAddLineBtn')?.addEventListener('click', () => {
      const spec = readStationerySpecFromForm();
      if ((spec.headerLines || []).length >= 8) return;
      spec.headerLines.push({
        text: '',
        font: 'noto',
        sizePt: 10,
        weight: '600',
        color: '#0b2a56',
        align: 'center',
      });
      stationerySpec = spec;
      renderStationeryHeaderLines(spec.headerLines);
      markStationeryDirty();
    });
    el('tplStHeaderLines')?.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-remove-line]');
      if (!btn) return;
      const index = Number(btn.getAttribute('data-remove-line'));
      const spec = readStationerySpecFromForm();
      if ((spec.headerLines || []).length <= 1) return;
      spec.headerLines.splice(index, 1);
      stationerySpec = spec;
      renderStationeryHeaderLines(spec.headerLines);
      markStationeryDirty();
    });
    el('tplStHeaderLines')?.addEventListener('input', () => markStationeryDirty());
    el('tplStHeaderLines')?.addEventListener('change', () => markStationeryDirty());
    [
      'tplStPaper', 'tplStOrientation', 'tplStWidthMm', 'tplStHeightMm', 'tplStBg', 'tplStBorder',
      'tplStLogoOn', 'tplStLogoW', 'tplStLogoAlign', 'tplStWmOn', 'tplStWmOpacity',
      'tplStFootText', 'tplStFootFont', 'tplStFootSize', 'tplStFootWeight', 'tplStFootColor',
      'tplStationeryCategory', 'tplStationeryStatus',
    ].forEach((id) => {
      el(id)?.addEventListener('input', () => markStationeryDirty());
      el(id)?.addEventListener('change', () => markStationeryDirty());
    });
    el('tplStLogoFile')?.addEventListener('change', () => {
      const file = el('tplStLogoFile')?.files?.[0];
      if (file) pickStationeryImage('logo', file);
    });
    el('tplStWmFile')?.addEventListener('change', () => {
      const file = el('tplStWmFile')?.files?.[0];
      if (file) pickStationeryImage('wm', file);
    });
  }

  function isStationeryTemplate(doc) {
    if (!doc) return false;
    if (doc.options && doc.options.stationery && typeof doc.options.stationery === 'object') return true;
    return (doc.tags || []).includes('stationery');
  }

  function isComposedTemplate(doc) {
    if (!doc) return false;
    if (isStationeryTemplate(doc)) return false;
    if (doc.options && doc.options.composed) return true;
    return (doc.tags || []).includes('compose');
  }

  async function beginEditComposedTemplate(id) {
    const doc = await resolveTemplateDoc(id);
    if (!doc?.id) throw new Error('Document not found');
    if (isStationeryTemplate(doc)) {
      await beginEditStationeryTemplate(doc.id);
      return;
    }
    if (!isComposedTemplate(doc)) {
      beginEditTemplate(id);
      return;
    }
    const session = await mountComposeEditor();
    if (!session) throw new Error('Composer is not ready');
    const headers = {};
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    const res = await fetch(authDocUrl(`/api/rwa/templates/${encodeURIComponent(doc.id)}/file`), {
      credentials: 'same-origin',
      headers,
    });
    if (!res.ok) throw new Error('Could not load the document');
    const html = await res.text();
    const C = window.MhwsComposer;
    const body = C?.extractBody ? C.extractBody(html) : html;
    session.setHTML(body || '<p></p>');
    if (el('tplComposeEditId')) el('tplComposeEditId').value = doc.id;
    if (el('tplComposeTitle')) el('tplComposeTitle').value = doc.title || '';
    if (el('tplComposeCategory') && doc.category) el('tplComposeCategory').value = doc.category;
    if (el('tplComposeStatus') && doc.status) el('tplComposeStatus').value = doc.status;
    const chrome = doc.options?.composeChrome || '';
    if (el('tplComposeChrome') && chrome) {
      const select = el('tplComposeChrome');
      if ([...select.options].some((o) => o.value === chrome)) select.value = chrome;
    }
    if (el('tplComposeWatermark') && doc.options && 'composeWatermark' in doc.options) {
      el('tplComposeWatermark').value = doc.options.composeWatermark ? '1' : '0';
    }
    syncComposeWatermarkField();
    applyComposeChromeSettings(chrome || el('tplComposeChrome')?.value || 'simple');
    composeDirty = false;
    showTemplatesWorkspace('compose');
    closeDocViewer();
    if (el('tplComposeStatus')) {
      el('tplComposeStatus').textContent = `Editing “${doc.title || 'document'}”. Save to update the library copy.`;
    }
    el('tplComposeShell')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    session.driver?.focus?.();
  }

  async function beginEditStationeryTemplate(id) {
    const doc = await resolveTemplateDoc(id);
    if (!doc?.id) throw new Error('Template not found');
    if (!isStationeryTemplate(doc)) {
      beginEditTemplate(id);
      return;
    }
    await ensureStationeryForm();
    if (el('tplStationeryEditId')) el('tplStationeryEditId').value = doc.id;
    if (el('tplStationeryTitle')) el('tplStationeryTitle').value = doc.title || '';
    if (el('tplStationeryCategory') && doc.category) el('tplStationeryCategory').value = doc.category;
    if (el('tplStationeryStatus') && doc.status) el('tplStationeryStatus').value = doc.status;
    applyStationerySpecToForm(doc.options?.stationery || stationeryApi()?.defaultSpec());
    stationeryDirty = false;
    showTemplatesWorkspace('stationery');
    paintStationeryDesk();
    closeDocViewer();
    if (el('tplStationeryStatus')) {
      el('tplStationeryStatus').textContent = `Editing “${doc.title || 'letterhead'}”. Save to update the letterhead.`;
    }
    el('templatesStationery')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function beginEditTemplate(id) {
    const doc = templatesCache.find((t) => t.id === id);
    if (!doc) return;
    if (isStationeryTemplate(doc)) {
      beginEditStationeryTemplate(doc.id).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Open template designer failed';
      });
      return;
    }
    if (isComposedTemplate(doc)) {
      beginEditComposedTemplate(doc.id).catch((e) => {
        if (el('templatesStatus')) el('templatesStatus').textContent = e.message || 'Open composer failed';
      });
      return;
    }
    if (el('templatesEditId')) el('templatesEditId').value = doc.id;
    if (el('templatesTitleInput')) el('templatesTitleInput').value = doc.title || '';
    if (el('templatesDescInput')) el('templatesDescInput').value = doc.description || '';
    if (el('templatesCategoryInput')) el('templatesCategoryInput').value = doc.category || 'other';
    if (el('templatesStatusInput')) el('templatesStatusInput').value = doc.status || 'published';
    if (el('templatesTagsInput')) el('templatesTagsInput').value = (doc.tags || []).join(', ');
    if (el('templatesFileInput')) el('templatesFileInput').value = '';
    applyTemplateOptionsToForm(doc.options || templatesOptionDefaults);
    if (el('templatesSaveBtn')) el('templatesSaveBtn').textContent = 'Update';
    if (el('templatesStatus')) {
      el('templatesStatus').textContent = doc.docType === 'static'
        ? 'Editing a seeded print pad. Upload a file only if you want to replace it with a private copy.'
        : 'Leave the file blank to keep the current file.';
    }
    showTemplatesWorkspace('upload');
    const printOpts = el('templatesEditor')?.querySelector('.templates-print-options');
    if (printOpts) printOpts.open = true;
    el('templatesForm')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function templateLooksOffice(doc) {
    const name = `${doc?.originalName || ''} ${doc?.filename || ''} ${doc?.staticPath || ''}`.toLowerCase();
    const mime = String(doc?.mimeType || '').toLowerCase();
    return name.includes('.docx') || name.includes('.doc')
      || mime.includes('msword') || mime.includes('wordprocessingml');
  }

  function templateKindBadge(doc) {
    if (isStationeryTemplate(doc)) return { label: 'Letterhead', cls: 'is-link' };
    if (isComposedTemplate(doc)) return { label: 'Written', cls: 'is-file' };
    if (templateLooksOffice(doc)) return { label: 'Word', cls: 'is-file' };
    const mime = String(doc?.mimeType || '').toLowerCase();
    const name = `${doc?.originalName || ''} ${doc?.filename || ''} ${doc?.staticPath || ''} ${doc?.publicUrl || ''}`.toLowerCase();
    if (mime.includes('pdf') || name.includes('.pdf')) return { label: 'PDF', cls: 'is-file' };
    if (templateIsHtml(doc) || doc?.docType === 'static') return { label: 'Print pad', cls: 'is-link' };
    return { label: 'File', cls: 'is-file' };
  }

  function templateVisibleTags(doc) {
    const skip = new Set([
      'compose', 'composed', 'stationery', 'print', 'a4', 'letterhead',
      String(doc?.category || '').toLowerCase(),
    ]);
    return (doc?.tags || []).filter((t) => {
      const v = String(t || '').trim();
      return v && !skip.has(v.toLowerCase());
    });
  }

  function templateCardMeta(doc) {
    const bits = [];
    if (!isComposedTemplate(doc) && doc.originalName) bits.push(doc.originalName);
    if (doc.updatedAt) {
      bits.push(`Updated ${new Date(doc.updatedAt).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}`);
    }
    if (isComposedTemplate(doc)) return bits.join(' · ');
    const opts = doc.options || {};
    let paperLabel = opts.paperSize || 'A4';
    if (opts.paperSize === 'E2210') paperLabel = '22 × 10 cm';
    if (opts.paperSize === 'CUSTOM') {
      const w = opts.customWidthCm || 22;
      const h = opts.customHeightCm || 10;
      paperLabel = `${w} × ${h} cm`;
    }
    const bg = opts.background === 'none' ? 'no watermark' : (opts.background === 'plain' ? 'plain' : '');
    bits.push(paperLabel);
    if (bg) bits.push(bg);
    return bits.join(' · ');
  }

  function groupedTemplates(list) {
    const order = (templatesCategories || []).map((c) => c.id);
    const groups = new Map();
    for (const doc of list || []) {
      const id = doc.category || 'other';
      if (!groups.has(id)) {
        groups.set(id, { id, label: doc.categoryLabel || id, items: [] });
      }
      groups.get(id).items.push(doc);
    }
    const ordered = [];
    for (const id of order) {
      if (groups.has(id)) ordered.push(groups.get(id));
    }
    for (const [id, group] of groups) {
      if (!order.includes(id)) ordered.push(group);
    }
    return ordered;
  }

  function renderTemplatesList() {
    const mount = el('templatesList');
    if (!mount) return;
    if (!templatesCache.length) {
      mount.innerHTML = '<p class="muted">Nothing in this view. Write a document or upload a file.</p>';
      return;
    }
    mount.innerHTML = groupedTemplates(templatesCache).map((group) => {
      const cards = group.items.map((doc) => {
      const tags = templateVisibleTags(doc).map((t) => `<span class="info-doc-badge">${escapeHtml(t)}</span>`).join(' ');
      const kind = templateKindBadge(doc);
      const composed = isComposedTemplate(doc);
      const stationery = isStationeryTemplate(doc);
      const status = doc.status && doc.status !== 'published'
        ? `<span class="info-doc-badge is-draft">${escapeHtml(doc.status)}</span>`
        : '';
      const meta = templateCardMeta(doc);
      return `
        <article class="info-doc-card" data-doc-type="${escapeHtml(doc.docType || 'file')}">
          <div class="info-doc-card-row">
            <div>
              <div class="info-doc-badges">
                <span class="info-doc-badge ${kind.cls}">${escapeHtml(kind.label)}</span>
                ${status}
              </div>
              <h4 class="info-doc-card-title tpl-open-title" data-tpl-open="${escapeHtml(doc.id)}" title="Open">${escapeHtml(doc.title || 'Untitled')}</h4>
              ${meta ? `<p class="meta">${escapeHtml(meta)}</p>` : ''}
              ${doc.description ? `<p class="summary">${escapeHtml(doc.description)}</p>` : ''}
              ${tags ? `<div class="info-doc-badges" style="margin-top:0.35rem">${tags}</div>` : ''}
            </div>
          </div>
          <div class="tpl-card-toolbar">
            <button type="button" class="btn secondary compact" data-tpl-open="${escapeHtml(doc.id)}">Open</button>
            ${composed ? `<button type="button" class="btn ghost compact" data-tpl-compose-edit="${escapeHtml(doc.id)}">Edit</button>` : ''}
            ${stationery ? `<button type="button" class="btn ghost compact" data-tpl-stationery-edit="${escapeHtml(doc.id)}">Edit</button>` : ''}
            <details class="tpl-card-actions">
              <summary class="btn ghost compact tpl-card-actions-summary">More</summary>
              <div class="btn-row info-doc-card-actions-inline">
                <button type="button" class="btn ghost compact" data-tpl-download="${escapeHtml(doc.id)}">Download</button>
                <button type="button" class="btn ghost compact" data-tpl-mail="${escapeHtml(doc.id)}">Mail</button>
                <button type="button" class="btn ghost compact" data-tpl-edit="${escapeHtml(doc.id)}">Details</button>
                <button type="button" class="btn ghost compact" data-tpl-delete="${escapeHtml(doc.id)}">Delete</button>
              </div>
            </details>
          </div>
        </article>`;
      }).join('');
      const count = group.items.length;
      return `
        <section class="tpl-category-block">
          <div class="tpl-category-head">
            <div>
              <h4>${escapeHtml(group.label)}</h4>
              <p class="muted">${count} item${count === 1 ? '' : 's'}</p>
            </div>
            ${count > 1 ? `<button type="button" class="btn ghost compact" data-tpl-mail-category="${escapeHtml(group.id)}">Mail all</button>` : ''}
          </div>
          <div class="info-doc-list is-cards">${cards}</div>
        </section>`;
    }).join('');
  }

  async function loadTemplates() {
    if (!hasEntitlement('manage_templates')) return;
    const qs = new URLSearchParams();
    const status = el('templatesStatusFilter')?.value || 'all';
    const category = el('templatesCategoryFilter')?.value || '';
    qs.set('status', status);
    if (category) qs.set('category', category);
    const data = await api(`/api/rwa/templates?${qs.toString()}`);
    fillTemplatesCategorySelects(data.categories || []);
    if (data.optionPresets?.defaults) {
      templatesOptionDefaults = data.optionPresets.defaults;
    }
    templatesCache = data.templates || [];
    templatesStarters = Array.isArray(data.starters) ? data.starters : templatesStarters;
    templatesChromes = Array.isArray(data.chromes) ? data.chromes : templatesChromes;
    fillComposeStarterSelect();
    fillComposeChromeSelect();
    applyComposeChromeSettings(el('tplComposeChrome')?.value || 'simple');
    if (el('templatesCompose')?.open) {
      mountComposeEditor().catch((e) => {
        if (el('tplComposeStatus')) {
          el('tplComposeStatus').textContent = e.message || 'Composer failed to load — hard refresh the page.';
        }
      });
    }
    renderTemplatesList();
    if (el('templatesStatus') && !el('templatesEditId')?.value) {
      el('templatesStatus').textContent = `${templatesCache.length} template${templatesCache.length === 1 ? '' : 's'}`;
    }
  }

  function templateFileUrls(doc) {
    if (!doc?.id) return { viewUrl: '', downloadUrl: '', mime: 'application/octet-stream', useRender: false };
    const mime = doc.mimeType
      || (doc.docType === 'static' && /\.html?$/i.test(doc.publicUrl || doc.staticPath || '')
        ? 'text/html'
        : 'application/octet-stream');
    const useRender = templateIsHtml(doc);
    if (useRender) {
      const renderApi = `/api/rwa/templates/${encodeURIComponent(doc.id)}/render`;
      return {
        viewUrl: authDocUrl(renderApi),
        downloadUrl: authDocUrl(renderApi, { download: '1' }),
        mime: 'text/html',
        filename: doc.originalName || pathlibBasename(doc.publicUrl || doc.staticPath || 'template.html'),
        useRender: true,
      };
    }
    if (doc.docType === 'static' && doc.publicUrl) {
      return {
        viewUrl: doc.publicUrl,
        downloadUrl: doc.publicUrl,
        mime,
        filename: doc.originalName || pathlibBasename(doc.publicUrl || doc.staticPath || 'template.html'),
        useRender: false,
      };
    }
    const fileApi = `/api/rwa/templates/${encodeURIComponent(doc.id)}/file`;
    return {
      viewUrl: authDocUrl(fileApi),
      downloadUrl: authDocUrl(fileApi, { download: '1' }),
      mime,
      filename: doc.originalName || doc.filename || 'template',
      useRender: false,
    };
  }

  function pathlibBasename(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    return parts[parts.length - 1] || 'template';
  }

  async function resolveTemplateDoc(id) {
    return templatesCache.find((t) => t.id === id)
      || (await api(`/api/rwa/templates/${encodeURIComponent(id)}`)).template;
  }

  async function openTemplate(id, { printAfter = false } = {}) {
    const doc = await resolveTemplateDoc(id);
    if (!doc?.id) throw new Error('Template not found');
    const urls = templateFileUrls(doc);
    if (!urls.viewUrl) throw new Error('Template file is missing');
    showDocViewerSource(urls.viewUrl, {
      title: doc.title || 'Template',
      filename: urls.filename,
      mime: urls.mime,
      isBlob: false,
      downloadUrl: urls.downloadUrl,
      newTabUrl: urls.viewUrl,
      canPrint: true,
      canDownload: false,
      canEditCompose: isComposedTemplate(doc),
      templateId: doc.id,
      printAfterOpen: Boolean(printAfter),
    });
  }

  function closeTemplateMailDialog() {
    const dialog = el('templateMailDialog');
    if (dialog && typeof dialog.close === 'function' && dialog.open) {
      dialog.close();
      return;
    }
    if (dialog) dialog.hidden = true;
  }

  function openTemplateMailDialog({ templateId = '', category = '' } = {}) {
    const dialog = el('templateMailDialog');
    if (!dialog) return;
    if (dialog.parentElement !== document.body) document.body.appendChild(dialog);
    const tid = String(templateId || '').trim();
    const cat = String(category || '').trim();
    if (el('templateMailTemplateId')) el('templateMailTemplateId').value = tid;
    if (el('templateMailCategory')) el('templateMailCategory').value = cat;
    const doc = tid ? templatesCache.find((t) => t.id === tid) : null;
    const group = cat ? groupedTemplates(templatesCache).find((g) => g.id === cat) : null;
    if (el('templateMailTitle')) {
      el('templateMailTitle').textContent = tid ? 'Mail template' : 'Mail category files';
    }
    if (el('templateMailLead')) {
      const office = tid && templateLooksOffice(doc);
      el('templateMailLead').textContent = tid
        ? (office
          ? `Send the original Word file for “${doc?.title || 'this template'}”.`
          : `Send a print-formatted PDF of “${doc?.title || 'this template'}”.`)
        : `Send all ${group?.items?.length || 0} file${(group?.items?.length || 0) === 1 ? '' : 's'} in ${group?.label || cat} (PDF for print pads, original Word for .doc/.docx).`;
    }
    if (el('templateMailSubject')) {
      el('templateMailSubject').value = tid
        ? `MHWS template — ${doc?.title || 'colony pad'}`
        : `MHWS templates — ${group?.label || cat}`;
    }
    if (el('templateMailMessage')) el('templateMailMessage').value = '';
    if (el('templateMailStatus')) el('templateMailStatus').textContent = '';
    if (el('templateMailSubmitBtn')) el('templateMailSubmitBtn').disabled = false;
    try {
      if (typeof dialog.showModal === 'function') {
        if (!dialog.open) dialog.showModal();
        el('templateMailTo')?.focus();
        return;
      }
    } catch (_e) { /* ignore */ }
    dialog.hidden = false;
    el('templateMailTo')?.focus();
  }

  async function submitTemplateMail(event) {
    event.preventDefault();
    const to = String(el('templateMailTo')?.value || '').trim();
    const statusLine = el('templateMailStatus');
    const btn = el('templateMailSubmitBtn');
    const templateId = String(el('templateMailTemplateId')?.value || '').trim();
    const category = String(el('templateMailCategory')?.value || '').trim();
    if (!to) {
      if (statusLine) statusLine.textContent = 'Enter at least one email address.';
      return;
    }
    const path = templateId
      ? `/api/rwa/templates/${encodeURIComponent(templateId)}/mail`
      : `/api/rwa/templates/category/${encodeURIComponent(category)}/mail`;
    if (!templateId && !category) {
      if (statusLine) statusLine.textContent = 'Choose a template or category.';
      return;
    }
    const body = {
      to,
      subject: String(el('templateMailSubject')?.value || '').trim(),
      message: String(el('templateMailMessage')?.value || '').trim(),
    };
    if (!templateId) body.status = el('templatesStatusFilter')?.value || 'all';
    if (btn) btn.disabled = true;
    if (statusLine) statusLine.textContent = 'Formatting PDF and sending…';
    try {
      const data = await api(path, { method: 'POST', body: JSON.stringify(body) });
      const n = data.count || 1;
      const sent = (data.to || []).join(', ');
      if (statusLine) statusLine.textContent = `Sent ${n} file${n === 1 ? '' : 's'} to ${sent}.`;
      if (el('templatesStatus')) el('templatesStatus').textContent = `Mailed ${n} file${n === 1 ? '' : 's'} to ${sent}.`;
      window.setTimeout(() => closeTemplateMailDialog(), 900);
    } catch (err) {
      if (statusLine) statusLine.textContent = err.message || 'Mail failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function downloadTemplate(id) {
    const doc = await resolveTemplateDoc(id);
    if (!doc?.id) throw new Error('Template not found');
    const urls = templateFileUrls(doc);
    if (!urls.downloadUrl) throw new Error('Template file is missing');
    const filename = urls.filename || 'template';
    // Force a save for HTML/static pads (same-origin navigation would just open the page).
    if (doc.docType === 'static' || /html/i.test(urls.mime || '') || /\.html?$/i.test(filename)) {
      const res = await fetch(urls.downloadUrl, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Download failed');
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = filename.endsWith('.html') || filename.endsWith('.htm')
        ? filename
        : `${filename.replace(/\.[^.]+$/, '') || 'template'}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
      return;
    }
    const a = document.createElement('a');
    a.href = urls.downloadUrl;
    a.download = filename;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function saveTemplate(event) {
    event.preventDefault();
    if (!hasEntitlement('manage_templates')) return;
    const statusLine = el('templatesStatus');
    const saveBtn = el('templatesSaveBtn');
    const title = String(el('templatesTitleInput')?.value || '').trim();
    if (!title) {
      if (statusLine) statusLine.textContent = 'Title required.';
      return;
    }
    const editId = String(el('templatesEditId')?.value || '').trim();
    const file = el('templatesFileInput')?.files?.[0];
    if (!editId && !file) {
      if (statusLine) statusLine.textContent = 'Choose a file to upload.';
      return;
    }
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    const options = readTemplateOptionsFromForm();
    try {
      let doc;
      if (file) {
        const body = new FormData();
        body.append('file', file);
        body.append('title', title);
        body.append('description', el('templatesDescInput')?.value.trim() || '');
        body.append('category', el('templatesCategoryInput')?.value || 'other');
        body.append('tags', el('templatesTagsInput')?.value.trim() || '');
        body.append('status', el('templatesStatusInput')?.value || 'published');
        body.append('options', JSON.stringify(options));
        if (editId) body.append('id', editId);
        const headers = {};
        if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
        const path = editId
          ? `/api/rwa/templates/${encodeURIComponent(editId)}`
          : '/api/rwa/templates';
        const res = await fetch(path, {
          method: editId ? 'PATCH' : 'POST',
          credentials: 'same-origin',
          headers,
          body,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
        doc = data.template;
      } else {
        const payload = {
          title,
          description: el('templatesDescInput')?.value.trim() || '',
          category: el('templatesCategoryInput')?.value || 'other',
          tags: el('templatesTagsInput')?.value.trim() || '',
          status: el('templatesStatusInput')?.value || 'published',
          options,
        };
        doc = (await api(`/api/rwa/templates/${encodeURIComponent(editId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })).template;
      }
      resetTemplatesForm();
      await loadTemplates();
      if (statusLine) statusLine.textContent = `Saved “${doc?.title || title}”.`;
    } catch (e) {
      if (statusLine) statusLine.textContent = e.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function deleteTemplate(id) {
    const doc = templatesCache.find((t) => t.id === id);
    if (!doc) return;
    const label = doc.title || id;
    if (!window.confirm(`Delete template “${label}”?${doc.docType === 'static' ? ' (Site file stays on disk; only the catalog entry is removed.)' : ''}`)) {
      return;
    }
    await api(`/api/rwa/templates/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (el('templatesEditId')?.value === id) resetTemplatesForm();
    await loadTemplates();
    if (el('templatesStatus')) el('templatesStatus').textContent = `Deleted “${label}”.`;
  }

  async function initReportsForm() {
    if (!el('reportForm') || !hasEntitlement('generate_reports')) return;
    try {
      reportMeta = await api('/api/rwa/reports/meta');
    } catch (_e) {
      reportMeta = { reports: [{ id: 'pending-dues', title: 'Pending Dues Report', kind: 'builtin', fields: [] }], datasets: {} };
    }
    const select = el('reportTypeSelect');
    if (select) {
      select.innerHTML = (reportMeta.reports || []).map((r) =>
        `<option value="${escapeHtml(r.id)}">${escapeHtml(r.title)}</option>`
      ).join('');
    }
    const dsSelect = el('reportDatasetSelect');
    if (dsSelect && reportMeta.datasets) {
      const preferred = ['dues', 'payments', 'cash', 'directory', 'concerns', 'passes', 'tenants', 'vehicles', 'works', 'notices', 'no_dues', 'reimbursements', 'transactions'];
      const ids = Object.keys(reportMeta.datasets);
      ids.sort((a, b) => {
        const ia = preferred.indexOf(a);
        const ib = preferred.indexOf(b);
        return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib) || a.localeCompare(b);
      });
      const prev = dsSelect.value;
      dsSelect.innerHTML = ids.map((id) => {
        const ds = reportMeta.datasets[id];
        return `<option value="${escapeHtml(id)}">${escapeHtml(ds.title || id)}</option>`;
      }).join('');
      if (prev && reportMeta.datasets[prev]) dsSelect.value = prev;
    }
    syncReportUi();
  }

  function buildReportPayload() {
    const def = currentReportDef();
    const reportId = def?.id || 'pending-dues';
    const isCustom = def?.kind === 'custom' || reportId === 'custom';
    const isTemplate = def?.kind === 'template';
    const dataset = isCustom || isTemplate
      ? (el('reportDatasetSelect')?.value || def?.dataset || 'dues')
      : (def?.dataset || 'dues');
    const plotsRaw = (el('reportPlots')?.value || '').trim();
    const houseIds = plotsRaw ? plotsRaw.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean) : [];
    const filters = {
      section: el('reportSection')?.value || 'all',
      search: (el('reportSearch')?.value || '').trim(),
      houseIds,
      pendingOnly: Boolean(el('reportPendingOnly')?.checked),
      status: el('reportConcernStatus')?.value || 'open',
      kind: 'all',
    };
    if (dataset === 'passes') {
      filters.kind = el('reportPassKind')?.value || 'all';
      filters.status = el('reportPassStatus')?.value || 'all';
    } else if (dataset === 'vehicles') {
      filters.status = el('reportPassStatus')?.value || 'all';
    } else if (dataset === 'tenants') {
      filters.status = el('reportTenantStatus')?.value || 'active';
    } else if (dataset === 'concerns') {
      filters.status = el('reportConcernStatus')?.value || 'open';
    }
    const customColumns = reportCustomColumnLabels().map((label) => ({ label }));
    if (customColumns.length) filters.customColumns = customColumns;
    const style = reportStyleOptions();
    filters.style = style;
    return {
      reportId,
      dataset,
      fields: selectedReportFieldIds(),
      filters,
      style,
      title: def?.title || undefined,
    };
  }

  async function downloadReportPdf(payload) {
    const headers = { 'Content-Type': 'application/json' };
    if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
    const res = await fetch('/api/rwa/reports/generate', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body: JSON.stringify(payload),
    });
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok) {
      const data = ctype.includes('json') ? await res.json().catch(() => ({})) : {};
      throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const stamp = todayIstDate().replace(/-/g, '');
    a.href = url;
    a.download = `report-${stamp}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  el('reportTypeSelect')?.addEventListener('change', () => syncReportUi());
  el('reportDatasetSelect')?.addEventListener('change', () => syncReportUi());
  el('reportDefaultsBtn')?.addEventListener('click', () => {
    const def = currentReportDef();
    const dataset = el('reportDatasetSelect')?.value || def?.dataset || 'dues';
    const fields = def?.kind === 'custom'
      ? (reportMeta.datasets?.[dataset]?.fields || [])
      : (def?.fields || []);
    renderReportFields(fields, fields.filter((f) => f.default).map((f) => f.id));
    setReportCustomColumnLabels([]);
    setReportStyleOptions({ fontSize: 12, color: 'black', contrast: 'hard' });
    if (el('reportStatus')) el('reportStatus').textContent = 'Columns reset to defaults.';
  });

  el('reportForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('reportStatus');
    const btn = el('reportDownloadBtn');
    if (status) status.textContent = 'Generating PDF…';
    if (btn) btn.disabled = true;
    try {
      await downloadReportPdf(buildReportPayload());
      if (status) status.textContent = 'PDF downloaded.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Report failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('reportSaveTemplateBtn')?.addEventListener('click', async () => {
    const status = el('reportStatus');
    const name = (el('reportTemplateName')?.value || '').trim();
    if (!name) {
      if (status) status.textContent = 'Enter a template name to save.';
      return;
    }
    const payload = buildReportPayload();
    const def = currentReportDef();
    const body = {
      name,
      dataset: payload.dataset,
      fields: payload.fields,
      filters: payload.filters,
    };
    if (def?.kind === 'template' && def.templateId) body.id = def.templateId;
    try {
      await api('/api/rwa/reports/templates', { method: 'POST', body: JSON.stringify(body) });
      if (status) status.textContent = 'Template saved.';
      await initReportsForm();
      if (el('reportTypeSelect') && body.id) {
        el('reportTypeSelect').value = `template:${body.id}`;
      } else {
        // select newest matching name
        const opt = Array.from(el('reportTypeSelect')?.options || []).find((o) => o.textContent === name);
        if (opt) el('reportTypeSelect').value = opt.value;
      }
      syncReportUi();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not save template';
    }
  });

  el('reportDeleteTemplateBtn')?.addEventListener('click', async () => {
    const def = currentReportDef();
    if (def?.kind !== 'template' || !def.templateId) return;
    if (!window.confirm(`Delete template “${def.title}”?`)) return;
    try {
      await api(`/api/rwa/reports/templates/${encodeURIComponent(def.templateId)}`, { method: 'DELETE', body: '{}' });
      if (el('reportStatus')) el('reportStatus').textContent = 'Template deleted.';
      await initReportsForm();
    } catch (err) {
      if (el('reportStatus')) el('reportStatus').textContent = err.message || 'Delete failed';
    }
  });

  let entitlementCatalog = [];

  async function loadEcCharterPanel() {
    const box = el('ecCharterList');
    if (!box) return;
    if (!(hasEntitlement('manage_roles') || hasEntitlement('sensitive_ops'))) return;
    try {
      const data = await api('/api/rwa/ec/charter');
      const members = data.members || [];
      const plotList = el('ecCharterPlotList');
      if (plotList) {
        const dir = await api('/api/rwa/directory').catch(() => ({ residents: [] }));
        plotList.innerHTML = (dir.residents || []).map((r) =>
          `<option value="${escapeHtml(r.houseId)}">${escapeHtml(r.houseId)} — ${escapeHtml(r.ownerName || r.name || '')}</option>`
        ).join('');
      }
      if (!members.length) {
        box.innerHTML = '<p class="muted">No EC charter members yet. Add a plot with an eligible seat holder above.</p>';
      } else {
        box.innerHTML = members.map((m) => {
          const roleBits = [
            m.isEcAdmin ? 'EC Admin' : null,
            m.isOfficeBearer ? 'Office Bearer' : null,
            m.isEcMember ? 'EC Member' : null,
          ].filter(Boolean).join(' · ');
          const seatOpts = (m.eligibleMembers || []).map((p) =>
            `<option value="${escapeHtml(p.id)}" ${p.id === m.ecMemberId ? 'selected' : ''}>${escapeHtml(p.name)} (${escapeHtml(p.identityLabel || p.relationLabel || '')})</option>`
          ).join('');
          return `<div class="roles-member-card" data-house="${escapeHtml(m.houseId)}">
            <div class="roles-member-head">
              ${personAvatarHtml(m, { size: 'md' })}
              <div class="roles-member-text">
                <strong>${escapeHtml(m.plotNo)}</strong> · ${escapeHtml(m.displayName || m.name)}
                <span class="muted">${escapeHtml(m.officialTitle || '')}${m.officialTitle ? ' · ' : ''}${escapeHtml(roleBits)}</span>
                <span class="muted">Seat: ${escapeHtml(m.ecSeatHolderName || '—')} (${escapeHtml(m.ecSeatHolderLabel || '—')})</span>
              </div>
            </div>
            <div class="settings-grid">
              <label>Seat holder
                <select class="ec-charter-seat" data-house="${escapeHtml(m.houseId)}">${seatOpts || '<option value="">No eligible people</option>'}</select>
              </label>
              <label>Official title
                <input class="ec-charter-title" data-house="${escapeHtml(m.houseId)}" value="${escapeHtml(m.officialTitle || '')}" maxlength="80">
              </label>
            </div>
            <div class="btn-row">
              <button type="button" class="btn secondary compact ec-charter-save" data-house="${escapeHtml(m.houseId)}">Update seat / title</button>
              ${m.isEcAdmin
                ? `<button type="button" class="btn ghost compact ec-charter-demote" data-house="${escapeHtml(m.houseId)}">Demote Admin</button>`
                : `<button type="button" class="btn ghost compact ec-charter-elevate" data-house="${escapeHtml(m.houseId)}">Elevate Admin</button>`}
              <button type="button" class="btn ghost compact ec-charter-remove" data-house="${escapeHtml(m.houseId)}">Remove from EC</button>
            </div>
          </div>`;
        }).join('');
        await hydrateAvatars(box);
      }
      if (el('ecCharterStatus')) el('ecCharterStatus').textContent = `${members.length} charter seat(s)`;
    } catch (err) {
      box.innerHTML = `<p class="error">${escapeHtml(err.message || 'Failed to load charter')}</p>`;
    }
  }

  async function loadEcCharterEligible(houseId) {
    const seat = el('ecCharterSeat');
    if (!seat || !houseId) return;
    seat.innerHTML = '<option value="">Loading…</option>';
    try {
      const data = await api(`/api/rwa/ec/eligible/${encodeURIComponent(houseId)}`);
      const members = data.members || [];
      if (!members.length) {
        seat.innerHTML = '<option value="">No owner / primary delegate on this plot</option>';
        return;
      }
      seat.innerHTML = members.map((m) =>
        `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name)} (${escapeHtml(m.identityLabel || '')})</option>`
      ).join('');
    } catch (err) {
      seat.innerHTML = `<option value="">${escapeHtml(err.message || 'Failed')}</option>`;
    }
  }

  el('ecCharterRefreshBtn')?.addEventListener('click', () => loadEcCharterPanel().catch(console.error));
  el('ecCharterLoadEligibleBtn')?.addEventListener('click', () => {
    const plot = (el('ecCharterPlot')?.value || '').trim();
    loadEcCharterEligible(plot).catch(console.error);
  });
  el('ecCharterPlot')?.addEventListener('change', () => {
    const plot = (el('ecCharterPlot')?.value || '').trim();
    loadEcCharterEligible(plot).catch(console.error);
  });
  el('ecCharterForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('ecCharterStatus');
    const plot = (el('ecCharterPlot')?.value || '').trim();
    const seatId = (el('ecCharterSeat')?.value || '').trim();
    const title = (el('ecCharterTitle')?.value || '').trim();
    const role = (el('ecCharterRole')?.value || 'member').trim();
    if (!plot || !seatId) {
      if (status) status.textContent = 'Plot and seat holder are required.';
      return;
    }
    const body = {
      houseId: plot,
      ecMemberId: seatId,
      isEcMember: true,
    };
    if (role === 'bearer' || role === 'admin') {
      if (!title) {
        if (status) status.textContent = 'Official title is required for office bearers / EC Admin.';
        return;
      }
      body.isOfficeBearer = true;
      body.officialTitle = title;
    } else if (title) {
      body.officialTitle = title;
      body.isOfficeBearer = true;
    }
    if (role === 'admin') body.role = 'admin';
    try {
      await api('/api/rwa/ec/charter', { method: 'PATCH', body: JSON.stringify(body) });
      if (status) status.textContent = `Saved ${plot} on the charter.`;
      el('ecCharterForm')?.reset();
      if (el('ecCharterSeat')) el('ecCharterSeat').innerHTML = '<option value="">Select plot first…</option>';
      await loadEcCharterPanel();
      if (hasEntitlement('sensitive_ops')) await loadRolesPanel().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Save failed';
    }
  });

  el('ecCharterList')?.addEventListener('click', async (event) => {
    const save = event.target.closest('.ec-charter-save');
    const elevate = event.target.closest('.ec-charter-elevate');
    const demote = event.target.closest('.ec-charter-demote');
    const remove = event.target.closest('.ec-charter-remove');
    const btn = save || elevate || demote || remove;
    if (!btn) return;
    const house = btn.getAttribute('data-house');
    if (!house) return;
    const card = btn.closest('.roles-member-card');
    const status = el('ecCharterStatus');
    try {
      if (remove) {
        if (!window.confirm(`Remove plot ${house} from the EC charter?`)) return;
        await api('/api/rwa/ec/charter', {
          method: 'PATCH',
          body: JSON.stringify({ houseId: house, remove: true }),
        });
      } else if (elevate) {
        await api('/api/rwa/ec/charter', {
          method: 'PATCH',
          body: JSON.stringify({ houseId: house, role: 'admin', isEcMember: true, isOfficeBearer: true }),
        });
      } else if (demote) {
        await api('/api/rwa/ec/charter', {
          method: 'PATCH',
          body: JSON.stringify({ houseId: house, role: 'resident', isEcMember: true, isOfficeBearer: true }),
        });
      } else if (save) {
        const seat = card?.querySelector('.ec-charter-seat')?.value || '';
        const title = card?.querySelector('.ec-charter-title')?.value || '';
        await api('/api/rwa/ec/charter', {
          method: 'PATCH',
          body: JSON.stringify({
            houseId: house,
            ecMemberId: seat,
            officialTitle: title,
            isEcMember: true,
            isOfficeBearer: Boolean(title),
          }),
        });
      }
      if (status) status.textContent = 'Charter updated.';
      await loadEcCharterPanel();
      if (hasEntitlement('sensitive_ops')) await loadRolesPanel().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Update failed';
    }
  });

  async function loadRolesPanel() {
    const box = el('rolesMembersList');
    if (!box || !hasEntitlement('sensitive_ops')) return;
    try {
      const [meta, data] = await Promise.all([
        api('/api/rwa/entitlements/meta'),
        api('/api/rwa/roles'),
      ]);
      entitlementCatalog = (meta.grantable || []).map((id) => {
        const def = (meta.entitlements || []).find((e) => e.id === id);
        return def || { id, label: id };
      });
      const explicitIds = new Set(meta.explicit || ['issue_no_dues']);
      const members = data.members || [];
      if (!members.length) {
        box.innerHTML = '<p class="muted">No EC members yet. Add an EC Member or designate an Office Bearer above.</p>';
        return;
      }
      box.innerHTML = members.map((m) => {
        const grants = new Set(m.entitlements || []);
        const roleBits = [
          m.isEcAdmin ? 'EC Admin' : null,
          m.isOfficeBearer ? 'Office Bearer' : null,
          m.isEcMember ? 'EC Member' : null,
        ].filter(Boolean);
        const canGrant = m.isEcMember && !m.isEcAdmin;
        const canElevate = m.isOfficeBearer && !m.isEcAdmin;
        const checks = entitlementCatalog.map((e) => {
          const isExplicit = explicitIds.has(e.id);
          const disabled = m.isEcAdmin && !isExplicit ? ' disabled' : '';
          const checked = (m.isEcAdmin && !isExplicit) || grants.has(e.id) ? ' checked' : '';
          return `<label class="check"><input type="checkbox" data-ent="${escapeHtml(e.id)}"${checked}${disabled}> <span>${escapeHtml(e.label)}</span></label>`;
        }).join('');
        return `<div class="roles-member-card" data-house="${escapeHtml(m.houseId)}">
          <div class="roles-member-head">
            ${personAvatarHtml(m, { size: 'md' })}
            <div class="roles-member-text">
              <strong>${escapeHtml(m.plotNo)}</strong> · ${escapeHtml(m.name)}
              <span class="muted">${escapeHtml(m.officialTitle || '')}${m.officialTitle ? ' · ' : ''}${escapeHtml(roleBits.join(' · '))}</span>
            </div>
          </div>
          <div class="report-field-grid">${checks}</div>
          <div class="btn-row">
            ${m.isEcAdmin
              ? `<button type="button" class="btn ghost compact roles-demote" data-house="${escapeHtml(m.houseId)}">Demote from EC Admin</button>`
              : `${canElevate ? `<button type="button" class="btn secondary compact roles-elevate" data-house="${escapeHtml(m.houseId)}">Elevate to EC Admin</button>` : ''}
                 ${!m.isOfficeBearer ? `<button type="button" class="btn ghost compact roles-make-ob" data-house="${escapeHtml(m.houseId)}">Make Office Bearer</button>` : ''}`}
            <button type="button" class="btn ghost compact roles-save-grants" data-house="${escapeHtml(m.houseId)}">Save entitlements</button>
            <button type="button" class="btn ghost compact roles-remove-member" data-house="${escapeHtml(m.houseId)}">Remove from EC</button>
          </div>
        </div>`;
      }).join('');
      await hydrateAvatars(box);
      if (el('rolesStatus')) el('rolesStatus').textContent = `${members.length} EC member(s)`;
    } catch (err) {
      box.innerHTML = `<p class="error">${escapeHtml(err.message || 'Failed to load roles')}</p>`;
    }
  }

  el('rolesRefreshBtn')?.addEventListener('click', () => loadRolesPanel().catch(console.error));
  el('rolesDesignateMemberBtn')?.addEventListener('click', async () => {
    const plot = (el('rolesDesignatePlot')?.value || '').trim();
    const status = el('rolesStatus');
    if (!plot) {
      if (status) status.textContent = 'Plot is required.';
      return;
    }
    try {
      await api(`/api/rwa/residents/${encodeURIComponent(plot)}`, {
        method: 'PATCH',
        body: JSON.stringify({ isEcMember: true }),
      });
      if (status) status.textContent = `Added ${plot} as EC Member.`;
      el('rolesDesignatePlot').value = '';
      await loadRolesPanel();
      if (hasEntitlement('manage_roster')) await loadRoster().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Add member failed';
    }
  });
  el('rolesDesignateBtn')?.addEventListener('click', async () => {
    const plot = (el('rolesDesignatePlot')?.value || '').trim();
    const title = (el('rolesDesignateTitle')?.value || '').trim();
    const status = el('rolesStatus');
    if (!plot || !title) {
      if (status) status.textContent = 'Plot and official title are required for office bearers.';
      return;
    }
    try {
      await api(`/api/rwa/residents/${encodeURIComponent(plot)}`, {
        method: 'PATCH',
        body: JSON.stringify({ isEcMember: true, isOfficeBearer: true, officialTitle: title }),
      });
      if (status) status.textContent = `Designated ${plot} as office bearer.`;
      el('rolesDesignatePlot').value = '';
      el('rolesDesignateTitle').value = '';
      await loadRolesPanel();
      if (hasEntitlement('manage_roster')) await loadRoster().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Designate failed';
    }
  });

  el('rolesMembersList')?.addEventListener('click', async (event) => {
    const elevate = event.target.closest('.roles-elevate');
    const demote = event.target.closest('.roles-demote');
    const save = event.target.closest('.roles-save-grants');
    const remove = event.target.closest('.roles-remove-member');
    const makeOb = event.target.closest('.roles-make-ob');
    const status = el('rolesStatus');
    const btn = elevate || demote || save || remove || makeOb;
    if (!btn) return;
    const houseId = btn.getAttribute('data-house');
    const card = btn.closest('.roles-member-card');
    try {
      if (elevate) {
        await api(`/api/rwa/residents/${encodeURIComponent(houseId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ role: 'admin', isOfficeBearer: true, isEcMember: true }),
        });
        if (status) status.textContent = `Elevated ${houseId} to EC Admin.`;
      } else if (demote) {
        if (!window.confirm(`Demote plot ${houseId} from EC Admin? They remain an office bearer / EC member.`)) return;
        await api(`/api/rwa/residents/${encodeURIComponent(houseId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ role: 'resident', isOfficeBearer: true, isEcMember: true }),
        });
        if (status) status.textContent = `Demoted ${houseId}.`;
      } else if (makeOb) {
        const title = window.prompt(`Official title for plot ${houseId}?`, '') || '';
        if (!title.trim()) {
          if (status) status.textContent = 'Official title required.';
          return;
        }
        await api(`/api/rwa/residents/${encodeURIComponent(houseId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ isEcMember: true, isOfficeBearer: true, officialTitle: title.trim() }),
        });
        if (status) status.textContent = `Made ${houseId} an office bearer.`;
      } else if (save) {
        const ents = Array.from(card.querySelectorAll('input[data-ent]:checked')).map((i) => i.getAttribute('data-ent'));
        await api(`/api/rwa/residents/${encodeURIComponent(houseId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ entitlements: ents, isEcMember: true }),
        });
        if (status) status.textContent = `Saved entitlements for ${houseId}.`;
      } else if (remove) {
        if (!window.confirm(`Remove ${houseId} from EC (member / bearer / admin)?`)) return;
        await api(`/api/rwa/residents/${encodeURIComponent(houseId)}`, {
          method: 'PATCH',
          body: JSON.stringify({ isEcMember: false, isOfficeBearer: false, role: 'resident' }),
        });
        if (status) status.textContent = `Removed ${houseId} from EC.`;
      }
      await loadRolesPanel();
      if (hasEntitlement('manage_roster')) await loadRoster().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Update failed';
    }
  });

  el('ledgerImportForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('ledgerImportStatus');
    const fileInput = event.currentTarget.querySelector('input[type="file"]');
    if (!fileInput?.files?.length) return;
    if (!window.confirm('Import this ledger PDF? This refreshes dues for the whole colony.')) return;
    status.textContent = 'Importing…';
    try {
      const body = new FormData();
      body.append('file', fileInput.files[0]);
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const res = await fetch('/api/rwa/ledger/import', {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      status.textContent = `Imported ${data.rows || data.residents || 0} rows (ledger ${data.ledgerId || ''}).`;
      await loadRoster().catch(() => {});
    } catch (err) {
      status.textContent = err.message || 'Import failed';
    }
  });

  function renderRosterStats(stats) {
    const line = el('rosterStats');
    if (!line || !stats) return;
    line.textContent = `${stats.total} plots · ${stats.withPhone} with phone · ${stats.missingPhone} missing · ${stats.withEmail} with email`;
  }

  function rosterMatches(r, q, missingOnly) {
    if (missingOnly && r.phone) return false;
    if (!q) return true;
    const hay = `${r.houseId} ${r.plotNo} ${r.householdCode || ''} ${r.title || ''} ${r.name} ${r.profession || ''} ${r.phone || ''} ${r.email || ''} ${r.officialTitle || ''} ${r.role} ${committeeRoleLabel(r)}`.toLowerCase();
    return hay.includes(q);
  }

  function renderRosterRows() {
    const tbody = el('rosterRows');
    if (!tbody) return;
    const q = (el('rosterSearch')?.value || '').trim().toLowerCase();
    const missingOnly = Boolean(el('rosterMissingPhone')?.checked);
    const rows = rosterCache.filter((r) => rosterMatches(r, q, missingOnly));
    const superOnly = isSuperAdmin();
    if (!rows.length) {
      tbody.innerHTML = '<tr class="is-empty-row"><td colspan="13" class="muted">No matching residents.</td></tr>';
      refreshMobileListUi();
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const roleDisabled = superOnly ? '' : ' disabled';
      const statusDisabled = (superOnly || r.role !== 'admin') ? '' : ' disabled';
      const statusNote = (!superOnly && r.role === 'admin') ? ' title="Only super admin can suspend EC admins"' : '';
      const roleLabel = committeeRoleLabel(r);
      const residentOptionLabel = r.role === 'admin'
        ? 'Resident'
        : (r.isOfficeBearer ? 'Office Bearer' : (r.isEcMember ? 'EC Member' : 'Resident'));
      const masterName = (r.ownerName || r.name || '').trim();
      return `
      <tr data-house="${escapeHtml(r.houseId)}" class="${r.phone ? '' : 'is-missing-phone'}">
        <td class="plot-cell" data-label="Plot"><span class="person-cell">${personAvatarHtml(r)}<span><code>${escapeHtml(r.houseId)}</code><div class="muted plot-section">${escapeHtml(r.section || '')}</div></span></span></td>
        <td data-label="HH code"><code class="hh-code">${escapeHtml(r.householdCode || '—')}</code></td>
        <td data-label="Title"><input name="title" value="${escapeHtml(r.title || '')}" placeholder="Mr/Mrs/Dr" aria-label="Title ${escapeHtml(r.houseId)}"></td>
        <td data-label="Name"><input name="name" value="${escapeHtml(masterName)}" aria-label="Name ${escapeHtml(r.houseId)}"></td>
        <td data-label="Profession"><input name="profession" value="${escapeHtml(r.profession || '')}" placeholder="Profession" aria-label="Profession ${escapeHtml(r.houseId)}"></td>
        <td data-label="Job">
          <select name="employmentStatus" aria-label="Employment ${escapeHtml(r.houseId)}">
            <option value="unknown"${(r.employmentStatus || 'unknown') === 'unknown' ? ' selected' : ''}>—</option>
            <option value="working"${r.employmentStatus === 'working' ? ' selected' : ''}>Working</option>
            <option value="retired"${r.employmentStatus === 'retired' ? ' selected' : ''}>Retired</option>
          </select>
        </td>
        <td data-label="Phone"><input name="phone" type="tel" inputmode="tel" placeholder="mobile" value="${escapeHtml(r.phone || '')}" aria-label="Phone ${escapeHtml(r.houseId)}"></td>
        <td data-label="Email"><input name="email" type="email" placeholder="email" value="${escapeHtml(r.email || '')}" aria-label="Email ${escapeHtml(r.houseId)}"></td>
        <td data-label="EC title"><input name="officialTitle" value="${escapeHtml(r.officialTitle || '')}" placeholder="EC title" aria-label="Official title ${escapeHtml(r.houseId)}"></td>
        <td data-label="Notes"><input name="notes" value="${escapeHtml(r.notes || '')}" placeholder="e.g. EC: Father Full Name" aria-label="Notes ${escapeHtml(r.houseId)}"></td>
        <td data-label="Role">
          <select name="role" aria-label="Role ${escapeHtml(r.houseId)}"${roleDisabled} title="${escapeHtml(roleLabel)}">
            <option value="resident"${r.role !== 'admin' ? ' selected' : ''}>${escapeHtml(residentOptionLabel)}</option>
            <option value="admin"${r.role === 'admin' ? ' selected' : ''}>EC Admin</option>
          </select>
        </td>
        <td data-label="Status">
          <select name="status" aria-label="Status ${escapeHtml(r.houseId)}"${statusDisabled}${statusNote}>
            <option value="active"${(r.status || 'active') === 'active' ? ' selected' : ''}>Active</option>
            <option value="inactive"${r.status === 'inactive' ? ' selected' : ''}>Suspended</option>
          </select>
        </td>
        <td data-label="Actions" class="row-actions">
          <button type="button" class="btn secondary compact roster-save" data-house="${escapeHtml(r.houseId)}">Save</button>
          <div class="row-status"></div>
        </td>
      </tr>`;
    }).join('');
    refreshMobileListUi();
    hydrateAvatars(tbody).catch(() => {});
  }

  async function loadRoster() {
    if (!hasEntitlement('manage_roster') && !hasEntitlement('sensitive_ops') && !isEcAdmin()) return;
    const data = await api('/api/rwa/residents');
    rosterCache = data.residents || [];
    renderRosterStats(data.stats);
    renderRosterRows();
    populateEcDelegateHouseListFromCache();
    if (el('rosterStatus')) el('rosterStatus').textContent = isSuperAdmin()
      ? 'Super admin: you can assign, remove, or suspend EC admins.'
      : 'EC: edit resident details. Role / EC suspend requires Super admin.';
  }

  function populateEcDelegateHouseListFromCache() {
    const list = el('ecDelegateHouseList');
    if (!list) return;
    const rows = rosterCache.length
      ? rosterCache
      : [];
    list.innerHTML = rows.map((r) =>
      `<option value="${escapeHtml(r.houseId)}">${escapeHtml(r.houseId)} — ${escapeHtml(r.name || '')}</option>`
    ).join('');
  }

  async function populateEcDelegateHouseList() {
    if (!isEcAdmin()) return;
    if (rosterCache.length) {
      populateEcDelegateHouseListFromCache();
      return;
    }
    try {
      const data = await api('/api/rwa/directory');
      const list = el('ecDelegateHouseList');
      if (!list) return;
      list.innerHTML = (data.residents || []).map((r) =>
        `<option value="${escapeHtml(r.houseId)}">${escapeHtml(r.houseId)} — ${escapeHtml(r.name || '')}</option>`
      ).join('');
    } catch (_) { /* ignore */ }
  }

  function ecDelegateHouseId() {
    return (el('ecDelegateHouse')?.value || '').trim();
  }

  function renderEcDelegateMembers(data) {
    const list = el('ecDelegateMemberList');
    if (!list) return;
    const canManage = Boolean(data?.canManage);
    const houseLabel = data?.houseId || ecDelegateHouseId();
    const ownerName = data?.householdName ? ` · ${data.householdName}` : '';
    list.innerHTML = `
      <p class="muted">Household for <code>${escapeHtml(houseLabel)}</code>${escapeHtml(ownerName)}</p>
      ${(data.members || []).map((m) => {
        const badges = [
          m.isPrimary ? 'Owner' : (m.isPrimaryDelegate ? 'Primary delegate' : (m.relationLabel || m.relation)),
          m.viewOnly ? 'View only' : null,
        ].filter(Boolean).join(' · ');
        const actions = canManage && !m.isPrimary ? `
          <div class="btn-row">
            <label class="check compact"><input type="checkbox" class="ec-hh-primary-delegate" data-id="${escapeHtml(m.id)}" ${m.isPrimaryDelegate ? 'checked' : ''}> Primary delegate</label>
            <label class="check compact"><input type="checkbox" class="ec-hh-view-only" data-id="${escapeHtml(m.id)}" ${m.viewOnly ? 'checked' : ''} ${m.isPrimaryDelegate ? 'disabled' : ''}> View only</label>
            <button type="button" class="btn ghost compact ec-hh-remove" data-id="${escapeHtml(m.id)}">Remove</button>
          </div>` : (m.isPrimary ? '<p class="muted">Plot owner</p>' : '');
        return `
          <article class="household-member-card" data-id="${escapeHtml(m.id)}">
            ${hhAvatarHtml(m)}
            <strong>${escapeHtml(m.name)}</strong>
            <span class="muted">${escapeHtml(badges)}</span>
            ${actions}
          </article>`;
      }).join('') || '<p class="muted">No household members yet.</p>'}`;
    hydrateAvatars(list).catch(() => {});
  }

  async function loadEcDelegateHousehold() {
    const hid = ecDelegateHouseId();
    const status = el('ecDelegateStatus');
    const list = el('ecDelegateMemberList');
    if (!hid) {
      if (list) list.innerHTML = '';
      return;
    }
    if (status) status.textContent = 'Loading household…';
    try {
      const data = await api(`/api/rwa/household/${encodeURIComponent(hid)}/members`);
      data.houseId = hid;
      renderEcDelegateMembers(data);
      if (status) status.textContent = '';
    } catch (err) {
      if (list) list.innerHTML = `<p class="error">${escapeHtml(err.message || 'Could not load household')}</p>`;
      if (status) status.textContent = err.message || 'Could not load household';
    }
  }

  el('ecDelegateLoadBtn')?.addEventListener('click', () => {
    loadEcDelegateHousehold().catch(console.error);
  });

  el('ecDelegateHouse')?.addEventListener('change', () => {
    loadEcDelegateHousehold().catch(console.error);
  });

  el('ecDelegateForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!isEcAdmin()) return;
    const hid = ecDelegateHouseId();
    const status = el('ecDelegateStatus');
    const name = (el('ecDelegateName')?.value || '').trim();
    if (!hid || !name) return;
    if (status) status.textContent = 'Adding…';
    try {
      await api(`/api/rwa/household/${encodeURIComponent(hid)}/members`, {
        method: 'POST',
        body: JSON.stringify({
          name,
          relation: el('ecDelegateRelation')?.value || 'other',
          viewOnly: Boolean(el('ecDelegateViewOnly')?.checked),
          isPrimaryDelegate: Boolean(el('ecDelegatePrimary')?.checked),
        }),
      });
      if (el('ecDelegateName')) el('ecDelegateName').value = '';
      if (el('ecDelegateViewOnly')) el('ecDelegateViewOnly').checked = false;
      if (el('ecDelegatePrimary')) el('ecDelegatePrimary').checked = false;
      if (status) status.textContent = `Delegate added for ${hid}.`;
      await loadEcDelegateHousehold();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not add delegate';
    }
  });

  el('ecDelegateMemberList')?.addEventListener('change', async (event) => {
    const primaryDel = event.target.closest('.ec-hh-primary-delegate');
    const box = event.target.closest('.ec-hh-view-only');
    const hid = ecDelegateHouseId();
    if (primaryDel) {
      const id = primaryDel.getAttribute('data-id');
      if (!hid || !id) return;
      try {
        await api(`/api/rwa/household/${encodeURIComponent(hid)}/members/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ isPrimaryDelegate: primaryDel.checked }),
        });
        await loadEcDelegateHousehold();
      } catch (err) {
        alert(err.message || 'Could not update primary delegate');
        primaryDel.checked = !primaryDel.checked;
      }
      return;
    }
    if (!box) return;
    const id = box.getAttribute('data-id');
    if (!hid || !id) return;
    try {
      await api(`/api/rwa/household/${encodeURIComponent(hid)}/members/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ viewOnly: box.checked }),
      });
      await loadEcDelegateHousehold();
    } catch (err) {
      alert(err.message || 'Could not update access');
      box.checked = !box.checked;
    }
  });

  el('ecDelegateMemberList')?.addEventListener('click', async (event) => {
    const btn = event.target.closest('.ec-hh-remove');
    if (!btn) return;
    const hid = ecDelegateHouseId();
    const id = btn.getAttribute('data-id');
    if (!hid || !id) return;
    if (!window.confirm('Remove this household login?')) return;
    try {
      await api(`/api/rwa/household/${encodeURIComponent(hid)}/members/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        body: '{}',
      });
      await loadEcDelegateHousehold();
    } catch (err) {
      alert(err.message || 'Could not remove member');
    }
  });

  function residentApiId(houseId) {
    return encodeURIComponent(String(houseId || ''));
  }

  async function saveRosterRow(houseId, tr) {
    const status = tr.querySelector('.row-status');
    const btn = tr.querySelector('.roster-save');
    const payload = {
      title: tr.querySelector('input[name="title"]')?.value.trim() || '',
      name: tr.querySelector('input[name="name"]')?.value.trim() || '',
      profession: tr.querySelector('input[name="profession"]')?.value.trim() || '',
      employmentStatus: tr.querySelector('select[name="employmentStatus"]')?.value || 'unknown',
      phone: tr.querySelector('input[name="phone"]')?.value.trim() || '',
      email: tr.querySelector('input[name="email"]')?.value.trim() || '',
      officialTitle: tr.querySelector('input[name="officialTitle"]')?.value.trim() || '',
      notes: tr.querySelector('input[name="notes"]')?.value.trim() || '',
    };
    if (isSuperAdmin()) {
      payload.role = tr.querySelector('select[name="role"]')?.value || 'resident';
      payload.status = tr.querySelector('select[name="status"]')?.value || 'active';
    } else {
      const st = tr.querySelector('select[name="status"]');
      if (st && !st.disabled) payload.status = st.value;
    }
    if (status) status.textContent = 'Saving…';
    if (btn) btn.disabled = true;
    try {
      const data = await api(`/api/rwa/residents/${residentApiId(houseId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const updated = data.resident || {};
      const idx = rosterCache.findIndex((r) => r.houseId === houseId);
      if (idx >= 0) {
        rosterCache[idx] = { ...rosterCache[idx], ...updated, hasPhone: Boolean(updated.phone), hasEmail: Boolean(updated.email) };
      }
      renderRosterStats(data.stats);
      tr.classList.remove('is-dirty');
      tr.classList.toggle('is-missing-phone', !updated.phone);
      if (status) status.textContent = 'Saved';
      loadRevisions().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('rosterSearch')?.addEventListener('input', () => renderRosterRows());
  el('rosterMissingPhone')?.addEventListener('change', () => renderRosterRows());
  el('rosterRows')?.addEventListener('input', (event) => {
    const tr = event.target.closest('tr[data-house]');
    if (tr) tr.classList.add('is-dirty');
  });
  el('rosterRows')?.addEventListener('change', (event) => {
    const tr = event.target.closest('tr[data-house]');
    if (tr) tr.classList.add('is-dirty');
  });
  el('rosterRows')?.addEventListener('click', (event) => {
    const btn = event.target.closest('.roster-save');
    if (!btn) return;
    const houseId = btn.getAttribute('data-house');
    const tr = btn.closest('tr[data-house]');
    if (houseId && tr) saveRosterRow(houseId, tr);
  });
  el('rosterRows')?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const tr = event.target.closest('tr[data-house]');
    if (!tr) return;
    event.preventDefault();
    saveRosterRow(tr.getAttribute('data-house'), tr);
  });

  function fieldDiffSummary(rev) {
    const fields = rev.fields || [];
    if (!fields.length) return '—';
    return fields.map((f) => {
      const before = rev.before?.[f] ?? '';
      const after = rev.after?.[f] ?? '';
      return `${f}: “${before || '—'}” → “${after || '—'}”`;
    }).join('; ');
  }

  async function loadRevisions() {
    if (!hasEntitlement('sensitive_ops')) return;
    const houseId = (el('revisionHouseFilter')?.value || '').trim();
    const qs = houseId ? `?houseId=${encodeURIComponent(houseId)}&limit=80` : '?limit=80';
    const data = await api(`/api/rwa/residents/revisions${qs}`);
    const tbody = el('revisionRows');
    const rows = data.revisions || [];
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr class="is-empty-row"><td colspan="5" class="muted">No revisions yet.</td></tr>';
      if (el('revisionStatus')) el('revisionStatus').textContent = '';
      refreshMobileListUi();
      return;
    }
    tbody.innerHTML = rows.map((rev) => `
      <tr>
        <td data-label="When">${escapeHtml(formatIstDateTime(rev.changedAt))}</td>
        <td data-label="Plot"><code>${escapeHtml(rev.houseId)}</code></td>
        <td data-label="Changed by">${escapeHtml(rev.changedByName || rev.changedByHouseId || 'system')}<div class="muted plot-section">${escapeHtml(rev.source || '')}</div></td>
        <td data-label="Fields">${escapeHtml((rev.fields || []).join(', ') || '—')}</td>
        <td data-label="Summary" class="revision-summary muted">${escapeHtml(fieldDiffSummary(rev))}</td>
      </tr>`).join('');
    if (el('revisionStatus')) el('revisionStatus').textContent = `${rows.length} recent change(s)`;
    refreshMobileListUi();
  }

  el('revisionRefreshBtn')?.addEventListener('click', () => loadRevisions().catch(console.error));
  el('revisionHouseFilter')?.addEventListener('change', () => loadRevisions().catch(console.error));
  el('revisionHouseFilter')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      loadRevisions().catch(console.error);
    }
  });

  async function loadSmtpStatus() {
    const line = el('smtpStatusLine');
    if (!line || !canOpenEcDesk()) return;
    try {
      const data = await api('/api/rwa/smtp/status');
      line.textContent = data.configured
        ? `SMTP ready · ${data.provider} · from ${data.from}`
        : `SMTP not configured — set App Password in Platform settings (from ${data.from || 'housingcolonysanyard@gmail.com'})`;
    } catch (_e) {
      line.textContent = 'SMTP status unavailable';
    }
  }

  async function loadSettings() {
    if (!isSuperAdmin()) return;
    const data = await api('/api/rwa/settings');
    const s = data.settings || {};
    const smtp = s.smtp || {};
    if (el('settingsSmtpProvider')) el('settingsSmtpProvider').value = smtp.provider || 'gmail';
    if (el('settingsSmtpHost')) el('settingsSmtpHost').value = smtp.host || '';
    if (el('settingsSmtpPort')) el('settingsSmtpPort').value = smtp.port || 587;
    if (el('settingsSmtpUser')) el('settingsSmtpUser').value = smtp.user || '';
    if (el('settingsSmtpFrom')) el('settingsSmtpFrom').value = smtp.from || '';
    if (el('settingsSmtpPass')) el('settingsSmtpPass').placeholder = smtp.passwordSet ? '•••••••• (leave blank to keep)' : 'Gmail App Password';
    if (el('settingsOtpTtl')) el('settingsOtpTtl').value = s.otpTtl || 600;
    if (el('settingsSaUser')) el('settingsSaUser').value = s.superadminUser || 'admin';
    if (el('settingsInfoCentreProtect')) {
      el('settingsInfoCentreProtect').checked = Boolean(s.infoCentreProtect);
    }
    setInfoCentreProtectFeature(Boolean(s.infoCentreProtect));
    if (el('settingsStatus')) {
      el('settingsStatus').textContent = smtp.configured
        ? `Configured · file ${s.envFile || 'data/smtp.env'}`
        : `Not fully configured · edit and save (${s.envFile || 'data/smtp.env'})`;
    }
    fillOpsSettingsForm(s.ops || {});
    await loadOpsStatus().catch(() => {});
  }

  function fillOpsSettingsForm(ops = {}) {
    if (el('opsAlertTo')) el('opsAlertTo').value = ops.alertTo || '';
    if (el('opsVitalsEnabled')) el('opsVitalsEnabled').checked = ops.vitalsEnabled !== false;
    if (el('opsBackupRetainDays')) el('opsBackupRetainDays').value = ops.backupRetainDays ?? 3;
    if (el('opsBackupDiskMinPct')) el('opsBackupDiskMinPct').value = ops.backupDiskMinPct ?? 15;
    if (el('opsAccessEventsDays')) el('opsAccessEventsDays').value = ops.accessEventsDays ?? 90;
    if (el('opsDiskWarnPct')) el('opsDiskWarnPct').value = ops.diskWarnPct ?? 20;
    if (el('opsDiskCritPct')) el('opsDiskCritPct').value = ops.diskCritPct ?? 10;
    if (el('opsMemWarnPct')) el('opsMemWarnPct').value = ops.memWarnPct ?? 15;
    if (el('opsMemCritPct')) el('opsMemCritPct').value = ops.memCritPct ?? 8;
    if (el('opsLoadWarnRatio')) el('opsLoadWarnRatio').value = ops.loadWarnRatio ?? 1.5;
    if (el('opsLoadCritRatio')) el('opsLoadCritRatio').value = ops.loadCritRatio ?? 2.5;
    if (el('opsBackupMaxAgeHours')) el('opsBackupMaxAgeHours').value = ops.backupMaxAgeHours ?? 28;
    if (el('opsAlertCooldownWarnH')) el('opsAlertCooldownWarnH').value = ops.alertCooldownWarnHours ?? 6;
    if (el('opsAlertCooldownCritH')) el('opsAlertCooldownCritH').value = ops.alertCooldownCritHours ?? 1;
    if (el('opsDriveEnabled')) el('opsDriveEnabled').checked = Boolean(ops.driveEnabled);
    if (el('opsDriveFolderId')) el('opsDriveFolderId').value = ops.driveFolderId || '';
    if (el('opsDriveRetainDays')) el('opsDriveRetainDays').value = ops.driveRetainDays ?? 14;
    if (el('opsDriveSaHint')) {
      el('opsDriveSaHint').innerHTML = ops.driveSaConfigured
        ? 'Service account JSON found at <code>data/drive-sa.json</code>. Share the Drive folder with that SA email (Editor).'
        : 'Missing <code>data/drive-sa.json</code> on the server — upload the Google service-account key (chmod 600), then enable Drive.';
    }
  }

  function collectOpsSettingsPayload() {
    return {
      alertTo: el('opsAlertTo')?.value.trim() || '',
      vitalsEnabled: Boolean(el('opsVitalsEnabled')?.checked),
      backupRetainDays: Number(el('opsBackupRetainDays')?.value || 3),
      backupDiskMinPct: Number(el('opsBackupDiskMinPct')?.value || 15),
      accessEventsDays: Number(el('opsAccessEventsDays')?.value || 90),
      diskWarnPct: Number(el('opsDiskWarnPct')?.value || 20),
      diskCritPct: Number(el('opsDiskCritPct')?.value || 10),
      memWarnPct: Number(el('opsMemWarnPct')?.value || 15),
      memCritPct: Number(el('opsMemCritPct')?.value || 8),
      loadWarnRatio: Number(el('opsLoadWarnRatio')?.value || 1.5),
      loadCritRatio: Number(el('opsLoadCritRatio')?.value || 2.5),
      backupMaxAgeHours: Number(el('opsBackupMaxAgeHours')?.value || 28),
      alertCooldownWarnHours: Number(el('opsAlertCooldownWarnH')?.value || 6),
      alertCooldownCritHours: Number(el('opsAlertCooldownCritH')?.value || 1),
      driveEnabled: Boolean(el('opsDriveEnabled')?.checked),
      driveFolderId: el('opsDriveFolderId')?.value.trim() || '',
      driveRetainDays: Number(el('opsDriveRetainDays')?.value || 14),
    };
  }

  function fmtOpsWhen(iso) {
    return formatIstDateTime(iso) || '—';
  }

  async function loadOpsStatus() {
    if (!isSuperAdmin()) return;
    const panel = el('opsStatusPanel');
    if (!panel) return;
    panel.textContent = 'Loading server status…';
    try {
      const data = await api('/api/rwa/ops/status');
      const live = data.live || {};
      const lastB = data.lastBackup || {};
      const lastV = data.lastVitals || {};
      const lastD = data.lastDriveSync || {};
      const disk = live.diskFreePct ?? '—';
      const mem = live.memAvailablePct ?? '—';
      const load = live.loadRatio ?? '—';
      const adminOk = live.adminServiceActive;
      const ngxOk = live.nginxActive;
      const svc = (ok) => (ok === true ? 'OK · active' : (ok === false ? 'Down' : '—'));
      let driveLabel = '—';
      if (lastD.skipped) driveLabel = 'Skipped (disabled)';
      else if (lastD.ok === false) driveLabel = `Failed · ${lastD.error || ''}`.trim();
      else if (lastD.ok) driveLabel = 'OK';
      panel.innerHTML = `
        <div class="ops-status-grid">
          <div><strong>Disk free</strong><span>${escapeHtml(String(disk))}%</span></div>
          <div><strong>Memory avail</strong><span>${escapeHtml(String(mem))}%</span></div>
          <div><strong>Load ratio</strong><span>${escapeHtml(String(load))}</span></div>
          <div><strong>Admin service</strong><span>${escapeHtml(svc(adminOk))}</span></div>
          <div><strong>Nginx</strong><span>${escapeHtml(svc(ngxOk))}</span></div>
          <div><strong>Last backup</strong><span>${lastB.ok === false ? 'Failed' : (lastB.ok ? 'OK' : '—')} · ${escapeHtml(fmtOpsWhen(lastB.at))}</span></div>
          <div><strong>Last Drive sync</strong><span>${escapeHtml(driveLabel)} · ${escapeHtml(fmtOpsWhen(lastD.at))}</span></div>
          <div><strong>Last vitals</strong><span>${escapeHtml(lastV.overall || '—')} · ${escapeHtml(fmtOpsWhen(lastV.at))}</span></div>
        </div>`;
    } catch (err) {
      panel.textContent = err.message || 'Could not load ops status';
    }
  }

  async function loadObservability() {
    if (!isSuperAdmin()) return;
    const status = el('obsStatus');
    if (status) status.textContent = 'Loading…';
    const days = el('obsDays')?.value || '7';
    const houseId = String(el('obsHouseFilter')?.value || '').trim();
    const qs = new URLSearchParams({ days, limit: '250' });
    if (houseId) qs.set('houseId', houseId);
    const data = await api(`/api/rwa/observability?${qs.toString()}`);
    const summary = data.summary || {};
    if (el('obsSummary')) {
      el('obsSummary').innerHTML = `
        <div class="stat"><span>Total events</span><strong>${summary.totalEvents ?? 0}</strong></div>
        <div class="stat"><span>Unique users</span><strong>${summary.uniqueUsers ?? 0}</strong></div>
        <div class="stat"><span>Sign-ins</span><strong>${summary.logins ?? 0}</strong></div>
        <div class="stat"><span>Panel opens</span><strong>${summary.panelViews ?? 0}</strong></div>
        <div class="stat"><span>API calls</span><strong>${summary.apiCalls ?? 0}</strong></div>`;
    }
    const byDay = data.byDay || [];
    const maxDay = Math.max(1, ...byDay.map((d) => d.count || 0));
    // Inject sparkline above summary if present
    let spark = el('obsSpark');
    if (!spark && el('obsSummary')) {
      spark = document.createElement('div');
      spark.id = 'obsSpark';
      spark.className = 'obs-day-bar';
      el('obsSummary').before(spark);
    }
    if (spark) {
      spark.innerHTML = byDay.length
        ? byDay.map((d) => {
            const h = Math.max(6, Math.round(((d.count || 0) / maxDay) * 64));
            return `<div class="bar" style="height:${h}px" title="${escapeHtml(d.day)}: ${d.count}"></div>`;
          }).join('')
        : '<p class="muted">No activity in this period yet — use the portal to start collecting events.</p>';
    }
    if (el('obsTopActions')) {
      el('obsTopActions').innerHTML = (data.topActions || []).length
        ? data.topActions.map((a) => `
            <tr>
              <td data-label="Function">${escapeHtml(a.action)}</td>
              <td data-label="Count">${a.count}</td>
            </tr>`).join('')
        : '<tr><td colspan="2">No function usage yet.</td></tr>';
    }
    if (el('obsTopUsers')) {
      el('obsTopUsers').innerHTML = (data.topUsers || []).length
        ? data.topUsers.map((u) => `
            <tr>
              <td data-label="User"><code>${escapeHtml(u.houseId)}</code> ${escapeHtml(u.name || '')}</td>
              <td data-label="Role">${escapeHtml(u.role || '')}</td>
              <td data-label="Events">${u.count}</td>
            </tr>`).join('')
        : '<tr><td colspan="3">No users in this period.</td></tr>';
    }
    if (el('obsTrailStats')) {
      el('obsTrailStats').textContent = `${(data.recent || []).length} recent events · since ${formatIstDate(data.since) || '—'}`;
    }
    if (el('obsRecentRows')) {
      el('obsRecentRows').innerHTML = (data.recent || []).length
        ? data.recent.map((e) => {
            const when = formatIstDateTime(e.createdAt, { withSeconds: true });
            const who = e.superAdmin
              ? `admin · ${escapeHtml(e.name || 'Super admin')}`
              : `<code>${escapeHtml(e.houseId || '—')}</code> ${escapeHtml(e.name || '')}`;
            return `
              <tr>
                <td data-label="When">${escapeHtml(when)}</td>
                <td data-label="Who">${who}</td>
                <td data-label="Function">${escapeHtml(e.action || '')}</td>
                <td data-label="Type">${escapeHtml(e.eventType || '')}</td>
                <td data-label="Status">${e.statusCode ?? ''}</td>
              </tr>`;
          }).join('')
        : '<tr><td colspan="5">No events yet.</td></tr>';
    }
    if (status) status.textContent = '';
    refreshMobileListUi();
  }
  el('obsDays')?.addEventListener('change', () => loadObservability().catch(console.error));
  el('obsHouseFilter')?.addEventListener('change', () => loadObservability().catch(console.error));
  el('obsHouseFilter')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      loadObservability().catch(console.error);
    }
  });

  el('settingsForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!isSuperAdmin()) return;
    const status = el('settingsStatus');
    const btn = el('settingsSaveBtn');
    if (status) status.textContent = 'Saving…';
    if (btn) btn.disabled = true;
    try {
      const payload = {
        smtp: {
          provider: el('settingsSmtpProvider')?.value || 'gmail',
          host: el('settingsSmtpHost')?.value.trim() || '',
          port: Number(el('settingsSmtpPort')?.value || 587),
          user: el('settingsSmtpUser')?.value.trim() || '',
          from: el('settingsSmtpFrom')?.value.trim() || '',
        },
        otpTtl: Number(el('settingsOtpTtl')?.value || 600),
        superadminUser: el('settingsSaUser')?.value.trim() || 'admin',
        infoCentreProtect: Boolean(el('settingsInfoCentreProtect')?.checked),
        ops: collectOpsSettingsPayload(),
      };
      const pass = el('settingsSmtpPass')?.value || '';
      if (pass) payload.smtp.password = pass;
      const saPass = el('settingsSaPass')?.value || '';
      if (saPass) payload.superadminPassword = saPass;
      const data = await api('/api/rwa/settings', { method: 'PUT', body: JSON.stringify(payload) });
      if (el('settingsSmtpPass')) el('settingsSmtpPass').value = '';
      if (el('settingsSaPass')) el('settingsSaPass').value = '';
      setInfoCentreProtectFeature(Boolean(data.settings?.infoCentreProtect));
      if (el('settingsInfoCentreProtect')) {
        el('settingsInfoCentreProtect').checked = Boolean(data.settings?.infoCentreProtect);
      }
      const smtp = data.settings?.smtp || {};
      if (status) {
        const protectNote = data.settings?.infoCentreProtect
          ? ' Info Centre protection ON.'
          : ' Info Centre protection off.';
        status.textContent = smtp.configured
          ? `Settings saved. SMTP ready.${protectNote}`
          : `Settings saved. SMTP still needs an App Password.${protectNote}`;
      }
      loadSmtpStatus();
      fillOpsSettingsForm(data.settings?.ops || {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Save failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('opsSettingsForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!isSuperAdmin()) return;
    const status = el('opsSettingsStatus');
    const btn = el('opsSettingsSaveBtn');
    if (status) status.textContent = 'Saving…';
    if (btn) btn.disabled = true;
    try {
      const data = await api('/api/rwa/settings', {
        method: 'PUT',
        body: JSON.stringify({ ops: collectOpsSettingsPayload() }),
      });
      fillOpsSettingsForm(data.settings?.ops || {});
      if (status) status.textContent = 'Ops settings saved.';
    } catch (err) {
      if (status) status.textContent = err.message || 'Save failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('opsTestAlertBtn')?.addEventListener('click', async () => {
    if (!isSuperAdmin()) return;
    const status = el('opsSettingsStatus');
    const btn = el('opsTestAlertBtn');
    if (status) status.textContent = 'Sending test alert…';
    if (btn) btn.disabled = true;
    try {
      const data = await api('/api/rwa/ops/test-alert', { method: 'POST', body: '{}' });
      if (status) status.textContent = `Test alert sent to ${data.to || 'alert address'}.`;
    } catch (err) {
      if (status) status.textContent = err.message || 'Test alert failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('opsRefreshStatusBtn')?.addEventListener('click', () => {
    loadOpsStatus().catch((err) => {
      if (el('opsSettingsStatus')) el('opsSettingsStatus').textContent = err.message || 'Refresh failed';
    });
  });

  // Progressive Web App: service worker + install hint
  let deferredInstall = null;
  function showPwaHint(html) {
    const box = el('pwaInstallHint');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = html;
  }
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstall = event;
    showPwaHint(
      'Install <strong>Home@Sanyard</strong> on your phone for one-tap access.' +
      ' <button type="button" class="btn secondary compact" id="pwaInstallBtn">Install app</button>'
    );
    el('pwaInstallBtn')?.addEventListener('click', async () => {
      if (!deferredInstall) return;
      deferredInstall.prompt();
      try { await deferredInstall.userChoice; } catch (_e) { /* ignore */ }
      deferredInstall = null;
      const box = el('pwaInstallHint');
      if (box) box.hidden = true;
    }, { once: true });
  });
  window.addEventListener('appinstalled', () => {
    deferredInstall = null;
    const box = el('pwaInstallHint');
    if (box) {
      box.hidden = false;
      box.textContent = 'Installed. Open Home@Sanyard from your home screen anytime.';
    }
  });
  // iOS Safari has no beforeinstallprompt — show manual tip
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
  if (isIos && !isStandalone) {
    showPwaHint('On iPhone: tap Share → <strong>Add to Home Screen</strong> to install <strong>Home@Sanyard</strong>.');
  }
  if ('serviceWorker' in navigator) {
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });

    const setRefreshStatus = (msg) => {
      const s = el('appRefreshStatus');
      if (s) s.textContent = msg;
    };

    async function hardRefreshApp() {
      setRefreshStatus('Updating…');
      try {
        if ('caches' in window) {
          const keys = await caches.keys();
          await Promise.all(keys.map((k) => caches.delete(k)));
        }
        const reg = await navigator.serviceWorker.getRegistration();
        if (reg) {
          await reg.update();
          if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
      } catch (_e) { /* ignore */ }
      window.location.reload();
    }

    el('appRefreshBtn')?.addEventListener('click', () => hardRefreshApp());

    navigator.serviceWorker.register('/sw.js').then(async (reg) => {
      // Auto-check for a new service worker on launch and periodically
      try { await reg.update(); } catch (_e) { /* ignore */ }
      if (reg.waiting) {
        setRefreshStatus('Update ready — refreshing…');
        reg.waiting.postMessage({ type: 'SKIP_WAITING' });
      }
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            setRefreshStatus('Update ready — refreshing…');
            sw.postMessage({ type: 'SKIP_WAITING' });
          }
        });
      });
      setInterval(() => { reg.update().catch(() => {}); }, 5 * 60 * 1000);
    }).catch((err) => {
      console.warn('Service worker registration failed', err);
    });
  } else {
    el('appRefreshBtn')?.addEventListener('click', () => window.location.reload());
  }

  document.addEventListener('click', (event) => {
    const foldHead = event.target.closest('.mobile-fold-head');
    if (foldHead && isMobileLayout()) {
      if (event.target.closest('.notice-actions, .notice-engage, .notice-comments, .btn-row, .mailbox-reply, input, select, textarea, a')) return;
      const card = foldHead.closest('.mobile-fold');
      if (!card) return;
      const open = card.classList.toggle('is-open');
      foldHead.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) scrollBelowAppHeader(card.querySelector('.mobile-fold-body') || card);
      return;
    }
    const sectionToggle = event.target.closest('.mobile-section-toggle, .desk-section-toggle');
    if (sectionToggle) {
      event.preventDefault();
      toggleDeskSection(sectionToggle.closest('.mobile-section'));
      return;
    }
    const sectionHead = event.target.closest(
      '.mobile-section > .roster-toolbar > div:first-child, .mobile-section > .panel-head, .mobile-section .mailbox-toolbar > .panel-head'
    );
    if (sectionHead) {
      if (event.target.closest('input, select, textarea, button, a, label, .roster-search, .roster-toolbar-actions')) return;
      toggleDeskSection(sectionHead.closest('.mobile-section'));
    }
  });

  MOBILE_MQ.addEventListener('change', () => {
    updateAppTopOffset();
    refreshMobileListUi();
  });
  window.addEventListener('resize', updateAppTopOffset);

  prepareMobileSections();
  updateAppTopOffset();

  // PWA / iOS: cookie jar can drop; restore from localStorage before session check.
  const bootToken = loadStoredToken();
  if (bootToken && !state.session) {
    state.session = { token: bootToken };
  }

  refreshSession().catch(() => {
    clearPersistedAuth();
    setAuthed(null);
  });

  // Re-validate when returning to a backgrounded PWA / bfcache restore.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted || loadStoredToken()) {
      refreshSession().catch(() => {});
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (!loadStoredToken() && !state.session?.token) return;
    refreshSession().catch(() => {});
  });
})();
