<p align="left">
	<img src="fortress_logo.jpeg" alt="FortressDigital" width="220" />
</p>

# FortressDigital Control Plane (MVP)

FortressDigital is the Zero Trust + Zero Proof control plane that authorizes, risk-scores, cryptographically proves, and anchors every stablecoin treasury settlement on FlowCortex.

This repository implements an **integration-first MVP** where Treasury Settlement Platform and FlowCortex/ProofCortex remain separate systems.

## Purpose in Demo Context

FortressDigital sits between:
- Enterprise Treasury Apps (business intent)
- Wallet/Key custody execution
- FlowCortex transaction anchoring
- ProofCortex proof verification/anchoring

For every settlement request, it enforces:
- Zero Trust authentication/context checks
- Policy decision (`ALLOW` / `CHALLENGE` / `BLOCK`)
- Real-time risk scoring
- Zero Proof commitment generation (stub hash for MVP)
- Anchor transaction hash generation (FlowCortex integration placeholder)
- Immutable audit evidence record

## Platform Boundaries (Important)

This codebase covers **FortressDigital integration layer only**.

Not implemented here (external platforms):
- Treasury Settlement UI platform
- FlowCortex chain/node platform
- ProofCortex verifier platform

## MVP Architecture (Implemented)

Modular Rust layout designed for step-by-step replacement:
- `src/api.rs`: HTTP routes and request/response boundary only
- `src/service.rs`: settlement orchestration use-case
- `src/domain.rs`: shared domain models and outcomes
- `src/identity.rs`: identity/context extraction adapter
- `src/risk.rs`: risk scoring trait + rule-based scorer
- `src/policy.rs`: policy decision logic
- `src/integrations.rs`: pluggable traits + HTTP adapters (ProofCortex, FlowCortex, KeyCortex)
- `src/intents.rs`: maker-checker intent store (sled-backed)
- `src/audit.rs`: append-only evidence ledger writer
- `src/velocity.rs`: per-user velocity tracking + velocity-enriched scorer (feature: `velocity`)
- `src/onnx.rs`: ONNX ML model inference scorer (feature: `ai-risk`)
- `src/llm.rs`: Ollama LLM audit explainer (feature: `llm-explain`)
- `src/util.rs`: shared utilities
- `src/main.rs`: wiring/composition root

### Extensibility Contracts

`src/integrations.rs` exposes trait-based contracts:
- `ProofVerifier` — ✅ `HttpProofCortexClient` (calls ProofCortex `/api/v1/prove`)
- `CustodySigner` — ✅ `HttpCustodySignerClient` (calls KeyCortex `/wallet/sign`)
- `FlowAnchorClient` — ✅ `HttpFlowAnchorClient` (calls FlowCortex `/api/anchor_commitment`)

Mock implementations are retained for testing (`PROOF_MODE=mock`, `CUSTODY_MODE=mock`, `FLOW_ANCHOR_MODE=mock`).

## API Contract (MVP)

### Health
`GET /health`

### Settlement Decision + Execution
`POST /v1/settlements`

### Maker-Checker Intent Creation
`POST /v1/settlements/intents`

Creates a settlement intent from maker input and stores it in `pending_approval` state when not blocked.

### Maker-Checker Approval
`POST /v1/settlements/intents/{intent_id}/approve`

Completes settlement execution only when:
- approver identity is valid
- `approver_role=approver`
- maker and checker are different users

### Console Settlement Feed
`GET /v1/console/settlements?limit=<n>&cursor=<offset>&sort=<asc|desc>`

Returns recent settlement/audit records for dashboard tables.
Response includes `next_cursor` for infinite scroll pagination.

### Console Audit Search
`GET /v1/console/audit/search?user_id=<id>&wallet=<addr>&tx_hash=<hash>&decision=<ALLOW|CHALLENGE|BLOCK>&limit=<n>&cursor=<offset>&sort=<asc|desc>`

Returns filtered audit evidence records for console search screens.

### Console Live Events (SSE stub)
`GET /v1/console/events`

Streams heartbeat SSE events as a live feed integration contract for the SPA.

Headers:
- `Authorization: Bearer <token>`
- `x-device-id` (optional)
- `x-source-ip` (optional)
- `x-geo-region` (optional, `corp_hq` is low-risk baseline)

Body:
```json
{
	"amount": 12000.0,
	"currency": "FLOWER",
	"counterparty_wallet": "wallet_abc123",
	"purpose_code": "vendor_payout",
	"user_id": "alice",
	"user_role": "treasury_ops"
}
```

Response includes:
- `decision`
- `risk_score`
- `anomaly_flags`
- `policy_trace`
- `commitment_hash` (when `ALLOW`)
- `proof_hash` (when `ALLOW`)
- `tx_hash` (when `ALLOW`)
- `anchor_block_height` (when `ALLOW`)
- `anchor_timestamp` (when `ALLOW`)
- `anchor_status`

If authentication context is insufficient for the operation, API returns:
- `403` with `error=insufficient_authentication`
- `required_acr`, `required_amr`, `step_up_url`, and `step_up_methods`

## Functionality Matrix

Implemented behaviors:
- Identity enforcement: request denied when token is missing/invalid.
- Policy enforcement: deterministic `ALLOW` / `CHALLENGE` / `BLOCK` decisions.
- Risk scoring: anomaly-driven score + flags are included in response.
- Proof flow: proof commitment generated only on `ALLOW`.
- Anchor flow: tx hash generated only on `ALLOW`.
- Audit evidence: every settlement attempt persisted as JSONL evidence.
- Backend outage safety: integration failures return `500` and still write audit evidence with failure trace.

Expected settlement outcomes:
- `ALLOW` => proof hash + tx hash + `anchor_status=anchored`
- `CHALLENGE` => no proof hash + no tx hash + `anchor_status=not_anchored`
- `BLOCK` => no proof hash + no tx hash + `anchor_status=not_anchored`

Maker-checker outcomes:
- intent create (`/intents`) returns `pending_approval` unless blocked
- approval endpoint returns final settlement receipt on success
- pending intents are persisted in `sled` and survive service restarts
- approval endpoint returns:
	- `403` for role or separation-of-duties violations
	- `404` for unknown intent
	- `409` for invalid intent state

## Policy + Risk Defaults (MVP)

Policy:
- Currency must be `FLOWER`
- `treasury_ops` maker challenge over `100000`
- Risk `>= 85` => `BLOCK`
- Risk `>= 60` => `CHALLENGE`

Risk signals:
- High value (`amount > 50000`) => `high_value`
- New wallet prefix (`new_`) => `new_wallet`
- Non-HQ region (`x-geo-region != corp_hq`) => `geo_mismatch`

## Run

```bash
cargo run
```

Server defaults:
- `PORT=8821`
- `FLOWCORTEX_HTTP_ENDPOINT=http://192.168.29.78:3000`
- `FLOWCORTEX_GRPC_ENDPOINT=http://192.168.29.78:50051`
- `PROOFCORTEX_ENDPOINT=http://192.168.29.78:8841`
- `KEYCORTEX_ENDPOINT=http://192.168.29.78:8811`
- `INTENT_DB_PATH=data/intents_db`

Integration mode toggles:
- `FLOW_ANCHOR_MODE=http` (`mock`, `http`, or `tonic` — default `http`)
- `PROOF_MODE=http` (`mock` or `http` — default `http`)
- `CUSTODY_MODE=http` (`mock` or `http` — default `http`)
- `RISK_MODE=rules` (`rules`, `velocity`, or `onnx` — default `rules`)
- `FLOWCORTEX_TIMEOUT_MS=1200` (used in tonic mode)
- `FLOWCORTEX_MAX_RETRIES=2` (used in tonic mode)
- `FLOWCORTEX_RETRY_BACKOFF_MS=150` (used in tonic mode)

Identity mode:
- `IDENTITY_MODE=demo` (local mode, expects `Authorization: Bearer demo-<user_id>`)
- `IDENTITY_MODE=oidc` (OIDC JWT validation)

Demo auth-context override headers (optional):
- `x-auth-acr` (default `urn:authbuddy:silver`)
- `x-auth-amr` (default `password,totp`)
- `x-session-id` (optional)
- `x-token-iat` (optional unix seconds)

OIDC mode settings:
- `OIDC_ISSUER` (required in OIDC mode)
- `OIDC_AUDIENCE` (required in OIDC mode)
- `OIDC_JWKS_URL` (optional; if unset, discovered via issuer metadata)
- `OIDC_JWKS_CACHE_TTL_SECS` (optional, default `300`)

Step-up settings:
- `AUTHBUDDY_AUTHORIZE_URL` (optional; default `https://authbuddy.example.com/oauth2/authorize`)

AI/ML settings (feature-flagged):
- `VELOCITY_DB_PATH=data/velocity_db` (requires `velocity` feature)
- `ONNX_MODEL_PATH=models/risk_scorer.onnx` (requires `ai-risk` feature)
- `OLLAMA_URL=http://127.0.0.1:11434` (requires `llm-explain` feature)
- `OLLAMA_MODEL=llama3.2` (requires `llm-explain` feature)

## Quick Test

```bash
curl -sS http://192.168.29.78:8821/health

curl -sS -X POST http://192.168.29.78:8821/v1/settlements \
	-H 'Content-Type: application/json' \
	-H 'Authorization: Bearer demo-alice' \
	-H 'x-device-id: corp-laptop-17' \
	-H 'x-source-ip: 10.10.1.22' \
	-H 'x-geo-region: corp_hq' \
	-d '{
		"amount": 12000,
		"currency": "FLOWER",
		"counterparty_wallet": "wallet_abc123",
		"purpose_code": "vendor_payout",
		"user_id": "alice",
		"user_role": "treasury_ops"
	}'
```

OIDC mode example run:
```bash
IDENTITY_MODE=oidc \
OIDC_ISSUER='https://idp.example.com/realms/treasury' \
OIDC_AUDIENCE='fortressdigital-control-plane' \
cargo run
```

## React Console SPA

Frontend lives in `console-ui/` and consumes the console endpoints.

Run frontend:
```bash
cd console-ui
npm install
npm run dev
```

Frontend environment (optional):
- `VITE_API_BASE_URL` (default `http://192.168.29.78:8821`)

Build frontend:
```bash
cd console-ui
npm run build
```

FlowCortex tonic mode example run:
```bash
FLOW_ANCHOR_MODE=tonic \
FLOWCORTEX_GRPC_ENDPOINT='http://192.168.29.78:50051' \
FLOWCORTEX_TIMEOUT_MS=1200 \
FLOWCORTEX_MAX_RETRIES=2 \
cargo run
```

## Testing

Run all tests:
```bash
cargo test
```

Run only end-to-end settlement tests:
```bash
cargo test --test e2e_settlements
```

Current E2E coverage includes:
- health endpoint availability
- settlement `ALLOW` path
- settlement `CHALLENGE` path
- settlement `BLOCK` path
- unauthorized request handling
- audit evidence write verification
- proof backend failure (`500` + audit trace)
- signer backend failure (`500` + audit trace)
- FlowCortex backend failure (`500` + audit trace)
- maker-checker happy path (intent -> checker approval)
- maker-checker separation-of-duties rejection
- maker-checker role enforcement rejection
- maker-checker missing intent rejection
- intent persistence across simulated service restart (sled)
- console settlements list endpoint
- console audit search endpoint
- console SSE endpoint contract

Maker-checker quick example:
```bash
# 1) Maker creates intent
curl -sS -X POST http://192.168.29.78:8821/v1/settlements/intents \
	-H 'Content-Type: application/json' \
	-H 'Authorization: Bearer demo-alice' \
	-d '{
		"amount": 15000,
		"currency": "FLOWER",
		"counterparty_wallet": "wallet_abc123",
		"purpose_code": "vendor_payout",
		"user_id": "alice",
		"user_role": "treasury_ops"
	}'

# 2) Checker approves (replace <intent_id>)
curl -sS -X POST http://192.168.29.78:8821/v1/settlements/intents/<intent_id>/approve \
	-H 'Content-Type: application/json' \
	-H 'Authorization: Bearer demo-bob' \
	-d '{
		"approver_user_id": "bob",
		"approver_role": "approver"
	}'
```

Console quick examples:
```bash
# Recent settlements for dashboard
curl -sS "http://192.168.29.78:8821/v1/console/settlements?limit=20&sort=desc"

# Next page using cursor from previous response
curl -sS "http://192.168.29.78:8821/v1/console/settlements?limit=20&sort=desc&cursor=20"

# Audit search by user and decision
curl -sS "http://192.168.29.78:8821/v1/console/audit/search?user_id=alice&decision=ALLOW&limit=20&sort=desc"

# Live events stream (SSE)
curl -N -H 'Accept: text/event-stream' http://192.168.29.78:8821/v1/console/events
```

## Step-by-Step Path to Full System

1. ✅ Identity Hardening
	- OIDC JWT validation available via `IDENTITY_MODE=oidc` with issuer/audience validation and JWKS caching.
2. Policy Externalization
	- Keep `PolicyEngine` interface, move rule source to OPA/Rego or policy config store.
3. ✅ Real ProofCortex Adapter
	- `HttpProofCortexClient` calls ProofCortex `POST /api/v1/prove`. Toggle: `PROOF_MODE=mock|http`.
4. ✅ Real KeyCortex Custody Adapter
	- `HttpCustodySignerClient` calls KeyCortex `/wallet/sign`. Toggle: `CUSTODY_MODE=mock|http`.
5. ✅ Real FlowCortex Adapter
	- `HttpFlowAnchorClient` calls FlowCortex REST `POST /api/anchor_commitment`. Toggle: `FLOW_ANCHOR_MODE=mock|http|tonic`.
6. ✅ Maker-Checker Workflow
	- Implemented with intent create + approve endpoints and separation-of-duties checks.
7. ✅ Audit & Replay Expansion
	- Durable `sled` intent store; JSONL evidence ledger; console search/pagination APIs.

## AI/ML Risk Scoring (Feature-Flagged)

FortressDigital includes optional AI-powered risk scoring behind Cargo feature flags:

| Feature | `RISK_MODE` | Description |
|---------|-------------|-------------|
| (default) | `rules` | 3-rule heuristic scorer (high_value, new_wallet, geo_mismatch) |
| `velocity` | `velocity` | Per-user rolling window stats (txn count, amount z-score, diversity, timing) backed by sled |
| `ai-risk` | `onnx` | GradientBoosting ONNX model (93.85% accuracy, 0.97 AUC) with velocity fallback |

LLM endpoints (requires `llm-explain` feature + running Ollama):
- `GET /v1/ai/explain/{settlement_id}` — audit narrative with risk reasoning
- `POST /v1/ai/anomaly-narration` — velocity/anomaly flag narration
- `POST /v1/admin/policy-suggestion` — data-driven policy threshold recommendations
