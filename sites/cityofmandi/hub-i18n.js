/** Site-wide English / Hindi content language for City of Mandi. */
(() => {
  const LANG_KEY = "hub_content_lang";
  const LEGACY_KEY = "seri_lang";

  const STRINGS = {
    en: {
      signIn: "Sign in",
      signOut: "Sign out",
      boards: "Boards",
      contact: "Contact",
      explore: "Explore Mandi",
      contactBoard: "Contact Board",
      preferences: "Preferences",
      preferredBoard: "Preferred board",
      homeLocality: "Home locality",
      contentLang: "Content language",
      contentLangHint: "Board and page text in English or Hindi.",
      langEn: "English",
      langHi: "Hindi",
      register: "Register",
      login: "Sign in",
      createAccount: "Create account",
      useLocation: "Use my location",
      area: "Area",
      savePrefs: "Save preferences",
      yourPlace: "Your place in the city",
      pickBoardLoc: "Pick the board you use most, your locality, and content language.",
      openMeInto: "Open me into",
      iCareAbout: "I care about",
      yourName: "Your name",
      email: "Email",
      password: "Password (8+)",
      passwordShort: "Password",
      partnerPhone: "Partner with phone + PIN?",
      labour: "Labour",
      cabs: "Cabs",
      services: "Services",
      geoHint: "Tap the map or use GPS — live boards prefer this area.",
      detected: "Detected",
      preferred: "Preferred",
      heroKicker: "Himachal Pradesh · Independent city hub",
      heroGreeting: "The civic home for news, places, services, and everyday life in Mandi — by the city, not the corporation.",
      scrollExplore: "Explore",
      onThisPage: "On this page",
      account: "Account",
      hub: "Hub",
      langToggle: "Language",
    },
    hi: {
      signIn: "साइन इन",
      signOut: "साइन आउट",
      boards: "बोर्ड",
      contact: "संपर्क",
      explore: "मंडी देखें",
      contactBoard: "संपर्क बोर्ड",
      preferences: "प्राथमिकताएँ",
      preferredBoard: "पसंदीदा बोर्ड",
      homeLocality: "घर का इलाका",
      contentLang: "सामग्री भाषा",
      contentLangHint: "बोर्ड और पृष्ठ की भाषा — अंग्रेज़ी या हिंदी।",
      langEn: "अंग्रेज़ी",
      langHi: "हिंदी",
      register: "पंजीकरण",
      login: "साइन इन",
      createAccount: "खाता बनाएँ",
      useLocation: "मेरी लोकेशन",
      area: "इलाका",
      savePrefs: "प्राथमिकताएँ सहेजें",
      yourPlace: "शहर में आपकी जगह",
      pickBoardLoc: "पसंदीदा बोर्ड, इलाका और सामग्री भाषा चुनें।",
      openMeInto: "मुझे यहाँ खोलें",
      iCareAbout: "मेरी रुचि",
      yourName: "आपका नाम",
      email: "ईमेल",
      password: "पासवर्ड (८+)",
      passwordShort: "पासवर्ड",
      partnerPhone: "फोन + पिन से पार्टनर?",
      labour: "मज़दूर",
      cabs: "कैब",
      services: "सेवाएँ",
      geoHint: "मानचित्र या GPS — लाइव बोर्ड इसी इलाके को प्राथमिकता देते हैं।",
      detected: "पाया गया",
      preferred: "पसंदीदा",
      heroKicker: "हिमाचल प्रदेश · स्वतंत्र शहर हब",
      heroGreeting: "मंडी के समाचार, स्थान, सेवाएँ और रोज़मर्रा की ज़िंदगी का नागरिक घर — शहर का, निगम का नहीं।",
      scrollExplore: "देखें",
      onThisPage: "इस पृष्ठ पर",
      account: "खाता",
      hub: "हब",
      langToggle: "भाषा",
    },
  };

  function normalizeLang(raw) {
    const v = String(raw || "").trim().toLowerCase();
    if (v === "hi" || v === "hindi" || v === "hin" || v === "हिं" || v === "हिंदी") return "hi";
    return "en";
  }

  function readLang() {
    try {
      const stored = localStorage.getItem(LANG_KEY) || localStorage.getItem(LEGACY_KEY);
      if (stored) return normalizeLang(stored);
    } catch { /* ignore */ }
    const htmlLang = document.documentElement.getAttribute("lang");
    if (htmlLang) return normalizeLang(htmlLang);
    const nav = (navigator.languages && navigator.languages[0]) || navigator.language || "";
    if (/^hi\b/i.test(nav)) return "hi";
    return "en";
  }

  function writeLang(lang) {
    const next = normalizeLang(lang);
    try {
      localStorage.setItem(LANG_KEY, next);
      localStorage.setItem(LEGACY_KEY, next);
    } catch { /* ignore */ }
    return next;
  }

  function t(key, lang) {
    const pack = STRINGS[normalizeLang(lang || readLang())] || STRINGS.en;
    return pack[key] != null ? pack[key] : (STRINGS.en[key] || key);
  }

  function applyDocumentLang(lang) {
    const next = normalizeLang(lang);
    document.documentElement.setAttribute("lang", next);
    document.documentElement.dataset.contentLang = next;
    document.documentElement.classList.toggle("lang-hi", next === "hi");
    document.documentElement.classList.toggle("lang-en", next === "en");
  }

  function applyStaticI18n(lang) {
    const next = normalizeLang(lang);
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.getAttribute("data-i18n");
      if (!key) return;
      // Nested opt/req markers handled by labour.js; skip empty keys
      if (node.classList.contains("labour-opt") || node.classList.contains("labour-req")) return;
      const attr = node.getAttribute("data-i18n-attr");
      const value = t(key, next);
      if (attr) {
        node.setAttribute(attr, value);
        return;
      }
      if (node.tagName === "INPUT" || node.tagName === "TEXTAREA") {
        node.placeholder = value;
        return;
      }
      // Preserve child em/req if present as only decoration
      if (node.children.length && node.querySelector(".labour-req, .labour-opt")) return;
      node.textContent = value;
    });

    document.querySelectorAll("[data-en][data-hi]").forEach((node) => {
      const en = node.getAttribute("data-en") || "";
      const hi = node.getAttribute("data-hi") || "";
      node.textContent = next === "hi" ? hi : en;
    });

    document.querySelectorAll(".i18n-en, .i18n-hi").forEach((node) => {
      const isHi = node.classList.contains("i18n-hi");
      node.hidden = next === "hi" ? !isHi : isHi;
    });
  }

  function syncToggleButtons(root, lang) {
    const next = normalizeLang(lang);
    (root || document).querySelectorAll(".hub-lang-btn, .labour-lang-btn").forEach((btn) => {
      const on = btn.getAttribute("data-lang") === next;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function setLang(lang, { silent = false } = {}) {
    const next = writeLang(lang);
    applyDocumentLang(next);
    applyStaticI18n(next);
    syncToggleButtons(document, next);
    if (window.HubPrefs?.rememberContentLang) {
      window.HubPrefs.rememberContentLang(next);
    }
    if (!silent) {
      document.dispatchEvent(new CustomEvent("hub:lang", { detail: { lang: next } }));
    }
    return next;
  }

  function toggleHtml() {
    return `
      <div class="hub-lang" role="group" aria-label="${t("langToggle")} · भाषा">
        <button type="button" class="hub-lang-btn" data-lang="en" aria-label="English" title="English">
          <span class="hub-lang-icon" aria-hidden="true">A</span>
          <span class="hub-lang-code">EN</span>
        </button>
        <button type="button" class="hub-lang-btn" data-lang="hi" aria-label="हिन्दी" title="हिन्दी">
          <span class="hub-lang-icon hub-lang-icon-hi" aria-hidden="true">अ</span>
          <span class="hub-lang-code">हिं</span>
        </button>
      </div>
    `;
  }

  function bindToggle(root) {
    if (!root || root.dataset.hubLangBound === "1") return;
    root.dataset.hubLangBound = "1";
    root.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-lang]");
      if (!btn || !root.contains(btn)) return;
      event.preventDefault();
      setLang(btn.getAttribute("data-lang"));
    });
  }

  function findMountPoint() {
    return document.getElementById("hubLangMount")
      || document.querySelector(".landing-top-right")
      || document.querySelector(".auth-top")
      || document.querySelector(".labour-top")
      || document.querySelector(".desk-top-actions")
      || document.querySelector(".desk-top")
      || document.querySelector(".shop-top")
      || null;
  }

  function mountLangToggle(opts = {}) {
    const existing = document.querySelector(".hub-lang");
    if (existing) {
      bindToggle(existing);
      syncToggleButtons(document, readLang());
      return existing;
    }
    // Upgrade legacy labour-lang blocks
    const legacy = document.querySelector(".labour-lang");
    if (legacy && !opts.forceMount) {
      legacy.classList.add("hub-lang");
      legacy.querySelectorAll(".labour-lang-btn").forEach((btn) => btn.classList.add("hub-lang-btn"));
      // Ensure icon spans exist
      legacy.querySelectorAll(".hub-lang-btn, .labour-lang-btn").forEach((btn) => {
        if (btn.querySelector(".hub-lang-icon")) return;
        const code = btn.getAttribute("data-lang") === "hi" ? "hi" : "en";
        btn.innerHTML = code === "hi"
          ? `<span class="hub-lang-icon hub-lang-icon-hi" aria-hidden="true">अ</span><span class="hub-lang-code">हिं</span>`
          : `<span class="hub-lang-icon" aria-hidden="true">A</span><span class="hub-lang-code">EN</span>`;
      });
      bindToggle(legacy);
      syncToggleButtons(document, readLang());
      return legacy;
    }

    const mount = opts.mount
      || (opts.mountId && document.getElementById(opts.mountId))
      || findMountPoint();
    const wrap = document.createElement("div");
    wrap.className = "hub-lang-wrap";
    wrap.innerHTML = toggleHtml();
    if (mount) {
      if (mount.classList.contains("landing-top-right") || mount.classList.contains("desk-top-actions")) {
        mount.prepend(wrap);
      } else {
        mount.appendChild(wrap);
      }
    } else {
      wrap.classList.add("hub-lang-fab");
      document.body.appendChild(wrap);
    }
    const root = wrap.querySelector(".hub-lang");
    bindToggle(root);
    syncToggleButtons(document, readLang());
    return root;
  }

  function mountLangPicker(containerId, selectId, selected) {
    const box = document.getElementById(containerId);
    const select = document.getElementById(selectId);
    if (!box) return null;
    let current = normalizeLang(selected || (select && select.value) || readLang());

    function paint() {
      box.innerHTML = `
        <button type="button" class="hub-lang-chip${current === "en" ? " is-on" : ""}" data-lang="en" aria-pressed="${current === "en"}">
          <span class="hub-lang-icon" aria-hidden="true">A</span>
          <strong>${t("langEn", current)}</strong>
          <span>EN</span>
        </button>
        <button type="button" class="hub-lang-chip${current === "hi" ? " is-on" : ""}" data-lang="hi" aria-pressed="${current === "hi"}">
          <span class="hub-lang-icon hub-lang-icon-hi" aria-hidden="true">अ</span>
          <strong>${t("langHi", current)}</strong>
          <span>हिं</span>
        </button>
      `;
      if (select) select.value = current;
      box.querySelectorAll("[data-lang]").forEach((btn) => {
        btn.addEventListener("click", () => {
          current = normalizeLang(btn.getAttribute("data-lang"));
          paint();
          setLang(current);
          select?.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });
    }
    paint();
    return {
      get: () => current,
      set: (id) => {
        current = normalizeLang(id);
        paint();
      },
    };
  }

  // Boot early so first paint matches preference
  const bootLang = readLang();
  applyDocumentLang(bootLang);

  function bootUi() {
    mountLangToggle();
    applyStaticI18n(bootLang);
    syncToggleButtons(document, bootLang);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootUi);
  } else {
    bootUi();
  }

  window.HubI18n = {
    LANG_KEY,
    STRINGS,
    normalizeLang,
    readLang,
    writeLang,
    setLang,
    t,
    applyStaticI18n,
    mountLangToggle,
    mountLangPicker,
    syncToggleButtons,
  };
})();
