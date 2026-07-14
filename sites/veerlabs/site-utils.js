/**
 * Shared VeerLabs site utilities — project filtering, logos, sorting.
 */
(function (global) {
  const DEFAULT_LOGO = 'assets/default-project-logo.svg';
  const LOGO_SIZES = { sm: 56, md: 84, lg: 120, xl: 160 };

  function isEnabled(project) {
    if (!project) return false;
    const value = project.enabled;
    if (value === false || value === 0) return false;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (normalized === 'false' || normalized === '0' || normalized === 'no' || normalized === 'off') {
        return false;
      }
    }
    return true;
  }

  function sortProjects(projects) {
    return [...projects].sort((a, b) => {
      const orderA = typeof a.sortOrder === 'number' ? a.sortOrder : 9999;
      const orderB = typeof b.sortOrder === 'number' ? b.sortOrder : 9999;
      if (orderA !== orderB) return orderA - orderB;
      return (a.name || a.slug || '').localeCompare(b.name || b.slug || '');
    });
  }

  function visibleProjects(projects) {
    return sortProjects((projects || []).filter(isEnabled));
  }

  function normalizeLogoPath(project) {
    const logo = project && project.logo;
    if (!logo || typeof logo !== 'string' || !logo.trim() || logo.includes('<')) {
      return DEFAULT_LOGO;
    }
    if (logo.startsWith('http://') || logo.startsWith('https://')) return logo;
    if (logo.startsWith('miniapps/') || logo.startsWith('assets/')) return logo;
    if (project.slug) return `miniapps/${project.slug}/${logo.replace(/^\.\//, '')}`;
    return logo;
  }

  function logoSizeClass(project, context) {
    const size = (project && project.logoSize) || 'md';
    const prefix = context === 'detail' ? 'project-logo-detail' : 'project-logo';
    return `${prefix} logo-size-${size}`;
  }

  function applyProjectLogo(imageEl, project, context) {
    if (!imageEl) return;
    imageEl.src = normalizeLogoPath(project);
    imageEl.alt = (project && project.logoAlt) || `${(project && project.name) || 'Project'} logo`;
    imageEl.className = logoSizeClass(project, context || 'card');
    imageEl.onerror = () => {
      if (imageEl.dataset.fallbackApplied === 'true') return;
      imageEl.dataset.fallbackApplied = 'true';
      imageEl.src = DEFAULT_LOGO;
    };
  }

  function getCardSubtitle(project) {
    const subtitle = project && typeof project.subtitle === 'string' ? project.subtitle.trim() : '';
    const summary = project && typeof project.summary === 'string' ? project.summary.trim() : '';
    if (!subtitle) return '';
    if (!summary) return subtitle;
    const subtitleWords = subtitle.toLowerCase().split(/\W+/).filter(Boolean);
    const summaryWords = summary.toLowerCase().split(/\W+/).filter(Boolean);
    const overlap = subtitleWords.filter(word => summaryWords.includes(word)).length;
    const overlapRatio = subtitleWords.length ? overlap / subtitleWords.length : 0;
    return overlapRatio >= 0.5 ? '' : subtitle;
  }

  let siteMetaPromise = null;

  function loadSiteMeta() {
    if (!siteMetaPromise) {
      siteMetaPromise = fetch('site-meta.json', { cache: 'no-store' })
        .then(r => (r.ok ? r.json() : {}))
        .catch(() => ({}));
    }
    return siteMetaPromise;
  }

  function catalogCacheBuster(meta) {
    const version = meta && meta.version ? String(meta.version) : '';
    const updated = meta && meta.lastUpdated ? String(meta.lastUpdated) : '';
    return encodeURIComponent(version || updated || Date.now());
  }

  function fetchCatalog(path, cacheBuster) {
    const url = cacheBuster ? `${path}?v=${cacheBuster}` : path;
    return fetch(url, { cache: 'no-store' }).then(r => {
      if (!r.ok) throw new Error(`${path} unavailable`);
      return r.json();
    });
  }

  function loadProjects() {
    return loadSiteMeta().then(meta => {
      const cacheBuster = catalogCacheBuster(meta);
      return fetchCatalog('projects-public.json', cacheBuster)
        .catch(() => fetchCatalog('projects.json', cacheBuster))
        .then(projects => visibleProjects(projects));
    });
  }

  global.VeerSite = {
    DEFAULT_LOGO,
    LOGO_SIZES,
    isEnabled,
    sortProjects,
    visibleProjects,
    normalizeLogoPath,
    logoSizeClass,
    applyProjectLogo,
    getCardSubtitle,
    loadSiteMeta,
    loadProjects,
  };
})(window);
