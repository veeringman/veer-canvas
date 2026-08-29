/**
 * Society branding from site-meta.json — drives simple chrome and stationery defaults.
 */

let siteBranding = null;

function cacheBust(path, meta) {
  if (!path) return path;
  if (/[?&]v=/.test(path)) return path;
  const stamp = meta?.lastUpdated || meta?.version || '';
  if (!stamp) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}v=${encodeURIComponent(String(stamp))}`;
}

function normalizeBranding(meta) {
  const m = meta && typeof meta === 'object' ? meta : {};
  const compose = m.composeBranding && typeof m.composeBranding === 'object' ? m.composeBranding : {};
  const society = String(m.societyName || compose.societyName || '').trim();
  const colony = String(m.siteName || m.brandName || compose.colonyName || '').trim();
  const origin = String(m.publicOrigin || compose.publicOrigin || '').trim().replace(/\/$/, '');
  const email = String(compose.email || m.email || '').trim();
  const address = String(compose.addressLine || compose.address || '').trim();
  let footer = String(compose.footerLine || compose.footer || '').trim();
  if (!footer && society) footer = society;
  const logoPrint = cacheBust(String(m.logoPrint || compose.logoPrint || '/assets/favicon-192.png'), m);
  const logoWatermark = cacheBust(String(m.logoWatermark || compose.logoWatermark || logoPrint), m);
  const metaBits = [];
  if (address) metaBits.push(address);
  if (email) metaBits.push(email);
  if (origin) {
    const host = origin.replace(/^https?:\/\//, '');
    if (host && !metaBits.join(' · ').includes(host)) metaBits.push(host);
  }
  return {
    societyName: society || colony || 'Residents Welfare Association',
    colonyName: colony || society || 'Society',
    addressLine: address,
    email,
    publicOrigin: origin,
    metaLine: metaBits.join(' · '),
    footerLine: footer,
    logoPrint: logoPrint.startsWith('/') ? logoPrint : `/${logoPrint.replace(/^\//, '')}`,
    logoWatermark: logoWatermark.startsWith('/') ? logoWatermark : `/${logoWatermark.replace(/^\//, '')}`,
  };
}

export function setSocietyBranding(meta) {
  siteBranding = normalizeBranding(meta);
}

export function getSocietyBranding() {
  return siteBranding || normalizeBranding(null);
}

export function simpleChromeHeadHtml() {
  const b = getSocietyBranding();
  const meta = b.metaLine ? `<p class="meta">${escapeHtml(b.metaLine)}</p>` : '';
  return `<div class="mhws-simple-chrome">
  <div class="mhws-simple-head">
  <img src="${escapeHtml(b.logoPrint)}" alt="">
  <h1>${escapeHtml(b.societyName)}</h1>
  <p class="sub">${escapeHtml(b.colonyName)}</p>
  ${meta}
</div>
<div class="rule" aria-hidden="true"><span class="pip"></span></div>
</div>`;
}

export function simpleChromeFootHtml() {
  const b = getSocietyBranding();
  return `<div class="mhws-simple-foot">${escapeHtml(b.footerLine)}</div>`;
}

export function defaultStationeryFromBranding() {
  const b = getSocietyBranding();
  return {
    paper: { id: 'A4', widthMm: 210, heightMm: 297, orientation: 'portrait' },
    backgroundColor: '#ffffff',
    logo: { src: b.logoPrint, widthMm: 18, align: 'center', enabled: true },
    headerLines: [
      {
        text: b.societyName,
        font: 'garamond',
        sizePt: 15,
        weight: '700',
        color: '#0b2a56',
        align: 'center',
      },
      {
        text: b.colonyName,
        font: 'source',
        sizePt: 10,
        weight: '600',
        color: '#1a6b3a',
        align: 'center',
      },
      ...(b.addressLine ? [{
        text: b.addressLine,
        font: 'noto',
        sizePt: 8,
        weight: '400',
        color: '#5a6a80',
        align: 'center',
      }] : []),
    ],
    watermark: { src: b.logoWatermark, opacity: 0.72, enabled: true },
    footer: {
      text: b.footerLine,
      font: 'noto',
      sizePt: 8,
      weight: '600',
      color: '#5a6a80',
    },
    border: { style: 'tricolor' },
  };
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
