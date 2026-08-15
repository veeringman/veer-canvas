(() => {
  const ROTATE_MS = 9000;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function pickWeighted(ads) {
    const total = ads.reduce((n, a) => n + Math.max(1, Number(a.weight) || 1), 0);
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

  function mount(el, ads) {
    if (!el || !ads.length) {
      if (el) {
        el.innerHTML = `<div class="sp-ad sp-ad-empty" aria-hidden="true"></div>`;
        el.hidden = true;
      }
      return;
    }
    el.hidden = false;
    let current = pickWeighted(ads);
    el.innerHTML = renderAd(current);
    if (ads.length < 2) return;
    window.setInterval(() => {
      let next = pickWeighted(ads);
      if (ads.length > 1) {
        let guard = 0;
        while (next.id === current.id && guard++ < 6) next = pickWeighted(ads);
      }
      current = next;
      el.classList.add("is-swapping");
      window.setTimeout(() => {
        el.innerHTML = renderAd(current);
        el.classList.remove("is-swapping");
      }, 220);
    }, ROTATE_MS);
  }

  async function boot() {
    const slots = [...document.querySelectorAll("[data-sponsored-slot]")];
    if (!slots.length) return;
    try {
      const res = await fetch("/api/hub/sponsored-ads", { credentials: "same-origin" });
      const data = await res.json().catch(() => ({}));
      const ads = Array.isArray(data.ads) ? data.ads : [];
      slots.forEach((slot) => mount(slot, ads));
    } catch {
      slots.forEach((slot) => { slot.hidden = true; });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
