(() => {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  let activeRole = params.get("role") || "delivery_food";
  const ROLES = ["delivery_food", "delivery_grocery", "delivery_hardware", "haulage"];
  if (!ROLES.includes(activeRole)) activeRole = "delivery_food";

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  function syncTabs() {
    document.querySelectorAll("#roleTabs [data-role]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.getAttribute("data-role") === activeRole);
    });
  }

  async function loadJobs() {
    const data = await api(`/api/hub/commerce/jobs?role=${encodeURIComponent(activeRole)}`);
    const box = $("jobsList");
    const jobs = data.jobs || [];
    if (!jobs.length) {
      box.innerHTML = `<p class="muted">No open ${esc(activeRole.replace(/_/g, " "))} jobs right now. Check again after a shop accepts an order.</p>`;
      return;
    }
    box.innerHTML = jobs.map((j) => `
      <article class="merchant-order">
        <header>
          <strong>${esc(j.shopName)}</strong>
          <span class="merchant-status">₹${j.total}</span>
        </header>
        <p class="muted">Pickup: ${esc(j.shopAddress || "Shop")}</p>
        <p>Drop: ${esc(j.dropAddress)}</p>
        <p class="muted">${esc(j.locality)} · ${esc(j.customerName || "Customer")}</p>
        <button type="button" class="btn primary" data-claim="${esc(j.id)}">Claim · दावा करें</button>
      </article>
    `).join("");
    box.querySelectorAll("[data-claim]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api(`/api/hub/commerce/jobs/${encodeURIComponent(btn.getAttribute("data-claim"))}/claim`, {
            method: "POST",
            body: "{}",
          });
          await loadJobs();
          alert("Claimed — head to the shop / stand, then complete the trip. COD stays with the customer.");
        } catch (ex) {
          alert(ex.message);
          btn.disabled = false;
        }
      });
    });
  }

  async function boot() {
    syncTabs();
    try {
      const sess = await api("/api/hub/providers/session");
      if (!sess.authenticated || !sess.provider) throw new Error("auth");
      $("deliveryGate").hidden = true;
      $("deliveryApp").hidden = false;
      $("logoutBtn").hidden = false;
      $("deliveryHello").textContent = `Signed in as ${sess.provider.name || "partner"}`;
      await loadJobs();
    } catch {
      $("deliveryGate").hidden = false;
      $("deliveryApp").hidden = true;
    }
  }

  document.querySelectorAll("#roleTabs [data-role]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeRole = btn.getAttribute("data-role");
      const url = new URL(location.href);
      url.searchParams.set("role", activeRole);
      history.replaceState(null, "", url);
      syncTabs();
      loadJobs().catch((ex) => alert(ex.message));
    });
  });

  $("refreshJobs")?.addEventListener("click", () => loadJobs().catch((ex) => alert(ex.message)));
  $("logoutBtn")?.addEventListener("click", async () => {
    await fetch("/api/hub/providers/logout", { method: "POST", credentials: "same-origin" });
    location.reload();
  });

  boot();
  setInterval(() => {
    if (!$("deliveryApp").hidden) loadJobs().catch(() => {});
  }, 25000);
})();
