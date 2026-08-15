# City of Mandi

Independent civic hub for **Mandi, Himachal Pradesh**. Not a Municipal Corporation, District Administration, or HIMUDA website.

| | |
|--|--|
| **Site id** | `cityofmandi` |
| **Live host** | `cityofmandi.com` (also `cityofmandi.veerlabs.solutions`) |
| **Public domain** | `cityofmandi.com` |
| **CMS** | `/cms/` (VeerCanvas authoring) |
| **Portal desk** | `/admin/` (hub operators — features, services, business pages) |
| **Business pages** | `/b/{slug}` now · `{slug}.cityofmandi.com` after the domain |
| **Admin service** | `veercanvas-admin-cityofmandi` on port **8085** |

## Surfaces

| URL | Who | Purpose |
|-----|-----|---------|
| `/` | Public | City hub |
| `/adda` | Public + Adda/publisher accounts | **Mandi Adda** — city chat (public rooms, DMs, private channels, Sanyard pulse) |
| `/join` | Publishers | Register or sign in |
| `/publish` | Publishers | Submit news, ads, services, businesses, or a custom kind |
| `/admin/` | Hub operators | Moderation, features, offerings, hosted pages, **sponsored header ads** |
| `/cms/` | Authors | VeerCanvas CMS |
| `/b/veerlabs` | Public | Example hosted business page |

## Mandi Adda

City chat at `/adda`. Guests can **read** public topic rooms. Signing in with a **Mandi Adda** account (or a publisher account via `/join?next=/adda`) unlocks posting, DMs, and private channels. Hub operators can moderate public rooms. Neighbourhood syndicate posts from Sanyard appear in the read-only **Sanyard pulse** room. Storage lives in `data/hub.db` (`adda_*` tables); files under `data/adda/`.

**Safety:** posts are checked by the Rust **Veer AI** sidecar (`services/veer-ai`, `127.0.0.1:8095`). Mode in `data/ai.env`: `flag` (default, hold as hidden), `block`, or `off`.

Same first-boot CMS/operator login: username `admin`. Change it after sign-in.

## Publish flow

Anyone can register at `/join` and submit a listing at `/publish`. Kinds: news, ad, service, business, place, event, or a custom type. Submissions stay **pending** until an operator approves them at `/admin/`. Approved hosted businesses also land in `businesses.json` as `/b/{slug}`.

## Business monetization

Plans in the portal desk:

- **Listed** — card on the hub
- **Featured** — highlighted card
- **Hosted** — own page at `/b/{slug}`, later `{slug}.cityofmandi.com` (see `wildcard.cityofmandi.com.http.conf`)

## Deploy

```bash
SITE_ID=cityofmandi EC2_KEY=/path/to/key.pem ./deploy/remote-deploy.sh
```

## Next

See **[BACKLOG.md](./BACKLOG.md)**.
