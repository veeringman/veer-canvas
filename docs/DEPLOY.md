# Deploy guide

How VeerCanvas ships a site + its Flask admin to EC2.

## Quick start

```bash
SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=canvas  EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=ops     EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh

# Opt-in: fetch NEW GitHub repos during deploy
SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh --import-repos
```

Before first deploy of a new host, point DNS (`A`/`AAAA`) at the EC2 IP so TLS can be issued.

## How `SITE_ID` resolves

[`deploy/lib/site-env.sh`](../deploy/lib/site-env.sh) loads `sites/${SITE_ID}/site.config.json` and sets:

| Variable | From |
|----------|------|
| `SITE_DOMAIN` | `domain` |
| `WEB_ROOT` | `webRoot` (or `/var/www/<domain>`) |
| `ADMIN_PORT` | `admin.port` |
| `SERVICE_NAME` | `admin.serviceName` |
| `IS_PLATFORM` / `IS_OPS` | `platform` / `ops` flags (or env override) |
| `GITHUB_OWNER` | `githubOwner` |

## Scripts

| Script | Role |
|--------|------|
| [`deploy/remote-deploy.sh`](../deploy/remote-deploy.sh) | Local → SSH/rsync → invoke remote site-deploy |
| [`deploy/site-deploy.sh`](../deploy/site-deploy.sh) | On host: nginx + systemd for that site |
| [`deploy/lib/site-env.sh`](../deploy/lib/site-env.sh) | Shared path/config resolution |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `SITE_ID` | `veerlabs` | Which site package to deploy |
| `EC2_HOST` | set in script | SSH target |
| `EC2_USER` | `ubuntu` | SSH user |
| `EC2_KEY` | `./VeerSetuHost.pem` | Private key path |
| `OVERRIDE_CATALOG` | `0` | `1` = skip pulling live CMS catalog (dangerous) |
| `IMPORT_REPOS` / `--import-repos` | off | Run GitHub import for new repos |
| `VEERCANVAS_PLATFORM` / `VEERCANVAS_OPS` | from config | Forced onto remote systemd unit |

## Catalog pull (safe by default)

Unless `OVERRIDE_CATALOG=1`, deploy **pulls** from the live web root first:

- `projects.json`, `projects-public.json`, `catalog-exclusions.json`, `site-meta.json`
- `miniapps/`
- `assets/site/` (CMS brand uploads)

That prevents a local git checkout from resurrecting deleted/hidden projects.

## What gets pushed

Typical sync:

- Site theme + public assets (excluding secrets)
- `admin/`, `deploy/`, `cli/` platform code
- For **platform** or **ops** sites: full `sites/` tree (so ops can read peer data)

### Preserve filters (not overwritten)

rsync protect includes:

- `visitor-access.json`
- `engagement.json`
- `contact-messages.json`
- `assets/site/`
- `veercanvas/` (runtime data dirs when present)

`site.config.json` is used for deploy resolution and is not treated as a public web asset to clobber carelessly — see script comments.

## Nginx

Examples live in [`deploy/nginx/examples/`](../deploy/nginx/examples/):

- `veerlabs.solutions.conf`
- `canvas.veerlabs.solutions.conf`
- `ops.veerlabs.solutions.conf`
- `new-website.veerlabs.solutions.conf`

Pattern:

- Static site at `/`
- `/admin/` and `/api/` → Flask on `ADMIN_PORT`
- Ops: `/` is the observability shell (still needs auth via admin session)

`site-deploy.sh` installs the matching example when certs exist, otherwise generates a workable config.

## Remote unit env

systemd services typically receive:

- `VEERCANVAS_SITE_ID`, `VEERCANVAS_SITE_ROOT`, `VEERCANVAS_ROOT`
- `PORT` / admin port
- `VEERCANVAS_PLATFORM` and/or `VEERCANVAS_OPS` when applicable
- `VEERCANVAS_ADMIN_SECRET` (set on host — not from git)

## Related

- [HANDOFF.md](HANDOFF.md) · [STATUS.md](STATUS.md) · [deploy/README.md](../deploy/README.md)
