(() => {
  const ROTATE_MS = 9000;
  let bootSeq = 0;
  let booting = false;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function pickWeighted(ads) {
    const total = ads.reduce((n, row) => n + Math.max(1, Number(row.weight) || 1), 0);
    let r = Math.random() * total;
    for (const ad of ads) {
      r -= Math.max(1, Number(ad.weight) || 1);
      if (r <= 0) return ad;
    }
    return ads[0];
  }

  function renderAd(ad) {
    const anim = ad.animation || "marquee";
    const img = ad.imageUrl
      ? `<img class="sp-ad-img" src="${esc(ad.imageUrl)}" alt="" decoding="async">`
      : "";
    const sub = ad.subtitle
      ? `<span class="sp-ad-sub">${esc(ad.subtitle)}</span>`
      : "";
    const sponsor = ad.sponsor
      ? `<span class="sp-ad-sponsor">${esc(ad.sponsor)}</span>`
      : "";
    const inner = `
      <span class="sp-ad-inner anim-${esc(anim)}">
        ${anim === "independence" ? `
          <span class="sp-tricolor" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="sp-burst" aria-hidden="true"></span>
        ` : ""}
        ${anim === "confetti" ? `<span class="sp-confetti" aria-hidden="true"></span>` : ""}
        ${img}
        <span class="sp-ad-copy">
          <span class="sp-ad-title">${esc(ad.title)}</span>
          ${sub}
        </span>
        ${sponsor}
      </span>
    `;
    if (ad.linkUrl) {
      return `<a class="sp-ad" href="${esc(ad.linkUrl)}" target="_blank" rel="noopener noreferrer">${inner}</a>`;
    }
    return `<div class="sp-ad">${inner}</div>`;
  }

  function applyRunningText(slot) {
    const copy = slot.querySelector(".sp-ad-copy");
    const title = slot.querySelector(".sp-ad-title");
    if (!copy || !title) return;

    copy.classList.remove("is-running");
    title.style.removeProperty("--sp-overflow");
    title.style.removeProperty("--sp-run-duration");
    if (title.dataset.baseTitle) {
      title.textContent = title.dataset.baseTitle;
    }

    const prevOverflow = title.style.overflow;
    const prevAnim = title.style.animation;
    title.style.overflow = "visible";
    title.style.animation = "none";
    const overflowPx = Math.ceil(title.scrollWidth - copy.clientWidth);
    title.style.overflow = prevOverflow;
    title.style.animation = prevAnim;

    if (overflowPx <= 2) return;

    const base = title.dataset.baseTitle || title.textContent || "";
    title.dataset.baseTitle = base;
    copy.classList.add("is-running");
    title.innerHTML = `<span class="sp-run-track"><span class="sp-run-chunk">${esc(base)}</span><span class="sp-run-chunk" aria-hidden="true">${esc(base)}</span></span>`;
    const duration = Math.max(9, Math.min(32, (title.scrollWidth || overflowPx * 2) / 32));
    title.style.setProperty("--sp-run-duration", `${duration}s`);
  }

  function mount(el, ads) {
    if (!el) return;
    if (!ads.length) {
      // Keep any already-rendered ad rather than blanking the header on a race.
      if (el.querySelector(".sp-ad-title")) return;
      el.innerHTML = "";
      el.hidden = true;
      el.setAttribute("aria-hidden", "true");
      return;
    }
    el.hidden = false;
    el.removeAttribute("aria-hidden");
    let current = pickWeighted(ads);
    const paint = (ad) => {
      el.innerHTML = renderAd(ad);
      requestAnimationFrame(() => {
        applyRunningText(el);
        window.setTimeout(() => applyRunningText(el), 120);
      });
    };
    paint(current);

    if (el._spResize) window.removeEventListener("resize", el._spResize);
    el._spResize = () => applyRunningText(el);
    window.addEventListener("resize", el._spResize, { passive: true });

    if (el._spTimer) window.clearInterval(el._spTimer);
    if (ads.length < 2) return;
    el._spTimer = window.setInterval(() => {
      let next = pickWeighted(ads);
      if (ads.length > 1) {
        let guard = 0;
        while (next.id === current.id && guard++ < 6) next = pickWeighted(ads);
      }
      current = next;
      el.classList.add("is-swapping");
      window.setTimeout(() => {
        paint(current);
        el.classList.remove("is-swapping");
      }, 220);
    }, ROTATE_MS);
  }

  async function fetchAds() {
    const res = await fetch("/api/hub/sponsored-ads", {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`sponsored ${res.status}`);
    const data = await res.json().catch(() => ({}));
    return Array.isArray(data.ads) ? data.ads : [];
  }

  async function boot() {
    if (booting) return;
    booting = true;
    const seq = ++bootSeq;
    try {
      const slots = [...document.querySelectorAll("[data-sponsored-slot]")];
      if (!slots.length) return;
      let ads = [];
      try {
        ads = await fetchAds();
      } catch {
        try {
          ads = await fetchAds();
        } catch {
          ads = [];
        }
      }
      if (seq !== bootSeq) return;
      slots.forEach((slot) => {
        try {
          mount(slot, ads);
        } catch {
          /* keep header usable if one slot fails */
        }
      });
    } finally {
      booting = false;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.addEventListener("city:live", (event) => {
    if ((event.detail?.changed || []).includes("sponsored")) boot();
  });
})();
