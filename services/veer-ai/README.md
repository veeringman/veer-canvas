# Veer AI

Native Rust AI platform sidecar for VeerCanvas sites.

## v1 — content moderation

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness |
| `POST` | `/v1/moderate` | Score text (and optional image URL) for hate / obscenity / harassment / spam |

**Response `action`:** `allow` | `flag` | `block`

Engine today: deterministic lexicon + scoring (`veer-ai-rules`). The HTTP contract is stable so a model backend can replace scoring later.

## Run locally

```bash
cd services/veer-ai
cargo run --release
# listens on 127.0.0.1:8095
```

```bash
curl -s localhost:8095/v1/moderate -H 'content-type: application/json' \
  -d '{"text":"Good morning Mandi","site_id":"cityofmandi"}'
```

## City of Mandi wiring

Flask Mandi Adda reads:

| Env | Default | Meaning |
|-----|---------|---------|
| `VEER_AI_URL` | `http://127.0.0.1:8095` | Sidecar base URL |
| `VEER_AI_MODE` | `flag` | `off` · `flag` (hold as hidden) · `block` (reject) |
| `VEER_AI_TIMEOUT_MS` | `280` | HTTP timeout |

Set in `data/ai.env` on the site (or systemd `Environment=`).

## Systemd

See [`deploy/systemd/veer-ai.service`](../../deploy/systemd/veer-ai.service).
