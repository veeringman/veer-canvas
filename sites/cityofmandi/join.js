(() => {
  const params = new URLSearchParams(location.search);
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

  function showLogin(on) {
    $("registerForm").hidden = on;
    $("loginForm").hidden = !on;
    $("tabRegister").setAttribute("aria-selected", on ? "false" : "true");
    $("tabLogin").setAttribute("aria-selected", on ? "true" : "false");
  }

  function fail(err) {
    $("authError").hidden = false;
    $("authError").textContent = err.message;
  }

  $("tabRegister").addEventListener("click", () => showLogin(false));
  $("tabLogin").addEventListener("click", () => showLogin(true));
  if (params.get("mode") === "login") showLogin(true);

  $("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      await api("/api/hub/register", {
        method: "POST",
        body: JSON.stringify({
          name: $("regName").value.trim(),
          email: $("regEmail").value.trim(),
          password: $("regPassword").value,
        }),
      });
      location.href = "/publish";
    } catch (err) { fail(err); }
  });

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("authError").hidden = true;
    try {
      await api("/api/hub/publisher/login", {
        method: "POST",
        body: JSON.stringify({
          email: $("loginEmail").value.trim(),
          password: $("loginPassword").value,
        }),
      });
      location.href = "/publish";
    } catch (err) { fail(err); }
  });

  api("/api/hub/publisher/session").then((sess) => {
    if (sess.authenticated) location.replace("/publish");
  }).catch(() => {});
})();
