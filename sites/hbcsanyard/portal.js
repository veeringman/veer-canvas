(() => {
  const state = {
    session: null,
    pendingHouse: '',
    pendingMemberId: '',
    pendingContact: false,
    missingEmail: false,
    missingPhone: false,
  };

  const el = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const token = state.session?.token;
    if (token) headers['X-RWA-Token'] = token;
    const res = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    return data;
  }

  function inr(n) {
    const num = Number(n) || 0;
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num);
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
    if (r.viewOnly || r.isPrimary === false) return false;
    const ents = r.entitlements;
    if (Array.isArray(ents) && ents.length) return ents.includes(key);
    // Fallback for older sessions: EC admin role implies all
    return r.role === 'admin' && Boolean(r.isPrimary !== false);
  }

  function isEcAdmin(r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly || r.isPrimary === false) return false;
    if (typeof r.isEcAdmin === 'boolean') return r.isEcAdmin;
    return r.role === 'admin';
  }

  function canOpenEcDesk(r = state.session?.resident) {
    if (!r) return false;
    if (isSuperAdmin(r)) return true;
    if (r.viewOnly || r.isPrimary === false) return false;
    if (isEcAdmin(r)) return true;
    const ents = r.entitlements;
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

  function personAvatarHtml(person = {}, { size = 'sm', className = '' } = {}) {
    const url = person.photoUrl || '';
    const cls = ['person-avatar', size === 'md' ? 'is-md' : (size === 'lg' ? 'is-lg' : 'is-sm'), className].filter(Boolean).join(' ');
    const attrs = url ? ` data-photo-url="${escapeHtml(url)}"` : '';
    return `<span class="${cls}"${attrs} aria-hidden="true"><span class="person-avatar-fallback">${AVATAR_PLACEHOLDER_SVG}</span></span>`;
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
      if (translated[i] && !String(n.hiEl.value || '').trim()) n.hiEl.value = translated[i];
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
          <span class="meta">${escapeHtml(n.category || 'general')}${(n.publishedAt || '').slice(0, 10) ? ` · ${escapeHtml((n.publishedAt || '').slice(0, 10))}` : ''}</span>
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
      const openBtn = d.docType === 'html' && d.hasHtmlHi
        ? `<button type="button" class="btn primary compact info-doc-open-hi" data-id="${escapeHtml(d.id)}">Open Hindi HTML</button>`
        : (d.docType === 'html'
          ? `<button type="button" class="btn secondary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open English HTML</button>`
          : `<button type="button" class="btn secondary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open file</button>`);
      cards.push(`
        <article class="lang-overlay-card">
          <h4>${escapeHtml(title.text || d.title || 'Untitled')} ${autoBadge(title.auto || summary.auto)}</h4>
          <span class="meta">${escapeHtml(d.categoryLabel || d.category || '')}${d.docType === 'html' ? ' · HTML' : ' · File'}</span>
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
    const blocks = root.querySelectorAll('#panel-admin .roster-block, #panel-observability .roster-block, #adminDues');
    blocks.forEach((block, index) => {
      if (block.dataset.mobileSectionReady) return;
      block.dataset.mobileSectionReady = '1';
      block.classList.add('mobile-section');
      const toolbar = block.querySelector(':scope > .roster-toolbar, :scope > .panel-head, :scope > .ledger-toolbar');
      if (!toolbar) return;

      const bodyNodes = [];
      let node = toolbar.nextElementSibling;
      while (node) {
        bodyNodes.push(node);
        node = node.nextElementSibling;
      }
      if (!bodyNodes.length) return;

      const body = document.createElement('div');
      body.className = 'mobile-section-body';
      bodyNodes.forEach((n) => body.appendChild(n));
      block.appendChild(body);

      const heading = toolbar.querySelector('h3, h2');
      if (heading && !toolbar.querySelector('.mobile-section-toggle')) {
        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'mobile-section-toggle';
        toggle.setAttribute('aria-expanded', index === 0 ? 'true' : 'false');
        toggle.innerHTML = '<span class="mobile-section-chevron" aria-hidden="true"></span>';
        heading.parentElement.insertBefore(toggle, heading);
        if (index !== 0) block.classList.add('is-section-collapsed');
      }
    });
  }

  function refreshMobileListUi() {
    applyMobileListLimit(el('ledgerRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('rosterRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('revisionRows'), 'tr:not(.is-empty-row)', 5);
    applyMobileListLimit(el('obsRecentRows'), 'tr:not(.is-empty-row)', 8);
    applyMobileListLimit(el('noticeList'), '.notice.mobile-fold', 4);
    applyMobileListLimit(el('mailboxList'), '.grievance-card.mobile-fold', 4);
    applyMobileListLimit(el('ecGrievanceList'), '.grievance-card.mobile-fold', 4);
    applyMobileListLimit(el('infoDocList'), '.info-doc-card.mobile-fold', 5);
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

  function setAuthed(session) {
    state.session = session;
    const isAuthed = Boolean(session?.resident);
    document.body.classList.toggle('is-authed', isAuthed);
    const gate = el('gateView');
    const app = el('appView');
    if (gate) gate.hidden = isAuthed;
    if (app) app.hidden = !isAuthed;

    if (!isAuthed) {
      document.querySelectorAll('.admin-only, .superadmin-only').forEach((node) => {
        node.hidden = true;
      });
      const duesTab = el('duesTab') || document.querySelector('.tab[data-panel="dues"]');
      if (duesTab) duesTab.hidden = false;
      return;
    }

    const r = session.resident;
    const chip = el('userChip');
    if (chip) {
      const tag = r.superAdmin
        ? ' · Super admin'
        : (r.role === 'admin' ? ' · EC' : (r.viewOnly ? ' · View only' : (r.isPrimary ? '' : ` · ${r.relationLabel || 'Delegate'}`)));
      const label = r.superAdmin ? 'admin' : r.houseId;
      const titleBit = (r.officialTitle && r.role === 'admin') ? ` (${r.officialTitle})` : '';
      chip.textContent = `${label} · ${r.name}${titleBit}${tag}`;
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
  }

  function activePanelName() {
    return document.querySelector('.tab.is-active')?.dataset?.panel || 'home';
  }

  function ensurePanelVisibility(preferred) {
    let name = preferred || activePanelName() || 'home';
    if (name === 'admin' && !canOpenEcDesk()) name = 'home';
    if (name === 'observability' && !isSuperAdmin()) name = 'home';
    if (name === 'dues' && isSuperAdmin()) name = 'home';
    switchPanel(name);
  }

  async function refreshSession() {
    const data = await api('/api/rwa/session');
    if (data.authenticated) {
      const preferred = activePanelName();
      setAuthed(data);
      ensurePanelVisibility(preferred);
    } else {
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

  function renderNoticeCard(n, { canMoveUp = false, canMoveDown = false } = {}) {
    const date = (n.publishedAt || '').slice(0, 10);
    const welcome = isWelcomeNotice(n);
    const recent = isRecentNotice(n);
    const likeCount = Number(n.likeCount || 0);
    const commentCount = Number(n.commentCount || 0);
    const liked = Boolean(n.likedByMe);
    const viewOnly = isViewOnly();
    const engageDisabled = viewOnly ? ' disabled title="View-only access"' : '';
    const moveActions = (hasEntitlement('manage_notices') && n.pinned && !welcome) ? `
        <button type="button" class="btn ghost compact notice-move-up" data-id="${escapeHtml(n.id)}" ${canMoveUp ? '' : 'disabled'} title="Move up">↑ Up</button>
        <button type="button" class="btn ghost compact notice-move-down" data-id="${escapeHtml(n.id)}" ${canMoveDown ? '' : 'disabled'} title="Move down">↓ Down</button>` : '';
    const pinDelete = welcome
      ? ''
      : `
        <button type="button" class="btn ghost compact notice-pin" data-id="${escapeHtml(n.id)}" data-pinned="${n.pinned ? '1' : '0'}">${n.pinned ? 'Unpin' : 'Pin'}</button>
        <button type="button" class="btn ghost compact notice-delete" data-id="${escapeHtml(n.id)}">Delete</button>`;
    const actions = hasEntitlement('manage_notices') ? `
      <div class="notice-actions">
        ${moveActions}
        <button type="button" class="btn ghost compact notice-edit" data-id="${escapeHtml(n.id)}">Edit</button>
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
      box.innerHTML = '<p class="muted">No drafts yet. Save a draft, or wait for another EC member to share one with you.</p>';
      if (stats) stats.textContent = 'Your drafts and those shared with you.';
      return;
    }
    if (stats) {
      stats.textContent = `${draftsCache.length} draft${draftsCache.length === 1 ? '' : 's'} · share as edit (default) or view only`;
    }
    box.innerHTML = draftsCache.map((n) => {
      const excerpt = String(n.body || '').trim() || 'No body yet.';
      const short = excerpt.length > 160 ? `${excerpt.slice(0, 157)}…` : excerpt;
      const when = (n.publishedAt || '').slice(0, 16).replace('T', ' ');
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
        : 'Write notice';
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
    ['noticeTitleInput', 'noticeBodyInput', 'noticeCategoryInput', 'noticePinnedInput'].forEach((id) => {
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
    const pinLabel = el('noticePinnedInput')?.closest('label');
    if (pinLabel) pinLabel.title = '';
    if (el('noticeBodyInput')) el('noticeBodyInput').required = true;
    ['noticeTitleInput', 'noticeBodyInput', 'noticeCategoryInput', 'noticePinnedInput'].forEach((id) => {
      const field = el(id);
      if (field) field.disabled = false;
    });
    syncNoticeFormMode(null);
    setAuthorFormLang('notice', 'en');
    if (el('noticeTitleHiInput')) el('noticeTitleHiInput').value = '';
    if (el('noticeBodyHiInput')) el('noticeBodyHiInput').value = '';
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
        status: asDraft ? 'draft' : 'published',
      };
      if (noticeId) {
        await api(`/api/rwa/notices/${encodeURIComponent(noticeId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        await api('/api/rwa/notices', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      resetNoticeForm();
      await loadNoticeDrafts().catch(console.error);
      if (asDraft) {
        if (statusLine) statusLine.textContent = 'Draft saved. Continue anytime from the list above.';
        switchPanel('admin');
      } else {
        await loadHome();
        switchPanel('home');
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
        card.innerHTML = `
          <div class="stat-grid">
            <div class="stat"><span>Previous total</span><strong>${inr(p.previousTotal ?? p.balancePrev)}</strong></div>
            <div class="stat"><span>Previous paid</span><strong>${inr(p.previousPaid ?? 0)}</strong></div>
            <div class="stat"><span>Previous pending / dues</span><strong>${inr(p.previousPending ?? p.balancePrev)}</strong></div>
            <div class="stat"><span>Current year total</span><strong>${inr(p.currentYearTotal ?? p.feeAmount)}</strong></div>
            <div class="stat"><span>Pending / dues</span><strong>${inr(p.pendingDues ?? p.balanceOutstanding)}</strong></div>
          </div>`;
      }
    }
    const bank = el('bankCard');
    if (bank) {
      renderPayCard(bank, data.summary?.bank, { showEdit: isEcAdmin() });
    }

    if (isEcAdmin()) {
      await loadLedger();
    }
  }

  function qrImgUrl(bank) {
    if (!bank?.hasQr && !bank?.qrUrl) return '';
    const base = bank.qrUrl || '/api/rwa/bank/qr';
    return `${base}?t=${encodeURIComponent(bank.qrFilename || bank.updatedAt || Date.now())}`;
  }

  function renderPayCard(target, bank, { showEdit = false } = {}) {
    if (!target) return;
    const b = bank || {};
    const name = b.bankName || b.bank_name || 'Bank of Baroda — Mandi';
    const account = b.accountNo || b.account_no || '09640100004511';
    const ifsc = b.ifsc || 'BARB0MANDIX';
    const upiId = b.upiId || '';
    const upiName = b.upiName || '';
    const qr = qrImgUrl(b);
    const label = b.label || 'RWA collection';
    target.innerHTML = `
      <div class="pay-card-body">
        <div>
          <h3>${escapeHtml(label)}</h3>
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
    if (el('bankEditLabel')) el('bankEditLabel').value = b.label || 'RWA collection';
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
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: hasEntitlement('manage_bank') });
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
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: hasEntitlement('manage_bank') });
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
      if (el('bankCard')) renderPayCard(el('bankCard'), data.bank, { showEdit: hasEntitlement('manage_bank') });
      fillBankEditForm(data.bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'QR removed.';
    } catch (err) {
      setBankEditError(err.message || 'Could not remove QR');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    }
  }

  let ledgerCache = [];
  let ledgerAutoRecalc = true;

  function renderLedgerSummary(sum) {
    if (!el('ledgerSummary') || !sum) return;
    el('ledgerSummary').textContent =
      `${sum.households || 0} households · due ${inr(sum.totalDue)} · received ${inr(sum.totalReceived)} · outstanding ${inr(sum.totalOutstanding)}`;
  }

  function renderLedgerRows() {
    const tbody = el('ledgerRows');
    if (!tbody) return;
    const q = (el('ledgerSearch')?.value || '').trim().toLowerCase();
    const rows = ledgerCache.filter((r) => {
      if (!q) return true;
      return `${r.houseId} ${r.plotNo || ''} ${r.name || ''} ${r.section || ''} ${r.remarks || ''}`.toLowerCase().includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = '<tr class="is-empty-row"><td colspan="8" class="muted">No matching ledger rows.</td></tr>';
      refreshMobileListUi();
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-house="${escapeHtml(r.houseId)}">
        <td data-label="Plot"><code>${escapeHtml(r.houseId)}</code></td>
        <td data-label="Name">${escapeHtml(r.name || '')}</td>
        <td data-label="Prev total">${inr(r.previousTotal ?? r.balancePrev)}</td>
        <td data-label="Prev paid">${inr(r.previousPaid ?? 0)}</td>
        <td data-label="Prev pending">${inr(r.previousPending ?? r.balancePrev)}</td>
        <td data-label="Year total">${inr(r.currentYearTotal ?? r.feeAmount)}</td>
        <td data-label="Pending / dues">${inr(r.pendingDues ?? r.balanceOutstanding)}</td>
        <td data-label="Actions" class="row-actions"><button type="button" class="btn secondary compact ledger-edit" data-house="${escapeHtml(r.houseId)}">Edit</button></td>
      </tr>`).join('');
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
  el('ledgerRows')?.addEventListener('click', (event) => {
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

  async function loadDirectory() {
    const data = await api('/api/rwa/directory');
    el('directoryRows').innerHTML = (data.residents || []).map((r) => {
      const roleLabel = committeeRoleLabel(r);
      const titleBit = r.officialTitle ? ` · ${escapeHtml(r.officialTitle)}` : '';
      return `
      <tr>
        <td data-label="Plot"><code>${escapeHtml(r.houseId)}</code></td>
        <td data-label="Section">${escapeHtml(r.section)}</td>
        <td data-label="Name" class="person-cell">${personAvatarHtml(r)} <span>${escapeHtml(r.name)}</span></td>
        <td data-label="Role">${escapeHtml(roleLabel)}${titleBit}</td>
      </tr>`;
    }).join('');
    await hydrateAvatars(el('directoryRows'));
  }

  let infoCategoriesCache = [];
  let infoDocsCache = [];

  function formatBytes(n) {
    const num = Number(n) || 0;
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
    return `${(num / (1024 * 1024)).toFixed(1)} MB`;
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

  function syncInfoSourcePanes() {
    const source = document.querySelector('input[name="infoSource"]:checked')?.value || 'file';
    if (el('infoFilePane')) el('infoFilePane').hidden = source !== 'file';
    if (el('infoHtmlPane')) el('infoHtmlPane').hidden = source !== 'html';
    if (el('infoFileInput')) el('infoFileInput').required = false;
  }

  function resetInfoForm() {
    const form = el('infoDocForm');
    if (!form) return;
    form.reset();
    if (el('infoEditId')) el('infoEditId').value = '';
    if (el('infoStatusInput')) el('infoStatusInput').value = 'published';
    if (el('infoAudienceInput')) el('infoAudienceInput').value = 'all';
    if (el('infoFormTitle')) el('infoFormTitle').textContent = 'Publish a document';
    if (el('infoSaveBtn')) el('infoSaveBtn').textContent = 'Publish';
    if (el('infoCancelEditBtn')) el('infoCancelEditBtn').hidden = true;
    if (el('infoFormStatus')) el('infoFormStatus').textContent = '';
    const fileRadio = document.querySelector('input[name="infoSource"][value="file"]');
    if (fileRadio) fileRadio.checked = true;
    if (el('infoTitleHiInput')) el('infoTitleHiInput').value = '';
    if (el('infoSummaryHiInput')) el('infoSummaryHiInput').value = '';
    if (el('infoHtmlHiInput')) el('infoHtmlHiInput').value = '';
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
    if (el('infoStatusInput')) el('infoStatusInput').value = doc.status || 'draft';
    if (el('infoAudienceInput')) el('infoAudienceInput').value = doc.audience || 'all';
    const htmlRadio = document.querySelector('input[name="infoSource"][value="html"]');
    const fileRadio = document.querySelector('input[name="infoSource"][value="file"]');
    if (doc.docType === 'html' && htmlRadio) htmlRadio.checked = true;
    else if (fileRadio) fileRadio.checked = true;
    syncInfoSourcePanes();
    if (el('infoHtmlInput') && doc.docType !== 'html') el('infoHtmlInput').value = '';
    if (el('infoHtmlHiInput') && doc.docType !== 'html') el('infoHtmlHiInput').value = '';
    setAuthorFormLang('info', 'en');
    if (el('infoFormTitle')) el('infoFormTitle').textContent = 'Update document';
    if (el('infoSaveBtn')) el('infoSaveBtn').textContent = 'Save changes';
    if (el('infoCancelEditBtn')) el('infoCancelEditBtn').hidden = false;
    if (el('infoFormStatus')) {
      el('infoFormStatus').textContent = doc.docType === 'html'
        ? 'Editing HTML document — switch EN/हिं for bilingual content. Leave HTML blank to keep existing.'
        : `Editing ${doc.originalName || doc.id} — Hindi title/summary optional; file uploads stay single-language.`;
    }
    el('infoManageBlock')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function confirmInfoPublish(title, audience) {
    if (audience === 'ec') {
      return window.confirm(
        `Are you sure you want to publish “${title}” to EC members only?\n\nRegular residents will not see this document.`
      );
    }
    return window.confirm(
      `Are you sure you want to publish “${title}” to ALL members?\n\nThis will be visible to every signed-in resident.`
    );
  }

  function renderInfoDocs() {
    const box = el('infoDocList');
    const status = el('infoListStatus');
    if (!box) return;
    if (!infoDocsCache.length) {
      box.innerHTML = '<p class="muted">No documents yet. EC can publish circulars, bye-laws, forms, and guides here.</p>';
      if (status) status.textContent = '';
      return;
    }
    if (status) {
      status.textContent = `${infoDocsCache.length} document${infoDocsCache.length === 1 ? '' : 's'}`;
    }
    box.innerHTML = infoDocsCache.map((d) => {
      const when = String(d.publishedAt || d.updatedAt || '').slice(0, 10);
      const badges = [
        `<span class="info-doc-badge">${escapeHtml(d.categoryLabel || d.category || 'general')}</span>`,
        `<span class="info-doc-badge ${d.docType === 'html' ? 'is-html' : 'is-file'}">${d.docType === 'html' ? 'HTML' : 'File'}</span>`,
        d.status === 'published'
          ? `<span class="info-doc-badge ${d.audience === 'ec' ? 'is-ec' : 'is-all'}">${escapeHtml(d.audienceLabel || (d.audience === 'ec' ? 'EC only' : 'All members'))}</span>`
          : '',
        d.status === 'draft' ? '<span class="info-doc-badge is-draft">Draft</span>' : '',
      ].filter(Boolean).join('');
      const metaBits = [
        d.originalName || '',
        d.sizeBytes ? formatBytes(d.sizeBytes) : '',
        when || '',
      ].filter(Boolean).join(' · ');
      const actions = [
        `<button type="button" class="btn primary compact info-doc-open" data-id="${escapeHtml(d.id)}">Open</button>`,
      ];
      if (isEcAdmin()) {
        actions.push(`<button type="button" class="btn secondary compact info-doc-edit" data-id="${escapeHtml(d.id)}">Edit</button>`);
        if (d.status !== 'published') {
          actions.push(`<button type="button" class="btn ghost compact info-doc-publish" data-id="${escapeHtml(d.id)}" data-audience="all">Publish to all</button>`);
          actions.push(`<button type="button" class="btn ghost compact info-doc-publish" data-id="${escapeHtml(d.id)}" data-audience="ec">Publish to EC</button>`);
        } else {
          actions.push(`<button type="button" class="btn ghost compact info-doc-unpublish" data-id="${escapeHtml(d.id)}">Unpublish</button>`);
        }
        actions.push(`<button type="button" class="btn ghost compact info-doc-delete" data-id="${escapeHtml(d.id)}">Delete</button>`);
      }
      return `
        <article class="info-doc-card mobile-fold" data-id="${escapeHtml(d.id)}">
          <button type="button" class="mobile-fold-head" aria-expanded="false">
            <span class="mobile-fold-head-main">
              <span>${badges}</span>
              <span class="info-doc-card-title">${escapeHtml(d.title || 'Untitled')}</span>
              <span class="meta">${escapeHtml(metaBits)}</span>
            </span>
            <span class="mobile-fold-chevron" aria-hidden="true"></span>
          </button>
          <div class="mobile-fold-body">
            ${d.summary ? `<p class="summary">${escapeHtml(d.summary)}</p>` : ''}
            <div class="btn-row">${actions.join('')}</div>
          </div>
        </article>`;
    }).join('');
    refreshMobileListUi();
  }

  async function loadInfoCentre() {
    if (el('infoManageBlock')) el('infoManageBlock').hidden = !hasEntitlement('manage_info');
    const status = hasEntitlement('manage_info')
      ? (el('infoStatusFilter')?.value || 'published')
      : 'published';
    const category = el('infoCategoryFilter')?.value || '';
    const qs = new URLSearchParams({ status });
    if (category) qs.set('category', category);
    const data = await api(`/api/rwa/info-centre?${qs.toString()}`);
    fillInfoCategorySelects(data.categories || []);
    infoDocsCache = data.documents || [];
    renderInfoDocs();
    if (sectionLang.info === 'hi') renderInfoOverlay();
  }

  async function openInfoDocument(doc, { lang = 'en' } = {}) {
    if (!doc?.id) return;
    const token = state.session?.token || '';
    const qs = lang === 'hi' ? '?lang=hi' : '';
    const url = `/api/rwa/info-centre/${encodeURIComponent(doc.id)}/file${qs}`;
    // Authenticated open: fetch blob then open object URL (headers not sent on plain window.open).
    const res = await fetch(url, {
      credentials: 'same-origin',
      headers: token ? { 'X-RWA-Token': token } : {},
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || res.statusText || 'Could not open document');
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const win = window.open(objectUrl, '_blank', 'noopener');
    if (!win) {
      // Popup blocked — force download via temporary link
      const a = document.createElement('a');
      a.href = objectUrl;
      a.download = doc.originalName || 'document';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }

  async function saveInfoDocument(event) {
    event.preventDefault();
    if (!isEcAdmin()) return;
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
    if (statusVal === 'published') {
      if (!confirmInfoPublish(title, audienceVal)) return;
    }
    if (saveBtn) saveBtn.disabled = true;
    if (statusLine) statusLine.textContent = 'Saving…';
    try {
      let doc;
      if (source === 'html') {
        const htmlBody = String(el('infoHtmlInput')?.value || '').trim();
        if (!htmlBody && !editId) {
          if (statusLine) statusLine.textContent = 'Write HTML content, or switch to file upload.';
          return;
        }
        const payload = {
          title,
          titleHi: el('infoTitleHiInput')?.value.trim() || '',
          summary: el('infoSummaryInput')?.value.trim() || '',
          summaryHi: el('infoSummaryHiInput')?.value.trim() || '',
          category: el('infoCategoryInput')?.value || 'general',
          status: statusVal,
          audience: audienceVal,
          docType: 'html',
        };
        if (htmlBody) payload.htmlBody = htmlBody;
        const htmlBodyHi = String(el('infoHtmlHiInput')?.value || '').trim();
        if (htmlBodyHi || el('infoHtmlHiInput')?.value === '') {
          // Always send when Hindi pane was used / cleared on edit intent.
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
          body.append('status', statusVal);
          body.append('audience', audienceVal);
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
          // Metadata-only update
          doc = (await api(`/api/rwa/info-centre/${encodeURIComponent(editId)}`, {
            method: 'PATCH',
            body: JSON.stringify({
              title,
              titleHi: el('infoTitleHiInput')?.value.trim() || '',
              summary: el('infoSummaryInput')?.value.trim() || '',
              summaryHi: el('infoSummaryHiInput')?.value.trim() || '',
              category: el('infoCategoryInput')?.value || 'general',
              status: statusVal,
              audience: audienceVal,
            }),
          })).document;
        }
      }
      resetInfoForm();
      if (statusLine) {
        statusLine.textContent = doc?.status === 'published'
          ? (doc.audience === 'ec' ? 'Published to EC only.' : 'Published to all members.')
          : 'Saved as draft.';
      }
      await loadInfoCentre();
    } catch (err) {
      if (statusLine) statusLine.textContent = err.message || 'Save failed';
    } finally {
      if (saveBtn) saveBtn.disabled = false;
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

  function switchPanel(name) {
    if (name === 'admin' && !canOpenEcDesk()) name = 'home';
    if (name === 'observability' && !isSuperAdmin()) name = 'home';
    if (name === 'dues' && isSuperAdmin()) name = 'home';
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
    if (name === 'home') loadHome().catch(console.error);
    if (name === 'dues') loadDues().catch((e) => { el('duesCard').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
    if (name === 'concerns') loadMailbox().catch((e) => {
      if (el('mailboxList')) el('mailboxList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'directory') loadDirectory().catch((e) => { el('directoryRows').innerHTML = `<tr><td colspan="4">${escapeHtml(e.message)}</td></tr>`; });
    if (name === 'info') loadInfoCentre().catch((e) => {
      if (el('infoDocList')) el('infoDocList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'works') loadWorks().catch((e) => {
      if (el('worksList')) el('worksList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'admin') {
      prepareMobileSections();
      applyEntitlementVisibility();
      loadSmtpStatus();
      initReportsForm().catch(() => {});
      if (hasEntitlement('manage_notices')) {
        loadNoticeDrafts().catch((e) => {
          if (el('noticeDraftList')) el('noticeDraftList').innerHTML = `<p class="error">${escapeHtml(e.message || 'Drafts failed')}</p>`;
        });
      }
      if (hasEntitlement('manage_bank')) {
        loadBankDetails().catch((e) => { if (el('ecBankPreview')) el('ecBankPreview').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
      }
      if (hasEntitlement('manage_concerns')) {
        loadEcGrievances().catch((e) => { if (el('ecGrievanceStatus')) el('ecGrievanceStatus').textContent = e.message || 'Concerns failed'; });
      }
      if (hasEntitlement('manage_roster')) {
        loadRoster().catch((e) => { if (el('rosterStatus')) el('rosterStatus').textContent = e.message || 'Roster failed'; });
      } else if (isEcAdmin()) {
        populateEcDelegateHouseList().catch(() => {});
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
    if (el('otpInput')) el('otpInput').value = '';
    if (el('otpContactEmail')) el('otpContactEmail').value = '';
    if (el('otpContactPhone')) el('otpContactPhone').value = '';
    if (el('otpMemberList')) el('otpMemberList').innerHTML = '';
    state.pendingHouse = '';
    state.pendingMemberId = '';
    state.pendingContact = false;
    state.missingEmail = false;
    state.missingPhone = false;
    showError('');
  }

  function showMemberPicker(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = '';
    el('otpRequestForm').hidden = true;
    el('otpContactForm').hidden = true;
    el('otpVerifyForm').hidden = true;
    el('otpMemberForm').hidden = false;
    const name = data.householdName ? ` (${escapeHtml(data.householdName)})` : '';
    el('otpMemberHint').innerHTML = data.message
      || `Who is signing in for plot <strong>${escapeHtml(state.pendingHouse)}</strong>${name}?`;
    const list = el('otpMemberList');
    list.innerHTML = (data.members || []).map((m) => `
      <button type="button" class="member-pick-btn" data-member-id="${escapeHtml(m.id)}">
        ${personAvatarHtml({ ...m, photoUrl: '' }, { size: 'md' })}
        <span class="member-pick-text">
          <strong>${escapeHtml(m.name || 'Member')}</strong>
          <span class="muted">${escapeHtml(m.relationLabel || m.relation || '')}${m.viewOnly ? ' · view only' : ''}${m.emailMasked ? ` · ${escapeHtml(m.emailMasked)}` : ''}</span>
        </span>
      </button>
    `).join('');
  }

  function showContactForm(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingMemberId = data.memberId || state.pendingMemberId;
    state.missingEmail = Boolean(data.missingEmail);
    state.missingPhone = Boolean(data.missingPhone);
    el('otpRequestForm').hidden = true;
    el('otpMemberForm') && (el('otpMemberForm').hidden = true);
    el('otpVerifyForm').hidden = true;
    el('otpContactForm').hidden = false;
    const name = data.name ? ` for ${data.name}` : '';
    el('otpContactHint').textContent = data.message
      || `Plot ${state.pendingHouse}${name} is missing contact details. Enter them below. They are saved only after you verify the emailed code.`;
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
    el('otpRequestForm').hidden = true;
    el('otpMemberForm') && (el('otpMemberForm').hidden = true);
    el('otpContactForm').hidden = true;
    el('otpVerifyForm').hidden = false;
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
      const data = await requestOtp({ houseId });
      await handleOtpRequestResult(data, houseId);
    } catch (err) {
      showError(err.message || 'Could not send code');
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
      const data = await requestOtp({
        houseId: state.pendingHouse,
        memberId,
      });
      await handleOtpRequestResult(data, state.pendingHouse);
    } catch (err) {
      showError(err.message || 'Could not send code');
      btn.disabled = false;
    }
  });

  el('otpMemberBackBtn')?.addEventListener('click', () => resetLoginForms());

  el('otpContactForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    const btn = el('otpContactSubmitBtn');
    if (btn) btn.disabled = true;
    try {
      const payload = {
        houseId: state.pendingHouse || el('houseIdInput').value.trim(),
        memberId: state.pendingMemberId || undefined,
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
      setAuthed(data);
      ensurePanelVisibility('home');
      if (data.contactUpdated) {
        const list = el('noticeList');
        if (list) {
          const note = document.createElement('p');
          note.className = 'muted';
          note.textContent = 'Your email/phone were verified and saved to the colony register.';
          list.prepend(note);
        }
      }
    } catch (err) {
      showError(err.message || 'Invalid code');
    } finally {
      el('verifyOtpBtn').disabled = false;
    }
  });

  el('otpContactBackBtn')?.addEventListener('click', () => resetLoginForms());
  el('restartLoginBtn')?.addEventListener('click', () => resetLoginForms());

  el('logoutBtn')?.addEventListener('click', async () => {
    try { await api('/api/rwa/logout', { method: 'POST', body: '{}' }); } catch (_e) { /* ignore */ }
    setAuthed(null);
    resetLoginForms();
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
          m.isPrimary ? 'Owner' : (m.relationLabel || m.relation),
          m.viewOnly ? 'View only' : null,
        ].filter(Boolean).join(' · ');
        const actions = canManage && !m.isPrimary ? `
          <div class="btn-row">
            <label class="check compact"><input type="checkbox" class="hh-view-only" data-id="${escapeHtml(m.id)}" ${m.viewOnly ? 'checked' : ''}> View only</label>
            <button type="button" class="btn ghost compact hh-remove" data-id="${escapeHtml(m.id)}">Remove</button>
          </div>` : (m.isPrimary ? '<p class="muted">Primary owner — EC access stays with this login only</p>' : '');
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
    const box = event.target.closest('.hh-view-only');
    if (!box) return;
    const r = state.session?.resident;
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

  el('noticeForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    await saveNotice({ asDraft: false });
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
      const when = (c.createdAt || '').slice(0, 16).replace('T', ' ');
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
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
    } catch (_e) {
      return String(iso).slice(0, 16);
    }
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
  el('infoCategoryFilter')?.addEventListener('change', () => loadInfoCentre().catch(console.error));
  el('infoStatusFilter')?.addEventListener('change', () => loadInfoCentre().catch(console.error));
  el('infoDocForm')?.addEventListener('submit', saveInfoDocument);
  el('infoCancelEditBtn')?.addEventListener('click', () => resetInfoForm());
  document.querySelectorAll('input[name="infoSource"]').forEach((input) => {
    input.addEventListener('change', syncInfoSourcePanes);
  });
  el('infoDocList')?.addEventListener('click', async (event) => {
    const openBtn = event.target.closest('.info-doc-open');
    const editBtn = event.target.closest('.info-doc-edit');
    const pubBtn = event.target.closest('.info-doc-publish');
    const unpubBtn = event.target.closest('.info-doc-unpublish');
    const delBtn = event.target.closest('.info-doc-delete');
    const id = (openBtn || editBtn || pubBtn || unpubBtn || delBtn)?.getAttribute('data-id');
    const doc = infoDocsCache.find((d) => d.id === id);
    if (!id || !doc) return;

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
    if (!isEcAdmin()) return;
    if (editBtn) {
      startInfoEdit(doc);
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
        await loadInfoCentre();
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
        await loadInfoCentre();
      } catch (err) {
        alert(err.message || 'Delete failed');
        delBtn.disabled = false;
      }
    }
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
    if (el('reportConcernStatus') && filters.status) el('reportConcernStatus').value = filters.status;
    const duesLike = dataset === 'dues';
    const concernsLike = dataset === 'concerns';
    if (el('reportPendingOnlyWrap')) el('reportPendingOnlyWrap').hidden = !duesLike;
    if (el('reportPlotsWrap')) el('reportPlotsWrap').hidden = concernsLike;
    if (el('reportConcernStatusWrap')) el('reportConcernStatusWrap').hidden = !concernsLike;
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
    };
    return {
      reportId,
      dataset,
      fields: selectedReportFieldIds(),
      filters,
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
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
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
          const disabled = m.isEcAdmin ? ' disabled' : '';
          const checked = m.isEcAdmin || grants.has(e.id) ? ' checked' : '';
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
          ${canGrant || m.isEcAdmin ? `<div class="report-field-grid">${checks}</div>` : '<p class="muted">No entitlements yet — save grants below after selecting.</p><div class="report-field-grid">' + checks + '</div>'}
          <div class="btn-row">
            ${m.isEcAdmin
              ? `<button type="button" class="btn ghost compact roles-demote" data-house="${escapeHtml(m.houseId)}">Demote from EC Admin</button>`
              : `${canElevate ? `<button type="button" class="btn secondary compact roles-elevate" data-house="${escapeHtml(m.houseId)}">Elevate to EC Admin</button>` : ''}
                 ${!m.isOfficeBearer ? `<button type="button" class="btn ghost compact roles-make-ob" data-house="${escapeHtml(m.houseId)}">Make Office Bearer</button>` : ''}
                 <button type="button" class="btn ghost compact roles-save-grants" data-house="${escapeHtml(m.houseId)}">Save entitlements</button>`}
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

  let rosterCache = [];

  function renderRosterStats(stats) {
    const line = el('rosterStats');
    if (!line || !stats) return;
    line.textContent = `${stats.total} plots · ${stats.withPhone} with phone · ${stats.missingPhone} missing · ${stats.withEmail} with email`;
  }

  function rosterMatches(r, q, missingOnly) {
    if (missingOnly && r.phone) return false;
    if (!q) return true;
    const hay = `${r.houseId} ${r.plotNo} ${r.title || ''} ${r.name} ${r.profession || ''} ${r.phone || ''} ${r.email || ''} ${r.officialTitle || ''} ${r.role} ${committeeRoleLabel(r)}`.toLowerCase();
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
      tbody.innerHTML = '<tr class="is-empty-row"><td colspan="12" class="muted">No matching residents.</td></tr>';
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
      return `
      <tr data-house="${escapeHtml(r.houseId)}" class="${r.phone ? '' : 'is-missing-phone'}">
        <td class="plot-cell" data-label="Plot"><span class="person-cell">${personAvatarHtml(r)}<span><code>${escapeHtml(r.houseId)}</code><div class="muted plot-section">${escapeHtml(r.section || '')}</div></span></span></td>
        <td data-label="Title"><input name="title" value="${escapeHtml(r.title || '')}" placeholder="Mr/Mrs/Dr" aria-label="Title ${escapeHtml(r.houseId)}"></td>
        <td data-label="Name"><input name="name" value="${escapeHtml(r.name || '')}" aria-label="Name ${escapeHtml(r.houseId)}"></td>
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
        <td data-label="Notes"><input name="notes" value="${escapeHtml(r.notes || '')}" placeholder="notes" aria-label="Notes ${escapeHtml(r.houseId)}"></td>
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
          m.isPrimary ? 'Owner' : (m.relationLabel || m.relation),
          m.viewOnly ? 'View only' : null,
        ].filter(Boolean).join(' · ');
        const actions = canManage && !m.isPrimary ? `
          <div class="btn-row">
            <label class="check compact"><input type="checkbox" class="ec-hh-view-only" data-id="${escapeHtml(m.id)}" ${m.viewOnly ? 'checked' : ''}> View only</label>
            <button type="button" class="btn ghost compact ec-hh-remove" data-id="${escapeHtml(m.id)}">Remove</button>
          </div>` : (m.isPrimary ? '<p class="muted">Primary owner</p>' : '');
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
        }),
      });
      if (el('ecDelegateName')) el('ecDelegateName').value = '';
      if (el('ecDelegateViewOnly')) el('ecDelegateViewOnly').checked = false;
      if (status) status.textContent = `Delegate added for ${hid}.`;
      await loadEcDelegateHousehold();
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not add delegate';
    }
  });

  el('ecDelegateMemberList')?.addEventListener('change', async (event) => {
    const box = event.target.closest('.ec-hh-view-only');
    if (!box) return;
    const hid = ecDelegateHouseId();
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
        <td data-label="When">${escapeHtml((rev.changedAt || '').replace('T', ' ').replace('Z', ''))}</td>
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
        : `SMTP not configured — set App Password in Platform settings (from ${data.from || 'vij.ksh@gmail.com'})`;
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
    if (el('opsBackupRetainDays')) el('opsBackupRetainDays').value = ops.backupRetainDays ?? 14;
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
  }

  function collectOpsSettingsPayload() {
    return {
      alertTo: el('opsAlertTo')?.value.trim() || '',
      vitalsEnabled: Boolean(el('opsVitalsEnabled')?.checked),
      backupRetainDays: Number(el('opsBackupRetainDays')?.value || 14),
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
    };
  }

  function fmtOpsWhen(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
    } catch (_e) {
      return String(iso).slice(0, 16);
    }
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
      const disk = live.diskFreePct ?? '—';
      const mem = live.memAvailablePct ?? '—';
      const load = live.loadRatio ?? '—';
      const adminOk = live.adminServiceActive;
      const ngxOk = live.nginxActive;
      const svc = (ok) => (ok === true ? '✓ active' : (ok === false ? '✗ down' : '—'));
      panel.innerHTML = `
        <div class="ops-status-grid">
          <div><strong>Disk free</strong><span>${escapeHtml(String(disk))}%</span></div>
          <div><strong>Memory avail</strong><span>${escapeHtml(String(mem))}%</span></div>
          <div><strong>Load ratio</strong><span>${escapeHtml(String(load))}</span></div>
          <div><strong>Admin service</strong><span>${escapeHtml(svc(adminOk))}</span></div>
          <div><strong>Nginx</strong><span>${escapeHtml(svc(ngxOk))}</span></div>
          <div><strong>Last backup</strong><span>${lastB.ok === false ? 'Failed' : (lastB.ok ? 'OK' : '—')} · ${escapeHtml(fmtOpsWhen(lastB.at))}</span></div>
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
      el('obsTrailStats').textContent = `${(data.recent || []).length} recent events · since ${(data.since || '').slice(0, 10)}`;
    }
    if (el('obsRecentRows')) {
      el('obsRecentRows').innerHTML = (data.recent || []).length
        ? data.recent.map((e) => {
            const when = String(e.createdAt || '').slice(0, 19).replace('T', ' ');
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
        ops: collectOpsSettingsPayload(),
      };
      const pass = el('settingsSmtpPass')?.value || '';
      if (pass) payload.smtp.password = pass;
      const saPass = el('settingsSaPass')?.value || '';
      if (saPass) payload.superadminPassword = saPass;
      const data = await api('/api/rwa/settings', { method: 'PUT', body: JSON.stringify(payload) });
      if (el('settingsSmtpPass')) el('settingsSmtpPass').value = '';
      if (el('settingsSaPass')) el('settingsSaPass').value = '';
      const smtp = data.settings?.smtp || {};
      if (status) {
        status.textContent = smtp.configured
          ? 'Settings saved. SMTP ready.'
          : 'Settings saved. SMTP still needs an App Password.';
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
      'Install HBC Sanyard on your phone for one-tap access.' +
      ' <button type="button" class="btn secondary compact" id="pwaInstallBtn">Add to Home Screen</button>'
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
      box.textContent = 'Installed. Open HBC Sanyard from your home screen anytime.';
    }
  });
  // iOS Safari has no beforeinstallprompt — show manual tip
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
  if (isIos && !isStandalone) {
    showPwaHint('On iPhone: tap Share → <strong>Add to Home Screen</strong> to install HBC Sanyard.');
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
    const sectionToggle = event.target.closest('.mobile-section-toggle');
    if (sectionToggle && isMobileLayout()) {
      const section = sectionToggle.closest('.mobile-section');
      if (!section) return;
      const open = !section.classList.contains('is-section-collapsed');
      section.classList.toggle('is-section-collapsed', open);
      sectionToggle.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (!open) scrollBelowAppHeader(section.querySelector('.mobile-section-body') || section);
    }
  });

  MOBILE_MQ.addEventListener('change', () => {
    updateAppTopOffset();
    refreshMobileListUi();
  });
  window.addEventListener('resize', updateAppTopOffset);

  prepareMobileSections();
  updateAppTopOffset();
  refreshSession().catch(() => setAuthed(null));
})();
