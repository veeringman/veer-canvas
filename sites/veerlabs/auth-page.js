(function () {
  function qs(id) { return document.getElementById(id); }

  function params() {
    return new URLSearchParams(window.location.search);
  }

  function returnTo() {
    const raw = params().get('return_to');
    if (!raw) return 'index.html';
    try {
      const dest = new URL(raw, window.location.href);
      // Stay on-site; reject auth.html loops.
      if (dest.origin !== window.location.origin) return 'index.html';
      if (/\/auth\.html(?:$|\?)/i.test(dest.pathname)) return 'index.html';
      return dest.href;
    } catch (_e) {
      return raw;
    }
  }

  function continueToReturn() {
    window.location.replace(returnTo());
  }

  function clientId() {
    return (window.VeerAuth && window.VeerAuth.config() || {}).clientId || 'veerlabs-web';
  }

  function setError(msg) {
    const el = qs('authError');
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || '';
  }

  function setStatus(msg) {
    const el = qs('authStatus');
    if (!el) return;
    el.hidden = !msg;
    el.textContent = msg || '';
  }

  let policy = null;
  let mfaKind = 'totp';
  let loginOptions = null;
  let activeLoginMethod = 'password';
  let pendingMfaMethods = [];
  let enrollForced = false;
  let enrollUsername = '';

  function policyMethods() {
    const raw = (policy && (policy.mfa_methods || policy.methods)) || [];
    return raw.map((m) => String(m).toLowerCase().replace(/^registrationmethod::/i, ''));
  }

  function policyAllows(method) {
    const methods = policyMethods();
    if (!methods.length) return true;
    // methods may be enums like "totp" or objects — normalize via JSON stringify path already handled
    const flat = (policy.methods || []).map((m) => {
      if (typeof m === 'string') return m.toLowerCase();
      return String(m).toLowerCase();
    });
    const mfa = (policy.mfa_methods || []).map((m) => String(m).toLowerCase());
    return flat.includes(method) || mfa.includes(method);
  }

  function showTab(whichTab) {
    const login = qs('loginForm');
    const register = qs('registerForm');
    const mfa = qs('mfaPanel');
    document.querySelectorAll('.auth-tab[data-tab]').forEach((btn) => {
      btn.classList.toggle('is-active', btn.dataset.tab === whichTab);
    });
    if (mfa) mfa.hidden = true;
    enrollForced = false;
    if (whichTab === 'register') {
      login.hidden = true;
      register.hidden = false;
      qs('authTitle').textContent = 'Register';
      qs('authSubtitle').textContent = 'Create an account using the methods allowed by this site’s AuthBuddy policy.';
      applyPolicyToRegisterForm();
    } else {
      login.hidden = false;
      register.hidden = true;
      qs('authTitle').textContent = 'Sign in';
      qs('authSubtitle').textContent = 'Enter your username. We’ll ask for the factors required by this site’s AuthBuddy policy.';
      resetLoginToIdentify();
    }
  }

  function renderMethods(p) {
    const pills = qs('methodPills');
    if (!pills || !p) return;
    const methods = p.methods || [];
    pills.innerHTML = methods.map((m) => {
      const label = typeof m === 'string' ? m : String(m);
      return `<span class="status-pill">${label.replace(/_/g, ' ')}</span>`;
    }).join('');
    qs('policyNotes').textContent = p.notes || '';
  }

  function applyPolicyToRegisterForm() {
    if (!policy) return;
    const passwordRequired = policy.password_required === true;
    const passwordlessAllowed = policy.passwordless_allowed === true && !passwordRequired;
    const row = qs('regPasswordlessRow');
    const fieldset = qs('regTypeFieldset');
    if (row) row.hidden = !passwordlessAllowed;
    if (fieldset) fieldset.hidden = passwordRequired && !passwordlessAllowed;
    if (passwordRequired) {
      const pwRadio = document.querySelector('input[name="regType"][value="password"]');
      if (pwRadio) pwRadio.checked = true;
    }
    // MFA kind tabs from policy
    document.querySelectorAll('.auth-tab[data-mfa]').forEach((btn) => {
      const kind = btn.dataset.mfa;
      if (kind === 'passkey') {
        btn.hidden = !(policy.passkey_allowed || policyAllows('passkey'));
      } else {
        btn.hidden = !policyAllows(kind);
      }
    });
    syncPasswordFields();
  }

  function syncPasswordFields() {
    const type = (document.querySelector('input[name="regType"]:checked') || {}).value;
    const passwordless = type === 'passwordless';
    qs('passwordFields').hidden = passwordless;
    const pw = qs('registerForm').querySelector('[name="password"]');
    const pw2 = qs('registerForm').querySelector('[name="password2"]');
    if (passwordless) {
      pw.required = false;
      pw2.required = false;
    } else {
      pw.required = true;
      pw2.required = true;
    }
  }

  function resetLoginToIdentify() {
    loginOptions = null;
    activeLoginMethod = 'password';
    pendingMfaMethods = [];
    qs('loginIdentifyStep').hidden = false;
    qs('loginCredentialStep').hidden = true;
    qs('loginPassword').value = '';
    qs('loginOtpCode').value = '';
    qs('loginSubmitBtn').textContent = 'Sign in';
    qs('loginSubmitRow').hidden = false;
    setError('');
    setStatus('');
  }

  function methodLabel(method) {
    if (method === 'password') return 'Password';
    if (method === 'totp') return 'TOTP';
    if (method === 'hotp') return 'HOTP';
    if (method === 'passkey') return 'Passkey';
    if (method === 'hybrid_pqc') return 'Hybrid PQC';
    if (method === 'qr') return 'QR / Approve';
    if (method === 'number_match') return 'Number match';
    return method;
  }

  function renderLoginOptions(options) {
    loginOptions = options;
    qs('loginIdentifyStep').hidden = true;
    qs('loginCredentialStep').hidden = false;
    qs('loginUserLabel').textContent = options.username;

    const pills = qs('loginMethodPills');
    let methods = options.primary_methods || [];
    // Filter by site policy when available
    if (policy) {
      methods = methods.filter((m) => {
        if (m === 'password') return policy.password_required !== false || policyAllows('password');
        if (m === 'passkey') return policy.passkey_allowed || policyAllows('passkey');
        return policyAllows(m) || true;
      });
    }
    pills.innerHTML = methods.length
      ? methods.map((m) => `<span class="status-pill">${methodLabel(m)}</span>`).join('')
      : '<span class="status-pill">No methods</span>';

    const choosable = methods.filter((m) => m === 'password' || m === 'totp' || m === 'hotp' || m === 'passkey');
    if (!choosable.length) {
      setError('This account has no usable sign-in method yet. Complete authenticator setup after creating an account.');
      qs('loginPasswordBlock').hidden = true;
      qs('loginOtpBlock').hidden = true;
      qs('loginPasskeyBlock').hidden = true;
      qs('loginMethodTabs').hidden = true;
      qs('loginSubmitBtn').disabled = true;
      return;
    }

    qs('loginSubmitBtn').disabled = false;
    if (choosable.includes('password')) activeLoginMethod = 'password';
    else if (choosable.includes('passkey')) activeLoginMethod = 'passkey';
    else activeLoginMethod = choosable[0];
    renderLoginMethodTabs(choosable);
    applyLoginMethod(activeLoginMethod);
    setStatus(options.message || '');
  }

  function renderLoginMethodTabs(methods) {
    const tabs = qs('loginMethodTabs');
    const groups = [];
    if (methods.includes('password')) groups.push({ id: 'password', label: 'Password' });
    if (methods.includes('passkey')) groups.push({ id: 'passkey', label: 'Passkey' });
    if (methods.includes('totp') || methods.includes('hotp')) groups.push({ id: 'otp', label: 'Authenticator' });

    if (groups.length < 2) {
      tabs.hidden = true;
      tabs.innerHTML = '';
      return;
    }

    tabs.hidden = false;
    tabs.innerHTML = groups.map((g) => {
      const active = (g.id === 'password' && activeLoginMethod === 'password')
        || (g.id === 'passkey' && activeLoginMethod === 'passkey')
        || (g.id === 'otp' && (activeLoginMethod === 'totp' || activeLoginMethod === 'hotp'));
      return `<button type="button" class="auth-tab${active ? ' is-active' : ''}" data-login-method="${g.id}">${g.label}</button>`;
    }).join('');

    tabs.querySelectorAll('[data-login-method]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const group = btn.dataset.loginMethod;
        if (group === 'password') activeLoginMethod = 'password';
        else if (group === 'passkey') activeLoginMethod = 'passkey';
        else if (loginOptions.has_totp) activeLoginMethod = 'totp';
        else activeLoginMethod = 'hotp';
        tabs.querySelectorAll('.auth-tab').forEach((b) => b.classList.toggle('is-active', b === btn));
        applyLoginMethod(activeLoginMethod);
      });
    });
  }

  function applyLoginMethod(method) {
    activeLoginMethod = method;
    const passwordBlock = qs('loginPasswordBlock');
    const otpBlock = qs('loginOtpBlock');
    const passkeyBlock = qs('loginPasskeyBlock');
    const submitRow = qs('loginSubmitRow');
    const pw = qs('loginPassword');
    const otp = qs('loginOtpCode');

    passwordBlock.hidden = true;
    otpBlock.hidden = true;
    passkeyBlock.hidden = true;
    pw.required = false;
    otp.required = false;
    submitRow.hidden = false;

    if (method === 'password') {
      passwordBlock.hidden = false;
      pw.required = true;
      qs('loginSubmitBtn').textContent = 'Sign in';
      pw.focus();
      return;
    }

    if (method === 'passkey') {
      passkeyBlock.hidden = false;
      submitRow.hidden = true;
      return;
    }

    otpBlock.hidden = false;
    otp.required = true;
    const hasBoth = loginOptions && loginOptions.has_totp && loginOptions.has_hotp;
    const switchEl = qs('otpTypeSwitch');
    if (hasBoth) {
      qs('loginOtpLabelText').textContent = 'Authenticator code';
      qs('loginOtpHint').textContent = method === 'hotp'
        ? 'Using HOTP (counter). Tap Next in BuddyAuthenticator after each code.'
        : 'Using TOTP (time-based).';
      switchEl.hidden = false;
      switchEl.innerHTML = `
        <button type="button" class="auth-tab${method === 'totp' ? ' is-active' : ''}" data-otp-kind="totp">TOTP</button>
        <button type="button" class="auth-tab${method === 'hotp' ? ' is-active' : ''}" data-otp-kind="hotp">HOTP</button>`;
      switchEl.querySelectorAll('[data-otp-kind]').forEach((b) => {
        b.addEventListener('click', () => {
          activeLoginMethod = b.dataset.otpKind;
          applyLoginMethod(activeLoginMethod);
        });
      });
    } else {
      switchEl.hidden = true;
      switchEl.innerHTML = '';
      qs('loginOtpLabelText').textContent = method === 'hotp' ? 'HOTP code' : 'TOTP code';
      qs('loginOtpHint').textContent = method === 'hotp'
        ? 'Enter the current counter code from BuddyAuthenticator.'
        : 'Enter the current 6-digit code from BuddyAuthenticator.';
    }
    qs('loginSubmitBtn').textContent = 'Sign in with code';
    otp.focus();
  }

  function allowedEnrollKinds() {
    const kinds = [];
    if (!policy || policyAllows('totp')) kinds.push('totp');
    if (!policy || policyAllows('hotp')) kinds.push('hotp');
    if (!policy || policy.passkey_allowed || policyAllows('passkey')) kinds.push('passkey');
    if (!policy || policyAllows('hybrid_pqc')) kinds.push('hybrid_pqc');
    return kinds.length ? kinds : ['totp', 'hotp', 'passkey', 'hybrid_pqc'];
  }

  function showMfaEnrollPanel(message, opts) {
    opts = opts || {};
    enrollForced = opts.forced !== false && (opts.forced === true || (policy && policy.mfa_required));
    if (message) setStatus(message);
    qs('loginForm').hidden = true;
    qs('registerForm').hidden = true;
    qs('mfaPanel').hidden = false;
    qs('mfaTitle').textContent = 'Set up authenticator';
    qs('mfaLead').textContent = enrollForced
      ? 'Site policy requires a second factor before you can access protected pages.'
      : 'Enroll TOTP, HOTP, a passkey, or Hybrid PQC, then continue.';
    qs('mfaSetupBox').hidden = false;
    qs('mfaVerifyOnly').hidden = true;
    qs('mfaQrArea').hidden = true;
    qs('continueAfterAuth').hidden = enrollForced;
    syncMfaKindTabs(allowedEnrollKinds());
    applyMfaKindUI(mfaKind);
  }

  let devicePollTimer = null;
  let deviceChallengeId = null;
  let hybridPqcPollTimer = null;
  let hybridPqcChallengeId = null;

  function stopDevicePoll() {
    if (devicePollTimer) {
      clearInterval(devicePollTimer);
      devicePollTimer = null;
    }
  }

  function stopHybridPqcPoll() {
    if (hybridPqcPollTimer) {
      clearInterval(hybridPqcPollTimer);
      hybridPqcPollTimer = null;
    }
  }

  function normalizeMfaMethods(methods) {
    const out = [];
    const seen = new Set();
    (methods || []).forEach((raw) => {
      const m = String(raw).toLowerCase();
      // Consolidate number_match into the QR / Approve tab
      const key = m === 'number_match' ? 'qr' : m;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(key);
      }
    });
    return out;
  }

  function showMfaChallengePanel(methods, message) {
    stopDevicePoll();
    stopHybridPqcPoll();
    pendingMfaMethods = normalizeMfaMethods(
      methods && methods.length ? methods : allowedEnrollKinds()
    );
    if (message) setStatus(message);
    qs('loginForm').hidden = true;
    qs('registerForm').hidden = true;
    qs('mfaPanel').hidden = false;
    qs('mfaTitle').textContent = 'Verify authenticator';
    qs('mfaLead').textContent = 'Use BuddyAuthenticator: Hybrid PQC, QR approve, TOTP/HOTP code, or a passkey.';
    qs('mfaSetupBox').hidden = true;
    qs('mfaVerifyOnly').hidden = false;
    qs('continueAfterAuth').hidden = true;
    enrollForced = true;

    const prefer = pendingMfaMethods.includes('hybrid_pqc')
      ? 'hybrid_pqc'
      : (pendingMfaMethods.includes('qr')
        ? 'qr'
        : (pendingMfaMethods.includes('totp') ? 'totp' : pendingMfaMethods[0]));
    mfaKind = prefer || 'totp';
    syncMfaKindTabs(pendingMfaMethods);
    qs('mfaVerifyPasskeyBtn').hidden = !pendingMfaMethods.includes('passkey');
    qs('mfaVerifyCode').value = '';
    applyVerifyKindUI(mfaKind);
  }

  function applyVerifyKindUI(kind) {
    mfaKind = kind;
    const isQr = kind === 'qr' || kind === 'number_match';
    const isPasskey = kind === 'passkey';
    const isHybrid = kind === 'hybrid_pqc';
    qs('mfaVerifyCodeBlock').hidden = isQr || isPasskey || isHybrid;
    qs('mfaVerifyQrBlock').hidden = !isQr;
    const hybridBlock = qs('mfaVerifyHybridPqcBlock');
    if (hybridBlock) hybridBlock.hidden = !isHybrid;
    if (isQr) {
      stopHybridPqcPoll();
      startDeviceChallenge().catch((err) => setError(err.message || 'Could not start QR challenge'));
    } else if (isHybrid) {
      stopDevicePoll();
      startHybridPqcChallenge().catch((err) => setError(err.message || 'Could not start Hybrid PQC challenge'));
    } else {
      stopDevicePoll();
      stopHybridPqcPoll();
      if (!isPasskey) qs('mfaVerifyCode').focus();
    }
  }

  async function startDeviceChallenge() {
    stopDevicePoll();
    setError('');
    qs('mfaDeviceStatus').textContent = 'Starting challenge…';
    const username = enrollUsername
      || (loginOptions && loginOptions.username)
      || String(qs('loginUsername').value || '').trim();
    const begin = await window.VeerAuth.idpPost('/auth/mfa/device_challenge/begin', {
      purpose: 'mfa',
      username: username || undefined,
      client_id: clientId(),
    });
    deviceChallengeId = begin.challenge_id;
    qs('mfaMatchNumber').textContent = String(begin.number).padStart(2, '0');
    const img = qs('mfaDeviceQrImg');
    if (begin.qr_data_uri) {
      img.src = begin.qr_data_uri;
      img.hidden = false;
    } else {
      img.hidden = true;
    }
    qs('mfaDeviceStatus').textContent = 'Waiting for BuddyAuthenticator approval…';
    devicePollTimer = setInterval(() => {
      pollDeviceChallenge().catch(() => {});
    }, 2000);
  }

  async function pollDeviceChallenge() {
    if (!deviceChallengeId) return;
    const st = await window.VeerAuth.idpPost('/auth/mfa/device_challenge/status', {
      challenge_id: deviceChallengeId,
    });
    if (st.status === 'approved') {
      stopDevicePoll();
      if (st.session_id) window.VeerAuth.saveSessionId(st.session_id);
      qs('mfaDeviceStatus').textContent = 'Approved. Continuing…';
      setStatus('Verified. Continuing…');
      setTimeout(() => { continueToReturn(); }, 500);
    } else if (st.status === 'expired') {
      stopDevicePoll();
      qs('mfaDeviceStatus').textContent = 'Challenge expired — tap Refresh QR.';
    }
  }

  async function startHybridPqcChallenge() {
    stopHybridPqcPoll();
    setError('');
    const statusEl = qs('mfaHybridPqcStatus');
    if (statusEl) statusEl.textContent = 'Starting Hybrid PQC challenge…';
    const begin = await window.VeerAuth.idpPost('/auth/mfa/hybrid_pqc/challenge', {});
    hybridPqcChallengeId = begin.challenge_id;
    if (statusEl) {
      statusEl.textContent = 'Waiting for BuddyAuthenticator… Open Hybrid PQC → Approve pending challenge.';
    }
    hybridPqcPollTimer = setInterval(() => {
      pollHybridPqcChallenge().catch(() => {});
    }, 2000);
  }

  async function pollHybridPqcChallenge() {
    if (!hybridPqcChallengeId) return;
    const st = await window.VeerAuth.idpPost('/auth/mfa/hybrid_pqc/status', {
      challenge_id: hybridPqcChallengeId,
    });
    const statusEl = qs('mfaHybridPqcStatus');
    if (st.status === 'approved') {
      stopHybridPqcPoll();
      if (st.session_id) window.VeerAuth.saveSessionId(st.session_id);
      if (statusEl) statusEl.textContent = 'Approved. Continuing…';
      setStatus('Hybrid PQC verified. Continuing…');
      setTimeout(() => { continueToReturn(); }, 500);
    } else if (st.status === 'expired') {
      stopHybridPqcPoll();
      if (statusEl) statusEl.textContent = 'Challenge expired — tap Refresh challenge.';
    }
  }

  function syncMfaKindTabs(allowed) {
    document.querySelectorAll('.auth-tab[data-mfa]').forEach((b) => {
      const ok = allowed.includes(b.dataset.mfa);
      b.hidden = !ok;
      b.classList.toggle('is-active', ok && b.dataset.mfa === mfaKind);
    });
    const visible = [...document.querySelectorAll('.auth-tab[data-mfa]')].filter((b) => !b.hidden);
    if (visible.length && !visible.some((b) => b.dataset.mfa === mfaKind)) {
      mfaKind = visible[0].dataset.mfa;
      visible.forEach((b) => b.classList.toggle('is-active', b.dataset.mfa === mfaKind));
    }
    qs('mfaKindTabs').hidden = visible.length < 2;
  }

  function applyMfaKindUI(kind) {
    mfaKind = kind;
    const passkey = kind === 'passkey';
    const hybrid = kind === 'hybrid_pqc';
    qs('mfaTotpHotpSetup').hidden = passkey || hybrid;
    qs('mfaPasskeySetup').hidden = !passkey;
    const hybridSetup = qs('mfaHybridPqcSetup');
    if (hybridSetup) hybridSetup.hidden = !hybrid;
    qs('mfaQrArea').hidden = true;
  }

  async function afterAuthOk(message, forced) {
    showMfaEnrollPanel(message || 'Complete authenticator setup to finish.', { forced: forced !== false });
    if (window.VeerAuth && window.VeerAuth.mountTopbarAuth) {
      window.VeerAuth.mountTopbarAuth();
    }
  }

  async function loadWebAuthn() {
    return import('https://cdn.jsdelivr.net/npm/@simplewebauthn/browser@13.1.2/+esm');
  }

  function extractPublicKeyOptions(publicKey) {
    if (!publicKey) return publicKey;
    return publicKey.publicKey || publicKey.public_key || publicKey;
  }

  async function runPasskeyEnroll() {
    setError('');
    const username = enrollUsername
      || (loginOptions && loginOptions.username)
      || (qs('registerForm').querySelector('[name="username"]') || {}).value
      || '';
    if (!username) {
      setError('Username required for passkey enrollment');
      return;
    }
    const begin = await window.VeerAuth.idpPost('/auth/passkey/register/begin', { username });
    const webauthn = await loadWebAuthn();
    const attResp = await webauthn.startRegistration({
      optionsJSON: extractPublicKeyOptions(begin.public_key),
    });
    await window.VeerAuth.idpPost('/auth/passkey/register/complete', {
      challenge_id: begin.challenge_id,
      user_id: begin.user_id,
      public_key: attResp,
    });
    setStatus('Passkey enrolled. Continuing…');
    setTimeout(() => { continueToReturn(); }, 700);
  }

  async function runPasskeyLogin(username) {
    setError('');
    const begin = await window.VeerAuth.idpPost('/auth/passkey/authenticate/begin', { username });
    const webauthn = await loadWebAuthn();
    const assertion = await webauthn.startAuthentication({
      optionsJSON: extractPublicKeyOptions(begin.public_key),
    });
    const data = await window.VeerAuth.idpPost('/auth/passkey/authenticate/complete', {
      challenge_id: begin.challenge_id,
      public_key: assertion,
    });
    if (data.session_id) window.VeerAuth.saveSessionId(data.session_id);
    continueToReturn();
  }

  async function runMfaSetup() {
    setError('');
    if (mfaKind === 'passkey') {
      await runPasskeyEnroll();
      return;
    }
    if (mfaKind === 'hybrid_pqc') {
      setStatus('Open BuddyAuthenticator → Hybrid PQC → Sign in → Generate & enroll keys, then return here to verify.');
      return;
    }
    const path = mfaKind === 'hotp' ? '/auth/mfa/hotp/setup' : '/auth/mfa/totp/setup';
    const data = await window.VeerAuth.idpPost(path, {});
    qs('mfaQrArea').hidden = false;
    qs('mfaQrImg').src = data.qr_data_uri || '';
    qs('mfaUri').textContent = data.qr_code_uri || '';
    const hint = qs('mfaCounterHint');
    if (mfaKind === 'hotp') {
      hint.hidden = false;
      hint.textContent = 'Counter starts at ' + (data.counter != null ? data.counter : 0)
        + '. After each login code, tap Next in BuddyAuthenticator.';
    } else {
      hint.hidden = true;
    }
    qs('mfaCode').value = '';
    qs('mfaCode').focus();
  }

  async function confirmMfaEnroll() {
    setError('');
    const code = String(qs('mfaCode').value || '').trim();
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the 6-digit code from BuddyAuthenticator');
      return;
    }
    const path = mfaKind === 'hotp' ? '/auth/mfa/hotp/verify' : '/auth/mfa/totp/verify';
    let data;
    try {
      data = await window.VeerAuth.idpPost(path, { code, client_id: clientId() });
    } catch (_err) {
      const alt = mfaKind === 'hotp' ? '/auth/mfa/totp/verify' : '/auth/mfa/hotp/verify';
      data = await window.VeerAuth.idpPost(alt, { code, client_id: clientId() });
    }
    if (!data.success) {
      setError(data.message || 'Invalid code');
      return;
    }
    if (data.session_id) window.VeerAuth.saveSessionId(data.session_id);
    setStatus('Authenticator verified. Continuing…');
    setTimeout(() => { continueToReturn(); }, 700);
  }

  async function confirmMfaChallenge() {
    setError('');
    const code = String(qs('mfaVerifyCode').value || '').trim();
    if (!/^\d{6,8}$/.test(code)) {
      setError('Enter the code from BuddyAuthenticator');
      return;
    }
    const order = [mfaKind].concat(pendingMfaMethods.filter((m) => m !== mfaKind && m !== 'passkey'));
    let lastErr = null;
    for (const method of order) {
      try {
        const data = await window.VeerAuth.idpPost(
          method === 'hotp' ? '/auth/mfa/hotp/verify' : '/auth/mfa/totp/verify',
          { code, client_id: clientId() }
        );
        if (data.success) {
          if (data.session_id) window.VeerAuth.saveSessionId(data.session_id);
          setStatus('Verified. Continuing…');
          setTimeout(() => { continueToReturn(); }, 500);
          return;
        }
        lastErr = new Error(data.message || 'Invalid code');
      } catch (err) {
        lastErr = err;
      }
    }
    setError((lastErr && lastErr.message) || 'Invalid authenticator code');
  }

  async function continueWithUsername() {
    setError('');
    setStatus('');
    const username = String(qs('loginUsername').value || '').trim();
    if (!username) {
      setError('Enter your username');
      return;
    }
    const btn = qs('loginContinueBtn');
    btn.disabled = true;
    btn.textContent = 'Checking…';
    try {
      const options = await window.VeerAuth.idpPost('/auth/login/options', { username });
      if (!options.exists) {
        setError(options.message || 'No account found for that username.');
        return;
      }
      renderLoginOptions(options);
    } catch (err) {
      setError(err.message || 'Could not look up account');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Continue';
    }
  }

  async function submitLogin(event) {
    event.preventDefault();
    setError('');
    if (qs('loginIdentifyStep').hidden === false) {
      await continueWithUsername();
      return;
    }
    if (!loginOptions) {
      setError('Enter your username first');
      return;
    }
    if (activeLoginMethod === 'passkey') {
      await runPasskeyLogin(loginOptions.username);
      return;
    }

    const username = loginOptions.username;
    const submit = qs('loginSubmitBtn');
    submit.disabled = true;
    const prev = submit.textContent;
    submit.textContent = 'Signing in…';

    try {
      if (activeLoginMethod === 'password') {
        const password = String(qs('loginPassword').value || '');
        if (!password) {
          setError('Enter your password');
          return;
        }
        const login = await window.VeerAuth.idpPost('/auth/login', {
          username,
          password,
          client_id: clientId(),
        });
        if (login.session_id) window.VeerAuth.saveSessionId(login.session_id);
        enrollUsername = username;
        if (login.enrollment_required) {
          await afterAuthOk(login.message || 'Enroll an authenticator to finish sign-in.', true);
          return;
        }
        if (login.requires_mfa) {
          const methods = (login.mfa_methods && login.mfa_methods.length)
            ? login.mfa_methods
            : allowedEnrollKinds();
          showMfaChallengePanel(methods, 'Password accepted — complete your second factor.');
          return;
        }
        continueToReturn();
        return;
      }

      const code = String(qs('loginOtpCode').value || '').trim();
      if (!/^\d{6,8}$/.test(code)) {
        setError('Enter the authenticator code from BuddyAuthenticator');
        return;
      }
      await window.VeerAuth.idpPost('/auth/login/otp', {
        username,
        code,
        method: activeLoginMethod === 'hotp' ? 'hotp' : 'totp',
        client_id: clientId(),
      });
      continueToReturn();
    } catch (err) {
      if (err.status === 401) {
        setError(activeLoginMethod === 'password'
          ? 'Login failed — check your password.'
          : 'Invalid authenticator code.');
      } else {
        setError(err.message || 'Login failed');
      }
    } finally {
      submit.disabled = false;
      submit.textContent = prev;
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const mode = params().get('mode');
    if (mode === 'register') showTab('register');

    document.querySelectorAll('.auth-tab[data-tab]').forEach((btn) => {
      btn.addEventListener('click', () => showTab(btn.dataset.tab));
    });
    document.querySelectorAll('.auth-tab[data-mfa]').forEach((btn) => {
      btn.addEventListener('click', () => {
        mfaKind = btn.dataset.mfa;
        document.querySelectorAll('.auth-tab[data-mfa]').forEach((b) => {
          b.classList.toggle('is-active', b.dataset.mfa === mfaKind);
        });
        applyMfaKindUI(mfaKind);
        if (qs('mfaVerifyOnly') && !qs('mfaVerifyOnly').hidden) {
          applyVerifyKindUI(mfaKind);
        }
      });
    });
    document.querySelectorAll('input[name="regType"]').forEach((el) => {
      el.addEventListener('change', syncPasswordFields);
    });
    syncPasswordFields();

    await new Promise((r) => setTimeout(r, 50));
    if (!window.VeerAuth) {
      setError('Auth helper failed to load');
      return;
    }

    qs('loginContinueBtn').addEventListener('click', () => {
      continueWithUsername().catch((err) => setError(err.message || 'Lookup failed'));
    });
    qs('loginChangeUserBtn').addEventListener('click', () => {
      resetLoginToIdentify();
      qs('loginUsername').focus();
    });
    qs('loginUsername').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        continueWithUsername().catch((err) => setError(err.message || 'Lookup failed'));
      }
    });
    qs('loginPasskeyBtn').addEventListener('click', () => {
      if (!loginOptions) return;
      runPasskeyLogin(loginOptions.username).catch((err) => setError(err.message || 'Passkey failed'));
    });

    qs('continueAfterAuth').addEventListener('click', () => {
      if (enrollForced) {
        setError('Complete authenticator setup before continuing.');
        return;
      }
      continueToReturn();
    });
    qs('startMfaSetup').addEventListener('click', () => {
      runMfaSetup().catch((err) => setError(err.message || 'MFA setup failed'));
    });
    qs('startPasskeySetup').addEventListener('click', () => {
      runPasskeyEnroll().catch((err) => setError(err.message || 'Passkey setup failed'));
    });
    qs('confirmMfaCode').addEventListener('click', () => {
      confirmMfaEnroll().catch((err) => setError(err.message || 'MFA confirm failed'));
    });
    qs('confirmMfaVerify').addEventListener('click', () => {
      confirmMfaChallenge().catch((err) => setError(err.message || 'MFA failed'));
    });
    qs('mfaVerifyPasskeyBtn').addEventListener('click', () => {
      const user = enrollUsername || (loginOptions && loginOptions.username) || '';
      runPasskeyLogin(user).catch((err) => setError(err.message || 'Passkey failed'));
    });
    const restartQr = qs('mfaRestartQrBtn');
    if (restartQr) {
      restartQr.addEventListener('click', () => {
        startDeviceChallenge().catch((err) => setError(err.message || 'Could not refresh QR'));
      });
    }
    const restartHybrid = qs('mfaRestartHybridPqcBtn');
    if (restartHybrid) {
      restartHybrid.addEventListener('click', () => {
        startHybridPqcChallenge().catch((err) => setError(err.message || 'Could not refresh Hybrid PQC'));
      });
    }

    try {
      policy = await window.VeerAuth.getPolicy();
      renderMethods(policy);
      applyPolicyToRegisterForm();
    } catch (_e) {
      setStatus('Could not load policy from agent — using local defaults.');
    }

    const existing = await window.VeerAuth.getSession(true);
    if (window.VeerAuth.isAuthenticated(existing)) {
      // Already signed in — continue to the gated page (e.g. Learn more → project).
      if (params().get('return_to')) {
        setStatus('You are signed in. Continuing…');
        continueToReturn();
        return;
      }
      // Fully authenticated — optional extra enroll, allow skip unless policy forces.
      if (policy && policy.mfa_required) {
        // Already signed in with completed factors; just offer continue to catalog.
        setStatus('You are signed in.');
        showTab('login');
      } else {
        showMfaEnrollPanel('You are signed in. Optionally enroll another authenticator.', { forced: false });
      }
    } else if (window.VeerAuth.savedSessionId()) {
      // Enrollment-only cookie may still exist — prompt to finish setup.
      showMfaEnrollPanel('Finish authenticator setup to access protected pages.', { forced: true });
    }

    qs('loginForm').addEventListener('submit', (event) => {
      submitLogin(event).catch((err) => setError(err.message || 'Login failed'));
    });

    qs('registerForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      setError('');
      const fd = new FormData(event.currentTarget);
      const type = fd.get('regType') || 'password';
      const username = String(fd.get('username') || '').trim();
      const email = String(fd.get('email') || '').trim();
      const given_name = String(fd.get('given_name') || '').trim();
      const family_name = String(fd.get('family_name') || '').trim();
      enrollUsername = username;
      const profileNames = {};
      if (given_name) profileNames.given_name = given_name;
      if (family_name) profileNames.family_name = family_name;
      try {
        if (policy && policy.password_required && type === 'passwordless') {
          setError('Passwordless registration is disabled for this site.');
          return;
        }
        if (type === 'passwordless') {
          const reg = await window.VeerAuth.idpPost('/auth/register', {
            username,
            email,
            passwordless: true,
            client_id: clientId(),
            ...profileNames,
          });
          await afterAuthOk(reg.message || 'Enroll an authenticator before accessing protected pages.', true);
          return;
        }
        const password = String(fd.get('password') || '');
        const password2 = String(fd.get('password2') || '');
        if (password !== password2) {
          setError('Passwords do not match');
          return;
        }
        if (password.length < 8) {
          setError('Password must be at least 8 characters');
          return;
        }
        if (!/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/[0-9]/.test(password)) {
          setError('Password needs upper, lower, and a number');
          return;
        }
        const reg = await window.VeerAuth.idpPost('/auth/register', {
          username,
          email,
          password,
          client_id: clientId(),
          ...profileNames,
        });
        const forced = reg.requires_mfa || reg.enrollment_required || (policy && policy.mfa_required);
        await afterAuthOk(reg.message || 'Account created. Complete second-factor setup.', forced);
      } catch (err) {
        if (err.status === 409) {
          setError('That username or email is already registered. Try signing in.');
        } else {
          setError(err.message || 'Registration failed');
        }
      }
    });
  });
})();
