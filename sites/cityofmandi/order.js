(() => {
  const params = new URLSearchParams(location.search);
  const orderId = params.get("id") || "";
  const phone = params.get("phone") || "";

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const STEPS = ["placed", "accepted", "preparing", "ready", "out_for_delivery", "delivered"];

  function render(order) {
    const card = document.getElementById("orderCard");
    if (!order) {
      card.innerHTML = `<h1>Order not found</h1><p class="muted"><a href="/#landing-food">Food board</a></p>`;
      return;
    }
    const idx = STEPS.indexOf(order.status);
    const steps = STEPS.map((s, i) => `
      <li class="${i <= idx ? "is-done" : ""} ${order.status === s ? "is-current" : ""}">${esc(s.replace(/_/g, " "))}</li>
    `).join("");
    card.innerHTML = `
      <p class="landing-section-kicker">${esc((order.payment || "cod").toUpperCase())} · ${esc(order.paymentStatus || "")}</p>
      <h1>${esc(order.shopName || "Order")}</h1>
      <p class="muted">${esc(order.id)} · ₹${order.total}</p>
      <p class="order-status-pill">${esc(order.status.replace(/_/g, " "))}</p>
      <ol class="order-timeline">${steps}</ol>
      <ul class="merchant-order-items">
        ${(order.items || []).map((i) => `<li>${esc(i.name)} × ${i.qty} — ₹${i.line}</li>`).join("")}
      </ul>
      ${order.address ? `<p class="muted">Deliver to ${esc(order.address)}</p>` : ""}
      ${order.shopSlug ? `<p><a class="btn ghost compact" href="/b/${esc(order.shopSlug)}">Back to shop</a></p>` : ""}
    `;
  }

  async function load() {
    if (!orderId) {
      render(null);
      return;
    }
    const q = new URLSearchParams({ phone });
    const res = await fetch(`/api/hub/commerce/orders/${encodeURIComponent(orderId)}?${q}`, { cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      document.getElementById("orderCard").innerHTML = `<p class="error">${esc(data.error || "Could not load order")}</p>`;
      return;
    }
    render(data.order);
  }

  load().catch((ex) => {
    document.getElementById("orderCard").innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  });
  setInterval(() => { load().catch(() => {}); }, 20000);
})();
