# City of Mandi — backlog

Unofficial civic hub. Do not impersonate government, MC Mandi, or HIMUDA.

## Now

- [x] Civic landing from the Sanyard homepage foundation
- [x] Teal-slate / copper theme (distinct from colony navy / gold)
- [x] Virtual host on `cityofmandi.veerlabs.solutions`
- [x] Extra-domain nginx examples ready for `cityofmandi.com`
- [x] First deploy on `cityofmandi.veerlabs.solutions`
- [x] CMS at `/cms`; hub operators at `/admin`
- [x] Hosted business pages (`/b/{slug}`, VeerLabs sample)
- [x] Attach `cityofmandi.com` + `www` (DNS A → 3.216.30.113)
- [ ] Wildcard `{slug}.cityofmandi.com` after `*.cityofmandi.com` DNS
- [ ] Payments / invoicing for listed · featured · hosted plans

## Next

- [x] Publisher register / sign-in (`/join`) and listing desk (`/publish`)
- [x] Operator moderation queue at `/admin/`
- [x] Public feed of approved news, ads, services, places, businesses
- [x] Mandi Adda city chat (`/adda`) — public rooms, Adda + publisher identity, DMs, private channels, Sanyard pulse bridge
- [x] Sponsored header ads manager (animation types + Independence Day seed)
- [ ] AI moderator for Mandi Adda (hate, obscenity, and related abuse) — **v1 shipped**: Rust `veer-ai` rules engine + Flask flag/block modes; model backends next
- [ ] Events calendar
- [ ] Transport & weather pointers
- [ ] More neighbourhood portals besides Sanyard
- [ ] Email verification for publishers
- [ ] Hindi (and later Pahari) copy
- [ ] Mandi Adda push notifications / AuthBuddy SSO

## Guardrails

- Footer and About must keep the unofficial disclaimer
- No civic tax, licence, tender, or “official notice” language
- Link out to government sites instead of mirroring them
