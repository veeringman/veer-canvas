/** 24×24 stroke icons for the composer toolbar. */
const SVG_ATTR = 'viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

const PATHS = {
  undo: '<path d="M9 14H4V9"/><path d="M4 14a8 8 0 1 0 2.2-5.5L4 11"/>',
  redo: '<path d="M15 14h5V9"/><path d="M20 14a8 8 0 1 1-2.2-5.5L20 11"/>',
  bold: '<path d="M7 5h6.2A3.3 3.3 0 0 1 16.5 8.3 3.1 3.1 0 0 1 13.5 11.5H7z"/><path d="M7 11.5h7.2A3.4 3.4 0 0 1 17.5 15 3.3 3.3 0 0 1 14.2 18.2H7z"/>',
  italic: '<path d="M10 5h8"/><path d="M6 19h8"/><path d="M14 5l-4 14"/>',
  underline: '<path d="M7 5v7.2A5 5 0 0 0 12 17a5 5 0 0 0 5-4.8V5"/><path d="M5 21h14"/>',
  strike: '<path d="M5 12h14"/><path d="M16.2 7.4A4.2 4.2 0 0 0 12 5.5 4 4 0 0 0 8.2 8"/><path d="M8 16.2A4.1 4.1 0 0 0 12 18.5 4.3 4.3 0 0 0 16.4 16"/>',
  heading: '<path d="M6 5v14"/><path d="M18 5v14"/><path d="M6 12h12"/>',
  quote: '<path d="M8 17h.01M7 8h5v5H8z"/><path d="M14 17h.01M13 8h5v5h-4z"/>',
  hr: '<path d="M4 12h16"/><path d="M8 8h8"/><path d="M8 16h8"/>',
  bulletList: '<path d="M10 6h10M10 12h10M10 18h10"/><circle cx="5" cy="6" r="1.2" fill="currentColor" stroke="none"/><circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="5" cy="18" r="1.2" fill="currentColor" stroke="none"/>',
  orderedList: '<path d="M10 6h10M10 12h10M10 18h10"/><path d="M4 5h2.2v6H4"/><path d="M4 15h3.2l-3 4h3.4"/>',
  outdent: '<path d="M4 6h16M10 12h10M4 18h16"/><path d="M8 9l-3 3 3 3"/>',
  indent: '<path d="M4 6h16M8 12h12M4 18h16"/><path d="M4 9l3 3-3 3"/>',
  alignLeft: '<path d="M4 6h16M4 12h10M4 18h14"/>',
  alignCenter: '<path d="M4 6h16M7 12h10M5 18h14"/>',
  alignRight: '<path d="M4 6h16M10 12h10M6 18h14"/>',
  alignJustify: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  font: '<path d="M5 19l4.2-12h1.6L15 19"/><path d="M6.8 14h6.4"/><path d="M17 11v8"/><path d="M15.5 11h3"/>',
  fontSize: '<path d="M5 18V8h3.2c1.8 0 3 1 3 2.6 0 1.3-.8 2.1-2 2.4 1.3.2 2.3 1.2 2.3 2.6 0 1.8-1.4 2.4-3.4 2.4z"/><path d="M16 18V10h2.2c1.4 0 2.3.8 2.3 2s-.8 1.9-2.1 2.1c1.4.2 2.3 1 2.3 2.2 0 1.4-1.1 1.7-2.7 1.7z"/>',
  color: '<path d="M4 20h16"/><path d="M12 4l5.5 11h-11z"/>',
  highlight: '<path d="M7 16l-2 4 4-2 8.5-8.5a2.1 2.1 0 0 0 0-3L15.5 4.5a2.1 2.1 0 0 0-3 0z"/><path d="M12 8l4 4"/>',
  clear: '<path d="M5 7h14"/><path d="M9 7V5h6v2"/><path d="M7 7l.8 12h8.4L17 7"/><path d="M10 11v5M14 11v5"/>',
  table: '<rect x="4" y="5" width="16" height="14" rx="1.2"/><path d="M4 10h16M4 15h16M10 5v14M16 5v14"/>',
  tableRowAdd: '<path d="M4 6h16M4 11h16"/><path d="M12 14v6"/><path d="M9 17h6"/>',
  tableRowAddAbove: '<path d="M12 4v6"/><path d="M9 7h6"/><path d="M4 13h16M4 18h16"/>',
  tableRowDel: '<path d="M4 7h16M4 12h16"/><path d="M9 17h6"/>',
  tableColAdd: '<path d="M6 4v16M11 4v16"/><path d="M16 9v6"/><path d="M13 12h6"/>',
  tableColAddLeft: '<path d="M5 9v6"/><path d="M2 12h6"/><path d="M13 4v16M18 4v16"/>',
  tableColDel: '<path d="M7 4v16M12 4v16"/><path d="M16 12h5"/>',
  tableDelete: '<rect x="3" y="6" width="12" height="12" rx="1"/><path d="M3 10h12M7 6v12"/><path d="M16 8l6 8M22 8l-6 8"/>',
  margins: '<rect x="4" y="4" width="16" height="16" rx="1.5"/><path d="M8 8h8v8H8z"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  image: '<rect x="4" y="6" width="16" height="13" rx="1.5"/><circle cx="9" cy="11" r="1.5"/><path d="M20 16l-4.5-4.5L7 20"/>',
  sign: '<path d="M4 19h16"/><path d="M6 16c2-4 3.5-8 5-8 1.2 0 1.4 3 2.5 5 .8 1.6 2 3 4.5 3"/>',
};

export function iconSvg(name) {
  const inner = PATHS[name];
  if (!inner) return null;
  const wrap = document.createElement('span');
  wrap.className = 'mhws-composer-icon';
  wrap.innerHTML = `<svg ${SVG_ATTR}>${inner}</svg>`;
  return wrap;
}
