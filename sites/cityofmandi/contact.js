(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    me: null,
    meta: null,
    activeMailId: null,
    view: "write",
  };

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

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function showPanel(name) {
    state.view = name;
    $("writePanel").hidden = name !== "write";
    $("minePanel").hidden = name !== "mine";
    $("boxPanel").hidden = name !== "box";
    $("detailPanel").hidden = name !== "detail";
    $("tabWrite").setAttribute("aria-selected", name === "write" ? "true" : "false");
    $("tabMine").setAttribute("aria-selected", name === "mine" ? "true" : "false");
    $("tabBox").setAttribute("aria-selected", name === "box" ? "true" : "false");
    $("tabWrite").classList.toggle("primary", name === "write");
    $("tabWrite").classList.toggle("ghost", name !== "write");
    $("tabMine").classList.toggle("primary", name === "mine");
    $("tabMine").classList.toggle("ghost", name !== "mine");
    $("tabBox").classList.toggle("primary", name === "box");
    $("tabBox").classList.toggle("ghost", name !== "box");
  }

  async function loadMeta() {
    const [meta, me] = await Promise.all([
      api("/api/board/contact/meta"),
      api("/api/board/me").catch(() => ({ ok: true, canAccessMailbox: false })),
    ]);
    state.meta = meta;
    state.me = me;
    $("contactCategory").innerHTML = (meta.categories || [])
      .map((c) => `<option value="${esc(c.id)}">${esc(c.title)}</option>`)
      .join("");
    $("contactArea").innerHTML = (meta.areas || [])
      .map((a) => `<option value="${esc(a.id)}">${esc(a.title)}</option>`)
      .join("");
    if (meta.displayName) $("contactName").value = meta.displayName;
    if (meta.email && !String(meta.email).includes("@adda.local")) {
      $("contactEmail").value = meta.email;
    }
    $("contactHint").textContent = meta.authenticated
      ? "Signed in — replies will show under My messages."
      : "Optional: sign in on Mandi Adda to track replies.";
    $("tabBox").hidden = !me.canAccessMailbox && !me.isOperator;
  }

  function mailCard(item, { manage = false } = {}) {
    return `
      <article class="desk-row contact-mail-card" data-mail="${esc(item.id)}">
        <p class="landing-meta">${esc(item.status)} · ${esc(item.category)}${item.areaTitle ? ` · ${esc(item.areaTitle)}` : ""} · ${esc(item.createdAt || "")}</p>
        <strong>${esc(item.subject)}</strong>
        <p>${esc((item.body || "").slice(0, 160))}${(item.body || "").length > 160 ? "…" : ""}</p>
        <p class="landing-contact">${esc(item.authorName)}${item.authorEmail ? ` · ${esc(item.authorEmail)}` : ""}</p>
        ${manage ? "" : ""}
      </article>
    `;
  }

  async function loadMine() {
    try {
      const data = await api("/api/board/mailbox/mine");
      const list = $("mineList");
      if (!(data.items || []).length) {
        list.innerHTML = `<p class="muted">No messages yet.</p>`;
        return;
      }
      list.innerHTML = data.items.map((item) => mailCard(item)).join("");
      list.querySelectorAll("[data-mail]").forEach((el) => {
        el.addEventListener("click", () => openMail(el.getAttribute("data-mail")));
      });
    } catch (err) {
      $("mineList").innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    }
  }

  async function loadBox() {
    const status = $("boxStatusFilter").value;
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    try {
      const data = await api(`/api/board/mailbox${q}`);
      const list = $("boxList");
      if (!(data.items || []).length) {
        list.innerHTML = `<p class="muted">Mailbox is empty for this filter.</p>`;
        return;
      }
      list.innerHTML = data.items.map((item) => mailCard(item, { manage: true })).join("");
      list.querySelectorAll("[data-mail]").forEach((el) => {
        el.addEventListener("click", () => openMail(el.getAttribute("data-mail")));
      });
    } catch (err) {
      $("boxList").innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  async function openMail(id) {
    state.activeMailId = id;
    const data = await api(`/api/board/mailbox/${encodeURIComponent(id)}`);
    const item = data.item;
    showPanel("detail");
    $("detailMeta").textContent = `${item.status} · ${item.category} · ${data.areaTitle || item.areaId} · ${item.createdAt}`;
    $("detailSubject").textContent = item.subject;
    $("detailBody").textContent = item.body;
    $("detailReplies").innerHTML = (item.replies || [])
      .map((r) => {
        if (r.status === "hidden" && !data.canManage) return "";
        return `<article class="desk-row">
          <p class="landing-meta">${esc(r.authorRole)} · ${esc(r.authorName)} · ${esc(r.createdAt)}${r.status === "hidden" ? " · hidden" : ""}</p>
          <p>${esc(r.body)}</p>
          ${data.canManage ? `<div class="desk-actions">
            <button type="button" class="btn ghost compact" data-reply-mod="${esc(r.id)}" data-action="${r.status === "hidden" ? "unhide" : "hide"}">${r.status === "hidden" ? "Unhide" : "Hide"}</button>
          </div>` : ""}
        </article>`;
      })
      .join("") || `<p class="muted">No replies yet.</p>`;
    $("replyForm").hidden = false;
    $("detailStatus").hidden = !data.canManage;
    $("detailStatusBtn").hidden = !data.canManage;
    if (data.canManage) $("detailStatus").value = item.status;
    history.replaceState(null, "", `#mail/${id}`);
    $("detailReplies").querySelectorAll("[data-reply-mod]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/board/mailbox/${encodeURIComponent(id)}/replies/${encodeURIComponent(btn.dataset.replyMod)}/moderate`, {
          method: "POST",
          body: JSON.stringify({ action: btn.dataset.action }),
        });
        openMail(id);
      });
    });
  }

  $("tabWrite").addEventListener("click", () => {
    history.replaceState(null, "", "/contact");
    showPanel("write");
  });
  $("tabMine").addEventListener("click", () => {
    history.replaceState(null, "", "/contact#mine");
    showPanel("mine");
    loadMine();
  });
  $("tabBox").addEventListener("click", () => {
    history.replaceState(null, "", "/contact#mailbox");
    showPanel("box");
    loadBox();
  });
  $("boxRefresh").addEventListener("click", loadBox);
  $("boxStatusFilter").addEventListener("change", loadBox);
  $("detailBack").addEventListener("click", () => {
    if (state.me?.canAccessMailbox || state.me?.isOperator) {
      showPanel("box");
      loadBox();
    } else {
      showPanel("mine");
      loadMine();
    }
  });

  $("contactForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("contactError").hidden = true;
    $("contactOk").hidden = true;
    try {
      const data = await api("/api/board/contact", {
        method: "POST",
        body: JSON.stringify({
          name: $("contactName").value.trim(),
          email: $("contactEmail").value.trim(),
          category: $("contactCategory").value,
          areaId: $("contactArea").value,
          subject: $("contactSubject").value.trim(),
          body: $("contactBody").value.trim(),
        }),
      });
      $("contactOk").hidden = false;
      $("contactOk").textContent = data.message || "Sent.";
      $("contactSubject").value = "";
      $("contactBody").value = "";
      if (data.id) openMail(data.id).catch(() => {});
    } catch (err) {
      $("contactError").hidden = false;
      $("contactError").textContent = err.message;
    }
  });

  $("replyForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("replyError").hidden = true;
    try {
      await api(`/api/board/mailbox/${encodeURIComponent(state.activeMailId)}/reply`, {
        method: "POST",
        body: JSON.stringify({ body: $("replyBody").value.trim() }),
      });
      $("replyBody").value = "";
      openMail(state.activeMailId);
    } catch (err) {
      $("replyError").hidden = false;
      $("replyError").textContent = err.message;
    }
  });

  $("detailStatusBtn").addEventListener("click", async () => {
    await api(`/api/board/mailbox/${encodeURIComponent(state.activeMailId)}`, {
      method: "PATCH",
      body: JSON.stringify({ status: $("detailStatus").value }),
    });
    openMail(state.activeMailId);
  });

  function applyHash() {
    const hash = (location.hash || "").replace(/^#/, "");
    if (hash.startsWith("mail/")) {
      openMail(hash.slice(5)).catch(() => showPanel("write"));
      return;
    }
    if (hash === "mine") {
      showPanel("mine");
      loadMine();
      return;
    }
    if (hash === "mailbox") {
      showPanel("box");
      loadBox();
      return;
    }
    showPanel("write");
  }

  loadMeta().then(applyHash).catch(() => showPanel("write"));
  window.addEventListener("hashchange", applyHash);
})();
