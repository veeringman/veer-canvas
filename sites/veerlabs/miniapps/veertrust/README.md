# VeerTrust - Zero Trust Architecture for Veer Edge

This document outlines VeerTrust , the full Zero Trust Network (ZTN) architecture for the **Veer Edge Platform**, including its core components, protocols, interactions, and design dynamics.

---

## 🧩 Architecture Diagram

![ZTN Diagram](./docs/veertrust_ztn.png)

> _The above diagram represents device interaction with Edge Gateway, mobile apps, cloud services, and secure policy enforcement in a Zero Trust model._

---

## 🔐 VeerTrust ZTN Core Layers & Components

### 1. **Devices**
- Includes IoT sensors, mobile phones, user devices
- **Functions**:
  - Authenticate via JWT or device certificates
  - TPM-backed attestation
  - Secure telemetry/data streaming
- **Protocols**: `mTLS`, `OAuth2`, `JWT`, `TPM attestation`

### 2. **Edge Gateway**
Core component enforcing Zero Trust principles at the edge

- **Modules**:
  - `VeerAuth Agent` – Manages workload/device identities
  - `VeerPolicy` – Enforces RBAC/ABAC policies
  - `VeerAttest` – Performs remote attestation
- **Protocols**: `mTLS`, `QUIC`, `gRPC`, `SPIFFE IDs`

### 3. **Mobile Apps / Web Consoles**
- User access layer for managing and interacting with edge services
- **Protocols**: `HTTPS`, `OAuth2`, `WebTransport`, `gRPC`

### 4. **MEC Server**
- Handles heavy computation and model inference
- **Functions**:
  - Validates trust state via attestation
  - Connects securely to edge gateway and policy engine
- **Protocols**: `mTLS`, `Remote Attestation`, `QUIC`, `gRPC`

### 5. **Policy Engine**
- **Functions**:
  - Evaluates access decisions using context and risk
  - Hosts RBAC/ABAC policies
  - Syncs policy bundles with gateways
- **Protocols**: `gRPC`, `WASM Runtime`, `OPA`/custom engine

### 6. **Remote Verifier**
- Trust broker to validate hardware/software posture
- **Protocols**: `Attestation Protocols`, `gRPC`, `Signed Tokens`

### 7. **ICE Enclave**
- Secure enclave for protected workload execution (e.g., AI inference)
- **Basis**: `Enarx`, `SEV`, `SGX`, or lightweight containerized TEE runtimes

### 8. **Observability Stack**
- Telemetry collection and behavior anomaly detection
- **Tools**: `OpenTelemetry`, `Prometheus`, `Loki`
- **Protocols**: `OTLP`, `gRPC`, `HTTP`

---

## 🔄 Communication Matrix

| Source → Target | Protocols | Purpose |
|-----------------|-----------|---------|
| Device → Edge Gateway | mTLS, QUIC | Secure, verified access |
| App → API Gateway | OAuth2, mTLS, gRPC | Secure user data/API access |
| Edge → Policy Engine | gRPC, OPA Bundles | Policy sync + evaluation |
| Gateway → Verifier | Remote Attestation | Trust validation |
| Edge → MEC | mTLS, QUIC | Secure heavy compute access |
| Edge → ICE Enclave | IPC, encrypted gRPC | Secure isolated workloads |
| Edge → Observability | OTLP, gRPC | Telemetry, anomaly reporting |
| Policy → Cloud | HTTPS, gRPC | Risk ingestion, cloud policy sync |

---

## ✅ Summary

- Built fully in **Rust** for maximum performance and security
- Based on **mutual authentication**, **dynamic policy enforcement**, and **real-time risk evaluation**
- Modular components (`VeerAuth`, `VeerPolicy`, `VeerAttest`) form the foundation of a decentralized trust network
- Future-ready for integration into **QuantumSrc**

> _All identities, policies, and trust signals are evaluated continuously. Nothing is trusted by default._

---

_This architecture ensures secure, adaptive, and resilient edge deployments for mobile, IoT, and smart infrastructure._

