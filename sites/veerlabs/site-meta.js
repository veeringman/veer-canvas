function renderSiteFooter() {
  const footer = document.getElementById('site-footer');
  if (!footer) return;
  fetch('site-meta.json')
    .then(response => response.json())
    .then(meta => {
      const updated = meta.lastUpdated ? new Date(meta.lastUpdated).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      }) : 'recently updated';
      footer.innerHTML = `<span>Last updated ${updated}</span><span>Version ${meta.version || 'dev'}</span>`;
    })
    .catch(() => {
      footer.innerHTML = '<span>Website update info unavailable</span>';
    });
}

document.addEventListener('DOMContentLoaded', renderSiteFooter);
