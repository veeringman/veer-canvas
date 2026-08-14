(() => {
  const $ = (id) => document.getElementById(id);

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

  function fillKinds(kinds) {
    const select = $("kind");
    const options = [...kinds, { id: "other", title: "Something else" }];
    select.innerHTML = options.map((row) =>
      `<option value="${escapeHtml(row.id)}">${escapeHtml(row.title)}</option>`
    ).join("");
    syncKindUi();
  }

  function syncKindUi() {
    const kind = $("kind").value;
    $("bizExtras").hidden = kind !== "business";
    $("customKindWrap").hidden = kind !== "other";
    $("customKind").required = kind === "other";
    $("slug").required = kind === "business" && $("plan").value === "hosted";
  }

  function renderPosts(posts) {
    const wrap = $("myPosts");
    if (!posts.length) {
      wrap.innerHTML = `<p class="muted">Nothing submitted yet.</p>`;
      return;
    }
    wrap.innerHTML = posts.map((post) => `
      <article class="desk-row">
        <p class="landing-meta">${escapeHtml(post.kind)} · ${escapeHtml(post.status)}</p>
        <strong>${escapeHtml(post.title)}</strong>
        <p>${escapeHtml(post.summary)}</p>
        ${post.status !== "published" ? `<div class="desk-actions"><button type="button" class="btn ghost compact" data-del="${post.id}">Withdraw</button></div>` : ""}
      </article>
    `).join("");
    wrap.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/api/hub/publisher/posts/${btn.getAttribute("data-del")}`, { method: "DELETE" });
        const data = await api("/api/hub/publisher/posts");
        renderPosts(data.posts || []);
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
    fillKinds(sess.kinds || []);
    const data = await api("/api/hub/publisher/posts");
    renderPosts(data.posts || []);
  }

  $("logoutBtn").addEventListener("click", async () => {
    await api("/api/hub/publisher/logout", { method: "POST", body: "{}" });
    location.href = "/join";
  });

  $("kind").addEventListener("change", syncKindUi);
  $("plan").addEventListener("change", syncKindUi);

  $("postForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("postError").hidden = true;
    $("postStatus").textContent = "";
    const kind = $("kind").value === "other"
      ? $("customKind").value.trim().toLowerCase()
      : $("kind").value;
    try {
      await api("/api/hub/publisher/posts", {
        method: "POST",
        body: JSON.stringify({
          kind,
          title: $("title").value.trim(),
          summary: $("summary").value.trim(),
          category: $("category").value.trim(),
          location: $("location").value.trim(),
          phone: $("phone").value.trim(),
          url: $("url").value.trim(),
          plan: $("plan").value,
          slug: $("slug").value.trim(),
        }),
      });
      $("postForm").reset();
      syncKindUi();
      $("postStatus").textContent = "Submitted for review. It will appear on the hub after an operator approves it.";
      const data = await api("/api/hub/publisher/posts");
      renderPosts(data.posts || []);
    } catch (err) {
      $("postError").hidden = false;
      $("postError").textContent = err.message;
    }
  });

  boot().catch(() => location.replace("/join"));
})();
