(() => {
  const BOARD_HASHES = new Set([
    "landing-board",
    "landing-spotlight",
    "landing-news",
    "landing-places",
    "landing-scitech",
    "landing-culture",
    "landing-services",
    "landing-labour",
    "landing-taxi",
    "landing-experts",
    "landing-vehicle",
    "landing-doctor",
    "landing-tours",
    "landing-tutors",
    "landing-home",
    "landing-food",
    "landing-grocery",
    "landing-hardware",
    "landing-haulage",
    "landing-rentals",
    "landing-seri",
    "landing-channels",
    "landing-ads",
    "landing-businesses",
    "landing-neighbourhoods",
    "landing-about",
  ]);

  const el = (id) => document.getElementById(id);

  function isBoardHash(hash) {
    return BOARD_HASHES.has((hash || "").replace(/^#/, ""));
  }

  function openBoard({ scrollTo = "landing-news", updateHash = true } = {}) {
    const shell = el("landingView");
    const board = el("landing-board");
    const connect = el("landing-connect-band");
    if (!shell || !board) return;
    shell.classList.add("board-open");
    board.hidden = false;
    if (connect) connect.hidden = false;
    const targetId = scrollTo || "landing-news";
    if (updateHash) {
      const nextHash = `#${targetId}`;
      if (location.hash !== nextHash) {
        history.pushState(null, "", `${location.pathname}${location.search}${nextHash}`);
      }
    }
    requestAnimationFrame(() => {
      const node = document.getElementById(targetId);
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  function closeBoard({ scrollTop = true } = {}) {
    const shell = el("landingView");
    const board = el("landing-board");
    const connect = el("landing-connect-band");
    if (!shell) return;
    shell.classList.remove("board-open");
    if (board) board.hidden = true;
    if (connect) connect.hidden = true;
    if (scrollTop) window.scrollTo({ top: 0, behavior: "smooth" });
    const hash = (location.hash || "").replace(/^#/, "");
    if (isBoardHash(hash)) {
      history.replaceState(null, "", `${location.pathname}${location.search}`);
    }
  }

  function bindBoard() {
    const shell = el("landingView");
    if (!shell || shell.dataset.boardBound === "1") return;
    shell.dataset.boardBound = "1";

    shell.querySelectorAll('a[href^="#landing"]').forEach((link) => {
      link.addEventListener("click", (event) => {
        const target = (link.getAttribute("href") || "").replace(/^#/, "");
        if (!isBoardHash(target)) return;
        if (target === "landing-spotlight") {
          const spotlight = el("landingSpotlight");
          if (spotlight && !spotlight.hidden) {
            event.preventDefault();
            spotlight.scrollIntoView({ behavior: "smooth", block: "start" });
            return;
          }
        }
        if (!shell.classList.contains("board-open")) {
          event.preventDefault();
          openBoard({ scrollTo: target === "landing-spotlight" ? "landing-news" : target });
        }
      });
    });

    shell.querySelector(".landing-scroll-hint")?.addEventListener("click", (event) => {
      const spotlight = el("landingSpotlight");
      if (spotlight && !spotlight.hidden) {
        event.preventDefault();
        spotlight.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (!shell.classList.contains("board-open")) {
        event.preventDefault();
        openBoard({ scrollTo: "landing-news" });
      }
    });

    ["landingHeroExploreBtn"].forEach((id) => {
      el(id)?.addEventListener("click", () => {
        const spotlight = el("landingSpotlight");
        if (spotlight && !spotlight.hidden) {
          spotlight.scrollIntoView({ behavior: "smooth", block: "start" });
          return;
        }
        openBoard({ scrollTo: "landing-news" });
      });
    });

    el("landingTopBoardBtn")?.addEventListener("click", () => {
      if (shell.classList.contains("board-open")) {
        const news = document.getElementById("landing-news");
        news?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      openBoard({ scrollTo: "landing-news" });
    });

    shell.querySelector(".landing-top-brand")?.addEventListener("click", (event) => {
      if (shell.classList.contains("board-open")) {
        event.preventDefault();
        closeBoard();
      }
    });
  }

  function bindBoardsShortcut() {
    if (!window.HubPrefs?.mountBoardsNav) return;
    window.HubPrefs.mountBoardsNav({
      onNavigate(href, boardId) {
        if (boardId === "explore" || (href && href.startsWith("/#landing-"))) {
          const hash = (href || "").replace(/^\/?#?/, "") || "landing-news";
          if (boardId === "explore") {
            window.HubPrefs.setMyMandi(false);
            paintMyMandiPanel();
            openBoard({ scrollTo: "landing-news" });
            return true;
          }
          if (boardId && boardId !== "contact") {
            const known = window.HubPrefs.BOARDS.some((b) => b.id === boardId);
            if (known) {
              const prefs = window.HubPrefs.readPrefs();
              window.HubPrefs.rememberPrefs(boardId, prefs.loc, prefs.lang);
              paintMyMandiPanel();
            }
          }
          if (document.getElementById(hash)) {
            openBoard({ scrollTo: hash });
            return true;
          }
        }
        return false;
      },
    });
  }

  function applyHash() {
    const hash = (location.hash || "").replace(/^#/, "");
    if (isBoardHash(hash)) {
      openBoard({ scrollTo: hash, updateHash: false });
      return true;
    }
    return false;
  }

  function bindScrollChrome() {
    const shell = el("landingView");
    const onScroll = () => {
      if (!shell) return;
      shell.classList.toggle("is-scrolled", window.scrollY > 12);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function postCard(row) {
    const extra = [];
    if (row.location) extra.push(escapeHtml(row.location));
    if (row.publisherName) extra.push(escapeHtml(row.publisherName));
    const links = [];
    const professionKinds = new Set([
      "labour", "seri", "taxi", "experts", "vehicle", "doctor", "tours", "tutors", "home",
      "sme", "doc", "travel", "coaching", "mentor",
    ]);
    if (professionKinds.has(row.kind)) {
      const boardId = window.HubPrefs?.normalizeBoard(row.kind === "seri" ? "labour" : row.kind)
        || (row.kind === "taxi" ? "taxi" : "labour");
      const count = Number(row.interestCount || 0);
      const countLabel = count === 1
        ? "1 interested · 1 ने रुचि दिखाई"
        : count > 1
          ? `${count} interested · ${count} ने रुचि दिखाई`
          : "No interest yet · अभी कोई रुचि नहीं";
      const cta = boardId === "taxi"
        ? "I can take this · मैं ले सकता/सकती हूँ"
        : "I'm available · मैं उपलब्ध हूँ";
      links.push(`<p class="landing-meta seri-interest-count">${countLabel}</p>`);
      links.push(
        `<p class="landing-contact"><button type="button" class="btn primary compact seri-interest-btn" data-board-interest="${escapeHtml(row.id)}" data-board-id="${boardId}" data-board-title="${escapeHtml(row.title)}">${cta}</button></p>`
      );
    } else {
      if (row.phone) links.push(`<p class="landing-phone"><a href="tel:${escapeHtml(row.phone)}">${escapeHtml(row.phone)}</a></p>`);
      if (row.url) links.push(`<p class="landing-contact"><a href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">Link</a></p>`);
      if (row.kind === "business" && row.plan === "hosted" && row.slug) {
        links.push(`<p class="landing-contact"><a href="/b/${encodeURIComponent(row.slug)}">Open page</a></p>`);
      }
    }
    const boardClass = professionKinds.has(row.kind) ? " is-seri" : "";
    return `<article class="landing-card${row.plan === "featured" ? " is-featured" : ""}${boardClass}" data-hub-live="1">
      <p class="landing-meta">${escapeHtml(row.category || row.kind)}${extra.length ? " · " + extra.join(" · ") : ""}</p>
      <strong>${escapeHtml(row.title)}</strong>
      <p>${escapeHtml(row.summary || "")}</p>
      ${links.join("")}
    </article>`;
  }

  function injectPosts(listId, posts) {
    const list = el(listId);
    if (!list) return;
    list.querySelectorAll('[data-hub-live="1"]').forEach((node) => node.remove());
    if (!posts.length) return;
    list.insertAdjacentHTML("afterbegin", posts.map(postCard).join(""));
  }

  async function loadPublicBoard() {
    const [hub, biz, feed] = await Promise.all([
      fetch("hub.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({})),
      fetch("businesses.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ businesses: [] })),
      fetch("/api/hub/feed", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ byKind: {} })),
    ]);
    const features = hub.features || {};
    window.__hubFeatures = features;
    syncHeroBoardCards();
    const map = {
      news: "landing-news",
      places: "landing-places",
      scitech: "landing-scitech",
      culture: "landing-culture",
      services: "landing-services",
      seri: "landing-labour",
      labour: "landing-labour",
      taxi: "landing-taxi",
      experts: "landing-experts",
      vehicle: "landing-vehicle",
      doctor: "landing-doctor",
      tours: "landing-tours",
      tutors: "landing-tutors",
      home: "landing-home",
      food: "landing-food",
      grocery: "landing-grocery",
      hardware: "landing-hardware",
      haulage: "landing-haulage",
      rentals: "landing-rentals",
      commerce: "landing-food",
      channels: "landing-channels",
      ads: "landing-ads",
      neighbourhoods: "landing-neighbourhoods",
      businesses: "landing-businesses",
      boards: "landing-labour",
    };
    Object.entries(map).forEach(([key, id]) => {
      const node = el(id);
      if (!node) return;
      if (key === "boards") return;
      let hide = false;
      if (key === "seri" || key === "labour") {
        hide = features.labour === false && features.seri === false;
      } else if (key === "taxi") {
        hide = features.taxi === false;
      } else if (key === "food" || key === "commerce") {
        hide = features.food === false && features.commerce === false;
      } else if (key === "grocery") {
        hide = features.grocery === false && features.commerce === false;
      } else if (key === "hardware") {
        hide = features.hardware === false && features.commerce === false;
      } else if (key === "haulage") {
        hide = features.haulage === false && features.commerce === false;
      } else if (key === "rentals") {
        hide = features.rentals === false && features.commerce === false;
      } else {
        hide = features[key] === false;
      }
      node.dataset.featureHidden = hide ? "1" : "0";
      if (!window.HubPrefs?.isMyMandiOn()) node.hidden = hide;
      else if (hide) node.hidden = true;
    });
    const byKind = feed.byKind || {};
    injectPosts("landingNewsList", byKind.news || []);
    injectPosts("landingPlacesList", byKind.place || []);
    injectPosts("landingSciTechList", byKind.scitech || []);
    injectPosts("landingCultureList", byKind.culture || []);
    injectPosts("landingServicesList", byKind.service || []);
    const labourPosts = [...(byKind.labour || []), ...(byKind.seri || [])];
    injectPosts("landingLabourList", labourPosts);
    injectPosts("landingSeriList", labourPosts);
    injectPosts("landingTaxiList", byKind.taxi || []);
    injectPosts("landingExpertsList", byKind.experts || byKind.sme || []);
    injectPosts("landingVehicleList", byKind.vehicle || []);
    injectPosts("landingDoctorList", byKind.doctor || byKind.doc || []);
    injectPosts("landingToursList", byKind.tours || byKind.travel || []);
    injectPosts("landingTutorsList", byKind.tutors || byKind.coaching || []);
    injectPosts("landingHomeList", byKind.home || []);
    injectPosts("landingChannelsList", byKind.channel || []);
    const known = new Set([
      "news", "place", "scitech", "culture", "service", "seri", "labour", "taxi",
      "experts", "sme", "vehicle", "doctor", "doc", "tours", "travel", "tutors",
      "coaching", "mentor", "home", "channel", "ad", "event", "business",
    ]);
    const extras = Object.entries(byKind)
      .filter(([kind]) => !known.has(kind))
      .flatMap(([, rows]) => rows);
    const ads = [...(byKind.ad || []), ...(byKind.event || []), ...extras];
    const adsList = el("landingAdsList");
    if (adsList) {
      adsList.querySelectorAll('[data-hub-live="1"]').forEach((node) => node.remove());
      if (ads.length) {
        adsList.insertAdjacentHTML("afterbegin", ads.map(postCard).join(""));
      }
    }
    const list = el("landingBusinessList");
    if (!list) return;
    const hosted = (biz.businesses || []).filter((row) => row.status === "published");
    const community = (byKind.business || []).filter((row) => row.plan !== "hosted");
    const cards = [
      ...hosted.map((row) => {
        const href = row.plan === "hosted" ? `/b/${encodeURIComponent(row.slug)}` : (row.website || "#");
        const extra = row.plan === "hosted"
          ? `<p class="landing-contact"><a href="${href}">Open page</a> · ${escapeHtml(row.slug)}.cityofmandi.com</p>`
          : (row.website ? `<p class="landing-contact"><a href="${escapeHtml(row.website)}" target="_blank" rel="noopener noreferrer">Website</a></p>` : "");
        return `<article class="landing-card${row.plan === "featured" ? " is-featured" : ""}" data-hub-live="1">
          <p class="landing-meta">${escapeHtml(row.category || row.plan)}</p>
          <strong>${escapeHtml(row.name)}</strong>
          <p>${escapeHtml(row.tagline || row.summary || "")}</p>
          ${extra}
        </article>`;
      }),
      ...community.map(postCard),
    ];
    const staticBiz = [...list.querySelectorAll(".landing-card:not([data-hub-live='1'])")];
    list.querySelectorAll('[data-hub-live="1"]').forEach((node) => node.remove());
    if (cards.length) {
      list.insertAdjacentHTML("afterbegin", cards.join(""));
    } else if (!staticBiz.length) {
      list.innerHTML = `<article class="landing-card" data-hub-live="1"><p class="landing-meta">Open</p><strong>List your Mandi business</strong><p>Register to publish a directory card or hosted page.</p><p class="landing-contact"><a href="/join">Publish</a></p></article>`;
    }
  }

  document.addEventListener("city:live", (event) => {
    const changed = event.detail?.changed || [];
    if (changed.some((key) => key === "hub" || key === "businesses" || key === "feed" || key === "seri" || key === "boards")) {
      loadPublicBoard().catch(() => {});
    }
  });

  function bindAccountHeader() {
    const guest = el("landingAccountGuest");
    const userBox = el("landingAccountUser");
    const chip = el("landingAccountChip");
    const menu = el("landingAccountMenu");
    const avatar = el("landingAccountAvatar");
    const nameEl = el("landingAccountName");
    const signOut = el("landingSignOutBtn");
    if (!guest || !userBox || !chip || !menu) return;

    const closeMenu = () => {
      menu.hidden = true;
      chip.setAttribute("aria-expanded", "false");
    };
    const openMenu = () => {
      menu.hidden = false;
      chip.setAttribute("aria-expanded", "true");
    };

    chip.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.hidden) openMenu();
      else closeMenu();
    });
    document.addEventListener("click", (event) => {
      if (!userBox.contains(event.target)) closeMenu();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });

    signOut?.addEventListener("click", async () => {
      closeMenu();
      await Promise.allSettled([
        fetch("/api/hub/publisher/logout", { method: "POST", credentials: "same-origin" }),
        fetch("/api/adda/logout", { method: "POST", credentials: "same-origin" }),
        fetch("/api/hub/providers/logout", { method: "POST", credentials: "same-origin" }),
      ]);
      guest.hidden = false;
      userBox.hidden = true;
    });

    Promise.all([
      fetch("/api/hub/publisher/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
      fetch("/api/adda/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
      fetch("/api/hub/providers/session", { credentials: "same-origin", cache: "no-store" })
        .then((r) => r.json()).catch(() => ({})),
    ]).then(([pub, adda, provider]) => {
      const name = pub.publisher?.name
        || adda.user?.displayName
        || adda.user?.display_name
        || provider.provider?.name
        || provider.worker?.name
        || "";
      const signedIn = !!(pub.authenticated || adda.authenticated || adda.user || provider.authenticated);
      if (!signedIn || !name) {
        guest.hidden = false;
        userBox.hidden = true;
        return;
      }
      guest.hidden = true;
      userBox.hidden = false;
      nameEl.textContent = name;
      avatar.textContent = (name.trim()[0] || "?").toUpperCase();
      chip.setAttribute("aria-label", `Account menu for ${name}`);
    }).catch(() => {});
  }

  function bindContextualSignIn() {
    const btn = el("landingSignInBtn");
    if (!btn || !window.HubPrefs) return;
    const { board } = window.HubPrefs.readPrefs();
    const next = encodeURIComponent(window.HubPrefs.boardHome(board));
    btn.href = `/join?mode=login&next=${next}`;
    const heroSignIn = el("landingHeroSignIn");
    if (heroSignIn) heroSignIn.href = `/join?mode=login&next=${encodeURIComponent("/")}`;
  }

  const KEEP_SECTIONS = new Set([
    "landing-about",
    "landing-neighbourhoods",
  ]);

  function preferredSectionId() {
    const HP = window.HubPrefs;
    if (!HP) return "landing-news";
    const { board } = HP.readPrefs();
    if (board === "adda") return "landing-news";
    return HP.boardSectionId(board) || `landing-${board}`;
  }

  function applyMyMandiCollapse(on) {
    const shell = el("landingView");
    const main = shell?.querySelector(".landing-main");
    if (!shell || !main) return;
    shell.classList.toggle("is-my-mandi", !!on);
    const keep = preferredSectionId();
    main.querySelectorAll(".landing-section").forEach((section) => {
      const id = section.id || "";
      if (!on) {
        section.classList.remove("is-my-mandi-focus", "is-my-mandi-dim");
        section.hidden = section.dataset.featureHidden === "1";
        return;
      }
      if (id === keep) {
        section.classList.add("is-my-mandi-focus");
        section.classList.remove("is-my-mandi-dim");
        section.hidden = false;
      } else if (KEEP_SECTIONS.has(id)) {
        section.classList.remove("is-my-mandi-focus");
        section.classList.add("is-my-mandi-dim");
      } else {
        section.classList.remove("is-my-mandi-focus");
        section.classList.add("is-my-mandi-dim");
        // Keep in DOM for Boards menu navigation, but visually collapse
      }
    });
    // Side nav: mark preferred
    shell.querySelectorAll(".landing-side-nav a[href^='#']").forEach((link) => {
      const href = (link.getAttribute("href") || "").replace(/^#/, "");
      link.classList.toggle("is-my-mandi-current", on && href === keep);
    });
  }

  function paintMyMandiPanel() {
    const HP = window.HubPrefs;
    const panel = el("myMandiHome");
    const guestCta = el("landingHeroGuestCta");
    const greeting = document.querySelector(".landing-greeting");
    if (!HP || !panel) return false;
    const on = HP.isMyMandiOn();
    if (!on) {
      panel.hidden = true;
      if (guestCta) guestCta.hidden = false;
      if (greeting) greeting.hidden = false;
      applyMyMandiCollapse(false);
      syncHeroBoardCards();
      return false;
    }
    const prefs = HP.readPrefs();
    const meta = HP.boardMeta(prefs.board);
    const locLabel = HP.localityLabel(prefs.loc);
    const lang = window.HubI18n?.readLang?.() || "en";
    const boardLabel = lang === "hi"
      ? `${meta.labelHi || meta.label} · ${meta.label}`
      : `${meta.label} · ${meta.labelHi || ""}`.replace(/\s·\s$/, "");
    el("myMandiBoardLabel").textContent = boardLabel;
    el("myMandiMeta").textContent = lang === "hi"
      ? `${locLabel} · आज का बोर्ड`
      : `${locLabel} · your board today`;
    panel.hidden = false;
    if (guestCta) guestCta.hidden = true;
    if (greeting) greeting.hidden = true;
    applyMyMandiCollapse(true);
    syncHeroBoardCards();
    return true;
  }

  function openPreferredBoard() {
    const HP = window.HubPrefs;
    if (!HP) return;
    const { board } = HP.readPrefs();
    if (board === "adda") {
      location.href = "/adda";
      return;
    }
    const sectionId = preferredSectionId();
    openBoard({ scrollTo: sectionId });
  }

  const HERO_BOARD_ORDER = [
    "city", "food", "grocery", "taxi", "rentals", "home", "vehicle",
    "doctor", "tours", "labour", "haulage", "hardware", "experts", "tutors", "adda",
  ];
  const HERO_BOARD_LEDE = {
    city: { en: "News, places, and everyday Mandi.", hi: "खबर, जगहें, और रोज़ की मंडी।" },
    food: { en: "Kitchens and delivery near you.", hi: "आस-पास रसोई और डिलीवरी।" },
    grocery: { en: "Kirana and daily needs.", hi: "किराना और रोज़मर्रा।" },
    taxi: { en: "Cabs and local rides.", hi: "कैब और स्थानीय सवारी।" },
    rentals: { en: "To rent or sell nearby.", hi: "किराये या बिक्री आस-पास।" },
    home: { en: "Home help on the board.", hi: "घर की मदद बोर्ड पर।" },
    vehicle: { en: "Service desks for your vehicle.", hi: "वाहन की सर्विस।" },
    doctor: { en: "Doc on call in your area.", hi: "आपके इलाके में डॉक्टर।" },
    tours: { en: "Day trips and travel desks.", hi: "घूमना और यात्रा।" },
    labour: { en: "Morning work at Seri and around.", hi: "सेरी और आस-पास सुबह का काम।" },
    haulage: { en: "Tempo and load moving.", hi: "टेम्पो और ढुलाई।" },
    hardware: { en: "Supplies and hardware.", hi: "सामग्री और हार्डवेयर।" },
    experts: { en: "Local experts and SMEs.", hi: "स्थानीय विशेषज्ञ।" },
    tutors: { en: "Tutors near home.", hi: "घर के पास ट्यूटर।" },
    adda: { en: "City chat on Mandi Adda.", hi: "मंडी अड्डा पर बात।" },
  };
  const HERO_ROTATE_MS = 10000;
  let heroBoardTimer = 0;
  let heroBoardIndex = 0;

  function heroCardsWanted() {
    const features = window.__hubFeatures || {};
    return features.heroBoardCards !== false;
  }

  function hasBoardPreference() {
    return !!window.HubPrefs?.isMyMandiOn();
  }

  function localityDisplay(loc) {
    const HP = window.HubPrefs;
    if (!HP) return "Mandi";
    const lang = window.HubI18n?.readLang?.() || "en";
    const row = HP.LOCALITIES.find((l) => l.id === loc);
    const en = row?.label || HP.localityLabel(loc);
    const hi = row?.labelHi || "";
    if (lang === "hi" && hi) return hi;
    return en;
  }

  function paintHeroBrand() {
    const brand = el("heroBoardBrand");
    if (!brand) return;
    const lang = window.HubI18n?.readLang?.() || "en";
    if (lang === "hi") {
      brand.innerHTML = `मेरा <span class="hero-board-heart" aria-hidden="true">❤</span> मंडी`;
    } else {
      brand.innerHTML = `I <span class="hero-board-heart" aria-hidden="true">❤</span> My Mandi`;
    }
  }

  function paintHeroLocality() {
    const HP = window.HubPrefs;
    const locEl = el("heroBoardLoc");
    const loc = HP?.readPrefs().loc || "mandi";
    if (locEl) locEl.textContent = localityDisplay(loc);
    return loc;
  }

  function hasChosenLocality() {
    try {
      if (window.HubPrefs?.isMyMandiOn()) return true;
      return Number(localStorage.getItem("hub_geo_manual_ts") || 0) > 0;
    } catch {
      return false;
    }
  }

  async function detectHeroLocality() {
    const HP = window.HubPrefs;
    const Geo = window.HubGeo;
    paintHeroLocality();
    if (!HP || !Geo?.detectNearest) return;
    if (hasChosenLocality() || Geo.recentlyManual?.()) return;
    if (Geo.recentlyAuto?.()) return;
    try {
      const hit = await Geo.detectNearest();
      const next = hit?.nearest?.id;
      if (!next) return;
      const loc = HP.normalizeLocality(next);
      try {
        localStorage.setItem(HP.LOCALITY_KEY, loc);
        localStorage.setItem("hub_geo_auto_ts", String(Date.now()));
      } catch { /* ignore */ }
      document.dispatchEvent(new CustomEvent("hub:locality", {
        detail: { locality: loc, manual: false, source: "hero" },
      }));
      paintHeroLocality();
    } catch {
      paintHeroLocality();
    }
  }

  function heroBoardList() {
    const HP = window.HubPrefs;
    if (!HP) return [];
    if (hasBoardPreference()) {
      const preferred = HP.boardMeta(HP.readPrefs().board);
      return preferred ? [preferred] : [];
    }
    const byId = Object.fromEntries(HP.BOARDS.map((b) => [b.id, b]));
    const ordered = HERO_BOARD_ORDER.map((id) => byId[id]).filter(Boolean);
    HP.BOARDS.forEach((b) => {
      if (!ordered.some((x) => x.id === b.id)) ordered.push(b);
    });
    return ordered;
  }

  function openHeroBoard(id) {
    const HP = window.HubPrefs;
    const home = HP?.boardHome(id) || `/#landing-${id}`;
    if (id === "adda" || home.startsWith("/adda")) {
      location.href = "/adda";
      return;
    }
    const hash = home.includes("#") ? home.split("#")[1] : `landing-${id}`;
    openBoard({ scrollTo: hash || "landing-news" });
  }

  function paintHeroBoard(index) {
    const HP = window.HubPrefs;
    const card = el("heroBoardCard");
    const titleEl = el("heroBoardTitle");
    const boards = heroBoardList();
    if (!HP || !card || !boards.length) return;
    heroBoardIndex = ((index % boards.length) + boards.length) % boards.length;
    const board = boards[heroBoardIndex];
    const lang = window.HubI18n?.readLang?.() || "en";
    const title = lang === "hi"
      ? `${board.labelHi || board.label} · ${board.label}`
      : `${board.label}${board.labelHi ? " · " + board.labelHi : ""}`;
    card.href = board.home;
    card.setAttribute("data-hero-board", board.id);
    card.setAttribute("aria-label", `${title} — ${localityDisplay(HP.readPrefs().loc)}`);
    if (titleEl) titleEl.textContent = title;
    paintHeroBrand();
    paintHeroLocality();
  }

  function stopHeroBoardRotate() {
    if (heroBoardTimer) {
      window.clearInterval(heroBoardTimer);
      heroBoardTimer = 0;
    }
  }

  function startHeroBoardRotate() {
    stopHeroBoardRotate();
    if (hasBoardPreference()) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reduce) return;
    if (heroBoardList().length < 2) return;
    heroBoardTimer = window.setInterval(() => {
      paintHeroBoard(heroBoardIndex + 1);
    }, HERO_ROTATE_MS);
  }

  function renderHeroBoardCards() {
    const wrap = el("heroBoardCards");
    const hero = el("landingHero");
    const shell = el("landingView");
    const nextBtn = el("heroBoardNext");
    if (!wrap) return;
    const show = heroCardsWanted();
    const preferred = hasBoardPreference();
    wrap.hidden = !show;
    wrap.classList.toggle("is-preferred", preferred);
    hero?.classList.toggle("has-board-cards", show);
    shell?.classList.toggle("has-hero-pref-card", show && preferred);
    if (nextBtn) {
      nextBtn.hidden = preferred;
      nextBtn.setAttribute("aria-hidden", preferred ? "true" : "false");
    }
    if (!show) {
      stopHeroBoardRotate();
      return;
    }
    if (preferred) heroBoardIndex = 0;
    paintHeroBoard(heroBoardIndex);
    startHeroBoardRotate();
  }

  function syncHeroBoardCards() {
    renderHeroBoardCards();
  }

  function mountHeroBoardCards() {
    const wrap = el("heroBoardCards");
    const card = el("heroBoardCard");
    const nextBtn = el("heroBoardNext");
    if (!wrap || wrap.dataset.bound === "1") {
      renderHeroBoardCards();
      detectHeroLocality();
      return;
    }
    wrap.dataset.bound = "1";
    nextBtn?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      paintHeroBoard(heroBoardIndex + 1);
      startHeroBoardRotate();
    });
    card?.addEventListener("click", (event) => {
      const id = card.getAttribute("data-hero-board");
      const href = card.getAttribute("href") || "";
      if (!id) return;
      if (id === "adda" || href.startsWith("/adda")) return;
      event.preventDefault();
      openHeroBoard(id);
    });
    document.addEventListener("hub:locality", () => paintHeroLocality());
    document.addEventListener("hub:lang", () => renderHeroBoardCards());
    document.addEventListener("hub:mymandi", () => renderHeroBoardCards());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopHeroBoardRotate();
      else startHeroBoardRotate();
    });
    renderHeroBoardCards();
    detectHeroLocality();
  }

  function mountMyMandi() {
    const HP = window.HubPrefs;
    if (!HP) return;
    paintMyMandiPanel();

    el("myMandiOpenBtn")?.addEventListener("click", () => {
      HP.setMyMandi(true);
      paintMyMandiPanel();
      openPreferredBoard();
    });
    el("myMandiExploreAll")?.addEventListener("click", () => {
      HP.setMyMandi(false);
      paintMyMandiPanel();
      openBoard({ scrollTo: "landing-news" });
    });

    document.addEventListener("hub:mymandi", () => paintMyMandiPanel());
    document.addEventListener("hub:locality", () => {
      if (HP.isMyMandiOn()) paintMyMandiPanel();
    });
    document.addEventListener("hub:lang", () => {
      if (HP.isMyMandiOn()) paintMyMandiPanel();
    });
  }

  function bootHub() {
    bindContextualSignIn();
    bindBoardsShortcut();
    bindAccountHeader();
    bindBoard();
    bindScrollChrome();
    mountMyMandi();
    mountHeroBoardCards();
    loadPublicBoard().then(() => {
      if (window.HubPrefs?.isMyMandiOn()) paintMyMandiPanel();
    }).catch(() => {});

    const hadHash = applyHash();
    if (!hadHash) {
      if (window.HubPrefs?.isMyMandiOn()) {
        openBoard({ scrollTo: preferredSectionId(), updateHash: true });
      } else {
        closeBoard({ scrollTop: false });
      }
    }
    window.addEventListener("hashchange", () => {
      if (!applyHash()) closeBoard({ scrollTop: false });
    });
  }

  if (window.HubPrefs) bootHub();
  else {
    let n = 0;
    const wait = () => {
      if (window.HubPrefs || n > 40) bootHub();
      else {
        n += 1;
        setTimeout(wait, 25);
      }
    };
    wait();
  }
})();
