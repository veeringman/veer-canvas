const SECTION_FORMATS = ['auto', 'markdown', 'html', 'mermaid'];
const ALIGN_OPTIONS = ['', 'left', 'center', 'right', 'justify'];
const SIZE_OPTIONS = ['', 'sm', 'md', 'lg', 'xl', 'full'];

let sectionState = [];
let editorMode = 'visual';

function defaultSection() {
  return {
    title: 'New section',
    format: 'markdown',
    align: '',
    size: '',
    body: '',
    items: [],
  };
}

function normalizeSection(raw) {
  const section = { ...defaultSection(), ...(raw || {}) };
  if (!section.title) section.title = 'Untitled section';
  if (!SECTION_FORMATS.includes(section.format)) section.format = 'auto';
  return section;
}

function sectionsFromJson(value) {
  try {
    const parsed = JSON.parse(value || '[]');
    return Array.isArray(parsed) ? parsed.map(normalizeSection) : [];
  } catch (error) {
    return null;
  }
}

function sectionsToJson(sections) {
  return JSON.stringify(sections.map(section => {
    const payload = {
      title: section.title || '',
      body: section.body || '',
    };
    if (section.format && section.format !== 'auto') payload.format = section.format;
    if (section.align) payload.align = section.align;
    if (section.size) payload.size = section.size;
    if (section.titleAlign) payload.titleAlign = section.titleAlign;
    if (section.bodyAlign) payload.bodyAlign = section.bodyAlign;
    if (section.className) payload.className = section.className;
    if (section.width) payload.width = section.width;
    if (Array.isArray(section.items) && section.items.length) payload.items = section.items;
    if (Array.isArray(section.blocks) && section.blocks.length) payload.blocks = section.blocks;
    return payload;
  }), null, 2);
}

function syncDetailsField() {
  const field = document.getElementById('field-details');
  if (field) field.value = sectionsToJson(sectionState);
}

function setEditorMode(mode) {
  editorMode = mode;
  const visual = document.getElementById('sectionEditor');
  const jsonWrap = document.getElementById('detailsJsonWrap');
  const visualBtn = document.getElementById('editorModeVisual');
  const jsonBtn = document.getElementById('editorModeJson');
  if (mode === 'json') {
    syncDetailsField();
    if (visual) visual.hidden = true;
    if (jsonWrap) jsonWrap.hidden = false;
    if (visualBtn) visualBtn.classList.remove('active');
    if (jsonBtn) jsonBtn.classList.add('active');
    return;
  }
  const parsed = sectionsFromJson(document.getElementById('field-details')?.value || '[]');
  if (parsed) sectionState = parsed;
  renderSectionEditor();
  if (visual) visual.hidden = false;
  if (jsonWrap) jsonWrap.hidden = true;
  if (visualBtn) visualBtn.classList.add('active');
  if (jsonBtn) jsonBtn.classList.remove('active');
  syncDetailsField();
  renderContentPreview();
}

function iconSvg(name) {
  const icons = {
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m18 15-6-6-6 6"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    remove: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
  };
  return icons[name] || '';
}

function renderSectionEditor() {
  const root = document.getElementById('sectionEditor');
  if (!root) return;
  root.innerHTML = '';

  sectionState.forEach((section, index) => {
    const card = document.createElement('article');
    card.className = 'section-card';
    card.innerHTML = `
      <div class="section-card-head">
        <strong>Section ${index + 1}</strong>
        <div class="section-card-actions">
          <button type="button" class="btn icon-btn" data-action="up" data-index="${index}" title="Move up" aria-label="Move section up">${iconSvg('up')}</button>
          <button type="button" class="btn icon-btn" data-action="down" data-index="${index}" title="Move down" aria-label="Move section down">${iconSvg('down')}</button>
          <button type="button" class="btn icon-btn danger" data-action="remove" data-index="${index}" title="Remove section" aria-label="Remove section">${iconSvg('remove')}</button>
        </div>
      </div>
      <label>Title<input data-field="title" data-index="${index}" value="${escapeAttr(section.title || '')}"></label>
      <div class="grid-3">
        <label>Format<select data-field="format" data-index="${index}">
          ${SECTION_FORMATS.map(value => `<option value="${value}" ${section.format === value ? 'selected' : ''}>${value}</option>`).join('')}
        </select></label>
        <label>Align<select data-field="align" data-index="${index}">
          ${ALIGN_OPTIONS.map(value => `<option value="${value}" ${section.align === value ? 'selected' : ''}>${value || 'default'}</option>`).join('')}
        </select></label>
        <label>Size<select data-field="size" data-index="${index}">
          ${SIZE_OPTIONS.map(value => `<option value="${value}" ${section.size === value ? 'selected' : ''}>${value || 'default'}</option>`).join('')}
        </select></label>
      </div>
      <label>Body<textarea data-field="body" data-index="${index}" rows="6" placeholder="Markdown, HTML, or mermaid diagram code">${escapeHtml(section.body || '')}</textarea></label>
      <label>List items (one per line)<textarea data-field="items" data-index="${index}" rows="3" placeholder="Optional bullet list items">${escapeHtml((section.items || []).join('\n'))}</textarea></label>
    `;
    root.appendChild(card);
  });

  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'btn add-section';
  addBtn.innerHTML = `${iconSvg('plus')}<span>Add section</span>`;
  addBtn.onclick = () => {
    sectionState.push(defaultSection());
    renderSectionEditor();
    syncDetailsField();
    renderContentPreview();
  };
  root.appendChild(addBtn);
}

function escapeAttr(value) {
  return String(value || '').replace(/"/g, '&quot;');
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function updateSectionFromTarget(target) {
  const index = Number(target.dataset.index);
  if (Number.isNaN(index) || !sectionState[index]) return;
  const field = target.dataset.field;
  if (field === 'items') {
    sectionState[index].items = target.value.split('\n').map(line => line.trim()).filter(Boolean);
  } else {
    sectionState[index][field] = target.value;
  }
  syncDetailsField();
  renderContentPreview();
}

function handleSectionEditorClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const index = Number(button.dataset.index);
  const action = button.dataset.action;
  if (action === 'remove') {
    sectionState.splice(index, 1);
  } else if (action === 'up' && index > 0) {
    [sectionState[index - 1], sectionState[index]] = [sectionState[index], sectionState[index - 1]];
  } else if (action === 'down' && index < sectionState.length - 1) {
    [sectionState[index + 1], sectionState[index]] = [sectionState[index], sectionState[index + 1]];
  }
  renderSectionEditor();
  syncDetailsField();
  renderContentPreview();
}

function getPreviewProject() {
  const slug = document.getElementById('field-slug')?.value.trim() || 'preview';
  let details = sectionState;
  if (editorMode === 'json') {
    details = sectionsFromJson(document.getElementById('field-details')?.value || '[]') || [];
  }
  return {
    slug,
    name: document.getElementById('field-name')?.value.trim() || 'Preview',
    summary: document.getElementById('field-summary')?.value || '',
    summaryFormat: document.getElementById('field-summaryFormat')?.value || 'auto',
    summaryAlign: document.getElementById('field-summaryAlign')?.value || '',
    summarySize: document.getElementById('field-summarySize')?.value || '',
    details,
  };
}

let previewTimer = null;

function renderContentPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const panel = document.getElementById('contentPreview');
    if (!panel || typeof VeerContent === 'undefined') return;
    panel.innerHTML = '<p class="muted">Rendering preview...</p>';
    try {
      await VeerContent.renderProjectContent(panel, getPreviewProject());
    } catch (error) {
      panel.innerHTML = `<p class="error">Preview failed: ${escapeHtml(error.message || error)}</p>`;
    }
  }, 250);
}

function loadSectionsIntoEditor(details) {
  sectionState = Array.isArray(details) ? details.map(normalizeSection) : [];
  syncDetailsField();
  if (editorMode === 'visual') renderSectionEditor();
  renderContentPreview();
}

function initContentEditor() {
  const root = document.getElementById('sectionEditor');
  if (!root) return;

  root.addEventListener('input', (event) => {
    if (event.target.dataset.index) updateSectionFromTarget(event.target);
  });
  root.addEventListener('change', (event) => {
    if (event.target.dataset.index) updateSectionFromTarget(event.target);
  });
  root.addEventListener('click', handleSectionEditorClick);

  document.getElementById('editorModeVisual')?.addEventListener('click', () => setEditorMode('visual'));
  document.getElementById('editorModeJson')?.addEventListener('click', () => setEditorMode('json'));
  document.getElementById('field-details')?.addEventListener('input', () => {
    if (editorMode === 'json') renderContentPreview();
  });

  ['field-summary', 'field-summaryFormat', 'field-summaryAlign', 'field-summarySize', 'field-name']
    .forEach(id => document.getElementById(id)?.addEventListener('input', renderContentPreview));

  setEditorMode('visual');
}

document.addEventListener('DOMContentLoaded', initContentEditor);
