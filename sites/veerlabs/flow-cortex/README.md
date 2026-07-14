<img src="IMG_1250.jpeg" width=150 />

**FlowCortex** is a payment-centric, ordering-less blockchain designed for extreme throughput, stateless verification, and parallel execution.

At its core, FlowCortex replaces global transaction ordering with **proof-driven state validation**, enabling payments to scale with actual contention rather than network size.

The system is implemented in **Rust**, optimized for **CPU, GPU, and future ASIC acceleration**, and built to be **post-quantum ready**.

---

## Project Status

✅ **Working L1 node with full REST + gRPC API, Explorer UI, WASM capsule runtime, and end-to-end demo integration.**

All 16 development phases are complete:
- Phases 1–3: Core ledger, accounts, balances, blocks, transactions, gRPC handlers
- Phase 4–6: Commitment anchoring, proof verification, event system
- Phase 7–9: FloweR stablecoin (1 FLOWER = 1 INR), token management, pool snapshots
- Phase 10–12: Capsule runtime (native + WASM via wasmtime), settlement routes, bank admin API
- Phase 13: Demo-specific features, end-to-end scenario support
- Phase 14–16: Testing, documentation, demo readiness

See [DEMO_TODO_LIST.md](DEMO_TODO_LIST.md) for the complete phase tracker.

---

## Vision

Traditional blockchains are constrained by:
- Global transaction ordering
- Sequential execution
- Full state replication
- Verification cost tied to total state size

FlowCortex takes a different path:

> **Transactions do not compete for position in a block.
They compete only for the state they touch.**

This makes FlowCortex naturally suited for:
- High-volume payments
- Real-time settlement
- Stateless validators
- Hardware-accelerated verification

---

## Core Design Principles

- **Ordering-less execution** — No global transaction sequence unless state conflicts require it.
- **Stateless verification** — Validators do not store full state; transactions carry their own proofs.
- **Payment-first architecture** — Optimized for balance transfers, batching, and settlement.
- **Parallelism by default** — Proof verification and execution scale across CPU cores, GPUs, and ASICs.
- **Post-quantum oriented** — Commitment schemes designed to evolve beyond classical cryptography.

---

## Repository Structure

```
flow-cortex/
├── flowcortex-l1/       # L1 blockchain node (Rust/axum, gRPC/tonic)
│   ├── src/
│   │   ├── main.rs      # Binary entrypoint (REST + gRPC servers)
│   │   ├── rpc.rs       # 29 REST API routes (axum)
│   │   ├── grpc.rs      # 6 gRPC services (tonic)
│   │   ├── ledger.rs    # In-memory ledger (accounts, tokens, blocks, commitments, proofs)
│   │   ├── node.rs      # Node state, block production, transaction application
│   │   ├── demo.rs      # Demo settlement scenarios (8-step flow)
│   │   ├── wasm_capsule.rs  # WASM capsule runtime (wasmtime)
│   │   ├── qct.rs       # Quantum Cascade Tree stubs
│   │   └── ...
│   ├── proto/           # Protobuf definitions (6 services)
│   └── tests/           # E2E integration tests
├── explorer/            # Web-based Explorer UI (Rust/axum/Askama)
│   ├── src/             # Backend routes + handlers
│   ├── templates/       # HTML/JS UI (11 tabs)
│   └── static/          # CSS/JS assets
├── flowcortex-l0/       # QCT proof-of-concept library
├── docs/                # Project documentation
│   ├── CAPSULE_DEVELOPER_MANUAL.md
│   ├── API_SPECIFICATIONS.md
│   ├── INTEGRATION_GUIDE_*.md
│   └── ...
├── scripts/             # Build, run, E2E test scripts
└── examples/            # Example configurations
```

---

## Quick Start

### Start the L1 node and Explorer

```bash
# Build and start both services
scripts/run_servers.sh

# L1 node: http://192.168.29.78:3000
# Explorer: http://192.168.29.78:4000
```

Or start individually:

```bash
# L1 node only
cargo run --manifest-path flowcortex-l1/Cargo.toml

# Explorer only (requires L1 running)
cargo run --manifest-path explorer/Cargo.toml
```

### Verify it works

```bash
curl http://192.168.29.78:3000/pool
# → {"block_height":0,"tx_count":0,...}

curl http://192.168.29.78:3000/tokens
# → [{"symbol":"FLW","name":"FloweR Stablecoin",...}]
```

---

## REST API Routes (L1 Node — port 3000)

### Core Ledger
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/account` | Create account |
| `POST` | `/mint` | Mint tokens to account |
| `POST` | `/transfer` | Transfer tokens between accounts |
| `GET` | `/balance/{account}/{token}` | Query balance |
| `POST` | `/token/create` | Create new token type |
| `GET` | `/tokens` | List all tokens |
| `GET` | `/token/{symbol}` | Get token metadata |
| `GET` | `/pool` | Node state snapshot |
| `POST` | `/block` | Produce a new block |
| `GET` | `/blocks` | List all blocks |
| `GET` | `/snapshot` | Full ledger snapshot |
| `POST` | `/tx` | Submit raw transaction |

### Anchoring & Compliance
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/anchors` | List commitment anchors |
| `GET` | `/anchor/{id}` | Get anchor by ID |
| `POST` | `/api/anchor_commitment` | Anchor a commitment hash |
| `POST` | `/api/verify_proof` | Verify a STARK proof |
| `GET` | `/api/commitment/{hash}` | Query commitment by hash |
| `GET` | `/api/proof_status/{hash}` | Query proof status |
| `GET` | `/api/events` | Compliance event stream |
| `GET` | `/api/stats` | Dashboard statistics |

### Capsules (Native + WASM)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/capsule` | Upload/register capsule |
| `GET` | `/capsule` | List deployed capsules |
| `POST` | `/capsule/{id}/invoke` | Invoke native capsule |
| `POST` | `/capsule/{id}/invoke_wasm` | Invoke WASM capsule |

### Settlement (Bank Operations)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/settlement/mint` | Settlement mint (approved banks) |
| `POST` | `/settlement/redeem` | Settlement redeem/burn |
| `POST` | `/settlement/transfer` | Inter-bank settlement transfer |
| `POST` | `/bank/approve` | Register a settlement bank |
| `POST` | `/bank/daily_limit` | Set bank daily mint limit |

### gRPC Services (port 50051)

Six gRPC services defined in `flowcortex-l1/proto/`:
- `LedgerService` — account/balance/transfer operations
- `BlockProducer` — block creation and queries
- `TransactionPool` — transaction submission
- `TokenService` — token management
- `CommitmentAnchor` — commitment anchoring
- `ProofVerifier` — STARK proof verification

---

## Explorer UI (port 4000)

The Explorer is a web-based dashboard with **11 tabs**:

1. **Dashboard** — Node stats, block height, token counts
2. **Blocks** — Block list with height, hash, transaction count
3. **Transactions** — Transaction log with filtering
4. **Accounts** — Account browser with balance display
5. **Tokens** — Token registry (FLW FloweR stablecoin, etc.)
6. **Capsules** — Capsule IDE with WAT editor, example gallery, wabt.js compilation, invoke panel
7. **Commitments** — Anchor commitment form, query by hash, stats
8. **Proofs** — Verify proof form, status badges, result display
9. **Events** — Compliance event stream with type filters
10. **Settlement** — Settlement operation forms
11. **Config** — API configuration panel

---

## WASM Capsule Runtime

FlowCortex supports sandboxed WASM capsules via wasmtime. Guest modules can call host functions:

| Host Function | Description |
|---------------|-------------|
| `host_mint` | Mint tokens to an account |
| `host_transfer` | Transfer tokens between accounts |
| `host_burn` | Burn tokens from an account |
| `host_balance` | Query account balance |
| `host_log` | Emit a log entry |
| `host_output` | Set capsule output |

Ledger operations are accumulated during execution and applied atomically on success.

See [docs/CAPSULE_DEVELOPER_MANUAL.md](docs/CAPSULE_DEVELOPER_MANUAL.md) for the full developer guide.

---

## Integration Points

FlowCortex L1 integrates with the full demo platform:

| Service | Integration | Details |
|---------|------------|---------|
| **FortressDigital** | `POST /api/anchor_commitment` | Anchors settlement authorization commitments |
| **ProofCortex** | `POST /api/verify_proof` | Verifies STARK proofs against anchored commitments |
| **KeyCortex** | `GET /balance`, `POST /transfer` | Real wallet balance and transaction submission |
| **TreasurySettlement** | Settlement + bank routes | Mint/redeem/transfer for approved banks |
| **Explorer** | All read endpoints | Visualizes ledger, blocks, tokens, compliance data |

See integration guides in `docs/`:
- [INTEGRATION_GUIDE_FORTRESSDIGITAL.md](docs/INTEGRATION_GUIDE_FORTRESSDIGITAL.md)
- [INTEGRATION_GUIDE_PROOFCORTEX.md](docs/INTEGRATION_GUIDE_PROOFCORTEX.md)
- [INTEGRATION_GUIDE_TREASURY.md](docs/INTEGRATION_GUIDE_TREASURY.md)
- [INTEGRATION_GUIDE_WALLET.md](docs/INTEGRATION_GUIDE_WALLET.md)

---

## Testing

```bash
# L1 unit + integration tests
cargo test --manifest-path flowcortex-l1/Cargo.toml

# Explorer tests
cargo test --manifest-path explorer/Cargo.toml

# Full E2E (builds, starts servers, runs curl checks)
scripts/e2e/run_l1_explorer_e2e.sh
```

### Running the servers

The L1 node and explorer binaries read `BIND_ADDR` to determine the listen address. By default they bind to `0.0.0.0:3000` and `0.0.0.0:4000` respectively.

```sh
# Start both services, listening on all interfaces
scripts/run_servers.sh

# Custom addresses
scripts/run_servers.sh 0.0.0.0:3001 127.0.0.1:4005
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [DEMO_QUICK_START.md](DEMO_QUICK_START.md) | Hands-on curl-based demo walkthrough |
| [DEMO_NARRATIVE.md](DEMO_NARRATIVE.md) | 8-step settlement flow narrative |
| [DEMO_CONTEXT.md](DEMO_CONTEXT.md) | Demo architecture and business context |
| [DEMO_EXPECTATIONS.md](DEMO_EXPECTATIONS.md) | Engineering contract and expectations |
| [docs/API_SPECIFICATIONS.md](docs/API_SPECIFICATIONS.md) | Full API specification |
| [docs/CAPSULE_DEVELOPER_MANUAL.md](docs/CAPSULE_DEVELOPER_MANUAL.md) | WASM capsule development guide |
| [docs/OPERATIONS_GUIDE.md](docs/OPERATIONS_GUIDE.md) | Deployment and operations |
| [docs/DEVELOPER_ONBOARDING.md](docs/DEVELOPER_ONBOARDING.md) | New developer setup guide |
