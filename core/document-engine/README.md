# Document engine

Shared building blocks for RWA / society printable documents on VeerCanvas.

## Layers

1. **Content** — composed body fragments (`body.html`), starters, import pipeline.
2. **Chrome** — letterhead pads, stationery specs, versioned snapshots (`template_versions`).
3. **Render** — wrap on read, PDF export, print CSS profiles.

## Modules

| Path | Role |
|------|------|
| `branding.py` | `site-meta.json` → society name, logos, compose shell strings |
| `../composer/` | Browser composer (pages, stationery designer, export hooks) |

Site-specific Python (`rwa_templates.py`, `rwa_compose_export.py`) lives under each society’s `scripts/` until fully extracted.

## New society scaffold

Copy `sites/_template/rwa-society/` and set `site-meta.json` + `composeBranding`. Point the portal at `/veercanvas/core/composer/boot.js` on deployed hosts (see scaffold README).
