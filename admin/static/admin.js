function logStatus(message) {
  const el = document.getElementById('statusLog');
  if (!el) return;
  const stamp = new Date().toLocaleTimeString();
  el.textContent = `[${stamp}] ${message}\n` + el.textContent;
}

const LOGO_PRESET_HEIGHTS = { sm: 44, md: 64, lg: 88, xl: 112 };

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 413) {
      throw new Error('Upload too large (max 20MB). Compress the image and try again.');
    }
    throw new Error(data.error || data.output || response.statusText || `HTTP ${response.status}`);
  }
  return data;
}

function clearEditor() {
  document.getElementById('editorForm').reset();
  document.getElementById('field-slug').value = '';
  document.getElementById('field-isNew').value = 'false';
  document.getElementById('field-slug').readOnly = false;
  document.getElementById('field-logoWidth').value = '';
  document.getElementById('field-logoHeight').value = '';
  const title = document.getElementById('editorTitle');
  if (title) title.textContent = 'Edit project';
  const hint = document.getElementById('slugFieldHint');
  if (hint) hint.textContent = 'Lowercase letters, numbers, hyphens. Locked after create.';
  updateLogoPreview();
  if (typeof loadSectionsIntoEditor === 'function') loadSectionsIntoEditor([]);
}

function startNewProject() {
  clearEditor();
  document.getElementById('field-isNew').value = 'true';
  document.getElementById('field-slug').readOnly = false;
  document.getElementById('field-enabled').value = 'true';
  document.getElementById('field-requireAuth').value = 'false';
  document.getElementById('field-logoSize').value = 'md';
  document.getElementById('field-reimport').value = 'false';
  document.getElementById('field-sortOrder').value = '';
  document.getElementById('field-status').value = 'Draft';
  document.getElementById('field-logo').value = 'assets/default-project-logo.svg';
  document.getElementById('field-details').value = '[]';
  if (typeof loadSectionsIntoEditor === 'function') loadSectionsIntoEditor([]);
  const title = document.getElementById('editorTitle');
  if (title) title.textContent = 'New project';
  const hint = document.getElementById('slugFieldHint');
  if (hint) hint.textContent = 'Required. Will become the project URL and folder name.';
  updateLogoPreview();
  document.getElementById('editorPanel').scrollIntoView({ behavior: 'smooth' });
  document.getElementById('field-name')?.focus();
  logStatus('Creating a new project tile (no GitHub import required)');
}

document.getElementById('newProjectBtn')?.addEventListener('click', startNewProject);

function updateLogoPreview() {
  const preview = document.getElementById('logoPreview');
  if (!preview) return;
  const logoPath = document.getElementById('field-logo')?.value.trim() || '';
  const slug = document.getElementById('field-slug')?.value.trim() || '';
  const size = document.getElementById('field-logoSize')?.value || 'md';
  const widthRaw = document.getElementById('field-logoWidth')?.value;
  const heightRaw = document.getElementById('field-logoHeight')?.value;
  const width = widthRaw ? Number(widthRaw) : null;
  const height = heightRaw ? Number(heightRaw) : (LOGO_PRESET_HEIGHTS[size] || 64);
  let src = '/site/assets/default-project-logo.svg';
  if (logoPath.startsWith('miniapps/') || logoPath.startsWith('assets/')) {
    src = `/site/${logoPath}`;
  } else if (logoPath && slug) {
    src = `/site/miniapps/${slug}/${logoPath.replace(/^\.\//, '')}`;
  }
  preview.src = src;
  preview.style.height = `${height}px`;
  preview.style.width = width ? `${width}px` : 'auto';
  preview.style.maxWidth = '100%';
  preview.style.objectFit = 'contain';
}

async function editProject(slug) {
  const data = await api(`/api/project/${encodeURIComponent(slug)}`);
  const p = data.project;
  document.getElementById('field-isNew').value = 'false';
  document.getElementById('field-slug').value = p.slug || '';
  document.getElementById('field-slug').readOnly = true;
  document.getElementById('field-name').value = p.name || '';
  document.getElementById('field-subtitle').value = p.subtitle || '';
  document.getElementById('field-summary').value = p.summary || '';
  document.getElementById('field-summaryFormat').value = p.summaryFormat || 'auto';
  document.getElementById('field-summaryAlign').value = p.summaryAlign || '';
  document.getElementById('field-summarySize').value = p.summarySize || '';
  document.getElementById('field-enabled').value = String(p.enabled !== false);
  document.getElementById('field-requireAuth').value = String(p.requireAuth === true || p.requireAuth === 'true');
  document.getElementById('field-reimport').value = String(p.reimport === true || p.reimport === 'true');
  document.getElementById('field-logoSize').value = p.logoSize || 'md';
  document.getElementById('field-logoWidth').value = p.logoWidth || '';
  document.getElementById('field-logoHeight').value = p.logoHeight || '';
  document.getElementById('field-sortOrder').value = data.position || p.sortOrder || 1;
  document.getElementById('field-tags').value = (p.tags || []).join(', ');
  document.getElementById('field-status').value = (p.status || []).join(', ');
  document.getElementById('field-logo').value = p.logo || '';
  document.getElementById('field-details').value = JSON.stringify(p.details || [], null, 2);
  if (typeof loadSectionsIntoEditor === 'function') loadSectionsIntoEditor(p.details || []);
  const title = document.getElementById('editorTitle');
  if (title) title.textContent = 'Edit project';
  const hint = document.getElementById('slugFieldHint');
  if (hint) hint.textContent = 'Slug is locked for existing projects.';
  updateLogoPreview();
  document.getElementById('editorPanel').scrollIntoView({ behavior: 'smooth' });
  logStatus(`Loaded ${slug} (dashboard position ${data.position || '?'})`);
}

async function toggleProject(slug) {
  const data = await api('/api/toggle', { method: 'POST', body: JSON.stringify({ slug }) });
  logStatus(`${slug} is now ${data.enabled ? 'shown' : 'hidden'} (public catalog: ${data.publicCount})`);
  location.reload();
}

async function queueReimport(slug) {
  await api('/api/mark-reimport', { method: 'POST', body: JSON.stringify({ slug }) });
  logStatus(`Queued ${slug} for re-import. Run Import to refresh it from GitHub.`);
  location.reload();
}

async function deleteProject(slug) {
  if (!confirm(`Delete ${slug}? This removes the miniapp folder and hides it from future imports.`)) return;
  const data = await api('/api/delete', { method: 'POST', body: JSON.stringify({ slug }) });
  logStatus(`Deleted ${slug} (public catalog: ${data.publicCount})`);
  location.reload();
}

async function moveProject(slug, direction) {
  const data = await api('/api/reorder', {
    method: 'POST',
    body: JSON.stringify({ slug, direction }),
  });
  if (data.unchanged) {
    logStatus(`${slug} already at the ${direction === 'up' ? 'top' : 'bottom'}`);
    return;
  }
  logStatus(`Moved ${slug} to dashboard position ${data.position}`);
  location.reload();
}

async function setProjectPosition(slug, position) {
  const value = Number(position);
  if (!Number.isFinite(value) || value < 1) {
    alert('Position must be a positive number (1 = first on the website).');
    location.reload();
    return;
  }
  const data = await api('/api/reorder', {
    method: 'POST',
    body: JSON.stringify({ slug, position: value }),
  });
  logStatus(`Set ${slug} to dashboard position ${data.position}`);
  location.reload();
}

document.getElementById('normalizeOrderBtn')?.addEventListener('click', async () => {
  if (!confirm('Renumber all dashboard positions from the current list order (1…N)?')) return;
  const firstRow = document.querySelector('#projectRows tr[data-slug]');
  const slug = firstRow?.getAttribute('data-slug');
  if (!slug) return;
  const data = await api('/api/reorder', {
    method: 'POST',
    body: JSON.stringify({ slug, direction: 'normalize' }),
  });
  logStatus(`Normalized dashboard order (public catalog: ${data.publicCount})`);
  location.reload();
});

document.getElementById('editorForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const isNew = document.getElementById('field-isNew')?.value === 'true';
  let slug = document.getElementById('field-slug').value.trim();
  const name = document.getElementById('field-name').value.trim();
  if (!name) {
    alert('Name is required');
    return;
  }
  if (isNew && !slug) {
    slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    document.getElementById('field-slug').value = slug;
  }
  if (!slug) {
    alert('Slug is required');
    return;
  }
  if (typeof syncDetailsField === 'function') syncDetailsField();
  let details = [];
  try {
    details = JSON.parse(document.getElementById('field-details').value || '[]');
  } catch (error) {
    alert('Details must be valid JSON');
    return;
  }
  const payload = {
    slug,
    name,
    subtitle: document.getElementById('field-subtitle').value.trim(),
    summary: document.getElementById('field-summary').value.trim(),
    summaryFormat: document.getElementById('field-summaryFormat').value || 'auto',
    summaryAlign: document.getElementById('field-summaryAlign').value || '',
    summarySize: document.getElementById('field-summarySize').value || '',
    enabled: document.getElementById('field-enabled').value === 'true',
    requireAuth: document.getElementById('field-requireAuth').value === 'true',
    reimport: document.getElementById('field-reimport').value === 'true',
    logoSize: document.getElementById('field-logoSize').value,
    logoWidth: document.getElementById('field-logoWidth').value.trim(),
    logoHeight: document.getElementById('field-logoHeight').value.trim(),
    sortOrder: Number(document.getElementById('field-sortOrder').value || 0),
    tags: document.getElementById('field-tags').value.split(',').map(s => s.trim()).filter(Boolean),
    status: document.getElementById('field-status').value.split(',').map(s => s.trim()).filter(Boolean),
    logo: document.getElementById('field-logo').value.trim() || 'assets/default-project-logo.svg',
    logoAlt: `${name} logo`,
    details,
  };
  try {
    const endpoint = isNew ? '/api/create' : '/api/update';
    const saved = await api(endpoint, { method: 'POST', body: JSON.stringify(payload) });
    const savedSlug = saved.project?.slug || slug;

    const fileInput = document.getElementById('field-logo-file');
    if (fileInput?.files?.length) {
      const form = new FormData();
      form.append('slug', savedSlug);
      form.append('logo', fileInput.files[0]);
      const upload = await fetch('/api/upload-logo', { method: 'POST', body: form });
      const uploadData = await upload.json().catch(() => ({}));
      if (!upload.ok) {
        if (upload.status === 413) throw new Error('Logo too large (max 20MB). Compress and try again.');
        throw new Error(uploadData.error || 'Logo upload failed');
      }
      logStatus(`Uploaded logo for ${savedSlug}`);
    }

    logStatus(isNew ? `Created ${savedSlug}` : `Saved ${savedSlug}`);
    location.reload();
  } catch (error) {
    alert(error.message || 'Save failed');
    logStatus(`Save failed: ${error.message}`);
  }
});

document.getElementById('siteSettingsForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    // If a file was chosen but not uploaded yet, upload it before saving paths.
    if (document.getElementById('site-brandMark-file')?.files?.length) {
      await uploadSiteBrandAsset('brandMark', 'site-brandMark-file', 'site-brandMark', 'site-brandMark-preview');
    }
    if (document.getElementById('site-platformMark-file')?.files?.length) {
      await uploadSiteBrandAsset('platformMark', 'site-platformMark-file', 'site-platformMark', 'site-platformMark-preview');
    }
    if (document.getElementById('site-favicon-file')?.files?.length) {
      await uploadSiteBrandAsset('favicon', 'site-favicon-file', 'site-favicon', 'site-favicon-preview');
    }
    const payload = {
      siteName: document.getElementById('site-siteName')?.value.trim() || '',
      platform: document.getElementById('site-platform')?.value.trim() || 'VeerCanvas',
      brandName: document.getElementById('site-brandName')?.value.trim() || '',
      brandTag: document.getElementById('site-brandTag')?.value.trim() || '',
      eyebrow: document.getElementById('site-eyebrow')?.value.trim() || '',
      title: document.getElementById('site-title')?.value.trim() || '',
      subtitle: document.getElementById('site-subtitle')?.value.trim() || '',
      chipPrimary: document.getElementById('site-chipPrimary')?.value.trim() || '',
      chipSecondary: document.getElementById('site-chipSecondary')?.value.trim() || '',
      favicon: document.getElementById('site-favicon')?.value.trim() || 'assets/favicon.svg',
      brandMark: document.getElementById('site-brandMark')?.value.trim() || 'assets/veer-canvas-icon.svg',
      platformMark: document.getElementById('site-platformMark')?.value.trim() || 'assets/veer-canvas-icon.svg',
    };
    const data = await api('/api/site-meta', { method: 'POST', body: JSON.stringify(payload) });
    if (data.meta?.brandMark) document.getElementById('site-brandMark').value = data.meta.brandMark;
    if (data.meta?.platformMark) document.getElementById('site-platformMark').value = data.meta.platformMark;
    if (data.meta?.favicon) document.getElementById('site-favicon').value = data.meta.favicon;
    logStatus(`Saved site content (${data.meta?.siteName || 'ok'})`);
  } catch (error) {
    alert(error.message || 'Failed to save site content');
    logStatus(`Site save failed: ${error.message}`);
  }
});

async function uploadSiteBrandAsset(kind, fileInputId, pathInputId, previewId) {
  const fileInput = document.getElementById(fileInputId);
  const file = fileInput?.files?.[0];
  if (!file) {
    alert(kind === 'favicon' ? 'Choose a favicon image first.' : 'Choose a brand logo image first.');
    return;
  }
  const form = new FormData();
  form.append('kind', kind);
  form.append('file', file);
  const response = await fetch('/api/upload-brand', { method: 'POST', body: form });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 413) throw new Error('Image too large (max 20MB). Compress and try again.');
    throw new Error(data.error || 'Upload failed');
  }
  const pathInput = document.getElementById(pathInputId);
  if (pathInput) pathInput.value = data.path || '';
  const preview = document.getElementById(previewId);
  if (preview && data.path) {
    // Prefer the public site URL so preview matches live website.
    preview.src = `${data.publicUrl || `/${data.path}`}?v=${Date.now()}`;
  }
  if (fileInput) fileInput.value = '';
  logStatus(`Uploaded ${kind === 'favicon' ? 'favicon' : 'brand logo'} → ${data.path} (${data.bytes || 0} bytes)`);
  return data;
}

document.getElementById('uploadBrandMarkBtn')?.addEventListener('click', async () => {
  try {
    await uploadSiteBrandAsset('brandMark', 'site-brandMark-file', 'site-brandMark', 'site-brandMark-preview');
  } catch (error) {
    alert(error.message || 'Brand logo upload failed');
    logStatus(`Brand logo upload failed: ${error.message}`);
  }
});

document.getElementById('uploadFaviconBtn')?.addEventListener('click', async () => {
  try {
    await uploadSiteBrandAsset('favicon', 'site-favicon-file', 'site-favicon', 'site-favicon-preview');
  } catch (error) {
    alert(error.message || 'Favicon upload failed');
    logStatus(`Favicon upload failed: ${error.message}`);
  }
});

function previewLocalBrandFile(fileInputId, previewId, kind) {
  const fileInput = document.getElementById(fileInputId);
  const preview = document.getElementById(previewId);
  if (!fileInput || !preview) return;
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    // Show immediate local preview, then auto-upload so live site path is real.
    preview.src = URL.createObjectURL(file);
    try {
      const pathId = kind === 'favicon' ? 'site-favicon' : 'site-brandMark';
      await uploadSiteBrandAsset(kind, fileInputId, pathId, previewId);
    } catch (error) {
      alert(error.message || 'Upload failed');
      logStatus(`Auto-upload failed: ${error.message}`);
    }
  });
}
previewLocalBrandFile('site-brandMark-file', 'site-brandMark-preview', 'brandMark');
previewLocalBrandFile('site-favicon-file', 'site-favicon-preview', 'favicon');

document.getElementById('githubTokenForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const token = document.getElementById('github-token-input')?.value.trim() || '';
  if (!token) {
    alert('Paste a GitHub personal access token first.');
    return;
  }
  try {
    const data = await api('/api/github-token', { method: 'POST', body: JSON.stringify({ token }) });
    document.getElementById('github-token-input').value = '';
    updateGithubStatusLabel(data.github || data.token);
    logStatus('Saved GitHub token for private repo imports');
  } catch (error) {
    alert(error.message || 'Failed to save token');
    logStatus(`Token save failed: ${error.message}`);
  }
});

function updateGithubStatusLabel(info) {
  const statusEl = document.getElementById('githubTokenStatus');
  if (!statusEl || !info) return;
  if (info.ok && info.login) {
    statusEl.textContent = `Connected as ${info.login}` +
      (info.repoCount != null ? ` · ${info.repoCount}+ recent repos visible` : '') +
      (info.source ? ` (${info.source})` : '');
  } else if (info.configured) {
    statusEl.textContent = `Token configured (${info.source || 'file'})` +
      (info.error ? ` — ${info.error}` : ' — private imports enabled');
  } else {
    statusEl.textContent = 'No token — private repos cannot be imported';
  }
}

function writeSyncLog(message) {
  const el = document.getElementById('syncStatusLog');
  if (el) {
    el.hidden = false;
    const stamp = new Date().toLocaleTimeString();
    el.textContent = `[${stamp}] ${message}\n` + el.textContent;
  }
  logStatus(message);
}

async function runGithubSync({ onlySlugs = '', reimportQueued = true } = {}) {
  const only = String(onlySlugs || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  writeSyncLog(
    only.length
      ? `Syncing slugs: ${only.join(', ')}...`
      : 'Syncing NEW GitHub repos (+ queued re-imports)...'
  );
  const payload = {
    includePrivate: true,
    reimportAll: false,
    reimportSlugs: reimportQueued ? undefined : [],
    onlySlugs: only,
  };
  const data = await api('/api/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  const summary = data.summary || {};
  const newSlugs = data.newSlugs || summary.newSlugs || summary.importedSlugs || [];
  const parts = [
    `Sync complete`,
    `catalog ${data.projectCount}`,
    `public ${data.publicCount}`,
  ];
  if (summary.imported != null) parts.push(`imported ${summary.imported}`);
  if (summary.skipped != null) parts.push(`skipped ${summary.skipped}`);
  if (newSlugs.length) parts.push(`new: ${newSlugs.join(', ')}`);
  else parts.push('no new repos');
  writeSyncLog(parts.join(' · '));
  if (data.output) writeSyncLog(data.output.slice(-1500));
  return data;
}

document.getElementById('testGithubBtn')?.addEventListener('click', async () => {
  writeSyncLog('Testing GitHub connection...');
  try {
    const data = await api('/api/github-status', { method: 'POST', body: '{}' });
    updateGithubStatusLabel(data.github);
    if (data.github?.ok) {
      writeSyncLog(`GitHub OK as ${data.github.login} (owner ${data.owner})`);
    } else {
      writeSyncLog(`GitHub check failed: ${data.github?.error || 'unknown'}`);
      alert(data.github?.error || 'GitHub connection failed');
    }
  } catch (error) {
    writeSyncLog(`GitHub check failed: ${error.message}`);
    alert(error.message || 'GitHub check failed');
  }
});

document.getElementById('syncNewReposBtn')?.addEventListener('click', async () => {
  const onlySlugs = document.getElementById('sync-only-slugs')?.value.trim() || '';
  if (!confirm(
    onlySlugs
      ? `Sync only these repos from GitHub?\n\n${onlySlugs}\n\nAlready-imported projects are skipped unless queued for re-import.`
      : 'Sync NEW GitHub repos into the live catalog?\n\nAlready-imported projects are skipped unless queued for re-import.\nDeleted projects stay excluded.\nNo redeploy required.'
  )) return;
  try {
    await runGithubSync({ onlySlugs, reimportQueued: true });
    location.reload();
  } catch (error) {
    writeSyncLog(`Sync failed: ${error.message}`);
    alert(error.message || 'Sync failed');
  }
});

document.getElementById('syncQueuedBtn')?.addEventListener('click', async () => {
  if (!confirm('Run sync for projects queued for re-import only?\n\n(Also picks up any brand-new repos.)')) return;
  try {
    await runGithubSync({ onlySlugs: '', reimportQueued: true });
    location.reload();
  } catch (error) {
    writeSyncLog(`Sync failed: ${error.message}`);
    alert(error.message || 'Sync failed');
  }
});

['field-logoSize', 'field-logoWidth', 'field-logoHeight', 'field-logo'].forEach((id) => {
  document.getElementById(id)?.addEventListener('input', updateLogoPreview);
  document.getElementById(id)?.addEventListener('change', updateLogoPreview);
});

document.getElementById('importBtn')?.addEventListener('click', async () => {
  const onlySlugs = document.getElementById('sync-only-slugs')?.value.trim() || '';
  if (!confirm(
    'Sync NEW GitHub repos into the live catalog?\n\n' +
    'Already-imported projects are skipped unless marked for re-import.\n' +
    'Deleted projects stay excluded.\n' +
    'No redeploy required.'
  )) return;
  try {
    await runGithubSync({ onlySlugs, reimportQueued: true });
    location.reload();
  } catch (error) {
    writeSyncLog(`Sync failed: ${error.message}`);
    alert(error.message || 'Sync failed');
  }
});

document.getElementById('publishBtn')?.addEventListener('click', async () => {
  if (!confirm('Publish site and bump minor version?\n\nHidden and deleted projects stay off the public catalog.')) return;
  const data = await api('/api/publish', { method: 'POST', body: '{}' });
  logStatus(`Published ${data.meta.version} — catalog ${data.projectCount}, public ${data.publicCount}`);
  location.reload();
});

document.getElementById('search')?.addEventListener('input', (event) => {
  const q = event.target.value.toLowerCase();
  document.querySelectorAll('#projectRows tr').forEach((row) => {
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});

(function initResizablePanes() {
  const layout = document.querySelector('.admin-layout');
  const row = document.getElementById('workspaceRow');
  const resizer = document.getElementById('paneResizer');
  const projectsPanel = document.getElementById('projectsPanel');
  const resetBtn = document.getElementById('resetPaneWidthsBtn');
  if (!layout || !row || !resizer || !projectsPanel) return;

  const STORAGE_KEY = 'veercanvas.admin.projectsPanePct';
  const MIN_PROJECTS_PCT = 22;
  const MAX_PROJECTS_PCT = 68;
  const DEFAULT_PCT = 32;

  function isStacked() {
    return window.matchMedia('(max-width: 1100px)').matches;
  }

  function clamp(pct) {
    return Math.min(MAX_PROJECTS_PCT, Math.max(MIN_PROJECTS_PCT, pct));
  }

  function applyWidth(pct) {
    const value = `${clamp(pct)}%`;
    layout.style.setProperty('--projects-pane-width', value);
    resizer.setAttribute('aria-valuenow', String(Math.round(clamp(pct))));
  }

  function loadWidth() {
    const saved = Number(localStorage.getItem(STORAGE_KEY));
    applyWidth(Number.isFinite(saved) && saved > 0 ? saved : DEFAULT_PCT);
  }

  function saveWidth(pct) {
    localStorage.setItem(STORAGE_KEY, String(clamp(pct)));
  }

  function setFromClientX(clientX) {
    const rect = row.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pct = ((clientX - rect.left) / rect.width) * 100;
    applyWidth(pct);
    return pct;
  }

  loadWidth();
  resizer.setAttribute('aria-valuemin', String(MIN_PROJECTS_PCT));
  resizer.setAttribute('aria-valuemax', String(MAX_PROJECTS_PCT));

  let dragging = false;

  function onPointerDown(event) {
    if (isStacked()) return;
    dragging = true;
    row.classList.add('is-resizing');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    resizer.setPointerCapture?.(event.pointerId);
    setFromClientX(event.clientX);
    event.preventDefault();
  }

  function onPointerMove(event) {
    if (!dragging) return;
    setFromClientX(event.clientX);
  }

  function onPointerUp(event) {
    if (!dragging) return;
    dragging = false;
    row.classList.remove('is-resizing');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    const pct = setFromClientX(event.clientX);
    if (pct != null) saveWidth(pct);
  }

  resizer.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  window.addEventListener('pointercancel', onPointerUp);

  resizer.addEventListener('keydown', (event) => {
    if (isStacked()) return;
    const current = Number(String(layout.style.getPropertyValue('--projects-pane-width')).replace('%', '')) || DEFAULT_PCT;
    let next = current;
    if (event.key === 'ArrowLeft') next = current - 2;
    else if (event.key === 'ArrowRight') next = current + 2;
    else if (event.key === 'Home') next = MIN_PROJECTS_PCT;
    else if (event.key === 'End') next = MAX_PROJECTS_PCT;
    else return;
    event.preventDefault();
    applyWidth(next);
    saveWidth(next);
  });

  resetBtn?.addEventListener('click', () => {
    applyWidth(DEFAULT_PCT);
    saveWidth(DEFAULT_PCT);
    logStatus('Reset projects/editor pane widths');
  });

  window.addEventListener('resize', () => {
    if (isStacked()) return;
    const current = Number(String(layout.style.getPropertyValue('--projects-pane-width')).replace('%', ''));
    if (Number.isFinite(current)) applyWidth(current);
  });
})();
