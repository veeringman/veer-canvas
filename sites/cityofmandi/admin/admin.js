(() => {
  const FEATURE_KEYS = ["news", "places", "scitech", "culture", "services", "channels", "ads", "neighbourhoods", "businesses"];
  let ANIMATIONS = [
    { id: "independence", label: "Independence Day" },
    { id: "marquee", label: "Marquee" },
    { id: "pulse", label: "Pulse" },
    { id: "confetti", label: "Confetti" },
    { id: "fade_slide", label: "Fade & slide" },
    { id: "sparkle", label: "Sparkle" },
    { id: "banner", label: "Image banner" },
  ];

  const $ = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    const opts = { credentials: "same-origin", ...options };
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.error || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function escapeAttr(value) {
    return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }
  function escapeText(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  }

  function serviceRow(item = {}) {
    const wrap = document.createElement("div");
    wrap.className = "desk-row";
    wrap.innerHTML = `
      <div class="desk-row-grid">
        <label>Id <input name="id" value="${escapeAttr(item.id || "")}" placeholder="hosted-page"></label>
        <label>Title <input name="title" value="${escapeAttr(item.title || "")}" placeholder="Hosted business page"></label>
      </div>
      <label>Note <input name="lede" value="${escapeAttr(item.lede || "")}"></label>
      <label class="desk-check"><input type="checkbox" name="enabled" ${item.enabled !== false ? "checked" : ""}> Offered</label>
      <div class="desk-actions"><button type="button" class="btn ghost compact remove">Remove</button></div>
    `;
    wrap.querySelector(".remove").addEventListener("click", () => wrap.remove());
    return wrap;
  }

  function bizRow(item = {}) {
    const wrap = document.createElement("div");
    wrap.className = "desk-row";
    wrap.innerHTML = `
      <div class="desk-row-grid">
        <label>Slug <input name="slug" value="${escapeAttr(item.slug || "")}" placeholder="veerlabs"></label>
        <label>Name <input name="name" value="${escapeAttr(item.name || "")}"></label>
        <label>Category <input name="category" value="${escapeAttr(item.category || "")}"></label>
        <label>Plan
          <select name="plan">
            <option value="listed"${item.plan === "listed" ? " selected" : ""}>Listed</option>
            <option value="featured"${item.plan === "featured" ? " selected" : ""}>Featured</option>
            <option value="hosted"${item.plan === "hosted" || !item.plan ? " selected" : ""}>Hosted page</option>
          </select>
        </label>
        <label>Status
          <select name="status">
            <option value="draft"${item.status === "draft" ? " selected" : ""}>Draft</option>
            <option value="published"${item.status !== "draft" ? " selected" : ""}>Published</option>
          </select>
        </label>
        <label>Website <input name="website" value="${escapeAttr(item.website || "")}" placeholder="https://"></label>
      </div>
      <label>Tagline <input name="tagline" value="${escapeAttr(item.tagline || "")}"></label>
      <label>Summary <textarea name="summary" rows="3">${escapeText(item.summary || "")}</textarea></label>
      <label>Location <input name="location" value="${escapeAttr(item.location || "")}"></label>
      <div class="desk-actions"><button type="button" class="btn ghost compact remove">Remove</button></div>
    `;
    wrap.querySelector(".remove").addEventListener("click", () => wrap.remove());
    return wrap;
  }

  function animOptions(selected) {
    return ANIMATIONS.map((a) =>
      `<option value="${escapeAttr(a.id)}"${a.id === selected ? " selected" : ""}>${escapeText(a.label)}</option>`
    ).join("");
  }

  function sponsoredRow(item = {}) {
    const wrap = document.createElement("div");
    wrap.className = "desk-row sponsored-row";
    const anim = item.animation || "independence";
    wrap.innerHTML = `
      <div class="desk-row-grid">
        <label>Id <input name="id" value="${escapeAttr(item.id || "")}" placeholder="happy-independence-day"></label>
        <label>Title <input name="title" value="${escapeAttr(item.title || "")}" placeholder="Happy Independence Day!"></label>
        <label>Animation
          <select name="animation">${animOptions(anim)}</select>
        </label>
        <label>Weight <input name="weight" type="number" min="1" max="100" value="${escapeAttr(item.weight || 10)}"></label>
      </div>
      <label>Subtitle <input name="subtitle" value="${escapeAttr(item.subtitle || "")}" placeholder="City of Mandi · Jai Hind"></label>
      <div class="desk-row-grid">
        <label>Sponsor <input name="sponsor" value="${escapeAttr(item.sponsor || "")}"></label>
        <label>Link URL <input name="linkUrl" value="${escapeAttr(item.linkUrl || "")}" placeholder="https://"></label>
        <label>Starts (ISO) <input name="startsAt" value="${escapeAttr(item.startsAt || "")}" placeholder="2026-08-15T00:00:00Z"></label>
        <label>Ends (ISO) <input name="endsAt" value="${escapeAttr(item.endsAt || "")}" placeholder="optional"></label>
      </div>
      <div class="sponsored-image-row">
        <label>Image URL <input name="imageUrl" value="${escapeAttr(item.imageUrl || "")}" placeholder="/api/hub/sponsored-ads/images/…"></label>
        <label class="btn ghost compact sponsored-upload-btn">Upload image
          <input type="file" name="imageFile" accept="image/*" hidden>
        </label>
        <img class="sponsored-preview" alt="" ${item.imageUrl ? `src="${escapeAttr(item.imageUrl)}"` : "hidden"}>
      </div>
      <label class="desk-check"><input type="checkbox" name="active" ${item.active !== false ? "checked" : ""}> Active in header</label>
      <div class="desk-actions"><button type="button" class="btn ghost compact remove">Remove</button></div>
    `;
    wrap.querySelector(".remove").addEventListener("click", () => wrap.remove());
    const fileInput = wrap.querySelector('[name="imageFile"]');
    const urlInput = wrap.querySelector('[name="imageUrl"]');
    const preview = wrap.querySelector(".sponsored-preview");
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const data = await api("/api/hub/sponsored-ads/upload", { method: "POST", body: fd });
        urlInput.value = data.imageUrl || "";
        if (data.imageUrl) {
          preview.hidden = false;
          preview.src = data.imageUrl;
        }
        $("sponsoredStatus").textContent = "Image uploaded — save ads to keep.";
      } catch (err) {
        $("sponsoredStatus").textContent = err.message;
      }
    });
    urlInput.addEventListener("input", () => {
      if (urlInput.value.trim()) {
        preview.hidden = false;
        preview.src = urlInput.value.trim();
      } else {
        preview.hidden = true;
        preview.removeAttribute("src");
      }
    });
    return wrap;
  }

  function readServices() {
    return [...$("servicesList").querySelectorAll(".desk-row")].map((row) => ({
      id: row.querySelector('[name="id"]').value.trim(),
      title: row.querySelector('[name="title"]').value.trim(),
      lede: row.querySelector('[name="lede"]').value.trim(),
      enabled: row.querySelector('[name="enabled"]').checked,
    }));
  }

  function readBusinesses() {
    return [...$("bizList").querySelectorAll(".desk-row")].map((row) => ({
      slug: row.querySelector('[name="slug"]').value.trim().toLowerCase(),
      name: row.querySelector('[name="name"]').value.trim(),
      category: row.querySelector('[name="category"]').value.trim(),
      plan: row.querySelector('[name="plan"]').value,
      status: row.querySelector('[name="status"]').value,
      website: row.querySelector('[name="website"]').value.trim(),
      tagline: row.querySelector('[name="tagline"]').value.trim(),
      summary: row.querySelector('[name="summary"]').value.trim(),
      location: row.querySelector('[name="location"]').value.trim(),
    }));
  }

  function readSponsored() {
    return [...$("sponsoredList").querySelectorAll(".sponsored-row")].map((row) => ({
      id: row.querySelector('[name="id"]').value.trim(),
      title: row.querySelector('[name="title"]').value.trim(),
      subtitle: row.querySelector('[name="subtitle"]').value.trim(),
      animation: row.querySelector('[name="animation"]').value,
      imageUrl: row.querySelector('[name="imageUrl"]').value.trim(),
      linkUrl: row.querySelector('[name="linkUrl"]').value.trim(),
      sponsor: row.querySelector('[name="sponsor"]').value.trim(),
      active: row.querySelector('[name="active"]').checked,
      weight: Number(row.querySelector('[name="weight"]').value || 10),
      startsAt: row.querySelector('[name="startsAt"]').value.trim(),
      endsAt: row.querySelector('[name="endsAt"]').value.trim(),
    }));
  }

  function fillDesk(state) {
    const features = (state.hub && state.hub.features) || {};
    FEATURE_KEYS.forEach((key) => {
      const input = $("featuresForm").elements[key];
      if (input) input.checked = features[key] !== false;
    });
    $("servicesList").innerHTML = "";
    (state.hub.services || []).forEach((item) => $("servicesList").appendChild(serviceRow(item)));
    $("bizList").innerHTML = "";
    (state.businesses.businesses || []).forEach((item) => $("bizList").appendChild(bizRow(item)));
  }

  async function loadSponsored() {
    const data = await api("/api/hub/sponsored-ads/manage");
    if (Array.isArray(data.animations) && data.animations.length) {
      ANIMATIONS = data.animations;
    }
    $("sponsoredList").innerHTML = "";
    const ads = data.ads || [];
    if (!ads.length) {
      $("sponsoredList").appendChild(sponsoredRow({
        id: "happy-independence-day",
        title: "Happy Independence Day!",
        subtitle: "City of Mandi · Jai Hind",
        animation: "independence",
        active: true,
        weight: 20,
      }));
      return;
    }
    ads.forEach((item) => $("sponsoredList").appendChild(sponsoredRow(item)));
  }

  function renderModeration(data) {
    const pending = data.pending || [];
    const pubs = data.publishers || [];
    const queue = $("moderationList");
    const people = $("publisherList");
    if (!pending.length) {
      queue.innerHTML = `<p class="muted">Nothing waiting. New listings from /publish land here.</p>`;
    } else {
      queue.innerHTML = pending.map((post) => `
        <article class="desk-row">
          <p class="landing-meta">${escapeText(post.kind)} · ${escapeText(post.plan)} · ${escapeText(post.publisherName || "")} · ${escapeText(post.publisherEmail || "")}</p>
          <strong>${escapeText(post.title)}</strong>
          <p>${escapeText(post.summary)}</p>
          <div class="desk-actions">
            <button type="button" class="btn primary compact" data-approve="${post.id}">Approve</button>
            <button type="button" class="btn ghost compact" data-reject="${post.id}">Reject</button>
          </div>
        </article>
      `).join("");
      queue.querySelectorAll("[data-approve]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/api/hub/moderation/${btn.getAttribute("data-approve")}/approve`, { method: "POST", body: "{}" });
          await loadModeration();
        });
      });
      queue.querySelectorAll("[data-reject]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/api/hub/moderation/${btn.getAttribute("data-reject")}/reject`, { method: "POST", body: "{}" });
          await loadModeration();
        });
      });
    }
    if (!pubs.length) {
      people.innerHTML = `<p class="muted">No publisher accounts yet.</p>`;
      return;
    }
    people.innerHTML = pubs.map((row) => `
      <article class="desk-row">
        <p class="landing-meta">${escapeText(row.status)} · ${escapeText(row.email)}</p>
        <strong>${escapeText(row.name)}</strong>
        <div class="desk-actions">
          <button type="button" class="btn ghost compact" data-pub="${row.id}" data-status="${row.status === "active" ? "disabled" : "active"}">
            ${row.status === "active" ? "Pause" : "Reactivate"}
          </button>
        </div>
      </article>
    `).join("");
    people.querySelectorAll("[data-pub]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/hub/publishers/${btn.getAttribute("data-pub")}/status`, {
          method: "POST",
          body: JSON.stringify({ status: btn.getAttribute("data-status") }),
        });
        await loadModeration();
      });
    });
  }

  async function loadModeration() {
    const data = await api("/api/hub/moderation");
    renderModeration(data);
  }

  function showDesk() {
    $("loginCard").hidden = true;
    $("deskApp").hidden = false;
    $("logoutBtn").hidden = false;
  }

  async function boot() {
    try {
      const sess = await api("/api/hub/session");
      if (!sess.authenticated) return;
      const state = await api("/api/hub/state");
      fillDesk(state);
      showDesk();
      await loadModeration();
      await loadSponsored();
    } catch {
      /* stay on login */
    }
  }

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("loginError").hidden = true;
    try {
      await api("/api/hub/login", {
        method: "POST",
        body: JSON.stringify({
          username: $("username").value.trim(),
          password: $("password").value,
        }),
      });
      const state = await api("/api/hub/state");
      fillDesk(state);
      showDesk();
      await loadModeration();
      await loadSponsored();
    } catch (err) {
      $("loginError").hidden = false;
      $("loginError").textContent = err.message;
    }
  });

  $("logoutBtn").addEventListener("click", async () => {
    await api("/api/hub/logout", { method: "POST", body: "{}" });
    location.reload();
  });

  $("featuresForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const features = {};
    FEATURE_KEYS.forEach((key) => {
      features[key] = $("featuresForm").elements[key].checked;
    });
    await api("/api/hub/hub", {
      method: "PUT",
      body: JSON.stringify({ features, services: readServices() }),
    });
    $("saveStatus").textContent = "Features saved.";
  });

  $("addServiceBtn").addEventListener("click", () => {
    $("servicesList").appendChild(serviceRow({ enabled: true }));
  });
  $("saveServicesBtn").addEventListener("click", async () => {
    const features = {};
    FEATURE_KEYS.forEach((key) => {
      features[key] = $("featuresForm").elements[key].checked;
    });
    await api("/api/hub/hub", {
      method: "PUT",
      body: JSON.stringify({ features, services: readServices() }),
    });
    $("saveStatus").textContent = "Services saved.";
  });

  $("addBizBtn").addEventListener("click", () => {
    $("bizList").appendChild(bizRow({ plan: "hosted", status: "draft" }));
  });
  $("saveBizBtn").addEventListener("click", async () => {
    await api("/api/hub/businesses", {
      method: "PUT",
      body: JSON.stringify({ businesses: readBusinesses() }),
    });
    $("saveStatus").textContent = "Business pages saved.";
  });

  $("addSponsoredBtn").addEventListener("click", () => {
    $("sponsoredList").appendChild(sponsoredRow({
      animation: "marquee",
      active: true,
      weight: 10,
    }));
  });
  $("saveSponsoredBtn").addEventListener("click", async () => {
    try {
      await api("/api/hub/sponsored-ads", {
        method: "PUT",
        body: JSON.stringify({ ads: readSponsored() }),
      });
      $("sponsoredStatus").textContent = "Sponsored ads saved.";
      await loadSponsored();
    } catch (err) {
      $("sponsoredStatus").textContent = err.message;
    }
  });

  boot();
})();
