# RWA society site scaffold

Template for cloning a new housing society portal on VeerCanvas.

## Quick start

1. Copy this folder to `sites/<site-id>/` (or use `deploy/create-rwa-society-site.sh` when available).
2. Edit `site-meta.json.example` → `site-meta.json` (name, logos, `composeBranding`, auth URLs).
3. Set `site.config.json` / deploy env: `SITE_ID`, domain, `ADMIN_PORT`.
4. Deploy: `SITE_ID=<id> EC2_KEY=... ./deploy/remote-deploy.sh`
5. In `index.html`, load the shared composer:
   ```html
   <script type="module" src="/veercanvas/core/composer/boot.js?v=1"></script>
   ```
   (On EC2 the site web root contains a `veercanvas/` tree from platform sync.)

## Document stack

- **Templates API** — `admin` + `scripts/rwa_templates.py` (copy from `hbcsanyard` scripts).
- **Composer** — `core/composer/` (browser editor + stationery designer).
- **Branding** — `core/document-engine/branding.py` + `site-meta.json` `composeBranding`.
- **Chrome versions** — `template_versions` table; publish letterheads before residents rely on pinned wraps.

## Assets

Place society seal, watermark, and favicons under `assets/`. Reference paths in `site-meta.json` (`logoPrint`, `logoWatermark`, `brandMark`).
