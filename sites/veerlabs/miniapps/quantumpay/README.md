<p align="center">
  <img src="assets/quantumpay.png" alt="QuantumPay — the intelligent payment orchestration layer" width="720">
</p>

QuantumPay is a standalone, developer-centric platform for integrating, routing, monitoring, reconciling, and managing payments across multiple regulated providers — through **one API**.

> **Orchestrate payments. Don't become the payment rail.**

QuantumPay does not accept, hold, pool, escrow, or settle customer funds. Execution and settlement stay with regulated payment providers and financial institutions.

```text
Merchant / platform
        │  one API, one webhook contract, one ledger view
        ▼
   QuantumPay
        │  adapters · policy routing · failover · reconciliation
        ├──────────► Provider A  ──► UPI / cards / net banking / …
        ├──────────► Provider B
        └──────────► Provider C
```

## Documentation

The architecture is specified in [`docs/`](docs/README.md). Start here:

| | |
| --- | --- |
| [Vision](docs/vision.md) | Why this product exists |
| [Architecture](docs/architecture.md) | Modular monolith, hexagon, runtime |
| [Payment lifecycle](docs/payment-lifecycle.md) | Intent/attempt state machines, including `UNKNOWN` |
| [Security](docs/security.md) | Controls that are part of the runtime |
| [Compliance](docs/compliance.md) | The regulatory fence |
| [Legal drafts](docs/legal/README.md) | Society dues terms skeletons (not legal advice) |
| [UPI / PhonePe / Razorpay](docs/upi-phonepe-razorpay.md) | Who does UPI vs settlement; TPAPs vs merchant |
| [Society Razorpay KYC](docs/legal/razorpay-society-kyc.md) | Prep list; society is merchant of record |
| [Test deploy (.78)](docs/deploy-test.md) | LAN test environment |
| [Local Postgres](docs/local.md) | Docker Compose on a laptop |
| [Roadmap](docs/roadmap.md) | What is built when |
| [ADRs](docs/adr/README.md) | Why decisions were made |

## Design in one page

1. **Provider agnostic** — adapters behind a port; the core never speaks a PSP dialect.
2. **Money-neutral** — orchestration facts, not custody of funds.
3. **Deterministic** — append-only events and ledger; status is a projection.
4. **Idempotent** — retries must not create money movement.
5. **Event-driven** — HTTP responses are not the final financial state.
6. **Observable** — a payment is reconstructable end to end.
7. **Secure by default** — fail closed on auth, KMS, and webhook verify.
8. **Independently complete** — no sibling platform required to ship a payment.

## What QuantumPay is not (Phase 1)

Not a payment aggregator that handles funds, not an acquiring bank, not a UPI PSP, not an escrow, not a rail.

Production use in India requires independent legal, regulatory, contractual, security, banking, and provider review.

## Status

**Architecture and a running test API.** Implementation is a Cargo workspace. Test host: [`docs/deploy-test.md`](docs/deploy-test.md) (`192.168.29.78:18980`). No production payment traffic.

Planned stack: Rust, Tokio, Axum, PostgreSQL, Redis, OpenTelemetry, Kubernetes.

## License

License to be determined.
