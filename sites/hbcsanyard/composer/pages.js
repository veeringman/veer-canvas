/**
 * A4 (and later paper sizes) page frames in the composer.
 * Letterhead chrome is painted on every sheet; overflowing blocks move to the
 * next sheet. Grey desk gaps stay compact. Chrome nodes are stripped on save.
 */

export const PAPER_SIZES = {
  A4: { id: 'A4', widthMm: 210, heightMm: 297 },
  A5: { id: 'A5', widthMm: 148, heightMm: 210 },
  Letter: { id: 'Letter', widthMm: 215.9, heightMm: 279.4 },
};

const CHROME_MM = {
  none: { header: 0, footer: 0 },
  simple: { header: 32, footer: 22 },
  'tpl-mhws-letterhead': { header: 58, footer: 32 },
  'tpl-rwa-letterhead-blank': { header: 48, footer: 28 },
};

const CHROME_MM_DEFAULT = { header: 48, footer: 28 };

const GAP_MM = 18;

const DIAMOND_RULE = '<div class="rule" aria-hidden="true"><span class="pip"></span></div>';

const SIMPLE_HEAD = `<div class="mhws-simple-chrome">
  <div class="mhws-simple-head">
  <img src="/assets/mhws-logo/mhws-logo-seal-cert.png?v=20260822logo1" alt="">
  <h1>Mandi Housing Welfare Society</h1>
  <p class="sub">Himuda Housing Colony Sanyard</p>
  <p class="meta">Housing Colony Sanyard, Mandi HP 175001 · Registration No. 467 dated 21/07/2012</p>
</div>
${DIAMOND_RULE}
</div>`;

const SIMPLE_FOOT = `<div class="mhws-simple-foot">Unity · Harmony · Progress · Mandi Housing Welfare Society</div>`;

function chromeFor(id) {
  return CHROME_MM[id] || CHROME_MM_DEFAULT;
}

function paperFor(id) {
  return PAPER_SIZES[id] || PAPER_SIZES.A4;
}

function isPagerNode(node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
  return node.classList.contains('mhws-page-spacer')
    || node.classList.contains('mhws-page-chrome');
}

function clearPagerNodes(host) {
  host.querySelectorAll('.mhws-page-spacer, .mhws-page-chrome').forEach((el) => el.remove());
}

export function stripPageSpacers(html) {
  const raw = String(html || '');
  if (!/mhws-page-spacer|mhws-page-chrome/.test(raw)) return raw;
  if (typeof document === 'undefined') {
    return raw.replace(/<div\b[^>]*class="[^"]*\b(mhws-page-spacer|mhws-page-chrome)\b[^"]*"[^>]*>[\s\S]*?<\/div>/gi, '');
  }
  const box = document.createElement('div');
  box.innerHTML = raw;
  box.querySelectorAll('.mhws-page-spacer, .mhws-page-chrome').forEach((el) => el.remove());
  return box.innerHTML;
}

function isFlowBlock(node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
  if (isPagerNode(node)) return false;
  const tag = node.tagName;
  return /^(P|H1|H2|H3|H4|UL|OL|TABLE|BLOCKQUOTE|DIV|HR)$/.test(tag)
    || node.classList.contains('mhws-img-pair')
    || node.classList.contains('mhws-img');
}

function isEmptyBlock(el) {
  if (!el || el.tagName !== 'P') return false;
  if (el.querySelector('img, table, .mhws-img')) return false;
  return !String(el.textContent || '').replace(/\u200b/g, '').trim();
}

function contentTop(host, el, padTop) {
  const hostBox = host.getBoundingClientRect();
  const borderTop = Number.parseFloat(window.getComputedStyle(host).borderTopWidth) || 0;
  return el.getBoundingClientRect().top - hostBox.top - borderTop - padTop;
}

function currentParts(opts, chromeId) {
  const parts = typeof opts.getChromeParts === 'function' ? (opts.getChromeParts() || {}) : {};
  const id = chromeId || parts.id || 'simple';
  if (id === 'none') {
    return { id, headerHtml: '', footerHtml: '', chromeCss: '', watermarkUrl: '' };
  }
  let headerHtml = String(parts.headerHtml || '').trim();
  let footerHtml = String(parts.footerHtml || '').trim();
  if (id === 'simple' || !headerHtml) {
    headerHtml = headerHtml || SIMPLE_HEAD;
    footerHtml = footerHtml || SIMPLE_FOOT;
  }
  const showWm = typeof opts.getWatermark === 'function' ? opts.getWatermark() : true;
  let watermarkUrl = showWm ? String(parts.watermarkUrl || '').trim() : '';
  if (showWm && !watermarkUrl && id !== 'simple' && id !== 'none') {
    watermarkUrl = '/assets/mhws-logo/mhws-logo-watermark.png?v=20260811wm8';
  }
  return {
    id,
    headerHtml,
    footerHtml,
    chromeCss: String(parts.chromeCss || ''),
    watermarkUrl,
  };
}

const COMPOSE_OFFICERS_CSS = `
  .sheet[data-layout="top"] .officers,
  .officers {
    display: grid !important;
    grid-template-columns: repeat(4, 1fr);
    column-gap: 0;
    align-items: start;
    justify-items: center;
    margin: 0 0 1.6mm;
    width: 100%;
    padding: 0;
  }
  .sheet[data-layout="top"] .role,
  .officers .role {
    text-align: center;
    min-width: 0;
    width: 100%;
    padding: 0 2mm;
    position: relative;
    align-self: start;
  }
  .sheet[data-layout="top"] .role:not(:last-child)::after,
  .officers .role:not(:last-child)::after {
    content: "";
    position: absolute;
    top: 10%;
    bottom: 10%;
    right: 0;
    width: 0;
    border-right: 0.7pt solid rgba(11, 42, 86, 0.14);
  }
  .sheet[data-layout="top"] .officers + .rule,
  .officers + .rule {
    display: grid !important;
    margin: 0 0 1.6mm;
  }
  .officers-foot,
  .mhws-header-gold-rule {
    display: none !important;
  }
  .rule {
    display: grid !important;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 3mm;
    margin: 0 0 2.2mm;
    width: 100%;
  }
  .rule::before,
  .rule::after {
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
  .head,
  .mhws-st-head,
  .mhws-simple-head,
  .org,
  .brand {
    border-bottom: none !important;
  }
`;

function hasOfficersBlock(html) {
  return /\bclass="[^"]*\bofficers\b/.test(String(html || ''));
}

/** Pad CSS targets `.sheet[data-layout="top"]`; extracted header fragments omit that wrapper. */
function wrapPadChrome(html) {
  const raw = String(html || '').trim();
  if (!raw || !hasOfficersBlock(raw)) return raw;
  if (/\bclass="[^"]*\bsheet\b/.test(raw)) return raw;
  return `<div class="sheet" data-layout="top"><div class="pad">${raw}</div></div>`;
}

function filledChromeHeight(el) {
  const inner = el.shadowRoot?.querySelector('.mhws-chrome-inner') || el;
  return Math.ceil(inner.getBoundingClientRect().height);
}

function fillExact(el, html, css) {
  el.innerHTML = '';
  const chromeHtml = wrapPadChrome(html);
  const officersCss = css ? COMPOSE_OFFICERS_CSS : '';
  if (css) {
    const root = el.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>
      ${css}
      ${officersCss}
      :host { display: block; }
      html, body, .sheet, .pad {
        min-height: 0 !important;
        height: auto !important;
        max-height: none !important;
        overflow: visible !important;
        margin: 0 !important;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
      }
      .screen-hint, .layout-picker { display: none !important; }
      img.wm { display: none !important; }
    </style><div class="mhws-chrome-inner">${chromeHtml}</div>`;
    return;
  }
  el.innerHTML = chromeHtml || '';
}

function measureChrome(wrap, html, css, widthPx) {
  const probe = document.createElement('div');
  probe.style.cssText = `position:absolute;left:-99999px;top:0;width:${Math.max(120, widthPx)}px;visibility:hidden;pointer-events:none`;
  wrap.append(probe);
  fillExact(probe, html, css);
  const inner = probe.shadowRoot?.querySelector('.mhws-chrome-inner') || probe;
  const h = Math.ceil(inner.getBoundingClientRect().height);
  probe.remove();
  return Math.max(0, h);
}

function chromeBandPx(wrap, html, css, widthPx, fallbackMm, mmPx) {
  if (!html) return 0;
  let px = measureChrome(wrap, html, css, widthPx);
  if (px < 8) px = mmPx * fallbackMm;
  return Math.ceil(px + mmPx * 1.2);
}

function ensureFrameLayer(wrap) {
  let layer = wrap.querySelector(':scope > .mhws-page-frames');
  if (!layer) {
    layer = document.createElement('div');
    layer.className = 'mhws-page-frames';
    layer.setAttribute('aria-hidden', 'true');
    wrap.insertBefore(layer, wrap.firstChild);
  }
  return layer;
}

function applyWatermark(host, url, pageCount, pagePx, gapPx) {
  if (!url || pageCount < 1) {
    host.style.backgroundImage = '';
    host.style.backgroundPosition = '';
    host.style.backgroundSize = '';
    host.style.backgroundRepeat = '';
    host.style.backgroundOrigin = '';
    host.style.backgroundClip = '';
    return;
  }
  const stride = pagePx + gapPx;
  const layers = Array.from({ length: pageCount }, () => `url("${url}")`);
  host.style.backgroundImage = layers.join(',');
  host.style.backgroundRepeat = Array.from({ length: pageCount }, () => 'no-repeat').join(',');
  host.style.backgroundOrigin = Array.from({ length: pageCount }, () => 'border-box').join(',');
  host.style.backgroundClip = Array.from({ length: pageCount }, () => 'border-box').join(',');
  host.style.backgroundPosition = Array.from({ length: pageCount }, (_, i) => (
    `center ${i * stride + pagePx * 0.5}px`
  )).join(',');
  host.style.backgroundSize = Array.from({ length: pageCount }, () => 'min(112mm, 70%) auto').join(',');
}

function marginBox(heightPx) {
  const box = document.createElement('div');
  box.className = 'mhws-page-chrome-margin';
  box.style.height = `${Math.max(0, heightPx)}px`;
  return box;
}

function accurateChromePx(wrap, html, css, widthPx, fallbackMm, mmPx, chromeId) {
  if (!html) return 0;
  const probe = document.createElement('div');
  probe.style.cssText = `position:absolute;left:-9999px;top:0;width:${Math.max(120, widthPx)}px;visibility:hidden;pointer-events:none`;
  (wrap || document.body).append(probe);
  const tpl = document.createElement('div');
  tpl.className = `mhws-page-chrome-tpl is-${chromeId || 'simple'}`;
  fillExact(tpl, html, css);
  probe.append(tpl);
  const px = Math.max(0, filledChromeHeight(tpl));
  probe.remove();
  if (px < 8) return Math.ceil(mmPx * fallbackMm);
  return px;
}

function paintFrames(wrap, host, spec) {
  const layer = ensureFrameLayer(wrap);
  const {
    pageCount, pagePx, gapPx, headerPx, footerPx, marginTopPx, marginBottomPx,
    headerHtml, footerHtml, chromeCss, chromeId,
  } = spec;
  layer.style.left = `${host.offsetLeft}px`;
  layer.style.top = `${host.offsetTop}px`;
  layer.style.width = `${host.offsetWidth}px`;
  const sheetStride = pageCount * pagePx + Math.max(0, pageCount - 1) * gapPx;
  layer.style.height = `${Math.max(host.offsetHeight, sheetStride)}px`;
  layer.dataset.chrome = chromeId;
  layer.innerHTML = '';
  let maxHeadPx = headerPx;
  let maxFootPx = footerPx;
  for (let i = 0; i < pageCount; i += 1) {
    const y = i * (pagePx + gapPx);
    const head = document.createElement('div');
    head.className = 'mhws-page-frame-head';
    head.style.top = `${y}px`;
    const tpl = document.createElement('div');
    tpl.className = `mhws-page-chrome-tpl is-${chromeId}`;
    fillExact(tpl, headerHtml, chromeCss);
    const actualHeadPx = Math.max(headerPx, filledChromeHeight(tpl));
    maxHeadPx = Math.max(maxHeadPx, actualHeadPx);
    head.style.height = `${actualHeadPx + marginTopPx}px`;
    head.append(tpl);
    head.append(marginBox(marginTopPx));
    layer.append(head);
    const foot = document.createElement('div');
    foot.className = 'mhws-page-frame-foot';
    foot.append(marginBox(marginBottomPx));
    const ftpl = document.createElement('div');
    ftpl.className = `mhws-page-chrome-tpl is-${chromeId}`;
    fillExact(ftpl, footerHtml, chromeCss);
    const actualFootPx = Math.max(footerPx, filledChromeHeight(ftpl));
    maxFootPx = Math.max(maxFootPx, actualFootPx);
    foot.style.height = `${actualFootPx + marginBottomPx}px`;
    foot.style.top = `${y + pagePx - (actualFootPx + marginBottomPx)}px`;
    foot.append(ftpl);
    layer.append(foot);
  }
  return { headPx: maxHeadPx, footPx: maxFootPx };
}

function makeBreak(pageNo, leftover, footerBand, gapPx, headerBand, padLeft, padRight) {
  const spacer = document.createElement('div');
  spacer.className = 'mhws-page-spacer';
  spacer.contentEditable = 'false';
  spacer.setAttribute('data-label', `Page ${pageNo}`);
  const rest = Math.max(0, leftover);
  spacer.style.height = `${rest + footerBand + gapPx + headerBand}px`;
  spacer.style.marginLeft = `-${padLeft}px`;
  spacer.style.marginRight = `-${padRight}px`;
  spacer.style.width = `calc(100% + ${padLeft + padRight}px)`;
  spacer.innerHTML = `${rest > 0.5 ? `<div class="mhws-page-spacer-rest" style="height:${rest}px"></div>` : ''}
    <div class="mhws-page-spacer-foot" style="height:${footerBand}px"></div>
    <div class="mhws-page-gap" data-label="Page ${pageNo}" style="height:${gapPx}px"></div>
    <div class="mhws-page-spacer-head" style="height:${headerBand}px"></div>`;
  return spacer;
}

export function attachPager(host, opts = {}) {
  if (!host) return { refresh() {}, schedule() {}, setChrome() {}, setPaper() {}, destroy() {} };
  const wrap = host.parentElement;
  if (wrap) wrap.classList.add('mhws-composer-desk');
  host.classList.add('is-paged');

  let chromeId = opts.getChromeId ? opts.getChromeId() : (opts.chromeId || 'simple');
  let paperId = opts.paper || 'A4';
  let timer = 0;
  let paging = false;

  function currentChrome() {
    if (typeof opts.getChromeId === 'function') return opts.getChromeId() || chromeId || 'simple';
    return chromeId || 'simple';
  }

  function applyPaperBox() {
    const paper = paperFor(paperId);
    host.dataset.paper = paper.id;
    host.dataset.chrome = currentChrome();
    host.style.width = `${paper.widthMm}mm`;
    host.style.maxWidth = 'none';
    host.style.minHeight = `${paper.heightMm}mm`;
  }

  function paginate() {
    if (paging) return;
    paging = true;
    host.dataset.mhwsPaging = '1';
    const wasEditable = host.getAttribute('contenteditable');
    host.setAttribute('contenteditable', 'false');
    try {
      if (typeof opts.saveSelection === 'function') opts.saveSelection();
      clearPagerNodes(host);
      applyPaperBox();
      const paper = paperFor(paperId);
      const chromeIdNow = currentChrome();
      const margins = opts.getMargins ? opts.getMargins() : { top: 16, right: 16, bottom: 16, left: 16 };
      const parts = currentParts(opts, chromeIdNow);
      const hostBox = host.getBoundingClientRect();
      const mmPx = hostBox.width / paper.widthMm;
      const pagePx = Math.max(120, mmPx * paper.heightMm);
      const gapPx = Math.max(8, mmPx * GAP_MM);
      const fallback = chromeFor(chromeIdNow);
      let headerPx = 0;
      let footerPx = 0;
      const cachedChrome = host.dataset.mhwsLayoutChrome || '';
      if (cachedChrome === chromeIdNow && host.dataset.mhwsHeadPx) {
        headerPx = Number(host.dataset.mhwsHeadPx) || 0;
        footerPx = Number(host.dataset.mhwsFootPx) || 0;
      }
      if (parts.headerHtml && !headerPx) {
        headerPx = accurateChromePx(wrap || host, parts.headerHtml, parts.chromeCss, hostBox.width, fallback.header, mmPx, chromeIdNow);
      }
      if (parts.footerHtml && !footerPx) {
        footerPx = accurateChromePx(wrap || host, parts.footerHtml, parts.chromeCss, hostBox.width, fallback.footer, mmPx, chromeIdNow);
      }
      host.style.padding = `${headerPx + mmPx * margins.top}px ${margins.right}mm ${footerPx + mmPx * margins.bottom}px ${margins.left}mm`;
      const cs = window.getComputedStyle(host);
      const padTop = Number.parseFloat(cs.paddingTop) || 0;
      const padBottom = Number.parseFloat(cs.paddingBottom) || 0;
      const padLeft = Number.parseFloat(cs.paddingLeft) || 0;
      const padRight = Number.parseFloat(cs.paddingRight) || 0;
      const writable = pagePx - padTop - padBottom;
      if (writable < 48) return;
      const stride = pagePx + gapPx;
      const blocks = [...host.children].filter(isFlowBlock);
      let page = 0;
      let pageNo = 2;
      blocks.forEach((block, index) => {
        if (isEmptyBlock(block) && index === blocks.length - 1) return;
        const top = contentTop(host, block, padTop);
        const height = block.getBoundingClientRect().height;
        const limit = page * stride + writable;
        if (top + height <= limit + 1) return;
        if (index === 0 || top <= page * stride + 8) {
          page += 1;
          pageNo += 1;
          return;
        }
        const target = (page + 1) * stride;
        const expected = padBottom + gapPx + padTop;
        const leftover = Math.max(0, (writable - (top - page * stride)));
        const push = target - top;
        if (push < 4) return;
        const spacer = makeBreak(pageNo, leftover, padBottom, gapPx, padTop, padLeft, padRight);
        if (Math.abs(push - (leftover + expected)) > 2) {
          spacer.style.height = `${push}px`;
        }
        host.insertBefore(spacer, block);
        page += 1;
        pageNo += 1;
      });
      const pageCount = page + 1;
      const sheetMm = pageCount * paper.heightMm + (pageCount - 1) * GAP_MM;
      host.style.height = `${sheetMm}mm`;
      host.style.minHeight = `${sheetMm}mm`;
      host.style.boxSizing = 'border-box';
      if (wrap && (parts.headerHtml || parts.footerHtml)) {
        const framed = paintFrames(wrap, host, {
          pageCount,
          pagePx,
          gapPx,
          headerPx,
          footerPx,
          marginTopPx: mmPx * margins.top,
          marginBottomPx: mmPx * margins.bottom,
          headerHtml: parts.headerHtml,
          footerHtml: parts.footerHtml,
          chromeCss: parts.chromeCss,
          chromeId: parts.id,
        });
        const padHead = framed.headPx + mmPx * margins.top;
        const padFoot = framed.footPx + mmPx * margins.bottom;
        host.dataset.mhwsLayoutChrome = chromeIdNow;
        host.dataset.mhwsHeadPx = String(framed.headPx);
        host.dataset.mhwsFootPx = String(framed.footPx);
        host.style.padding = `${padHead}px ${margins.right}mm ${padFoot}px ${margins.left}mm`;
        if (
          (Math.abs(framed.headPx - headerPx) > 1 || Math.abs(framed.footPx - footerPx) > 1)
          && !host.dataset.mhwsRepaginate
        ) {
          host.dataset.mhwsRepaginate = '1';
          window.requestAnimationFrame(() => {
            delete host.dataset.mhwsRepaginate;
            paginate();
          });
        }
      } else {
        wrap?.querySelector(':scope > .mhws-page-frames')?.replaceChildren();
      }
      applyWatermark(host, parts.watermarkUrl, pageCount, pagePx, gapPx);
      host.classList.toggle('has-watermark', Boolean(parts.watermarkUrl));
      if (typeof opts.restoreSelection === 'function') opts.restoreSelection();
    } finally {
      if (wasEditable !== 'false') host.setAttribute('contenteditable', wasEditable || 'true');
      delete host.dataset.mhwsPaging;
      paging = false;
    }
  }

  function schedule() {
    window.clearTimeout(timer);
    timer = window.setTimeout(paginate, 100);
  }

  function refresh() {
    window.clearTimeout(timer);
    paginate();
  }

  const ro = typeof ResizeObserver === 'function'
    ? new ResizeObserver(() => schedule())
    : null;
  if (ro && wrap) ro.observe(wrap);

  function onProtectKey(event) {
    if (event.key !== 'Backspace' && event.key !== 'Delete') return;
    const sel = window.getSelection();
    if (!sel || !sel.isCollapsed || !sel.rangeCount || !host.contains(sel.anchorNode)) return;
    const range = sel.getRangeAt(0);
    if (event.key === 'Backspace' && range.startOffset === 0) {
      let el = range.startContainer;
      if (el.nodeType === Node.TEXT_NODE) el = el.parentElement;
      while (el && el !== host && !el.previousElementSibling) el = el.parentElement;
      if (el && el !== host && isPagerNode(el.previousElementSibling)) {
        event.preventDefault();
      }
    }
  }
  host.addEventListener('keydown', onProtectKey, true);

  applyPaperBox();
  window.requestAnimationFrame(paginate);

  return {
    refresh,
    schedule,
    setChrome(id) {
      chromeId = id || 'simple';
      delete host.dataset.mhwsLayoutChrome;
      delete host.dataset.mhwsHeadPx;
      delete host.dataset.mhwsFootPx;
      delete host.dataset.mhwsRepaginate;
      refresh();
    },
    setPaper(id) {
      paperId = PAPER_SIZES[id] ? id : 'A4';
      refresh();
    },
    destroy() {
      window.clearTimeout(timer);
      if (ro) ro.disconnect();
      host.removeEventListener('keydown', onProtectKey, true);
      clearPagerNodes(host);
      wrap?.querySelector(':scope > .mhws-page-frames')?.remove();
      host.classList.remove('is-paged');
    },
  };
}
