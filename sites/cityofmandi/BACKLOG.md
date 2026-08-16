# City of Mandi — backlog & TODOs

Unofficial civic hub. Do not impersonate government, MC Mandi, or HIMUDA.

**How to use:** Check boxes as items ship. Prefer **depth on one daily loop** over new boards.  
**Source of truth for agents:** this file + `.cursor/rules/cityofmandi-backlog.mdc`

---

## Tracking legend

| Status | Meaning |
|--------|---------|
| `[ ]` | Open |
| `[~]` | In progress |
| `[x]` | Done / closed |
| `[!]` | Blocked (note why) |

---

## Active sprint — polish & My Mandi

- [x] **My Mandi home** — collapse hub to preferred board + locality (`hub_my_mandi`)
- [x] Hero panel: board label, locality, Open my board / Change / Explore all
- [x] Boards menu updates preferred board when picking a board
- [x] Account toggle: “My Mandi home”
- [x] **Responsive UX pass** — tap targets, header stack, board actions wrap, grids, My Mandi CTAs
- [ ] Soften demo CTAs once ≥3 real merchants on flagship board
- [ ] Order status timeline on `/order` (accepted → on the way → delivered)
- [ ] Enquiry / interest → WhatsApp deep-link (broker + profession boards)

---

## Priority queue (do next)

### P0 — Make one loop real
- [ ] Choose flagship: **Food+delivery** *or* **Labour morning** (pick one)
- [ ] Onboard 5–10 real partners on that board (not demos)
- [ ] Onboard 3–5 riders / providers for that loop
- [ ] Hide or demote demo shops for flagship board

### P1 — Trust & money
- [ ] Live **Razorpay** keys in `data/payments.env` (packs + online pay)
- [ ] Publisher email / OTP verification
- [ ] Phone-checked badge on partners & shops
- [ ] Wildcard `{slug}.cityofmandi.com` after DNS `*.cityofmandi.com`

### P2 — Clarity
- [ ] Role labels in UI: Citizen · Partner · Broker/Merchant · Rider
- [ ] Unified account (one phone/email, roles attached)
- [ ] Admin weekly metrics: DAU boards, orders, claims, live listings

### P3 — Later (not now)
- [ ] AI moderator model backends (rules engine already shipped)
- [ ] Events calendar
- [ ] Transport & weather pointers
- [ ] More neighbourhood portals besides Sanyard
- [ ] Mandi Adda push / AuthBuddy SSO
- [ ] Payments / invoicing for listed · featured · hosted **publisher** plans
- [ ] Multi-shop cart, escrow, multi-city deploys

---

## Shipped (closed)

### Foundation
- [x] Civic landing + teal-slate / copper theme
- [x] Hosts: `cityofmandi.veerlabs.solutions`, `cityofmandi.com` + www
- [x] CMS `/cms`, hub operators `/admin`
- [x] Hosted business pages `/b/{slug}`
- [x] Mobile-first UX pass

### Auth & prefs
- [x] Publisher `/join`, listing desk `/publish`
- [x] Partner desks `/labour` `/taxi` `/partner`
- [x] Header Sign in; preferred board + locality
- [x] Content language EN/हिं site-wide + on register/login
- [x] Expanded localities + map/GPS for live boards
- [x] `/account` preferences

### Profession boards
- [x] Labour + taxi (privacy until response)
- [x] Experts, Vehicle, Doc on call, Tours, Tutors, Home services

### Commerce
- [x] P0 Food — shop, cart, COD, merchant desk
- [x] P1 Delivery claim race `/delivery`
- [x] P2–P3 Grocery, hardware, haulage + demos
- [x] P4 Sponsored packs + Razorpay-ready / demo pay
- [x] **To rent or sell** — brokers as businesses; categories; `/b/demo-broker`

### Community
- [x] Mandi Adda
- [x] Sponsored header ads
- [x] Public feed + moderation queue

---

## Locked product decisions

- Merchant = publisher + hosted shop; rider = `hub_providers`; checkout = phone (+ optional account)
- Delivery v1 = on-duty **claim race**
- Payment = COD always; Razorpay when keys set; demo when `HUB_PAYMENTS_DEMO=1`
- UX = mobile-first
- **My Mandi** = after prefs/login, home collapses to preferred board + locality; “Explore all boards” exits
- Guardrails: unofficial disclaimer; no fake civic authority; link out to gov sites

### Commerce smoke
1. `/b/demo-rasoi` · kirana · hardware · tempo · **demo-broker**
2. `/merchant` → accept order → job (non-rentals)
3. `/delivery?role=…` → claim
4. Promote pack (demo or Razorpay)

---

## Session notes

| Date | Note |
|------|------|
| 2026-08-16 | Localities, geo, new profession boards, EN/हिं, rentals board |
| 2026-08-17 | My Mandi home + backlog tracking file |
| 2026-08-17 | Responsive UX: buttons ≥44px, header reflow, board rails wrap, tablet grids |

**Deploy:** `SITE_ID=cityofmandi EC2_KEY=~/Downloads/VeerSetuHost.pem ./deploy/remote-deploy.sh`
