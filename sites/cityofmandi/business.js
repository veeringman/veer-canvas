(() => {
  function slugFromLocation() {
    const host = (location.hostname || "").toLowerCase();
    const sub = host.match(/^([a-z0-9-]+)\.cityofmandi\.com$/);
    if (sub && sub[1] !== "www") return sub[1];
    const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
    if (parts[0] === "b" && parts[1]) return parts[1].toLowerCase();
    return "";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function boot() {
    const slug = slugFromLocation();
    const hostEl = document.getElementById("bizHost");
    const section = document.getElementById("bizSection");
    if (hostEl) {
      hostEl.textContent = slug ? `${slug}.cityofmandi.com` : "Business page";
    }
    if (!slug) {
      section.innerHTML = `<p class="landing-section-kicker">Hub</p><h1>Missing business</h1><p class="muted">Use /b/{slug} or {slug}.cityofmandi.com</p>`;
      return;
    }
    const data = await fetch("/businesses.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ businesses: [] }));
    const biz = (data.businesses || []).find((row) => row.slug === slug && row.status === "published");
    if (!biz) {
      document.title = "Not found — City of Mandi";
      section.innerHTML = `<p class="landing-section-kicker">Hub</p><h1>This page is not live</h1><p class="muted">No published hosted page for <strong>${escapeHtml(slug)}</strong>.</p><p><a href="/">Back to City of Mandi</a></p>`;
      return;
    }
    document.title = `${biz.name} — City of Mandi`;
    const site = biz.website
      ? `<p class="landing-contact"><a href="${escapeHtml(biz.website)}" target="_blank" rel="noopener noreferrer">${escapeHtml(biz.website.replace(/^https?:\/\//, ""))}</a></p>`
      : "";
    section.innerHTML = `
      <header class="landing-section-head">
        <div>
          <p class="landing-section-kicker">${escapeHtml(biz.category || "Business")}</p>
          <h1>${escapeHtml(biz.name)}</h1>
        </div>
        <p class="muted landing-section-lede">${escapeHtml(biz.tagline || "")}</p>
      </header>
      <p>${escapeHtml(biz.summary || "")}</p>
      ${biz.location ? `<p class="landing-meta">${escapeHtml(biz.location)}</p>` : ""}
      ${site}
      <p class="muted" style="margin-top:1.2rem">A hosted page on City of Mandi, the civic home of Mandi. Also at <a href="/b/${encodeURIComponent(slug)}">/b/${escapeHtml(slug)}</a>. Subdomain <strong>${escapeHtml(slug)}.cityofmandi.com</strong> after wildcard DNS.</p>
    `;
  }

  boot();
})();
