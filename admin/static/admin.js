function logStatus(message) {
  const el = document.getElementById('statusLog');
  if (!el) return;
  const stamp = new Date().toLocaleTimeString();
  el.textContent = `[${stamp}] ${message}\n` + el.textContent;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function clearEditor() {
  document.getElementById('editorForm').reset();
  document.getElementById('field-slug').value = '';
  if (typeof loadSectionsIntoEditor === 'function') loadSectionsIntoEditor([]);
}

async function editProject(slug) {
  const data = await api(`/api/project/${encodeURIComponent(slug)}`);
  const p = data.project;
  document.getElementById('field-slug').value = p.slug || '';
  document.getElementById('field-name').value = p.name || '';
  document.getElementById('field-subtitle').value = p.subtitle || '';
  document.getElementById('field-summary').value = p.summary || '';
  document.getElementById('field-summaryFormat').value = p.summaryFormat || 'auto';
  document.getElementById('field-summaryAlign').value = p.summaryAlign || '';
  document.getElementById('field-summarySize').value = p.summarySize || '';
  document.getElementById('field-enabled').value = String(p.enabled !== false);
  document.getElementById('field-logoSize').value = p.logoSize || 'md';
  document.getElementById('field-sortOrder').value = p.sortOrder ?? 0;
  document.getElementById('field-tags').value = (p.tags || []).join(', ');
  document.getElementById('field-status').value = (p.status || []).join(', ');
  document.getElementById('field-logo').value = p.logo || '';
  document.getElementById('field-details').value = JSON.stringify(p.details || [], null, 2);
  if (typeof loadSectionsIntoEditor === 'function') loadSectionsIntoEditor(p.details || []);
  document.getElementById('editorPanel').scrollIntoView({ behavior: 'smooth' });
  logStatus(`Loaded ${slug}`);
}

async function toggleProject(slug) {
  const data = await api('/api/toggle', { method: 'POST', body: JSON.stringify({ slug }) });
  logStatus(`${slug} is now ${data.enabled ? 'shown' : 'hidden'}`);
  location.reload();
}

async function deleteProject(slug) {
  if (!confirm(`Delete ${slug}? This removes the miniapp folder.`)) return;
  await api('/api/delete', { method: 'POST', body: JSON.stringify({ slug }) });
  logStatus(`Deleted ${slug}`);
  location.reload();
}

document.getElementById('editorForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const slug = document.getElementById('field-slug').value.trim();
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
    name: document.getElementById('field-name').value.trim(),
    subtitle: document.getElementById('field-subtitle').value.trim(),
    summary: document.getElementById('field-summary').value.trim(),
    summaryFormat: document.getElementById('field-summaryFormat').value || 'auto',
    summaryAlign: document.getElementById('field-summaryAlign').value || '',
    summarySize: document.getElementById('field-summarySize').value || '',
    enabled: document.getElementById('field-enabled').value === 'true',
    logoSize: document.getElementById('field-logoSize').value,
    sortOrder: Number(document.getElementById('field-sortOrder').value || 0),
    tags: document.getElementById('field-tags').value.split(',').map(s => s.trim()).filter(Boolean),
    status: document.getElementById('field-status').value.split(',').map(s => s.trim()).filter(Boolean),
    logo: document.getElementById('field-logo').value.trim(),
    logoAlt: `${document.getElementById('field-name').value.trim()} logo`,
    details,
  };
  await api('/api/update', { method: 'POST', body: JSON.stringify(payload) });

  const fileInput = document.getElementById('field-logo-file');
  if (fileInput?.files?.length) {
    const form = new FormData();
    form.append('slug', slug);
    form.append('logo', fileInput.files[0]);
    const upload = await fetch('/api/upload-logo', { method: 'POST', body: form });
    const uploadData = await upload.json();
    if (!upload.ok) throw new Error(uploadData.error || 'Logo upload failed');
    logStatus(`Uploaded logo for ${slug}`);
  }

  logStatus(`Saved ${slug}`);
  location.reload();
});

document.getElementById('importBtn')?.addEventListener('click', async () => {
  if (!confirm('Import all GitHub repos (including private) into the catalog?')) return;
  logStatus('Import started...');
  const data = await api('/api/import', { method: 'POST', body: JSON.stringify({ includePrivate: true }) });
  logStatus(data.output || `Import complete: ${data.projectCount} projects`);
  location.reload();
});

document.getElementById('publishBtn')?.addEventListener('click', async () => {
  if (!confirm('Publish site and bump minor version?')) return;
  const data = await api('/api/publish', { method: 'POST', body: '{}' });
  logStatus(`Published ${data.meta.version} with ${data.projectCount} projects`);
  location.reload();
});

document.getElementById('search')?.addEventListener('input', (event) => {
  const q = event.target.value.toLowerCase();
  document.querySelectorAll('#projectRows tr').forEach((row) => {
    row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});
