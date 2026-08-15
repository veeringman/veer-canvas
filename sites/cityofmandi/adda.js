(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    user: null,
    isOperator: false,
    threads: [],
    activeId: null,
    threadMeta: null,
    messages: [],
    sinceId: null,
    cardThemes: [],
    bgStyles: [],
    peopleMode: "dm",
    selectedPeople: [],
    people: [],
    pollTimer: null,
    files: [],
  };

  async function api(path, options = {}) {
    const opts = { credentials: "same-origin", ...options };
    if (opts.body && !(opts.body instanceof FormData)) {
      opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch {
      return iso;
    }
  }

  function setAuthUi() {
    const signed = !!state.user;
    $("addaGuestBanner").hidden = signed;
    $("addaAuthBtn").hidden = signed;
    $("addaLogoutBtn").hidden = !signed;
    $("addaSidebarActions").hidden = !signed;
    $("addaUserChip").hidden = !signed;
    if (signed) $("addaUserChip").textContent = state.user.displayName;
    syncMobileChrome();
  }

  function isMobileAdda() {
    return window.matchMedia("(max-width: 860px)").matches;
  }

  function closeRoomsDrawer() {
    document.body.classList.remove("adda-rooms-open");
    const scrim = $("addaScrim");
    if (scrim) {
      scrim.hidden = true;
      scrim.setAttribute("aria-hidden", "true");
    }
  }

  function openRoomsDrawer() {
    document.body.classList.add("adda-rooms-open");
    const scrim = $("addaScrim");
    if (scrim) {
      scrim.hidden = false;
      scrim.setAttribute("aria-hidden", "false");
    }
  }

  function syncMobileChrome() {
    const inRoom = !!state.activeId && !$("addaRoom").hidden;
    const mobile = isMobileAdda();
    const back = $("addaBackBtn");
    const roomsBtn = $("addaToggleRooms");
    if (back) back.hidden = !(mobile && inRoom);
    if (roomsBtn) roomsBtn.hidden = !(mobile && inRoom);
    if (mobile && !inRoom) closeRoomsDrawer();
  }

  function leaveRoomView() {
    state.activeId = null;
    state.threadMeta = null;
    state.messages = [];
    state.sinceId = null;
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    document.body.classList.remove("adda-room-open");
    closeRoomsDrawer();
    $("addaRoom").hidden = true;
    $("addaEmpty").hidden = false;
    if ($("addaChannelAdmin")) $("addaChannelAdmin").hidden = true;
    if (location.hash) {
      history.replaceState(null, "", location.pathname + location.search);
    }
    renderThreadList();
    syncMobileChrome();
  }

  function fillThemeSelects() {
    const themes = state.cardThemes.length
      ? state.cardThemes
      : [{ id: "plain", label: "Default" }];
    $("addaCardTheme").innerHTML = themes
      .map((t) => `<option value="${esc(t.id)}">${esc(t.label)}</option>`)
      .join("");
    const bgs = state.bgStyles.length
      ? state.bgStyles
      : [{ id: "none", label: "None" }];
    $("addaManageBg").innerHTML = bgs
      .map((t) => `<option value="${esc(t.id)}">${esc(t.label)}</option>`)
      .join("");
  }

  const HIGHLIGHT_ROOM_IDS = [
    "adda_lounge",
    "adda_news",
    "adda_services",
    "adda_jobs",
    "adda_nb_sundernagar",
    "adda_seri_live",
    "adda_dilli_lahore",
  ];
  const HIGHLIGHT_RANK = Object.fromEntries(HIGHLIGHT_ROOM_IDS.map((id, i) => [id, i]));

  function groupThreads(threads) {
    const highlighted = [];
    const publicRooms = [];
    const bridge = [];
    const dms = [];
    const groups = [];
    for (const t of threads) {
      if (HIGHLIGHT_RANK[t.id] != null) highlighted.push(t);
      else if (t.kind === "public") publicRooms.push(t);
      else if (t.kind === "bridge") bridge.push(t);
      else if (t.kind === "dm") dms.push(t);
      else if (t.kind === "group") groups.push(t);
    }
    highlighted.sort((a, b) => (HIGHLIGHT_RANK[a.id] ?? 99) - (HIGHLIGHT_RANK[b.id] ?? 99));
    publicRooms.sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));
    return { highlighted, publicRooms, bridge, dms, groups };
  }

  function renderThreadList() {
    const { highlighted, publicRooms, bridge, dms, groups } = groupThreads(state.threads);
    const parts = [];
    const section = (label, items, { highlight = false } = {}) => {
      if (!items.length) return;
      parts.push(`<p class="adda-list-label">${esc(label)}</p>`);
      for (const t of items) {
        const active = t.id === state.activeId ? " is-active" : "";
        const pin = highlight || HIGHLIGHT_RANK[t.id] != null ? " is-highlight" : "";
        const unread = t.unread ? `<span class="adda-unread">${t.unread}</span>` : "";
        const badge = t.isOfficial ? `<span class="adda-mini-official">Official</span>` : "";
        const preview = t.lastMessage
          ? `<span class="adda-preview">${esc(t.lastMessage.body)}</span>`
          : `<span class="adda-preview muted">${esc(t.subtitle || "")}</span>`;
        const icon = t.iconUrl
          ? `<img class="adda-list-icon" src="${esc(t.iconUrl)}" alt="">`
          : `<span class="adda-list-icon adda-list-icon-fallback">${esc((t.title || "?")[0])}</span>`;
        parts.push(`
          <button type="button" class="adda-thread-btn${pin}${active}" data-thread="${esc(t.id)}">
            ${icon}
            <span class="adda-thread-meta">
              <span class="adda-thread-name">${esc(t.title)} ${badge}</span>
              ${preview}
            </span>
            ${unread}
          </button>
        `);
      }
    };
    section("Highlights", highlighted, { highlight: true });
    section("City rooms", publicRooms);
    section("Neighbourhood", bridge);
    if (state.user) {
      section("Direct", dms);
      section("Private channels", groups);
    }
    $("addaThreadList").innerHTML = parts.join("") || `<p class="muted">No rooms yet.</p>`;
    $("addaThreadList").querySelectorAll("[data-thread]").forEach((btn) => {
      btn.addEventListener("click", () => {
        closeRoomsDrawer();
        openThread(btn.dataset.thread);
      });
    });
  }

  function applyRoomBg(thread) {
    const el = $("addaMessages");
    el.dataset.bg = thread.bgStyle || "none";
    if (thread.bgStyle === "custom" && thread.bgUrl) {
      el.style.backgroundImage = `url(${thread.bgUrl})`;
    } else {
      el.style.backgroundImage = "";
    }
  }

  function renderMessages() {
    const canMod = state.threadMeta?.canModerate;
    const box = $("addaMessages");
    box.innerHTML = state.messages
      .map((m) => {
        if (m.hidden && !canMod) {
          return `<article class="adda-msg is-hidden"><p class="muted">Message hidden</p></article>`;
        }
        const theme = m.cardTheme ? ` theme-${esc(m.cardTheme)}` : "";
        const sys = m.isSystem ? " is-system" : "";
        const atts = (m.attachments || [])
          .map((a) => {
            if ((a.mime || "").startsWith("image/")) {
              return `<a class="adda-att-img" href="${esc(a.url)}" target="_blank" rel="noopener"><img src="${esc(a.url)}" alt=""></a>`;
            }
            return `<a class="adda-att-file" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.filename || "File")}</a>`;
          })
          .join("");
        const mod = canMod
          ? `<div class="adda-mod">
              <button type="button" data-mod="hide" data-id="${esc(m.id)}">Hide</button>
              <button type="button" data-mod="unhide" data-id="${esc(m.id)}">Unhide</button>
              <button type="button" data-mod="delete" data-id="${esc(m.id)}">Delete</button>
              <button type="button" data-mod="pin" data-id="${esc(m.id)}">Pin</button>
            </div>`
          : "";
        const like = state.user
          ? `<button type="button" class="adda-like${m.likedByMe ? " is-on" : ""}" data-like="${esc(m.id)}">♥ ${m.likeCount || 0}</button>`
          : `<span class="adda-like-count">♥ ${m.likeCount || 0}</span>`;
        return `
          <article class="adda-msg${theme}${sys}${m.hidden ? " is-hidden" : ""}">
            <header>
              <strong>${esc(m.authorName || "Adda")}</strong>
              <time>${esc(fmtTime(m.createdAt))}</time>
            </header>
            ${m.body ? `<p>${esc(m.body).replace(/\n/g, "<br>")}</p>` : ""}
            ${atts}
            <footer>${like}${mod}</footer>
          </article>
        `;
      })
      .join("");
    box.querySelectorAll("[data-like]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const data = await api(`/api/adda/messages/${btn.dataset.like}/like`, { method: "POST", body: "{}" });
          const msg = state.messages.find((m) => m.id === btn.dataset.like);
          if (msg) {
            msg.likedByMe = data.likedByMe;
            msg.likeCount = data.likeCount;
            renderMessages();
          }
        } catch (err) {
          alert(err.message);
        }
      });
    });
    box.querySelectorAll("[data-mod]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/adda/messages/${btn.dataset.id}/moderate`, {
            method: "POST",
            body: JSON.stringify({ action: btn.dataset.mod }),
          });
          await openThread(state.activeId, { quiet: true });
        } catch (err) {
          alert(err.message);
        }
      });
    });
    box.scrollTop = box.scrollHeight;
  }

  function renderPinned(pinned) {
    const el = $("addaPinned");
    if (!pinned || pinned.hidden) {
      el.hidden = true;
      el.innerHTML = "";
      return;
    }
    el.hidden = false;
    el.innerHTML = `<strong>Pinned</strong> ${esc((pinned.body || "").slice(0, 160))}`;
  }

  async function loadThreads() {
    const data = await api("/api/adda/threads");
    state.threads = data.threads || [];
    renderThreadList();
  }

  async function openThread(id, { quiet = false } = {}) {
    if (!id) return;
    state.activeId = id;
    location.hash = `room/${id}`;
    document.body.classList.add("adda-room-open");
    closeRoomsDrawer();
    try {
      const data = await api(`/api/adda/threads/${encodeURIComponent(id)}?limit=80`);
      state.threadMeta = data;
      const t = data.thread;
      $("addaEmpty").hidden = true;
      $("addaRoom").hidden = false;
      $("addaRoomTitle").textContent = t.title;
      $("addaRoomSub").textContent = t.subtitle || (t.kind === "dm" ? "Direct message" : t.kind === "bridge" ? "Read-only neighbourhood pulse" : "");
      $("addaOfficialBadge").hidden = !t.isOfficial;
      const icon = $("addaRoomIcon");
      if (t.iconUrl) {
        icon.hidden = false;
        icon.src = t.iconUrl;
      } else {
        icon.hidden = true;
        icon.removeAttribute("src");
      }
      applyRoomBg(t);
      state.messages = data.messages || [];
      state.sinceId = state.messages.length ? state.messages[state.messages.length - 1].id : null;
      renderMessages();
      renderPinned(data.pinned);
      const canPost = !!data.canPost;
      $("addaCompose").hidden = !canPost;
      $("addaReadOnly").hidden = canPost;
      $("addaEscalateBtn").hidden = !data.canEscalate;
      $("addaManage").hidden = !data.canManage;
      if (data.canManage) {
        $("addaManageTitle").value = t.title;
        $("addaManageOfficial").checked = !!t.isOfficial;
        $("addaManageBg").value = t.bgStyle || "none";
        loadMembers(id);
      }
      $("addaChannelAdmin").hidden = !data.canAdminChannel;
      if (data.canAdminChannel) {
        $("addaChanEnabled").checked = t.enabled !== false;
        $("addaChanHidden").checked = !!t.hidden;
      }
      renderThreadList();
      syncMobileChrome();
      if (state.user) {
        api(`/api/adda/threads/${encodeURIComponent(id)}/read`, { method: "POST", body: "{}" }).catch(() => {});
      }
      if (!quiet) startPoll();
    } catch (err) {
      if (!quiet) alert(err.message);
      syncMobileChrome();
    }
  }

  async function loadMembers(id) {
    try {
      const data = await api(`/api/adda/threads/${encodeURIComponent(id)}/members`);
      const box = $("addaMembersBox");
      box.innerHTML = `<p class="adda-list-label">Members</p>` + (data.members || [])
        .map((m) => `<div class="adda-member-row"><span>${esc(m.label)}</span></div>`)
        .join("");
    } catch {
      $("addaMembersBox").innerHTML = "";
    }
  }

  function startPoll() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      if (!state.activeId || document.hidden) return;
      try {
        const q = state.sinceId
          ? `?since=${encodeURIComponent(state.sinceId)}&limit=40`
          : "?limit=80";
        const data = await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}${q}`);
        if (state.sinceId && data.messages?.length) {
          const known = new Set(state.messages.map((m) => m.id));
          for (const m of data.messages) {
            if (!known.has(m.id)) state.messages.push(m);
          }
          state.sinceId = state.messages[state.messages.length - 1].id;
          renderMessages();
        } else if (!state.sinceId) {
          state.messages = data.messages || [];
          state.sinceId = state.messages.length ? state.messages[state.messages.length - 1].id : null;
          renderMessages();
        }
        if (data.thread) {
          const idx = state.threads.findIndex((t) => t.id === data.thread.id);
          if (idx >= 0) state.threads[idx] = { ...state.threads[idx], ...data.thread };
          renderThreadList();
        }
      } catch {
        /* ignore poll errors */
      }
    }, 5000);
  }

  async function refreshSession() {
    const data = await api("/api/adda/session");
    state.user = data.user || null;
    state.isOperator = !!data.isOperator;
    state.cardThemes = data.cardThemes || [];
    state.bgStyles = data.bgStyles || [];
    fillThemeSelects();
    setAuthUi();
  }

  function showAuth(login = false) {
    $("addaAuthError").hidden = true;
    $("addaRegFields").hidden = login;
    $("addaLoginFields").hidden = !login;
    $("addaTabRegister").setAttribute("aria-selected", login ? "false" : "true");
    $("addaTabLogin").setAttribute("aria-selected", login ? "true" : "false");
    $("addaAuthDialog").showModal();
  }

  async function searchPeople(q) {
    const data = await api(`/api/adda/people?q=${encodeURIComponent(q || "")}`);
    state.people = data.people || [];
    const box = $("addaPeopleResults");
    box.innerHTML = state.people
      .map((p) => {
        const on = state.selectedPeople.includes(p.userId) ? " is-on" : "";
        return `<button type="button" class="adda-people-btn${on}" data-uid="${esc(p.userId)}">${esc(p.label)}</button>`;
      })
      .join("") || `<p class="muted">No matches</p>`;
    box.querySelectorAll("[data-uid]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = btn.dataset.uid;
        if (state.peopleMode === "dm") {
          state.selectedPeople = [uid];
        } else if (state.selectedPeople.includes(uid)) {
          state.selectedPeople = state.selectedPeople.filter((x) => x !== uid);
        } else {
          state.selectedPeople = [...state.selectedPeople, uid];
        }
        searchPeople($("addaPeopleQ").value);
        renderSelectedChips();
      });
    });
  }

  function renderSelectedChips() {
    const map = Object.fromEntries(state.people.map((p) => [p.userId, p.label]));
    $("addaPeopleSelected").innerHTML = state.selectedPeople
      .map((id) => `<span class="adda-chip">${esc(map[id] || id)}</span>`)
      .join("");
  }

  function openPeople(mode) {
    state.peopleMode = mode;
    state.selectedPeople = [];
    $("addaPeopleError").hidden = true;
    $("addaPeopleTitle").textContent = mode === "dm" ? "Start a DM" : "New private channel";
    $("addaChannelNameLabel").hidden = mode !== "group";
    $("addaChannelName").value = "";
    $("addaPeopleOk").textContent = mode === "dm" ? "Open" : "Create";
    $("addaPeopleDialog").showModal();
    searchPeople("");
    renderSelectedChips();
  }

  function routeFromHash() {
    const m = location.hash.match(/^#?room\/([A-Za-z0-9._-]+)/);
    if (m) openThread(m[1]);
  }

  /* —— events —— */
  $("addaAuthBtn").addEventListener("click", () => showAuth(false));
  $("addaGuestSignIn").addEventListener("click", () => showAuth(false));
  $("addaTabRegister").addEventListener("click", () => showAuth(false));
  $("addaTabLogin").addEventListener("click", () => showAuth(true));
  $("addaAuthPublisher").addEventListener("click", () => {
    location.href = "/join?next=/adda&mode=login";
  });
  $("addaLogoutBtn").addEventListener("click", async () => {
    await api("/api/adda/logout", { method: "POST", body: "{}" });
    state.user = null;
    setAuthUi();
    await loadThreads();
  });

  $("addaAuthForm").addEventListener("submit", async (ev) => {
    const submitter = ev.submitter;
    if (submitter && submitter.value === "cancel") return;
    ev.preventDefault();
    $("addaAuthError").hidden = true;
    const login = $("addaLoginFields").hidden === false;
    try {
      if (login) {
        await api("/api/adda/login", {
          method: "POST",
          body: JSON.stringify({
            email: $("addaLoginEmail").value.trim(),
            password: $("addaLoginPassword").value,
          }),
        });
      } else {
        await api("/api/adda/register", {
          method: "POST",
          body: JSON.stringify({
            displayName: $("addaRegName").value.trim(),
            email: $("addaRegEmail").value.trim(),
            password: $("addaRegPassword").value,
          }),
        });
      }
      $("addaAuthDialog").close();
      await refreshSession();
      await loadThreads();
      if (state.activeId) await openThread(state.activeId, { quiet: true });
    } catch (err) {
      $("addaAuthError").hidden = false;
      $("addaAuthError").textContent = err.message;
    }
  });

  $("addaNewDmBtn").addEventListener("click", () => openPeople("dm"));
  $("addaNewChannelBtn").addEventListener("click", () => openPeople("group"));
  $("addaPeopleQ").addEventListener("input", () => searchPeople($("addaPeopleQ").value));

  $("addaPeopleForm").addEventListener("submit", async (ev) => {
    const submitter = ev.submitter;
    if (submitter && submitter.value === "cancel") return;
    ev.preventDefault();
    $("addaPeopleError").hidden = true;
    try {
      if (state.peopleMode === "dm") {
        if (!state.selectedPeople[0]) throw new Error("Choose someone");
        const data = await api("/api/adda/dm", {
          method: "POST",
          body: JSON.stringify({ userId: state.selectedPeople[0] }),
        });
        $("addaPeopleDialog").close();
        await loadThreads();
        await openThread(data.thread.id);
      } else {
        const title = $("addaChannelName").value.trim();
        if (!title) throw new Error("Name the channel");
        const data = await api("/api/adda/groups", {
          method: "POST",
          body: JSON.stringify({ title, memberIds: state.selectedPeople }),
        });
        $("addaPeopleDialog").close();
        await loadThreads();
        await openThread(data.thread.id);
      }
    } catch (err) {
      $("addaPeopleError").hidden = false;
      $("addaPeopleError").textContent = err.message;
    }
  });

  $("addaAttach").addEventListener("change", () => {
    state.files = Array.from($("addaAttach").files || []).slice(0, 3);
    $("addaAttachNames").textContent = state.files.map((f) => f.name).join(", ");
  });

  $("addaCompose").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!state.activeId) return;
    $("addaComposeError").hidden = true;
    const body = $("addaBody").value.trim();
    const theme = $("addaCardTheme").value;
    try {
      let data;
      if (state.files.length) {
        const fd = new FormData();
        fd.append("body", body);
        if (theme && theme !== "plain") fd.append("cardTheme", theme);
        state.files.forEach((f) => fd.append("files", f));
        data = await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/messages`, {
          method: "POST",
          body: fd,
        });
      } else {
        data = await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/messages`, {
          method: "POST",
          body: JSON.stringify({ body, cardTheme: theme === "plain" ? "" : theme }),
        });
      }
      $("addaBody").value = "";
      state.files = [];
      $("addaAttach").value = "";
      $("addaAttachNames").textContent = "";
      if (data.message) {
        state.messages.push(data.message);
        state.sinceId = data.message.id;
        renderMessages();
      }
      if (data.heldForReview) {
        $("addaComposeError").hidden = false;
        $("addaComposeError").textContent = data.notice || "Held for review";
      }
      await loadThreads();
    } catch (err) {
      $("addaComposeError").hidden = false;
      $("addaComposeError").textContent = err.message;
    }
  });

  $("addaSaveManage").addEventListener("click", async () => {
    if (!state.activeId) return;
    try {
      await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: $("addaManageTitle").value.trim(),
          isOfficial: $("addaManageOfficial").checked,
          bgStyle: $("addaManageBg").value,
        }),
      });
      const icon = $("addaManageIcon").files?.[0];
      if (icon) {
        const fd = new FormData();
        fd.append("file", icon);
        await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/icon`, { method: "POST", body: fd });
        $("addaManageIcon").value = "";
      }
      const bg = $("addaManageBgFile").files?.[0];
      if (bg) {
        const fd = new FormData();
        fd.append("file", bg);
        await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/background`, { method: "POST", body: fd });
        $("addaManageBgFile").value = "";
      }
      await loadThreads();
      await openThread(state.activeId, { quiet: true });
    } catch (err) {
      alert(err.message);
    }
  });

  $("addaArchiveBtn").addEventListener("click", async () => {
    if (!state.activeId || !confirm("Archive this channel?")) return;
    try {
      await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}`, {
        method: "PATCH",
        body: JSON.stringify({ archive: true }),
      });
      leaveRoomView();
      await loadThreads();
    } catch (err) {
      alert(err.message);
    }
  });

  $("addaLeaveBtn").addEventListener("click", async () => {
    if (!state.activeId || !confirm("Leave this channel?")) return;
    try {
      await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/leave`, {
        method: "POST",
        body: "{}",
      });
      leaveRoomView();
      await loadThreads();
    } catch (err) {
      alert(err.message);
    }
  });

  $("addaEscalateBtn").addEventListener("click", () => {
    $("addaEscError").hidden = true;
    $("addaEscSubject").value = state.threadMeta?.thread?.title
      ? `From Mandi Adda: ${state.threadMeta.thread.title}`
      : "";
    $("addaEscalateDialog").showModal();
  });

  $("addaEscalateForm").addEventListener("submit", async (ev) => {
    const submitter = ev.submitter;
    if (submitter && submitter.value === "cancel") return;
    ev.preventDefault();
    try {
      const data = await api(`/api/adda/threads/${encodeURIComponent(state.activeId)}/escalate`, {
        method: "POST",
        body: JSON.stringify({
          subject: $("addaEscSubject").value.trim(),
          note: $("addaEscNote").value.trim(),
        }),
      });
      $("addaEscalateDialog").close();
      if (data.url) location.href = data.url;
      else alert(data.message || "Sent to Contact Board");
    } catch (err) {
      $("addaEscError").hidden = false;
      $("addaEscError").textContent = err.message;
    }
  });

  $("addaSaveChannelFlags")?.addEventListener("click", async () => {
    if (!state.activeId) return;
    try {
      await api(`/api/board/channels/${encodeURIComponent(state.activeId)}`, {
        method: "PATCH",
        body: JSON.stringify({
          enabled: $("addaChanEnabled").checked,
          hidden: $("addaChanHidden").checked,
        }),
      });
      await openThread(state.activeId);
      await loadThreads();
    } catch (err) {
      alert(err.message);
    }
  });

  $("addaToggleRooms").addEventListener("click", () => {
    if (document.body.classList.contains("adda-rooms-open")) closeRoomsDrawer();
    else openRoomsDrawer();
  });
  $("addaBackBtn")?.addEventListener("click", () => leaveRoomView());
  $("addaScrim")?.addEventListener("click", () => closeRoomsDrawer());
  window.addEventListener("resize", () => syncMobileChrome());
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/^#?room\/([A-Za-z0-9._-]+)/);
    if (m) openThread(m[1]);
    else leaveRoomView();
  });

  (async () => {
    try {
      await refreshSession();
      // Publishers arriving from /join already have session; link if needed
      if (!state.user) {
        try {
          await api("/api/adda/link-publisher", { method: "POST", body: "{}" });
          await refreshSession();
        } catch {
          /* not a publisher */
        }
      }
      await loadThreads();
      routeFromHash();
      syncMobileChrome();
    } catch (err) {
      console.error(err);
      $("addaThreadList").innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  })();
})();
