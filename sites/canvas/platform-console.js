const KNOWN_INTEGRATIONS = [
  'contact', 'engagement', 'github-sync', 'auth', 'api-backend', 'analytics',
];

const state = {
  sites: [],
  templates: [],
  step: 0,
  editingId: null,
  selectedTemplateId: 'catalog-static',
  integrationsCatalog: KNOWN_INTEGRATIONS,
};

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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

function showView(name) {
  document.querySelectorAll('.view-panel').forEach((el) => {
    el.hidden = el.id !== `view-${name}`;
  });
  document.querySelectorAll('.studio-tab').forEach((tab) => {
    tab.classList.toggle('is-active', tab.dataset.view === name);
  });
}

function statusPill(status) {
  const map = {
    defined: 'off',
    authoring: 'on',
    published: 'on',
    disabled: 'warn',
    deleted: 'off',
  };
  return `<span class="pill ${map[status] || 'off'}">${esc(status || '—')}</span>`;
}

function parseRepos(text) {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split('|').map((p) => p.trim());
      return {
        name: parts[0] || '',
        url: parts[1] || '',
        role: (parts[2] || 'content').toLowerCase(),
      };
    });
}

function formatRepos(repos) {
  if (!Array.isArray(repos) || !repos.length) return '';
  return repos.map((r) => `${r.name || ''} | ${r.url || ''} | ${r.role || 'content'}`).join('\n');
}

function selectedIntegrations() {
  return [...document.querySelectorAll('#integrationsGrid input:checked')].map((el) => el.value);
}

function setWizardStep(step) {
  state.step = step;
  document.querySelectorAll('.wizard-step').forEach((el) => {
    el.classList.toggle('is-active', Number(el.dataset.step) === step);
  });
  document.querySelectorAll('.wizard-pane').forEach((pane) => {
    pane.hidden = Number(pane.dataset.pane) !== step;
  });
  const back = document.getElementById('wizardBackBtn');
  const next = document.getElementById('wizardNextBtn');
  const submit = document.getElementById('wizardSubmitBtn');
  if (back) back.hidden = step === 0;
  if (next) next.hidden = step === 4;
  if (submit) {
    submit.hidden = step !== 4;
    submit.textContent = state.editingId ? 'Save changes' : 'Create website';
  }
  if (step === 4) renderReview();
}

function renderIntegrations(selected = ['contact', 'engagement', 'github-sync']) {
  const grid = document.getElementById('integrationsGrid');
  if (!grid) return;
  const catalog = state.integrationsCatalog.length ? state.integrationsCatalog : KNOWN_INTEGRATIONS;
  grid.innerHTML = catalog.map((key) => `
    <label class="check-chip">
      <input type="checkbox" value="${esc(key)}" ${selected.includes(key) ? 'checked' : ''}/>
      <span>${esc(key)}</span>
    </label>
  `).join('');
}

function templatesForType(siteType) {
  return (state.templates || []).filter((t) => {
    const types = t.siteTypes || [];
    return !types.length || types.includes(siteType);
  });
}

function renderTemplatePicker() {
  const siteType = document.querySelector('input[name="siteType"]:checked')?.value || 'responsive';
  const list = templatesForType(siteType);
  if (!list.find((t) => t.id === state.selectedTemplateId) && list[0]) {
    state.selectedTemplateId = list[0].id;
  }
  const host = document.getElementById('templatePicker');
  if (!host) return;
  host.innerHTML = list.length
    ? list.map((t) => `
      <label class="template-card ${t.id === state.selectedTemplateId ? 'is-selected' : ''}">
        <input type="radio" name="templateId" value="${esc(t.id)}" ${t.id === state.selectedTemplateId ? 'checked' : ''}/>
        <img src="/api/templates/${esc(t.id)}/preview" alt="" onerror="this.style.display='none'"/>
        <div>
          <strong>${esc(t.name)}</strong>
          <small>${esc(t.description || '')}</small>
          <span class="meta-chip">${esc((t.siteTypes || []).join(', ') || 'any')} · ${esc(t.layout || t.id)}</span>
        </div>
      </label>
    `).join('')
    : '<p class="muted">No templates match this site type.</p>';

  host.querySelectorAll('input[name="templateId"]').forEach((input) => {
    input.addEventListener('change', () => {
      state.selectedTemplateId = input.value;
      renderTemplatePicker();
    });
  });
}

function renderTemplatesLibrary() {
  const host = document.getElementById('templatesLibrary');
  const cloneSelect = document.getElementById('tpl-clone-from');
  if (host) {
    host.innerHTML = (state.templates || []).map((t) => `
      <article class="template-card readonly">
        <img src="/api/templates/${esc(t.id)}/preview" alt="" onerror="this.style.display='none'"/>
        <div>
          <strong>${esc(t.name)}</strong>
          <small>${esc(t.description || '')}</small>
          <span class="meta-chip">${esc(t.id)}${t.builtin ? ' · builtin' : ' · custom'}</span>
        </div>
      </article>
    `).join('') || '<p class="muted">No templates registered.</p>';
  }
  if (cloneSelect) {
    cloneSelect.innerHTML = (state.templates || []).map((t) =>
      `<option value="${esc(t.id)}">${esc(t.name)} (${esc(t.id)})</option>`
    ).join('');
  }
}

function cmsUrl(site) {
  if (!site?.domain) return '#';
  const proto = location.protocol === 'https:' ? 'https' : 'https';
  return `${proto}://${site.domain}/admin/`;
}

function renderLibrary() {
  const filter = document.getElementById('statusFilter')?.value || '';
  const rows = document.getElementById('sitesRows');
  const deploySelect = document.getElementById('deploy-site-id');
  const active = (state.sites || []).filter((s) => s.status !== 'deleted');
  const filtered = filter ? active.filter((s) => s.status === filter) : active;

  if (rows) {
    rows.innerHTML = filtered.length
      ? filtered.map((site) => `
        <tr>
          <td>
            <strong>${esc(site.name)}</strong><br/>
            <code>${esc(site.id)}</code>
            ${site.platform ? ' <span class="pill on">Platform</span>' : ''}
            ${site.ops ? ' <span class="pill on">Ops</span>' : ''}
          </td>
          <td>${statusPill(site.status)}</td>
          <td>${esc(site.siteType || '—')}</td>
          <td><code>${esc(site.templateId || '—')}</code></td>
          <td>${esc((site.locales || []).join(', ') || site.defaultLocale || '—')}</td>
          <td>${esc(site.domain || '—')}</td>
          <td>${esc((site.updatedAt || '').slice(0, 16).replace('T', ' '))}</td>
          <td class="actions">
            ${site.platform || site.ops ? '' : `
              <button type="button" class="btn ghost compact" data-action="edit" data-id="${esc(site.id)}">Edit</button>
              <button type="button" class="btn ghost compact" data-action="deploy" data-id="${esc(site.id)}">Deploy</button>
              ${site.status === 'disabled'
                ? `<button type="button" class="btn ghost compact" data-action="enable" data-id="${esc(site.id)}">Enable</button>`
                : `<button type="button" class="btn ghost compact" data-action="disable" data-id="${esc(site.id)}">Disable</button>`}
              <button type="button" class="btn ghost compact" data-action="delete" data-id="${esc(site.id)}">Delete</button>
            `}
            ${site.domain && !site.platform ? `<a class="btn secondary compact" href="${esc(cmsUrl(site))}" target="_blank" rel="noopener">CMS</a>` : ''}
            ${site.platform ? '<a class="btn secondary compact" href="/admin/">CMS</a>' : ''}
            ${site.ops ? `<a class="btn secondary compact" href="https://${esc(site.domain)}/" target="_blank" rel="noopener">Ops</a>` : ''}
          </td>
        </tr>
      `).join('')
      : '<tr><td colspan="8" class="muted">No websites match this filter</td></tr>';
  }

  if (deploySelect) {
    const current = deploySelect.value;
    const deployable = active.filter((s) => !s.platform && !['deleted', 'disabled'].includes(s.status));
    deploySelect.innerHTML = '<option value="">Select site…</option>' +
      deployable.map((s) => `<option value="${esc(s.id)}">${esc(s.id)} — ${esc(s.domain || '')}</option>`).join('');
    if (current) deploySelect.value = current;
  }
}

function renderDeleted() {
  const rows = document.getElementById('deletedRows');
  const deleted = (state.sites || []).filter((s) => s.status === 'deleted');
  if (!rows) return;
  rows.innerHTML = deleted.length
    ? deleted.map((site) => `
      <tr>
        <td><code>${esc(site.id)}</code> — ${esc(site.name)}</td>
        <td>${esc(site.domain || '—')}</td>
        <td>${esc((site.updatedAt || '').slice(0, 16).replace('T', ' '))}</td>
        <td class="actions">
          <button type="button" class="btn secondary compact" data-action="restore" data-id="${esc(site.id)}">Restore</button>
          <button type="button" class="btn ghost compact" data-action="hard-delete" data-id="${esc(site.id)}">Hard delete</button>
        </td>
      </tr>
    `).join('')
    : '<tr><td colspan="4" class="muted">No deleted websites</td></tr>';
}

function collectWizardPayload() {
  const id = document.getElementById('site-create-id')?.value.trim() || '';
  const localesRaw = document.getElementById('site-locales')?.value || 'en';
  const locales = localesRaw.split(',').map((x) => x.trim()).filter(Boolean);
  return {
    id,
    name: document.getElementById('site-create-name')?.value.trim() || '',
    description: document.getElementById('site-create-description')?.value.trim() || '',
    domain: document.getElementById('site-create-domain')?.value.trim()
      || (id ? `${id}.veerlabs.solutions` : ''),
    siteType: document.querySelector('input[name="siteType"]:checked')?.value || 'responsive',
    templateId: state.selectedTemplateId || 'catalog-static',
    locales,
    defaultLocale: document.getElementById('site-default-locale')?.value.trim() || locales[0] || 'en',
    githubOwner: document.getElementById('site-create-owner')?.value.trim() || '',
    repos: parseRepos(document.getElementById('site-repos')?.value || ''),
    integrations: selectedIntegrations(),
  };
}

function renderReview() {
  const payload = collectWizardPayload();
  const tpl = state.templates.find((t) => t.id === payload.templateId);
  const card = document.getElementById('reviewCard');
  if (!card) return;
  card.innerHTML = `
    <dl class="review-dl">
      <div><dt>Id</dt><dd><code>${esc(payload.id)}</code></dd></div>
      <div><dt>Name</dt><dd>${esc(payload.name)}</dd></div>
      <div><dt>Domain</dt><dd>${esc(payload.domain)}</dd></div>
      <div><dt>Type</dt><dd>${esc(payload.siteType)}</dd></div>
      <div><dt>Template</dt><dd>${esc(tpl?.name || payload.templateId)}</dd></div>
      <div><dt>Locales</dt><dd>${esc(payload.locales.join(', '))} (default ${esc(payload.defaultLocale)})</dd></div>
      <div><dt>GitHub</dt><dd>${esc(payload.githubOwner || '—')}</dd></div>
      <div><dt>Repos</dt><dd>${payload.repos.length ? esc(payload.repos.map((r) => r.name).join(', ')) : '—'}</dd></div>
      <div><dt>Integrations</dt><dd>${esc(payload.integrations.join(', ') || '—')}</dd></div>
      <div><dt>Description</dt><dd>${esc(payload.description || '—')}</dd></div>
    </dl>
  `;
}

function resetWizard() {
  state.editingId = null;
  state.step = 0;
  state.selectedTemplateId = 'catalog-static';
  document.getElementById('wizardForm')?.reset();
  document.getElementById('edit-site-id').value = '';
  document.getElementById('site-create-id').readOnly = false;
  document.getElementById('wizardTitle').textContent = 'Define a website';
  document.getElementById('wizardModeHint').textContent = 'Capture metadata, pick a template, then scaffold';
  document.getElementById('site-locales').value = 'en';
  document.getElementById('site-default-locale').value = 'en';
  const responsive = document.querySelector('input[name="siteType"][value="responsive"]');
  if (responsive) responsive.checked = true;
  renderIntegrations();
  renderTemplatePicker();
  setWizardStep(0);
}

async function loadEditSite(siteId) {
  const data = await api(`/api/sites/${encodeURIComponent(siteId)}`);
  const site = data.site;
  state.editingId = site.id;
  document.getElementById('edit-site-id').value = site.id;
  document.getElementById('wizardTitle').textContent = `Edit ${site.name}`;
  document.getElementById('wizardModeHint').textContent = 'Update definition metadata (template change does not re-copy files)';
  document.getElementById('site-create-id').value = site.id;
  document.getElementById('site-create-id').readOnly = true;
  document.getElementById('site-create-name').value = site.name || '';
  document.getElementById('site-create-description').value = site.description || '';
  document.getElementById('site-create-domain').value = site.domain || '';
  document.getElementById('site-create-owner').value = site.githubOwner || '';
  document.getElementById('site-locales').value = (site.locales || ['en']).join(', ');
  document.getElementById('site-default-locale').value = site.defaultLocale || 'en';
  document.getElementById('site-repos').value = formatRepos(site.repos);
  const typeInput = document.querySelector(`input[name="siteType"][value="${site.siteType || 'responsive'}"]`);
  if (typeInput) typeInput.checked = true;
  state.selectedTemplateId = site.templateId || 'catalog-static';
  renderIntegrations(site.integrations || []);
  renderTemplatePicker();
  showView('wizard');
  setWizardStep(0);
}

async function refreshAll() {
  const [sitesData, templatesData] = await Promise.all([
    api('/api/sites?includeDeleted=1'),
    api('/api/templates'),
  ]);
  state.sites = sitesData.sites || [];
  state.templates = templatesData.templates || [];
  state.integrationsCatalog = sitesData.integrationsCatalog || KNOWN_INTEGRATIONS;
  renderLibrary();
  renderDeleted();
  renderTemplatesLibrary();
  renderTemplatePicker();
}

async function ensureSession() {
  const data = await api('/api/platform/session');
  const chip = document.getElementById('platformUserChip');
  if (chip) chip.textContent = data.username ? `Signed in as ${data.username}` : 'Signed in';
  const owner = document.getElementById('site-create-owner');
  if (owner && !owner.value && data.githubOwner) owner.value = data.githubOwner;
  document.getElementById('platformShell').hidden = false;
  return data;
}

async function deploySite(siteId) {
  const id = siteId || document.getElementById('deploy-site-id')?.value.trim() || '';
  if (!id) {
    alert('Select a site to deploy');
    return;
  }
  const log = document.getElementById('deployStatusLog');
  if (log) {
    log.hidden = false;
    log.textContent = `Deploying ${id}…`;
  }
  try {
    const data = await api(`/api/sites/${encodeURIComponent(id)}/deploy`, {
      method: 'POST',
      body: JSON.stringify({
        ec2Host: document.getElementById('deploy-ec2-host')?.value.trim() || '',
      }),
    });
    const text = [data.stdout, data.stderr].filter(Boolean).join('\n') || 'Deploy finished';
    if (log) log.textContent = text;
    if (!data.ok) alert(data.error || `Deploy failed for ${id}`);
    await refreshAll();
  } catch (error) {
    if (error.message === 'Authentication required') return;
    if (log) log.textContent = error.message || String(error);
    alert(error.message || 'Deploy failed');
  }
}

// Domain autofill
const siteIdInput = document.getElementById('site-create-id');
const siteDomainInput = document.getElementById('site-create-domain');
let domainTouched = false;
siteDomainInput?.addEventListener('input', () => {
  domainTouched = Boolean(siteDomainInput.value.trim());
});
siteIdInput?.addEventListener('input', () => {
  if (domainTouched || !siteDomainInput || state.editingId) return;
  const id = (siteIdInput.value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  siteDomainInput.value = id ? `${id}.veerlabs.solutions` : '';
});

document.querySelectorAll('.studio-tab').forEach((tab) => {
  tab.addEventListener('click', () => showView(tab.dataset.view));
});

document.getElementById('newWebsiteBtn')?.addEventListener('click', () => {
  resetWizard();
  showView('wizard');
});
document.getElementById('gotoTemplatesBtn')?.addEventListener('click', () => showView('templates'));
document.getElementById('refreshLibraryBtn')?.addEventListener('click', () => refreshAll().catch((e) => alert(e.message)));
document.getElementById('statusFilter')?.addEventListener('change', renderLibrary);
document.getElementById('deploySiteBtn')?.addEventListener('click', () => deploySite());

document.querySelectorAll('input[name="siteType"]').forEach((input) => {
  input.addEventListener('change', renderTemplatePicker);
});

document.getElementById('wizardBackBtn')?.addEventListener('click', () => {
  if (state.step > 0) setWizardStep(state.step - 1);
});
document.getElementById('wizardNextBtn')?.addEventListener('click', () => {
  if (state.step === 0) {
    const id = document.getElementById('site-create-id')?.value.trim();
    const name = document.getElementById('site-create-name')?.value.trim();
    if (!id || !name) {
      alert('Site id and display name are required');
      return;
    }
  }
  if (state.step === 1 && !state.selectedTemplateId) {
    alert('Select a template');
    return;
  }
  if (state.step < 4) setWizardStep(state.step + 1);
});

document.querySelectorAll('.wizard-step').forEach((btn) => {
  btn.addEventListener('click', () => setWizardStep(Number(btn.dataset.step)));
});

document.getElementById('wizardForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = collectWizardPayload();
  if (!payload.id || !payload.name) {
    alert('Site id and display name are required');
    return;
  }
  try {
    if (state.editingId) {
      const { id, ...patch } = payload;
      await api(`/api/sites/${encodeURIComponent(state.editingId)}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      alert(`Updated ${state.editingId}`);
    } else {
      const data = await api('/api/sites', { method: 'POST', body: JSON.stringify(payload) });
      alert(`Created ${data.site?.id}\n\n${data.site?.hint || ''}`);
    }
    await refreshAll();
    resetWizard();
    showView('library');
  } catch (error) {
    if (error.message !== 'Authentication required') alert(error.message || 'Save failed');
  }
});

document.getElementById('createTemplateForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const siteTypes = (document.getElementById('tpl-site-types')?.value || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
  try {
    await api('/api/templates', {
      method: 'POST',
      body: JSON.stringify({
        id: document.getElementById('tpl-id')?.value.trim(),
        name: document.getElementById('tpl-name')?.value.trim(),
        description: document.getElementById('tpl-description')?.value.trim(),
        cloneFrom: document.getElementById('tpl-clone-from')?.value.trim(),
        siteTypes,
      }),
    });
    document.getElementById('createTemplateForm').reset();
    await refreshAll();
    alert('Template created');
  } catch (error) {
    if (error.message !== 'Authentication required') alert(error.message || 'Failed to create template');
  }
});

document.addEventListener('click', async (event) => {
  const btn = event.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.getAttribute('data-action');
  const id = btn.getAttribute('data-id');
  try {
    if (action === 'edit') {
      await loadEditSite(id);
    } else if (action === 'deploy') {
      document.getElementById('deploy-site-id').value = id;
      await deploySite(id);
    } else if (action === 'disable') {
      await api(`/api/sites/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'disabled', statusNote: 'Disabled from Site Studio' }),
      });
      await refreshAll();
    } else if (action === 'enable') {
      await api(`/api/sites/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'authoring', statusNote: 'Re-enabled from Site Studio' }),
      });
      await refreshAll();
    } else if (action === 'delete') {
      if (!confirm(`Soft-delete ${id}? You can restore from the Deleted view.`)) return;
      await api(`/api/sites/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await refreshAll();
    } else if (action === 'restore') {
      await api(`/api/sites/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'authoring', statusNote: 'Restored from deleted' }),
      });
      await refreshAll();
      showView('library');
    } else if (action === 'hard-delete') {
      if (!confirm(`Permanently delete ${id} from disk? This cannot be undone.`)) return;
      await api(`/api/sites/${encodeURIComponent(id)}?hard=1`, { method: 'DELETE' });
      await refreshAll();
    }
  } catch (error) {
    if (error.message !== 'Authentication required') alert(error.message || 'Action failed');
  }
});

(async function boot() {
  try {
    await ensureSession();
    renderIntegrations();
    await refreshAll();
    resetWizard();
    showView('library');
  } catch (error) {
    if (error.message !== 'Authentication required') redirectToLogin();
  }
})();
