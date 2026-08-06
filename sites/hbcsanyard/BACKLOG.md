# HBC Sanyard — feature backlog

Future work for the resident portal / RWA app. Not scheduled; pick items when ready.

Last updated: 2026-08-07

---

## Reports (PDF export)

Export printable PDFs from the portal / EC desk:

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
- [ ] **Dues receipt vault** — resident uploads UPI screenshot; EC verifies; plot receipt history
- [ ] **Seasonal digests** — monthly email/PDF: notices, concerns, works, own dues

## Platform / UX

- [ ] **Offline-first PWA polish** — cached notices + dues snapshot for weak network
- [ ] **Proxy / mandate letter** — owner grants timed “act for dues/concerns” (beyond view-only)
- [ ] **AGM mode** — attendance QR, agenda, live votes, minutes → Info Centre

## Ops / reliability

- [ ] **Scheduled data backups** — regular interval dumps of `rwa.db` (+ optional uploads folder / smtp.env secrets policy)
- [ ] **Google Drive upload** — push encrypted or dated backup snapshots to a Drive folder (service account or OAuth; retain N days/weeks)
- [ ] **Backup restore drill** — documented restore path + dry-run from Drive to staging
- [ ] **Log / event stream rollover** — rotate app/nginx/systemd logs; size + time based retention
- [ ] **Observability event pruning** — archive or purge old `access_events` (and similar streams) on a schedule; keep hot window for EC/super-admin dashboards
- [ ] **Backup & rollover alerts** — email/notify super admin on backup failure or disk pressure

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

Take the HBC Sanyard resident portal beyond one colony — configurable product for other RWAs / housing societies.

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

1. PDF report exports (dues statement + colony summary)
2. Security hardening (rate limits, headers, DoS shields) + scheduled backups → Drive + log/event rollover
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
