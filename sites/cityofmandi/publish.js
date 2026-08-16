(() => {
  const $ = (id) => document.getElementById(id);
  const LABOUR_CATEGORIES = ["Construction", "Garden", "Clean", "Load/unload", "Other"];
  const TAXI_CATEGORIES = ["Local", "Outstation", "Airport/rail", "Shared", "Other"];
  const CATEGORY_HI = {
    Construction: "निर्माण / मजदूरी",
    Garden: "बागवानी",
    Clean: "सफाई",
    "Load/unload": "उतारना-चढ़ाना",
    Other: "अन्य",
    Local: "स्थानीय",
    Outstation: "आउटस्टेशन",
    "Airport/rail": "एयरपोर्ट / रेल",
    Shared: "शेयर",
  };
  let labourCategories = LABOUR_CATEGORIES;
  let taxiCategories = TAXI_CATEGORIES;

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

  function escapeHtml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function isBoardKind(kind) {
    return kind === "labour" || kind === "seri" || kind === "taxi";
  }

  function fillKinds(kinds) {
    const select = $("kind");
    const filtered = (kinds || []).filter((row) => row.id !== "seri");
    const options = [...filtered, { id: "other", title: "Something else · कुछ और" }];
    select.innerHTML = options.map((row) => {
      let label = escapeHtml(row.title);
      if (row.id === "labour") label += " · मज़दूर";
      if (row.id === "taxi") label += " · कैब";
      return `<option value="${escapeHtml(row.id)}">${label}</option>`;
    }).join("");
    syncKindUi();
  }

  function fillBoardCategories() {
    const labour = $("labourCategory");
    if (labour) {
      labour.innerHTML = labourCategories.map((c) =>
        `<option value="${escapeHtml(c)}">${escapeHtml(c)} · ${escapeHtml(CATEGORY_HI[c] || c)}</option>`
      ).join("");
    }
    const taxi = $("taxiCategory");
    if (taxi) {
      taxi.innerHTML = taxiCategories.map((c) =>
        `<option value="${escapeHtml(c)}">${escapeHtml(c)} · ${escapeHtml(CATEGORY_HI[c] || c)}</option>`
      ).join("");
    }
  }

  function syncKindUi() {
    const kind = $("kind").value;
    const isLabour = kind === "labour" || kind === "seri";
    const isTaxi = kind === "taxi";
    const isBoard = isLabour || isTaxi;
    $("bizExtras").hidden = kind !== "business";
    $("customKindWrap").hidden = kind !== "other";
    $("customKind").required = kind === "other";
    $("slug").required = kind === "business" && $("plan").value === "hosted";
    $("contactFields").hidden = isBoard;
    $("labourFields").hidden = !isLabour;
    $("taxiFields").hidden = !isTaxi;
    $("boardHint").hidden = !isBoard;
    if (isLabour) {
      $("boardHint").textContent = "Labour need: no public phone. Workers respond privately — you see contacts on this desk.";
      $("category").value = $("labourCategory").value || "Other";
      $("phone").value = "";
      $("url").value = "";
    } else if (isTaxi) {
      $("boardHint").textContent = "Ride request: pickup, drop, when. Drivers respond privately — contacts stay on this desk.";
      $("category").value = $("taxiCategory").value || "Other";
      $("phone").value = "";
      $("url").value = "";
    }
  }

  async function loadInterests(postId, host) {
    host.innerHTML = `<p class="muted">Loading interests…</p>`;
    try {
      const data = await api(`/api/hub/publisher/posts/${postId}/interests`);
      const rows = data.interests || [];
      if (!rows.length) {
        host.innerHTML = `<p class="muted">No interest yet · अभी कोई रुचि नहीं</p>`;
        return;
      }
      host.innerHTML = rows.map((row) => `
        <article class="desk-row seri-interest-row">
          <p class="landing-meta">${escapeHtml(row.createdAt || "")}</p>
          <strong>${escapeHtml(row.name)}</strong>
          <p class="landing-phone"><a href="tel:${escapeHtml(row.phone)}">${escapeHtml(row.phone)}</a></p>
          ${row.note ? `<p>${escapeHtml(row.note)}</p>` : ""}
        </article>
      `).join("");
    } catch (err) {
      host.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
    }
  }

  function renderPosts(posts) {
    const wrap = $("myPosts");
    if (!posts.length) {
      wrap.innerHTML = `<p class="muted">Nothing submitted yet.</p>`;
      return;
    }
    wrap.innerHTML = posts.map((post) => {
      const count = Number(post.interestCount || 0);
      const boardBlock = isBoardKind(post.kind) && post.status === "published"
        ? `<div class="seri-owner-interests">
            <p class="landing-meta">${count} interested · ${count} ने रुचि दिखाई</p>
            <button type="button" class="btn ghost compact" data-interests="${post.id}">Show contacts · संपर्क देखें</button>
            <div class="seri-interest-list" id="interests-${post.id}" hidden></div>
          </div>`
        : "";
      return `
      <article class="desk-row">
        <p class="landing-meta">${escapeHtml(post.kind)} · ${escapeHtml(post.status)}</p>
        <strong>${escapeHtml(post.title)}</strong>
        <p>${escapeHtml(post.summary)}</p>
        ${boardBlock}
        ${post.status !== "published" ? `<div class="desk-actions"><button type="button" class="btn ghost compact" data-del="${post.id}">Withdraw</button></div>` : ""}
      </article>
    `;
    }).join("");
    wrap.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/hub/publisher/posts/${btn.getAttribute("data-del")}`, { method: "DELETE" });
        const data = await api("/api/hub/publisher/posts");
        renderPosts(data.posts || []);
      });
    });
    wrap.querySelectorAll("[data-interests]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-interests");
        const box = document.getElementById(`interests-${id}`);
        if (!box) return;
        const open = box.hidden;
        box.hidden = !open;
        btn.textContent = open ? "Hide contacts · संपर्क छिपाएँ" : "Show contacts · संपर्क देखें";
        if (open) await loadInterests(id, box);
      });
    });
  }

  async function boot() {
    const sess = await api("/api/hub/publisher/session");
    if (!sess.authenticated) {
      location.replace("/join?mode=login");
      return;
    }
    $("helloKicker").textContent = sess.publisher.name;
    if (Array.isArray(sess.seriCategories) && sess.seriCategories.length) {
      labourCategories = sess.seriCategories;
    }
    if (Array.isArray(sess.taxiCategories) && sess.taxiCategories.length) {
      taxiCategories = sess.taxiCategories;
    }
    fillKinds(sess.kinds || []);
    fillBoardCategories();
    const data = await api("/api/hub/publisher/posts");
    if (Array.isArray(data.seriCategories) && data.seriCategories.length) {
      labourCategories = data.seriCategories;
    }
    if (Array.isArray(data.taxiCategories) && data.taxiCategories.length) {
      taxiCategories = data.taxiCategories;
    }
    fillBoardCategories();
    renderPosts(data.posts || []);
  }

  $("logoutBtn").addEventListener("click", async () => {
    await api("/api/hub/publisher/logout", { method: "POST", body: "{}" });
    location.href = "/join";
  });

  $("kind").addEventListener("change", syncKindUi);
  $("plan").addEventListener("change", syncKindUi);
  $("labourCategory")?.addEventListener("change", () => {
    if ($("kind").value === "labour" || $("kind").value === "seri") {
      $("category").value = $("labourCategory").value;
    }
  });
  $("taxiCategory")?.addEventListener("change", () => {
    if ($("kind").value === "taxi") $("category").value = $("taxiCategory").value;
  });

  $("postForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("postError").hidden = true;
    $("postStatus").textContent = "";
    const kind = $("kind").value === "other"
      ? $("customKind").value.trim().toLowerCase()
      : $("kind").value;
    const isLabour = kind === "labour" || kind === "seri";
    const isTaxi = kind === "taxi";
    const isBoard = isLabour || isTaxi;
    try {
      const payload = {
        kind: kind === "seri" ? "labour" : kind,
        title: $("title").value.trim(),
        summary: $("summary").value.trim(),
        category: isLabour
          ? ($("labourCategory").value || "Other")
          : isTaxi
            ? ($("taxiCategory").value || "Other")
            : $("category").value.trim(),
        location: isLabour
          ? ($("locationLabour").value.trim() || $("location").value.trim())
          : isTaxi
            ? ($("taxiPickup").value.trim() || $("location").value.trim())
            : $("location").value.trim(),
        phone: isBoard ? "" : $("phone").value.trim(),
        url: isBoard ? "" : $("url").value.trim(),
        plan: isBoard ? "listed" : $("plan").value,
        slug: isBoard ? "" : $("slug").value.trim(),
      };
      if (isTaxi) {
        payload.pickup = $("taxiPickup").value.trim();
        payload.dropoff = $("taxiDropoff").value.trim();
        payload.when = $("taxiWhen").value.trim();
        if (!payload.summary) {
          payload.summary = [payload.pickup && `From ${payload.pickup}`, payload.dropoff && `to ${payload.dropoff}`, payload.when && `· ${payload.when}`]
            .filter(Boolean)
            .join(" ");
        }
      }
      await api("/api/hub/publisher/posts", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      $("postForm").reset();
      syncKindUi();
      $("postStatus").textContent = isBoard
        ? "Submitted for review. After approval it appears on the board — providers respond privately. · समीक्षा के बाद बोर्ड पर दिखेगा।"
        : "Submitted for review. It will appear on the hub after an operator approves it.";
      const data = await api("/api/hub/publisher/posts");
      renderPosts(data.posts || []);
    } catch (err) {
      $("postError").hidden = false;
      $("postError").textContent = err.message;
    }
  });

  boot().catch(() => location.replace("/join"));
})();
