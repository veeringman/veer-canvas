# VeerCanvas operator handoff

Day-2 runbook for deploying and operating VeerCanvas on EC2. Do **not** commit SSH keys, GitHub tokens, or admin passwords to git.

## Prerequisites

- Repo: [github.com/veeringman/veer-canvas](https://github.com/veeringman/veer-canvas)
- SSH key with access to the host (pass via `EC2_KEY=…`; keep the PEM outside the repo or untracked)
- DNS for each site domain pointing at the EC2 public IP (needed for TLS)
- Optional: `GITHUB_TOKEN` / `GH_TOKEN` for private repo import

Defaults used by deploy scripts (override as needed):

| Variable | Typical value |
|----------|----------------|
| `EC2_HOST` | production host IP |
| `EC2_USER` | `ubuntu` |
| `EC2_KEY` | path to PEM |

## Surfaces to keep healthy

| Priority | Site | Check |
|----------|------|-------|
| P0 | `veerlabs` | Public catalog + `/admin/` CMS |
| P0 | `ops` | Login → observability / visits / inbox |
| P1 | `canvas` | Site Studio create/deploy |
| P2 | author sites | Per `SITE_ID` CMS |

## Deploy

```bash
cd veer-canvas
chmod 600 /path/to/key.pem

SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=ops      EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
SITE_ID=canvas   EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

Opt-in GitHub fetch during deploy: add `--import-repos`.  
Force local catalog over live CMS state: `OVERRIDE_CATALOG=1` (destructive to remote edits — rare).

Full detail: [DEPLOY.md](DEPLOY.md).

## Where live data lives (remote)

Under each site web root (from `site.config.json` → `webRoot`), typically:

- Theme + public JSON (synced from git)
- Runtime: `engagement.json`, `contact-messages.json`, `visitor-access.json` (preserved across deploys)
- CMS DB: `admin.db` (or under platform data dirs) — **back up separately**
- Uploaded brand marks: `assets/site/`

Platform/ops hosts also keep a synced tree of managed `sites/` so observability can read peer data.

### Backup checklist

- Catalog: `projects.json`, `projects-public.json`, `catalog-exclusions.json`, `miniapps/`
- Runtime metrics: `visitor-access.json`, `engagement.json`, `contact-messages.json`
- Auth: `admin.db` per site service
- Secrets: systemd unit env / host files (not in git)

## Reading visits & inbox

1. Open [ops.veerlabs.solutions](https://ops.veerlabs.solutions/)
2. Sign in at `/admin/login` if redirected
3. Overview cards → page visits / unique IPs / anon vs token
4. **Visits** tab → recent IPs, paths, auth mode, devices, top paths/referrers
5. Messagebox tabs → contact messages, comments, visitors, access events

## Auth notes

- **Admin** — Flask session per site admin process. First empty DB seeds development user `admin` (password hash defined in `admin/admin_app.py`). Change immediately; never document production passwords in this repo.
- **Visitors** — name + email → 1h token for gated projects; stored in `visitor-access.json`.
- **Sessions** — set a strong `VEERCANVAS_ADMIN_SECRET` on each systemd service.

## systemd services

| Site | Service |
|------|---------|
| veerlabs | `veercanvas-admin` |
| canvas | `veercanvas-admin-canvas` |
| ops | `veercanvas-admin-ops` |

```bash
sudo systemctl status veercanvas-admin
sudo systemctl restart veercanvas-admin-ops
sudo journalctl -u veercanvas-admin -n 100 --no-pager
```

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Public site 502 on `/admin/` or `/api/` | Admin service down / wrong port | `systemctl status` + restart; check `PORT` in unit |
| Nginx config test fails | Bad site conf | `sudo nginx -t`; compare `deploy/nginx/examples/<domain>.conf` |
| Local catalog wiped remote CMS edits | Pushed without pull | Default deploy pulls first; avoid `OVERRIDE_CATALOG=1` |
| Visits empty in ops | Site not beaconing / data not synced | Confirm `engagement.js` on site; redeploy ops so `sites/` tree is present |
| Learn More always prompts | Token expired or missing | Re-auth; check TTL / `visitor-access.json` tokens |
| TLS pending | DNS not pointed yet | Point A/AAAA records, re-run deploy or certbot |

## Related

- [STATUS.md](STATUS.md) · [ADMIN_MANUAL.md](ADMIN_MANUAL.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md)
