# VeerCanvas site templates

Each subdirectory is a theme package copied into `sites/<id>/` when creating a website (CLI `create_site.py` or Canvas Site Studio).

## Builtin templates

| Id | Layout | Best for |
|----|--------|----------|
| `catalog-static` | Tile grid + project detail | Portfolios, product catalogs |
| `docs-hub` | Docs-oriented chrome, same structure | Documentation hubs |
| `ops-console` | Auth-gated ops shell | Internal consoles (reference for ops host) |

Metadata lives in [`registry.json`](registry.json): `id`, `name`, `description`, `siteTypes`, `layout`, `source`, `version`, `preview`, `builtin`, `defaultIntegrations`.

## Custom templates

Site Studio can clone an existing package into `_templates/` and register it in `registry.json` (`POST /api/templates` on a `platform` host). Prefer cloning `catalog-static` for new public sites.

## Related

- Scaffold example site: `sites/new-website/` (authoring status)
- Live consumers: `sites/veerlabs/` (catalog), `sites/ops/` (ops-console), `sites/canvas/` (Studio UI)
- [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) · [docs/ADMIN_MANUAL.md](../../docs/ADMIN_MANUAL.md)
