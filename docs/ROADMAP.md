# VeerCanvas Roadmap

## Phase 1 — Catalog CMS (shipped)

- [x] Project catalog model (`projects.json`, miniapps)
- [x] Admin CMS with enable/disable, logos, import
- [x] Rich content sections (HTML, Markdown, Mermaid)
- [x] Public catalog filtering (`projects-public.json`)
- [x] Opt-in GitHub import on deploy
- [x] VeerLabs reference site

## Phase 2 — Platform extraction (in progress)

- [x] `veercanvas/` monorepo layout
- [ ] Standalone `veer-canvas` GitHub repository
- [ ] Generic site template and theme separation
- [ ] Platform CI (lint, admin smoke, catalog build)

## Phase 3 — Dynamic content

- [ ] API routes per site (`/api/*` behind VeerCanvas runtime)
- [ ] Server-side section types (data-bound components)
- [ ] Webhooks on publish (Slack, GitHub, custom)
- [ ] Draft vs published environments

## Phase 4 — Components & extensibility

- [ ] Component registry (React/Vue/lite web components)
- [ ] Plugin SDK for importers and renderers
- [ ] Multi-site hosting from one admin instance
- [ ] Role-based admin (editor, publisher, admin)

## Phase 5 — Edge & scale

- [ ] Edge rendering / ISR for hybrid static+dynamic pages
- [ ] CDN-aware cache invalidation on publish
- [ ] Managed VeerCanvas Cloud (optional hosting product)
