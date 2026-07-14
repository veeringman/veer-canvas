# VeerCanvas

**VeerCanvas** is a content authoring and publishing platform for building rich web experiences — from static catalogs today to dynamic pages, server components, and APIs tomorrow.

The **VeerLabs Solutions** site (`sites/veerlabs/`) ships as the official reference implementation.

## Repository layout

```
veercanvas/
├── admin/           # Flask CMS (authoring, publish, import)
├── cli/             # Import, catalog sync, publish tooling
├── core/            # Shared platform libraries (expanding)
├── deploy/          # Remote deploy, nginx, systemd helpers
├── docs/            # Platform documentation
└── sites/
    ├── veerlabs/    # Sample: VeerLabs project catalog
    └── _template/   # Starter site scaffold
```

## Quick start (VeerLabs sample site)

```bash
# Install admin dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r admin/requirements.txt

# Run CMS locally against the VeerLabs site
export VEERCANVAS_SITE_ID=veerlabs
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/veerlabs"
python admin/admin_app.py
# Admin: http://127.0.0.1:8080/admin/

# Build public catalog (enabled projects only)
python cli/scripts/import_github_projects_full.py veeringman imported_projects \
  --site-root sites/veerlabs \
  --projects-json sites/veerlabs/projects.json \
  --write-public-catalog
```

## Deploy VeerLabs to EC2

```bash
SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh

# Refresh GitHub repos during deploy (opt-in)
SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh --import-repos
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VEERCANVAS_ROOT` | repo root | Platform root path |
| `VEERCANVAS_SITE_ID` | `veerlabs` | Site folder under `sites/` |
| `VEERCANVAS_SITE_ROOT` | `sites/<id>` | Override site content root |
| `VEERCANVAS_ADMIN_SECRET` | dev default | Flask session secret |
| `IMPORT_REPOS` / `--import-repos` | off | Fetch GitHub repos on deploy |

## Roadmap

VeerCanvas is intentionally evolving beyond static publishing:

- **Now:** catalog sites, rich sections (HTML/Markdown/Mermaid), admin CMS, GitHub import
- **Next:** dynamic routes, server APIs, component registry, webhooks
- **Future:** server components, edge rendering, multi-tenant hosting, plugin SDK

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Split from VeerSetu

This directory is designed to live in its own repository: **`veer-canvas`** (GitHub: `veeringman/veer-canvas`).

See [docs/MIGRATION.md](docs/MIGRATION.md) for publishing this tree as a standalone repo.
