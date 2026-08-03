<div align="center">

<img src="assets/veer-dharam.png" alt="Veer Dharam" width="230"/>

## The AI Trust Operating System

### Every piece of data has a Dharam. Every AI must honor it.

**AI-Native Data Trust Infrastructure for Privacy, Security, Governance, Compliance, and Responsible AI**

<br/>

[![Status](https://img.shields.io/badge/status-under--development-orange)](https://github.com)
[![Rust](https://img.shields.io/badge/Rust-2024-orange?logo=rust)](https://www.rust-lang.org/)
[![AI Native](https://img.shields.io/badge/AI-Native-6C63FF)](https://github.com)
[![Privacy First](https://img.shields.io/badge/Privacy-First-0088CC)](https://github.com)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

</div>

---

# The Problem

Artificial Intelligence is becoming deeply embedded in how organizations create, process, analyze, and act upon information.

Enterprise data is now flowing through:

- Large Language Models
- AI Agents
- RAG pipelines
- Vector databases
- AI copilots
- Autonomous workflows
- Model training pipelines
- APIs
- SaaS platforms
- Cloud infrastructure

Yet most existing security and privacy systems were designed for a world of:

```text
Files
Databases
Networks
Applications
Users
```

The AI era has introduced an entirely new environment:

```text
Prompts
Context
Embeddings
Models
Agents
Memories
Tools
RAG
Inference
Autonomous Decisions
```

Traditional DLP asks:

> **"Is this data sensitive?"**

Veer Dharam asks a deeper question:

> **"Is this AI allowed to use this data, for this purpose, in this context, under these obligations?"**

---

# The Vision

## AI needs a Trust Layer

Artificial Intelligence should not merely understand information.

It should understand **responsibility**.

Every piece of data has:

- An identity
- An owner
- A purpose
- A sensitivity
- A consent state
- A jurisdiction
- A lifecycle
- A set of obligations
- A level of trust
- A permitted way of being used

Veer Dharam turns these properties into a machine-readable and enforceable identity.

We call this:

# Data Dharam™

---

# What is Dharam?

**Dharam** represents the intrinsic nature, purpose, responsibility, and rightful conduct associated with something.

For data, its Dharam describes:

```text
Who owns it?

Why does it exist?

Why was it collected?

Who may access it?

Which AI systems may process it?

For what purpose?

Where may it be processed?

Which regulations apply?

How long may it exist?

What transformations are permitted?

What happens when consent is revoked?
```

Veer Dharam makes these obligations understandable to machines.

> **Data should not merely be protected. Its purpose should be preserved.**

---

# Data Dharam DNA™

The foundation of Veer Dharam is **Data Dharam DNA™**.

Every data object receives a semantic identity describing its nature, obligations, provenance, and permitted usage.

```text
                         DATA
                           │
                           ▼
                 ┌───────────────────┐
                 │ Semantic Identity │
                 └─────────┬─────────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
         Ownership      Purpose       Sensitivity
             │             │             │
             └─────────────┼─────────────┘
                           ▼
                       Consent
                           │
                           ▼
                     Jurisdiction
                           │
                           ▼
                       Retention
                           │
                           ▼
                       Provenance
                           │
                           ▼
                       Trust / Risk
                           │
                           ▼
                    AI Permissions
```

The result is a portable, machine-readable **Dharam identity** for data.

---

# The AI Trust Operating System

Veer Dharam is not another:

- DLP product
- AI firewall
- Compliance dashboard
- API gateway
- Data catalog
- AI observability tool

It is an **AI Trust Operating System** that connects all of them through a unified understanding of data and AI behavior.

```text
                     ┌──────────────────────┐
                     │     Applications     │
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │      AI Agents       │
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │      AI Gateway      │
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │    Dharam Engine     │
                     └──────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
       Data Intelligence   Policy Engine    Risk Engine
              │                 │                 │
              └─────────────────┼─────────────────┘
                                ▼
                     ┌──────────────────────┐
                     │   Decision Engine    │
                     └──────────┬───────────┘
                                │
                 ┌──────────────┼──────────────┐
                 ▼              ▼              ▼
              ALLOW           MODIFY          DENY
                 │              │              │
                 └──────────────┼──────────────┘
                                ▼
                     ┌──────────────────────┐
                     │ Monitoring & Audit   │
                     └──────────────────────┘
```

---

# The Four Pillars

Everything in Veer Dharam revolves around four fundamental capabilities.

## 1. Understand

Understand the meaning, context, sensitivity, ownership, and purpose of data.

## 2. Decide

Determine whether a specific AI operation is permitted.

## 3. Enforce

Apply the decision in real time.

## 4. Observe

Continuously monitor lineage, behavior, risk, and compliance.

```text
              ┌───────────────┐
              │   UNDERSTAND  │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │     DECIDE    │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │    ENFORCE    │
              └───────┬───────┘
                      │
                      ▼
              ┌───────────────┐
              │    OBSERVE    │
              └───────────────┘
```

---

# Core Capabilities

## AI Data Discovery

Discover sensitive and regulated information across:

- Files
- Databases
- Object Storage
- APIs
- SaaS applications
- Enterprise applications
- Email
- Chat systems
- AI conversations
- Data lakes
- Vector databases

---

## Semantic Data Classification

Move beyond regex and pattern matching.

Veer Dharam understands the **meaning and context** of information.

It can identify:

- Personally Identifiable Information
- Protected Health Information
- Financial Information
- Government IDs
- Credentials
- Source Code
- Intellectual Property
- Trade Secrets
- Contracts
- Legal Information
- Biometric Information
- Confidential Business Information
- Custom enterprise-defined data classes

---

# Purpose-Aware AI Governance

The same data may be legitimate for one purpose and prohibited for another.

For example:

```text
Payroll Data

        │
        ├── HR Analysis ───────────► ALLOW
        │
        ├── Payroll Reporting ─────► ALLOW
        │
        ├── Anonymous Statistics ──► TRANSFORM
        │
        └── Public AI Training ────► DENY
```

Veer Dharam evaluates **intent and purpose**, not just data sensitivity.

---

# Prompt Firewall

Protect AI interactions in real time.

Detect and respond to:

- Sensitive data leakage
- Prompt injection
- Jailbreak attempts
- Secret exposure
- Unauthorized context
- Malicious instructions
- Data exfiltration
- Unsafe tool invocation

Possible actions:

```text
ALLOW
MASK
REDACT
TRANSFORM
QUARANTINE
DENY
AUDIT
```

---

# AI Gateway

Provide a unified trust layer between applications and AI providers.

Designed to support:

- OpenAI
- Azure OpenAI
- Anthropic
- Google Gemini
- Amazon Bedrock
- NVIDIA NIM
- Ollama
- vLLM
- OpenRouter
- Self-hosted models
- Enterprise AI platforms

The application should not need to understand every provider's security model.

Veer Dharam becomes the trust boundary.

---

# AI Agent Governance

AI agents can:

- Read documents
- Query databases
- Call APIs
- Execute tools
- Modify records
- Send messages
- Create content
- Trigger workflows

Veer Dharam governs these operations through context-aware policies.

Designed for ecosystems including:

- MCP
- LangChain
- LangGraph
- CrewAI
- AutoGen
- OpenAI Agents SDK
- Custom AI agents

---

# RAG & Vector Database Protection

AI systems increasingly transform sensitive information into embeddings.

Veer Dharam treats embeddings as governed data rather than anonymous vectors.

The platform is designed to protect:

- Documents
- Chunks
- Embeddings
- Metadata
- Retrieval context
- Vector indexes
- RAG responses

Target integrations include:

- PostgreSQL / pgvector
- Milvus
- Pinecone
- Qdrant
- Weaviate
- Chroma
- Redis

---

# Data Lineage

Understand the complete journey of information.

```text
                  Source Document
                        │
                        ▼
                     Chunking
                        │
                        ▼
                    Embedding
                        │
                        ▼
                   Vector DB
                        │
                        ▼
                    Retrieval
                        │
                        ▼
                      Prompt
                        │
                        ▼
                       LLM
                        │
                        ▼
                     Agent
                        │
                        ▼
                       API
                        │
                        ▼
                    Decision
```

Every transformation becomes part of the trust graph.

---

# Trust Graph

Veer Dharam maintains relationships between:

- People
- Data
- Applications
- Models
- Agents
- Prompts
- Embeddings
- APIs
- Policies
- Regulations
- Decisions

This enables questions such as:

> Which AI models have accessed this customer's information?

> Which prompts contained regulated data?

> Which vector indexes contain this document?

> Which agents can access this dataset?

> What must be deleted if consent is revoked?

> Which regulations apply to this AI workflow?

---

# AI Risk Engine

Continuously evaluate:

- Privacy Risk
- Data Exposure Risk
- Regulatory Risk
- Model Risk
- Agent Risk
- Supply Chain Risk
- Prompt Risk
- Context Risk
- Compliance Risk

Every AI operation can receive a contextual risk assessment.

---

# Autonomous Dharam Agents

Veer Dharam will eventually include autonomous agents capable of:

### Discovery Agent

Find sensitive data and unknown AI data flows.

### Privacy Agent

Identify privacy violations.

### Compliance Agent

Map data usage against regulatory requirements.

### Remediation Agent

Automatically apply safe corrective actions.

### Investigation Agent

Explain how a data exposure occurred.

### Policy Agent

Recommend or generate policies based on observed behavior.

---

# Regulations & Frameworks

Veer Dharam is designed to support policy frameworks including:

- GDPR
- EU AI Act
- India's Digital Personal Data Protection Act
- CCPA / CPRA
- HIPAA
- PCI DSS
- SOC 2
- ISO 27001
- ISO 42001
- NIST AI Risk Management Framework
- PIPEDA
- Regional and organization-specific policies

Regulatory support is implemented as **machine-readable policy**, rather than static documentation.

---

# Architecture

```text
                         VEER DHARAM
                    AI TRUST OPERATING SYSTEM

 ┌─────────────────────────────────────────────────────────┐
 │                    TRUST CONTROL PLANE                  │
 │                                                         │
 │  ┌────────────┐  ┌────────────┐  ┌─────────────────┐   │
 │  │ Data DNA   │  │   Policy   │  │   Risk Engine   │   │
 │  └────────────┘  └────────────┘  └─────────────────┘   │
 │                                                         │
 │  ┌────────────┐  ┌────────────┐  ┌─────────────────┐   │
 │  │ Trust Graph│  │ Compliance │  │ Dharam Agents   │   │
 │  └────────────┘  └────────────┘  └─────────────────┘   │
 └───────────────────────────┬─────────────────────────────┘
                             │
                             ▼
 ┌─────────────────────────────────────────────────────────┐
 │                     TRUST DATA PLANE                    │
 │                                                         │
 │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │
 │  │ AI Gateway │ │ Prompt FW  │ │ Agent Enforcement  │  │
 │  └────────────┘ └────────────┘ └────────────────────┘  │
 │                                                         │
 │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │
 │  │ RAG Guard  │ │ Data Guard │ │ Runtime Monitoring │  │
 │  └────────────┘ └────────────┘ └────────────────────┘  │
 └───────────────────────────┬─────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
           LLMs           Agents         Enterprise
                                           Systems
```

---

# Repository Structure

```text
veer-dharam/
│
├── crates/
│   ├── dharam-core/
│   ├── dharam-dna/
│   ├── dharam-classifier/
│   ├── dharam-policy/
│   ├── dharam-gateway/
│   ├── dharam-shield/
│   ├── dharam-risk/
│   ├── dharam-graph/
│   ├── dharam-lineage/
│   ├── dharam-audit/
│   ├── dharam-watch/
│   ├── dharam-agents/
│   ├── dharam-sdk/
│   └── dharam-cli/
│
├── ui/
│
├── integrations/
│   ├── llm/
│   ├── vector-db/
│   ├── databases/
│   ├── cloud/
│   └── agents/
│
├── policies/
│   ├── gdpr/
│   ├── dpdp/
│   ├── eu-ai-act/
│   ├── hipaa/
│   ├── pci-dss/
│   └── custom/
│
├── schemas/
│
├── examples/
│
├── docs/
│   ├── architecture/
│   ├── concepts/
│   ├── dharam-dna/
│   ├── policies/
│   ├── integrations/
│   └── security/
│
├── tests/
│
├── Cargo.toml
├── LICENSE
└── README.md
```

---

# Technology Foundation

Veer Dharam is designed as cloud-native infrastructure.

| Layer | Technology |
|---|---|
| Core Language | Rust |
| Edition | Rust 2024 |
| Async Runtime | Tokio |
| API Framework | Axum |
| Database | PostgreSQL |
| Graph | Neo4j |
| Search | OpenSearch |
| Cache | Redis |
| Messaging | NATS |
| Vector Engine | pgvector / Milvus |
| Policy | Open Policy Agent |
| Policy Language | Rego |
| UI | React + TypeScript |
| CLI | Rust |
| Containers | OCI |
| Orchestration | Kubernetes |

The architecture remains modular so individual components can evolve independently.

---

# Design Principles

## Privacy by Design

Privacy is an architectural property, not an afterthought.

## Zero Trust

No AI system, agent, application, or user is inherently trusted.

## Purpose First

Data usage must be evaluated against its intended purpose.

## Semantic Understanding

Meaning matters more than patterns.

## Policy as Code

Policies must be executable, testable, versioned, and auditable.

## Explainable Decisions

Every significant trust decision should be explainable.

## Data Sovereignty

Jurisdiction and residency must be first-class concepts.

## Open Architecture

Veer Dharam should integrate with existing AI infrastructure rather than replace it unnecessarily.

## Developer First

Trust should be easy to integrate into applications and AI systems.

## Autonomous Governance

The platform should progressively move from detecting violations to preventing and remediating them.

---

# Security Model

Veer Dharam itself follows a Zero Trust architecture.

```text
             Identity
                │
                ▼
             Context
                │
                ▼
              Policy
                │
                ▼
              Risk
                │
                ▼
             Decision
                │
                ▼
             Action
                │
                ▼
              Audit
```

Security controls should themselves be observable, testable, and auditable.

---

# Roadmap

## Phase 0 — Foundation

- [ ] Repository architecture
- [ ] Dharam Core
- [ ] Data Dharam DNA schema
- [ ] Core policy model
- [ ] Rust workspace
- [ ] CLI foundation
- [ ] Developer documentation

## Phase 1 — Understand

- [ ] Data discovery
- [ ] Semantic classification
- [ ] PII detection
- [ ] Secret detection
- [ ] Data ownership
- [ ] Data purpose
- [ ] Sensitivity model
- [ ] Data Dharam DNA generation

## Phase 2 — Decide

- [ ] Policy engine
- [ ] Context-aware authorization
- [ ] Purpose-aware authorization
- [ ] Regulatory policy packs
- [ ] Risk engine
- [ ] Explainable decisions

## Phase 3 — Enforce

- [ ] AI Gateway
- [ ] Prompt Firewall
- [ ] Data masking
- [ ] Redaction
- [ ] Token filtering
- [ ] Agent controls
- [ ] RAG protection
- [ ] Vector database controls

## Phase 4 — Observe

- [ ] Data lineage
- [ ] Trust Graph
- [ ] AI activity monitoring
- [ ] Audit system
- [ ] Compliance dashboard
- [ ] Risk visualization

## Phase 5 — Autonomous Trust

- [ ] Dharam Agents
- [ ] Autonomous remediation
- [ ] Predictive privacy risk
- [ ] AI workflow simulation
- [ ] Data Trust Twin
- [ ] Continuous compliance
- [ ] Automated policy generation

---

# The Long-Term Vision

The ultimate goal is not simply to detect violations.

It is to make violations **structurally difficult to occur**.

Imagine an organization where:

```text
Every Dataset
      │
      ▼
Has a Dharam
      │
      ▼
Every AI knows it
      │
      ▼
Every AI operation is evaluated
      │
      ▼
Every decision is enforceable
      │
      ▼
Every transformation is traceable
      │
      ▼
Every violation can be explained
      │
      ▼
Every remediation can become autonomous
```

That is the future Veer Dharam is designed to build.

---

# The Mission

Veer Dharam exists to create a world where Artificial Intelligence can operate at enormous scale without requiring organizations to surrender control of their data.

We believe trust should not be manually added to AI.

**Trust should be built into its infrastructure.**

---

<div align="center">

# Veer Dharam

## Every piece of data has a Dharam.

## Every AI must honor it.

---

### Building the Trust Layer for the Age of Artificial Intelligence.

</div>
