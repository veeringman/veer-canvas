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
| `site-deploy.sh` | Runs on the host (nginx + systemd) |
| `lib/site-env.sh` | Resolves `SITE_ID` → domain, ports, flags |
| `nginx/examples/` | Per-domain nginx configs |

Full operator documentation: [docs/DEPLOY.md](../docs/DEPLOY.md) · [docs/HANDOFF.md](../docs/HANDOFF.md).
