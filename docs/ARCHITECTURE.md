# VeerCanvas Architecture

## Vision

VeerCanvas is a **publish platform**, not just a static site generator. Catalog-style sites (project tiles, detail pages, CMS) ship today; the layout leaves room for dynamic routes, APIs, and server-driven components without breaking existing sites.

## Surfaces

| Surface | Host | Role | `site.config.json` |
|---------|------|------|--------------------|
| **Canvas** | [canvas.veerlabs.solutions](https://canvas.veerlabs.solutions/) | Site Studio — create/manage websites | `platform: true` |
| **Ops** | [ops.veerlabs.solutions](https://ops.veerlabs.solutions/) | Observability + messagebox across sites | `ops: true` |
| **Site CMS** | `https://<site>/admin/` | Content authoring for that site only | both flags `false` |

Auth-gated shells (canvas `/`, ops `/`) redirect unauthenticated users to `/admin/login?next=/`. Per-site `/admin/` is pure CMS — no metrics, no create-site.

## Layers

```
┌─────────────────────────────────────────────────────────────┐
│  sites/<id>/     Content, theme, site.config.json           │
│  sites/_templates/   Builtin scaffolds (registry.json)      │
├─────────────────────────────────────────────────────────────┤
│  admin/          Flask CMS + public APIs (one process/site) │
│  cli/            create_site, GitHub import, catalog sync   │
├─────────────────────────────────────────────────────────────┤
│  core/           Shared schemas / runtime (WIP)             │
├─────────────────────────────────────────────────────────────┤
│  deploy/         remote-deploy, nginx examples, systemd     │
└─────────────────────────────────────────────────────────────┘
```

## Site package

Each site under `sites/<id>/` contains:

| Path | Role |
|------|------|
| `site.config.json` | Domain, web root, admin port/service, `platform` / `ops`, template metadata |
| `site-meta.json` | Published version metadata |
| `projects.json` | Full catalog (admin source of truth; not publicly served) |
| `projects-public.json` | Enabled-only public catalog |
| `catalog-exclusions.json` | Deleted slugs skipped on import |
| `miniapps/<slug>/` | Per-entry content packages |
| Theme files | `index.html`, `project.html`, `*.js`, `style.css` |
| `engagement.json` | Likes, dislikes, comments (runtime; preserved on deploy) |
| `contact-messages.json` | Contact form inbox (runtime; preserved) |
| `visitor-access.json` | Visitor tokens, access events, **visits[]** (runtime; preserved) |

## Templates

Builtin packages live in [`sites/_templates/`](../sites/_templates/) and are listed in `registry.json`:

- **catalog-static** — tile grid + project detail (default for catalogs)
- **docs-hub** — docs-oriented chrome, same structure
- **ops-console** — auth-gated ops shell pattern

Canvas Site Studio scaffolds new sites from a template and can clone custom templates into the registry.

## Catalog rules

- **Import** creates packages for *new* GitHub repos unless `reimport: true` / CLI reimport flags.
- **Hide** sets `enabled: false` — stays in admin catalog, removed from `projects-public.json`.
- **Delete** removes the miniapp, drops the catalog entry, and adds the slug to `catalog-exclusions.json`.
- **Deploy** pulls the live CMS catalog from the server before syncing (unless `OVERRIDE_CATALOG=1`).

## Auth model

| Mode | How | Used for |
|------|-----|----------|
| Admin session | Flask cookie after `/admin/login` | CMS, Site Studio APIs, Ops APIs |
| Visitor token | `POST /api/public/access/token` (name + email); TTL default 1h (`VEERCANVAS_VISITOR_TOKEN_TTL`) | Learn More gates when `requireAuth` is set |
| Anonymous | No token | Open pages; still recorded by visit tracking |

`access_authorized()` accepts an admin session **or** a valid visitor token (`X-Visitor-Token` header or body/query `token`).

## Visit metrics

Public pages call `POST /api/public/visit` on load (with or without a token). Rows append to `visitor-access.json` → `visits[]` (IP, path, referrer, UA/browser/device, auth mode, UTMs, etc.). Ops aggregates them via `GET /api/observability`.

## Publish & deploy flow

1. Author in **admin** (sections editor or JSON)
2. Admin writes catalog + miniapp files; **Publish** bumps `site-meta.json`
3. **Deploy** (`SITE_ID=… ./deploy/remote-deploy.sh`) rsyncs site + platform admin to the host
4. Nginx serves static theme; `/admin/` and `/api/` proxy to the per-site Flask service
5. Platform/ops deploys also sync the full `sites/` tree so observability can read sibling data roots

## Extension points (planned)

- Dynamic routes / API manifests per site
- Server components in `core/components/`
- Plugin entry points for importers, renderers, deploy hooks
- Per-site CI workflows under `.github/workflows/`

## Sample site

`sites/veerlabs/` — VeerLabs Solutions catalog at [veerlabs.solutions](https://veerlabs.solutions).
