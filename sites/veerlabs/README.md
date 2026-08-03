# VeerLabs — reference catalog

Official sample VeerCanvas site: public project catalog for VeerLabs Solutions.

| | |
|--|--|
| **Domain** | [veerlabs.solutions](https://veerlabs.solutions) |
| **Config** | `platform: false`, `ops: false` |
| **Admin port** | `8080` (`veercanvas-admin`) |
| **Template** | `catalog-static` |

## Role

- Public tile grid + project detail pages
- Content CMS at `/admin/` (projects, import, publish, branding)
- `engagement.js` — likes/comments, contact modal, visit beacon
- **AuthBuddy Agent** — Sign in / Register; Learn More → `project.html` gated when `auth.gateAllLearnMore` is true
- **Custom error pages** — `/errors/{403,404,500,502,503,504}.html` (no nginx default banners)

## AuthBuddy via VeerSetu (important)

AuthBuddy IdP runs on the **LAN** (`192.168.29.78:18080`). The public site runs on **EC2**. Connectivity is **not** direct LAN from the browser.

```text
Browser → veerlabs.solutions nginx (EC2)
       → 127.0.0.1:18080   (veersetu connect authbuddy)
       → VeerSetu relay
       → LAN AuthBuddy :18080
```

VeerSetu project: `/Users/vijay/rnd/projects/veersetu` (`deploy/public-gateway/`).

| Config | Value |
|--------|--------|
| Same-origin agent API | `agentBaseUrl: ""` → `/agent/*`, `/auth/*` on this site |
| Public IdP / account UI | `https://authbuddy.veerlabs.solutions` |
| Nginx upstream | `http://127.0.0.1:18080` only — never `192.168.29.78` from the public vhost |

`site-meta.json` → `auth`:

```json
{
  "agentBaseUrl": "",
  "idpPublicUrl": "https://authbuddy.veerlabs.solutions",
  "clientId": "veerlabs-web",
  "gateAllLearnMore": true
}
```

Session id from `/auth/login` is stored in `localStorage` and sent as `Authorization: Bearer` to `/agent/v1/session`.

### Auth UX (current)

| Piece | Behavior |
|-------|----------|
| Header | Guest: Sign in / Register. Signed-in: username + Sign out (mutually exclusive) |
| Policy | `GET /agent/v1/policy` — VeerLabs blueprint requires **password + MFA** (`totp` / `hotp` / `passkey`) |
| Register | Password required; passwordless hidden while policy says so; MFA enroll forced before RP access |
| Login | Adaptive: `POST /auth/login/options` then password and/or OTP / passkey |
| Gate | MFA-pending sessions → `/agent/v1/session` returns `authenticated: false`; Learn more stays gated |
| Files | `auth.js`, `auth-page.js`, `auth.html`, `style.css`, `site-meta.js` |

IdP policy seed: AuthBuddy `scripts/seed-veerlabs-policy.sh` · [VEERLABS_POLICY.md](../../../AuthBuddy/docs/agent/VEERLABS_POLICY.md) (sibling repo).

## Error pages

Branded pages under `errors/` are wired in `deploy/nginx/examples/veerlabs.solutions.conf` with `server_tokens off` and `proxy_intercept_errors on` so upstream/nginx defaults are not shown.

## Deploy

```bash
SITE_ID=veerlabs EC2_KEY=/path/to/VeerSetuHost.pem ./deploy/remote-deploy.sh
# Ensure veersetu-gateway-authbuddy is active on EC2 (binds 127.0.0.1:18080)
```

See [docs/ADMIN_MANUAL.md](../../docs/ADMIN_MANUAL.md) · VeerSetu [deploy/public-gateway/README.md](../../../veersetu/deploy/public-gateway/README.md).
