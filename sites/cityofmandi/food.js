(() => {
  const BOARDS = [
    {
      id: "food",
      listId: "landingFoodList",
      emptyTitle: "Kitchens coming online",
      emptyMeta: "Food · खाना",
      cta: "Order · ऑर्डर",
    },
    {
      id: "grocery",
      listId: "landingGroceryList",
      emptyTitle: "Kiranas coming online",
      emptyMeta: "Grocery · किराना",
      cta: "Order · ऑर्डर",
    },
    {
      id: "hardware",
      listId: "landingHardwareList",
      emptyTitle: "Hardware counters coming online",
      emptyMeta: "Hardware · हार्डवेयर",
      cta: "Order · ऑर्डर",
    },
    {
      id: "haulage",
      listId: "landingHaulageList",
      emptyTitle: "Tempo & truck desks coming online",
      emptyMeta: "Haulage · ढुलाई",
      cta: "Book · बुक करें",
    },
    {
      id: "rentals",
      listId: "landingRentalsList",
      emptyTitle: "Brokers coming online",
      emptyMeta: "Rent / Sell · किराये / बिक्री",
      cta: "Listings · सूची",
      noun: "listings",
    },
  ];

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadBoard(board) {
    const list = document.getElementById(board.listId);
    if (!list) return;
    try {
      const res = await fetch(`/api/hub/commerce/shops?board=${encodeURIComponent(board.id)}`, {
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Failed");
      const shops = data.shops || [];
      if (!shops.length) {
        list.innerHTML = `
          <article class="landing-card">
            <p class="landing-meta">${esc(board.emptyMeta)}</p>
            <strong>${esc(board.emptyTitle)}</strong>
            <p>${board.id === "rentals"
              ? "Brokers register as a business on the merchant desk, then publish rent/sale listings by category."
              : "Merchants open a shop from the merchant desk. Demo listings appear after deploy."}</p>
            <p class="landing-contact"><a href="/merchant">Merchant desk · व्यापारी डेस्क</a></p>
          </article>`;
        return;
      }
      const countLabel = board.noun || "items";
      list.innerHTML = shops.map((shop) => `
        <article class="landing-card food-shop-card${shop.featured ? " is-featured" : ""}">
          <p class="landing-meta">${esc(shop.category || board.id)} · ${shop.openNow ? "Open" : "Closed"}${shop.featured ? " · Sponsored" : ""}</p>
          <strong>${esc(shop.name)}</strong>
          <p>${esc(shop.tagline || shop.summary || "")}</p>
          <p class="muted">${shop.itemCount || 0} ${esc(countLabel)} · ${esc(shop.locality || "mandi")}</p>
          <p class="landing-contact">
            <a class="btn primary compact" href="/b/${encodeURIComponent(shop.slug)}">${esc(board.cta)}</a>
          </p>
        </article>
      `).join("");
    } catch {
      /* keep placeholder */
    }
  }

  function boot() {
    BOARDS.forEach((board) => {
      loadBoard(board);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
