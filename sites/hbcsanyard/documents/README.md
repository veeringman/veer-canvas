# Printable pads — Himuda Housing Colony Sanyard RWA

These files are **for print production only**. They are not linked from the resident portal.

**Logo:** managed registry — [`../assets/mhws-logo/logo.manifest.json`](../assets/mhws-logo/logo.manifest.json) lists every place the logo is applied. Roles: `print` (headers), `watermark`, `web256` (Info Centre mastheads). After changing artwork: `python3 scripts/export_logo_variants.py && python3 scripts/check_logo_refs.py`.

## Files

| File | Purpose |
|------|---------|
| `mhws-letterhead-pad.html` | Official **letterhead pad** — compact header, office bearers, watermark |
| `mhws-cash-receipt-booklet.html` | **Cash receipt booklet** — 210 mm wide slips: 2 on A5 landscape (1×2); 3 or 4 on A4 portrait (1×3 / 1×4) |
| `rwa-letterhead-blank.html` | Blank **letterhead pad** — org header + empty writing area |
| `ec-committee-pad.html` | **Executive Committee Charter** — office bearers + members (letterhead theme; regenerate from DB) |
| `proceedings-gh-mom-pad.html` | **General House MOM Register** — 2-page blank form for detailed minutes |
| `proceedings-ec-mom-pad.html` | **Executive Committee MOM Register** — 2-page blank form for detailed minutes |
| `resolution-engage-advocate-path-case-2026.html` | **EC resolution** — engage Advocate Shailesh Sharma for the pending path / link-road case; professional fee ₹50,000 (covering letter + certified copy) |
| `resolution-engage-advocate-path-case-2026.txt` | Plain-text twin of the advocate engagement resolution (Apple Pages) |

These are also catalogued under **EC Desk → Templates** (upload more with title / category / tags).

## Regenerate EC chart from database

From the site folder:

```bash
# Local DB
python3 scripts/export_ec_pad.py

# Live server DB (after SSH)
python3 scripts/export_ec_pad.py --db /var/www/hbcsanyard.veerlabs.solutions/data/rwa.db
```

Set EC **official titles** (President, Secretary, etc.) in EC desk → Resident contacts so they appear under Office Bearers.

## Print / press

1. Open the HTML file in Chrome or Safari.
2. **Print → Save as PDF** (A4, no headers/footers, margins default).
3. Send PDF to your print shop for letterhead pads or EC chart pads.

Tip: For blank letterhead pads, use `rwa-letterhead-blank.html`. For the full EC roster sheet (like a Sabha chart), use `ec-committee-pad.html`.
