# Printable pads — HBC Sanyard RWA

These files are **for print production only**. They are not linked from the resident portal.

## Files

| File | Purpose |
|------|---------|
| `rwa-letterhead-blank.html` | Blank **letterhead pad** — org header + empty writing area |
| `ec-committee-pad.html` | **Executive Committee chart** — office bearers + member list (regenerate from DB) |

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
