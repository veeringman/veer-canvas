# MHWS logo pack — managed registry

Single source of truth: [`logo.manifest.json`](logo.manifest.json).

## How to change the logo

- 1. Edit / regenerate master: python3 scripts/regenerate_official_logo.py
- 2. Export variants: python3 scripts/export_logo_variants.py
- 3. Verify every consumer: python3 scripts/check_logo_refs.py
- 4. Bump logo.manifest.json version + portal cache (?v=…) if browsers stick
- 5. Deploy site assets + documents + scripts

When you add a new place that shows the logo, **append a consumer** in
`logo.manifest.json`, then run `python3 scripts/check_logo_refs.py`.

## Roles

| Role | Path | Use |
|------|------|-----|
| `official` | `assets/mhws-logo/mhws-logo-official.png` | Canonical transparent seal — portal hero, mini seal, proceedings UI |
| `print` | `assets/mhws-logo/mhws-logo-print.png` | Print / PDF headers — letterheads, receipts, certificates, pads |
| `watermark` | `assets/mhws-logo/mhws-logo-watermark.png` | Pre-faded watermark for pads, receipts, PDF letterhead chrome |
| `web512` | `assets/mhws-logo/mhws-logo-web-512.png` | Large web / site-meta brand web mark |
| `web256` | `assets/mhws-logo/mhws-logo-web-256.png` | Info Centre HTML mastheads, attest page |
| `icon128` | `assets/mhws-logo/mhws-logo-icon-128.png` | Compact UI icons |
| `icon64` | `assets/mhws-logo/mhws-logo-icon-64.png` | Tiny chrome / lists |
| `ogSquare` | `assets/mhws-logo/mhws-logo-og-square.png` | Square share / OG-style mark on cream |
| `favicon` | `assets/favicon-192.png` | Browser favicon + PWA shortcut icons |
| `appleTouch` | `assets/apple-touch-icon.png` | Apple touch 180 (also mirrored at /apple-touch-icon.png) |
| `appleTouchRoot` | `apple-touch-icon.png` | Root apple-touch for iOS home screen |
| `appleTouch167` | `assets/apple-touch-icon-167.png` | Apple touch 167 |
| `appleTouch152` | `assets/apple-touch-icon-152.png` | Apple touch 152 |
| `pwa512` | `assets/hbcs-sanyard-seal-512.png` | PWA any-purpose 512 |
| `pwaMaskable` | `assets/hbcs-sanyard-seal-512-maskable.png` | PWA maskable 512 (navy plate) |
| `sealMark` | `assets/hbcs-sanyard-seal-mark.png` | Legacy transparent mark path (kept in sync) |
| `seal240` | `assets/hbcs-sanyard-seal-240.png` | Legacy 240 seal (kept in sync) |

## Consumers (places the logo is applied)

| Id | File | Role | Kind | Note |
|----|------|------|------|------|
| `portal-gate` | `index.html` | `official` | `img` | Gate hero seal |
| `portal-mini` | `index.html` | `official` | `img` | Signed-in brand mini seal |
| `portal-favicon` | `index.html` | `favicon` | `link` | Portal favicon |
| `portal-apple-touch` | `index.html` | `appleTouch` | `link` | Apple touch icons (180/167/152 + root) |
| `portal-proceedings-seal` | `portal.js` | `official` | `img` | Proceedings modal seal markup |
| `sw-precache-official` | `sw.js` | `official` | `precache` | Service worker precache |
| `sw-precache-web256` | `sw.js` | `web256` | `precache` | Service worker precache |
| `sw-precache-favicon` | `sw.js` | `favicon` | `precache` | Push / precache favicon |
| `sw-precache-pwa512` | `sw.js` | `pwa512` | `precache` | PWA 512 precache |
| `sw-precache-maskable` | `sw.js` | `pwaMaskable` | `precache` | PWA maskable precache |
| `manifest-favicon` | `manifest.webmanifest` | `favicon` | `manifest` | Web app manifest icons / shortcuts |
| `manifest-pwa512` | `manifest.webmanifest` | `pwa512` | `manifest` | PWA any 512 |
| `manifest-maskable` | `manifest.webmanifest` | `pwaMaskable` | `manifest` | PWA maskable 512 |
| `manifest-apple-root` | `manifest.webmanifest` | `appleTouchRoot` | `manifest` | Root apple-touch in manifest |
| `site-meta-brand` | `site-meta.json` | `official` | `meta` | brandMark |
| `site-meta-favicon` | `site-meta.json` | `favicon` | `meta` | favicon |
| `site-meta-print` | `site-meta.json` | `print` | `meta` | logoPrint |
| `site-meta-watermark` | `site-meta.json` | `watermark` | `meta` | logoWatermark |
| `site-meta-web` | `site-meta.json` | `web512` | `meta` | logoWeb |
| `attest-mark` | `attest.html` | `web256` | `img` | Attestation verify page seal |
| `attest-favicon` | `attest.html` | `favicon` | `link` | Attest favicon |
| `pdf-reports-header` | `scripts/rwa_reports.py` | `print` | `python` | PDF report / certificate / receipt headers (LOGO_CANDIDATES) |
| `pdf-reports-watermark` | `scripts/rwa_reports.py` | `watermark` | `python` | PDF letterhead watermark (WATERMARK_CANDIDATES) |
| `export-ec-pad` | `scripts/export_ec_pad.py` | `print` | `img` | EC chart HTML generator seal src |
| `doc-letterhead-logo` | `documents/mhws-letterhead-pad.html` | `print` | `img` | Letterhead header logo |
| `doc-letterhead-wm` | `documents/mhws-letterhead-pad.html` | `watermark` | `img` | Letterhead watermark |
| `doc-receipt-logo` | `documents/mhws-cash-receipt-booklet.html` | `print` | `img` | Cash receipt slip logos (×3) |
| `doc-receipt-wm` | `documents/mhws-cash-receipt-booklet.html` | `watermark` | `css-url` | Cash receipt watermark background |
| `doc-letterhead-blank` | `documents/rwa-letterhead-blank.html` | `print` | `img` | Blank letterhead seal |
| `doc-ec-pad` | `documents/ec-committee-pad.html` | `print` | `img` | EC committee pad seal |
| `doc-proceedings-ec` | `documents/proceedings-ec-mom-pad.html` | `print` | `img` | EC MoM pad seal |
| `doc-proceedings-gh` | `documents/proceedings-gh-mom-pad.html` | `print` | `img` | GH MoM pad seal |
| `info-bylaws-mast` | `documents/mhws-sanyard-rules-bylaws.html` | `web256` | `img` | Info Centre — Rules & Bye-laws masthead |
| `info-bylaws-favicon` | `documents/mhws-sanyard-rules-bylaws.html` | `favicon` | `link` | Info Centre — Rules favicon |
| `info-act-mast` | `documents/hp-societies-registration-act-2006.html` | `web256` | `img` | Info Centre — HP Societies Act masthead |
| `info-act-favicon` | `documents/hp-societies-registration-act-2006.html` | `favicon` | `link` | Info Centre — Act favicon |
| `info-civil-mast` | `documents/civil-suit-2023-sanyardh-path-right.html` | `web256` | `img` | Info Centre — Civil Suit case file masthead |
| `info-civil-favicon` | `documents/civil-suit-2023-sanyardh-path-right.html` | `favicon` | `link` | Info Centre — Civil Suit favicon |

Version: `20260810final1` · Updated: `2026-08-10`

Master: `assets/mhws-logo/mhws-logo-official.png`  
Locked: `assets/mhws-logo/mhws-logo-official-locked-20260810.png`  
Archive (regen source): `assets/mhws-logo/mhws-logo-official-archive-20260810.png`
