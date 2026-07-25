<p align="center">
  <img alt="VeerCanvas" src="../assets/branding/veer-canvas-icon.svg" width="96">
</p>

# VeerCanvas Admin

Flask CMS for authoring and publishing VeerCanvas sites. One process per site; flags unlock Site Studio or Ops APIs.

## Run locally

```bash
cd veer-canvas   # repo root
python3 -m venv .venv && source .venv/bin/activate
pip install -r admin/requirements.txt
export VEERCANVAS_SITE_ID=veerlabs
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/veerlabs"
python admin/admin_app.py
```

Admin UI: http://127.0.0.1:8080/admin/

For canvas Site Studio APIs:

```bash
export VEERCANVAS_SITE_ID=canvas
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/canvas"
export VEERCANVAS_PLATFORM=1
export PORT=8081
python admin/admin_app.py
```

For ops observability APIs:

```bash
export VEERCANVAS_SITE_ID=ops
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/ops"
export VEERCANVAS_OPS=1
export PORT=8083
python admin/admin_app.py
```

## Environment

| Variable | Purpose |
|----------|---------|
| `VEERCANVAS_ROOT` | Platform root path (repo root) |
| `VEERCANVAS_SITE_ID` | Site folder name under `sites/` |
| `VEERCANVAS_SITE_ROOT` | Override site content path |
| `VEERCANVAS_ADMIN_SECRET` | Flask session secret |
| `VEERCANVAS_PLATFORM` | Enable `/api/sites`, templates, platform session |
| `VEERCANVAS_OPS` | Enable `/api/observability`, ops session, cross-site inbox actions |
| `VEERCANVAS_VISITOR_TOKEN_TTL` | Visitor token lifetime seconds (default `3600`) |
| `PORT` / `VEERCANVAS_ADMIN_PORT` | Listen port |

Legacy `VEER_SITE_ROOT` is still honored for existing deployments.

## API surface by flag

| Flag | Extra routes |
|------|----------------|
| (none) | CMS + public engagement / access / visit |
| `VEERCANVAS_PLATFORM=1` | Site Studio site/template/deploy APIs |
| `VEERCANVAS_OPS=1` | Observability aggregate + cross-site inbox |

See [docs/API.md](../docs/API.md) and [docs/ADMIN_MANUAL.md](../docs/ADMIN_MANUAL.md).
