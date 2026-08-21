/**
 * Built-in format + insert extensions. Add entries here (or register() at
 * runtime) — toolbar.js renders whatever the registry holds.
 */
import { registry } from './registry.js';

export const BUILTIN_EXTENSIONS = [
  { id: 'undo', group: 'history', icon: 'undo', title: 'Undo', command: 'undo' },
  { id: 'redo', group: 'history', icon: 'redo', title: 'Redo', command: 'redo' },

  { id: 'bold', group: 'inline', icon: 'bold', title: 'Bold', command: 'bold', mark: true },
  { id: 'italic', group: 'inline', icon: 'italic', title: 'Italic', command: 'italic', mark: true },
  { id: 'underline', group: 'inline', icon: 'underline', title: 'Underline', command: 'underline', mark: true },
  { id: 'strike', group: 'inline', icon: 'strike', title: 'Strikethrough', command: 'strike', mark: true },

  {
    id: 'block',
    group: 'block',
    kind: 'select',
    icon: 'heading',
    title: 'Paragraph style',
    options: [
      { value: 'paragraph', label: 'Body' },
      { value: 'h2', label: 'Heading' },
      { value: 'h3', label: 'Subheading' },
      { value: 'blockquote', label: 'Quote' },
    ],
  },
  { id: 'hr', group: 'block', icon: 'hr', title: 'Horizontal line', command: 'hr' },

  { id: 'bulletList', group: 'list', icon: 'bulletList', title: 'Bullet list', command: 'bulletList' },
  { id: 'orderedList', group: 'list', icon: 'orderedList', title: 'Numbered list', command: 'orderedList' },
  { id: 'outdent', group: 'list', icon: 'outdent', title: 'Decrease indent', command: 'outdent' },
  { id: 'indent', group: 'list', icon: 'indent', title: 'Increase indent', command: 'indent' },

  { id: 'alignLeft', group: 'align', icon: 'alignLeft', title: 'Align left', command: 'alignLeft' },
  { id: 'alignCenter', group: 'align', icon: 'alignCenter', title: 'Align centre', command: 'alignCenter' },
  { id: 'alignRight', group: 'align', icon: 'alignRight', title: 'Align right', command: 'alignRight' },
  { id: 'alignJustify', group: 'align', icon: 'alignJustify', title: 'Justify', command: 'alignJustify' },

  {
    id: 'fontFamily',
    group: 'type',
    kind: 'select',
    icon: 'font',
    title: 'Font',
    command: 'fontFamily',
    options: [
      { value: 'Georgia, serif', label: 'Georgia' },
      { value: '"Times New Roman", Times, serif', label: 'Times' },
      { value: 'Palatino, "Palatino Linotype", serif', label: 'Palatino' },
      { value: '"Source Sans 3", "Segoe UI", sans-serif', label: 'Source Sans' },
      { value: 'Arial, Helvetica, sans-serif', label: 'Arial' },
      { value: '"Noto Sans", sans-serif', label: 'Noto Sans' },
      { value: '"Courier New", Courier, monospace', label: 'Courier' },
    ],
  },
  {
    id: 'fontSize',
    group: 'type',
    kind: 'select',
    icon: 'fontSize',
    title: 'Size',
    command: 'fontSize',
    options: [
      { value: '12pt', label: '12' },
      { value: '10pt', label: '10' },
      { value: '11pt', label: '11' },
      { value: '14pt', label: '14' },
      { value: '16pt', label: '16' },
      { value: '18pt', label: '18' },
      { value: '22pt', label: '22' },
      { value: '28pt', label: '28' },
    ],
  },
  { id: 'color', group: 'type', kind: 'color', icon: 'color', title: 'Text colour', command: 'color', value: '#12233f' },
  { id: 'highlight', group: 'type', kind: 'color', icon: 'highlight', title: 'Highlight', command: 'highlight', value: '#fff4c4' },
  { id: 'removeFormat', group: 'type', icon: 'clear', title: 'Clear formatting', command: 'removeFormat' },

  { id: 'insertTable', group: 'insert', kind: 'table', icon: 'table', title: 'Insert table', command: 'insertTable' },
  { id: 'pageMargins', group: 'insert', icon: 'margins', title: 'Page margins (top, bottom, left, right)' },
  { id: 'insertImage', group: 'insert', kind: 'file', icon: 'image', title: 'Insert image', accept: 'image/*' },
  {
    id: 'signBlock',
    group: 'insert',
    icon: 'sign',
    title: 'Signature lines',
    run(driver) {
      driver.run(
        'insertHTML',
        '<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>'
          + '<span style="font-size:9pt">President</span> &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; '
          + '<span style="font-size:9pt">General Secretary</span></p>',
      );
    },
  },
];

export function registerBuiltins() {
  BUILTIN_EXTENSIONS.forEach((ext) => registry.register(ext));
}
