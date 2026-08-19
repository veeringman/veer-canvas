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
| `/join` | Publishers | Register or sign in |
| `/publish` | Publishers | Submit news, ads, services, businesses, or a custom kind |
| `/admin/` | Hub operators | Moderation, features, offerings, hosted pages |
| `/cms/` | Authors | VeerCanvas CMS |
| `/b/veerlabs` | Public | Example hosted business page |

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
