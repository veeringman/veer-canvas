(() => {
  const BOARD_TZ = "Asia/Kolkata";
  const LOCALITY_KEY = "hub_board_locality";

  const COPY = {
    labour: {
      en: {
        modalTitle: "I'm available",
        modalHint: "Your number stays private. Only the person who posted this need can see it and call you back.",
        name: "Your name",
        phone: "Mobile number",
        note: "Note (optional)",
        notePh: "e.g. free after 8am, garden work OK",
        submit: "Send interest",
        cancel: "Cancel",
        needSignIn: "Register or sign in to show interest.",
        ok: "Sent. The poster can call you back from their desk.",
        available: "Available today",
        viewProfile: "View profile",
        contactPrivate: "Contact stays private until you respond to a need through the app.",
        respondCta: "Respond via a need on this board",
        close: "Close",
        markPrompt: "Optional note for today’s board:",
        providerLabel: "Available worker",
      },
      hi: {
        modalTitle: "मैं उपलब्ध हूँ",
        modalHint: "आपका नंबर छिपा रहेगा। सिर्फ ज़रूरत पोस्ट करने वाला इसे देखकर आपको कॉल कर सकता है।",
        name: "आपका नाम",
        phone: "मोबाइल नंबर",
        note: "नोट (वैकल्पिक)",
        notePh: "जैसे सुबह 8 बजे बाद, बागवानी ठीक",
        submit: "रुचि भेजें",
        cancel: "रद्द",
        needSignIn: "रुचि दिखाने के लिए पंजीकरण या साइन इन करें।",
        ok: "भेज दिया। पोस्टर अपने डेस्क से आपको वापस कॉल कर सकते हैं।",
        available: "आज उपलब्ध",
        viewProfile: "प्रोफ़ाइल देखें",
        contactPrivate: "संपर्क ऐप में ज़रूरत पर जवाब देने तक निजी रहता है।",
        respondCta: "इस बोर्ड की ज़रूरत पर जवाब दें",
        close: "बंद",
        markPrompt: "आज के बोर्ड के लिए नोट (वैकल्पिक):",
        providerLabel: "उपलब्ध मजदूर",
      },
    },
    taxi: {
      en: {
        modalTitle: "I can take this ride",
        modalHint: "Your number stays private. Only the person who posted this ride can see it.",
        name: "Your name",
        phone: "Mobile number",
        note: "Note (optional)",
        notePh: "e.g. sedan, free after 4pm",
        submit: "Send offer",
        cancel: "Cancel",
        needSignIn: "Register or sign in as a driver to respond.",
        ok: "Sent. The poster can call you back from their desk.",
        available: "On duty today",
        viewProfile: "View profile",
        contactPrivate: "Contact stays private until you respond to a ride request through the app.",
        respondCta: "Respond via a ride request on this board",
        close: "Close",
        markPrompt: "Optional note for today’s cab board:",
        providerLabel: "Driver on duty",
      },
      hi: {
        modalTitle: "मैं यह सवारी ले सकता/सकती हूँ",
        modalHint: "आपका नंबर छिपा रहेगा। सिर्फ सवारी पोस्ट करने वाला इसे देख सकता है।",
        name: "आपका नाम",
        phone: "मोबाइल नंबर",
        note: "नोट (वैकल्पिक)",
        notePh: "जैसे सेडान, शाम 4 बाद",
        submit: "ऑफ़र भेजें",
        cancel: "रद्द",
        needSignIn: "जवाब देने के लिए ड्राइवर के रूप में पंजीकरण या साइन इन करें।",
        ok: "भेज दिया। पोस्टर अपने डेस्क से आपको वापस कॉल कर सकते हैं।",
        available: "आज ड्यूटी पर",
        viewProfile: "प्रोफ़ाइल देखें",
        contactPrivate: "संपर्क ऐप में सवारी अनुरोध पर जवाब देने तक निजी रहता है।",
        respondCta: "इस बोर्ड की सवारी पर जवाब दें",
        close: "बंद",
        markPrompt: "आज के कैब बोर्ड के लिए नोट (वैकल्पिक):",
        providerLabel: "ड्यूटी पर ड्राइवर",
      },
    },
  };


  function serviceBoardCopy(label, labelHi, availableEn, availableHi, providerEn, providerHi) {
    return {
      en: {
        modalTitle: "I can help",
        modalHint: "Your number stays private. Only the person who posted this need can see it.",
        name: "Your name",
        phone: "Mobile number",
        note: "Note (optional)",
        notePh: "e.g. available after 4pm",
        submit: "Send interest",
        cancel: "Cancel",
        needSignIn: "Register or sign in to respond.",
        ok: "Sent. The poster can call you back from their desk.",
        available: availableEn,
        viewProfile: "View profile",
        contactPrivate: "Contact stays private until you respond through the app.",
        respondCta: "Respond via a need on this board",
        close: "Close",
        markPrompt: "Optional note for today’s board:",
        providerLabel: providerEn,
      },
      hi: {
        modalTitle: "मैं मदद कर सकता/सकती हूँ",
        modalHint: "आपका नंबर छिपा रहेगा। सिर्फ ज़रूरत पोस्ट करने वाला इसे देख सकता है।",
        name: "आपका नाम",
        phone: "मोबाइल नंबर",
        note: "नोट (वैकल्पिक)",
        notePh: "जैसे शाम 4 बाद",
        submit: "रुचि भेजें",
        cancel: "रद्द",
        needSignIn: "जवाब देने के लिए पंजीकरण या साइन इन करें।",
        ok: "भेज दिया। पोस्टर अपने डेस्क से आपको वापस कॉल कर सकते हैं।",
        available: availableHi,
        viewProfile: "प्रोफ़ाइल देखें",
        contactPrivate: "संपर्क ऐप में जवाब देने तक निजी रहता है।",
        respondCta: "इस बोर्ड की ज़रूरत पर जवाब दें",
        close: "बंद",
        markPrompt: "आज के बोर्ड के लिए नोट (वैकल्पिक):",
        providerLabel: providerHi,
      },
    };
  }
  COPY.experts = serviceBoardCopy("Experts", "विशेषज्ञ", "Available today", "आज उपलब्ध", "Expert", "विशेषज्ञ");
  COPY.vehicle = serviceBoardCopy("Vehicle", "वाहन", "On duty today", "आज ड्यूटी", "Mechanic", "मैकेनिक");
  COPY.doctor = serviceBoardCopy("Doctor", "डॉक्टर", "On call today", "आज ऑन कॉल", "Doctor", "डॉक्टर");
  COPY.tours = serviceBoardCopy("Tours", "टूर्स", "Available today", "आज उपलब्ध", "Guide / desk", "गाइड");
  COPY.tutors = serviceBoardCopy("Tutors", "ट्यूटर", "Available today", "आज उपलब्ध", "Tutor / mentor", "ट्यूटर");
  COPY.home = serviceBoardCopy("Home", "घर", "Available today", "आज उपलब्ध", "Home pro", "घर सेवा");

  const SERVICE_META = {
    experts: { title: "SME & experts", titleHi: "विशेषज्ञ और SME", kicker: "Expertise · विशेषज्ञ", needs: "Requests · अनुरोध", providers: "Experts available · उपलब्ध विशेषज्ञ", mark: "Mark available today · आज उपलब्ध", regPath: "/partner?board=experts" },
    vehicle: { title: "Vehicle servicing", titleHi: "वाहन सर्विस", kicker: "Garage · गैरेज", needs: "Service needs · सर्विस ज़रूरत", providers: "On duty · ड्यूटी पर", mark: "Mark on duty today · आज ड्यूटी", regPath: "/partner?board=vehicle" },
    doctor: { title: "Doc on call", titleHi: "डॉक्टर ऑन कॉल", kicker: "Health · स्वास्थ्य", needs: "Consult requests · परामर्श", providers: "On call · ऑन कॉल", mark: "Mark on call today · आज ऑन कॉल", regPath: "/partner?board=doctor" },
    tours: { title: "Tours & travels", titleHi: "टूर्स और ट्रैवल", kicker: "Travel · यात्रा", needs: "Trip requests · यात्रा अनुरोध", providers: "Guides & desks · गाइड", mark: "Mark available today · आज उपलब्ध", regPath: "/partner?board=tours" },
    tutors: { title: "Tutors & mentoring", titleHi: "ट्यूटर और मेंटरिंग", kicker: "Learn · सीखें", needs: "Learning needs · सीखने की ज़रूरत", providers: "Tutors · ट्यूटर", mark: "Mark available today · आज उपलब्ध", regPath: "/partner?board=tutors" },
    home: { title: "Home services", titleHi: "घर सेवाएँ", kicker: "Home · घर", needs: "Home needs · घरेलू ज़रूरत", providers: "Pros available · उपलब्ध", mark: "Mark available today · आज उपलब्ध", regPath: "/partner?board=home" },
  };

  const BOARDS = {
    labour: {
      id: "labour",
      sectionId: "landing-labour",
      legacySectionId: "landing-seri",
      listId: "landingLabourList",
      legacyListId: "landingSeriList",
      providersId: "landingLabourProviders",
      legacyProvidersId: "landingSeriWorkers",
      registerBtn: "labourRegisterBtn",
      signInBtn: "labourSignInBtn",
      markBtn: "labourMarkAvailableBtn",
      logoutBtn: "labourLogoutBtn",
      statusId: "labourProviderStatus",
      prefsBtn: "labourPrefsBtn",
      localitySelect: "labourLocalitySelect",
      registerPath: "/labour",
      heroId: "landingHeroLabour",
      morning: { startHour: 6, endHour: 10 },
      interestAttr: "data-board-interest",
      providerAttr: "data-board-provider",
      liveLocality: true,
    },
    taxi: {
      id: "taxi",
      sectionId: "landing-taxi",
      listId: "landingTaxiList",
      providersId: "landingTaxiProviders",
      registerBtn: "taxiRegisterBtn",
      signInBtn: "taxiSignInBtn",
      markBtn: "taxiMarkAvailableBtn",
      logoutBtn: "taxiLogoutBtn",
      statusId: "taxiProviderStatus",
      prefsBtn: "taxiPrefsBtn",
      localitySelect: "taxiLocalitySelect",
      registerPath: "/taxi",
      heroId: null,
      morning: null,
      interestAttr: "data-board-interest",
      providerAttr: "data-board-provider",
      liveLocality: true,
    },
  };

  Object.keys(SERVICE_META).forEach((id) => {
    const cap = id[0].toUpperCase() + id.slice(1);
    BOARDS[id] = {
      id,
      sectionId: `landing-${id}`,
      listId: `landing${cap}List`,
      providersId: `landing${cap}Providers`,
      registerBtn: `${id}RegisterBtn`,
      signInBtn: `${id}SignInBtn`,
      markBtn: `${id}MarkAvailableBtn`,
      logoutBtn: `${id}LogoutBtn`,
      statusId: `${id}ProviderStatus`,
      prefsBtn: `${id}PrefsBtn`,
      localitySelect: `${id}LocalitySelect`,
      registerPath: SERVICE_META[id].regPath,
      heroId: null,
      morning: null,
      interestAttr: "data-board-interest",
      providerAttr: "data-board-provider",
      liveLocality: ["vehicle", "doctor", "tours", "home"].includes(id),
      meta: SERVICE_META[id],
    };
  });

  function ensureLandingSections() {
    const anchor = document.getElementById("landing-taxi");
    if (!anchor || !anchor.parentElement) return;
    Object.keys(SERVICE_META).forEach((id) => {
      if (document.getElementById(`landing-${id}`)) return;
      const m = SERVICE_META[id];
      const board = BOARDS[id];
      const cap = id[0].toUpperCase() + id.slice(1);
      const next = encodeURIComponent(`/#landing-${id}`);
      const section = document.createElement("section");
      section.className = "landing-section";
      section.id = `landing-${id}`;
      section.setAttribute("aria-labelledby", `landing${cap}Title`);
      section.lang = "en";
      section.innerHTML = `
          <header class="landing-section-head">
            <div>
              <p class="landing-section-kicker">${m.kicker}</p>
              <h2 id="landing${cap}Title">${m.title} <span class="seri-hi-title" lang="hi">${m.titleHi}</span></h2>
            </div>
            <p class="muted landing-section-lede">
              Needs on the board; partners respond in-app. Contact stays private until a response.
              <span class="seri-hi-line" lang="hi">ज़रूरत बोर्ड पर; जवाब ऐप में। संपर्क जवाब तक निजी।</span>
            </p>
          </header>
          <div class="seri-board-actions" id="${id}BoardActions">
            <label class="board-locality-label muted">Area
              <select id="${board.localitySelect}" class="board-locality-select" aria-label="Home locality filter"></select>
            </label>
            <button type="button" class="btn ghost compact hub-locate-inline" data-hub-locate="${id}">Use my location</button>
            <a class="btn primary compact" id="${board.registerBtn}" href="${board.registerPath}&amp;next=${next}">Register · पंजीकरण</a>
            <a class="btn ghost compact" id="${board.signInBtn}" href="${board.registerPath}&amp;mode=login&amp;next=${next}">Sign in · साइन इन</a>
            <button type="button" class="btn primary compact" id="${board.markBtn}" hidden>${m.mark}</button>
            <button type="button" class="btn ghost compact" id="${board.logoutBtn}" hidden>Sign out · साइन आउट</button>
            <a class="btn ghost compact" id="${board.prefsBtn}" href="/account" hidden>Preferences · प्राथमिकताएँ</a>
            <a class="btn ghost compact" href="/join?next=${next}">Post a need · ज़रूरत लिखें</a>
          </div>
          <p class="seri-worker-status muted" id="${board.statusId}" hidden></p>
          <div class="seri-board-grid">
            <div class="seri-board-col">
              <h3 class="seri-board-col-title">${m.needs}</h3>
              <div id="${board.listId}" class="landing-grid landing-grid-ads">
                <article class="landing-card">
                  <p class="landing-meta">How it works</p>
                  <strong>Post a need · ज़रूरत लिखें</strong>
                  <p>Publish what you need. Registered partners respond; only you see their number on the publish desk.</p>
                  <p class="landing-contact"><a href="/join?next=${next}">Publish · प्रकाशित करें</a></p>
                </article>
              </div>
            </div>
            <div class="seri-board-col">
              <h3 class="seri-board-col-title">${m.providers}</h3>
              <div id="${board.providersId}" class="landing-grid landing-grid-ads">
                <article class="landing-card" data-board-providers-empty="1">
                  <p class="landing-meta">Partners</p>
                  <strong>Register, then mark available · पंजीकरण, फिर उपलब्ध</strong>
                  <p>Profiles show name, photo, and area — not phone numbers.</p>
                  <p class="landing-contact"><a href="${board.registerPath}&amp;next=${next}">Partner registration</a></p>
                </article>
              </div>
            </div>
          </div>`;
      // Insert after taxi (or after previous service section)
      const last = document.getElementById("landing-home")
        || document.getElementById("landing-tutors")
        || document.getElementById("landing-tours")
        || document.getElementById("landing-doctor")
        || document.getElementById("landing-vehicle")
        || document.getElementById("landing-experts")
        || anchor;
      last.insertAdjacentElement("afterend", section);
    });
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function t(boardId, key) {
    const pack = COPY[boardId] || COPY.labour;
    return `${pack.en[key]} · ${pack.hi[key]}`;
  }

  function kolkataHour(date = new Date()) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: BOARD_TZ,
      hour: "numeric",
      hourCycle: "h23",
    }).formatToParts(date);
    const hour = parts.find((p) => p.type === "hour")?.value;
    return Number(hour);
  }

  function isMorningWindow(board) {
    if (!board.morning) return false;
    const hour = kolkataHour();
    return hour >= board.morning.startHour && hour < board.morning.endHour;
  }

  function currentLocality() {
    return localStorage.getItem(LOCALITY_KEY) || "mandi";
  }

  function setLocality(id) {
    localStorage.setItem(LOCALITY_KEY, id || "mandi");
  }

  function resolveSection(board) {
    return document.getElementById(board.sectionId)
      || (board.legacySectionId ? document.getElementById(board.legacySectionId) : null);
  }

  function resolveList(board) {
    return document.getElementById(board.listId)
      || (board.legacyListId ? document.getElementById(board.legacyListId) : null);
  }

  function resolveProviders(board) {
    return document.getElementById(board.providersId)
      || (board.legacyProvidersId ? document.getElementById(board.legacyProvidersId) : null);
  }

  function syncLabourMorningHero() {
    const board = BOARDS.labour;
    const live = isMorningWindow(board);
    const hero = document.getElementById("landingHero");
    const banner = document.getElementById(board.heroId) || document.getElementById("landingHeroSeri");
    const section = resolveSection(board);
    if (hero) hero.classList.toggle("is-seri-morning", live);
    if (banner) banner.hidden = !live;
    if (section) section.classList.toggle("is-seri-morning", live);
  }

  async function hasSession() {
    const [provider, pub, adda] = await Promise.all([
      fetch("/api/hub/providers/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
      fetch("/api/hub/publisher/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
      fetch("/api/adda/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
    ]);
    const name = provider.provider?.name
      || provider.worker?.name
      || pub.publisher?.name
      || adda.user?.displayName
      || adda.user?.display_name
      || "";
    const phone = provider.provider?.phone || provider.worker?.phone || "";
    return {
      ok: !!(provider.authenticated || pub.authenticated || adda.authenticated || adda.user),
      name: String(name || "").trim(),
      phone: String(phone || "").trim(),
      isProvider: !!provider.authenticated,
      preferredBoard: provider.provider?.preferredBoard || "labour",
      homeLocality: provider.provider?.homeLocality || "mandi",
      session: provider,
    };
  }

  function ensureInterestModal(boardId) {
    const id = `boardInterestModal-${boardId}`;
    let root = document.getElementById(id);
    if (root) return root;
    root = document.createElement("div");
    root.id = id;
    root.className = "seri-modal board-modal";
    root.hidden = true;
    root.dataset.boardId = boardId;
    root.innerHTML = `
      <div class="seri-modal-backdrop" data-board-close></div>
      <div class="seri-modal-card" role="dialog" aria-modal="true">
        <p class="landing-section-kicker">${boardId === "taxi" ? "Cabs & taxis · कैब" : "Labour · मज़दूर"}</p>
        <h3 data-role="title"></h3>
        <p class="muted" data-role="need"></p>
        <p class="muted" data-role="hint"></p>
        <form class="desk-form" data-role="form">
          <label data-role="nameLabel">Name
            <input name="name" required minlength="2" autocomplete="name" data-role="name">
          </label>
          <label data-role="phoneLabel">Phone
            <input name="phone" required inputmode="tel" autocomplete="tel" minlength="8" data-role="phone">
          </label>
          <label data-role="noteLabel">Note
            <textarea name="note" rows="2" data-role="note"></textarea>
          </label>
          <p class="error" data-role="error" hidden></p>
          <div class="desk-actions">
            <button type="submit" class="btn primary" data-role="submit"></button>
            <button type="button" class="btn ghost" data-board-close data-role="cancel"></button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(root);
    root.querySelectorAll("[data-board-close]").forEach((node) => {
      node.addEventListener("click", () => {
        root.hidden = true;
        root.dataset.postId = "";
      });
    });
    root.querySelector("[data-role='form']").addEventListener("submit", async (event) => {
      event.preventDefault();
      const postId = root.dataset.postId;
      const err = root.querySelector("[data-role='error']");
      err.hidden = true;
      if (!postId) return;
      try {
        const res = await fetch(`/api/hub/posts/${encodeURIComponent(postId)}/interest`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: root.querySelector("[data-role='name']").value.trim(),
            phone: root.querySelector("[data-role='phone']").value.trim(),
            note: root.querySelector("[data-role='note']").value.trim(),
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
        root.hidden = true;
        window.alert(t(boardId, "ok"));
        document.dispatchEvent(new CustomEvent("city:live", {
          detail: { changed: ["feed", "boards"], rev: `board-${Date.now()}` },
        }));
      } catch (ex) {
        err.hidden = false;
        err.textContent = ex.message;
      }
    });
    return root;
  }

  function openInterestModal(boardId, postId, title, sess) {
    const root = ensureInterestModal(boardId);
    root.dataset.postId = String(postId);
    root.querySelector("[data-role='title']").textContent = t(boardId, "modalTitle");
    root.querySelector("[data-role='need']").textContent = title || "";
    root.querySelector("[data-role='hint']").textContent = t(boardId, "modalHint");
    root.querySelector("[data-role='nameLabel']").childNodes[0].textContent = `${t(boardId, "name")} `;
    root.querySelector("[data-role='phoneLabel']").childNodes[0].textContent = `${t(boardId, "phone")} `;
    root.querySelector("[data-role='noteLabel']").childNodes[0].textContent = `${t(boardId, "note")} `;
    root.querySelector("[data-role='note']").placeholder = t(boardId, "notePh");
    root.querySelector("[data-role='submit']").textContent = t(boardId, "submit");
    root.querySelector("[data-role='cancel']").textContent = t(boardId, "cancel");
    root.querySelector("[data-role='error']").hidden = true;
    const nameInput = root.querySelector("[data-role='name']");
    const phoneInput = root.querySelector("[data-role='phone']");
    if (sess?.name && !nameInput.value) nameInput.value = sess.name;
    if (sess?.phone) {
      phoneInput.value = sess.phone;
      phoneInput.readOnly = !!sess.isProvider;
    }
    root.hidden = false;
    nameInput.focus();
  }

  const providersByBoard = { labour: {}, taxi: {} };

  function providerCard(boardId, row) {
    const skills = Array.isArray(row.skills) ? row.skills.filter(Boolean) : [];
    const meta = [skills.slice(0, 3).join(" · "), row.location].filter(Boolean).join(" · ");
    const photo = row.photo
      ? `<img class="seri-worker-thumb" src="${esc(row.photo)}" alt="" width="56" height="56" loading="lazy" decoding="async">`
      : `<span class="seri-worker-thumb is-empty" aria-hidden="true"></span>`;
    return `<button type="button" class="landing-card is-seri-worker" data-board-provider="${esc(row.id)}" data-board-id="${esc(boardId)}" aria-label="View ${esc(row.name || "provider")}">
      <span class="seri-worker-card-top">
        ${photo}
        <span class="seri-worker-card-copy">
          <span class="landing-meta">${esc(t(boardId, "available"))}${meta ? ` · ${esc(meta)}` : ""}</span>
          <strong>${esc(row.name || "Provider")}</strong>
          <span class="seri-worker-card-note">${esc(row.note || "")}</span>
        </span>
      </span>
      <span class="seri-worker-card-cta">${esc(t(boardId, "viewProfile"))}</span>
    </button>`;
  }

  function ensureProviderModal() {
    let root = document.getElementById("boardProviderModal");
    if (root) return root;
    root = document.createElement("div");
    root.id = "boardProviderModal";
    root.className = "seri-modal board-modal";
    root.hidden = true;
    root.innerHTML = `
      <div class="seri-modal-backdrop" data-board-provider-close></div>
      <div class="seri-modal-card seri-worker-modal-card" role="dialog" aria-modal="true">
        <p class="landing-section-kicker" id="boardProviderModalKicker"></p>
        <img id="boardProviderModalPhoto" class="seri-worker-modal-photo" alt="" width="160" height="160" hidden>
        <h3 id="boardProviderModalTitle"></h3>
        <p class="muted" id="boardProviderModalMeta"></p>
        <p id="boardProviderModalNote"></p>
        <p class="seri-worker-modal-contact" id="boardProviderModalContact"></p>
        <div class="desk-actions">
          <a class="btn primary" id="boardProviderModalRespond" href="#landing-labour">Respond</a>
          <button type="button" class="btn ghost" data-board-provider-close id="boardProviderModalClose">Close</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);
    root.querySelectorAll("[data-board-provider-close]").forEach((node) => {
      node.addEventListener("click", () => {
        root.hidden = true;
      });
    });
    return root;
  }

  function openProviderModal(boardId, provider) {
    if (!provider) return;
    const root = ensureProviderModal();
    const board = BOARDS[boardId] || BOARDS.labour;
    root.querySelector("#boardProviderModalKicker").textContent = t(boardId, "providerLabel");
    root.querySelector("#boardProviderModalTitle").textContent = provider.name || "Provider";
    const skills = Array.isArray(provider.skills) ? provider.skills.filter(Boolean).join(" · ") : "";
    root.querySelector("#boardProviderModalMeta").textContent = [skills, provider.location || provider.address]
      .filter(Boolean)
      .join(" · ");
    root.querySelector("#boardProviderModalNote").textContent = provider.note || "";
    const photo = root.querySelector("#boardProviderModalPhoto");
    if (provider.photo) {
      photo.src = provider.photo;
      photo.hidden = false;
    } else {
      photo.removeAttribute("src");
      photo.hidden = true;
    }
    root.querySelector("#boardProviderModalContact").textContent = t(boardId, "contactPrivate");
    const respond = root.querySelector("#boardProviderModalRespond");
    respond.textContent = t(boardId, "respondCta");
    respond.href = `#${board.sectionId}`;
    root.querySelector("#boardProviderModalClose").textContent = t(boardId, "close");
    root.hidden = false;
  }

  async function loadProviders(boardId) {
    const board = BOARDS[boardId];
    if (!board) return;
    const list = resolveProviders(board);
    if (!list) return;
    const empty = list.querySelector("[data-board-providers-empty='1'], [data-seri-workers-empty='1']");
    const locality = currentLocality();
    try {
      const q = locality ? `?locality=${encodeURIComponent(locality)}` : "";
      const res = await fetch(`/api/hub/boards/${boardId}/providers${q}`, {
        cache: "no-store",
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      const rows = Array.isArray(data.providers) ? data.providers : (data.workers || []);
      providersByBoard[boardId] = {};
      rows.forEach((w) => {
        if (w?.id) providersByBoard[boardId][w.id] = w;
      });
      list.querySelectorAll("[data-board-provider], [data-seri-worker]").forEach((node) => node.remove());
      if (!rows.length) {
        if (empty) empty.hidden = false;
        return;
      }
      list.insertAdjacentHTML("afterbegin", rows.map((r) => providerCard(boardId, r)).join(""));
      if (empty) empty.hidden = true;
    } catch {
      /* keep empty state */
    }
  }

  async function refreshDesk(boardId) {
    const board = BOARDS[boardId];
    if (!board) return;
    const registerBtn = document.getElementById(board.registerBtn)
      || (boardId === "labour" ? document.getElementById("seriRegisterBtn") : null);
    const signInBtn = document.getElementById(board.signInBtn)
      || (boardId === "labour" ? document.getElementById("seriSignInBtn") : null);
    const markBtn = document.getElementById(board.markBtn)
      || (boardId === "labour" ? document.getElementById("seriMarkAvailableBtn") : null);
    const logoutBtn = document.getElementById(board.logoutBtn)
      || (boardId === "labour" ? document.getElementById("seriWorkerLogoutBtn") : null);
    const status = document.getElementById(board.statusId)
      || (boardId === "labour" ? document.getElementById("seriWorkerStatus") : null);
    if (!registerBtn || !signInBtn || !markBtn || !logoutBtn || !status) return;

    const next = encodeURIComponent(`/#${board.sectionId}`);
    registerBtn.href = `${board.registerPath}?next=${next}`;
    signInBtn.href = `${board.registerPath}?mode=login&next=${next}`;

    let sess = {};
    try {
      const res = await fetch("/api/hub/providers/session", {
        credentials: "same-origin",
        cache: "no-store",
      });
      sess = await res.json().catch(() => ({}));
    } catch {
      sess = {};
    }

    const on = !!sess.authenticated;
    registerBtn.hidden = on;
    signInBtn.hidden = on;
    markBtn.hidden = !on;
    logoutBtn.hidden = !on;
    status.hidden = !on;

    const prefs = document.getElementById(board.prefsBtn);
    if (prefs) prefs.hidden = !on;

    if (on) {
      const name = sess.provider?.name || sess.worker?.name || "Provider";
      const avail = sess.availableByBoard?.[boardId] || {};
      const available = !!avail.available || (boardId === "labour" && !!sess.worker?.availableToday);
      status.textContent = available
        ? `${name} · on today’s ${boardId} board`
        : `${name} · mark available for today’s ${boardId} board`;
      markBtn.textContent = available
        ? (boardId === "taxi" ? "Update note / stay on duty · अपडेट" : "Update note / stay available · अपडेट")
        : (boardId === "taxi" ? "Mark on duty today · आज ड्यूटी" : "Mark available today · आज उपलब्ध");
      markBtn.dataset.available = available ? "1" : "0";
      markBtn.dataset.boardId = boardId;
    }

    fillLocalitySelect(board, sess);
  }

  function fillLocalitySelect(board, sess) {
    const select = document.getElementById(board.localitySelect);
    if (!select) return;
    const localities = Array.isArray(sess?.localities) && sess.localities.length
      ? sess.localities
      : (window.HubPrefs?.LOCALITIES || [
      { id: "mandi", label: "Mandi" },
      { id: "sundernagar", label: "Sunder Nagar" },
      { id: "nerchowk", label: "Ner Chowk" },
      { id: "sarkaghat", label: "Sarkaghat" },
      { id: "pandoh", label: "Pandoh" },
    ]);
    const current = currentLocality();
    select.innerHTML = localities.map((row) =>
      `<option value="${esc(row.id)}"${row.id === current ? " selected" : ""}>${esc(row.label)}</option>`
    ).join("");
    select.onchange = () => {
      setLocality(select.value);
      loadProviders(board.id).catch(() => {});
    };
  }

  async function markAvailable(boardId) {
    const note = window.prompt(t(boardId, "markPrompt"), "");
    if (note === null) return;
    const res = await fetch(`/api/hub/boards/${boardId}/availability`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ available: true, note: String(note || "").trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    await refreshDesk(boardId);
    await loadProviders(boardId);
    document.dispatchEvent(new CustomEvent("city:live", {
      detail: { changed: ["boards", "seri"], rev: `board-avail-${Date.now()}` },
    }));
  }

  function openBoardSection(hashId) {
    const shell = document.getElementById("landingView");
    const section = document.getElementById(hashId);
    if (shell && !shell.classList.contains("board-open")) {
      shell.classList.add("board-open");
      const board = document.getElementById("landing-board");
      const connect = document.getElementById("landing-connect-band");
      if (board) board.hidden = false;
      if (connect) connect.hidden = false;
      history.pushState(null, "", `${location.pathname}${location.search}#${hashId}`);
    }
    requestAnimationFrame(() => {
      section?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // Legacy hash alias
  if (location.hash === "#landing-seri") {
    history.replaceState(null, "", `${location.pathname}${location.search}#landing-labour`);
  }

  document.addEventListener("click", async (event) => {
    const interestBtn = event.target.closest("[data-board-interest], [data-seri-interest]");
    if (interestBtn) {
      event.preventDefault();
      const postId = interestBtn.getAttribute("data-board-interest")
        || interestBtn.getAttribute("data-seri-interest");
      const title = interestBtn.getAttribute("data-board-title")
        || interestBtn.getAttribute("data-seri-title")
        || "";
      const boardId = interestBtn.getAttribute("data-board-id") || "labour";
      const sess = await hasSession();
      if (!sess.ok) {
        const next = encodeURIComponent(`${location.pathname}${location.search}#${BOARDS[boardId]?.sectionId || "landing-labour"}`);
        const base = BOARDS[boardId]?.registerPath || "/labour";
        const join = base.includes("?") ? "&" : "?";
        location.href = `${base}${join}mode=login&next=${next}`;
        return;
      }
      openInterestModal(boardId, postId, title, sess);
      return;
    }

    const providerBtn = event.target.closest("[data-board-provider], [data-seri-worker]");
    if (providerBtn) {
      event.preventDefault();
      const id = providerBtn.getAttribute("data-board-provider")
        || providerBtn.getAttribute("data-seri-worker");
      const boardId = providerBtn.getAttribute("data-board-id") || "labour";
      openProviderModal(boardId, providersByBoard[boardId]?.[id]);
    }
  });

  Object.values(BOARDS).forEach((board) => {
    const mark = document.getElementById(board.markBtn)
      || (board.id === "labour" ? document.getElementById("seriMarkAvailableBtn") : null);
    mark?.addEventListener("click", async () => {
      try {
        await markAvailable(board.id);
      } catch (ex) {
        window.alert(ex.message || "Could not mark available");
      }
    });
    const logout = document.getElementById(board.logoutBtn)
      || (board.id === "labour" ? document.getElementById("seriWorkerLogoutBtn") : null);
    logout?.addEventListener("click", async () => {
      try {
        await fetch("/api/hub/providers/logout", { method: "POST", credentials: "same-origin" });
      } catch {
        /* ignore */
      }
      await refreshDesk(board.id);
    });
  });

  const hero = document.getElementById("landingHeroLabour") || document.getElementById("landingHeroSeri");
  hero?.addEventListener("click", (event) => {
    event.preventDefault();
    openBoardSection("landing-labour");
  });

  document.addEventListener("city:live", (event) => {
    const changed = event.detail?.changed || [];
    if (changed.some((key) => key === "seri" || key === "feed" || key === "boards")) {
      Object.keys(BOARDS).forEach((id) => {
        loadProviders(id).catch(() => {});
        refreshDesk(id).catch(() => {});
      });
    }
  });

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-hub-locate]");
    if (!btn) return;
    event.preventDefault();
    const boardId = btn.getAttribute("data-hub-locate");
    window.HubGeo?.autoPreferForLive(boardId, { force: true }).then((nearest) => {
      if (!nearest?.id) return;
      setLocality(nearest.id);
      const board = BOARDS[boardId];
      const select = board && document.getElementById(board.localitySelect);
      if (select) {
        select.value = nearest.id;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      loadProviders(boardId).catch(() => {});
    }).catch(() => {});
  });

  syncLabourMorningHero();
  window.setInterval(syncLabourMorningHero, 60_000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      syncLabourMorningHero();
      Object.keys(BOARDS).forEach((id) => {
        refreshDesk(id).catch(() => {});
        loadProviders(id).catch(() => {});
      });
    }
  });

  hasSession().then((sess) => {
    if (!sess.ok || !sess.isProvider) return;
    if (sess.homeLocality && !localStorage.getItem(LOCALITY_KEY)) {
      setLocality(sess.homeLocality);
    }
  }).catch(() => {});

  ensureLandingSections();

  // Auto-set locality for live boards currently in view / preferred
  const preferred = window.HubPrefs?.readPrefs?.().board || "labour";
  if (window.HubGeo?.autoPreferForLive) {
    window.HubGeo.autoPreferForLive(preferred).then((nearest) => {
      if (!nearest?.id) return;
      setLocality(nearest.id);
      Object.values(BOARDS).forEach((board) => {
        const select = document.getElementById(board.localitySelect);
        if (select) select.value = nearest.id;
      });
    }).catch(() => {});
  }

  Object.keys(BOARDS).forEach((id) => {
    refreshDesk(id).catch(() => {});
    loadProviders(id).catch(() => {});
  });

  window.HubBoards = {
    BOARDS,
    loadProviders,
    refreshDesk,
    currentLocality,
    setLocality,
    openBoardSection,
  };
})();
