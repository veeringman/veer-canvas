# Veer AI

Native Rust AI platform sidecar for VeerCanvas sites.

## v0.79 — moderation + finer RAG (EC2-safe)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness + engine meta |
| `POST` | `/v1/moderate` | Score text for hate / obscenity / harassment / spam |
| `POST` | `/v1/rag/retrieve` | Rank colony knowledge chunks |

**Retrieval stack (no ONNX/Torch — fits ~1GB EC2):**

1. Okapi BM25 (**b=0.78**) + title boost + synonym expansion  
2. Soft score gate (drop weak BM25 tails)  
3. **Hashed n-gram mini-embeddings** (384-d signed hashing trick over unigrams/bigrams/char-trigrams) fused with BM25 via RRF  
4. MMR for diversity  

Corpus building stays in the site app (SQLite / Info Centre). The sidecar only ranks.

**Moderation `action`:** `allow` | `flag` | `block`

## Deploy binary (never compile on EC2)

The production host must not run `cargo` / rustup. On a laptop or CI (Linux x86_64):

```bash
cd services/veer-ai
cargo build --release
mkdir -p dist
cp target/release/veer-ai dist/veer-ai
```

`remote-deploy.sh` rsyncs `dist/` when present; `site-deploy.sh` installs it to `data/bin/veer-ai` or keeps the existing binary.

## Run locally

```bash
cd services/veer-ai
cargo run --release
# listens on 127.0.0.1:8095
```

```bash
curl -s localhost:8095/v1/rag/retrieve -H 'content-type: application/json' \
  -d '{"query":"outstanding dues","k":2,"docs":[{"id":"1","title":"My dues","text":"Plot A-12 owes Rs 4500 maintenance","source":"dues","boost":2}]}'
```

## Env (site `data/ai.env`)

| Env | Default | Meaning |
|-----|---------|---------|
| `VEER_AI_URL` | `http://127.0.0.1:8095` | Sidecar base URL |
| `VEER_AI_MODE` | `flag` | Mandi Adda moderation: `off` · `flag` · `block` |
| `VEER_AI_TIMEOUT_MS` | `280` | Moderation HTTP timeout |
| `VEER_AI_RAG` | `1` | Sanyard assistant: use Rust RAG (`0` to force Python fallback) |
| `VEER_AI_RAG_TIMEOUT_MS` | `1200` | RAG HTTP timeout |
| `VEER_AI_EMBED` | `1` | Optional OpenAI embedding hybrid on top (needs `RWA_AI_API_KEY`) |

## Systemd

See [`deploy/systemd/veer-ai.service`](../../deploy/systemd/veer-ai.service). Built for `cityofmandi` and `hbcsanyard` deploys (shared bind `127.0.0.1:8095`).
