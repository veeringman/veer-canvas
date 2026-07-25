# Changelog

All notable changes to VeerCanvas are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Documentation

- Full docs sweep: architecture, admin manual, deploy/CLI/API guides, handoff, status tracker, site READMEs

## [2026-07-25] — Visit metrics & platform polish

### Added

- `POST /api/public/visit` — record every page view (with or without visitor token): IP, path, referrer, UA/device, auth mode, UTMs
- Ops **Visits** tab + overview stats (page visits, unique IPs, anon vs token visits, top paths/referrers)
- Client beacon via `VeerEngage.trackVisit()` on catalog pages
- Site Studio templates registry (`catalog-static`, `docs-hub`, `ops-console`) under `sites/_templates/`
- Canvas Site Studio UI (`sites/canvas/`) for create / manage / deploy sites
- Ops console UI (`sites/ops/`) for cross-site observability + messagebox
- Visitor access tokens for Learn More (`requireAuth`): `/api/public/access/{status,token,gate}` (~1h TTL)
- Engagement (likes/comments) and contact inbox APIs
- Branding assets under `assets/branding/`

### Changed

- CMS at `*/admin` is content-only; metrics and create-site moved off per-site admin into ops / canvas
- Deploy rsync preserves `visitor-access.json`, `engagement.json`, `contact-messages.json`

## [2026-07-14] — Platform extraction

### Added

- Standalone repository [veeringman/veer-canvas](https://github.com/veeringman/veer-canvas)
- `sites/veerlabs/` reference catalog, `admin/` Flask CMS, `deploy/remote-deploy.sh`
- Migration from VeerSetu monorepo (`git subtree split`)

See [docs/MIGRATION.md](docs/MIGRATION.md).
