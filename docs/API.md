# VeerCanvas API

Base URL is the site origin (nginx proxies `/api/` to that site’s Flask admin). Auth:

| Mechanism | When |
|-----------|------|
| Session cookie | After `/admin/login` — CMS, platform, ops, inbox |
| `X-Visitor-Token` (or body/query `token`) | Public Learn More / visit auth mode |
| None | Open public engagement + visit recording |

Honeypot fields (`website`, `companyUrl`) on public POSTs are ignored when filled.

---

## CMS (login required)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/projects` | Full catalog |
| GET | `/api/project/<slug>` | One project |
| POST | `/api/create` | New project |
| POST | `/api/update` | Save project |
| POST | `/api/toggle` | Enable/disable |
| POST | `/api/reorder` | Order |
| POST | `/api/delete` | Delete + exclusion |
| POST | `/api/upload-logo` | Project logo |
| POST | `/api/upload-brand` | Site brand marks |
| GET/POST | `/api/site-meta` | Public meta |
| POST | `/api/import` | GitHub import |
| GET/POST | `/api/github-status` | Token/status |
| GET/POST | `/api/github-token` | Store token |
| POST | `/api/mark-reimport` | Flag reimport |
| POST | `/api/publish` | Bump version |
| GET | `/api/lookup` | Search |

---

## Platform (login + `VEERCANVAS_PLATFORM`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/platform/session` | Auth check for Site Studio shell |
| GET/POST | `/api/sites` | List / create |
| GET/PATCH/DELETE | `/api/sites/<site_id>` | Read / update / soft-delete |
| POST | `/api/sites/<site_id>/deploy` | Trigger remote deploy |
| GET | `/api/templates` | Template registry |
| GET | `/api/templates/<id>/preview` | Preview asset |
| POST | `/api/templates` | Clone/register template |

---

## Ops (login + `VEERCANVAS_OPS`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/ops/session` | Auth check for ops shell |
| GET | `/api/observability` | Aggregated metrics, visits, inbox |

`GET /api/observability` totals include likes, comments, messages, visitors, active tokens, **visits**, unique IPs, anon/authed/admin visit counts; plus `visits[]`, `topPaths`, `topReferrers`, `browsers`, `devices`.

---

## Inbox (login; cross-site hide/read when ops)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/inbox` | Site-local messages (+ comments context) |
| POST | `/api/inbox/contact/<msg_id>/read` | Mark contact read (`siteId` in body for ops) |
| POST | `/api/inbox/comments/hide` | Hide comment (`siteId`, `slug`, `id`) |

---

## Public engagement

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/public/engagement` | All project summaries |
| GET | `/api/public/engagement/<slug>` | One project |
| POST | `/api/public/engagement/<slug>/vote` | like/dislike |
| POST | `/api/public/engagement/<slug>/comments` | Add comment |
| POST | `/api/public/contact` | Contact form |

---

## Public access & visits

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/public/access/status` | Token/session auth state; optional `slug` → `requireAuth` |
| POST | `/api/public/access/token` | Issue/renew visitor token (name + email) |
| POST | `/api/public/access/gate` | Authorize gated Learn More / project view |
| POST | `/api/public/visit` | Record page visit (anon or authed) |

### Visit payload (high level)

Client may send: `visitorId`, `sessionId`, `path`, `page`, `slug`, `title`, `referrer`, `userAgent`, `language`, `timezone`, `screenW`/`screenH`, `utm` / UTM fields, optional `token`.

Server stores (among others): `at`, `ip`, `authMode` (`anonymous` \| `visitor` \| `admin`), browser/OS/device, referrer host. Rows live in `visitor-access.json` → `visits[]` (capped).

TTL for visitor tokens: `VEERCANVAS_VISITOR_TOKEN_TTL` (default `3600`).

---

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md) · [ADMIN_MANUAL.md](ADMIN_MANUAL.md) · [admin/README.md](../admin/README.md)
