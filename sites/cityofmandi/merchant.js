(() => {
  const $ = (id) => document.getElementById(id);

  const BOARD_CATEGORIES = {
    food: ["Restaurants", "Cafés", "Bakeries", "Sweets", "Other"],
    grocery: ["Grocers", "Dairy", "Vegetables", "Other"],
    hardware: ["Hardware", "Sanitary", "Electrical", "Other"],
    haulage: ["Tempo", "Truck", "Pickup", "Shared", "Other"],
    rentals: [
      "Real estate", "Auto", "Electronics", "Furniture", "Appliances",
      "Fashion", "Tools", "Industrial", "Other",
    ],
  };

  const BOARD_HASH = {
    food: "/#landing-food",
    grocery: "/#landing-grocery",
    hardware: "/#landing-hardware",
    haulage: "/#landing-haulage",
    rentals: "/#landing-rentals",
  };

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

  let shop = null;
  let items = [];
  let orders = [];

  function fillCategories(boardId, selected) {
    const cats = BOARD_CATEGORIES[boardId] || BOARD_CATEGORIES.food;
    const sel = $("shopCategory");
    if (!sel) return;
    sel.innerHTML = cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    if (selected && cats.includes(selected)) sel.value = selected;
  }

  function showTab(name) {
    document.querySelectorAll(".merchant-tabs [data-tab]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.getAttribute("data-tab") === name);
    });
    document.querySelectorAll("[data-pane]").forEach((pane) => {
      pane.hidden = pane.getAttribute("data-pane") !== name;
    });
    if (name === "orders") loadOrders().catch(() => {});
    if (name === "packs") loadPacks().catch(() => {});
  }

  function fillShop() {
    const boardId = shop?.boardId || $("shopBoard")?.value || "food";
    if ($("shopBoard")) $("shopBoard").value = boardId;
    fillCategories(boardId, shop?.category);
    if (!shop) return;
    $("shopName").value = shop.name || "";
    $("shopSlug").value = shop.slug || "";
    $("shopSlug").readOnly = true;
    $("shopTagline").value = shop.tagline || "";
    $("shopLocality").value = shop.locality || "mandi";
    $("shopAddress").value = shop.address || "";
    $("shopSummary").value = shop.summary || "";
    $("shopOpen").checked = !!shop.openNow;
    $("shopFee").value = shop.deliveryFee ?? 20;
    $("shopFreeAbove").value = shop.freeDeliveryAbove ?? 300;
    $("shopMin").value = shop.minOrder ?? 0;
    const link = $("shopPublicLink");
    if (link && shop.slug) {
      link.href = `/b/${encodeURIComponent(shop.slug)}`;
      link.textContent = "Public page";
    } else if (link) {
      link.href = BOARD_HASH[boardId] || "/#landing-food";
      link.textContent = "Board";
    }
  }

  function renderMenu() {
    const box = $("menuList");
    if (!items.length) {
      box.innerHTML = `<p class="muted">No items yet — add your first listing.</p>`;
      return;
    }
    box.innerHTML = items.map((item) => `
      <article class="merchant-menu-row">
        <div>
          <strong>${esc(item.name)}</strong>
          <p class="muted">${esc(item.category)} · ₹${item.price}${item.unit ? ` / ${esc(item.unit)}` : ""}${item.veg ? " · Veg" : ""}${item.available ? "" : " · Off"}</p>
        </div>
        <div class="merchant-row-actions">
          <button type="button" class="btn ghost compact" data-edit="${esc(item.id)}">Edit</button>
          <button type="button" class="btn ghost compact" data-del="${esc(item.id)}">Delete</button>
        </div>
      </article>
    `).join("");
    box.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => editItem(btn.getAttribute("data-edit")));
    });
    box.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", () => delItem(btn.getAttribute("data-del")));
    });
  }

  function editItem(id) {
    const item = items.find((i) => i.id === id);
    if (!item) return;
    $("itemId").value = item.id;
    $("itemName").value = item.name;
    $("itemCategory").value = item.category || "";
    $("itemPrice").value = item.price;
    $("itemDesc").value = item.description || "";
    $("itemVeg").checked = !!item.veg;
    $("itemAvail").checked = !!item.available;
    $("itemSaveBtn").textContent = "Update item";
    $("itemResetBtn").hidden = false;
    showTab("menu");
  }

  async function delItem(id) {
    if (!confirm("Delete this item?")) return;
    await api(`/api/hub/commerce/merchant/items/${encodeURIComponent(id)}`, { method: "DELETE" });
    await refreshShop();
  }

  function resetItemForm() {
    $("itemForm").reset();
    $("itemId").value = "";
    $("itemVeg").checked = true;
    $("itemAvail").checked = true;
    $("itemSaveBtn").textContent = "Add item";
    $("itemResetBtn").hidden = true;
  }

  function statusActions(status) {
    const map = {
      placed: ["accepted", "rejected"],
      accepted: ["preparing", "cancelled"],
      preparing: ["ready", "cancelled"],
      ready: ["out_for_delivery", "delivered"],
      out_for_delivery: ["delivered"],
    };
    return map[status] || [];
  }

  function renderOrders() {
    const box = $("ordersList");
    if (!orders.length) {
      box.innerHTML = `<p class="muted">No orders yet.</p>`;
      return;
    }
    box.innerHTML = orders.map((o) => `
      <article class="merchant-order">
        <header>
          <strong>${esc(o.id)}</strong>
          <span class="merchant-status">${esc(o.status)}</span>
        </header>
        <p>${esc(o.customerName)}${o.customerPhone ? ` · ${esc(o.customerPhone)}` : ""}</p>
        <p class="muted">${esc(o.address || "Pickup")} · ₹${o.total} · ${esc(o.payment || "cod").toUpperCase()}</p>
        <ul class="merchant-order-items">
          ${(o.items || []).map((i) => `<li>${esc(i.name)} × ${i.qty} — ₹${i.line}</li>`).join("")}
        </ul>
        <div class="merchant-order-actions">
          ${statusActions(o.status).map((s) => `
            <button type="button" class="btn primary compact" data-order="${esc(o.id)}" data-status="${s}">${s.replace(/_/g, " ")}</button>
          `).join("")}
        </div>
      </article>
    `).join("");
    box.querySelectorAll("[data-order]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/hub/commerce/merchant/orders/${encodeURIComponent(btn.getAttribute("data-order"))}/status`, {
            method: "POST",
            body: JSON.stringify({ status: btn.getAttribute("data-status") }),
          });
          await loadOrders();
        } catch (ex) {
          alert(ex.message);
        }
      });
    });
  }

  async function refreshShop() {
    const data = await api("/api/hub/commerce/merchant/shop");
    shop = data.shop;
    items = data.items || [];
    fillShop();
    renderMenu();
  }

  async function loadOrders() {
    const data = await api("/api/hub/commerce/merchant/orders");
    orders = data.orders || [];
    renderOrders();
  }

  let packPayCfg = { onlineEnabled: false, demoEnabled: true, packs: [] };

  function renderPacks(purchases) {
    const cat = $("packsCatalog");
    const list = $("packsPurchases");
    const packs = packPayCfg.packs || [];
    if (cat) {
      if (!packs.length) {
        cat.innerHTML = `<p class="muted">No packs configured.</p>`;
      } else {
        const mode = packPayCfg.onlineEnabled
          ? "Pay online (Razorpay)"
          : packPayCfg.demoEnabled
            ? "Activate now (demo)"
            : "Request invoice";
        cat.innerHTML = packs.map((p) => `
          <article class="merchant-pack-card">
            <div>
              <strong>${esc(p.title)}</strong>
              <p class="muted">${esc(p.lede)} · ${p.days} days</p>
            </div>
            <div class="merchant-pack-buy">
              <strong>₹${p.price}</strong>
              <button type="button" class="btn primary compact" data-buy-pack="${esc(p.id)}">${mode}</button>
            </div>
          </article>
        `).join("");
        cat.querySelectorAll("[data-buy-pack]").forEach((btn) => {
          btn.addEventListener("click", () => buyPack(btn.getAttribute("data-buy-pack"), btn));
        });
      }
    }
    if (list) {
      if (!purchases.length) {
        list.innerHTML = `<p class="muted">No purchases yet.</p>`;
      } else {
        list.innerHTML = purchases.map((p) => `
          <article class="merchant-order">
            <header>
              <strong>${esc(p.title)}</strong>
              <span class="merchant-status">${esc(p.status)} · ${esc(p.paymentStatus)}</span>
            </header>
            <p class="muted">₹${p.amount} · ${esc(p.startsAt || "—")} → ${esc(p.endsAt || "—")}</p>
          </article>
        `).join("");
      }
    }
  }

  async function loadPacks() {
    const data = await api("/api/hub/commerce/merchant/packs");
    packPayCfg = data;
    renderPacks(data.purchases || []);
  }

  async function openRazorpay(rzp, onSuccess) {
    await new Promise((resolve, reject) => {
      if (window.Razorpay) return resolve();
      const s = document.createElement("script");
      s.src = "https://checkout.razorpay.com/v1/checkout.js";
      s.onload = resolve;
      s.onerror = () => reject(new Error("Could not load Razorpay"));
      document.head.appendChild(s);
    });
    return new Promise((resolve, reject) => {
      const checkout = new window.Razorpay({
        key: rzp.keyId,
        amount: rzp.amount,
        currency: rzp.currency || "INR",
        name: rzp.name || "City of Mandi",
        description: rzp.description || "",
        order_id: rzp.orderId,
        handler(response) {
          onSuccess(response).then(resolve).catch(reject);
        },
        modal: { ondismiss() { reject(new Error("Payment cancelled")); } },
      });
      checkout.open();
    });
  }

  async function buyPack(packId, btn) {
    if (btn) btn.disabled = true;
    try {
      const payment = packPayCfg.onlineEnabled ? "online" : (packPayCfg.demoEnabled ? "demo" : "invoice");
      const data = await api("/api/hub/commerce/merchant/packs", {
        method: "POST",
        body: JSON.stringify({ packId, payment }),
      });
      if (data.razorpay) {
        await openRazorpay(data.razorpay, async (response) => {
          await api(`/api/hub/commerce/merchant/packs/${encodeURIComponent(data.purchase.id)}/verify`, {
            method: "POST",
            body: JSON.stringify({
              razorpayOrderId: response.razorpay_order_id,
              razorpayPaymentId: response.razorpay_payment_id,
              razorpaySignature: response.razorpay_signature,
            }),
          });
        });
      }
      await loadPacks();
      await refreshShop();
      alert(data.razorpay ? "Pack activated after payment." : "Pack activated.");
    } catch (ex) {
      alert(ex.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function boot() {
    fillCategories("food");
    try {
      const sess = await api("/api/hub/publisher/session");
      if (!sess.authenticated || !sess.publisher) throw new Error("auth");
    } catch {
      $("merchantGate").hidden = false;
      $("merchantApp").hidden = true;
      return;
    }
    $("merchantGate").hidden = true;
    $("merchantApp").hidden = false;
    await refreshShop();
    await loadOrders();
  }

  document.querySelectorAll(".merchant-tabs [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
  });

  $("shopBoard")?.addEventListener("change", () => {
    fillCategories($("shopBoard").value, $("shopCategory").value);
  });

  $("shopForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    $("shopSaveErr").hidden = true;
    $("shopSaveMsg").hidden = true;
    try {
      const data = await api("/api/hub/commerce/merchant/shop", {
        method: "POST",
        body: JSON.stringify({
          name: $("shopName").value.trim(),
          slug: $("shopSlug").value.trim(),
          tagline: $("shopTagline").value.trim(),
          category: $("shopCategory").value,
          locality: $("shopLocality").value,
          address: $("shopAddress").value.trim(),
          summary: $("shopSummary").value.trim(),
          boardId: $("shopBoard").value || "food",
          openNow: $("shopOpen").checked,
          deliveryFee: Number($("shopFee").value || 0),
          freeDeliveryAbove: Number($("shopFreeAbove").value || 0),
          minOrder: Number($("shopMin").value || 0),
          fulfillment: "both",
        }),
      });
      shop = data.shop;
      fillShop();
      $("shopSaveMsg").hidden = false;
      $("shopSaveMsg").textContent = "Saved.";
    } catch (ex) {
      $("shopSaveErr").hidden = false;
      $("shopSaveErr").textContent = ex.message;
    }
  });

  $("itemForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/hub/commerce/merchant/items", {
        method: "POST",
        body: JSON.stringify({
          id: $("itemId").value || undefined,
          name: $("itemName").value.trim(),
          category: $("itemCategory").value.trim() || "Other",
          price: Number($("itemPrice").value),
          description: $("itemDesc").value.trim(),
          veg: $("itemVeg").checked,
          available: $("itemAvail").checked,
        }),
      });
      resetItemForm();
      await refreshShop();
    } catch (ex) {
      alert(ex.message);
    }
  });

  $("itemResetBtn")?.addEventListener("click", resetItemForm);

  $("logoutBtn")?.addEventListener("click", async () => {
    await fetch("/api/hub/publisher/logout", { method: "POST", credentials: "same-origin" });
    location.href = "/join?next=%2Fmerchant";
  });

  boot().catch((ex) => {
    $("merchantGate").hidden = false;
    $("merchantGate").textContent = ex.message;
  });
})();
