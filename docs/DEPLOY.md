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
| `EXTRA_DOMAINS` | `extraDomains` plus non-`www` entries from `aliases` (excluding primary) |
| `ADMIN_PORT` | `admin.port` |
| `SERVICE_NAME` | `admin.serviceName` |
| `IS_PLATFORM` / `IS_OPS` | `platform` / `ops` flags (or env override) |
| `GITHUB_OWNER` | `githubOwner` |

## Scripts

| Script | Role |
|--------|------|
| [`deploy/remote-deploy.sh`](../deploy/remote-deploy.sh) | Local → SSH/rsync → invoke remote site-deploy |
| [`deploy/site-deploy.sh`](../deploy/site-deploy.sh) | On host: nginx + systemd + Phase-1 ops install |
| [`deploy/backup-site.sh`](../deploy/backup-site.sh) | Daily on-box SQLite / uploads / config backup |
| [`deploy/install-ops.sh`](../deploy/install-ops.sh) | Cron, journald retention, logrotate |
| [`deploy/lib/site-env.sh`](../deploy/lib/site-env.sh) | Shared path/config resolution |
| [`deploy/OPS-BACKUP.md`](../deploy/OPS-BACKUP.md) | Backup + restore runbook (Phase 1) |

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

Deploy protects the **entire** live `data/` tree (and never uploads a local `data/` copy):

- `data/rwa.db` (SQLite)
- `data/receipts/` (payment / claim proofs)
- `data/no-dues/` (issued certificates)
- `data/vault/` (Documents Vault uploads; catalog also indexes receipts / no-dues / cash notes in place)
- `data/info-centre/` (Information Centre files)
- `data/profile-photos/`, `data/payments/`, `data/imports/`, `data/messages/`
- `data/smtp.env`, `data/vapid.env` (Web Push VAPID keys) and other runtime env files

### Web Push (hbcsanyard)

- Requires HTTPS (already on production).
- First portal boot generates `data/vapid.env` if missing; deploy preserves an existing file.
- iOS Safari only delivers Web Push for apps added to the Home Screen (standalone PWA).

Also protected: `visitor-access.json`, `engagement.json`, `contact-messages.json`, `assets/site/`, `veercanvas/`.

First deploy only seeds missing `rwa.db` / example env with `--ignore-existing` — never overwrites.

`site.config.json` is used for deploy resolution and is not treated as a public web asset to clobber carelessly — see script comments.

## Nginx

Examples live in [`deploy/nginx/examples/`](../deploy/nginx/examples/):

- `veerlabs.solutions.conf`
- `canvas.veerlabs.solutions.conf`
- `ops.veerlabs.solutions.conf`
- `hbcsanyard.veerlabs.solutions.conf` — legacy alias vhost (same web root as primary)
- `housingcolonysanyard.in.conf` (+ `.http.conf` bootstrap until TLS exists)

Pattern:

- Static site at `/`
- `/admin/` and `/api/` → Flask on `ADMIN_PORT`
- Ops: `/` is the observability shell (still needs auth via admin session)

`site-deploy.sh` installs the matching example for **`domain`** when certs exist, otherwise generates a workable config or copies the `.http.conf` bootstrap.

### Extra domains / aliases

After the primary vhost is enabled, **`install_extra_domains`** loops `EXTRA_DOMAINS` (from `site.config.json` → `extraDomains`, plus apex hosts from `aliases` that are not the primary domain). For each host it:

1. Copies `deploy/nginx/examples/<host>.conf` when Let's Encrypt certs exist, else `<host>.http.conf` if present
2. Enables the site and reloads nginx
3. Runs `certbot certonly --webroot` when certs are missing (DNS must point only at the EC2 host — remove registrar forwarding A records first)

**hbcsanyard example:** primary `housingcolonysanyard.in`, web root stays `/var/www/hbcsanyard.veerlabs.solutions`, legacy alias `hbcsanyard.veerlabs.solutions` remains a separate enabled vhost (both serve the same files; no redirect between them).

TLS bootstrap for a new apex domain:

```bash
# On EC2 after DNS A record → EC2 IP (no GoDaddy forwarding)
sudo certbot certonly --webroot -w /var/www/hbcsanyard.veerlabs.solutions \
  -d housingcolonysanyard.in -d www.housingcolonysanyard.in
# Then redeploy or copy deploy/nginx/examples/housingcolonysanyard.in.conf into sites-enabled
```

### Public origin (RWA / share links)

For RWA sites, set on the host (not in git):

```bash
# /etc/veercanvas/hbcsanyard.env
VEERCANVAS_PUBLIC_ORIGIN=https://housingcolonysanyard.in
```

Used for Info Centre OG share cards, AuthBuddy redirect URIs, and portal canonical URLs. Deploy rebuilds `/share/*.html` for `hbcsanyard` after each push.

### PWA icons (hbcsanyard)

Regenerate from the master seal, then bump cache query strings in `manifest.webmanifest`, `index.html`, and `sw.js`:

```bash
cd sites/hbcsanyard
python3 scripts/export_logo_variants.py
# Home-screen icons: navy plate (#15233f), gold ring, larger seal — see _home_screen_icon()
```

Residents must remove and re-add the home-screen shortcut to pick up icon/name changes on iOS/Android.

## Remote unit env

systemd services typically receive:

- `VEERCANVAS_SITE_ID`, `VEERCANVAS_SITE_ROOT`, `VEERCANVAS_ROOT`
- `PORT` / admin port
- `VEERCANVAS_PLATFORM` and/or `VEERCANVAS_OPS` when applicable
- `VEERCANVAS_ADMIN_SECRET` (set on host — not from git)
- Optional `VEERCANVAS_ATTEST_SECRET` — HMAC key for portal PDF attestation (No Dues / cash notes). If unset, falls back to `VEERCANVAS_ADMIN_SECRET`. Prefer a dedicated long random value in the unit env or `data/smtp.env` (preserved across deploys). Never commit secrets.

Public verify page: `/attest.html?id=att_…` → `GET /api/rwa/attestations/<id>` (no login).

## Related

- [HANDOFF.md](HANDOFF.md) · [STATUS.md](STATUS.md) · [deploy/README.md](../deploy/README.md)
