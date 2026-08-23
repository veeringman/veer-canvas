import { createDomDriver } from './driver-dom.js';
import { renderToolbar } from './toolbar.js';
import { attachTableUi } from './table-ui.js';
import { attachImageUi } from './image-ui.js';
import { attachClipboard } from './clipboard.js';
import { attachPager } from './pages.js';
import { registry } from './registry.js';

const IMAGE_MAX_BYTES = 1.2 * 1024 * 1024;

function readImageAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file || !/^image\//.test(file.type || '')) {
      reject(new Error('Choose a PNG, JPEG, GIF, or WebP image.'));
      return;
    }
    if (file.size > IMAGE_MAX_BYTES) {
      reject(new Error('Image is too large (max about 1.2 MB).'));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Could not read image.'));
    reader.readAsDataURL(file);
  });
}

/**
 * @param {{ host: HTMLElement, toolbar: HTMLElement, imageInput?: HTMLInputElement, driver?: object, onDirty?: Function }} opts
 */
export function createSession(opts) {
  const host = opts.host;
  const toolbar = opts.toolbar;
  const imageInput = opts.imageInput;
  const driver = opts.driver || createDomDriver(host);
  driver.mount();

  const pager = attachPager(host, {
    paper: opts.paper || 'A4',
    getChromeId: opts.getChromeId,
    getChromeParts: opts.getChromeParts,
    getWatermark: opts.getWatermark,
    getMargins: () => (driver.getPageMargins ? driver.getPageMargins() : { top: 16, right: 16, bottom: 16, left: 16 }),
    saveSelection: () => driver.saveSelection && driver.saveSelection(),
    restoreSelection: () => driver.restoreSelection && driver.restoreSelection(),
  });

  const pickImage = () => {
    if (!imageInput) return;
    imageInput.value = '';
    imageInput.click();
  };

  const textarea = opts.textarea || null;
  const onInput = () => {
    if (host.dataset.mhwsPaging === '1') return;
    if (textarea) textarea.value = driver.getHTML();
    if (typeof opts.onDirty === 'function') opts.onDirty();
    pager.schedule();
  };

  renderToolbar(toolbar, driver, { onImageFile: pickImage });
  const onToolbarPointer = () => driver.saveSelection();
  toolbar.addEventListener('mousedown', onToolbarPointer, true);
  const tableUi = attachTableUi({ host, toolbar, driver, onChange: onInput });
  const imageUi = attachImageUi({ host, toolbar, driver, onChange: onInput });
  const clipboard = attachClipboard(host);

  if (imageInput) {
    imageInput.addEventListener('change', () => {
      const file = imageInput.files && imageInput.files[0];
      if (!file) return;
      readImageAsDataUrl(file)
        .then((src) => {
          driver.focus();
          driver.run('insertImage', src);
        })
        .catch((err) => {
          window.alert(err.message || 'Image failed');
        });
    });
  }

  host.addEventListener('input', onInput);

  const syncBlockSelect = () => {
    if (!host.contains(window.getSelection()?.anchorNode)) return;
    const select = toolbar.querySelector('[data-group="block"] select');
    if (select && document.activeElement !== select) {
      let node = driver.currentBlock && driver.currentBlock();
      let value = 'paragraph';
      while (node && node !== host) {
        if (node.tagName === 'H2') { value = 'h2'; break; }
        if (node.tagName === 'H3') { value = 'h3'; break; }
        if (node.tagName === 'BLOCKQUOTE') { value = 'blockquote'; break; }
        if (node.tagName === 'P') { value = 'paragraph'; break; }
        node = node.parentElement;
      }
      if (select.value !== value) select.value = value;
    }
    const fontSel = toolbar.querySelector('select[data-command="fontFamily"]');
    const sizeSel = toolbar.querySelector('select[data-command="fontSize"]');
    let styleNode = window.getSelection()?.anchorNode;
    if (styleNode?.nodeType === Node.TEXT_NODE) styleNode = styleNode.parentElement;
    if (!styleNode || !host.contains(styleNode)) return;
    const cs = window.getComputedStyle(styleNode);
    if (fontSel && document.activeElement !== fontSel) {
      const fam = (cs.fontFamily || '').toLowerCase().replace(/['"]/g, '');
      const hit = [...fontSel.options].find((o) => {
        const name = o.value.toLowerCase().replace(/['"]/g, '').split(',')[0].trim();
        return name && fam.includes(name);
      });
      if (hit && fontSel.value !== hit.value) fontSel.value = hit.value;
    }
    if (sizeSel && document.activeElement !== sizeSel) {
      const px = Number.parseFloat(cs.fontSize) || 0;
      const pt = px * 72 / 96;
      let best = null;
      let bestDiff = Infinity;
      [...sizeSel.options].forEach((o) => {
        const n = Number.parseFloat(o.value);
        if (!n) return;
        const d = Math.abs(n - pt);
        if (d < bestDiff) {
          bestDiff = d;
          best = o;
        }
      });
      if (best && bestDiff < 1.25 && sizeSel.value !== best.value) sizeSel.value = best.value;
    }
  };
  document.addEventListener('selectionchange', syncBlockSelect);

  return {
    driver,
    registry,
    applyStarter(starter) {
      if (!starter) return;
      driver.setHTML(starter.bodyHtml || '<p></p>');
      driver.focus();
      pager.refresh();
      onInput();
    },
    getHTML() {
      return driver.getHTML();
    },
    setHTML(html) {
      driver.setHTML(html);
      pager.refresh();
      if (textarea) textarea.value = driver.getHTML();
    },
    setChrome(id) {
      pager.setChrome(id);
    },
    setPaper(id) {
      pager.setPaper(id);
    },
    isEmpty() {
      const html = String(driver.getHTML() || '');
      if (/<img\b/i.test(html)) return false;
      const text = html
        .replace(/<[^>]+>/g, ' ')
        .replace(/&nbsp;/gi, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      return !text;
    },
    focus() {
      driver.focus();
    },
    destroy() {
      host.removeEventListener('input', onInput);
      document.removeEventListener('selectionchange', syncBlockSelect);
      toolbar.removeEventListener('mousedown', onToolbarPointer, true);
      pager.destroy();
      tableUi.destroy();
      imageUi.destroy();
      clipboard.destroy();
      driver.destroy();
    },
  };
}
