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
    const purpose = params().get('purpose') || '';
    const houseId = params().get('houseId') || params().get('house_id') || '';
    const memberId = params().get('memberId') || params().get('member_id') || '';
    const sid = (window.VeerAuth && window.VeerAuth.savedSessionId()) || '';
    const dest = returnTo();

    // Bridge AuthBuddy → RWA session when returning to the portal with plot context.
    if (sid && houseId && (purpose === 'login' || purpose === 'bridge')) {
      fetch('/api/rwa/authbuddy/session', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          houseId: houseId,
          memberId: memberId || undefined,
          authbuddySessionId: sid,
        }),
      })
        .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          if (ok && d && d.token) {
            window.location.replace(dest.indexOf('index.html') >= 0 ? 'index.html#home' : dest);
            return;
          }
          setStatus((d && d.error) || 'AuthBuddy signed in — finish with email passcode if not linked yet.');
          setTimeout(() => { window.location.replace(dest); }, 900);
        })
        .catch(() => { window.location.replace(dest); });
      return;
    }

    if (sid && purpose === 'link') {
      fetch('/api/rwa/authbuddy/link', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          authbuddySessionId: sid,
          memberId: memberId || undefined,
        }),
      })
        .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
        .then(({ ok, d }) => {
          if (ok) {
            setStatus('AuthBuddy linked. Returning…');
            setTimeout(() => { window.location.replace(dest); }, 500);
            return;
          }
          setError((d && d.error) || 'Could not link AuthBuddy');
          setTimeout(() => { window.location.replace(dest); }, 1200);
        })
        .catch(() => { window.location.replace(dest); });
      return;
    }

    window.location.replace(dest);
  }

  function clientId() {
    return (window.VeerAuth && window.VeerAuth.config() || {}).clientId || 'hbcsanyard-web';
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

  function buildChoosableLoginMethods(options) {
    const out = [];
    const add = (m) => { if (m && !out.includes(m)) out.push(m); };
    const policyOk = (m) => !policy || policyAllows(m);

    if (options.has_password && (!policy || policy.password_required !== false || policyAllows('password'))) {
      add('password');
    }
    if (options.has_passkey && (!policy || policy.passkey_allowed || policyAllows('passkey'))) {
      add('passkey');
    }
    if (options.has_totp && policyOk('totp')) add('totp');
    if (options.has_hotp && policyOk('hotp')) add('hotp');
    // QR / number match are first-factor capable (BuddyAuthenticator approve).
    if (policyOk('qr') || policyOk('number_match')) add('qr');
    // Hybrid PQC is MFA-session oriented; still list when policy allows and account may use it after password.
    // Offer as a primary tab only when password is not the only path — users can pick QR instead.
    // Keep hybrid visible in pills via policyMethods(); primary tab when enrolled is unknown from options.
    return out;
  }

  function renderLoginOptions(options) {
    loginOptions = options;
    qs('loginIdentifyStep').hidden = true;
    qs('loginCredentialStep').hidden = false;
    qs('loginUserLabel').textContent = options.username;

    const choosable = buildChoosableLoginMethods(options);
    const policyList = policyMethods().length
      ? policyMethods().map((m) => (m === 'number_match' ? 'qr' : m))
      : choosable.slice();
    const pillMethods = [];
    policyList.forEach((m) => {
      const key = m === 'number_match' ? 'qr' : m;
      if (!pillMethods.includes(key)) pillMethods.push(key);
    });
    choosable.forEach((m) => {
      if (!pillMethods.includes(m)) pillMethods.push(m);
    });

    const pills = qs('loginMethodPills');
    pills.innerHTML = pillMethods.length
      ? pillMethods.map((m) => {
        const label = methodLabel(m);
        return `<span class="status-pill${choosable.includes(m) ? '' : ' is-muted'}" title="${
          choosable.includes(m) ? 'Available now' : 'Allowed by site policy'
        }">${label}</span>`;
      }).join('')
      : '<span class="status-pill">No methods</span>';

    if (!choosable.length) {
      setError('This account has no usable sign-in method yet. Complete authenticator setup after creating an account.');
      qs('loginPasswordBlock').hidden = true;
      qs('loginOtpBlock').hidden = true;
      qs('loginPasskeyBlock').hidden = true;
      if (qs('loginQrBlock')) qs('loginQrBlock').hidden = true;
      qs('loginMethodTabs').hidden = true;
      qs('loginSubmitBtn').disabled = true;
      return;
    }

    qs('loginSubmitBtn').disabled = false;
    // Mobile / installed PWA: default to QR / Approve so match-number + QR show immediately.
    const preferQr = isMobileAuthUi();
    if (preferQr && choosable.includes('qr')) activeLoginMethod = 'qr';
    else if (choosable.includes('password')) activeLoginMethod = 'password';
    else if (choosable.includes('passkey')) activeLoginMethod = 'passkey';
    else if (choosable.includes('qr')) activeLoginMethod = 'qr';
    else activeLoginMethod = choosable[0];
    renderLoginMethodTabs(choosable);
    applyLoginMethod(activeLoginMethod);
    setStatus(options.message || 'Choose any allowed sign-in method.');
  }

  function renderLoginMethodTabs(methods) {
    const tabs = qs('loginMethodTabs');
    const groups = [];
    if (methods.includes('password')) groups.push({ id: 'password', label: 'Password' });
    if (methods.includes('passkey')) groups.push({ id: 'passkey', label: 'Passkey' });
    if (methods.includes('totp') || methods.includes('hotp')) groups.push({ id: 'otp', label: 'Authenticator' });
    if (methods.includes('qr')) groups.push({ id: 'qr', label: 'QR / Approve' });

    if (groups.length < 2) {
      tabs.hidden = true;
      tabs.innerHTML = '';
      return;
    }

    tabs.hidden = false;
    tabs.innerHTML = groups.map((g) => {
      const active = (g.id === 'password' && activeLoginMethod === 'password')
        || (g.id === 'passkey' && activeLoginMethod === 'passkey')
        || (g.id === 'qr' && activeLoginMethod === 'qr')
        || (g.id === 'otp' && (activeLoginMethod === 'totp' || activeLoginMethod === 'hotp'));
      return `<button type="button" class="auth-tab${active ? ' is-active' : ''}" data-login-method="${g.id}">${g.label}</button>`;
    }).join('');

    tabs.querySelectorAll('[data-login-method]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const group = btn.dataset.loginMethod;
        if (group === 'password') activeLoginMethod = 'password';
        else if (group === 'passkey') activeLoginMethod = 'passkey';
        else if (group === 'qr') activeLoginMethod = 'qr';
        else if (loginOptions && loginOptions.has_totp) activeLoginMethod = 'totp';
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
    const qrBlock = qs('loginQrBlock');
    const submitRow = qs('loginSubmitRow');
    const pw = qs('loginPassword');
    const otp = qs('loginOtpCode');

    passwordBlock.hidden = true;
    otpBlock.hidden = true;
    passkeyBlock.hidden = true;
    if (qrBlock) qrBlock.hidden = true;
    pw.required = false;
    otp.required = false;
    submitRow.hidden = false;
    stopDevicePoll();

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

    if (method === 'qr') {
      if (qrBlock) qrBlock.hidden = false;
      submitRow.hidden = true;
      startDeviceChallenge('login').catch((err) => setError(err.message || 'Could not start QR challenge'));
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
      startDeviceChallenge('mfa').catch((err) => setError(err.message || 'Could not start QR challenge'));
    } else if (isHybrid) {
      stopDevicePoll();
      startHybridPqcChallenge().catch((err) => setError(err.message || 'Could not start Hybrid PQC challenge'));
    } else {
      stopDevicePoll();
      stopHybridPqcPoll();
      if (!isPasskey) qs('mfaVerifyCode').focus();
    }
  }

  function isMobileAuthUi() {
    try {
      return window.matchMedia('(max-width: 820px)').matches
        || window.matchMedia('(display-mode: standalone)').matches
        || window.matchMedia('(display-mode: fullscreen)').matches
        || Boolean(window.navigator.standalone);
    } catch (_e) {
      return false;
    }
  }

  function wireDeviceApproveActions(isLoginQr, begin) {
    const openBtn = isLoginQr ? qs('loginOpenBuddyBtn') : qs('mfaOpenBuddyBtn');
    const copyBtn = isLoginQr ? qs('loginCopyMatchBtn') : qs('mfaCopyMatchBtn');
    const matchText = String(begin.number != null ? begin.number : '').padStart(2, '0');
    const qrUri = String(begin.qr_uri || '').trim();

    if (openBtn) {
      if (qrUri) {
        openBtn.hidden = false;
        openBtn.href = qrUri;
        openBtn.setAttribute('rel', 'noopener');
      } else {
        openBtn.hidden = true;
        openBtn.removeAttribute('href');
      }
    }
    if (copyBtn) {
      copyBtn.hidden = begin.number == null || begin.number === '';
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(matchText);
          setStatus(`Copied match number ${matchText}`);
        } catch (_e) {
          setStatus(`Match number: ${matchText}`);
        }
      };
    }
  }

  async function startDeviceChallenge(purpose) {
    stopDevicePoll();
    setError('');
    const isLoginQr = purpose === 'login';
    const statusEl = isLoginQr ? qs('loginDeviceStatus') : qs('mfaDeviceStatus');
    const matchEl = isLoginQr ? qs('loginMatchNumber') : qs('mfaMatchNumber');
    const img = isLoginQr ? qs('loginDeviceQrImg') : qs('mfaDeviceQrImg');
    if (statusEl) statusEl.textContent = 'Starting challenge…';
    const username = enrollUsername
      || (loginOptions && loginOptions.username)
      || String(qs('loginUsername').value || '').trim();
    const begin = await window.VeerAuth.idpPost('/auth/mfa/device_challenge/begin', {
      purpose: isLoginQr ? 'login' : 'mfa',
      username: username || undefined,
      client_id: clientId(),
    });
    deviceChallengeId = begin.challenge_id;
    const matchText = String(begin.number).padStart(2, '0');
    if (matchEl) matchEl.textContent = matchText;
    wireDeviceApproveActions(isLoginQr, begin);
    if (img) {
      if (begin.qr_data_uri) {
        img.src = begin.qr_data_uri;
        // On phone/PWA you usually approve in BuddyAuthenticator (number or deep link),
        // not by scanning your own screen — still show QR for cross-device use.
        img.hidden = false;
      } else {
        img.hidden = true;
      }
    }
    if (statusEl) {
      statusEl.textContent = isMobileAuthUi()
        ? `Number ${matchText} — open BuddyAuthenticator (must be signed in) → Approvals, or tap Approve below.`
        : 'Waiting for BuddyAuthenticator approval…';
    }
    devicePollTimer = setInterval(() => {
      pollDeviceChallenge(isLoginQr).catch(() => {});
    }, 2000);
  }

  async function pollDeviceChallenge(isLoginQr) {
    if (!deviceChallengeId) return;
    const st = await window.VeerAuth.idpPost('/auth/mfa/device_challenge/status', {
      challenge_id: deviceChallengeId,
    });
    const statusEl = isLoginQr ? qs('loginDeviceStatus') : qs('mfaDeviceStatus');
    if (st.status === 'approved') {
      stopDevicePoll();
      if (st.session_id) window.VeerAuth.saveSessionId(st.session_id);
      if (statusEl) statusEl.textContent = 'Approved. Continuing…';
      setStatus('Verified. Continuing…');
      setTimeout(() => { continueToReturn(); }, 500);
    } else if (st.status === 'expired') {
      stopDevicePoll();
      if (statusEl) statusEl.textContent = 'Challenge expired — tap Refresh QR.';
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
      data = await window.VeerAuth.idpPost(path, { code });
    } catch (_err) {
      const alt = mfaKind === 'hotp' ? '/auth/mfa/totp/verify' : '/auth/mfa/hotp/verify';
      data = await window.VeerAuth.idpPost(alt, { code });
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
          { code }
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
        startDeviceChallenge('mfa').catch((err) => setError(err.message || 'Could not refresh QR'));
      });
    }
    const loginRestartQr = qs('loginRestartQrBtn');
    if (loginRestartQr) {
      loginRestartQr.addEventListener('click', () => {
        startDeviceChallenge('login').catch((err) => setError(err.message || 'Could not refresh QR'));
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
    const purpose = params().get('purpose') || '';
    const linkedUsername = (
      params().get('username')
      || params().get('authbuddyUsername')
      || ''
    ).trim();
    // Colony gate login/bridge: if AuthBuddy is already signed in on this device
    // (PWA localStorage + agent cookie) for the linked username, continue without
    // forcing another password/QR challenge. Otherwise challenge as usual.
    const forceCredentialChallenge = purpose === 'login' || purpose === 'bridge';
    if (forceCredentialChallenge) {
      const prior = linkedUsername
        || (existing && existing.session
          ? (existing.session.username || existing.session.email || '')
          : '');
      const existingUser = (existing && existing.session
        ? (existing.session.username || existing.session.email || '')
        : '').trim();
      const sameUser = !linkedUsername
        || !existingUser
        || existingUser.toLowerCase() === String(linkedUsername).toLowerCase();
      if (window.VeerAuth.isAuthenticated(existing) && sameUser) {
        if (prior && qs('loginUsername')) qs('loginUsername').value = prior;
        setStatus('Already signed in on this device. Continuing…');
        continueToReturn();
        return;
      }
      // Drop SSO so password / passkey / TOTP / QR is required again.
      try { window.VeerAuth.saveSessionId(''); } catch (_e) { /* ignore */ }
      try {
        await fetch('/agent/v1/logout?return_to=' + encodeURIComponent(window.location.href), {
          method: 'GET',
          credentials: 'include',
          redirect: 'manual',
        });
      } catch (_e) { /* ignore */ }
      try {
        await fetch('/auth/logout', {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: '{}',
        });
      } catch (_e) { /* ignore */ }
      showTab('login');
      if (prior && qs('loginUsername')) {
        qs('loginUsername').value = prior;
      }
      if (prior) {
        qs('authSubtitle').textContent = `Sign in as ${prior} with any method allowed for HBC Sanyard.`;
        setStatus('Choose password, passkey, authenticator code, or QR approve.');
        await continueWithUsername();
      } else {
        setStatus('Sign in with AuthBuddy to continue to the colony portal.');
      }
    } else if (window.VeerAuth.isAuthenticated(existing)) {
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
    } else if (linkedUsername) {
      showTab('login');
      if (qs('loginUsername')) qs('loginUsername').value = linkedUsername;
      setStatus('Choose a sign-in method.');
      await continueWithUsername();
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
      enrollUsername = username;
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
