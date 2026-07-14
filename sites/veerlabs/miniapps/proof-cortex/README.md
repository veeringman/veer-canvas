# proof-cortex

A STARK-based zero-knowledge proving engine that converts FortressDigital policy decisions into verifiable proofs anchored on FlowCortex for provably compliant stablecoin settlement.

## Status

✅ **Working HTTP server with real Winterfell STARK prover and PolicyAir algebraic constraints.**

- Axum HTTP server on port `8841` (`POST /api/v1/prove`, `GET /health`)
- PolicyAir STARK circuit: 13-column execution trace with 12 degree-2 algebraic constraints
- Range-check gadgets via bit decomposition (risk < threshold, auth >= min, behavior >= min)
- Equality constraints (device_ok == 1, hash_match == 1)
- Guard row + shifted product for completeness
- Winterfell 0.8 prover/verifier with full proof generation and verification

## Stack

Rust-first modular workspace:

- `proofcortex-service` — HTTP server (axum) + pipeline orchestration entrypoint
- `proofcortex-config` — environment configuration
- `proofcortex-domain` — shared models/contracts
- `proofcortex-policy` — policy evaluation layer
- `proofcortex-trace` — execution trace builder (MvpTraceBuilder)
- `proofcortex-prover` — STARK prover (PolicyAir + PolicyProver, Winterfell 0.8)
- `proofcortex-binding` — commitment binding validation
- `proofcortex-flowcortex-client` — FlowCortex L1 API integration (HTTP)
- `proofcortex-pipeline` — end-to-end orchestration

## HTTP API

### Health Check
```
GET /health
```
Returns `{"status":"ok"}`.

### Generate Proof
```
POST /api/v1/prove
Content-Type: application/json

{
  "policy_id": "treasury_settlement_v1",
  "commitment_hash": "abc123...",
  "witness": {
    "risk_score": 42,
    "auth_strength": 3,
    "device_trust": 1,
    "behavior_score": 80,
    "amount_bucket": 2
  },
  "public_inputs": {
    "policy_id": "treasury_settlement_v1",
    "txn_amount_bucket": "HIGH"
  }
}
```

Returns proof hash, proof data (hex-encoded STARK proof), and verification metadata.

## Build & Run

1. Install Rust toolchain:
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source "$HOME/.cargo/env"
   ```

2. Copy environment template:
   ```bash
   cp .env.example .env
   ```

3. Configure `.env`:
   ```dotenv
   PC_BIND_ADDR=0.0.0.0:8841
   PC_FLOWCORTEX_ENDPOINT=http://192.168.29.78:3000
   PC_PROVER_BACKEND=real       # real = Winterfell STARK, mock = hash-only stub
   PC_FLOWCORTEX_CAPSULE_VERSION=verifier_v1
   ```

4. Build and run:
   ```bash
   cargo run -p proofcortex-service
   ```

5. Verify:
   ```bash
   curl http://192.168.29.78:8841/health
   # → {"status":"ok"}
   ```

## Testing

```bash
# All workspace tests (31 tests)
cargo test-all

# Check all crates
cargo check-all

# Lint
cargo lint

# Format check
cargo fmt-check
```

Benchmark harness:
```bash
cargo run -p proofcortex-service --bin benchmark
```
Results: [docs/BENCHMARK_RESULTS.md](docs/BENCHMARK_RESULTS.md)

## Integration

FortressDigital calls ProofCortex via `POST /api/v1/prove` when `PROOF_MODE=http`:
1. FortressDigital builds a `ProofRequest` from settlement context
2. ProofCortex runs the PolicyAir STARK pipeline (trace → prove → verify)
3. Returns proof_hash + proof_data to FortressDigital
4. FortressDigital anchors the proof on FlowCortex via `/api/anchor_commitment`

## Documentation

- [docs/PROOFCORTEX_SPEC.md](docs/PROOFCORTEX_SPEC.md) — project specification
- [docs/FLOWCORTEX_INTEGRATION_GUIDE.md](docs/FLOWCORTEX_INTEGRATION_GUIDE.md) — FlowCortex API integration
- [docs/IMPLEMENTATION_CHECKLIST.md](docs/IMPLEMENTATION_CHECKLIST.md) — implementation checklist
- [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md) — demo runbook
- [docs/DEMO_INTEGRATION_GUIDES.md](docs/DEMO_INTEGRATION_GUIDES.md) — cross-team demo guides
- [scripts/demo_operator.sh](scripts/demo_operator.sh) — demo operator script
- [TODO.md](TODO.md) — living build tracker
