function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function shortText(value, max = 120) {
  const text = String(value || '').trim();
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function redirectToLogin() {
  window.location.href = `/admin/login?next=${encodeURIComponent('/')}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    redirectToLogin();
    throw new Error('Authentication required');
  }
  if (!response.ok) {
    throw new Error(data.error || response.statusText || `HTTP ${response.status}`);
  }
  return data;
}

async function ensureSession() {
  const data = await api('/api/ops/session');
  const chip = document.getElementById('opsUserChip');
  if (chip) {
    chip.textContent = data.username ? `Signed in as ${data.username}` : 'Signed in';
  }
  const shell = document.getElementById('opsShell');
  if (shell) shell.hidden = false;
  return data;
}

async function refreshObservability() {
  try {
    const data = await api('/api/observability');
    const totals = data.totals || {};
    document.querySelectorAll('[data-obs]').forEach((el) => {
      const key = el.getAttribute('data-obs');
      el.textContent = totals[key] ?? 0;
    });
    const generated = document.getElementById('obsGeneratedAt');
    if (generated) {
      const stamp = (data.generatedAt || '').replace('T', ' ').slice(0, 19);
      generated.textContent = stamp ? `Updated ${stamp}` : 'Updated just now';
    }

    const siteRows = document.getElementById('obsSiteRows');
    if (siteRows) {
      const sites = data.sites || [];
      siteRows.innerHTML = sites.length
        ? sites.map((site) => `
          <tr>
            <td><code>${esc(site.id)}</code>${site.platform ? ' <span class="pill on">Platform</span>' : ''}${site.ops ? ' <span class="pill on">Ops</span>' : ''}</td>
            <td>${esc(site.domain || '—')}</td>
            <td>${site.likes || 0}</td>
            <td>${site.dislikes || 0}</td>
            <td>${site.comments || 0}</td>
            <td>${site.messages || 0}</td>
            <td><span class="pill ${site.unreadMessages ? 'warn' : 'off'}">${site.unreadMessages || 0}</span></td>
            <td>${site.visitors || 0}</td>
            <td>${site.activeTokens || 0}</td>
            <td>${site.visits || 0}</td>
            <td>${site.uniqueIps || 0}</td>
          </tr>`).join('')
        : '<tr><td colspan="11" class="muted">No managed sites found</td></tr>';
    }

    const topRows = document.getElementById('obsTopRows');
    if (topRows) {
      const top = data.topProjects || [];
      topRows.innerHTML = top.length
        ? top.map((row) => `
          <tr>
            <td><code>${esc(row.siteId)}</code></td>
            <td><code>${esc(row.slug)}</code></td>
            <td>${row.likes || 0}</td>
            <td>${row.dislikes || 0}</td>
            <td>${row.commentCount || 0}</td>
            <td>${row.score || 0}</td>
          </tr>`).join('')
        : '<tr><td colspan="6" class="muted">No engagement yet</td></tr>';
    }

    const msgRows = document.getElementById('obsMessageRows');
    if (msgRows) {
      const messages = data.messages || [];
      msgRows.innerHTML = messages.length
        ? messages.map((msg) => `
          <tr class="${msg.read ? '' : 'is-unread'}">
            <td>${esc((msg.createdAt || '').slice(0, 16).replace('T', ' '))}</td>
            <td><code>${esc(msg.siteId)}</code></td>
            <td>${esc(msg.name)}</td>
            <td><a href="mailto:${esc(msg.email)}">${esc(msg.email)}</a></td>
            <td title="${esc(msg.message)}">${esc(shortText(msg.message, 140))}</td>
            <td class="actions">
              ${msg.read
                ? '<span class="pill off">Read</span>'
                : `<button type="button" class="btn ghost compact" data-action="mark-read" data-site="${esc(msg.siteId)}" data-id="${esc(msg.id)}">Mark read</button>`}
            </td>
          </tr>`).join('')
        : '<tr><td colspan="6" class="muted">No contact messages yet</td></tr>';
    }

    const commentRows = document.getElementById('obsCommentRows');
    if (commentRows) {
      const comments = data.comments || [];
      commentRows.innerHTML = comments.length
        ? comments.map((c) => `
          <tr class="${c.hidden ? 'is-hidden-row' : ''}">
            <td>${esc((c.createdAt || '').slice(0, 16).replace('T', ' '))}</td>
            <td><code>${esc(c.siteId)}</code></td>
            <td><code>${esc(c.slug)}</code></td>
            <td>${esc(c.name)}</td>
            <td title="${esc(c.text)}">${esc(shortText(c.text, 140))}</td>
            <td class="actions">
              ${c.hidden
                ? '<span class="pill off">Hidden</span>'
                : `<button type="button" class="btn ghost compact" data-action="hide-comment" data-site="${esc(c.siteId)}" data-slug="${esc(c.slug)}" data-id="${esc(c.id)}">Hide</button>`}
            </td>
          </tr>`).join('')
        : '<tr><td colspan="6" class="muted">No comments yet</td></tr>';
    }

    const visitorRows = document.getElementById('obsVisitorRows');
    if (visitorRows) {
      const visitors = data.visitors || [];
      visitorRows.innerHTML = visitors.length
        ? visitors.map((v) => `
          <tr>
            <td><code>${esc(v.siteId)}</code></td>
            <td>${esc(v.name || '—')}</td>
            <td>${v.email ? `<a href="mailto:${esc(v.email)}">${esc(v.email)}</a>` : '—'}</td>
            <td><code>${esc(v.visitorId || '')}</code></td>
            <td><code>${esc(v.lastIp || '—')}</code></td>
            <td>${v.visitCount || 0}</td>
            <td>${esc((v.lastSeenAt || v.createdAt || '').slice(0, 16).replace('T', ' '))}</td>
          </tr>`).join('')
        : '<tr><td colspan="7" class="muted">No visitors tracked yet</td></tr>';
    }

    const visitRows = document.getElementById('obsVisitRows');
    if (visitRows) {
      const visits = data.visits || [];
      visitRows.innerHTML = visits.length
        ? visits.map((v) => {
          const mode = v.authMode || (v.hasToken ? 'visitor' : 'anonymous');
          const who = v.name || v.email || v.visitorId || '—';
          return `
          <tr>
            <td>${esc((v.at || '').slice(0, 19).replace('T', ' '))}</td>
            <td><code>${esc(v.siteId)}</code></td>
            <td><code>${esc(v.ip || '—')}</code></td>
            <td title="${esc(v.title || '')}"><code>${esc(shortText(v.path || '/', 48))}</code>${v.slug ? ` <span class="pill off">${esc(v.slug)}</span>` : ''}</td>
            <td><span class="pill ${mode === 'anonymous' ? 'off' : 'on'}">${esc(mode)}</span></td>
            <td>${esc(v.device || '—')}</td>
            <td>${esc(v.browser || '—')}</td>
            <td>${esc(v.referrerHost || '(direct)')}</td>
            <td title="${esc(v.visitorId || '')}">${esc(shortText(who, 28))}</td>
          </tr>`;
        }).join('')
        : '<tr><td colspan="9" class="muted">No visits recorded yet</td></tr>';
    }

    const topPathRows = document.getElementById('obsTopPathRows');
    if (topPathRows) {
      const rows = data.topPaths || [];
      topPathRows.innerHTML = rows.length
        ? rows.map((r) => `<tr><td><code>${esc(r.key)}</code></td><td>${r.count || 0}</td></tr>`).join('')
        : '<tr><td colspan="2" class="muted">No path data yet</td></tr>';
    }

    const topReferrerRows = document.getElementById('obsTopReferrerRows');
    if (topReferrerRows) {
      const rows = data.topReferrers || [];
      topReferrerRows.innerHTML = rows.length
        ? rows.map((r) => `<tr><td>${esc(r.key)}</td><td>${r.count || 0}</td></tr>`).join('')
        : '<tr><td colspan="2" class="muted">No referrer data yet</td></tr>';
    }

    const eventRows = document.getElementById('obsVisitorEventRows');
    if (eventRows) {
      const events = data.visitorEvents || [];
      eventRows.innerHTML = events.length
        ? events.map((e) => `
          <tr>
            <td>${esc((e.at || '').slice(0, 16).replace('T', ' '))}</td>
            <td><code>${esc(e.siteId)}</code></td>
            <td>${esc(e.type || '—')}</td>
            <td><code>${esc(e.slug || '—')}</code></td>
            <td>${esc(e.name || '—')}</td>
            <td>${esc(e.email || '—')}</td>
          </tr>`).join('')
        : '<tr><td colspan="6" class="muted">No access events yet</td></tr>';
    }
  } catch (error) {
    if (error.message === 'Authentication required') return;
    const siteRows = document.getElementById('obsSiteRows');
    if (siteRows) {
      siteRows.innerHTML = `<tr><td colspan="11" class="muted">${esc(error.message)}</td></tr>`;
    }
  }
}

async function markMessageRead(siteId, id) {
  try {
    await api(`/api/inbox/contact/${encodeURIComponent(id)}/read`, {
      method: 'POST',
      body: JSON.stringify({ siteId }),
    });
    await refreshObservability();
  } catch (error) {
    if (error.message !== 'Authentication required') {
      alert(error.message || 'Failed to mark read');
    }
  }
}

async function hideObservabilityComment(siteId, slug, id) {
  if (!confirm(`Hide comment on ${slug}?`)) return;
  try {
    await api('/api/inbox/comments/hide', {
      method: 'POST',
      body: JSON.stringify({ siteId, slug, id }),
    });
    await refreshObservability();
  } catch (error) {
    if (error.message !== 'Authentication required') {
      alert(error.message || 'Failed to hide comment');
    }
  }
}

document.getElementById('refreshAllBtn')?.addEventListener('click', refreshObservability);

document.querySelectorAll('.obs-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.obs-tab').forEach((el) => el.classList.toggle('is-active', el === tab));
    const which = tab.dataset.tab;
    const messagesPanel = document.getElementById('obsMessagesPanel');
    const commentsPanel = document.getElementById('obsCommentsPanel');
    const visitsPanel = document.getElementById('obsVisitsPanel');
    const visitorsPanel = document.getElementById('obsVisitorsPanel');
    const visitorEventsPanel = document.getElementById('obsVisitorEventsPanel');
    if (messagesPanel) messagesPanel.hidden = which !== 'messages';
    if (commentsPanel) commentsPanel.hidden = which !== 'comments';
    if (visitsPanel) visitsPanel.hidden = which !== 'visits';
    if (visitorsPanel) visitorsPanel.hidden = which !== 'visitors';
    if (visitorEventsPanel) visitorEventsPanel.hidden = which !== 'visitorEvents';
  });
});

document.addEventListener('click', (event) => {
  const btn = event.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.getAttribute('data-action');
  if (action === 'mark-read') {
    markMessageRead(btn.getAttribute('data-site'), btn.getAttribute('data-id'));
  } else if (action === 'hide-comment') {
    hideObservabilityComment(
      btn.getAttribute('data-site'),
      btn.getAttribute('data-slug'),
      btn.getAttribute('data-id'),
    );
  }
});

(async function boot() {
  try {
    await ensureSession();
    await refreshObservability();
  } catch (error) {
    if (error.message !== 'Authentication required') {
      redirectToLogin();
    }
  }
})();
