# Himuda Housing Colony Sanyard — feature backlog

Future work for the resident portal / RWA app. Not scheduled; pick items when ready.

Last updated: 2026-08-07

---

## Reports (PDF export)

Export printable PDFs from the portal / EC desk:

- [x] **Pending dues report** — customizable columns; all / filtered / selected plots; letterhead + office bearers (EC)
- [x] **Report catalog + custom + saved templates** — select report type; custom dataset/columns; save/reuse templates
- [ ] **Plot dues statement** — one plot: balance, year dues, payments, remarks
- [ ] **Colony dues summary** — all plots: pending / paid / totals (EC)
- [ ] **Notices archive** — date range of published notices
- [ ] **Mailbox / concerns report** — open vs resolved by category (EC)
- [ ] **Works & events status** — active projects, costs, funding snapshot (EC)
- [ ] **Household / directory roster** — active plots + optional household members (EC)
- [ ] **EC decision / activity digest** — monthly summary for AGM or notice board
- [ ] **Observability summary** — usage snapshot for super admin (optional)

Prefer A4, RWA letterhead styling consistent with `documents/` print pads.

---

## Colony life & operations

- [ ] **Maintenance vote / consent board** — EC posts work + cost; one vote per plot (Approve / Object / Abstain); link to Works & Events
- [ ] **Visitor / guest pass QR** — timed QR for guests/delivery; plot + validity window
- [ ] **Water / power / tank schedule** — calendar of cuts or tanker days; opt-in alerts
- [ ] **Plot “attention” flags** — soft EC signals (dues reminder, missing contact, visit due)

## Trust & transparency

- [ ] **EC decision log** — short dated decisions, searchable by year (separate from long notices)
- [ ] **Spend tracker** — collections vs committed vs spent (high-level, tied to Works)
- [ ] **Anonymous concern mode** — optional blind mailbox; EC sees plot privately

## Daily life

- [ ] **Colony marketplace / giveaway** — short-lived posts (auto-expire ~7 days)
- [ ] **Skill / help directory** — opt-in resident skills/contacts; phone after request
- [ ] **Event RSVP + carpool** — for colony functions; seats and lift offers

## Evidence & money

- [ ] **Photo evidence on concerns** — one photo + note; resolve with before/after
- [x] **Dues receipt vault** — resident/EC upload payment proofs; EC verify updates ledger; payment history on Dues panel
- [x] **Reimbursement claims** — resident/EC submit expense claims with proof; EC approve (no ledger change) then mark reimbursed when paid out
- [x] **No Dues Certificate** — resident requests when clear; **No Dues Issuer** issues; resident downloads stored PDF
- [x] **Portal PDF attestation (HMAC + QR)** — free seal on No Dues + cash notes; verify at `/attest.html` (not IT Act eSign)
- [ ] **Seasonal digests** — monthly email/PDF: notices, concerns, works, own dues

## Digital signatures (future — cost-dependent)

Colony RWA needs authenticity first; legal eSign only if banks/regulators demand it.

| Option | What it is | Cost (ballpark) | When it makes sense |
|--------|------------|-----------------|---------------------|
| **1. Portal attestation + QR** (shipped) | HMAC seal of PDF hash + public verify page | **₹0** (uses site secret) | Default for certificates / cash notes |
| **2. PAdES Document Signer** | Org `.pfx` cert; Adobe shows signed PDF (pyHanko) | **~₹7.5k–₹30k+/yr** + ops | Banks want Adobe “signed” badge; RWA can hold org cert |
| **3. Aadhaar eSign (ASP)** | IT Act–binding eSign via licensed provider | Higher (per-sign + integration) | Legal filings / when statute requires |
| **4. Visual drawn/typed stamp** | Capture signature image on approve, stamp PDF | ₹0 software; weak trust | UX polish only — pair with option 1, not alone |

Revisit **2** or **3** only if cost is justified by external requirements; keep **1** as the free baseline.

## Platform / UX

- [x] **Web Push notifications** — VAPID subscribe + prefs; notices, concerns, messages, dues remind, Treasury, No Dues
- [x] **Message center** — colony channel + plot-to-plot DMs; text, images/PDF, emoji; EC moderate/pin; likes; profile photos
- [x] **Private RAG AI Assistant** — per-member Messages thread; answers from notices/Info Centre/FAQ; optional LLM via `data/ai.env`
- [ ] **Offline-first PWA polish** — cached notices + dues snapshot for weak network
- [ ] **Proxy / mandate letter** — owner grants timed “act for dues/concerns” (beyond view-only)
- [ ] **AGM mode** — attendance QR, agenda, live votes, minutes → Info Centre

## Ops / reliability

- [x] **Scheduled data backups** — Phase 1 on-box: daily `sqlite3 .backup` + uploads/`smtp.env`/configs under `/var/backups/veercanvas/<site>/` (7-day retention default). See `deploy/OPS-BACKUP.md`
- [x] **Google Drive upload** — Phase 2 wired (`deploy/ops/sync-to-drive.*` + Super admin settings); enable with `data/drive-sa.json` + folder share (see OPS-BACKUP.md)
- [ ] **Backup restore drill** — documented restore path + dry-run from Drive to staging *(on-box restore steps in OPS-BACKUP.md)*
- [x] **Log / event stream rollover** — journald 100M/7d + nginx logrotate 14d + backup log rotate
- [x] **Observability event pruning** — purge `access_events` older than 90 days with each backup run
- [x] **Backup & rollover alerts** — email via `smtp.env` (`BACKUP_ALERT_TO`) on backup failure or disk pressure

## Security & abuse protection

- [ ] **Hardening review** — headers (CSP, HSTS, X-Frame-Options, Referrer-Policy), cookie flags, TLS, secrets not in repo
- [ ] **Input / injection defense** — audit all write APIs for SQLi, XSS (stored/reflected), path traversal on uploads
- [ ] **Auth abuse limits** — rate-limit OTP request/verify, admin login, and sensitive POSTs (per IP + per plot)
- [ ] **DoS / flood shielding** — nginx request limits, connection limits, body size caps; optional fail2ban / Cloudflare / similar edge
- [ ] **Bot & honeypot hardening** — tighten existing honeypot; challenge suspicious traffic on login and public forms
- [ ] **Upload safety** — MIME/size allowlists, virus/malware scan where practical, no executable serving from upload dirs
- [ ] **Session & CSRF** — review cookie/session fixation, SameSite, CSRF on state-changing routes
- [ ] **Privilege checks audit** — EC vs delegate vs view-only vs super admin on every mutating endpoint
- [ ] **Dependency & server patch cadence** — pip/OS updates, unused surface reduction on EC2
- [ ] **Security logging** — alert on repeated auth failures, OTP abuse, and admin privilege changes

## Platformization / white-label (multi-RWA)

Take the Himuda Housing Colony Sanyard resident portal beyond one colony — configurable product for other RWAs / housing societies.

- [ ] **Tenant / society config** — name, seal/logo, colours, domain, address, motto, registration line (no hard-coded “Sanyard” in core)
- [ ] **Site template** — VeerCanvas site type e.g. `rwa-portal` spun from Studio; clone schema + empty DB per society
- [ ] **Branding pack** — letterhead, EC pad, PWA icons/manifest, email OTP templates per tenant
- [ ] **Feature flags per society** — dues, mailbox, works, info centre, household delegates, votes (enable what each RWA needs)
- [ ] **Plot ID rules** — pluggable normalizers (HIMUDA-style vs flat numbers vs towers/flats)
- [ ] **Ledger import adapters** — PDF/Excel parsers selectable per society (not one HIMUDA-only importer)
- [ ] **Roles vocabulary** — map “EC / Sabha / Managing Committee” labels without code forks
- [ ] **Billing / ops for VeerLabs** — which societies are live, backup status, SMTP health, support contacts
- [ ] **Shared core, isolated data** — one codebase (`rwa_portal` + portal UI); separate DB + uploads + secrets per tenant
- [ ] **Onboarding wizard** — create society → upload seal → import roster/ledger → invite first EC → go live
- [ ] **Docs & runbook** — “launch an RWA in a day” for sales/ops; SLA for backups and uptime

---

## Suggested priority (when starting next)

1. More PDF reports (plot statement, colony summary, concerns)
2. Security hardening (rate limits, headers, DoS shields) + Phase 2 Drive backups + restore drill
3. Platformization spike — extract tenant config + `rwa-portal` site template (white-label path)
4. Maintenance consent votes
5. Dues receipt vault
6. EC decision + spend snapshot

## Already shipped (context)

- Notices (pin, drafts, likes/comments)
- Dues / ledger + bank QR
- Colony mailbox (concerns)
- Directory, profile, household members (owner + delegates, view-only)
- Info Centre, Works & Events
- EC desk, observability (super admin)
- Print letterhead / EC committee pads (`documents/`)
- **Treasury entitlement** — explicit grant (default Treasurer); validate → confirm on payments, ledger rows, No Dues; download gated until confirmed; ledger amounts still show after EC verify with status icons
- Portal attestation (HMAC + QR) for No Dues / cash notes
