(() => {
  const params = new URLSearchParams(location.search);
  const $ = (id) => document.getElementById(id);
  const nextRaw = (params.get("next") || "").trim();
  const HP = () => window.HubPrefs;
  const I18n = () => window.HubI18n;

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

  function contentLangValue(form) {
    const id = form === "login" ? "loginContentLang" : "regContentLang";
    const el = $(id);
    return I18n()?.normalizeLang(el?.value) || HP()?.readContentLang?.() || "en";
  }

  function bootPrefs() {
    const prefs = HP().readPrefs();
    const { board, loc, lang } = prefs;
    const fromNext = (() => {
      const hit = (HP().BOARDS || []).find((b) =>
        nextRaw.includes(`landing-${b.id}`)
        || nextRaw.includes(`/${b.id}`)
        || (b.id === "food" && (nextRaw.includes("demo-rasoi") || nextRaw.includes("/merchant")))
        || (b.id === "grocery" && nextRaw.includes("kirana"))
        || (b.id === "haulage" && nextRaw.includes("tempo"))
        || (b.id === "experts" && nextRaw.includes("sme"))
      );
      if (hit) return hit.id;
      if (nextRaw.includes("landing-news") || nextRaw.includes("landing-spotlight") || nextRaw.includes("landing-places")) {
        return "city";
      }
      if (nextRaw.includes("/partner")) {
        try {
          const q = new URL(nextRaw, location.origin).searchParams.get("board");
          if (q) return HP().normalizeBoard(q);
        } catch { /* ignore */ }
      }
      return board;
    })();
    HP().fillBoardSelects(["regPreferredBoard", "loginPreferredBoard"], fromNext);
    HP().fillLocalitySelects(["regLocality", "loginLocality"], loc);
    HP().mountBoardPicker("regBoardPicker", "regPreferredBoard", fromNext);
    HP().mountBoardPicker("loginBoardPicker", "loginPreferredBoard", fromNext);
    const regPicker = HP().mountLocalityPicker?.("regLocPicker", "regLocality", loc);
    HP().mountLocalityPicker?.("loginLocPicker", "loginLocality", loc);

    $("regContentLang").value = lang;
    $("loginContentLang").value = lang;
    I18n()?.mountLangPicker?.("regLangPicker", "regContentLang", lang);
    I18n()?.mountLangPicker?.("loginLangPicker", "loginContentLang", lang);
    I18n()?.setLang?.(lang, { silent: true });
    I18n()?.applyStaticI18n?.(lang);

    const Geo = window.HubGeo;
    if (Geo?.mountLocalityMap) {
      Geo.mountLocalityMap({
        mapId: "hubLocalityMap",
        selectId: "regLocality",
        statusId: "hubGeoStatus",
        locateBtnId: "hubLocateBtn",
        pickerApi: regPicker,
      }).catch(() => {});
    }
    if (Geo?.autoPreferForLive) {
      Geo.autoPreferForLive(fromNext).then((nearest) => {
        if (!nearest?.id) return;
        HP().fillLocalitySelects(["regLocality", "loginLocality"], nearest.id);
        regPicker?.set?.(nearest.id);
        HP().mountLocalityPicker?.("loginLocPicker", "loginLocality", nearest.id);
        const status = $("hubGeoStatus");
        if (status) {
          const label = I18n()?.t?.("detected") || "Detected";
          status.textContent = `${label}: ${nearest.label} (~${nearest.distanceKm} km)`;
        }
      }).catch(() => {});
    }
  }

  async function syncProviderPrefs(preferred, locality, contentLang) {
    try {
      const sess = await api("/api/hub/providers/session");
      if (!sess.authenticated) return;
      await api("/api/hub/providers/me", {
        method: "PATCH",
        body: JSON.stringify({
          preferredBoard: preferred,
          homeLocality: locality,
          contentLang,
        }),
      });
    } catch {
      /* publisher-only accounts skip provider prefs */
    }
  }

  function showLogin(on) {
    $("registerForm").hidden = on;
    $("loginForm").hidden = !on;
    $("tabRegister").setAttribute("aria-selected", on ? "false" : "true");
    $("tabLogin").setAttribute("aria-selected", on ? "true" : "false");
    $("tabRegister").classList.toggle("is-active", !on);
    $("tabLogin").classList.toggle("is-active", on);
  }

  function fail(err) {
    $("authError").hidden = false;
    $("authError").textContent = err.message;
  }

  $("tabRegister").addEventListener("click", () => showLogin(false));
  $("tabLogin").addEventListener("click", () => showLogin(true));
  if (params.get("mode") === "login") showLogin(true);
  else showLogin(false);

  $("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      const preferred = HP().normalizeBoard($("regPreferredBoard").value);
      const locality = HP().normalizeLocality($("regLocality").value);
      const contentLang = contentLangValue("register");
      HP().rememberPrefs(preferred, locality, contentLang);
      I18n()?.setLang?.(contentLang);
      await api("/api/hub/register", {
        method: "POST",
        body: JSON.stringify({
          name: $("regName").value.trim(),
          email: $("regEmail").value.trim(),
          password: $("regPassword").value,
          preferredBoard: preferred,
          homeLocality: locality,
          contentLang,
        }),
      });
      await syncProviderPrefs(preferred, locality, contentLang);
      location.href = HP().resolveDestination(preferred, nextRaw);
    } catch (err) { fail(err); }
  });

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      const preferred = HP().normalizeBoard($("loginPreferredBoard").value);
      const locality = HP().normalizeLocality($("loginLocality").value);
      const contentLang = contentLangValue("login");
      HP().rememberPrefs(preferred, locality, contentLang);
      I18n()?.setLang?.(contentLang);
      await api("/api/hub/publisher/login", {
        method: "POST",
        body: JSON.stringify({
          email: $("loginEmail").value.trim(),
          password: $("loginPassword").value,
          preferredBoard: preferred,
          homeLocality: locality,
          contentLang,
        }),
      });
      await syncProviderPrefs(preferred, locality, contentLang);
      location.href = HP().resolveDestination(preferred, nextRaw);
    } catch (err) { fail(err); }
  });

  document.addEventListener("hub:lang", () => {
    I18n()?.applyStaticI18n?.(I18n().readLang());
  });

  function whenReady(fn) {
    if (window.HubPrefs && window.HubI18n) fn();
    else setTimeout(() => whenReady(fn), 20);
  }

  whenReady(() => {
    bootPrefs();
    api("/api/hub/publisher/session").then(async (sess) => {
      if (!sess.authenticated) return;
      let preferred = HP().readPrefs().board;
      try {
        const publisherLang = sess.publisher?.contentLang;
        if (publisherLang) I18n()?.setLang?.(publisherLang);
        const provider = await api("/api/hub/providers/session");
        if (provider.authenticated && provider.provider?.preferredBoard) {
          preferred = HP().normalizeBoard(provider.provider.preferredBoard);
          HP().rememberPrefs(
            preferred,
            provider.provider.homeLocality || HP().readPrefs().loc,
            provider.provider.contentLang || publisherLang || HP().readContentLang(),
          );
          if (provider.provider.contentLang) I18n()?.setLang?.(provider.provider.contentLang);
        }
      } catch {
        /* ignore */
      }
      location.replace(HP().resolveDestination(preferred, nextRaw));
    }).catch(() => {});
  });
})();
