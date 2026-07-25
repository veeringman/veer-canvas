# VeerCanvas Admin Manual

Operator and author guide for the Flask CMS, Site Studio (canvas), Ops console, and public engagement features.

## Surfaces

| URL | Purpose |
|-----|---------|
| `https://<site>/admin/` | Content CMS for that site only |
| [canvas.veerlabs.solutions](https://canvas.veerlabs.solutions/) | Site Studio (create/manage sites) — requires `platform: true` |
| [ops.veerlabs.solutions](https://ops.veerlabs.solutions/) | Observability + messagebox — requires `ops: true` |

Unauthenticated visits to canvas or ops `/` redirect to `/admin/login?next=/`.

## Login

1. Open `https://<host>/admin/login` (or follow the redirect from `/`).
2. Sign in with an admin account stored in that site’s `admin.db`.
3. On **first boot** (empty DB), the app seeds a default `admin` user — change the password immediately in production. Do not commit credentials to git.

Session cookies gate CMS and platform/ops APIs. Set `VEERCANVAS_ADMIN_SECRET` in production.

## Local CMS

```bash
cd veer-canvas
python3 -m venv .venv && source .venv/bin/activate
pip install -r admin/requirements.txt

export VEERCANVAS_SITE_ID=veerlabs
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/veerlabs"
python admin/admin_app.py
# http://127.0.0.1:8080/admin/
```

For canvas or ops locally, point `VEERCANVAS_SITE_ID` / `SITE_ROOT` at that site and set `VEERCANVAS_PLATFORM=1` or `VEERCANVAS_OPS=1` (and a free `PORT`).

App entrypoint: [`admin/admin_app.py`](../admin/admin_app.py).

## Content CMS (per site)

Authors manage **content only** — no create-site, no cross-site metrics.

### Projects

- **List / search** — catalog from `projects.json`
- **New project** — create a slug + tile without GitHub
- **Edit** — visual section editor (HTML / Markdown / Mermaid) or raw JSON
- **Enable / hide** — `enabled` toggles membership in `projects-public.json`
- **Delete** — removes miniapp + catalog entry; slug goes to `catalog-exclusions.json`
- **Reorder** — display order on the public grid
- **Logo / brand** — upload to miniapp assets or site brand marks under `assets/site/`
- **Require auth** — per-project `requireAuth` gates Learn More / project detail behind visitor token or admin session

### GitHub import

- **Sync repos** — import *new* repos for the configured `githubOwner`
- Projects already imported are skipped unless marked for reimport
- CLI equivalent: [`cli/scripts/import_github_projects_full.py`](../cli/scripts/import_github_projects_full.py) (see [CLI.md](CLI.md))

### Publish

**Publish** bumps `site-meta.json` version metadata for the public site. Deploy separately (see [DEPLOY.md](DEPLOY.md)).

## Site Studio (canvas)

Available when the admin process runs with `platform: true` / `VEERCANVAS_PLATFORM=1`.

- Create sites from templates (`catalog-static`, `docs-hub`, …)
- Patch site metadata (status, domain, integrations)
- Soft/hard delete sites
- Trigger remote deploy for a site
- Clone custom templates into `sites/_templates/` + `registry.json`

Public shell: `sites/canvas/` (platform console UI). CMS remains at `/admin/`.

## Ops console

Available when `ops: true` / `VEERCANVAS_OPS=1`.

Dashboard at `/` (after login) shows:

- Overview — likes, comments, messages, visitors, **page visits**, unique IPs, anon vs token visits
- Per-site table including visit counts
- Messagebox — contact messages, comments, visitors, access events
- **Visits** tab — recent rows (IP, path, auth mode, device, browser, referrer) + top paths/referrers

Data is aggregated from each managed site’s `engagement.json`, `contact-messages.json`, and `visitor-access.json`.

## Public engagement (catalog sites)

On sites that ship `engagement.js` (e.g. VeerLabs):

- Likes / dislikes / comments on projects
- Contact modal → `contact-messages.json`
- **Visit beacon** — every page load posts to `/api/public/visit` (with or without token)
- **Learn More gate** — if `requireAuth`, visitor enters name + email, receives a ~1 hour token (`VEERCANVAS_VISITOR_TOKEN_TTL`, default `3600`), stored in browser localStorage

## Data files (site root)

| File | Written by | Notes |
|------|------------|-------|
| `projects.json` | CMS / import | Full catalog |
| `projects-public.json` | CMS / import | Public enabled list |
| `engagement.json` | Public APIs | Preserved on rsync deploy |
| `contact-messages.json` | Contact form | Preserved |
| `visitor-access.json` | Access + visits | Preserved (`visitors`, `tokens`, `events`, `visits`) |
| `admin.db` | Flask | Under site or deploy data root — not overwritten by theme rsync |

## Deploy reminder

```bash
SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=canvas  EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=ops     EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

See [HANDOFF.md](HANDOFF.md) and [DEPLOY.md](DEPLOY.md) for DNS, systemd service names, and troubleshooting.

## Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — surfaces and data model
- [API.md](API.md) — route catalog
- [STATUS.md](STATUS.md) — shipped vs next
- [admin/README.md](../admin/README.md) — env vars and local run
