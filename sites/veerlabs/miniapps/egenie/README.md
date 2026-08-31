<p align="left">
  <img src="brand/png/egenie-lockup-stacked.png" alt="eGenie" width="220" />
</p>
### The Intelligence Engine by VeerLabs

**eGenie** is a modular, model-agnostic AI engine that provides the common intelligence, reasoning, retrieval, agent, vision, speech, and decision capabilities consumed by your platforms.

It is designed to be the **intelligence infrastructure layer** behind products such as **WiseEars**, **QuantumArc**, **QuantumPay**, and future VeerLabs platforms — not another standalone chatbot.

> **Your Wish. My Command.**

---

## Vision

Modern applications increasingly depend on AI, but every product should not have to independently solve:

* Model routing and inference abstraction
* Reasoning, planning, and agent workflows
* RAG, embeddings, and knowledge graphs
* Conversation and semantic memory
* Vision, speech, and multimodal processing
* Safety, policy, and output validation
* Edge and local inference orchestration

**eGenie provides this intelligence as a reusable platform.**

Applications interact with eGenie through the SDK and API while eGenie handles orchestration across LLMs, SLMs, classical ML, rules, tools, and external providers.

---

## Core promise

**Understand → Think → Act**

| Phase | Meaning |
| --- | --- |
| **Understand** | Parse intent from text, speech, vision, or structured input |
| **Think** | Retrieve context, plan, reason, route to the right models and tools |
| **Act** | Execute workflows, emit structured outputs, verify results |

eGenie is **not synonymous with an LLM**. LLMs are one component; eGenie is the intelligence orchestration layer.

---

## Positioning

| Layer | Role |
| --- | --- |
| **QuantumArc** | Application infrastructure platform |
| **eGenie** | Intelligence infrastructure platform |

```text
                    ┌───────────────────────────┐
                    │       YOUR PRODUCTS       │
                    │ WiseEars │ QuantumArc ... │
                    └─────────────┬─────────────┘
                                  │
                         eGenie SDK / API
                                  │
              ┌───────────────────▼───────────────────┐
              │                 eGenie                 │
              │         AI / Intelligence Core        │
              └───────────────────────────────────────┘
```

---

## Platform pillars

| Pillar | Purpose |
| --- | --- |
| **eGenie Core** | Unified intelligence runtime and execution engine |
| **eGenie Brain** | Model abstraction, routing, inference, and reasoning |
| **eGenie Memory** | Conversation, semantic, episodic memory and knowledge stores |
| **eGenie Knowledge** | RAG, ingestion, embeddings, vector search, knowledge graphs |
| **eGenie Agent** | Planning, tool use, workflows, autonomous task execution |
| **eGenie Sense** | Vision, audio, STT, TTS, multimodal processing |
| **eGenie Decision** | Rules + ML + LLM reasoning for scoring, prediction, risk |
| **eGenie Guard** | Safety, permissions, policy, validation, guardrails |
| **eGenie Mesh** | Distributed / edge inference between eGenie instances |
| **eGenie SDK** | Rust core + APIs/SDKs for consuming applications |

---

## Rust workspace

```text
crates/
├── egenie-core/    # IDs, wishes, messages, phases (no I/O)
├── egenie-guard/   # Policy enforcement
├── egenie-brain/   # Model routing abstraction
└── egenie-sdk/     # Public Engine API
```

```bash
cargo test
```

The v0 SDK exposes `Engine::fulfill`, which runs a wish through all three phases with guarded policy checks and pluggable model providers.

---

## First integration: WiseEars

**WiseEars** is the first reference integration. Capture-time ASR and extraction stay in `wiseears-intelligence`; eGenie orchestrates interactive wishes — summaries, memory queries, and studio commands.

See [docs/integrations/wiseears.md](docs/integrations/wiseears.md).

---

## Documentation

| Document | Description |
| --- | --- |
| [Vision](docs/VISION.md) | Product direction and design principles |
| [Architecture](docs/ARCHITECTURE.md) | Platform architecture and module map |
| [SDK v0](docs/SDK.md) | Public SDK contract and request lifecycle |
| [WiseEars integration](docs/integrations/wiseears.md) | First reference integration plan |
| [Brand](brand/README.md) | Logo, colors, typography, assets |
| [ADR 001](docs/adr/001-rust-kernel.md) | Rust-native kernel decision |
| [ADR 002](docs/adr/002-wiseears-first-integration.md) | WiseEars as first integration target |

---

## Brand

| Element | Value |
| --- | --- |
| Name | eGenie |
| Tagline | Your Wish. My Command. |
| Genie Gold | `#FFB020` |
| Electric Blue | `#00B0FF` |
| Deep Indigo | `#0D1B3D` |

---

## Status

Early foundation phase:

- Brand identity locked with split assets
- Rust kernel scaffolded (`egenie-core`, `egenie-guard`, `egenie-brain`, `egenie-sdk`)
- WiseEars chosen as first integration target
- Next: wire `egenie-sdk` into WiseEars with episode summary wish

---

<p align="center">
  <sub>© VeerLabs · eGenie — The Intelligence Engine</sub>
</p>
