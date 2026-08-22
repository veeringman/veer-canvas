# MHWS document composer

Extensible in-browser composer shared by:

- EC **Templates → Compose** (Society letterhead / print / mail)
- **Information Centre → Write a document** (member-facing pages, EN + हिंदी)

## Pipeline

```
Starter catalogue (Python, rwa_template_starters.py)     [Templates only]
        ↓  GET /api/rwa/templates → starters[]
EditorSession (composer/)  — same mount() for every host
        ↓  getHTML()  fragment
Templates: wrap_composed_document() chrome pad → POST htmlBody
  chrome = Official / Blank letterhead / Simple (GET chromes[])
  Download: POST /api/rwa/templates/compose/export  (pdf | docx | txt)
  Import:   POST /api/rwa/templates/compose/import  (txt | doc/docx | pages | pdf text)
Info Centre: _wrap_html_document() page shell → POST htmlBody / htmlBodyHi
```

## Layout

Every host shell (`#tplComposeShell`, `#infoHtmlPane`, …) can call
`MhwsComposer.attachLayout(shell)`. Icon chrome:

- **Original** — editor stays in the page
- **Panel** — docks to the right
- **Full window** — fills the viewport
- Escape or the dimmed backdrop restores original

Only one composer is expanded at a time. Preference is stored per host.

## Letterhead, download, images

Templates Compose:

- **Pad** — Official letterhead, Blank letterhead, or Simple header & footer. Pads inject the draft into `.body-area` and keep the existing header, footer, and watermark.
- **Watermark** — on/off when the chosen pad has `img.wm`.
- **Save** — still writes draft/published HTML into the template library.
- **Download** — Word (`.docx`) and PDF use the chosen pad (header, footer, watermark). Text (`.txt`) is the body only. **Google Drive** saves the same files into a `Composer` folder when Drive backups are enabled.
- **Import** — text-only from this device or Google Drive: `.txt`, Word (`.docx`; older `.doc` if it is actually HTML/DOCX), Pages (preview PDF / index.xml), or PDF text layer (no OCR). Letterhead is not applied on import.
- **Images** — click to select; corner handles resize; drag to move; float left / centre / right. **In line** puts a text span beside the image so several lines sit against its height (top / middle / bottom).
- **Line spacing** — toolbar 1.0–2.0; highlighted paragraph only, otherwise the whole document.
- **Title / subtitle** — Heading and Subheading convert the paragraph to `h2` / `h3` (18pt / 14pt bold navy).
- **Clipboard** — Ctrl/Cmd+C / X / V inside the editor, paste from other apps (text, Word HTML, images), plus Cut / Copy / Paste on the toolbar.

## How to extend

**New document type** (resolution, NOC, …): add a dict to `DOCUMENT_STARTERS` in
`sites/hbcsanyard/scripts/rwa_template_starters.py`. No JS change.

**New formatting / insert** (QR, signature block, …): `MhwsComposer.registry.register({
  id, group, icon, title, kind: 'button'|'select'|'color'|'file',
  command, run(driver, payload)
})` before mount, or add to `formats.js` `BUILTIN_EXTENSIONS`.

**New host** (another panel that needs an editor):

```js
const C = await MhwsComposer.ready();
C.attachLayout(shellEl, { storageKey: 'mhws-composer-layout-mine' });
const session = C.mount({ host, toolbar, imageInput, textarea, onDirty });
```

**Swap the editing engine:** implement `EditorDriver` (`mount`, `getHTML`, `setHTML`,
`focus`, `run`, `destroy`) and pass it to `createSession({ driver })`. The DOM
driver is the default; a ProseMirror/TipTap driver can drop in later without
touching portal.js.

## Public API

```js
const C = await MhwsComposer.ready();
C.attachLayout(shell, { storageKey, langForm, applySaved });
const session = C.mount({ host, toolbar, imageInput, textarea, onDirty });
session.applyStarter(starter);
session.getHTML();
session.setHTML(html);
session.isEmpty();
C.extractBody(fullHtmlDocument); // authored fragment from a wrapped page
session.destroy();
```
