# VeerCanvas status tracker

Last updated: **2026-07-26**

## Live hosts

| Site id | Domain | Role | Admin port | systemd |
|---------|--------|------|------------|---------|
| `veerlabs` | [veerlabs.solutions](https://veerlabs.solutions) | Public catalog | 8080 | `veercanvas-admin` |
| `canvas` | [canvas.veerlabs.solutions](https://canvas.veerlabs.solutions) | Site Studio | 8081 | `veercanvas-admin-canvas` |
| `ops` | [ops.veerlabs.solutions](https://ops.veerlabs.solutions) | Observability | 8083 | `veercanvas-admin-ops` |
| `new-website` | `new-website.veerlabs.solutions` | Scaffold example (`authoring`) | 8082 | `veercanvas-admin-new-website` |

## Shipped

- [x] Catalog CMS (projects, sections, import, publish)
- [x] Multi-site layout under `sites/<id>/`
- [x] Canvas Site Studio (`platform: true`)
- [x] Ops observability + messagebox (`ops: true`)
- [x] Templates + registry (`sites/_templates/`)
- [x] Engagement + contact forms
- [x] Visitor tokens for gated Learn More
- [x] Visit tracking (IP + metrics) on public catalog pages
- [x] Branding SVGs / favicons
- [x] Standalone GitHub repo

## In progress / next

- [ ] Platform CI (lint, admin smoke, catalog build)
- [ ] Draft vs published environments
- [ ] Publish webhooks
- [ ] Role-based admin users (beyond single seeded admin)

## Known caveats

1. **Catalog pull on deploy** — `remote-deploy.sh` pulls live `projects.json` / miniapps / exclusions from the server before push unless `OVERRIDE_CATALOG=1`.
2. **Runtime JSON preserved** — rsync protect filters keep `visitor-access.json`, `engagement.json`, `contact-messages.json`, `assets/site/`, `veercanvas/` from being clobbered.
3. **One Flask process per site** — distinct ports/services; nginx proxies `/admin/` and `/api/` per domain.
4. **Platform/ops deploys sync full `sites/`** — needed so ops can read sibling site data roots.
5. **Visitor token TTL** — default 3600s; override with `VEERCANVAS_VISITOR_TOKEN_TTL`.
6. **Default admin seed** — first empty `admin.db` seeds a development `admin` user; rotate in production (see [HANDOFF.md](HANDOFF.md)).

## Quick links

- [HANDOFF.md](HANDOFF.md) · [DEPLOY.md](DEPLOY.md) · [ROADMAP.md](ROADMAP.md) · [CHANGELOG.md](../CHANGELOG.md)
