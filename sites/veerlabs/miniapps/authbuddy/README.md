<div align="left">
  <img src="auth_buddy_bluepurple.png" alt="AuthBuddy Logo" width="200"/>
</div>

AuthBuddy is a Rust-based identity provider and OAuth2/OIDC server that combines form login, MFA, passkeys, and standards-compliant federation in a single, extensible service.

## Overview
AuthBuddy provides a production-oriented authentication stack with a clean separation between domain models, services, HTTP handlers, and storage. It ships with client SDKs (TypeScript, React, Rust) and a Dioxus Web demo client.

## Key capabilities

### Core authentication
- User registration and password login with bcrypt and configurable password policy
- Session creation, validation, and revocation
- Account-level authentication context tracking

### MFA and passkeys
- TOTP setup and verification (RFC 6238)
- OTP via email or SMS (provider interface with mock implementations)
- Passkey registration and authentication (WebAuthn)

### OAuth2/OIDC provider
- OIDC discovery endpoint
- Authorization Code Flow with mandatory PKCE
- Token issuance (ID, access, refresh) with RS256 signing
- Token introspection and revocation endpoints
- JWKS for key distribution and rotation
- Consent model and logout endpoint
- Resource endpoints demonstrating access token validation

### Client SDKs and demos
- TypeScript/JavaScript SDK: `clients/typescript/`
- React SDK: `clients/react/`
- Rust SDK: `clients/rust/`
- Dioxus Web demo app: `clients/rust/examples/web-client/`

## Project layout
```
src/
	config/           # App configuration defaults and env mapping
	crypto/           # JWT key management and token issuer
	domain/           # Core domain models (user, session, consent, token)
	error/            # Error types
	http/             # HTTP routes and handlers
	logging/          # Logging configuration
	services/         # Business logic (auth, MFA, OAuth2)
	storage/          # Postgres and RocksDB implementations
migrations/         # SQL migrations
clients/            # SDKs and examples
```

## Quick start (server)

### Prerequisites
- Rust (stable)
- PostgreSQL 16+ (or use Docker)

### Start Postgres with Docker
```bash
docker compose up -d
```

The `migrations/` folder is mounted and applied during the container init.

### Run the server
```bash
cargo run
```

### Build a release binary
```bash
cargo build --release
```

The default server listens on `127.0.0.1:8080`.

## Configuration
AuthBuddy uses layered configuration: defaults, optional `.env`, then environment variables. The structure mirrors `AppConfig` in [src/config/mod.rs](src/config/mod.rs).

Example `.env`:
```env
SERVER__HOST=0.0.0.0
SERVER__PORT=8080
SERVER__ENV=development
DATABASE__POSTGRES_URL=postgres://authbuddy:authbuddy@192.168.29.78/authbuddy
STORAGE__ROCKSDB_PATH=./data/rocksdb
JWT__ISSUER=https://authbuddy.local
```

## Core endpoints (high level)

### Authentication
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/mfa/totp/setup`
- `POST /auth/mfa/totp/verify`
- `POST /auth/mfa/otp/request`
- `POST /auth/mfa/otp/verify`
- `POST /auth/passkey/register/begin`
- `POST /auth/passkey/register/complete`
- `POST /auth/passkey/authenticate/begin`
- `POST /auth/passkey/authenticate/complete`

### OAuth2/OIDC
- `GET /.well-known/openid-configuration`
- `GET /oauth2/authorize`
- `POST /oauth2/token`
- `GET /oauth2/jwks`
- `POST /oauth2/introspect`
- `POST /oauth2/revoke`
- `GET /oauth2/logout`

### Resource server examples
- `GET /resource/userinfo`
- `GET /resource/protected`

## Client SDKs
AuthBuddy ships with SDKs and examples in [clients/README.md](clients/README.md). Each SDK exposes a consistent feature set (auth, OAuth2/OIDC, MFA, passkeys, token management).

## Dioxus Web demo
The Rust example web client demonstrates all flows in a single SPA:
```
clients/rust/examples/web-client/
```

## Documentation
- Phase summaries: [PHASE_2_SUMMARY.md](PHASE_2_SUMMARY.md), [PHASE_3_SUMMARY.md](PHASE_3_SUMMARY.md), [PHASE_3.5_SUMMARY.md](PHASE_3.5_SUMMARY.md), [PHASE_4_SUMMARY.md](PHASE_4_SUMMARY.md)
- Client SDKs: [CLIENT_SDKS_SUMMARY.md](CLIENT_SDKS_SUMMARY.md)

## Enterprise Integrations
AuthBuddy can serve as an Identity Provider for enterprise platforms requiring step-up authentication and risk-based authorization:

### FortressDigital Treasury Settlement
Complete integration guide for using AuthBuddy as IdP in treasury operations with TOTP/OTP and WebAuthn step-up flows:
- **Integration Guide**: [FORTRESSDIGITAL_INTEGRATION.md](FORTRESSDIGITAL_INTEGRATION.md)
- **TypeScript Example**: [examples/fortressdigital-integration.ts](examples/fortressdigital-integration.ts)
- **Rust Example**: [examples/fortressdigital-integration.rs](examples/fortressdigital-integration.rs)

Features covered:
- Token validation and claims processing (amr, acr, device_id)
- Risk-based policies for treasury operations (view, transfer, wire)
- Step-up authentication triggers based on transaction risk
- TOTP/OTP and WebAuthn/Passkey flows
- Authentication context evaluation and enforcement

## Security notes
- TLS is required in production (see `security.require_tls_in_production` in config)
- PKCE is mandatory for OAuth2 authorization code flow
- Tokens are signed with RS256 and served via JWKS
- Password hashing uses bcrypt with configurable cost

## Development tips
- Run `cargo check` for fast compile feedback
- Use `docker compose up -d` to spin up Postgres quickly
- See [clients/README.md](clients/README.md) for SDK build and example commands
