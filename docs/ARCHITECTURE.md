# VeerCanvas Architecture

## Vision

VeerCanvas is a **publish platform**, not just a static site generator. The current release focuses on catalog-style sites (project tiles, detail pages, admin CMS). The architecture leaves room for dynamic content, APIs, and server-driven components without breaking existing sites.

## Layers

```
┌─────────────────────────────────────────────────────────┐
│  sites/<id>/          Site content + theme + config     │
│  (veerlabs sample)    projects.json, miniapps, HTML   │
├─────────────────────────────────────────────────────────┤
│  admin/               Authoring CMS (Flask)             │
│  cli/                 Import, sync, publish tools       │
├─────────────────────────────────────────────────────────┤
│  core/                Shared schemas, renderers (WIP)   │
├─────────────────────────────────────────────────────────┤
│  deploy/              CI/CD, nginx, systemd, remote     │
└─────────────────────────────────────────────────────────┘
```

## Site package

Each site under `sites/<id>/` contains:

| Path | Role |
|------|------|
| `site.config.json` | Domain, web root, GitHub owner, service names |
| `site-meta.json` | Published version metadata |
| `projects.json` | Full catalog (admin source of truth; not publicly served) |
| `projects-public.json` | Enabled-only public catalog (also excludes deleted slugs) |
| `catalog-exclusions.json` | Deleted slugs skipped on import and omitted from public catalog |
| `miniapps/<slug>/` | Per-entry content packages |
| Theme files | `index.html`, `project.html`, `*.js`, `style.css` |

## Catalog rules

- **Import** only creates packages for *new* GitHub repos. Already-imported projects are skipped unless marked `reimport: true` in admin (or CLI `--reimport-all` / `--reimport-slugs`).
- **Hide** sets `enabled: false` — project stays in admin catalog but is removed from `projects-public.json`.
- **Delete** removes the miniapp, drops the catalog entry, and adds the slug to `catalog-exclusions.json` so future imports cannot resurrect it.
- **Deploy** pulls the live CMS catalog from the server before syncing (unless `OVERRIDE_CATALOG=1`), so local git cannot overwrite admin hide/delete decisions.

## Publish flow (today)

1. Author in **admin** (visual section editor or JSON)
2. Admin writes `projects.json`, `projects-public.json`, `miniapps/*/project.json`
3. **Publish** bumps `site-meta.json` version
4. **Deploy** rsyncs site files + platform admin to host
5. Nginx serves static theme; `/admin/` proxies to Flask

## Extension points (planned)

- **Dynamic routes:** `sites/<id>/routes/` or API manifest
- **Server components:** registered in `core/components/`, rendered at request time
- **Plugins:** `veercanvas.plugin` entry points for importers, renderers, deploy hooks
- **CI/CD:** per-site workflows in `.github/workflows/` triggered by `sites/<id>/**`

## Sample site

` sites/veerlabs` — VeerLabs Solutions project catalog at [veerlabs.solutions](https://veerlabs.solutions).
