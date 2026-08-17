(() => {
  const params = new URLSearchParams(location.search);
  const $ = (id) => document.getElementById(id);
  const ALIASES = {
    seri: "labour", sme: "experts", doc: "doctor", travel: "tours",
    coaching: "tutors", mentor: "tutors",
  };
  const PROFESSION = new Set([
    "labour", "taxi", "experts", "vehicle", "doctor", "tours", "tutors", "home",
  ]);
  let rawBoard = (document.body.getAttribute("data-board") || params.get("board") || "labour").toLowerCase();
  if (ALIASES[rawBoard]) rawBoard = ALIASES[rawBoard];
  const boardId = PROFESSION.has(rawBoard) ? rawBoard : "labour";
  document.body.setAttribute("data-board", boardId);
  const defaultNext = window.HubPrefs?.boardHome(boardId) || `/#landing-${boardId}`;
  const nextRaw = (params.get("next") || "").trim();
  let nextPath = nextRaw.startsWith("/") && !nextRaw.startsWith("//")
    ? nextRaw
    : defaultNext;
  const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

  function serviceCopy(enTitle, hiTitle, enKicker, hiKicker) {
    return {
      en: {
        kicker: enKicker,
        title: `${enTitle} registration`,
        lede: `Join Mandi’s ${enTitle.toLowerCase()} board. Mobile and photo are required (photo max 5 MB). Same phone+PIN works across partner boards.`,
        tabRegister: "Register",
        tabLogin: "Sign in",
        phone: "Mobile number",
        photo: "Photo",
        photoHint: "Clear face / upper body photo. Max 5 MB — saved as a small square WebP.",
        name: "Name",
        email: "Email",
        address: "Address",
        officialId: "Official ID",
        officialHint: "Aadhaar / voter / other ID — kept private, not shown on the board.",
        pin: "PIN / password",
        optional: "(optional)",
        create: `Create ${enTitle.toLowerCase()} account`,
        signin: "Sign in",
        backBoard: `← Back to ${enTitle.toLowerCase()} board`,
        phName: "Your name",
        phAddress: "Colony / area / landmark",
        phId: "ID number (optional)",
        needPhoto: "Photo is required (max 5 MB).",
        photoTooBig: "Photo must be 5 MB or smaller.",
        uploading: "Uploading and compressing photo…",
        homeLocality: "Home locality",
        preferredBoard: "Preferred board",
        loginPrefsHint: "We’ll open your preferred board after sign-in.",
      },
      hi: {
        kicker: hiKicker,
        title: `${hiTitle} पंजीकरण`,
        lede: `मंडी के ${hiTitle} बोर्ड से जुड़ें। मोबाइल और फोटो ज़रूरी हैं (अधिकतम 5 MB)।`,
        tabRegister: "पंजीकरण",
        tabLogin: "साइन इन",
        phone: "मोबाइल नंबर",
        photo: "फोटो",
        photoHint: "चेहरा / ऊपरी शरीर साफ़ दिखे। अधिकतम 5 MB।",
        name: "नाम",
        email: "ईमेल",
        address: "पता",
        officialId: "आधिकारिक पहचान",
        officialHint: "आधार / वोटर / अन्य आईडी — निजी रहेगी।",
        pin: "पिन / पासवर्ड",
        optional: "(वैकल्पिक)",
        create: "खाता बनाएँ",
        signin: "साइन इन",
        backBoard: `← ${hiTitle} बोर्ड पर वापस`,
        phName: "आपका नाम",
        phAddress: "कॉलोनी / इलाका",
        phId: "आईडी नंबर (वैकल्पिक)",
        needPhoto: "फोटो ज़रूरी है (अधिकतम 5 MB)।",
        photoTooBig: "फोटो 5 MB या उससे छोटी होनी चाहिए।",
        uploading: "फोटो अपलोड हो रही है…",
        homeLocality: "घर का इलाका",
        preferredBoard: "पसंदीदा बोर्ड",
        loginPrefsHint: "साइन इन के बाद आपका पसंदीदा बोर्ड खुलेगा।",
      },
    };
  }

  const COPY = {
    labour: serviceCopy("Labour", "मज़दूर", "Labour board", "मज़दूर बोर्ड"),
    taxi: serviceCopy("Driver", "ड्राइवर", "Cabs & taxis", "कैब और टैक्सी"),
    experts: serviceCopy("SME / Experts", "विशेषज्ञ", "SME & experts", "विशेषज्ञ और SME"),
    vehicle: serviceCopy("Vehicle service", "वाहन सर्विस", "Vehicle servicing", "वाहन सर्विस"),
    doctor: serviceCopy("Doc on call", "डॉक्टर", "Doc on call", "डॉक्टर ऑन कॉल"),
    tours: serviceCopy("Tours & travels", "टूर्स", "Tours & travels", "टूर्स और ट्रैवल"),
    tutors: serviceCopy("Tutors", "ट्यूटर", "Tutors & mentoring", "ट्यूटर और मेंटरिंग"),
    home: serviceCopy("Home services", "घर सेवा", "Home services", "घर सेवाएँ"),
  };
  COPY.labour.en.title = "Worker registration";
  COPY.labour.en.create = "Create labour account";
  COPY.labour.en.backBoard = "← Back to labour board";
  COPY.taxi.en.title = "Driver registration";
  COPY.taxi.en.create = "Create driver account";
  COPY.taxi.en.backBoard = "← Back to cab board";

  let lang = (window.HubI18n?.readLang?.() || localStorage.getItem("hub_content_lang") || localStorage.getItem("seri_lang") || "en");
  lang = lang === "hi" ? "hi" : "en";
  let uploadedPhotoUrl = "";
  let localities = [
    { id: "mandi", label: "Mandi" },
    { id: "sundernagar", label: "Sunder Nagar" },
    { id: "nerchowk", label: "Ner Chowk" },
    { id: "sarkaghat", label: "Sarkaghat" },
    { id: "pandoh", label: "Pandoh" },
  ];

  async function api(path, options = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  function t(key) {
    return COPY[boardId][lang][key] || COPY[boardId].en[key] || key;
  }

  function applyLang(next) {
    lang = next === "hi" ? "hi" : "en";
    if (window.HubI18n?.setLang) window.HubI18n.setLang(lang, { silent: true });
    else {
      localStorage.setItem("seri_lang", lang);
      localStorage.setItem("hub_content_lang", lang);
      document.documentElement.lang = lang;
    }
    const pack = COPY[boardId][lang];

    const setLabel = (id, key, { required = false, optional = false } = {}) => {
      const input = $(id);
      const label = input?.closest("label");
      const span = label?.querySelector("span");
      if (!span) return;
      span.textContent = "";
      span.append(document.createTextNode(`${pack[key]} `));
      if (required) {
        const em = document.createElement("em");
        em.className = "labour-req";
        em.textContent = "*";
        span.appendChild(em);
      } else if (optional) {
        const em = document.createElement("em");
        em.className = "labour-opt";
        em.textContent = pack.optional;
        span.appendChild(em);
      }
    };

    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.getAttribute("data-i18n");
      if (!key || pack[key] == null) return;
      if (node.classList.contains("labour-opt") || node.classList.contains("labour-req")) return;
      if (node.tagName === "SPAN" && node.parentElement?.tagName === "LABEL" && !node.classList.contains("labour-field-hint")) {
        return;
      }
      if (node.tagName === "A" && key === "backBoard") {
        node.textContent = pack[key];
        node.href = defaultNext;
        return;
      }
      node.textContent = pack[key];
    });

    setLabel("regPhone", "phone", { required: true });
    setLabel("regPhoto", "photo", { required: true });
    setLabel("regName", "name", { optional: true });
    setLabel("regEmail", "email", { optional: true });
    setLabel("regAddress", "address", { optional: true });
    setLabel("regOfficialId", "officialId", { optional: true });
    setLabel("regPassword", "pin", { required: true });
    setLabel("loginPhone", "phone", { required: true });
    setLabel("loginPassword", "pin", { required: true });
    setLabel("regLocality", "homeLocality", { required: false });

    $("regName").placeholder = pack.phName;
    $("regAddress").placeholder = pack.phAddress;
    $("regOfficialId").placeholder = pack.phId;

    document.querySelectorAll(".labour-lang-btn").forEach((btn) => {
      const on = btn.getAttribute("data-lang") === lang;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function fillLocalities() {
    const HP = window.HubPrefs;
    const prefs = HP ? HP.readPrefs() : { board: boardId, loc: "mandi" };
    const current = prefs.loc || "mandi";
    if (HP) {
      HP.fillLocalitySelects(["regLocality", "loginLocality"], current);
      const preferred = HP.normalizeBoard(boardId || prefs.board);
      HP.fillBoardSelects(["regPreferredBoard", "loginPreferredBoard"], preferred);
      HP.mountBoardPicker("regBoardPicker", "regPreferredBoard", preferred);
      HP.mountBoardPicker("loginBoardPicker", "loginPreferredBoard", preferred);
      HP.mountLocalityPicker?.("regLocPicker", "regLocality", current);
      HP.mountLocalityPicker?.("loginLocPicker", "loginLocality", current);
      const lang = HP.readContentLang?.() || window.HubI18n?.readLang?.() || "en";
      const regLang = document.getElementById("regContentLang");
      const loginLang = document.getElementById("loginContentLang");
      if (regLang) regLang.value = lang;
      if (loginLang) loginLang.value = lang;
      window.HubI18n?.mountLangPicker?.("regLangPicker", "regContentLang", lang);
      window.HubI18n?.mountLangPicker?.("loginLangPicker", "loginContentLang", lang);
    } else {
      ["regLocality", "loginLocality"].forEach((id) => {
        const select = $(id);
        if (!select) return;
        select.innerHTML = localities.map((row) =>
          `<option value="${row.id}"${row.id === current ? " selected" : ""}>${row.label}</option>`
        ).join("");
      });
    }
    const Geo = window.HubGeo;
    if (Geo?.mountLocalityMap && $("hubLocalityMap")) {
      Geo.mountLocalityMap({
        mapId: "hubLocalityMap",
        selectId: "regLocality",
        statusId: "hubGeoStatus",
        locateBtnId: "hubLocateBtn",
      }).catch(() => {});
    }
    if (Geo?.autoPreferForLive) {
      Geo.autoPreferForLive(boardId).then((nearest) => {
        if (!nearest?.id) return;
        HP?.fillLocalitySelects(["regLocality", "loginLocality"], nearest.id);
        HP?.mountLocalityPicker?.("regLocPicker", "regLocality", nearest.id);
        HP?.mountLocalityPicker?.("loginLocPicker", "loginLocality", nearest.id);
        const status = $("hubGeoStatus");
        if (status) status.textContent = `Detected: ${nearest.label}`;
      }).catch(() => {});
    }
  }

  function boardHome(preferred) {
    if (window.HubPrefs) return window.HubPrefs.boardHome(preferred);
    return `/#landing-${preferred || boardId}`;
  }

  function isGenericNext(path) {
    const p = String(path || "").trim();
    return !p || p === "/" || p === "/#" || p === "/index.html" || p === "/labour" || p === "/taxi" || p === "/partner" || p.startsWith("/partner?");
  }

  async function routeAfterAuth(sess, overrides = {}) {
    const HP = window.HubPrefs;
    let preferred = overrides.preferredBoard
      || sess?.provider?.preferredBoard
      || boardId;
    preferred = HP ? HP.normalizeBoard(preferred) : (PROFESSION.has(preferred) ? preferred : boardId);
    const home = overrides.homeLocality || sess?.provider?.homeLocality;
    const contentLang = document.getElementById("regContentLang")?.value
      || document.getElementById("loginContentLang")?.value
      || window.HubI18n?.readLang?.() || "en";
    if (window.HubI18n?.setLang) window.HubI18n.setLang(contentLang);
    if (HP) HP.rememberPrefs(preferred, home || "mandi", contentLang);
    else {
      if (home) localStorage.setItem("hub_board_locality", home);
      localStorage.setItem("hub_preferred_board", preferred);
    }

    if (overrides.preferredBoard || overrides.homeLocality) {
      try {
        await api("/api/hub/providers/me", {
          method: "PATCH",
          body: JSON.stringify({
            preferredBoard: preferred,
            homeLocality: home || localStorage.getItem("hub_board_locality") || "mandi",
          }),
        });
      } catch {
        /* keep going */
      }
    }

    const dest = isGenericNext(nextRaw) ? boardHome(preferred) : nextPath;
    location.href = dest;
  }

  function showLogin(on) {
    $("registerForm").hidden = on;
    $("loginForm").hidden = !on;
    $("tabRegister").setAttribute("aria-selected", on ? "false" : "true");
    $("tabLogin").setAttribute("aria-selected", on ? "true" : "false");
  }

  function fail(err) {
    $("authError").hidden = false;
    $("authError").textContent = err.message;
  }

  async function uploadPhoto(file) {
    if (!file) throw new Error(t("needPhoto"));
    if (file.size > MAX_PHOTO_BYTES) throw new Error(t("photoTooBig"));
    const body = new FormData();
    body.append("file", file);
    const res = await fetch("/api/hub/providers/photo", {
      method: "POST",
      credentials: "same-origin",
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    return data.photoUrl || data.photo || "";
  }

  $("regPhoto")?.addEventListener("change", () => {
    uploadedPhotoUrl = "";
    const file = $("regPhoto").files?.[0];
    const preview = $("regPhotoPreview");
    if (!file || !preview) {
      if (preview) preview.hidden = true;
      return;
    }
    if (file.size > MAX_PHOTO_BYTES) {
      $("regPhoto").value = "";
      preview.hidden = true;
      fail(new Error(t("photoTooBig")));
      return;
    }
    $("authError").hidden = true;
    preview.src = URL.createObjectURL(file);
    preview.hidden = false;
  });

  document.querySelectorAll(".labour-lang-btn, .hub-lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyLang(btn.getAttribute("data-lang")));
  });
  document.addEventListener("hub:lang", (event) => {
    applyLang(event.detail?.lang || window.HubI18n?.readLang?.() || "en");
  });

  $("tabRegister").addEventListener("click", () => showLogin(false));
  $("tabLogin").addEventListener("click", () => showLogin(true));
  if (params.get("mode") === "login") showLogin(true);

  $("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      const file = $("regPhoto").files?.[0];
      if (!file && !uploadedPhotoUrl) throw new Error(t("needPhoto"));
      if (file && file.size > MAX_PHOTO_BYTES) throw new Error(t("photoTooBig"));
      $("authError").hidden = false;
      $("authError").textContent = t("uploading");
      if (!uploadedPhotoUrl) {
        uploadedPhotoUrl = await uploadPhoto(file);
      }
      const preferred = window.HubPrefs
        ? window.HubPrefs.normalizeBoard($("regPreferredBoard")?.value || boardId)
        : boardId;
      const sess = await api("/api/hub/providers/register", {
        method: "POST",
        body: JSON.stringify({
          phone: $("regPhone").value.trim(),
          name: $("regName").value.trim(),
          email: $("regEmail").value.trim(),
          address: $("regAddress").value.trim(),
          officialId: $("regOfficialId").value.trim(),
          password: $("regPassword").value,
          photo: uploadedPhotoUrl,
          boardId,
          preferredBoard: preferred,
          homeLocality: $("regLocality")?.value || "mandi",
          contentLang: $("regContentLang")?.value || window.HubI18n?.readLang?.() || "en",
        }),
      });
      await routeAfterAuth(sess, {
        preferredBoard: preferred,
        homeLocality: $("regLocality")?.value || "mandi",
      });
    } catch (err) {
      fail(err);
    }
  });

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      const preferred = window.HubPrefs
        ? window.HubPrefs.normalizeBoard($("loginPreferredBoard")?.value || boardId)
        : (($("loginPreferredBoard")?.value || boardId) === "taxi" ? "taxi" : "labour");
      const locality = $("loginLocality")?.value || "mandi";
      const loginBoard = preferred === "taxi" || preferred === "labour" ? preferred : boardId;
      const sess = await api("/api/hub/providers/login", {
        method: "POST",
        body: JSON.stringify({
          phone: $("loginPhone").value.trim(),
          password: $("loginPassword").value,
          contentLang: $("loginContentLang")?.value || window.HubI18n?.readLang?.() || "en",
          preferredBoard: preferred,
          homeLocality: locality,
          boardId: loginBoard,
        }),
      });
      await routeAfterAuth(sess, { preferredBoard: preferred, homeLocality: locality });
    } catch (err) {
      fail(err);
    }
  });

  applyLang(lang);
  fillLocalities();

  api("/api/hub/providers/session")
    .then((sess) => {
      if (Array.isArray(sess.localities) && sess.localities.length) {
        localities = sess.localities;
        fillLocalities();
      }
        if (sess.authenticated) {
        if ($("loginPreferredBoard") && sess.provider?.preferredBoard && window.HubPrefs) {
          const pref = window.HubPrefs.normalizeBoard(sess.provider.preferredBoard);
          $("loginPreferredBoard").value = pref;
          window.HubPrefs.mountBoardPicker("loginBoardPicker", "loginPreferredBoard", pref);
          window.HubPrefs.mountBoardPicker("regBoardPicker", "regPreferredBoard", pref);
        }
        if ($("loginLocality") && sess.provider?.homeLocality) {
          $("loginLocality").value = sess.provider.homeLocality;
        }
        routeAfterAuth(sess).catch(() => {});
      }
    })
    .catch(() => {});
})();
