# VeerCanvas core

Shared schemas, component registry, and runtime libraries for multi-site VeerCanvas hosting.

- **`document-engine/`** — branding loader, compose/version architecture (`README.md` inside).
- **`composer/`** — browser document composer (copy used by RWA society sites; load from `/veercanvas/core/composer/boot.js` on deploy).

Site-specific RWA scripts remain under `sites/<id>/scripts/` until fully extracted.
