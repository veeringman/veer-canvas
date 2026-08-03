/**
 * Public engagement (likes/dislikes/comments) + contact modal + Learn More access gate.
 */
(function (global) {
  const VISITOR_KEY = 'veerlabs-visitor-id';
  const TOKEN_KEY = 'veerlabs-visitor-token';
  const TOKEN_EXP_KEY = 'veerlabs-visitor-token-exp';
  const SESSION_KEY = 'veerlabs-visit-session';

  function visitorId() {
    try {
      let id = localStorage.getItem(VISITOR_KEY);
      if (!id || !/^[a-zA-Z0-9_-]{8,80}$/.test(id)) {
        id = `v_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`.slice(0, 32);
        localStorage.setItem(VISITOR_KEY, id);
      }
      return id;
    } catch (_err) {
      return `v_${Date.now().toString(36)}`;
    }
  }

  function sessionId() {
    try {
      let id = sessionStorage.getItem(SESSION_KEY);
      if (!id || !/^[a-zA-Z0-9_-]{8,64}$/.test(id)) {
        id = `s_${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`.slice(0, 32);
        sessionStorage.setItem(SESSION_KEY, id);
      }
      return id;
    } catch (_err) {
      return `s_${Date.now().toString(36)}`;
    }
  }

  function utmParams() {
    try {
      const params = new URLSearchParams(window.location.search || '');
      return {
        source: params.get('utm_source') || '',
        medium: params.get('utm_medium') || '',
        campaign: params.get('utm_campaign') || '',
      };
    } catch (_err) {
      return { source: '', medium: '', campaign: '' };
    }
  }

  function trackVisit(extra = {}) {
    const path = window.location.pathname || '/';
    const search = window.location.search || '';
    let page = 'other';
    let slug = String(extra.slug || '');
    if (/project\.html$/i.test(path)) {
      page = 'project';
      if (!slug) {
        try {
          slug = new URLSearchParams(search).get('slug') || '';
        } catch (_err) { /* ignore */ }
      }
    } else if (path === '/' || /index\.html$/i.test(path) || path === '') {
      page = 'home';
    }
    const payload = {
      visitorId: visitorId(),
      sessionId: sessionId(),
      path: path + (search ? search.slice(0, 120) : ''),
      page,
      slug,
      title: document.title || '',
      referrer: document.referrer || '',
      userAgent: navigator.userAgent || '',
      language: navigator.language || '',
      timezone: (Intl.DateTimeFormat().resolvedOptions().timeZone) || '',
      screenW: window.screen ? window.screen.width : 0,
      screenH: window.screen ? window.screen.height : 0,
      utm: utmParams(),
      website: '', // honeypot empty
      ...extra,
    };
    const body = JSON.stringify(payload);
    const headers = { 'Content-Type': 'application/json' };
    const token = storedToken();
    if (token) headers['X-Visitor-Token'] = token;
    try {
      if (navigator.sendBeacon) {
        // sendBeacon cannot set custom headers; include token in body for auth
        const withToken = JSON.stringify({ ...payload, token: token || '' });
        const ok = navigator.sendBeacon('/api/public/visit', new Blob([withToken], { type: 'application/json' }));
        if (ok) return Promise.resolve({ ok: true, beacon: true });
      }
    } catch (_err) { /* fall through */ }
    return fetch('/api/public/visit', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body,
      keepalive: true,
    }).then((r) => r.json().catch(() => ({ ok: false }))).catch(() => ({ ok: false }));
  }

  function storedToken() {
    try {
      const token = localStorage.getItem(TOKEN_KEY) || '';
      const exp = localStorage.getItem(TOKEN_EXP_KEY) || '';
      if (!token || !exp) return '';
      if (Date.parse(exp) <= Date.now()) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(TOKEN_EXP_KEY);
        return '';
      }
      return token;
    } catch (_err) {
      return '';
    }
  }

  function saveToken(token, expiresAt) {
    try {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(TOKEN_EXP_KEY, expiresAt || '');
    } catch (_err) { /* ignore */ }
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const token = storedToken();
    if (token) headers['X-Visitor-Token'] = token;
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers,
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || response.statusText || `HTTP ${response.status}`);
    return data;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatCount(n) {
    const num = Number(n) || 0;
    if (num >= 1000) return `${(num / 1000).toFixed(1).replace(/\.0$/, '')}k`;
    return String(num);
  }

  let pendingNavigate = null;

  function ensureAccessModal() {
    if (document.getElementById('accessModal')) return;
    const modal = document.createElement('div');
    modal.id = 'accessModal';
    modal.className = 'contact-modal';
    modal.hidden = true;
    modal.innerHTML = `
      <div class="contact-modal-backdrop" data-access-close="1"></div>
      <div class="contact-modal-card" role="dialog" aria-modal="true" aria-labelledby="accessTitle">
        <header>
          <h2 id="accessTitle">Temporary access</h2>
          <button type="button" class="contact-close" data-access-close="1" aria-label="Close">×</button>
        </header>
        <p class="muted">This project requires sign-in. Use an admin session, or request a 1-hour visitor access token.</p>
        <p class="field-hint" id="accessAdminHint" hidden></p>
        <form id="accessForm" class="contact-form">
          <input type="text" name="website" class="hp-field" tabindex="-1" autocomplete="off" aria-hidden="true"/>
          <label>Name<input name="name" required maxlength="80" autocomplete="name"/></label>
          <label>Email<input name="email" type="email" required maxlength="120" autocomplete="email"/></label>
          <div class="editor-actions">
            <button type="submit" class="btn primary compact" id="accessSubmitBtn">Get 1-hour access</button>
            <button type="button" class="btn secondary compact" id="accessContinueAdminBtn" hidden>Continue as admin</button>
            <button type="button" class="btn ghost compact" data-access-close="1">Cancel</button>
          </div>
          <p class="field-hint access-status" hidden></p>
        </form>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (event) => {
      if (event.target && event.target.dataset && event.target.dataset.accessClose) closeAccessModal();
    });
    modal.querySelector('#accessForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const status = form.querySelector('.access-status');
      const fd = new FormData(form);
      const renew = Boolean(storedToken());
      try {
        const data = await api('/api/public/access/token', {
          method: 'POST',
          body: JSON.stringify({
            name: fd.get('name'),
            email: fd.get('email'),
            website: fd.get('website'),
            visitorId: visitorId(),
            slug: (pendingNavigate && pendingNavigate.slug) || '',
            renew,
          }),
        });
        saveToken(data.token, data.expiresAt);
        if (status) {
          status.hidden = false;
          status.textContent = 'Access granted until ' + String(data.expiresAt || '').replace('T', ' ').slice(0, 16) + ' UTC.';
        }
        await finishPendingNavigate();
      } catch (error) {
        if (status) {
          status.hidden = false;
          status.textContent = error.message || 'Could not issue access token';
        }
      }
    });
    modal.querySelector('#accessContinueAdminBtn').addEventListener('click', async () => {
      await finishPendingNavigate();
    });
  }

  function openAccessModal(opts) {
    opts = opts || {};
    ensureAccessModal();
    pendingNavigate = { slug: opts.slug, href: opts.href };
    const modal = document.getElementById('accessModal');
    const adminBtn = document.getElementById('accessContinueAdminBtn');
    const form = document.getElementById('accessForm');
    const hint = document.getElementById('accessAdminHint');
    const status = modal.querySelector('.access-status');
    if (status) status.hidden = true;
    modal.hidden = false;
    api('/api/public/access/status?slug=' + encodeURIComponent(opts.slug || '') + '&visitorId=' + encodeURIComponent(visitorId()))
      .then((data) => {
        const isAdmin = data.mode === 'admin' && data.authorized;
        adminBtn.hidden = !isAdmin;
        hint.hidden = !isAdmin;
        hint.textContent = isAdmin ? 'Admin session detected — you can continue without a visitor token.' : '';
        form.hidden = isAdmin;
        if (!isAdmin && data.authorized && data.mode === 'visitor') finishPendingNavigate();
      })
      .catch(() => {
        adminBtn.hidden = true;
        form.hidden = false;
      });
  }

  function closeAccessModal() {
    const modal = document.getElementById('accessModal');
    if (modal) modal.hidden = true;
    pendingNavigate = null;
  }

  async function finishPendingNavigate() {
    const pending = pendingNavigate;
    if (!pending || !pending.href) {
      closeAccessModal();
      return;
    }
    try {
      if (pending.slug) {
        await api('/api/public/access/gate', {
          method: 'POST',
          body: JSON.stringify({
            slug: pending.slug,
            visitorId: visitorId(),
            token: storedToken(),
            event: 'learn_more',
          }),
        });
      }
      const href = pending.href;
      pendingNavigate = null;
      closeAccessModal();
      window.location.href = href;
    } catch (error) {
      const status = document.querySelector('#accessForm .access-status');
      if (status) {
        status.hidden = false;
        status.textContent = error.message || 'Access denied';
      }
    }
  }

  async function ensureProjectAccess(slug) {
    if (!slug) return true;
    const status = await api('/api/public/access/status?slug=' + encodeURIComponent(slug) + '&visitorId=' + encodeURIComponent(visitorId()));
    if (!status.requireAuth) return true;
    if (status.authorized) {
      await api('/api/public/access/gate', {
        method: 'POST',
        body: JSON.stringify({
          slug,
          visitorId: visitorId(),
          token: storedToken(),
          event: 'project_view',
        }),
      });
      return true;
    }
    return new Promise((resolve) => {
      openAccessModal({ slug, href: window.location.href });
      const timer = setInterval(async () => {
        try {
          const again = await api('/api/public/access/status?slug=' + encodeURIComponent(slug) + '&visitorId=' + encodeURIComponent(visitorId()));
          if (again.authorized) {
            clearInterval(timer);
            closeAccessModal();
            await api('/api/public/access/gate', {
              method: 'POST',
              body: JSON.stringify({
                slug,
                visitorId: visitorId(),
                token: storedToken(),
                event: 'project_view',
              }),
            });
            resolve(true);
          }
        } catch (_err) { /* keep waiting */ }
      }, 800);
      document.getElementById('accessModal').addEventListener('click', (event) => {
        if (event.target && event.target.dataset && event.target.dataset.accessClose) {
          clearInterval(timer);
          resolve(false);
        }
      }, { once: true });
    });
  }

  function bindLearnMoreGates(root) {
    const scope = root || document;
    scope.querySelectorAll('.learn-more-btn[data-require-auth="1"], a.is-gated[data-require-auth="1"]').forEach((link) => {
      if (link.dataset.gateBound === '1') return;
      link.dataset.gateBound = '1';
      link.addEventListener('click', async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const href = link.getAttribute('href') || '';
        const match = href.match(/[?&]project=([^&]+)/);
        const slug = match ? decodeURIComponent(match[1]) : ((link.closest('[data-slug]') || {}).dataset || {}).slug || '';

        // Prefer AuthBuddy Agent session over legacy visitor tokens.
        if (window.VeerAuth && typeof window.VeerAuth.ensureProjectAccess === 'function') {
          try {
            const session = await window.VeerAuth.getSession(true);
            if (window.VeerAuth.isAuthenticated(session)) {
              window.location.href = href;
              return;
            }
          } catch (_e) { /* fall through to auth hub */ }
          const authPage = new URL('auth.html', window.location.href);
          authPage.searchParams.set('return_to', new URL(href, window.location.href).toString());
          if (slug) authPage.searchParams.set('project', slug);
          window.location.href = authPage.toString();
          return;
        }

        try {
          const status = await api('/api/public/access/status?slug=' + encodeURIComponent(slug) + '&visitorId=' + encodeURIComponent(visitorId()));
          if (!status.requireAuth || status.authorized) {
            pendingNavigate = { slug, href };
            await finishPendingNavigate();
            return;
          }
          openAccessModal({ slug, href });
        } catch (_err) {
          openAccessModal({ slug, href });
        }
      });
    });
  }

  function renderEngageBar(row, slug, stats, opts) {
    opts = opts || {};
    const detailLink = opts.detailLink;
    if (!row || !slug) return;
    const vote = (stats && stats.vote) || null;
    const commentInner = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg><span data-count="comments">' + formatCount(stats && stats.commentCount) + '</span>';
    row.innerHTML =
      '<button type="button" class="engage-btn engage-like' + (vote === 'like' ? ' is-active' : '') + '" data-action="like" aria-label="Like">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg>' +
      '<span data-count="likes">' + formatCount(stats && stats.likes) + '</span></button>' +
      '<button type="button" class="engage-btn engage-dislike' + (vote === 'dislike' ? ' is-active' : '') + '" data-action="dislike" aria-label="Dislike">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg>' +
      '<span data-count="dislikes">' + formatCount(stats && stats.dislikes) + '</span></button>' +
      (detailLink
        ? '<a class="engage-btn engage-comment" href="' + detailLink + '">' + commentInner + '</a>'
        : '<span class="engage-btn engage-comment is-static">' + commentInner + '</span>');

    row.querySelectorAll('button[data-action]').forEach((btn) => {
      btn.addEventListener('click', async (event) => {
        event.preventDefault();
        event.stopPropagation();
        try {
          const data = await api('/api/public/engagement/' + encodeURIComponent(slug) + '/vote', {
            method: 'POST',
            body: JSON.stringify({ action: btn.dataset.action, visitorId: visitorId() }),
          });
          renderEngageBar(row, slug, data, { detailLink });
        } catch (error) {
          alert(error.message || 'Could not save vote');
        }
      });
    });
  }

  function mountTileActions(cardEl, slug, stats) {
    if (!cardEl || !slug) return;
    let row = cardEl.querySelector('.project-engage');
    if (!row) {
      row = document.createElement('div');
      row.className = 'project-engage';
      const footer = cardEl.querySelector('.project-card-footer');
      if (footer) footer.parentNode.insertBefore(row, footer);
      else {
        const copy = cardEl.querySelector('.project-copy');
        if (copy) copy.appendChild(row);
      }
    }
    renderEngageBar(row, slug, stats, {
      detailLink: 'project.html?project=' + encodeURIComponent(slug) + '#comments',
    });
  }

  async function hydrateTiles(root) {
    const scope = root || document;
    const cards = Array.prototype.slice.call(scope.querySelectorAll('.project-card'));
    if (!cards.length) return;
    let map = {};
    try {
      const data = await api('/api/public/engagement?visitorId=' + encodeURIComponent(visitorId()));
      map = data.projects || {};
    } catch (_err) {
      map = {};
    }
    cards.forEach((card) => {
      const link = card.querySelector('.learn-more-btn, a[href*="project="]');
      const href = (link && link.getAttribute('href')) || '';
      const match = href.match(/[?&]project=([^&]+)/);
      const slug = match ? decodeURIComponent(match[1]) : (card.dataset.slug || '');
      if (!slug) return;
      mountTileActions(card, slug, map[slug] || { likes: 0, dislikes: 0, commentCount: 0, vote: null });
    });
    bindLearnMoreGates(scope);
  }

  function renderCommentsList(container, comments) {
    if (!container) return;
    if (!comments.length) {
      container.innerHTML = '<p class="engage-empty">No comments yet — be the first.</p>';
      return;
    }
    container.innerHTML = comments.map((c) =>
      '<article class="comment-item"><header><strong>' + escapeHtml(c.name || 'Guest') +
      '</strong><time>' + escapeHtml(String(c.createdAt || '').slice(0, 10)) +
      '</time></header><p>' + escapeHtml(c.text || '') + '</p></article>'
    ).join('');
  }

  async function mountProjectEngagement(slug) {
    if (!slug) return;
    const host = document.getElementById('project-engagement');
    if (!host) return;
    host.innerHTML =
      '<div class="project-engage project-engage-detail" id="projectEngageBar"></div>' +
      '<section class="comments-panel" id="comments"><h2>Comments</h2>' +
      '<div class="comments-list" id="commentsList"><p class="engage-empty">Loading…</p></div>' +
      '<form class="comment-form" id="commentForm">' +
      '<input type="text" name="website" class="hp-field" tabindex="-1" autocomplete="off" aria-hidden="true"/>' +
      '<label>Name<input name="name" maxlength="60" placeholder="Your name" required/></label>' +
      '<label>Comment<textarea name="text" rows="3" maxlength="1000" placeholder="Share feedback on this project" required></textarea></label>' +
      '<button type="submit" class="btn primary compact learn-more-btn" style="border:0">Post comment</button>' +
      '<p class="field-hint comment-status" hidden></p></form></section>';

    const bar = host.querySelector('#projectEngageBar');
    const list = host.querySelector('#commentsList');
    const form = host.querySelector('#commentForm');

    async function refresh() {
      const data = await api('/api/public/engagement/' + encodeURIComponent(slug) + '?visitorId=' + encodeURIComponent(visitorId()) + '&comments=1');
      renderEngageBar(bar, slug, data, { detailLink: null });
      renderCommentsList(list, data.comments || []);
      return data;
    }

    try {
      await refresh();
    } catch (error) {
      if (list) list.innerHTML = '<p class="error-message">' + escapeHtml(error.message) + '</p>';
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const status = form.querySelector('.comment-status');
      const fd = new FormData(form);
      try {
        await api('/api/public/engagement/' + encodeURIComponent(slug) + '/comments', {
          method: 'POST',
          body: JSON.stringify({
            name: fd.get('name'),
            text: fd.get('text'),
            website: fd.get('website'),
            visitorId: visitorId(),
          }),
        });
        form.reset();
        if (status) {
          status.hidden = false;
          status.textContent = 'Thanks — comment posted.';
        }
        await refresh();
      } catch (error) {
        if (status) {
          status.hidden = false;
          status.textContent = error.message || 'Could not post comment';
        }
      }
    });
  }

  function ensureContactModal() {
    if (document.getElementById('contactModal')) return;
    const modal = document.createElement('div');
    modal.id = 'contactModal';
    modal.className = 'contact-modal';
    modal.hidden = true;
    modal.innerHTML =
      '<div class="contact-modal-backdrop" data-close="1"></div>' +
      '<div class="contact-modal-card" role="dialog" aria-modal="true" aria-labelledby="contactTitle">' +
      '<header><h2 id="contactTitle">Contact VeerLabs</h2>' +
      '<button type="button" class="contact-close" data-close="1" aria-label="Close">×</button></header>' +
      '<p class="muted">Send a message about a project, partnership, or general inquiry.</p>' +
      '<form id="contactForm" class="contact-form">' +
      '<input type="text" name="website" class="hp-field" tabindex="-1" autocomplete="off" aria-hidden="true"/>' +
      '<label>Name<input name="name" required maxlength="80" autocomplete="name"/></label>' +
      '<label>Email<input name="email" type="email" required maxlength="120" autocomplete="email"/></label>' +
      '<label>Message<textarea name="message" rows="4" required maxlength="4000" placeholder="How can we help?"></textarea></label>' +
      '<div class="editor-actions">' +
      '<button type="submit" class="btn primary compact">Send message</button>' +
      '<button type="button" class="btn ghost compact" data-close="1">Cancel</button></div>' +
      '<p class="field-hint contact-status" hidden></p></form></div>';
    document.body.appendChild(modal);
    modal.addEventListener('click', (event) => {
      if (event.target && event.target.dataset && event.target.dataset.close) closeContactModal();
    });
    modal.querySelector('#contactForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const status = form.querySelector('.contact-status');
      const fd = new FormData(form);
      try {
        await api('/api/public/contact', {
          method: 'POST',
          body: JSON.stringify({
            name: fd.get('name'),
            email: fd.get('email'),
            message: fd.get('message'),
            website: fd.get('website'),
          }),
        });
        form.reset();
        if (status) {
          status.hidden = false;
          status.textContent = 'Message sent — thank you.';
        }
        setTimeout(closeContactModal, 1200);
      } catch (error) {
        if (status) {
          status.hidden = false;
          status.textContent = error.message || 'Could not send message';
        }
      }
    });
  }

  function openContactModal() {
    ensureContactModal();
    document.getElementById('contactModal').hidden = false;
  }

  function closeContactModal() {
    const modal = document.getElementById('contactModal');
    if (modal) modal.hidden = true;
  }

  function mountContactButton() {
    // Prefer the dedicated topbar nav slot created by auth.js.
    let btn = document.getElementById('contactOpenBtn');
    if (!btn) {
      const nav = document.querySelector('.topbar-nav') || document.querySelector('.site-topbar');
      if (!nav) return;
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'contactOpenBtn';
      btn.className = 'topbar-link topbar-link-btn';
      btn.textContent = 'Contact';
      nav.appendChild(btn);
    }
    if (!btn.dataset.contactBound) {
      btn.dataset.contactBound = '1';
      btn.addEventListener('click', openContactModal);
    }
    ensureContactModal();
  }

  global.VeerEngage = {
    hydrateTiles,
    mountProjectEngagement,
    mountContactButton,
    openContactModal,
    bindLearnMoreGates,
    ensureProjectAccess,
    visitorId,
    trackVisit,
  };

  document.addEventListener('DOMContentLoaded', () => {
    mountContactButton();
    trackVisit();
  });
})(window);
