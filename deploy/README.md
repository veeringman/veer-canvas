# VeerCanvas deploy

Remote deploy helpers for sites under `sites/<id>/`.

## Usage

```bash
SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./remote-deploy.sh
SITE_ID=ops EC2_KEY=/path/to/key.pem ./remote-deploy.sh --import-repos
```

| Path | Role |
|------|------|
| `remote-deploy.sh` | Orchestrates pull/push + remote install |
| `site-deploy.sh` | Runs on the host (nginx + systemd + ops install) |
| `backup-site.sh` | Phase-1 on-box SQLite/uploads/config backup |
| `install-ops.sh` | Cron + journald + logrotate for a site |
| `lib/site-env.sh` | Resolves `SITE_ID` → domain, ports, flags |
| `nginx/examples/` | Per-domain nginx configs |
| `ops/` | Alert mailer, event prune, logrotate/journald snippets |

On-box backup & log rollover: [OPS-BACKUP.md](./OPS-BACKUP.md).

Full operator documentation: [docs/DEPLOY.md](../docs/DEPLOY.md) · [docs/HANDOFF.md](../docs/HANDOFF.md).
