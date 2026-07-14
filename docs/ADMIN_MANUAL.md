VeerLabs Website Developer / Admin Manual
=========================================

This manual documents the VeerLabs static website, the admin UI, deployment flow, and the content package structure.

Overview
--------
- The website is a static site under `veerabs_website/`.
- Content is driven by `veerabs_website/projects.json` and per-project miniapp packages under `veerabs_website/miniapps/`.
- An admin Flask app at `deploy/admin_app.py` manages `projects.json` and miniapp deletion/update.
- Deployment is automated with `deploy/deploy_veerlabs_website_remote.sh`.
- Remote server configuration is managed via `deploy/nginx_veerlabs.solutions.conf` when present.

Repository Layout
-----------------
- `veerabs_website/`
  - `index.html`, `project.js`, styles, and static assets for the public site.
  - `projects.json` — the website project catalog used by the homepage/dashboard.
  - `miniapps/<slug>/` — package folders containing project metadata and documentation.
  - `scripts/import_github_projects_full.py` — importer script for GitHub repos.
- `deploy/`
  - `admin_app.py` — Flask admin UI and API.
  - `requirements.txt` — Python dependencies for the admin app.
  - `deploy_veerlabs_website_remote.sh` — remote deployment script.
  - `nginx_veerlabs.solutions.conf` — recommended nginx site config for deployment.
  - `README_admin.md` — short admin app usage notes.

Website Content Model
---------------------
- `projects.json` is the primary catalog file. Each entry is a project object with fields like:
  - `slug`
  - `name`
  - `subtitle`
  - `logo`
  - `details` or `body`
  - `tags`
- Miniapp packages under `veerabs_website/miniapps/<slug>/` typically contain:
  - `project.json` — project metadata for the package
  - `source.json` — source repository metadata
  - `README.md` — detailed project description
  - `assets/` — logo and media files

Admin App
---------
- File: `deploy/admin_app.py`
- Default login: `admin`
- Default password: `vijay123`
- Default admin service URL: `http://<server>/admin/`

Capabilities:
- View the current `projects.json` project list.
- Delete a miniapp package by slug.
- Remove the corresponding entry from `projects.json`.
- Lookup a project by slug/name/subtitle.
- Edit a project's JSON and save it back to both `projects.json` and `miniapps/<slug>/project.json`.

How it runs
------------
- The admin app reads `VEER_SITE_ROOT` to locate the website root.
- Default `SITE_ROOT` is `../veerabs_website` relative to `deploy/admin_app.py`.
- When deployed, the systemd service sets `VEER_SITE_ROOT=/var/www/veerlabs.solutions`.

Deployment Flow
---------------
1. Sync website files and deploy assets from the local repo to remote.
2. Sync `deploy/` to the remote deployment folder.
3. Install or update server packages and Python dependencies.
4. Install the nginx site config from `deploy/nginx_veerlabs.solutions.conf` if available.
5. Create and enable `veerlabs-admin.service`.
6. Reload nginx.

Deploy script
-------------
- Path: `deploy/deploy_veerlabs_website_remote.sh`
- Usage:

```bash
chmod +x deploy/deploy_veerlabs_website_remote.sh
./deploy/deploy_veerlabs_website_remote.sh ubuntu@3.216.30.113 /var/www/veerlabs.solutions
```

- Default SSH key: `~/VeerSetuHost.pem` or environment variable `SSH_KEY`.
- Local site source: `veerabs_website/`.
- Remote root: default `/var/www/veerlabs.solutions`.

Nginx Configuration
-------------------
- Recommended config file: `deploy/nginx_veerlabs.solutions.conf`
- The deploy script copies this file to `/etc/nginx/sites-available/veerlabs.solutions`.
- The config proxies `/admin/`, `/login`, `/logout`, and `/api/` to the admin app on `127.0.0.1:8080`.
- Static content is served directly from the website root.

Admin Service
-------------
- Systemd unit: `/etc/systemd/system/veerlabs-admin.service`
- ExecStart: `/usr/bin/python3 /var/www/veerlabs.solutions/deploy/admin_app.py`
- Service name: `veerlabs-admin.service`

Common Commands
---------------
- Deploy the site:

```bash
./deploy/deploy_veerlabs_website_remote.sh ubuntu@3.216.30.113 /var/www/veerlabs.solutions
```

- Start/stop the admin service on the remote host:

```bash
ssh -i ~/VeerSetuHost.pem ubuntu@3.216.30.113 sudo systemctl restart veerlabs-admin.service
ssh -i ~/VeerSetuHost.pem ubuntu@3.216.30.113 sudo systemctl status veerlabs-admin.service
```

- Check nginx configuration and reload:

```bash
ssh -i ~/VeerSetuHost.pem ubuntu@3.216.30.113 sudo nginx -t
ssh -i ~/VeerSetuHost.pem ubuntu@3.216.30.113 sudo systemctl reload nginx
```

- Validate admin route locally on the server:

```bash
curl -I http://127.0.0.1:8080/login
```

- Validate public admin route through nginx:

```bash
curl -I http://veerlabs.solutions/admin/
```

Project Imports and Content Updates
-----------------------------------
- Update `projects.json` and package content with the importer:

```bash
cd veerabs_website
python3 scripts/import_github_projects_full.py veeringman --site-root . --projects-json projects.json --replace-existing
```

- After import, verify the generated package folders under `veerabs_website/miniapps/` and the updated `projects.json`.
- Then deploy to the remote host.

Troubleshooting
---------------
- If `/admin/` is 404, ensure the nginx site config is present and the admin app is running.
- If `/login` is 404, verify nginx is proxying `/login` to the app and the service listens on port `8080`.
- If `favicon.ico` or static assets fail, confirm the site root contains the expected files and nginx `root` is correct.
- If admin edits do not persist, check that `projects.json` is readable/writable by the admin service user.

Security Notes
--------------
- Change the default password immediately for production use.
- Use HTTPS on the public site and admin interface.
- Restrict access to the admin service by firewall or reverse proxy if possible.

Further Reading
---------------
- `deploy/README_admin.md` — quick admin app notes.
- `deploy/admin_app.py` — admin UI source and route definitions.
- `deploy/deploy_veerlabs_website_remote.sh` — remote deployment automation.
- `veerabs_website/scripts/import_github_projects_full.py` — GitHub importer for site packages.
