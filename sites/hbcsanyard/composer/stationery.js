/**
 * Stationery (letterhead) designer — spec, paper sizes, and HTML render.
 * Shared by the composer preview and the saved pad used as document chrome.
 */

export const STATIONERY_PAPERS = [
  { id: 'A3', label: 'A3', widthMm: 297, heightMm: 420 },
  { id: 'A4', label: 'A4', widthMm: 210, heightMm: 297 },
  { id: 'A5', label: 'A5', widthMm: 148, heightMm: 210 },
  { id: 'A6', label: 'A6', widthMm: 105, heightMm: 148 },
  { id: 'B5', label: 'B5', widthMm: 176, heightMm: 250 },
  { id: 'Letter', label: 'Letter', widthMm: 215.9, heightMm: 279.4 },
  { id: 'Legal', label: 'Legal', widthMm: 215.9, heightMm: 355.6 },
  { id: 'Tabloid', label: 'Tabloid', widthMm: 279.4, heightMm: 431.8 },
  { id: 'Executive', label: 'Executive', widthMm: 184.2, heightMm: 266.7 },
  { id: 'CUSTOM', label: 'Custom', widthMm: 210, heightMm: 297 },
];

export const STATIONERY_FONTS = [
  { id: 'noto', label: 'Noto Sans', css: '"Noto Sans", "Segoe UI", sans-serif' },
  { id: 'source', label: 'Source Sans', css: '"Source Sans 3", "Segoe UI", sans-serif' },
  { id: 'georgia', label: 'Georgia', css: 'Georgia, "Times New Roman", serif' },
  { id: 'garamond', label: 'Garamond', css: '"Cormorant Garamond", Garamond, Georgia, serif' },
  { id: 'times', label: 'Times', css: '"Times New Roman", Times, serif' },
];

export const STATIONERY_BORDERS = [
  { id: 'none', label: 'None' },
  { id: 'navy-rule', label: 'Navy rule' },
  { id: 'tricolor', label: 'Tricolour edge' },
  { id: 'gold-rule', label: 'Gold rule' },
  { id: 'double-box', label: 'Double box' },
];

const DEFAULT_LOGO = '/assets/mhws-logo/mhws-logo-seal-cert.png?v=20260822logo1';
const DEFAULT_WM = '/assets/mhws-logo/mhws-logo-watermark.png?v=20260811wm8';

function paperById(id) {
  return STATIONERY_PAPERS.find((p) => p.id === id) || STATIONERY_PAPERS.find((p) => p.id === 'A4');
}

function fontCss(id) {
  return (STATIONERY_FONTS.find((f) => f.id === id) || STATIONERY_FONTS[0]).css;
}

function hexColor(raw, fallback) {
  const text = String(raw || '').trim();
  if (/^#?[0-9a-fA-F]{6}$/.test(text)) return text.startsWith('#') ? text : `#${text}`;
  if (/^#?[0-9a-fA-F]{3}$/.test(text)) {
    const t = text.startsWith('#') ? text.slice(1) : text;
    return `#${t[0]}${t[0]}${t[1]}${t[1]}${t[2]}${t[2]}`;
  }
  return fallback;
}

function num(raw, lo, hi, fallback) {
  const n = Number.parseFloat(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
}

function esc(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function safeUrl(raw) {
  const text = String(raw || '').trim();
  if (!text) return '';
  if (/^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,/i.test(text)) return text;
  if (/^https?:\/\//i.test(text) || text.startsWith('/')) return text;
  return '';
}

export function defaultStationerySpec() {
  return {
    paper: { id: 'A4', widthMm: 210, heightMm: 297, orientation: 'portrait' },
    backgroundColor: '#ffffff',
    logo: { src: DEFAULT_LOGO, widthMm: 18, align: 'center', enabled: true },
    headerLines: [
      {
        text: 'Mandi Housing Welfare Society',
        font: 'garamond',
        sizePt: 15,
        weight: '700',
        color: '#0b2a56',
        align: 'center',
      },
      {
        text: 'Himuda Housing Colony Sanyard',
        font: 'source',
        sizePt: 10,
        weight: '600',
        color: '#1a6b3a',
        align: 'center',
      },
      {
        text: 'Housing Colony Sanyard, Mandi HP 175001 · Registration No. 467 dated 21/07/2012',
        font: 'noto',
        sizePt: 8,
        weight: '400',
        color: '#5a6a80',
        align: 'center',
      },
    ],
    watermark: { src: DEFAULT_WM, opacity: 0.72, enabled: true },
    footer: {
      text: 'Unity · Harmony · Progress · Mandi Housing Welfare Society',
      font: 'noto',
      sizePt: 8,
      weight: '600',
      color: '#5a6a80',
    },
    border: { style: 'tricolor' },
  };
}

export function normalizeStationerySpec(raw) {
  const base = defaultStationerySpec();
  const data = raw && typeof raw === 'object' ? raw : {};
  const paperIn = data.paper && typeof data.paper === 'object' ? data.paper : {};
  const known = paperById(paperIn.id || 'A4');
  const custom = String(paperIn.id || '') === 'CUSTOM';
  const widthMm = custom ? num(paperIn.widthMm, 70, 450, known.widthMm) : known.widthMm;
  const heightMm = custom ? num(paperIn.heightMm, 70, 500, known.heightMm) : known.heightMm;
  const orientation = paperIn.orientation === 'landscape' ? 'landscape' : 'portrait';
  const w = orientation === 'landscape' ? Math.max(widthMm, heightMm) : widthMm;
  const h = orientation === 'landscape' ? Math.min(widthMm, heightMm) : heightMm;
  const logoIn = data.logo && typeof data.logo === 'object' ? data.logo : {};
  const wmIn = data.watermark && typeof data.watermark === 'object' ? data.watermark : {};
  const footIn = data.footer && typeof data.footer === 'object' ? data.footer : {};
  const borderIn = data.border && typeof data.border === 'object' ? data.border : {};
  const linesIn = Array.isArray(data.headerLines) ? data.headerLines : base.headerLines;
  const headerLines = linesIn.slice(0, 8).map((line, i) => {
    const src = line && typeof line === 'object' ? line : {};
    const fallback = base.headerLines[Math.min(i, base.headerLines.length - 1)];
    const align = ['left', 'center', 'right'].includes(src.align) ? src.align : (fallback.align || 'center');
    const weight = ['400', '500', '600', '700'].includes(String(src.weight)) ? String(src.weight) : (fallback.weight || '600');
    return {
      text: String(src.text || ''),
      font: STATIONERY_FONTS.some((f) => f.id === src.font) ? src.font : (fallback.font || 'noto'),
      sizePt: num(src.sizePt, 6, 36, fallback.sizePt || 11),
      weight,
      color: hexColor(src.color, fallback.color || '#0b2a56'),
      align,
    };
  });
  if (!headerLines.length) headerLines.push({ ...base.headerLines[0], text: '' });
  return {
    paper: {
      id: custom ? 'CUSTOM' : known.id,
      widthMm: w,
      heightMm: h,
      orientation,
    },
    backgroundColor: hexColor(data.backgroundColor, base.backgroundColor),
    logo: {
      src: safeUrl(logoIn.src) || (logoIn.enabled === false ? '' : base.logo.src),
      widthMm: num(logoIn.widthMm, 8, 60, base.logo.widthMm),
      align: ['left', 'center', 'right'].includes(logoIn.align) ? logoIn.align : 'center',
      enabled: logoIn.enabled !== false && Boolean(safeUrl(logoIn.src) || base.logo.src),
    },
    headerLines,
    watermark: {
      src: safeUrl(wmIn.src) || (wmIn.enabled === false ? '' : base.watermark.src),
      opacity: num(wmIn.opacity, 0.08, 1, base.watermark.opacity),
      enabled: wmIn.enabled !== false && Boolean(safeUrl(wmIn.src) || base.watermark.src),
    },
    footer: {
      text: String(footIn.text || ''),
      font: STATIONERY_FONTS.some((f) => f.id === footIn.font) ? footIn.font : base.footer.font,
      sizePt: num(footIn.sizePt, 6, 16, base.footer.sizePt),
      weight: ['400', '500', '600', '700'].includes(String(footIn.weight)) ? String(footIn.weight) : base.footer.weight,
      color: hexColor(footIn.color, base.footer.color),
    },
    border: {
      style: STATIONERY_BORDERS.some((b) => b.id === borderIn.style) ? borderIn.style : 'navy-rule',
    },
  };
}

function borderCss(style, w, h) {
  if (style === 'double-box') {
    return `
      .sheet { outline: 1.4pt solid #0b2a56; outline-offset: -4mm; }
      .pad { box-shadow: inset 0 0 0 0.6pt rgba(11,42,86,0.35); }
    `;
  }
  if (style === 'gold-rule') {
    return `
      .mhws-st-foot { border-top: 0.7pt solid rgba(201, 162, 39, 0.55); }
    `;
  }
  if (style === 'navy-rule') {
    return `
      .mhws-st-foot { border-top: 0.7pt solid rgba(11,42,86,0.35); }
    `;
  }
  if (style === 'tricolor') {
    return `
      .sheet::before, .sheet::after {
        content: "";
        position: absolute;
        top: 0;
        height: 2.8mm;
        z-index: 2;
      }
      .sheet::before { left: 0; width: 42%; background: #0b2a56; }
      .sheet::after { right: 0; width: 42%; background: #1a6b3a; }
      .mhws-st-accent { position: absolute; top: 0; left: 42%; width: 16%; height: 2.8mm; background: #c9a227; z-index: 2; }
      .mhws-st-head { padding-top: 4mm; }
      .mhws-st-foot { border-top: 0.7pt solid rgba(11,42,86,0.35); }
    `;
  }
  return '';
}

export function renderStationerySheet(specIn) {
  const spec = normalizeStationerySpec(specIn);
  const w = spec.paper.widthMm;
  const h = spec.paper.heightMm;
  const logo = spec.logo.enabled && spec.logo.src
    ? `<img class="mhws-st-logo" src="${esc(spec.logo.src)}" alt="" style="width:${spec.logo.widthMm}mm">`
    : '';
  const lines = spec.headerLines.map((line) => (
    `<p class="mhws-st-line" style="font-family:${fontCss(line.font)};font-size:${line.sizePt}pt;font-weight:${line.weight};color:${line.color};text-align:${line.align}">${esc(line.text) || '&nbsp;'}</p>`
  )).join('');
  const headAlign = spec.logo.align === 'left' || spec.logo.align === 'right' ? spec.logo.align : 'center';
  const headInner = headAlign === 'left'
    ? `${logo}<div class="mhws-st-titles">${lines}</div>`
    : headAlign === 'right'
      ? `<div class="mhws-st-titles">${lines}</div>${logo}`
      : `${logo}<div class="mhws-st-titles">${lines}</div>`;
  const wm = spec.watermark.enabled && spec.watermark.src
    ? `<img class="wm" src="${esc(spec.watermark.src)}" alt="" style="opacity:${spec.watermark.opacity}">`
    : '';
  const foot = spec.footer.text
    ? `<footer class="mhws-st-foot" style="font-family:${fontCss(spec.footer.font)};font-size:${spec.footer.sizePt}pt;font-weight:${spec.footer.weight};color:${spec.footer.color}">${esc(spec.footer.text)}</footer>`
    : '<footer class="mhws-st-foot"></footer>';
  const css = `
    @page { size: ${w}mm ${h}mm; margin: 0; }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: #c5cdd8; }
    .sheet {
      position: relative;
      width: ${w}mm;
      min-height: ${h}mm;
      margin: 0 auto;
      background: ${spec.backgroundColor};
      overflow: hidden;
    }
    .pad {
      position: relative;
      z-index: 1;
      display: flex;
      flex-direction: column;
      min-height: ${h}mm;
      padding: 8mm 12mm 0;
    }
    .mhws-st-head {
      display: ${headAlign === 'center' ? 'flex' : 'grid'};
      ${headAlign === 'center' ? 'flex-direction:column;align-items:center;text-align:center;' : `grid-template-columns:${headAlign === 'left' ? 'auto 1fr' : '1fr auto'};align-items:center;gap:6mm;`}
      gap: 2.5mm;
      padding-bottom: 3.5mm;
    }
    .mhws-st-logo { display: block; height: auto; border: 0; background: transparent; }
    .mhws-st-titles { min-width: 0; width: 100%; }
    .mhws-st-line { margin: 0 0 1mm; line-height: 1.25; }
    .rule {
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      gap: 3mm;
      margin: 0 0 2.2mm;
      width: 100%;
    }
    .rule::before, .rule::after {
      content: "";
      height: 0;
      border-top: 1pt solid #0b2a56;
    }
    .rule .pip {
      width: 2.2mm;
      height: 2.2mm;
      background: #c9a227;
      transform: rotate(45deg);
      box-shadow: 0 0 0 1.2pt #fff, 0 0 0 1.7pt rgba(11, 42, 86, 0.35);
    }
    .mhws-header-gold-rule { display: none !important; }
    .body-area { flex: 1 1 auto; min-height: 40mm; }
    .mhws-st-foot {
      margin-top: auto;
      padding: 3mm 0 8mm;
      text-align: center;
    }
    img.wm {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: min(112mm, 68%);
      height: auto;
      pointer-events: none;
      z-index: 0;
    }
    ${borderCss(spec.border.style, w, h)}
  `;
  const html = `
    <div class="sheet">
      ${spec.border.style === 'tricolor' ? '<div class="mhws-st-accent"></div>' : ''}
      ${wm}
      <div class="pad">
        <header class="mhws-st-head is-${headAlign}">${headInner}</header>
        <div class="rule" aria-hidden="true"><span class="pip"></span></div>
        <div class="body-area"></div>
        ${foot}
      </div>
    </div>`;
  return { spec, css, html, widthMm: w, heightMm: h };
}

export function renderStationeryDocument(specIn, title = 'Letterhead') {
  const sheet = renderStationerySheet(specIn);
  return `<!DOCTYPE html>
<html lang="en" class="mhws-stationery-pad">
<head>
  <meta charset="UTF-8">
  <title>${esc(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@700&family=Noto+Sans:wght@400;500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
  <style>${sheet.css}</style>
</head>
<body>
${sheet.html}
</body>
</html>`;
}

export function paintStationeryPreview(host, specIn) {
  if (!host) return;
  const sheet = renderStationerySheet(specIn);
  host.style.width = `${sheet.widthMm}mm`;
  host.style.minHeight = `${sheet.heightMm}mm`;
  host.innerHTML = `<style>${sheet.css}
    .sheet { box-shadow: 0 1px 8px rgba(15,40,80,0.22); }
    html, body { background: transparent; }
  </style>${sheet.html}`;
}

export function readImageAsDataUrl(file, maxBytes = 1.2 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    if (!file || !/^image\//.test(file.type || '')) {
      reject(new Error('Choose a PNG, JPEG, GIF, or WebP image.'));
      return;
    }
    if (file.size > maxBytes) {
      reject(new Error('Image is too large (max about 1.2 MB).'));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Could not read image.'));
    reader.readAsDataURL(file);
  });
}
