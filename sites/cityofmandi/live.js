(() => {
  const POLL_MS = 20000;
  const FOCUS_MS = 4000;
  let lastRev = "";
  let lastParts = {};
  let timer = null;
  let inFlight = false;

  function changedParts(next) {
    const parts = next && typeof next === "object" ? next : {};
    const keys = new Set([...Object.keys(lastParts), ...Object.keys(parts)]);
    const changed = [];
    keys.forEach((key) => {
      if ((lastParts[key] || "") !== (parts[key] || "")) changed.push(key);
    });
    return changed;
  }

  async function tick({ force = false } = {}) {
    if (inFlight) return;
    if (!force && document.hidden) return;
    inFlight = true;
    try {
      const res = await fetch("/api/hub/changes", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!res.ok) return;
      const data = await res.json().catch(() => ({}));
      if (!data.ok || !data.rev) return;
      const parts = data.parts || {};
      if (!lastRev) {
        lastRev = data.rev;
        lastParts = { ...parts };
        return;
      }
      if (data.rev === lastRev) return;
      const changed = changedParts(parts);
      lastRev = data.rev;
      lastParts = { ...parts };
      if (!changed.length) return;
      document.dispatchEvent(
        new CustomEvent("city:live", {
          detail: { rev: data.rev, parts, changed },
        })
      );
    } catch {
      /* keep last known rev; try again next interval */
    } finally {
      inFlight = false;
    }
  }

  function schedule() {
    if (timer) window.clearInterval(timer);
    timer = window.setInterval(() => tick(), POLL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick({ force: true });
  });
  window.addEventListener("focus", () => {
    window.setTimeout(() => tick({ force: true }), FOCUS_MS);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      tick({ force: true });
      schedule();
    });
  } else {
    tick({ force: true });
    schedule();
  }
})();
