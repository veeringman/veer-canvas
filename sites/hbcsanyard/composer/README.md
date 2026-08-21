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
Templates: wrap_composed_document() letterhead → POST htmlBody
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
