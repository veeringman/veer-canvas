# Ops — Observability console

Cross-site metrics and messagebox for VeerCanvas-managed websites.

| | |
|--|--|
| **Domain** | [ops.veerlabs.solutions](https://ops.veerlabs.solutions/) |
| **Config** | `site.config.json` → `ops: true`, `platform: false` |
| **Admin port** | `8083` (`veercanvas-admin-ops`) |
| **Template** | `ops-console` |

## Role

- Auth-gated dashboard at `/` (redirects to `/admin/login` when needed)
- Overview: engagement, messages, visitors, **page visits**, unique IPs
- Tabs: messages, comments, **visits**, visitors, access events
- `/admin/` is CMS for this host only — metrics live on the ops shell, not in per-site CMS

Visit rows come from each site’s `visitor-access.json` (populated by `POST /api/public/visit`).

## Deploy

```bash
SITE_ID=ops EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

Platform/ops deploys sync the full `sites/` tree so this host can read peer data roots.

See [docs/ADMIN_MANUAL.md](../../docs/ADMIN_MANUAL.md) · [docs/API.md](../../docs/API.md).
