# VeerCanvas Roadmap

## Phase 1 — Catalog CMS (shipped)

- [x] Project catalog model (`projects.json`, miniapps)
- [x] Admin CMS with enable/disable, logos, import
- [x] Rich content sections (HTML, Markdown, Mermaid)
- [x] Public catalog filtering (`projects-public.json`)
- [x] Opt-in GitHub import on deploy
- [x] VeerLabs reference site

## Phase 2 — Multi-site platform (shipped)

- [x] Standalone [veer-canvas](https://github.com/veeringman/veer-canvas) GitHub repository
- [x] Site templates (`catalog-static`, `docs-hub`, `ops-console`) + `registry.json`
- [x] Site Studio on canvas (`platform: true`) — create / patch / deploy / soft-delete sites
- [x] Ops console (`ops: true`) — cross-site observability + messagebox
- [x] Per-site CMS isolation (content only at `*/admin`)
- [x] Engagement (likes/comments) + contact inbox
- [x] Visitor access tokens for Learn More (`requireAuth`, ~1h TTL)
- [x] Visit tracking (`POST /api/public/visit`, ops Visits metrics)
- [ ] Platform CI (lint, admin smoke, catalog build)

## Phase 3 — Dynamic content

- [ ] First-class API routes per site beyond current Flask public APIs
- [ ] Server-side section types (data-bound components)
- [ ] Webhooks on publish (Slack, GitHub, custom)
- [ ] Draft vs published environments

## Phase 4 — Components & extensibility

- [ ] Component registry (React/Vue/lite web components)
- [ ] Plugin SDK for importers and renderers
- [ ] Role-based admin (editor, publisher, admin)
- [ ] Stronger multi-tenant admin auth (shared IdP)

## Phase 5 — Edge & scale

- [ ] Edge rendering / ISR for hybrid static+dynamic pages
- [ ] CDN-aware cache invalidation on publish
- [ ] Managed VeerCanvas Cloud (optional hosting product)

See [STATUS.md](STATUS.md) for the live tracker and [CHANGELOG.md](../CHANGELOG.md) for shipped notes.
