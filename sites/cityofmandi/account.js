(() => {
  const $ = (id) => document.getElementById(id);
  const HP = () => window.HubPrefs;
  const I18n = () => window.HubI18n;
  const ROLE_IDS = [
    ["roleLabour", "labour"],
    ["roleTaxi", "taxi"],
    ["roleExperts", "experts"],
    ["roleVehicle", "vehicle"],
    ["roleDoctor", "doctor"],
    ["roleTours", "tours"],
    ["roleTutors", "tutors"],
    ["roleHome", "home"],
  ];

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

  function mountGeo(loc) {
    const picker = HP().mountLocalityPicker?.("prefsLocPicker", "homeLocality", loc);
    window.HubGeo?.mountLocalityMap?.({
      mapId: "hubLocalityMap",
      selectId: "homeLocality",
      statusId: "hubGeoStatus",
      locateBtnId: "hubLocateBtn",
      pickerApi: picker,
    }).catch(() => {});
  }

  function mountLang(lang) {
    const el = $("contentLang");
    if (el) el.value = lang;
    I18n()?.mountLangPicker?.("prefsLangPicker", "contentLang", lang);
    I18n()?.setLang?.(lang, { silent: true });
    I18n()?.applyStaticI18n?.(lang);
  }

  async function boot() {
    const prefs = HP().readPrefs();
    HP().fillBoardSelects(["preferredBoard"], prefs.board);
    HP().fillLocalitySelects(["homeLocality"], prefs.loc);
    HP().mountBoardPicker("prefsBoardPicker", "preferredBoard", prefs.board);
    mountGeo(prefs.loc);
    mountLang(prefs.lang || I18n()?.readLang?.() || "en");
    const toggle = $("myMandiToggle");
    if (toggle) toggle.checked = HP().isMyMandiOn();

    let sess = null;
    try {
      sess = await api("/api/hub/providers/session");
    } catch {
      sess = { authenticated: false };
    }

    if (!sess.authenticated) {
      try {
        const pub = await api("/api/hub/publisher/session");
        if (pub.authenticated) {
          $("prefsNeedLogin").hidden = true;
          $("prefsForm").hidden = false;
          $("prefsHello").textContent = `${pub.publisher?.name || "Publisher"} · local prefs`;
          $("prefsRoles").hidden = true;
          if (pub.publisher?.contentLang) mountLang(pub.publisher.contentLang);
          return;
        }
      } catch { /* ignore */ }
      $("prefsForm").hidden = true;
      $("prefsNeedLogin").hidden = false;
      return;
    }

    $("prefsNeedLogin").hidden = true;
    $("prefsForm").hidden = false;
    const p = sess.provider || {};
    $("prefsHello").textContent = `${p.name || "Provider"} · ${p.phone || ""}`;
    const preferred = HP().normalizeBoard(p.preferredBoard || prefs.board);
    $("preferredBoard").value = preferred;
    HP().mountBoardPicker("prefsBoardPicker", "preferredBoard", preferred);
    const loc = HP().normalizeLocality(p.homeLocality || prefs.loc);
    HP().fillLocalitySelects(["homeLocality"], loc);
    mountGeo(loc);
    mountLang(p.contentLang || prefs.lang || "en");
    const roles = new Set((p.roles || []).map((r) => r.boardId));
    ROLE_IDS.forEach(([elId, boardId]) => {
      const el = $(elId);
      if (!el) return;
      el.checked = roles.has(boardId) || (boardId === "labour" && !roles.size);
    });
  }

  $("prefsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("prefsError").hidden = true;
    $("prefsStatus").textContent = "";
    const preferred = HP().normalizeBoard($("preferredBoard").value);
    const locality = HP().normalizeLocality($("homeLocality").value);
    const contentLang = I18n()?.normalizeLang($("contentLang")?.value) || "en";
    const myMandi = !!$("myMandiToggle")?.checked;
    HP().rememberPrefs(preferred, locality, contentLang);
    HP().setMyMandi(myMandi);
    I18n()?.setLang?.(contentLang);
    try {
      window.HubGeo?.applyLocality?.(locality, { manual: true });
      const providerSess = await api("/api/hub/providers/session");
      if (providerSess.authenticated) {
        const roles = ROLE_IDS.map(([elId, boardId]) => ({
          boardId,
          active: !!$(elId)?.checked,
        }));
        await api("/api/hub/providers/me", {
          method: "PATCH",
          body: JSON.stringify({
            preferredBoard: preferred,
            homeLocality: locality,
            contentLang,
            roles,
          }),
        });
      }
      $("prefsStatus").textContent = "Saved.";
      setTimeout(() => {
        location.href = HP().boardHome(preferred);
      }, 500);
    } catch (err) {
      try {
        const pub = await api("/api/hub/publisher/session");
        if (pub.authenticated) {
          $("prefsStatus").textContent = "Saved on this device.";
          setTimeout(() => { location.href = HP().boardHome(preferred); }, 500);
          return;
        }
      } catch { /* fall through */ }
      $("prefsError").hidden = false;
      $("prefsError").textContent = err.message;
    }
  });

  function whenReady(fn) {
    if (window.HubPrefs && window.HubI18n) fn();
    else setTimeout(() => whenReady(fn), 20);
  }
  whenReady(() => boot().catch(() => {
    $("prefsForm").hidden = true;
    $("prefsNeedLogin").hidden = false;
  }));
})();
