# HBCS Sanyard RWA

Residents Welfare Association — **Himuda Housing Colony Sanyard, Mandi** (HIMUDA).

| | |
|--|--|
| **Site id** | `hbcsanyard` |
| **Domain** | `hbcsanyard.veerlabs.solutions` |
| **Database** | SQLite `data/rwa.db` |
| **Managed by** | [VeerCanvas](https://github.com/veeringman/veer-canvas) |
| **App repo** | `veeringman/hbcsanyard` (companion) |

## Surfaces

| URL | Audience | Purpose |
|-----|----------|---------|
| `/` | Residents + EC | Resident portal (OTP login, notices, dues, directory, profile) |
| `/admin/` | Authors / EC | **VeerCanvas CMS** — content authoring & publish (not the resident app) |

EC members with `role=admin` also see an **EC desk** tab inside the portal for notices, ledger import, and role promotion. That is separate from `/admin` CMS.

## Roles

- **admin** (Executive Committee) — publish notices, import PDF ledger, view full dues, promote members
- **resident** — view notices, own dues, directory, edit own profile

Login: **plot / house number** + **email OTP** via Gmail SMTP (`housingcolonysanyard@gmail.com`). Without App Password configured, API returns `devCode`. AuthBuddy planned later.

## Database + PDF import

```bash
# From iCloud / any path
.venv/bin/python sites/hbcsanyard/scripts/import_ledger_pdf.py \
  "/Users/vijay/Library/Mobile Documents/com~apple~CloudDocs/HIMUDA HOUSING COLONY SANYARD LIST.pdf"

# Or after copying to data/imports/
.venv/bin/python sites/hbcsanyard/scripts/import_ledger_pdf.py
```

EC desk can also upload the PDF via `/api/rwa/ledger/import`.

## Gmail SMTP (OTP)

1. Enable 2-Step Verification on the Gmail account.
2. Create an [App Password](https://myaccount.google.com/apppasswords).
3. Copy the example and set the password (never commit this file):

```bash
cp sites/hbcsanyard/data/smtp.env.example sites/hbcsanyard/data/smtp.env
# edit RWA_SMTP_PASS=xxxx xxxx xxxx xxxx
```

Defaults: `smtp.gmail.com:587`, from/user `housingcolonysanyard@gmail.com` (OTP, alerts, ops).  
On the server, `data/smtp.env` is loaded by systemd (`EnvironmentFile`) and preserved across deploys.

## Local run

```bash
export VEERCANVAS_SITE_ID=hbcsanyard
export VEERCANVAS_SITE_ROOT="$(pwd)/sites/hbcsanyard"
export PORT=8084
python admin/admin_app.py
# Portal: http://127.0.0.1:8084/site/   (or open sites/hbcsanyard/index.html via static host + API proxy)
```

For static + API together, deploy behind nginx (see `deploy/nginx/examples/hbcsanyard.veerlabs.solutions.conf`).

## Deploy

```bash
SITE_ID=hbcsanyard EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

`data/rwa.db` is preserved across rsync deploys.

## SMTP (production OTP)

| Env | Purpose |
|-----|---------|
| `RWA_SMTP_HOST` | SMTP host |
| `RWA_SMTP_PORT` | default `587` |
| `RWA_SMTP_USER` / `RWA_SMTP_PASS` | auth |
| `RWA_SMTP_FROM` | from address |
| `RWA_OTP_TTL` | seconds (default 600) |

## Next

See **[BACKLOG.md](./BACKLOG.md)** for planned features (PDF reports, consent votes, receipt vault, etc.).

Older notes:

- Excel upload for payment ledger refresh
- AuthBuddy SSO
- Companion mobile app against the same `/api/rwa/*` surface
