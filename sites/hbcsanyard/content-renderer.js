/**
 * VeerLabs rich content renderer — sections, markdown, HTML, mermaid, layout.
 */
(function (global) {
  const ALIGN_CLASSES = {
    left: 'content-align-left',
    center: 'content-align-center',
    right: 'content-align-right',
    justify: 'content-align-justify',
  };

  const SIZE_CLASSES = {
    sm: 'content-size-sm',
    md: 'content-size-md',
    lg: 'content-size-lg',
    xl: 'content-size-xl',
    full: 'content-size-full',
  };

  let mermaidInitialized = false;

  function escapeHtml(unsafe) {
    return String(unsafe || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));
  }

  function stripHtml(text) {
    const el = document.createElement('div');
    el.innerHTML = text;
    return (el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function normalizeAssetPath(src, slug) {
    if (!src || typeof src !== 'string') return src;
    const value = src.trim();
    if (!value || value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:')) {
      return value;
    }
    if (value.startsWith('miniapps/') || value.startsWith('assets/')) return value;
    const cleaned = value.replace(/^\.\//, '');
    if (cleaned.startsWith('docs/') || cleaned.startsWith('assets/') || cleaned.startsWith('images/')) {
      return slug ? `miniapps/${slug}/${cleaned}` : cleaned;
    }
    return slug ? `miniapps/${slug}/${cleaned}` : cleaned;
  }

  function convertMermaidFences(text) {
    return String(text || '').replace(/```mermaid\s*\n([\s\S]*?)```/gi, (_, code) => {
      return `<div class="mermaid">${escapeHtml(code.trim())}</div>`;
    });
  }

  function detectFormat(body, explicitFormat) {
    if (explicitFormat) return explicitFormat;
    const trimmed = String(body || '').trim();
    if (!trimmed) return 'markdown';
    if (trimmed.startsWith('<')) return 'html';
    if (/^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(-v2)?|erDiagram|gantt|pie|journey|gitGraph|mindmap|timeline|C4Context|C4Container)\b/m.test(trimmed)) {
      return 'mermaid';
    }
    return 'markdown';
  }

  function inlineReplacements(text, context) {
    if (!text) return '';
    const slug = context && context.slug;
    return String(text)
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
        const safe = normalizeAssetPath(url, slug);
        return `<img src="${safe}" alt="${escapeHtml(alt)}" class="inline-img logo-frame content-img"/>`;
      })
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
        const href = url.startsWith('http') ? url : normalizeAssetPath(url, slug);
        return `<a href="${href}" rel="noopener noreferrer">${label}</a>`;
      })
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  }

  function renderMarkdownTable(lines) {
    if (lines.length < 2) return '';
    const rows = lines.map(line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim()));
    const divider = rows[1].every(cell => /^:?-{3,}:?$/.test(cell));
    const header = rows[0];
    const bodyRows = divider ? rows.slice(2) : rows.slice(1);
    let html = '<div class="table-wrap"><table class="content-table"><thead><tr>';
    header.forEach(cell => { html += `<th>${inlineReplacements(cell, {})}</th>`; });
    html += '</tr></thead><tbody>';
    bodyRows.forEach(row => {
      html += '<tr>';
      row.forEach(cell => { html += `<td>${inlineReplacements(cell, {})}</td>`; });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    return html;
  }

  function renderMarkdown(md, context) {
    if (!md) return '';
    const lines = String(md).split('\n');
    let out = '';
    let inList = false;
    let inCode = false;
    let codeLang = '';
    let codeBuffer = [];
    let tableBuffer = [];

    function flushTable() {
      if (!tableBuffer.length) return;
      out += renderMarkdownTable(tableBuffer);
      tableBuffer = [];
    }

    function flushCode() {
      if (!codeBuffer.length) return;
      const code = codeBuffer.join('\n');
      if (codeLang === 'mermaid') {
        out += `<div class="mermaid">${escapeHtml(code)}</div>`;
      } else {
        out += `<pre class="code-block"><code>${escapeHtml(code)}</code></pre>`;
      }
      codeBuffer = [];
      codeLang = '';
    }

    for (let i = 0; i < lines.length; i += 1) {
      const line = lines[i];
      const fence = line.match(/^```(\w+)?\s*$/);
      if (fence) {
        if (inCode) {
          inCode = false;
          flushCode();
        } else {
          if (inList) { out += '</ul>'; inList = false; }
          flushTable();
          inCode = true;
          codeLang = (fence[1] || '').toLowerCase();
        }
        continue;
      }

      if (inCode) {
        codeBuffer.push(line);
        continue;
      }

      if (line.trim().startsWith('|')) {
        if (inList) { out += '</ul>'; inList = false; }
        tableBuffer.push(line);
        continue;
      }
      flushTable();

      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim())) {
        if (inList) { out += '</ul>'; inList = false; }
        out += '<hr class="content-divider"/>';
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        if (inList) { out += '</ul>'; inList = false; }
        const level = Math.min(6, heading[1].length + 2);
        out += `<h${level}>${inlineReplacements(heading[2], context)}</h${level}>`;
        continue;
      }

      const quote = line.match(/^>\s?(.*)$/);
      if (quote) {
        if (inList) { out += '</ul>'; inList = false; }
        out += `<blockquote class="content-quote"><p>${inlineReplacements(quote[1], context)}</p></blockquote>`;
        continue;
      }

      const li = line.match(/^\s*([*\-+]|\d+\.)\s+(.*)$/);
      if (li) {
        if (!inList) { out += '<ul class="section-list">'; inList = true; }
        out += `<li>${inlineReplacements(li[2], context)}</li>`;
        continue;
      }

      if (inList) { out += '</ul>'; inList = false; }
      if (line.trim() === '') continue;
      out += `<p>${inlineReplacements(line, context)}</p>`;
    }

    if (inList) out += '</ul>';
    flushTable();
    if (inCode) flushCode();
    return out;
  }

  function renderMermaidBody(body) {
    const code = String(body || '').trim();
    return `<div class="mermaid">${escapeHtml(code)}</div>`;
  }

  function renderBody(body, section, context) {
    const format = detectFormat(body, section && section.format);
    let html = '';
    if (format === 'mermaid') {
      html = renderMermaidBody(body);
    } else if (format === 'html') {
      html = convertMermaidFences(body);
    } else {
      html = renderMarkdown(body, context);
    }
    return convertMermaidFences(html);
  }

  function normalizeAssetsInElement(root, slug) {
    if (!root) return;
    root.querySelectorAll('img[src]').forEach(img => {
      const src = img.getAttribute('src');
      const normalized = normalizeAssetPath(src, slug);
      if (normalized) img.setAttribute('src', normalized);
      img.classList.add('inline-img', 'content-img');
      if (!img.classList.contains('logo-frame')) img.classList.add('logo-frame');
      const width = img.getAttribute('width');
      if (width && !img.style.maxWidth) {
        img.style.maxWidth = `${width}px`;
      }
    });
    root.querySelectorAll('a[href]').forEach(link => {
      const href = link.getAttribute('href');
      if (href && !href.startsWith('http') && !href.startsWith('#') && !href.startsWith('mailto:')) {
        link.setAttribute('href', normalizeAssetPath(href, slug));
      }
    });
  }

  function applyLayoutClasses(el, section) {
    if (!el || !section) return;
    const align = section.align || section.alignment;
    if (align && ALIGN_CLASSES[align]) el.classList.add(ALIGN_CLASSES[align]);
    const size = section.size || section.contentSize;
    if (size && SIZE_CLASSES[size]) el.classList.add(SIZE_CLASSES[size]);
    if (section.className) {
      section.className.split(/\s+/).filter(Boolean).forEach(cls => el.classList.add(cls));
    }
    if (section.width) el.style.maxWidth = /^\d+$/.test(String(section.width)) ? `${section.width}px` : String(section.width);
    if (section.style) el.setAttribute('style', `${el.getAttribute('style') || ''}${section.style}`);
  }

  function renderItemContent(item, context) {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return '';
    const body = item.text || item.body || '';
    const format = detectFormat(body, item.format);
    if (format === 'html') return convertMermaidFences(body);
    if (format === 'mermaid') return renderMermaidBody(body);
    return renderMarkdown(body, context);
  }

  function createSection(section, context) {
    const sectionEl = document.createElement('section');
    sectionEl.className = 'section content-panel';
    applyLayoutClasses(sectionEl, section);

    if (section.id) sectionEl.id = section.id;
    if (section.title) {
      const heading = document.createElement('h2');
      heading.className = 'section-title';
      if (section.titleAlign && ALIGN_CLASSES[section.titleAlign]) {
        heading.classList.add(ALIGN_CLASSES[section.titleAlign]);
      }
      heading.textContent = section.title;
      sectionEl.appendChild(heading);
    }

    if (section.body) {
      const div = document.createElement('div');
      div.className = 'section-body rich-content';
      applyLayoutClasses(div, {
        align: section.bodyAlign || section.align,
        size: section.bodySize || section.size,
        className: section.bodyClassName,
        width: section.bodyWidth,
        style: section.bodyStyle,
      });
      div.innerHTML = renderBody(section.body, section, context);
      normalizeAssetsInElement(div, context && context.slug);
      sectionEl.appendChild(div);
    }

    if (Array.isArray(section.items) && section.items.length) {
      const list = document.createElement('ul');
      list.className = 'section-list rich-content';
      applyLayoutClasses(list, { align: section.itemsAlign || section.align });
      section.items.forEach(item => {
        const li = document.createElement('li');
        const rendered = renderItemContent(item, context);
        if (/<[a-z][\s\S]*>/i.test(rendered)) {
          li.innerHTML = rendered;
          normalizeAssetsInElement(li, context && context.slug);
        } else {
          li.textContent = rendered;
        }
        list.appendChild(li);
      });
      sectionEl.appendChild(list);
    }

    if (Array.isArray(section.blocks)) {
      section.blocks.forEach(block => {
        sectionEl.appendChild(createSection({ ...block, title: block.title || '' }, context));
      });
    }

    return sectionEl;
  }

  function renderSummaryElement(summary, options) {
    const el = document.createElement('div');
    el.className = 'project-lead rich-content';
    const context = { slug: options && options.slug };
    const format = (options && options.summaryFormat) || detectFormat(summary, options && options.format);
    if (format === 'html') {
      el.innerHTML = convertMermaidFences(summary);
    } else if (format === 'markdown') {
      el.innerHTML = renderMarkdown(summary, context);
    } else if (format === 'mermaid') {
      el.innerHTML = renderMermaidBody(summary);
    } else {
      el.textContent = summary;
    }
    normalizeAssetsInElement(el, context.slug);
    applyLayoutClasses(el, options || {});
    return el;
  }

  function summaryPlainText(summary, options) {
    const format = (options && options.summaryFormat) || detectFormat(summary, options && options.format);
    if (format === 'text' || !summary) return String(summary || '');
    return stripHtml(renderSummaryElement(summary, options).innerHTML);
  }

  async function waitForMermaid(timeoutMs = 8000) {
    if (typeof global.mermaid !== 'undefined') return global.mermaid;
    const started = Date.now();
    return new Promise((resolve) => {
      const tick = () => {
        if (typeof global.mermaid !== 'undefined') {
          resolve(global.mermaid);
          return;
        }
        if (Date.now() - started >= timeoutMs) {
          resolve(null);
          return;
        }
        setTimeout(tick, 50);
      };
      tick();
    });
  }

  async function initMermaid(root) {
    if (!root) return;
    const nodes = Array.from(root.querySelectorAll('.mermaid')).filter((node) => {
      return !node.getAttribute('data-processed') && !node.dataset.mermaidError;
    });
    if (!nodes.length) return;

    const mermaid = await waitForMermaid();
    if (!mermaid) {
      nodes.forEach((node) => {
        node.dataset.mermaidError = 'true';
        node.innerHTML = `<pre class="code-block mermaid-error">Mermaid library failed to load.</pre>`;
      });
      return;
    }

    if (!mermaidInitialized) {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        securityLevel: 'loose',
        fontFamily: '"Plus Jakarta Sans", system-ui, sans-serif',
        flowchart: { htmlLabels: true, curve: 'basis' },
      });
      mermaidInitialized = true;
    }

    nodes.forEach((node, index) => {
      if (!node.id) node.id = `mermaid-${Date.now()}-${index}`;
      // Mermaid expects plain diagram text; keep whitespace intact.
      node.textContent = (node.textContent || '').trim();
    });

    try {
      if (typeof mermaid.run === 'function') {
        await mermaid.run({ nodes });
      } else if (typeof mermaid.init === 'function') {
        mermaid.init(undefined, nodes);
      }
    } catch (error) {
      // Retry one node at a time so one bad diagram does not blank the rest.
      for (const node of nodes) {
        if (node.getAttribute('data-processed')) continue;
        try {
          if (typeof mermaid.run === 'function') {
            await mermaid.run({ nodes: [node] });
          }
        } catch (nodeError) {
          node.dataset.mermaidError = 'true';
          node.innerHTML = `<pre class="code-block mermaid-error">${escapeHtml(nodeError.message || error.message || 'Mermaid render failed')}</pre>`;
        }
      }
    }
  }

  async function renderProjectContent(container, project) {
    if (!container || !project) return;
    container.innerHTML = '';
    const context = { slug: project.slug };

    if (project.summary) {
      container.appendChild(renderSummaryElement(project.summary, {
        slug: project.slug,
        summaryFormat: project.summaryFormat,
        align: project.summaryAlign,
        size: project.summarySize,
      }));
    }

    if (Array.isArray(project.details)) {
      project.details.forEach(detail => container.appendChild(createSection(detail, context)));
    }

    await initMermaid(container);
  }

  global.VeerContent = {
    ALIGN_CLASSES,
    SIZE_CLASSES,
    escapeHtml,
    stripHtml,
    normalizeAssetPath,
    convertMermaidFences,
    detectFormat,
    renderMarkdown,
    renderBody,
    createSection,
    renderSummaryElement,
    summaryPlainText,
    initMermaid,
    renderProjectContent,
  };
})(window);
