/** Geolocation + map for preferred locality (live / immediate boards). */
(() => {
  const COORDS_KEY = "hub_geo_coords";
  const AUTO_TS_KEY = "hub_geo_auto_ts";
  const MANUAL_TS_KEY = "hub_geo_manual_ts";
  const AUTO_TTL_MS = 30 * 60 * 1000; // re-probe every 30 min for live boards

  const LIVE_BOARDS = new Set(
    (window.HubPrefs?.BOARDS || [])
      .filter((b) => b.live)
      .map((b) => b.id)
      .concat(["labour", "taxi", "food", "grocery", "haulage", "vehicle", "doctor", "tours", "home"])
  );

  function localities() {
    return window.HubPrefs?.LOCALITIES || [];
  }

  function haversineKm(lat1, lng1, lat2, lng2) {
    const r = 6371;
    const toRad = (d) => (d * Math.PI) / 180;
    const p1 = toRad(lat1);
    const p2 = toRad(lat2);
    const dphi = toRad(lat2 - lat1);
    const dlmb = toRad(lng2 - lng1);
    const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dlmb / 2) ** 2;
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function nearestLocality(lat, lng) {
    const rows = localities().filter((l) => Number.isFinite(l.lat) && Number.isFinite(l.lng));
    if (!rows.length) return null;
    let best = null;
    let bestD = Infinity;
    rows.forEach((row) => {
      const d = haversineKm(lat, lng, row.lat, row.lng);
      if (d < bestD) {
        bestD = d;
        best = row;
      }
    });
    if (!best) return null;
    return { ...best, distanceKm: Math.round(bestD * 100) / 100 };
  }

  function saveCoords(lat, lng) {
    try {
      localStorage.setItem(COORDS_KEY, JSON.stringify({
        lat, lng, at: Date.now(),
      }));
    } catch { /* ignore */ }
  }

  function readCoords() {
    try {
      const raw = JSON.parse(localStorage.getItem(COORDS_KEY) || "null");
      if (!raw || !Number.isFinite(raw.lat) || !Number.isFinite(raw.lng)) return null;
      return raw;
    } catch {
      return null;
    }
  }

  function getPosition(options = {}) {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Location not supported on this device"));
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 12000,
        maximumAge: 60_000,
        ...options,
      });
    });
  }

  async function detectNearest(options = {}) {
    const pos = await getPosition(options);
    const lat = pos.coords.latitude;
    const lng = pos.coords.longitude;
    saveCoords(lat, lng);
    let nearest = nearestLocality(lat, lng);
    try {
      const res = await fetch(
        `/api/hub/localities/nearest?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`,
        { cache: "no-store" }
      );
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.locality?.id) {
        nearest = {
          id: data.locality.id,
          label: data.locality.label,
          labelHi: data.locality.labelHi || "",
          lat: data.locality.lat,
          lng: data.locality.lng,
          distanceKm: data.locality.distanceKm,
        };
      }
    } catch { /* offline / API missing — use client nearest */ }
    return { lat, lng, nearest, accuracy: pos.coords.accuracy };
  }

  function applyLocality(locId, { manual = false } = {}) {
    const HP = window.HubPrefs;
    if (!HP || !locId) return null;
    const prefs = HP.readPrefs();
    const remembered = HP.rememberPrefs(prefs.board, locId);
    try {
      localStorage.setItem(manual ? MANUAL_TS_KEY : AUTO_TS_KEY, String(Date.now()));
    } catch { /* ignore */ }
    document.dispatchEvent(new CustomEvent("hub:locality", {
      detail: { locality: remembered.loc, manual },
    }));
    return remembered.loc;
  }

  function recentlyManual(ms = AUTO_TTL_MS) {
    try {
      const ts = Number(localStorage.getItem(MANUAL_TS_KEY) || 0);
      return ts && (Date.now() - ts) < ms;
    } catch {
      return false;
    }
  }

  function recentlyAuto(ms = AUTO_TTL_MS) {
    try {
      const ts = Number(localStorage.getItem(AUTO_TS_KEY) || 0);
      return ts && (Date.now() - ts) < ms;
    } catch {
      return false;
    }
  }

  /** For live/immediate boards: detect GPS and set preferred locality. */
  async function autoPreferForLive(boardId, { force = false } = {}) {
    const id = window.HubPrefs?.normalizeBoard(boardId) || boardId;
    if (!LIVE_BOARDS.has(id)) return null;
    if (!force && recentlyManual()) return window.HubPrefs?.readPrefs().loc || null;
    if (!force && recentlyAuto()) return window.HubPrefs?.readPrefs().loc || null;
    try {
      const hit = await detectNearest();
      if (hit?.nearest?.id) {
        applyLocality(hit.nearest.id, { manual: false });
        return hit.nearest;
      }
    } catch {
      return null;
    }
    return null;
  }

  function ensureLeaflet() {
    return new Promise((resolve, reject) => {
      if (window.L) {
        resolve(window.L);
        return;
      }
      if (!document.getElementById("hub-leaflet-css")) {
        const link = document.createElement("link");
        link.id = "hub-leaflet-css";
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
      }
      const existing = document.getElementById("hub-leaflet-js");
      if (existing) {
        existing.addEventListener("load", () => resolve(window.L));
        existing.addEventListener("error", () => reject(new Error("Map failed to load")));
        return;
      }
      const script = document.createElement("script");
      script.id = "hub-leaflet-js";
      script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Map failed to load"));
      document.head.appendChild(script);
    });
  }

  /**
   * Mount a small map + “Use my location” under a locality select.
   * opts: { mapId, selectId, statusId, locateBtnId, pickerApi }
   */
  async function mountLocalityMap(opts = {}) {
    const mapEl = document.getElementById(opts.mapId || "hubLocalityMap");
    const select = document.getElementById(opts.selectId || "regLocality");
    const status = document.getElementById(opts.statusId || "hubGeoStatus");
    const locateBtn = document.getElementById(opts.locateBtnId || "hubLocateBtn");
    if (!mapEl || !select) return null;

    let L;
    try {
      L = await ensureLeaflet();
    } catch (err) {
      if (status) status.textContent = err.message || "Map unavailable";
      return null;
    }

    const HP = window.HubPrefs;
    const currentId = HP?.normalizeLocality(select.value) || "mandi";
    const seed = localities().find((l) => l.id === currentId) || localities()[0];
    const map = L.map(mapEl, { zoomControl: true, attributionControl: true })
      .setView([seed?.lat || 31.7083, seed?.lng || 76.9318], 10);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap",
    }).addTo(map);

    const markers = {};
    localities().forEach((loc) => {
      const m = L.circleMarker([loc.lat, loc.lng], {
        radius: 7,
        color: loc.id === currentId ? "#163c44" : "#5a7a82",
        weight: 2,
        fillColor: loc.id === currentId ? "#c45c26" : "#9eb8bf",
        fillOpacity: 0.85,
      }).addTo(map);
      m.bindTooltip(loc.label);
      m.on("click", () => {
        select.value = loc.id;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        applyLocality(loc.id, { manual: true });
        if (opts.pickerApi?.set) opts.pickerApi.set(loc.id);
        if (status) status.textContent = `Preferred: ${loc.label}`;
        highlight(loc.id);
      });
      markers[loc.id] = m;
    });

    let trackMarker = null;

    function highlight(id) {
      Object.entries(markers).forEach(([key, m]) => {
        m.setStyle({
          color: key === id ? "#163c44" : "#5a7a82",
          fillColor: key === id ? "#c45c26" : "#9eb8bf",
        });
      });
      const loc = localities().find((l) => l.id === id);
      if (loc) map.panTo([loc.lat, loc.lng]);
    }

    select.addEventListener("change", () => {
      const id = HP?.normalizeLocality(select.value) || select.value;
      applyLocality(id, { manual: true });
      if (opts.pickerApi?.set) opts.pickerApi.set(id);
      highlight(id);
      const loc = localities().find((l) => l.id === id);
      if (status && loc) status.textContent = `Preferred: ${loc.label}`;
    });

    async function locate() {
      if (status) status.textContent = "Finding your location…";
      if (locateBtn) locateBtn.disabled = true;
      try {
        const hit = await detectNearest({ enableHighAccuracy: true, maximumAge: 0 });
        if (trackMarker) map.removeLayer(trackMarker);
        trackMarker = L.marker([hit.lat, hit.lng]).addTo(map);
        trackMarker.bindPopup("You are here").openPopup();
        map.setView([hit.lat, hit.lng], 12);
        if (hit.nearest?.id) {
          select.value = hit.nearest.id;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          applyLocality(hit.nearest.id, { manual: true });
          if (opts.pickerApi?.set) opts.pickerApi.set(hit.nearest.id);
          highlight(hit.nearest.id);
          if (status) {
            status.textContent = `Nearest: ${hit.nearest.label} (~${hit.nearest.distanceKm} km)`;
          }
        }
      } catch (err) {
        if (status) {
          status.textContent = err?.code === 1
            ? "Location permission denied — pick a locality on the map."
            : (err.message || "Could not read location");
        }
      } finally {
        if (locateBtn) locateBtn.disabled = false;
      }
    }

    locateBtn?.addEventListener("click", (event) => {
      event.preventDefault();
      locate();
    });

    // Fit markers once
    try {
      const group = L.featureGroup(Object.values(markers));
      map.fitBounds(group.getBounds().pad(0.15));
    } catch { /* ignore */ }

    setTimeout(() => map.invalidateSize(), 80);

    return { map, locate, highlight };
  }

  window.HubGeo = {
    LIVE_BOARDS,
    nearestLocality,
    detectNearest,
    applyLocality,
    autoPreferForLive,
    mountLocalityMap,
    readCoords,
    saveCoords,
    recentlyManual,
    recentlyAuto,
  };
})();
