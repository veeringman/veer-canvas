# Phase 1 — on-box backup & log rollover

Daily local backups + journal/nginx retention for each VeerCanvas site. No off-box Drive copy yet (Phase 2).

## What runs

| Piece | Path / schedule |
|-------|-----------------|
| Backup script | `deploy/backup-site.sh` |
| Installer | `deploy/install-ops.sh` (called from `site-deploy.sh`) |
| Cron | `/etc/cron.d/veercanvas-backup-<site-id>` → **02:30** local |
| Backup store | `/var/backups/veercanvas/<site-id>/` (14-day retention) |
| Backup log | `/var/log/veercanvas/backup-<site-id>.log` |
| Journald | `/etc/systemd/journald.conf.d/veercanvas.conf` (200M / 14d) |
| Nginx rotate | `/etc/logrotate.d/veercanvas-nginx` (14 days) |
| Events prune | `access_events` older than **90 days** (with each backup) |
| **Vitals check** | `deploy/ops/check-server-vitals.sh` → **every 15 min** |
| Vitals log | `/var/log/veercanvas/vitals-<site-id>.log` |

Each run writes a dated folder (`db/`, `uploads/data-bundle.tgz`, `configs/configs.tgz`, `MANIFEST.txt`) plus `latest` / `latest.tgz` symlinks.

Included: `rwa.db`, `admin.db`, profile photos, payments, info-centre, imports, `smtp.env`, systemd unit, nginx site, optional `/etc/veercanvas/<id>.env`, `site.config.json`.

## Install / reinstall

Happens automatically on deploy via `site-deploy.sh`. Manual:

```bash
sudo SITE_ID=hbcsanyard \
  WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions \
  DOMAIN=hbcsanyard.veerlabs.solutions \
  VEERCANVAS_SERVICE_NAME=veercanvas-admin-hbcsanyard \
  bash /var/www/hbcsanyard.veerlabs.solutions/veercanvas/deploy/install-ops.sh

# Optional: run one backup immediately
sudo INSTALL_OPS_RUN_NOW=1 SITE_ID=hbcsanyard \
  WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions \
  bash /var/www/hbcsanyard.veerlabs.solutions/veercanvas/deploy/install-ops.sh
```

Or:

```bash
sudo SITE_ID=hbcsanyard WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions \
  /var/www/hbcsanyard.veerlabs.solutions/veercanvas/deploy/backup-site.sh
```

## Alerts

On failure (or disk free &lt; `DISK_MIN_PCT`, default 15%), email via `data/smtp.env`.

Optional in `smtp.env`:

```bash
BACKUP_ALERT_TO=you@example.com
```

Defaults to `RWA_SMTP_FROM` when unset.

**Super admin console:** Master admin → Admin → Platform settings → **Backups & server vitals** (saved to the same `data/smtp.env`). Live status + **Send test alert** there too.

### Server vitals (every 15 minutes)

Email when nearing critical levels:

| Metric | Warning | Critical |
|--------|---------|----------|
| Disk free (`/`, web root, backups) | ≤ 20% | ≤ 10% |
| Memory available | ≤ 15% | ≤ 8% |
| Load (1m / CPU count) | ≥ 1.5 | ≥ 2.5 |
| Admin systemd service | — | not active |
| nginx | — | not active |
| Backup age | &gt; 24h before max | &gt; 28h since last `rwa.db` backup |

Repeat alerts: **6h** for warnings, **1h** for critical (state in `/var/lib/veercanvas/vitals/`).

Manual run:

```bash
sudo SITE_ID=hbcsanyard WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions \
  /var/www/hbcsanyard.veerlabs.solutions/veercanvas/deploy/ops/check-server-vitals.sh
```

Override thresholds via cron env or export before the script (`DISK_WARN_PCT`, `DISK_CRIT_PCT`, `MEM_WARN_PCT`, etc.).

## Restore (on-box)

```bash
# Stop app
sudo systemctl stop veercanvas-admin-hbcsanyard

# Restore DB (example: latest)
sudo cp /var/backups/veercanvas/hbcsanyard/latest/db/rwa.db \
  /var/www/hbcsanyard.veerlabs.solutions/data/rwa.db
sudo chown ubuntu:ubuntu /var/www/hbcsanyard.veerlabs.solutions/data/rwa.db

# Restore uploads/secrets
sudo tar -C /var/www/hbcsanyard.veerlabs.solutions \
  -xzf /var/backups/veercanvas/hbcsanyard/latest/uploads/data-bundle.tgz

sudo systemctl start veercanvas-admin-hbcsanyard
```

Verify login + a notice/dues read. Prefer copying `latest` aside first so you can roll back the restore.

## Env knobs

| Variable | Default | Meaning |
|----------|---------|---------|
| `RETAIN_DAYS` | 14 | On-disk backup age |
| `DISK_MIN_PCT` | 15 | Fail if free % below this |
| `ACCESS_EVENTS_DAYS` | 90 | Event prune window |
| `ALERT_ON_SUCCESS` | 0 | Email on success too |
| `BACKUP_ROOT` | `/var/backups/veercanvas/<id>` | Override store |

## Not in Phase 1

- Google Drive / S3 off-box copy
- Encrypted archives for Drive
- Formal quarterly restore drill checklist (basic restore steps above only)
