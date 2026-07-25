# Canvas — Site Studio

Platform control plane for VeerCanvas.

| | |
|--|--|
| **Domain** | [canvas.veerlabs.solutions](https://canvas.veerlabs.solutions/) |
| **Config** | `site.config.json` → `platform: true`, `ops: false` |
| **Admin port** | `8081` (`veercanvas-admin-canvas`) |
| **Template** | UI shell in this folder; scaffolding uses `sites/_templates/` |

## Role

- Create, patch, soft-delete, and deploy managed websites
- Browse / clone site templates (`registry.json`)
- `/` is the Site Studio shell (auth-gated)
- `/admin/` remains the Flask CMS for this host’s own content (rarely used for catalog work)

## Deploy

```bash
SITE_ID=canvas EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

See [docs/ADMIN_MANUAL.md](../../docs/ADMIN_MANUAL.md) and [docs/HANDOFF.md](../../docs/HANDOFF.md).
