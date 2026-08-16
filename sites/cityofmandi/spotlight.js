(() => {
  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function el(id) {
    return document.getElementById(id);
  }

  function windowLabel(slot) {
    const end = (slot.endsAt || "").trim();
    if (!end) return "Now on the street";
    try {
      const endDate = new Date(end);
      if (Number.isNaN(endDate.getTime())) return "Now on the street";
      const days = Math.ceil((endDate.getTime() - Date.now()) / 86400000);
      if (days <= 0) return "Ending soon";
      if (days === 1) return "Through tomorrow";
      if (days <= 7) return `${days} days on the lane`;
      return "This fortnight";
    } catch {
      return "Now on the street";
    }
  }

  function openSpotlightTarget() {
    const strip = el("landingSpotlight");
    if (!strip || strip.hidden) return;
    requestAnimationFrame(() => {
      strip.scrollIntoView({ behavior: "smooth", block: "start" });
      strip.classList.add("is-focus");
      window.setTimeout(() => strip.classList.remove("is-focus"), 1400);
    });
  }

  function renderOrbit(slot) {
    const orbit = el("landingSpotlightOrbit");
    if (!orbit) return;
    const show = Boolean(slot && slot.showInHeroCircle);
    const imgUrl = slot && (slot.portraitUrl || slot.coverUrl);
    if (!show || !imgUrl) {
      orbit.hidden = true;
      orbit.innerHTML = "";
      return;
    }
    orbit.hidden = false;
    orbit.setAttribute("aria-label", `Open Spotlight: ${slot.title}`);
    orbit.innerHTML = `
      <span class="landing-spotlight-orbit-ring" aria-hidden="true"></span>
      <img class="landing-spotlight-orbit-img" src="${esc(imgUrl)}" alt="" width="72" height="72" decoding="async">
      <span class="landing-spotlight-orbit-chip">Spotlight</span>
    `;
  }

  function renderStrip(slot) {
    const section = el("landingSpotlight");
    if (!section) return;
    if (!slot) {
      section.hidden = true;
      section.innerHTML = "";
      section.classList.remove("is-ready", "is-person", "is-post");
      return;
    }
    const cover = slot.coverUrl || "";
    const portrait = slot.portraitUrl || slot.coverUrl || "";
    const kindLabel = slot.kind === "post" ? "Story" : "Common man";
    const ctaLabel = (slot.ctaLabel || (slot.kind === "post" ? "Read story" : "Meet them")).trim();
    const ctaHref = (slot.ctaHref || "").trim();
    const body = (slot.body || slot.subtitle || "").trim();
    const paras = body
      .split(/\n+/)
      .map((p) => p.trim())
      .filter(Boolean)
      .slice(0, 3);

    const cta = ctaHref
      ? `<a class="btn primary landing-spotlight-cta" href="${esc(ctaHref)}">${esc(ctaLabel)}</a>`
      : "";

    section.hidden = false;
    section.classList.toggle("is-person", slot.kind !== "post");
    section.classList.toggle("is-post", slot.kind === "post");
    const lead = paras[0] || "";
    const rest = paras.slice(1);
    section.innerHTML = `
      <div class="landing-spotlight-frame" aria-hidden="true"></div>
      <div class="landing-spotlight-stage">
        <div class="landing-spotlight-visual">
          <div class="landing-spotlight-cover-wrap">
            ${cover
              ? `<img class="landing-spotlight-cover" src="${esc(cover)}" alt="" decoding="async">`
              : `<div class="landing-spotlight-cover is-fallback" aria-hidden="true"></div>`}
          </div>
          <div class="landing-spotlight-visual-shade" aria-hidden="true"></div>
          <div class="landing-spotlight-beam" aria-hidden="true"></div>
          ${portrait
            ? `<img class="landing-spotlight-portrait" src="${esc(portrait)}" alt="" width="160" height="160" decoding="async">`
            : ""}
          <p class="landing-spotlight-streetmark" aria-hidden="true">Mandi streets</p>
        </div>
        <div class="landing-spotlight-copy">
          <p class="landing-spotlight-kicker">
            <span class="landing-spotlight-mark">Spotlight</span>
            <span class="landing-spotlight-kind">${esc(kindLabel)}</span>
            <span class="landing-spotlight-window">${esc(windowLabel(slot))}</span>
          </p>
          <h2 id="landingSpotlightTitle">${esc(slot.title)}</h2>
          ${slot.subtitle ? `<p class="landing-spotlight-sub">${esc(slot.subtitle)}</p>` : ""}
          <div class="landing-spotlight-rule" aria-hidden="true"></div>
          ${lead ? `<blockquote class="landing-spotlight-lead">${esc(lead)}</blockquote>` : ""}
          ${rest.length
            ? `<div class="landing-spotlight-body">${rest.map((p) => `<p>${esc(p)}</p>`).join("")}</div>`
            : ""}
          <div class="landing-spotlight-actions">
            ${cta}
            <button type="button" class="btn ghost landing-spotlight-cta-secondary" data-spotlight-scroll>Stay with this story</button>
          </div>
        </div>
      </div>
    `;

    section.querySelector("[data-spotlight-scroll]")?.addEventListener("click", openSpotlightTarget);
    requestAnimationFrame(() => {
      section.classList.add("is-ready");
      observeSpotlight(section);
    });
  }

  function observeSpotlight(section) {
    if (!("IntersectionObserver" in window) || section._spotObserved) return;
    section._spotObserved = true;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          section.classList.toggle("is-inview", entry.isIntersecting);
        });
      },
      { threshold: 0.28 }
    );
    io.observe(section);
  }

  async function loadSpotlight() {
    try {
      const res = await fetch("/api/hub/spotlight", { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      const slot = data.ok ? data.spotlight : null;
      renderStrip(slot);
      renderOrbit(slot);
    } catch {
      renderStrip(null);
      renderOrbit(null);
    }
  }

  el("landingSpotlightOrbit")?.addEventListener("click", (event) => {
    event.preventDefault();
    openSpotlightTarget();
  });

  document.addEventListener("city:live", (event) => {
    if ((event.detail?.changed || []).includes("spotlight")) {
      loadSpotlight();
    }
  });

  loadSpotlight();
})();
