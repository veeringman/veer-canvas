# VeerCanvas Admin

Flask CMS for authoring and publishing VeerCanvas sites.

## Run locally

```bash
cd veercanvas
python3 -m venv .venv && source .venv/bin/activate
pip install -r admin/requirements.txt
export VEERCANVAS_SITE_ID=veerlabs
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/veerlabs"
python admin/admin_app.py
```

Admin UI: http://127.0.0.1:8080/admin/

## Environment

| Variable | Purpose |
|----------|---------|
| `VEERCANVAS_ROOT` | Platform root (`veercanvas/`) |
| `VEERCANVAS_SITE_ID` | Site folder name under `sites/` |
| `VEERCANVAS_SITE_ROOT` | Override site content path |
| `VEERCANVAS_ADMIN_SECRET` | Flask session secret |

Legacy `VEER_SITE_ROOT` is still honored for existing deployments.
