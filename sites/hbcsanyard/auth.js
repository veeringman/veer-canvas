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
    // Shared Drive folder — drop the latest BuddyAuthenticator.apk here (Anyone with the link).
    buddyAuthenticatorApkUrl: 'https://drive.google.com/drive/folders/1ywOGks8jBiIUDrV9pmi2NGDD_I0O06Ep?usp=share_link',
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
      buddyAuthenticatorApkUrl: auth.buddyAuthenticatorApkUrl || DEFAULTS.buddyAuthenticatorApkUrl,
    });
  }

  function agentUrl(path) {
    const base = String(config.agentBaseUrl || '').replace(/\/$/, '');
    return base + path;
  }

  function idpUrl(path) {
    return String(config.idpPublicUrl || '').replace(/\/$/, '') + path;
  }

  function pwaUrl() {
    return idpUrl('/authenticator/');
  }

  function apkUrl() {
    return String(config.buddyAuthenticatorApkUrl || DEFAULTS.buddyAuthenticatorApkUrl || '').trim();
  }

  function applyAuthbuddyHelpLinks() {
    const pwa = pwaUrl();
    const apk = apkUrl();
    document.querySelectorAll('[data-authbuddy-pwa-href]').forEach((a) => {
      a.href = pwa;
    });
    document.querySelectorAll('[data-authbuddy-apk-href]').forEach((a) => {
      a.href = apk || '#';
      a.hidden = !apk;
    });
  }

  function authbuddyManualBodyInnerHtml() {
    return (
      '<p><strong>Do this first.</strong> TOTP codes, QR / number match, passkeys in the app, and Hybrid PQC only work after you add AuthBuddy as an application and sign in from <strong>Settings</strong>.</p>'
      + '<h4>1. Add the app and sign in</h4>'
      + '<ol>'
      + '<li>Install BuddyAuthenticator — Web App (PWA) or the Android app from Google Drive.</li>'
      + '<li>Open <strong>Settings</strong>.</li>'
      + '<li>Tap <strong>Add application / sign in</strong> (or <strong>Manage applications &amp; sign-in</strong>).</li>'
      + '<li>Register or sign in with the <strong>same email</strong> as this plot member.</li>'
      + '<li>Leave that application <strong>Active</strong>. If Approvals says to sign in first, this step is missing.</li>'
      + '</ol>'
      + '<h4>2. TOTP — 6-digit codes</h4>'
      + '<p>Time-based codes that change about every 30 seconds.</p>'
      + '<ol>'
      + '<li>On the portal or AuthBuddy, start authenticator setup. A QR code or secret key appears.</li>'
      + '<li>In BuddyAuthenticator open <strong>Codes</strong> → <strong>+</strong> → Scan QR, or enter the setup key. You can also enrol from Settings after you are signed in.</li>'
      + '<li>When logging in, open <strong>Codes</strong> and type the current 6-digit number before it rolls over.</li>'
      + '<li>iPhone without BuddyAuthenticator: Google Authenticator or Microsoft Authenticator can store <em>TOTP only</em> — not QR / number match, HOTP, or Hybrid PQC.</li>'
      + '</ol>'
      + '<h4>3. HOTP — counter codes</h4>'
      + '<p>If the login asks for a counter code, open <strong>Codes</strong>, enter the number, then tap <strong>Next</strong> in the app after each successful login.</p>'
      + '<h4>4. Passkeys (Face ID / fingerprint)</h4>'
      + '<ul>'
      + '<li>On the colony login page you can use Face ID / fingerprint in the <strong>browser</strong> without the app.</li>'
      + '<li>In BuddyAuthenticator: open <strong>Passkeys</strong> → register, then <strong>Sign in with passkey</strong>. You must already be signed in under Settings → Applications.</li>'
      + '<li>Do not turn on <strong>Authenticator-only</strong> in Settings — that hides passkeys and Hybrid PQC.</li>'
      + '</ul>'
      + '<h4>5. QR / number match (Approvals)</h4>'
      + '<p>This is the usual phone-approve login. It needs BuddyAuthenticator signed in — Google / Microsoft Authenticator cannot do this.</p>'
      + '<ol>'
      + '<li>Stay signed in under Settings → Applications. Keep <strong>Device approvals (QR + number match)</strong> on in Settings.</li>'
      + '<li>On the colony or AuthBuddy login page choose Continue with AuthBuddy / Approve. A <strong>two-digit number</strong> and a QR appear.</li>'
      + '<li><strong>Number match (same phone or another phone):</strong> open BuddyAuthenticator → <strong>Approvals</strong>. Confirm the number matches the website, then tap <strong>Approve</strong>. If nothing is listed, tap <strong>Refresh</strong>.</li>'
      + '<li><strong>QR scan (best when logging in on a computer):</strong> on the phone tap Approvals → <strong>Scan QR to approve</strong> and point at the computer screen. If the camera is blocked, use <strong>Take photo</strong>.</li>'
      + '<li>If you are already on the phone login page, do <em>not</em> scan your own screen — use number match, or tap <strong>Approve in BuddyAuthenticator</strong> when that button is shown.</li>'
      + '</ol>'
      + '<h4>6. Hybrid PQC (advanced)</h4>'
      + '<p>Post-quantum-ready keys that stay on this phone. Password + this method on the website.</p>'
      + '<ol>'
      + '<li>Sign in under Settings → Applications (password is enough to enrol keys).</li>'
      + '<li>Open <strong>Hybrid PQC</strong> → generate and enrol keys once.</li>'
      + '<li>On the website choose Hybrid PQC after password, then return to the app and approve the pending challenge.</li>'
      + '</ol>'
    );
  }

  function authbuddyManualHtml() {
    return (
      '<details class="authbuddy-manual">'
      + '<summary>'
      + '<span class="authbuddy-imp-mark"><span aria-hidden="true">!</span> Important</span>'
      + '<span class="authbuddy-manual-title">BuddyAuthenticator user manual</span>'
      + '</summary>'
      + '<div class="authbuddy-manual-body">'
      + '<div class="authbuddy-manual-actions">'
      + '<button type="button" class="btn ghost compact" data-save-authbuddy-manual>Save file</button>'
      + '<button type="button" class="btn ghost compact" data-print-authbuddy-manual>Print / PDF</button>'
      + '</div>'
      + authbuddyManualBodyInnerHtml()
      + '</div>'
      + '</details>'
    );
  }

  function authbuddyManualPrintableHtml() {
    const pwa = pwaUrl();
    const apk = apkUrl();
    const when = new Date().toISOString().slice(0, 10);
    return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
      + '<meta name="viewport" content="width=device-width, initial-scale=1">'
      + '<title>BuddyAuthenticator user manual</title>'
      + '<style>'
      + 'body{font:16px/1.5 -apple-system,BlinkMacSystemFont,"Noto Sans",sans-serif;color:#1a2a3a;max-width:40rem;margin:1.25rem auto;padding:0 1rem 2rem}'
      + 'h1{font-size:1.35rem;margin:0 0 .35rem} h4{font-size:1.02rem;margin:1.1rem 0 .35rem;color:#12243a}'
      + '.muted{color:#5c6b7a;font-size:.92rem} ol,ul{padding-left:1.2rem} li{margin:.25rem 0}'
      + '.actions{display:flex;gap:.5rem;flex-wrap:wrap;margin:0 0 1rem}'
      + '.actions button{font:inherit;padding:.4rem .7rem;border-radius:8px;border:1px solid #c9d2dc;background:#fff;cursor:pointer}'
      + '@media print{.actions{display:none} body{margin:0}}'
      + '</style></head><body>'
      + '<div class="actions"><button type="button" onclick="window.print()">Print / Save PDF</button></div>'
      + '<h1>BuddyAuthenticator user manual</h1>'
      + '<p class="muted">Himuda Housing Colony Sanyard · saved ' + when + '</p>'
      + '<p>Install the Web App (PWA): <a href="' + pwa + '">' + pwa + '</a>'
      + (apk ? '<br>Android app (.apk): <a href="' + apk + '">' + apk + '</a>' : '')
      + '</p>'
      + authbuddyManualBodyInnerHtml()
      + '<p class="muted">Email passcode on the colony portal still works anytime.</p>'
      + '</body></html>';
  }

  function downloadAuthbuddyManualFile() {
    const blob = new Blob([authbuddyManualPrintableHtml()], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'BuddyAuthenticator-user-manual.html';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2500);
  }

  function openAuthbuddyManualWindow() {
    const html = authbuddyManualPrintableHtml();
    const w = window.open('', '_blank');
    if (!w) return null;
    w.document.open();
    w.document.write(html);
    w.document.close();
    return w;
  }

  function saveAuthbuddyManual() {
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent || '');
    if (ios) {
      const w = openAuthbuddyManualWindow();
      if (w) return;
    }
    downloadAuthbuddyManualFile();
  }

  function printAuthbuddyManual() {
    const w = openAuthbuddyManualWindow();
    if (w) {
      setTimeout(function () {
        try { w.focus(); w.print(); } catch (_e) { /* ignore */ }
      }, 350);
      return;
    }
    downloadAuthbuddyManualFile();
  }

  function renderAuthbuddyManuals() {
    document.querySelectorAll('[data-authbuddy-manual-host]').forEach((el) => {
      if (el.dataset.authbuddyManualReady) return;
      el.dataset.authbuddyManualReady = '1';
      el.innerHTML = authbuddyManualHtml();
    });
  }

  function ensureAuthbuddyHelpDialog() {
    const dialog = document.getElementById('authbuddyHelpDialog');
    if (dialog && dialog.parentElement !== document.body) {
      document.body.appendChild(dialog);
    }
    return dialog;
  }

  function openAuthbuddyHelp() {
    applyAuthbuddyHelpLinks();
    const dialog = ensureAuthbuddyHelpDialog();
    if (!dialog) return;
    try {
      if (typeof dialog.showModal === 'function') {
        if (!dialog.open) dialog.showModal();
        return;
      }
    } catch (_e) { /* hidden ancestor / already open */ }
    dialog.hidden = false;
  }

  function closeAuthbuddyHelp() {
    const dialog = document.getElementById('authbuddyHelpDialog');
    if (dialog && typeof dialog.close === 'function' && dialog.open) {
      dialog.close();
      return;
    }
    if (dialog) dialog.hidden = true;
  }

  function bindAuthbuddyHelp() {
    renderAuthbuddyManuals();
    applyAuthbuddyHelpLinks();
    const dialog = ensureAuthbuddyHelpDialog();
    if (document.documentElement.dataset.authbuddyHelpBound) return;
    document.documentElement.dataset.authbuddyHelpBound = '1';
    document.addEventListener('click', (event) => {
      const target = event.target && event.target.closest;
      if (!target) return;
      if (event.target.closest('[data-save-authbuddy-manual]')) {
        event.preventDefault();
        saveAuthbuddyManual();
        return;
      }
      if (event.target.closest('[data-print-authbuddy-manual]')) {
        event.preventDefault();
        printAuthbuddyManual();
        return;
      }
      if (event.target.closest('[data-open-authbuddy-help]')) {
        event.preventDefault();
        openAuthbuddyHelp();
        return;
      }
      if (event.target.closest('[data-close-authbuddy-help]')) {
        event.preventDefault();
        closeAuthbuddyHelp();
      }
    });
    if (dialog && !dialog.dataset.authbuddyHelpBound) {
      dialog.dataset.authbuddyHelpBound = '1';
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) closeAuthbuddyHelp();
      });
    }
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
    pwaUrl,
    apkUrl,
    bindAuthbuddyHelp,
    renderAuthbuddyManuals,
    openAuthbuddyHelp,
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
    bindAuthbuddyHelp();
    const apply = (meta) => {
      loadConfigFromMeta(meta || {});
      applyAuthbuddyHelpLinks();
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
