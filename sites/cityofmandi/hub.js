(() => {
  const BOARD_HASHES = new Set([
    "landing-board",
    "landing-news",
    "landing-places",
    "landing-scitech",
    "landing-culture",
    "landing-services",
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
        if (!shell.classList.contains("board-open")) {
          event.preventDefault();
          openBoard({ scrollTo: target });
        }
      });
    });

    shell.querySelector(".landing-scroll-hint")?.addEventListener("click", (event) => {
      if (!shell.classList.contains("board-open")) {
        event.preventDefault();
        openBoard({ scrollTo: "landing-news" });
      }
    });

    ["landingHeroExploreBtn"].forEach((id) => {
      el(id)?.addEventListener("click", () => openBoard({ scrollTo: "landing-news" }));
    });

    shell.querySelector(".landing-top-brand")?.addEventListener("click", (event) => {
      if (shell.classList.contains("board-open")) {
        event.preventDefault();
        closeBoard();
      }
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
    if (row.phone) links.push(`<p class="landing-phone"><a href="tel:${escapeHtml(row.phone)}">${escapeHtml(row.phone)}</a></p>`);
    if (row.url) links.push(`<p class="landing-contact"><a href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">Link</a></p>`);
    if (row.kind === "business" && row.plan === "hosted" && row.slug) {
      links.push(`<p class="landing-contact"><a href="/b/${encodeURIComponent(row.slug)}">Open page</a></p>`);
    }
    return `<article class="landing-card${row.plan === "featured" ? " is-featured" : ""}">
      <p class="landing-meta">${escapeHtml(row.category || row.kind)}${extra.length ? " · " + extra.join(" · ") : ""}</p>
      <strong>${escapeHtml(row.title)}</strong>
      <p>${escapeHtml(row.summary || "")}</p>
      ${links.join("")}
    </article>`;
  }

  function prependPosts(listId, posts) {
    const list = el(listId);
    if (!list || !posts.length) return;
    list.insertAdjacentHTML("afterbegin", posts.map(postCard).join(""));
  }

  async function loadPublicBoard() {
    const [hub, biz, feed] = await Promise.all([
      fetch("hub.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({})),
      fetch("businesses.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ businesses: [] })),
      fetch("/api/hub/feed", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ byKind: {} })),
    ]);
    const features = hub.features || {};
    const map = {
      news: "landing-news",
      places: "landing-places",
      scitech: "landing-scitech",
      culture: "landing-culture",
      services: "landing-services",
      channels: "landing-channels",
      ads: "landing-ads",
      neighbourhoods: "landing-neighbourhoods",
      businesses: "landing-businesses",
    };
    Object.entries(map).forEach(([key, id]) => {
      const node = el(id);
      if (node && features[key] === false) node.hidden = true;
    });
    const byKind = feed.byKind || {};
    prependPosts("landingNewsList", byKind.news || []);
    prependPosts("landingPlacesList", byKind.place || []);
    prependPosts("landingSciTechList", byKind.scitech || []);
    prependPosts("landingCultureList", byKind.culture || []);
    prependPosts("landingServicesList", byKind.service || []);
    prependPosts("landingChannelsList", byKind.channel || []);
    const known = new Set(["news", "place", "scitech", "culture", "service", "channel", "ad", "event", "business"]);
    const extras = Object.entries(byKind)
      .filter(([kind]) => !known.has(kind))
      .flatMap(([, rows]) => rows);
    const ads = [...(byKind.ad || []), ...(byKind.event || []), ...extras];
    if (ads.length) {
      const adsList = el("landingAdsList");
      if (adsList) adsList.innerHTML = ads.map(postCard).join("");
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
        return `<article class="landing-card${row.plan === "featured" ? " is-featured" : ""}">
          <p class="landing-meta">${escapeHtml(row.category || row.plan)}</p>
          <strong>${escapeHtml(row.name)}</strong>
          <p>${escapeHtml(row.tagline || row.summary || "")}</p>
          ${extra}
        </article>`;
      }),
      ...community.map(postCard),
    ];
    list.innerHTML = cards.length
      ? cards.join("")
      : `<article class="landing-card"><p class="landing-meta">Open</p><strong>List your Mandi business</strong><p>Register to publish a directory card or hosted page.</p><p class="landing-contact"><a href="/join">Publish</a></p></article>`;
  }

  fetch("/api/hub/publisher/session", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((sess) => {
      const btn = el("landingPublishBtn");
      if (sess.authenticated && btn) {
        btn.setAttribute("href", "/publish");
        btn.querySelector("span").textContent = "Your desk";
      }
    })
    .catch(() => {});

  bindBoard();
  bindScrollChrome();
  loadPublicBoard();
  if (!applyHash()) closeBoard({ scrollTop: false });
  window.addEventListener("hashchange", () => {
    if (!applyHash()) closeBoard({ scrollTop: false });
  });
})();
