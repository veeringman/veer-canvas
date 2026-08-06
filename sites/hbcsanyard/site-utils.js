/**
 * Shared VeerLabs site utilities — project filtering, logos, sorting.
 */
(function (global) {
  const DEFAULT_LOGO = 'assets/default-project-logo.svg';
  // Preset heights for dashboard tiles (detail pages scale up slightly).
  const LOGO_SIZES = { sm: 44, md: 64, lg: 88, xl: 112 };
  const DETAIL_LOGO_SIZES = { sm: 72, md: 96, lg: 128, xl: 160 };

  function parsePositivePx(value) {
    if (value == null || value === '') return null;
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return null;
    return Math.round(num);
  }

  function resolveLogoDims(project, context) {
    const sizeKey = (project && project.logoSize) || 'md';
    const presets = context === 'detail' ? DETAIL_LOGO_SIZES : LOGO_SIZES;
    const presetHeight = presets[sizeKey] || presets.md;
    const width = parsePositivePx(project && project.logoWidth);
    const height = parsePositivePx(project && project.logoHeight) || presetHeight;
    return { width, height, sizeKey };
  }

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
      const orderA = Number.isFinite(Number(a && a.sortOrder)) ? Number(a.sortOrder) : 9999;
      const orderB = Number.isFinite(Number(b && b.sortOrder)) ? Number(b.sortOrder) : 9999;
      if (orderA !== orderB) return orderA - orderB;
      return (a.name || a.slug || '').localeCompare(b.name || b.slug || '');
    });
  }

  function visibleProjects(projects, excludedSlugs) {
    const excluded = new Set(excludedSlugs || []);
    return sortProjects((projects || []).filter((project) => {
      if (!isEnabled(project)) return false;
      if (project && project.slug && excluded.has(project.slug)) return false;
      return true;
    }));
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

  function optimizedLogoPath(originalPath, context) {
    if (!originalPath || typeof originalPath !== 'string') return null;
    if (/^https?:\/\//i.test(originalPath) || /\.svg$/i.test(originalPath)) return null;
    if (!/\.(png|jpe?g|webp)$/i.test(originalPath)) return null;
    const variant = context === 'detail' ? 'detail' : 'card';
    return originalPath.replace(/\.(png|jpe?g|webp)$/i, `.${variant}.webp`);
  }

  function ensureLogoPicture(imageEl, webpSrc, fallbackSrc) {
    if (!imageEl || !webpSrc) return;
    let picture = imageEl.closest('picture');
    if (!picture) {
      picture = document.createElement('picture');
      imageEl.parentNode.insertBefore(picture, imageEl);
      picture.appendChild(imageEl);
    }
    let source = picture.querySelector('source[data-logo-webp]');
    if (!source) {
      source = document.createElement('source');
      source.type = 'image/webp';
      source.dataset.logoWebp = '1';
      picture.insertBefore(source, imageEl);
    }
    source.srcset = webpSrc;
    imageEl.src = fallbackSrc;
    imageEl.dataset.logoFallback = fallbackSrc;
  }

  function logoSizeClass(project, context) {
    const { sizeKey } = resolveLogoDims(project, context || 'card');
    const prefix = context === 'detail' ? 'project-logo-detail' : 'project-logo';
    return `${prefix} logo-size-${sizeKey}`;
  }

  function applyProjectLogo(imageEl, project, context) {
    if (!imageEl) return;
    const mode = context || 'card';
    const { width, height, sizeKey } = resolveLogoDims(project, mode);
    const original = normalizeLogoPath(project);
    const optimized = optimizedLogoPath(original, mode);
    imageEl.alt = (project && project.logoAlt) || `${(project && project.name) || 'Project'} logo`;
    imageEl.className = logoSizeClass(project, mode);
    imageEl.loading = mode === 'card' ? 'lazy' : 'eager';
    imageEl.decoding = 'async';
    imageEl.style.objectFit = 'contain';
    imageEl.dataset.logoSize = sizeKey;
    if (width) imageEl.dataset.logoWidth = String(width);
    else delete imageEl.dataset.logoWidth;
    imageEl.dataset.logoHeight = String(height);
    delete imageEl.dataset.fallbackApplied;

    if (optimized) {
      ensureLogoPicture(imageEl, optimized, original);
    } else {
      imageEl.src = original;
    }

    if (mode === 'card') {
      // Fit inside the fixed logo well so tile copy shares one baseline.
      const fitHeight = Math.min(height, 54);
      imageEl.style.height = 'auto';
      imageEl.style.maxHeight = `${fitHeight}px`;
      imageEl.style.width = width ? `${Math.min(width, 220)}px` : 'auto';
      imageEl.style.maxWidth = '100%';
    } else {
      imageEl.style.height = `${height}px`;
      imageEl.style.maxHeight = '';
      imageEl.style.width = width ? `${width}px` : 'auto';
      imageEl.style.maxWidth = 'min(280px, 100%)';
    }

    imageEl.onerror = () => {
      if (imageEl.dataset.fallbackApplied === 'true') return;
      const fallback = imageEl.dataset.logoFallback || original;
      if (fallback && imageEl.src !== fallback && !imageEl.src.endsWith(fallback)) {
        imageEl.dataset.fallbackApplied = 'webp-miss';
        imageEl.src = fallback;
        return;
      }
      if (fallback !== DEFAULT_LOGO) {
        imageEl.dataset.fallbackApplied = 'true';
        imageEl.src = DEFAULT_LOGO;
      }
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
      const cacheBuster = catalogCacheBuster(meta) || String(Date.now());
      return fetchCatalog('projects-public.json', cacheBuster)
        .then(projects => {
          if (!Array.isArray(projects)) {
            throw new Error('Public catalog is not an array');
          }
          return fetch('catalog-exclusions.json', { cache: 'no-store' })
            .then(r => (r.ok ? r.json() : { deletedSlugs: [] }))
            .catch(() => ({ deletedSlugs: [] }))
            .then(exclusions => {
              const deleted = Array.isArray(exclusions.deletedSlugs) ? exclusions.deletedSlugs : [];
              return visibleProjects(projects, deleted);
            });
        });
    });
  }

  global.VeerSite = {
    DEFAULT_LOGO,
    LOGO_SIZES,
    DETAIL_LOGO_SIZES,
    isEnabled,
    sortProjects,
    visibleProjects,
    normalizeLogoPath,
    optimizedLogoPath,
    resolveLogoDims,
    logoSizeClass,
    applyProjectLogo,
    getCardSubtitle,
    loadSiteMeta,
    loadProjects,
  };
})(window);
