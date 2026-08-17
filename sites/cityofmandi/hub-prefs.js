/** Shared City of Mandi board + locality preferences (mobile-first auth). */
(() => {
  const BOARD_KEY = "hub_preferred_board";
  const LOCALITY_KEY = "hub_board_locality";
  const LANG_KEY = "hub_content_lang";
  const MY_MANDI_KEY = "hub_my_mandi";

  const LOCALITIES = [
    { id: "mandi", label: "Mandi", labelHi: "मंडी", lat: 31.7083, lng: 76.9318 },
    { id: "sundernagar", label: "Sunder Nagar", labelHi: "सुंदरनगर", lat: 31.5332, lng: 76.8924 },
    { id: "nerchowk", label: "Ner Chowk", labelHi: "नेरचौक", lat: 31.6085, lng: 76.9142 },
    { id: "sarkaghat", label: "Sarkaghat", labelHi: "सरकाघाट", lat: 31.7000, lng: 76.7333 },
    { id: "pandoh", label: "Pandoh", labelHi: "पंदोह", lat: 31.6667, lng: 77.0667 },
    { id: "jogindernagar", label: "Joginder Nagar", labelHi: "जोगिंदर नगर", lat: 31.9872, lng: 76.7903 },
    { id: "rewalsar", label: "Rewalsar", labelHi: "रेवालसर", lat: 31.6342, lng: 76.8331 },
    { id: "bagsaid", label: "Bagsaid", labelHi: "बगसैद", lat: 31.5500, lng: 76.8667 },
    { id: "aut", label: "Aut", labelHi: "औट", lat: 31.7250, lng: 77.2050 },
    { id: "karsog", label: "Karsog", labelHi: "करसोग", lat: 31.3833, lng: 77.2000 },
    { id: "gohar", label: "Gohar", labelHi: "गोहर", lat: 31.5500, lng: 77.0167 },
    { id: "baldwara", label: "Baldwara", labelHi: "बल्द्वारा", lat: 31.5833, lng: 76.7833 },
    { id: "padhar", label: "Padhar", labelHi: "पधार", lat: 31.9500, lng: 76.9167 },
    { id: "chauntra", label: "Chauntra", labelHi: "चौंतरा", lat: 32.0167, lng: 76.8333 },
    { id: "janjehli", label: "Janjehli", labelHi: "जंजेहली", lat: 31.5167, lng: 77.2167 },
    { id: "thunag", label: "Thunag", labelHi: "थुनाग", lat: 31.5500, lng: 77.1667 },
    { id: "dharampur", label: "Dharampur (Mandi)", labelHi: "धर्मपुर", lat: 31.3500, lng: 76.9500 },
    { id: "kullu", label: "Kullu", labelHi: "कुल्लू", lat: 31.9579, lng: 77.1095 },
    { id: "manali", label: "Manali", labelHi: "मनाली", lat: 32.2432, lng: 77.1892 },
    { id: "bhuntar", label: "Bhuntar", labelHi: "भुंतर", lat: 31.8760, lng: 77.1480 },
    { id: "banjar", label: "Banjar", labelHi: "बंजार", lat: 31.6333, lng: 77.3500 },
    { id: "jibhi", label: "Jibhi", labelHi: "जिभी", lat: 31.5950, lng: 77.3800 },
    { id: "kasol", label: "Kasol", labelHi: "कसोल", lat: 32.0100, lng: 77.3150 },
    { id: "birbilling", label: "Bir-Billing", labelHi: "बीर-बिलिंग", lat: 32.0420, lng: 76.7050 },
  ];

  /** Visitor / citizen default — news & places, not a trade desk. */
  const DEFAULT_BOARD = "city";

  /** Destination boards for contextual sign-in. */
  const BOARDS = [
    { id: "city", label: "City board", labelHi: "शहर बोर्ड", home: "/#landing-news", kind: "hub", live: true },
    { id: "labour", label: "Labour", labelHi: "मज़दूर", home: "/#landing-labour", kind: "profession", live: true },
    { id: "taxi", label: "Cabs", labelHi: "कैब", home: "/#landing-taxi", kind: "profession", live: true },
    { id: "experts", label: "SME / Experts", labelHi: "विशेषज्ञ", home: "/#landing-experts", kind: "profession", live: false },
    { id: "vehicle", label: "Vehicle service", labelHi: "वाहन", home: "/#landing-vehicle", kind: "profession", live: true },
    { id: "doctor", label: "Doc on call", labelHi: "डॉक्टर", home: "/#landing-doctor", kind: "profession", live: true },
    { id: "tours", label: "Tours", labelHi: "टूर्स", home: "/#landing-tours", kind: "profession", live: true },
    { id: "tutors", label: "Tutors", labelHi: "ट्यूटर", home: "/#landing-tutors", kind: "profession", live: false },
    { id: "home", label: "Home services", labelHi: "घर सेवा", home: "/#landing-home", kind: "profession", live: true },
    { id: "food", label: "Food", labelHi: "खाना", home: "/#landing-food", kind: "commerce", live: true },
    { id: "grocery", label: "Kirana", labelHi: "किराना", home: "/#landing-grocery", kind: "commerce", live: true },
    { id: "hardware", label: "Hardware", labelHi: "हार्डवेयर", home: "/#landing-hardware", kind: "commerce", live: false },
    { id: "haulage", label: "Tempo", labelHi: "ढुलाई", home: "/#landing-haulage", kind: "commerce", live: true },
    { id: "rentals", label: "Rent / Sell", labelHi: "किराये / बिक्री", home: "/#landing-rentals", kind: "commerce", live: true },
    { id: "adda", label: "Adda", labelHi: "अड्डा", home: "/adda", kind: "chat", live: false },
  ];

  const BOARD_ALIASES = {
    seri: "labour",
    sme: "experts",
    doc: "doctor",
    travel: "tours",
    coaching: "tutors",
    mentor: "tutors",
    explore: "city",
    news: "city",
    hub: "city",
  };

  const BOARD_IDS = new Set(BOARDS.map((b) => b.id));

  function normalizeBoard(raw) {
    let id = String(raw || "").trim().toLowerCase();
    if (BOARD_ALIASES[id]) id = BOARD_ALIASES[id];
    if (BOARD_IDS.has(id)) return id;
    return DEFAULT_BOARD;
  }

  function normalizeLocality(raw) {
    let id = String(raw || "").trim().toLowerCase().replace(/[\s_-]+/g, "");
    const aliases = {
      sundarnagar: "sundernagar",
      bir: "birbilling",
      billing: "birbilling",
      dharampurmandi: "dharampur",
      jogindernager: "jogindernagar",
    };
    if (aliases[id]) id = aliases[id];
    return LOCALITIES.some((l) => l.id === id) ? id : "mandi";
  }

  function boardMeta(id) {
    const key = normalizeBoard(id);
    return BOARDS.find((b) => b.id === key) || BOARDS[0];
  }

  function boardHome(preferred) {
    return boardMeta(preferred).home;
  }

  function rememberPrefs(preferred, locality, contentLang) {
    const board = normalizeBoard(preferred);
    const loc = normalizeLocality(locality);
    const lang = normalizeContentLang(contentLang);
    try {
      localStorage.setItem(BOARD_KEY, board);
      localStorage.setItem(LOCALITY_KEY, loc);
      if (lang) localStorage.setItem(LANG_KEY, lang);
      localStorage.setItem(MY_MANDI_KEY, "1");
    } catch { /* private mode */ }
    return { board, loc, lang: lang || readContentLang() };
  }

  function isMyMandiOn() {
    try {
      return localStorage.getItem(MY_MANDI_KEY) === "1";
    } catch {
      return false;
    }
  }

  function setMyMandi(on) {
    try {
      if (on) localStorage.setItem(MY_MANDI_KEY, "1");
      else localStorage.setItem(MY_MANDI_KEY, "0");
    } catch { /* ignore */ }
    document.dispatchEvent(new CustomEvent("hub:mymandi", { detail: { on: !!on } }));
    return !!on;
  }

  function localityLabel(id) {
    const loc = LOCALITIES.find((l) => l.id === normalizeLocality(id));
    return loc ? loc.label : "Mandi";
  }

  function boardSectionId(preferred) {
    const meta = boardMeta(preferred);
    if (meta.id === "adda") return null;
    const home = meta.home || "";
    const hash = home.includes("#") ? home.split("#")[1] : `landing-${meta.id}`;
    return hash || `landing-${meta.id}`;
  }

  function normalizeContentLang(raw) {
    if (window.HubI18n?.normalizeLang) return window.HubI18n.normalizeLang(raw);
    const v = String(raw || "").trim().toLowerCase();
    return v === "hi" || v === "hindi" ? "hi" : "en";
  }

  function rememberContentLang(lang) {
    const next = normalizeContentLang(lang);
    try {
      localStorage.setItem(LANG_KEY, next);
      localStorage.setItem("seri_lang", next);
    } catch { /* ignore */ }
    return next;
  }

  function readContentLang() {
    try {
      const stored = localStorage.getItem(LANG_KEY) || localStorage.getItem("seri_lang");
      if (stored) return normalizeContentLang(stored);
    } catch { /* ignore */ }
    return window.HubI18n?.readLang?.() || "en";
  }

  function readPrefs() {
    let board = DEFAULT_BOARD;
    let loc = "mandi";
    let lang = "en";
    try {
      board = normalizeBoard(localStorage.getItem(BOARD_KEY) || DEFAULT_BOARD);
      loc = normalizeLocality(localStorage.getItem(LOCALITY_KEY) || "mandi");
      lang = readContentLang();
    } catch { /* ignore */ }
    return { board, loc, lang };
  }

  function isGenericNext(path) {
    const p = String(path || "").trim();
    return !p || p === "/" || p === "/#" || p === "/index.html" || p === "/join" || p === "/account" || p === "/partner";
  }

  function resolveDestination(preferred, nextRaw) {
    if (!isGenericNext(nextRaw)) return nextRaw;
    return boardHome(preferred);
  }

  function optionsHtml(selected, { includeHi = false } = {}) {
    const sel = normalizeBoard(selected);
    return BOARDS.map((b) => {
      const label = includeHi ? `${b.label} · ${b.labelHi}` : b.label;
      return `<option value="${b.id}"${b.id === sel ? " selected" : ""}>${label}</option>`;
    }).join("");
  }

  function localityOptionsHtml(selected) {
    const sel = normalizeLocality(selected);
    return LOCALITIES.map((l) =>
      `<option value="${l.id}"${l.id === sel ? " selected" : ""}>${l.label}</option>`
    ).join("");
  }

  function fillBoardSelects(ids, selected) {
    const html = optionsHtml(selected, { includeHi: true });
    (ids || []).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    });
  }

  function fillLocalitySelects(ids, selected) {
    const html = localityOptionsHtml(selected);
    (ids || []).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    });
  }

  function mountBoardPicker(containerId, selectId, selected) {
    const box = document.getElementById(containerId);
    const select = document.getElementById(selectId);
    if (!box) return;
    let current = normalizeBoard(selected || (select && select.value) || readPrefs().board);

    function paint() {
      box.innerHTML = BOARDS.map((b) => `
        <button type="button" class="hub-board-chip${b.id === current ? " is-on" : ""}" data-board="${b.id}" aria-pressed="${b.id === current ? "true" : "false"}">
          <strong>${b.label}</strong>
          <span lang="hi">${b.labelHi}</span>
        </button>
      `).join("");
      if (select) select.value = current;
      box.querySelectorAll("[data-board]").forEach((btn) => {
        btn.addEventListener("click", () => {
          current = btn.getAttribute("data-board");
          paint();
          select?.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });
    }
    paint();
  }

  function mountLocalityPicker(containerId, selectId, selected) {
    const box = document.getElementById(containerId);
    const select = document.getElementById(selectId);
    if (!box) return;
    let current = normalizeLocality(selected || (select && select.value) || readPrefs().loc);

    function paint() {
      box.innerHTML = LOCALITIES.map((l) => `
        <button type="button" class="hub-loc-chip${l.id === current ? " is-on" : ""}" data-loc="${l.id}" aria-pressed="${l.id === current ? "true" : "false"}">
          ${l.label}
        </button>
      `).join("");
      if (select) select.value = current;
      box.querySelectorAll("[data-loc]").forEach((btn) => {
        btn.addEventListener("click", () => {
          current = btn.getAttribute("data-loc");
          paint();
          select?.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });
    }
    paint();
    return {
      get: () => current,
      set: (id) => {
        current = normalizeLocality(id);
        paint();
      },
    };
  }

  function mountBoardsNav({
    rootId = "landingBoardsNav",
    buttonId = "landingBoardsBtn",
    menuId = "landingBoardsMenu",
    onNavigate = null,
  } = {}) {
    const root = document.getElementById(rootId);
    const btn = document.getElementById(buttonId);
    const menu = document.getElementById(menuId);
    if (!root || !btn || !menu) return;
    if (menu.dataset.mounted === "1") return;
    menu.dataset.mounted = "1";

    const extras = [
      { id: "explore", label: "All boards", labelHi: "सब बोर्ड", home: "/#landing-news", kind: "hub" },
      { id: "contact", label: "Contact", labelHi: "संपर्क", home: "/contact", kind: "hub" },
    ];
    const items = [...extras, ...BOARDS];

    function close() {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      root.classList.remove("is-open");
    }

    function open() {
      menu.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      root.classList.add("is-open");
    }

    function toggle() {
      if (menu.hidden) open();
      else close();
    }

    menu.innerHTML = `
      <p class="landing-boards-heading">Boards · बोर्ड</p>
      ${items.map((b) => `
        <a class="landing-boards-item" role="menuitem" href="${b.home}" data-board="${b.id}">
          <strong>${b.label}</strong>
          <span lang="hi">${b.labelHi}</span>
        </a>
      `).join("")}
    `;

    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      toggle();
    });

    menu.querySelectorAll("[data-board]").forEach((link) => {
      link.addEventListener("click", (event) => {
        const id = link.getAttribute("data-board");
        const href = link.getAttribute("href") || "";
        if (typeof onNavigate === "function") {
          const handled = onNavigate(href, id, event);
          if (handled) {
            event.preventDefault();
          }
        }
        close();
      });
    });

    document.addEventListener("click", (event) => {
      if (!root.contains(event.target)) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
  }

  const ADDA_ICON = `<svg class="landing-brand-adda-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M4 5h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H9l-3.5 2.6V15H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm13.5 3H20a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-1v1.8L16.8 17H15.5v-2.1c1.7-.2 2-1.4 2-2.4V8z"/></svg>`;
  const CONTACT_HTML = `<a href="/contact" class="landing-nav-contact" aria-label="Contact Board · संपर्क बोर्ड" title="Contact Board"><svg class="landing-nav-contact-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 3v-3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm2 4v2h12V8H6zm0 4v2h8v-2H6z"/></svg><span class="landing-nav-contact-pulse" aria-hidden="true"></span></a>`;

  function pagePath() {
    return (location.pathname || "/").replace(/\/+$/, "") || "/";
  }

  function addaLinkHtml(isStatic) {
    const cls = `landing-brand-adda${isStatic ? " is-static" : ""}`;
    const open = isStatic
      ? `<div class="${cls}" aria-label="Mandi Adda — Live">`
      : `<a class="${cls}" href="/adda" aria-label="Mandi Adda — Live">`;
    const close = isStatic ? "</div>" : "</a>";
    return `${open}<span class="nav-live-mark" aria-hidden="true">Live</span>${ADDA_ICON}<span class="landing-brand-adda-label">Adda</span>${close}`;
  }

  function boardsNavHtml() {
    return `<div class="landing-boards-nav" id="landingBoardsNav"><button type="button" class="landing-boards-btn" id="landingBoardsBtn" aria-expanded="false" aria-haspopup="true" aria-controls="landingBoardsMenu" aria-label="Boards menu"><span class="landing-boards-burger" aria-hidden="true"><i></i><i></i><i></i></span><span class="landing-boards-label">Boards</span></button><div class="landing-boards-menu" id="landingBoardsMenu" hidden role="menu"></div></div>`;
  }

  function signinHtml() {
    const next = encodeURIComponent(`${location.pathname}${location.search}` || "/");
    return `<a class="landing-account-signin" href="/join?mode=login&amp;next=${next}" aria-label="Sign in"><svg class="landing-account-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 12a4.5 4.5 0 1 0-4.5-4.5A4.5 4.5 0 0 0 12 12zm0 2c-3.6 0-8 1.8-8 4.5V21h16v-2.5C20 15.8 15.6 14 12 14z"/></svg><span>Sign in</span></a>`;
  }

  function ensureSiteChrome() {
    const header = document.querySelector("header.landing-top, header.adda-top, header.desk-top, header.shop-top");
    if (!header || header.dataset.siteChrome === "1") return header;
    header.dataset.siteChrome = "1";
    header.classList.add("site-chrome");

    const path = pagePath();
    const isAdda = /\/adda$/.test(path) || path.endsWith("adda.html");
    const isJoin = /\/join$/.test(path) || path.endsWith("join.html");
    const isContact = /\/contact$/.test(path) || path.endsWith("contact.html");
    const isHome = path === "/" || path.endsWith("/index.html");

    let left = header.querySelector(".landing-top-left");
    if (!left) {
      left = document.createElement("div");
      left.className = "landing-top-left";
      const brand = header.querySelector(".landing-top-brand");
      if (brand) {
        brand.querySelector(".landing-top-name")?.remove();
        if (!brand.getAttribute("aria-label")) brand.setAttribute("aria-label", "City of Mandi home");
        left.appendChild(brand);
      } else {
        left.insertAdjacentHTML("afterbegin", `<a class="landing-top-brand" href="/" aria-label="City of Mandi home"><img class="landing-top-seal" src="/assets/cityofmandi-mark.webp?v=20260817seal1" alt="" width="40" height="40" decoding="async"></a>`);
      }
      header.insertBefore(left, header.firstChild);
    } else {
      left.querySelector(".landing-top-name")?.remove();
    }

    const adda = left.querySelector(".landing-brand-adda");
    if (!adda) {
      left.insertAdjacentHTML("beforeend", addaLinkHtml(isAdda));
    } else if (!adda.querySelector(".landing-brand-adda-icon")) {
      const live = adda.querySelector(".nav-live-mark");
      if (live) live.insertAdjacentHTML("afterend", ADDA_ICON);
      else adda.insertAdjacentHTML("afterbegin", ADDA_ICON);
    }

    if (!document.getElementById("landingBoardsNav")) {
      left.insertAdjacentHTML("beforeend", boardsNavHtml());
    }

    let right = header.querySelector(".landing-top-right");
    if (!right) {
      right = header.querySelector(".adda-top-actions, .desk-top-actions, #hubLangMount");
      if (right) {
        right.classList.add("landing-top-right");
      } else {
        right = document.createElement("div");
        right.className = "landing-top-right";
        header.appendChild(right);
      }
    }
    const lang = header.querySelector(".labour-lang, .hub-lang-wrap, #hubLangMount");
    if (lang && !right.contains(lang)) {
      right.insertBefore(lang, right.firstChild);
    }

    if (!isContact && !right.querySelector(".landing-nav-contact")) {
      right.insertAdjacentHTML("afterbegin", CONTACT_HTML);
    }
    if (
      !isJoin
      && !isHome
      && !right.querySelector(".landing-account-signin, #landingSignInBtn, #addaAuthBtn")
      && !header.querySelector("#logoutBtn")
    ) {
      right.insertAdjacentHTML("beforeend", signinHtml());
    }

    return header;
  }

  function bootSiteChrome() {
    try {
      ensureSiteChrome();
      if (!document.getElementById("landingView")) mountBoardsNav();
    } catch {
      /* keep the page usable if chrome fails */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootSiteChrome);
  } else {
    bootSiteChrome();
  }

  window.HubPrefs = {
    BOARD_KEY,
    LOCALITY_KEY,
    LANG_KEY,
    MY_MANDI_KEY,
    DEFAULT_BOARD,
    LOCALITIES,
    BOARDS,
    normalizeBoard,
    normalizeLocality,
    normalizeContentLang,
    boardMeta,
    boardHome,
    boardSectionId,
    localityLabel,
    rememberPrefs,
    rememberContentLang,
    readContentLang,
    readPrefs,
    isMyMandiOn,
    setMyMandi,
    isGenericNext,
    resolveDestination,
    optionsHtml,
    localityOptionsHtml,
    fillBoardSelects,
    fillLocalitySelects,
    mountBoardPicker,
    mountLocalityPicker,
    mountBoardsNav,
    ensureSiteChrome,
  };
})();
