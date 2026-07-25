function applyText(selector, value) {
  const el = document.querySelector(selector);
  if (!el || value == null || value === '') return;
  el.textContent = value;
}

function applyAttr(selector, attr, value) {
  const el = document.querySelector(selector);
  if (!el || value == null || value === '') return;
  el.setAttribute(attr, value);
}

function cacheBustedAsset(path, meta) {
  if (!path) return path;
  if (/[?&]v=/.test(path)) return path;
  const stamp = (meta && (meta.lastUpdated || meta.version)) || Date.now();
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}v=${encodeURIComponent(String(stamp))}`;
}

function applyBrandImage(selector, src, fallback) {
  const el = document.querySelector(selector);
  if (!el || !src) return;
  el.onerror = () => {
    if (el.dataset.fallbackApplied === 'true') return;
    el.dataset.fallbackApplied = 'true';
    el.src = fallback || 'assets/veer-canvas-icon.svg';
  };
  el.src = src;
}

function renderSiteChrome(meta) {
  const siteName = meta.siteName || meta.title || 'VeerLabs Solutions';
  const brandName = meta.brandName || 'VeerLabs';
  const brandTag = meta.brandTag || 'Solutions';
  const platform = meta.platform || 'VeerCanvas';
  const fallbackMark = 'assets/veer-canvas-icon.svg';
  const favicon = cacheBustedAsset(meta.favicon || 'assets/favicon.svg', meta);
  const brandMark = cacheBustedAsset(meta.brandMark || fallbackMark, meta);

  document.title = document.title.includes('—')
    ? document.title.replace(/—.*$/, `— ${siteName}`)
    : (document.querySelector('#project-name') ? document.title : siteName);

  const faviconLink = document.querySelector('link[rel="icon"]');
  if (faviconLink) {
    faviconLink.onerror = () => { faviconLink.href = 'assets/favicon.svg'; };
    faviconLink.href = favicon;
  }

  applyBrandImage('.brand-mark', brandMark, fallbackMark);
  applyAttr('.brand-lockup', 'aria-label', `${siteName} home`);
  applyText('.brand-name', brandName);
  applyText('.brand-tag', brandTag);
  applyText('.eyebrow', meta.eyebrow);
  applyText('.dashboard-hero h1', meta.title || siteName);
  applyText('.dashboard-hero .page-subtitle', meta.subtitle);

  const chips = document.querySelectorAll('.topbar-meta .meta-chip');
  if (chips[0] && meta.chipPrimary) chips[0].textContent = meta.chipPrimary;
  if (chips[1] && meta.chipSecondary) chips[1].textContent = meta.chipSecondary;

  const footer = document.getElementById('site-footer');
  if (!footer) return;
  const updated = meta.lastUpdated ? new Date(meta.lastUpdated).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  }) : 'recently updated';
  footer.innerHTML = `
    <div class="site-footer-brand">
      <img src="${brandMark}" alt="${platform}" width="22" height="22" onerror="this.onerror=null;this.src='${fallbackMark}'">
      <span>Powered by ${platform}</span>
    </div>
    <span>Last updated ${updated}</span>
    <span>Version ${meta.version || 'dev'}</span>`;
}

function renderSiteFooter() {
  fetch('site-meta.json', { cache: 'no-store' })
    .then(response => response.json())
    .then(meta => renderSiteChrome(meta || {}))
    .catch(() => {
      const footer = document.getElementById('site-footer');
      if (footer) footer.innerHTML = '<span>Website update info unavailable</span>';
    });
}

document.addEventListener('DOMContentLoaded', renderSiteFooter);
