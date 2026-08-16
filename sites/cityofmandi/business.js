(() => {
  const $ = (id) => document.getElementById(id);

  function slugFromLocation() {
    const host = (location.hostname || "").toLowerCase();
    const sub = host.match(/^([a-z0-9-]+)\.cityofmandi\.com$/);
    if (sub && sub[1] !== "www") return sub[1];
    const parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
    if (parts[0] === "b" && parts[1]) return parts[1].toLowerCase();
    return "";
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cartKey(slug) {
    return `hub_cart_${slug}`;
  }

  function loadCart(slug) {
    try {
      const raw = JSON.parse(localStorage.getItem(cartKey(slug)) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch {
      return {};
    }
  }

  function saveCart(slug, cart) {
    localStorage.setItem(cartKey(slug), JSON.stringify(cart));
  }

  let state = { slug: "", shop: null, items: [], cart: {}, pay: { onlineEnabled: false, demoEnabled: true } };

  function selectedPay() {
    const online = $("payOnline");
    const demo = $("payDemo");
    if (online && online.checked) return "online";
    if (demo && demo.checked) return "demo";
    return "cod";
  }

  function isRentals() {
    return (state.shop?.boardId || "") === "rentals";
  }

  function formatMoney(paiseOrRupees) {
    const n = Number(paiseOrRupees || 0);
    return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  }

  function syncPayUi() {
    const onlineWrap = $("payOnlineWrap");
    const demoWrap = $("payDemoWrap");
    if (onlineWrap) onlineWrap.hidden = !state.pay.onlineEnabled;
    if (demoWrap) demoWrap.hidden = !(!state.pay.onlineEnabled && state.pay.demoEnabled);
    const btn = $("shopPlaceBtn");
    const method = selectedPay();
    if (btn) {
      if (isRentals()) {
        btn.textContent = method === "cod"
          ? "Send enquiry · पूछताछ"
          : method === "online"
            ? "Pay deposit & enquire"
            : "Send enquiry · demo pay";
      } else {
        btn.textContent = method === "cod"
          ? "Place order · COD"
          : method === "online"
            ? "Pay online & place"
            : "Place order · pay now (demo)";
      }
    }
  }

  function cartLines() {
    const byId = Object.fromEntries(state.items.map((i) => [i.id, i]));
    return Object.entries(state.cart)
      .map(([id, qty]) => {
        const item = byId[id];
        if (!item || qty < 1) return null;
        return { item, qty: Number(qty), line: item.price * Number(qty) };
      })
      .filter(Boolean);
  }

  function cartTotals() {
    const lines = cartLines();
    const subtotal = lines.reduce((s, l) => s + l.line, 0);
    const shop = state.shop || {};
    let fee = Number(shop.deliveryFee || 0);
    if (isRentals()) fee = 0;
    const freeAbove = Number(shop.freeDeliveryAbove || 0);
    if (freeAbove && subtotal >= freeAbove) fee = 0;
    return { lines, subtotal, fee, total: subtotal + fee };
  }

  function syncCartBar() {
    const { lines, total } = cartTotals();
    const count = lines.reduce((s, l) => s + l.qty, 0);
    const bar = $("shopCartBar");
    if (!bar) return;
    if (!count) {
      bar.hidden = true;
      return;
    }
    bar.hidden = false;
    $("shopCartCount").textContent = String(count);
    $("shopCartTotal").textContent = formatMoney(total);
    const label = bar.querySelector(".shop-cart-label");
    if (label) label.textContent = isRentals() ? "View shortlist" : "View cart";
  }

  function renderCartSheet() {
    const { lines, subtotal, fee, total } = cartTotals();
    const box = $("shopCartLines");
    if (!lines.length) {
      box.innerHTML = `<p class="muted">${isRentals() ? "Shortlist is empty." : "Cart is empty."}</p>`;
    } else {
      box.innerHTML = lines.map(({ item, qty, line }) => `
        <div class="shop-cart-line">
          <div>
            <strong>${esc(item.name)}</strong>
            <p class="muted">${formatMoney(item.price)}${item.unit ? ` · ${esc(item.unit)}` : ""} × ${qty}</p>
          </div>
          <div class="shop-qty">
            <button type="button" data-dec="${esc(item.id)}">−</button>
            <span>${qty}</span>
            <button type="button" data-inc="${esc(item.id)}">+</button>
          </div>
          <strong>${formatMoney(line)}</strong>
        </div>
      `).join("");
    }
    if (isRentals()) {
      $("shopFeeLine").textContent = `Listings ${formatMoney(subtotal)} · Send enquiry to this broker`;
    } else {
      $("shopFeeLine").textContent = fee
        ? `Subtotal ${formatMoney(subtotal)} · Delivery ${formatMoney(fee)} · Total ${formatMoney(total)} · COD`
        : `Subtotal ${formatMoney(subtotal)} · Free delivery · Total ${formatMoney(total)} · COD`;
    }
    box.querySelectorAll("[data-inc]").forEach((btn) => {
      btn.addEventListener("click", () => bump(btn.getAttribute("data-inc"), 1));
    });
    box.querySelectorAll("[data-dec]").forEach((btn) => {
      btn.addEventListener("click", () => bump(btn.getAttribute("data-dec"), -1));
    });
  }

  function bump(id, delta) {
    const next = Math.max(0, (Number(state.cart[id] || 0) + delta));
    if (next === 0) delete state.cart[id];
    else state.cart[id] = next;
    saveCart(state.slug, state.cart);
    syncCartBar();
    renderMenu();
    renderCartSheet();
  }

  function renderMenu() {
    const section = $("bizSection");
    const shop = state.shop;
    if (!shop) return;
    const cats = [...new Set(state.items.map((i) => i.category || "Other"))];
    const chips = cats.map((c) => `<a class="shop-chip" href="#cat-${esc(c)}">${esc(c)}</a>`).join("");
    const blocks = cats.map((cat) => {
      const rows = state.items.filter((i) => (i.category || "Other") === cat);
      return `
        <section class="shop-cat" id="cat-${esc(cat)}">
          <h2>${esc(cat)}</h2>
          <div class="shop-items">
            ${rows.map((item) => {
              const qty = Number(state.cart[item.id] || 0);
              const meta = isRentals()
                ? `${esc(item.unit || "listing")}`
                : `${item.veg ? "Veg" : "Non-veg"}${item.unit ? ` · ${esc(item.unit)}` : ""}`;
              const addLabel = isRentals() ? "Shortlist" : "Add";
              return `
              <article class="shop-item">
                <div class="shop-item-copy">
                  <p class="shop-item-meta">${meta}</p>
                  <strong>${esc(item.name)}</strong>
                  ${item.description ? `<p class="muted">${esc(item.description)}</p>` : ""}
                  <p class="shop-price">${formatMoney(item.price)}${item.unit && isRentals() ? ` <span class="muted">· ${esc(item.unit)}</span>` : ""}</p>
                </div>
                <div class="shop-item-action">
                  ${qty
                    ? `<div class="shop-qty">
                        <button type="button" data-dec="${esc(item.id)}">−</button>
                        <span>${qty}</span>
                        <button type="button" data-inc="${esc(item.id)}">+</button>
                      </div>`
                    : `<button type="button" class="btn primary compact" data-add="${esc(item.id)}">${addLabel}</button>`}
                </div>
              </article>`;
            }).join("")}
          </div>
        </section>`;
    }).join("");

    section.innerHTML = `
      <header class="shop-hero">
        <p class="landing-section-kicker">${esc(shop.category || shop.boardId || "Food")}${shop.featured ? " · Sponsored" : ""}</p>
        <h1>${esc(shop.name)}</h1>
        <p class="muted">${esc(shop.tagline || shop.summary || "")}</p>
        <p class="shop-status ${shop.openNow ? "is-open" : "is-closed"}">
          ${shop.openNow ? "Open now · अभी खुला" : "Closed · बंद"}
          ${shop.address ? ` · ${esc(shop.address)}` : ""}
        </p>
      </header>
      <nav class="shop-chips" aria-label="${isRentals() ? "Listing categories" : "Menu sections"}">${chips}</nav>
      ${blocks || `<p class="muted">${isRentals() ? "No listings yet." : "Menu coming soon."}</p>`}
    `;
    section.querySelectorAll("[data-add]").forEach((btn) => {
      btn.addEventListener("click", () => bump(btn.getAttribute("data-add"), 1));
    });
    section.querySelectorAll("[data-inc]").forEach((btn) => {
      btn.addEventListener("click", () => bump(btn.getAttribute("data-inc"), 1));
    });
    section.querySelectorAll("[data-dec]").forEach((btn) => {
      btn.addEventListener("click", () => bump(btn.getAttribute("data-dec"), -1));
    });
  }

  function openSheet() {
    $("shopCartSheet").hidden = false;
    renderCartSheet();
  }

  function closeSheet() {
    $("shopCartSheet").hidden = true;
  }

  async function boot() {
    const slug = slugFromLocation();
    state.slug = slug;
    if ($("shopTopTitle")) $("shopTopTitle").textContent = slug || "Shop";
    const section = $("bizSection");
    if (!slug) {
      section.innerHTML = `<h1>Missing shop</h1><p class="muted">Use /b/{slug}</p>`;
      return;
    }
    const res = await fetch(`/api/hub/commerce/shops/${encodeURIComponent(slug)}`, { cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.shop) {
      // Fallback brochure from businesses.json
      const bizData = await fetch("/businesses.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({ businesses: [] }));
      const biz = (bizData.businesses || []).find((row) => row.slug === slug && row.status === "published");
      if (!biz) {
        document.title = "Not found — City of Mandi";
        section.innerHTML = `<h1>This page is not live</h1><p class="muted">No shop for <strong>${esc(slug)}</strong>.</p><p><a href="/#landing-food">Food board</a></p>`;
        return;
      }
      document.title = `${biz.name} — City of Mandi`;
      section.innerHTML = `
        <header class="shop-hero">
          <p class="landing-section-kicker">${esc(biz.category || "Business")}</p>
          <h1>${esc(biz.name)}</h1>
          <p class="muted">${esc(biz.tagline || "")}</p>
        </header>
        <p>${esc(biz.summary || "")}</p>
        <p class="muted">Ordering not enabled for this listing yet.</p>
      `;
      return;
    }
    state.shop = data.shop;
    state.items = Array.isArray(data.items) ? data.items : [];
    state.cart = loadCart(slug);
    document.title = `${data.shop.name} — Order · City of Mandi`;
    if ($("shopTopTitle")) $("shopTopTitle").textContent = data.shop.name;
    try {
      const payRes = await fetch("/api/hub/commerce/payments/config", { cache: "no-store" });
      const payData = await payRes.json().catch(() => ({}));
      if (payRes.ok) state.pay = payData;
    } catch { /* keep defaults */ }
    renderMenu();
    syncCartBar();
    syncPayUi();
    const brand = document.querySelector(".landing-top-brand");
    if (brand && state.shop?.boardId) {
      brand.href = `/#landing-${state.shop.boardId}`;
    }
    if ($("shopTopTitle") && isRentals()) $("shopTopTitle").textContent = "Broker";
  }

  $("shopCartOpen")?.addEventListener("click", openSheet);
  document.querySelectorAll("[data-sheet-close]").forEach((node) => {
    node.addEventListener("click", closeSheet);
  });
  document.querySelectorAll('input[name="payMethod"]').forEach((node) => {
    node.addEventListener("change", syncPayUi);
  });

  async function openRazorpay(rzp) {
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
        prefill: {
          name: $("coName").value.trim(),
          contact: $("coPhone").value.trim(),
        },
        handler(response) { resolve(response); },
        modal: { ondismiss() { reject(new Error("Payment cancelled")); } },
      });
      checkout.open();
    });
  }

  $("shopCheckout")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const err = $("shopOrderError");
    err.hidden = true;
    const { lines, total } = cartTotals();
    if (!lines.length) {
      err.hidden = false;
      err.textContent = "Cart is empty";
      return;
    }
    const payment = selectedPay();
    try {
      const res = await fetch("/api/hub/commerce/orders", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: state.slug,
          name: $("coName").value.trim(),
          phone: $("coPhone").value.trim(),
          address: $("coAddress").value.trim(),
          note: $("coNote").value.trim(),
          fulfillment: isRentals() ? "pickup" : "delivery",
          locality: state.shop?.locality || "mandi",
          payment,
          items: lines.map((l) => ({ id: l.item.id, qty: l.qty })),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Order failed");
      if (data.razorpay) {
        const rzpResp = await openRazorpay(data.razorpay);
        const verify = await fetch(`/api/hub/commerce/orders/${encodeURIComponent(data.order.id)}/pay/verify`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            phone: $("coPhone").value.trim(),
            razorpayOrderId: rzpResp.razorpay_order_id,
            razorpayPaymentId: rzpResp.razorpay_payment_id,
            razorpaySignature: rzpResp.razorpay_signature,
          }),
        });
        const vdata = await verify.json().catch(() => ({}));
        if (!verify.ok) throw new Error(vdata.error || "Payment verification failed");
      }
      state.cart = {};
      saveCart(state.slug, state.cart);
      syncCartBar();
      closeSheet();
      location.href = `/order?id=${encodeURIComponent(data.order.id)}&phone=${encodeURIComponent(data.order.customerPhone || $("coPhone").value.trim())}`;
    } catch (ex) {
      err.hidden = false;
      err.textContent = ex.message;
    }
  });

  boot().catch((ex) => {
    $("bizSection").innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  });
})();
