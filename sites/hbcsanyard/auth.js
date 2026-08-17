/**
 * HBC Sanyard ↔ AuthBuddy Agent auth helper.
 * Session checked via cookie + Bearer session UUID against /agent/v1/session.
 */
(function (global) {
  const DEFAULTS = {
    agentBaseUrl: '',
    idpPublicUrl: 'https://authbuddy.veerlabs.solutions',
    clientId: 'hbcsanyard-web',
    gateAllLearnMore: false,
  };

  let config = Object.assign({}, DEFAULTS);
  let cachedSession = null;
  let policyCache = null;

  function loadConfigFromMeta(meta) {
    const auth = (meta && meta.auth) || {};
    config = Object.assign({}, DEFAULTS, {
      agentBaseUrl: auth.agentBaseUrl != null ? auth.agentBaseUrl : DEFAULTS.agentBaseUrl,
      idpPublicUrl: auth.idpPublicUrl || auth.idpBaseUrl || DEFAULTS.idpPublicUrl,
      clientId: auth.clientId || DEFAULTS.clientId,
      gateAllLearnMore: auth.gateAllLearnMore === true,
    });
  }

  function agentUrl(path) {
    const base = String(config.agentBaseUrl || '').replace(/\/$/, '');
    return base + path;
  }

  function idpUrl(path) {
    return String(config.idpPublicUrl || '').replace(/\/$/, '') + path;
  }

  const SESSION_KEY = 'hbcsanyard_authbuddy_session';

  function savedSessionId() {
    try { return localStorage.getItem(SESSION_KEY) || ''; } catch (_e) { return ''; }
  }

  function saveSessionId(id) {
    try {
      if (id) localStorage.setItem(SESSION_KEY, id);
      else localStorage.removeItem(SESSION_KEY);
    } catch (_e) { /* ignore */ }
  }

  async function fetchJson(path, opts) {
    const headers = Object.assign({ Accept: 'application/json' }, (opts && opts.headers) || {});
    const sid = savedSessionId();
    if (sid && !headers.Authorization) headers.Authorization = 'Bearer ' + sid;
    const res = await fetch(agentUrl(path), Object.assign({
      credentials: 'include',
      headers,
    }, opts || {}, { headers }));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || data.message || ('HTTP ' + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  async function getPolicy() {
    if (policyCache) return policyCache;
    const q = config.clientId ? ('?client_id=' + encodeURIComponent(config.clientId)) : '';
    policyCache = await fetchJson('/agent/v1/policy' + q);
    return policyCache;
  }

  async function getSession(force) {
    if (!force && cachedSession) return cachedSession;
    try {
      cachedSession = await fetchJson('/agent/v1/session');
      // Keep local session id during MFA step-up. Clearing it here caused
      // password→MFA flows to lose Bearer auth and bounce to the dashboard as guest.
      if (cachedSession.authenticated && cachedSession.session && cachedSession.session.session_id) {
        saveSessionId(cachedSession.session.session_id);
      }
    } catch (_e) {
      cachedSession = { authenticated: false, session: null };
    }
    return cachedSession;
  }

  function isAuthenticated(session) {
    return Boolean(session && session.authenticated && session.session);
  }

  function loginUrl(returnTo) {
    const target = returnTo || (global.location.href);
    return agentUrl('/agent/v1/login?return_to=' + encodeURIComponent(target));
  }

  function registerUrl(returnTo) {
    const target = returnTo || (global.location.origin + global.location.pathname.replace(/[^/]*$/, '') + 'auth.html');
    return agentUrl('/agent/v1/register?return_to=' + encodeURIComponent(target));
  }

  function catalogUrl() {
    try {
      return new URL('index.html', global.location.href).href;
    } catch (_e) {
      return '/index.html';
    }
  }

  function logout(returnTo) {
    const target = returnTo || catalogUrl();
    saveSessionId('');
    cachedSession = { authenticated: false, session: null };

    // Full navigation: agent clears the session cookie and 307s back to the
    // catalog so the header remounts in guest mode (no stale Sign out).
    global.location.replace(
      agentUrl('/agent/v1/logout?return_to=' + encodeURIComponent(target))
    );
  }

  function projectRequiresAuth(project) {
    if (config.gateAllLearnMore) return true;
    return project && (project.requireAuth === true || project.requireAuth === 'true');
  }

  async function ensureProjectAccess(slug, project, returnToOverride) {
    if (project && !projectRequiresAuth(project)) return true;
    const session = await getSession(true);
    if (isAuthenticated(session)) return true;
    let returnTo = returnToOverride || global.location.href;
    try {
      // Prefer absolute same-origin destinations (Learn more → project.html).
      returnTo = new URL(returnTo, global.location.href).href;
    } catch (_e) { /* keep as-is */ }
    const authPage = new URL('auth.html', global.location.href);
    authPage.searchParams.set('return_to', returnTo);
    if (slug) authPage.searchParams.set('project', slug);
    global.location.href = authPage.toString();
    return false;
  }

  function ensureTopbarShell() {
    const topbar = document.querySelector('.site-topbar');
    if (!topbar) return null;

    let nav = topbar.querySelector('.topbar-nav');
    if (!nav) {
      nav = document.createElement('nav');
      nav.className = 'topbar-nav';
      nav.setAttribute('aria-label', 'Primary');
      topbar.appendChild(nav);
    }

    let catalog = nav.querySelector('[data-nav="catalog"]');
    if (!catalog) {
      catalog = document.createElement('a');
      catalog.className = 'topbar-link';
      catalog.dataset.nav = 'catalog';
      catalog.href = 'index.html';
      catalog.textContent = 'Catalog';
      nav.appendChild(catalog);
    }

    let contact = document.getElementById('contactOpenBtn');
    if (!contact) {
      contact = document.createElement('button');
      contact.type = 'button';
      contact.id = 'contactOpenBtn';
      contact.className = 'topbar-link topbar-link-btn';
      contact.textContent = 'Contact';
    } else {
      contact.className = 'topbar-link topbar-link-btn';
    }
    if (contact.parentElement !== nav) nav.appendChild(contact);

    let auth = topbar.querySelector('.topbar-auth');
    if (!auth) {
      auth = document.createElement('div');
      auth.className = 'topbar-auth';
      auth.id = 'topbarAuth';
      auth.setAttribute('data-state', 'loading');
      auth.innerHTML = `
        <div class="topbar-auth-guest" hidden>
          <a class="topbar-link" data-auth="signin" href="auth.html">Sign in</a>
          <a class="btn topbar-cta" data-auth="register" href="auth.html?mode=register">Register</a>
        </div>
        <div class="topbar-auth-user" hidden>
          <span class="topbar-user" data-auth="user" title=""></span>
          <button type="button" class="btn topbar-signout" data-auth="logout">Sign out</button>
        </div>`;
      topbar.appendChild(auth);
    }

    // Drop legacy chip rows so Sign in / Register / Contact don't pile up.
    const legacyMeta = topbar.querySelector('.topbar-meta');
    if (legacyMeta) legacyMeta.remove();

    return auth;
  }

  function renderAuthState(authEl, session) {
    const guest = authEl.querySelector('.topbar-auth-guest');
    const userBox = authEl.querySelector('.topbar-auth-user');
    const user = authEl.querySelector('[data-auth="user"]');
    const logoutBtn = authEl.querySelector('[data-auth="logout"]');
    const signedIn = isAuthenticated(session);
    const path = (global.location.pathname || '').toLowerCase();
    const onAuthPage = path.endsWith('auth.html');

    // Mutually exclusive: guest CTAs OR account+sign-out — never both.
    // On the auth page itself, hide guest CTAs (the form already covers that).
    authEl.setAttribute('data-state', signedIn ? 'user' : 'guest');
    if (guest) guest.hidden = signedIn || onAuthPage;
    if (userBox) userBox.hidden = !signedIn;

    if (signedIn && user) {
      const label = session.session.username || session.session.email || 'Account';
      user.textContent = label;
      user.title = session.session.email || label;
    }

    if (logoutBtn && !logoutBtn.dataset.bound) {
      logoutBtn.dataset.bound = '1';
      logoutBtn.addEventListener('click', (event) => {
        event.preventDefault();
        logoutBtn.disabled = true;
        logoutBtn.textContent = 'Signing out…';
        logout();
      });
    }
  }

  function mountTopbarAuth() {
    const authEl = ensureTopbarShell();
    if (!authEl) return;

    // Mark active nav
    const path = (global.location.pathname || '').toLowerCase();
    const catalog = authEl.parentElement && authEl.parentElement.querySelector('[data-nav="catalog"]');
    if (catalog) {
      const onCatalog = path.endsWith('/') || path.endsWith('index.html') || path === '';
      const onAuth = path.endsWith('auth.html');
      catalog.classList.toggle('is-active', onCatalog && !onAuth);
      catalog.setAttribute('aria-current', onCatalog && !onAuth ? 'page' : 'false');
    }

    renderAuthState(authEl, { authenticated: false, session: null });
    getSession(true).then((session) => {
      renderAuthState(authEl, session);
    });
  }

  async function idpPost(path, body) {
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
    const sid = savedSessionId();
    if (sid) headers.Authorization = 'Bearer ' + sid;
    const res = await fetch(agentUrl(path), {
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify(body == null ? {} : body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.message || data.error || ('HTTP ' + res.status));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    if (data.session_id) saveSessionId(data.session_id);
    return data;
  }

  const VeerAuth = {
    config: () => config,
    loadConfigFromMeta,
    getPolicy,
    getSession,
    isAuthenticated,
    loginUrl,
    registerUrl,
    logout,
    projectRequiresAuth,
    ensureProjectAccess,
    mountTopbarAuth,
    idpPost,
    agentUrl,
    idpUrl,
    saveSessionId,
    savedSessionId,
    biometricContinueLabel,
    authenticateWithPasskey,
  };

  function extractPublicKeyOptions(publicKey) {
    if (!publicKey) return publicKey;
    return publicKey.publicKey || publicKey.public_key || publicKey;
  }

  async function loadWebAuthn() {
    return import('https://cdn.jsdelivr.net/npm/@simplewebauthn/browser@13.1.2/+esm');
  }

  function biometricContinueLabel() {
    const ua = navigator.userAgent || '';
    if (/iPhone|iPad/.test(ua)) return 'Continue with Face ID';
    if (/Android/.test(ua)) return 'Continue with fingerprint';
    if (/Mac/.test(ua)) return 'Continue with Touch ID';
    return 'Continue with Face ID / fingerprint';
  }

  async function authenticateWithPasskey(username) {
    const user = String(username || '').trim();
    if (!user) throw new Error('Username required for Face ID / fingerprint');
    const begin = await idpPost('/auth/passkey/authenticate/begin', { username: user });
    const webauthn = await loadWebAuthn();
    const assertion = await webauthn.startAuthentication({
      optionsJSON: extractPublicKeyOptions(begin.public_key),
    });
    return idpPost('/auth/passkey/authenticate/complete', {
      challenge_id: begin.challenge_id,
      public_key: assertion,
    });
  }

  global.VeerAuth = VeerAuth;

  document.addEventListener('DOMContentLoaded', () => {
    const apply = (meta) => {
      loadConfigFromMeta(meta || {});
      if (document.querySelector('.site-topbar, .topbar-auth')) {
        mountTopbarAuth();
      }
    };
    fetch('site-meta.json')
      .then((r) => r.json())
      .then(apply)
      .catch(() => apply({}));
  });
})(window);
