
<p align="left">
	 <img src="edgeVault.png.png" alt="EdgeVault Logo" width="120"/>
</p>


**Bank-grade mobile security framework** — zero-trust device binding, hardware-backed crypto, and multi-jurisdiction compliance in a single, cross-platform SDK.

EdgeVault unifies Android Work Profile and iOS sandbox/MDM approaches into one developer-friendly solution, with a Rust cryptographic core shared across all platforms.

---

## At a Glance

| Metric | Value |
|--------|-------|
| **Languages** | Rust, Swift, Kotlin, TypeScript, Dart, Java, Go, Python |
| **Source files** | 174 |
| **Lines of code** | ~17,900 |
| **Rust tests** | 208 (all passing) |
| **Jurisdictions** | 19 countries |
| **Platform SDKs** | iOS (Swift), Android (Kotlin), React Native, Flutter, Ionic |
| **Backend SDKs** | Rust, Java, Python, Go |

---

## Architecture

```
                         ┌──────────────────────────────────────┐
                         │        Bank Backend / mBaaS          │
                         │  (Backbase, Firebase, Temenos, …)    │
                         └───────────────┬──────────────────────┘
                                         │
                              OpenAPI REST + Webhooks
                                         │
                         ┌───────────────┴──────────────────────┐
                         │     EdgeVault Integration Layer       │
                         │  Webhooks · SIEM · Connector Traits   │
                         └───────────────┬──────────────────────┘
                                         │
                              mTLS + Device Identity
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              │                                                     │
   ┌──────────────────┐                                  ┌──────────────────┐
   │   iOS Device      │                                  │  Android Device   │
   │                   │                                  │                   │
   │  Swift SDK        │                                  │  Kotlin SDK       │
   │  + Rust Core      │                                  │  + Rust Core      │
   │                   │                                  │                   │
   │  Secure Enclave   │                                  │  Android Keystore │
   └──────────────────┘                                  └──────────────────┘
              │                                                     │
     ┌────────────────┐                                    ┌────────────────┐
     │ React Native   │                                    │ Flutter / Ionic│
     │ Cross-platform │                                    │ Cross-platform │
     └────────────────┘                                    └────────────────┘
```

---

## Core Capabilities

### Cryptography
- AES-256-GCM encryption/decryption
- HKDF-SHA256 key derivation
- CSPRNG random byte generation
- Hardware-backed key storage (Secure Enclave / Android Keystore)

### Device Identity & Trust
- Hardware-bound device fingerprinting
- X.509 certificate management
- Platform attestation (Play Integrity / App Attest)
- Continuous trust scoring

### Policy Engine
- JSON-defined security rules with severity levels
- Real-time policy evaluation per device context
- Dynamic policy distribution from backend

### Compliance & Jurisdictions
19 jurisdiction profiles with pluggable compliance traits:

🇺🇸 US · 🇨🇦 CA · 🇮🇳 IN · 🇬🇧 GB · 🇪🇺 EU · 🇩🇪 DE · 🇦🇺 AU · 🇸🇬 SG · 🇯🇵 JP · 🇰🇷 KR · 🇧🇷 BR · 🇦🇪 AE · 🇸🇦 SA · 🇭🇰 HK · 🇿🇦 ZA · 🇲🇽 MX · 🇳🇬 NG · 🇨🇭 CH · 🇮🇩 ID

Each profile defines: crypto requirements, data residency rules, audit retention, incident reporting SLAs, and privacy constraints.

### Risk & Incident Response
- Multi-signal risk scoring (root/jailbreak, debugger, emulator, network, geo, behavioral)
- Automated incident creation with severity escalation
- Remote selective wipe with cryptographic verification
- Data Residency Router with jurisdiction-aware storage

### Bank Backend Integration
- **OpenAPI 3.1.0** REST contract (20+ endpoints, 30+ schemas)
- **Webhooks** with HMAC-SHA256 signatures for real-time event delivery
- **SIEM adapters** — Splunk, ELK, ArcSight (CEF), LogRhythm (LEEF), syslog (RFC 5424)
- **Banking connector traits** for Backbase, Firebase, Amplify, Temenos, custom REST
- **Backend SDKs** for Rust, Java (Spring Boot), Python (httpx/Pydantic), Go

---

## Project Structure

```
edgevault/
├── core/                    Rust core library (88 tests)
│   └── src/                 crypto, storage, identity, policy, compliance,
│                            risk, network, ffi
│
├── backend/                 Server-side services (61 tests)
│   └── src/                 API gateway, identity, trust, audit, wipe,
│                            data residency, incident response
│
├── workspace-app/           Secure container shell (22 tests)
│   └── src/                 Shell, module loader, sandbox, session, API
│
├── integration/             Bank backend integration layer (37 tests)
│   ├── openapi/             OpenAPI 3.1.0 spec
│   ├── src/                 Events, webhooks, SIEM, connector traits
│   └── sdk/                 Backend SDKs
│       ├── rust/            Async Rust client (reqwest + tokio)
│       ├── java/            Spring Boot 3.3+ (Maven)
│       ├── python/          httpx + Pydantic 2 (async)
│       └── go/              Standard library Go client
│
├── ios-sdk/                 Swift SDK (iOS 15+)
├── android-sdk/             Kotlin SDK (minSdk 26)
├── react-native-sdk/        React Native wrapper
├── flutter-sdk/             Flutter/Dart wrapper
├── ionic-sdk/               Ionic/Capacitor wrapper
│
├── examples/                Demo apps
│   ├── ios-demo/            SwiftUI (7 screens)
│   ├── android-demo/        Jetpack Compose (8 screens)
│   ├── react-native-demo/   10-feature demo
│   ├── flutter-demo/        10-feature demo
│   └── ionic-demo/          10-feature demo
│
└── docs/
    └── DEVELOPER_GUIDE.md   Comprehensive dev guide (~2,100 lines)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Cryptographic core** | Rust (AES-256-GCM, HKDF, X.509) |
| **iOS SDK** | Swift, C modulemap FFI bridge |
| **Android SDK** | Kotlin, JNA 5.14 |
| **React Native** | TypeScript, NativeModules bridge |
| **Flutter** | Dart 3.2+, MethodChannel |
| **Ionic** | Capacitor 5/6, web fallback |
| **Integration** | OpenAPI 3.1.0, HMAC-SHA256 webhooks |
| **Backend SDKs** | Rust (reqwest), Java (Spring Boot), Python (httpx), Go |
| **CI/CD** | GitHub Actions, Docker |

---

## Design Principles

1. **Zero Trust** — every request verified, no implicit trust
2. **Hardware-backed security** — Secure Enclave / Android Keystore for all key material
3. **Selective wipe** — cryptographic erasure without full device wipe
4. **Jurisdiction as code** — compliance profiles are pluggable traits, not hardcoded
5. **Defense in depth** — multiple layers from SDK to backend to SIEM

---

## Modes of Operation

### Embedded SDK Mode
Integrate EdgeVault directly into your existing banking app:
```
Bank App → EdgeVault SDK → Secure Storage + Identity + Policy
```

### Workspace App Mode
Deploy as a standalone secure container:
```
EdgeVault Workspace → Secure Shell → Mini Apps + Secure WebViews
```

---

## Getting Started

1. Clone: `git clone <repo-url>`
2. Build core: `cd edgevault/core && cargo build`
3. Run tests: `cd edgevault/core && cargo test`
4. See platform SDK READMEs for iOS/Android/cross-platform setup
5. See `docs/DEVELOPER_GUIDE.md` for the full developer guide

---

## Documentation

- [Developer Guide](edgevault/docs/DEVELOPER_GUIDE.md) — API reference, integration recipes, compliance guide, troubleshooting
- [Architecture Blueprint](EdgeVault_Architecture.md) — detailed system design
- [OpenAPI Spec](edgevault/integration/openapi/edgevault-api.yaml) — REST API contract

---

## License

See LICENSE file for details.
