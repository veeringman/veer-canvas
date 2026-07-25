# VeerLabs — reference catalog

Official sample VeerCanvas site: public project catalog for VeerLabs Solutions.

| | |
|--|--|
| **Domain** | [veerlabs.solutions](https://veerlabs.solutions) |
| **Config** | `platform: false`, `ops: false` |
| **Admin port** | `8080` (`veercanvas-admin`) |
| **Template** | `catalog-static` |

## Role

- Public tile grid + project detail pages
- Content CMS at `/admin/` (projects, import, publish, branding)
- `engagement.js` — likes/comments, contact modal, Learn More auth gate, **visit beacon**
- Per-project `requireAuth` gates Learn More behind a ~1h visitor token (or admin session)

Runtime data (preserved on deploy): `engagement.json`, `contact-messages.json`, `visitor-access.json`.

## Deploy

```bash
SITE_ID=veerlabs EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

See [docs/ADMIN_MANUAL.md](../../docs/ADMIN_MANUAL.md) · [docs/CLI.md](../../docs/CLI.md).
