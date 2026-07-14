<p align="left">
  <img src="treasury_logo.png" alt="Treasury Settlement" width="90" />
</p>

# Treasury Settlement System

An enterprise Treasury Settlement System for managing bank settlement transactions using FloweR stablecoin. Features a Rust/Actix-web backend API with a React + TypeScript frontend.

## Features

- **Multi-Bank Onboarding** — create banks, custodial wallets, and per-bank dashboards
- **Authentication & RBAC** — JWT-based login with enterprise operator and treasury manager roles
- **Settlement Workflows** — create, approve, and track settlement requests in FloweR
- **Counterparty Directory** — register and manage counterparty banks and wallet addresses
- **Digital Wallet Management** — create, import, and link wallets with AES-256-GCM encrypted key storage
- **OAuth / OIDC Integration** — AuthBuddy step-up authentication support

## Technology Stack

| Layer | Stack |
|-------|-------|
| **Backend** | Rust, Actix-web 4, SQLite (sqlx), JWT, bcrypt, AES-256-GCM |
| **Frontend** | React 18, TypeScript, Vite, TailwindCSS 4, React Router 7 |
| **Infra** | Docker, Docker Compose |

## Quick Start

### Prerequisites

- Rust 1.70+
- Node.js 18+
- SQLite 3

### Backend

```bash
git clone https://github.com/veeringman/TreasurySettlement.git
cd TreasurySettlement
cargo build -p treasury-backend --release
cargo run -p treasury-backend
```

The API starts on `http://192.168.29.78:8080`.

### Frontend

```bash
cd frontend-react
npm install
npm run dev
```

The dev server starts on `http://192.168.29.78:5173` and proxies `/api` requests to the backend.

### Docker

```bash
docker-compose up -d
```

## Project Layout

```
backend/          Rust API server (Actix-web)
frontend-react/   React + TypeScript SPA (Vite)
migrations/       SQLite migration scripts
scripts/          Utility and E2E test scripts
docs/             Integration contracts and manuals
```

## API Overview

| Area | Endpoints |
|------|-----------|
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/profile` |
| Banks | `POST /api/banks`, `GET /api/banks/{id}`, `POST /api/banks/{id}/wallets` |
| Settlements | `POST /api/settlements`, `GET /api/settlements`, `POST /api/settlements/{id}/approve` |
| Counterparties | `POST /api/counterparties`, `GET /api/counterparties` |
| Wallets | `POST /api/wallet`, `GET /api/wallet`, `POST /api/wallet/import` |

See [API_COLLECTION.json](API_COLLECTION.json) for the full request collection.

## Testing

```bash
# Backend unit tests
cargo test -p treasury-backend

# End-to-end tests (start backend first)
bash scripts/e2e.sh
```

## Configuration

Key environment variables (set in `.env` or export directly):

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLite connection string |
| `WALLET_ENC_KEY` | 32-byte AES-256-GCM key for wallet encryption |
| `JWT_SECRET` | Secret for JWT signing |
| `AUTHBUDDY_SERVER_URI` | AuthBuddy OAuth server URL |

Frontend-specific variables are documented in [frontend-react/README.md](frontend-react/README.md).

## Deployment

```bash
docker build -t treasury-settlement .
docker run -p 8080:8080 treasury-settlement
```

See [RUNNING.md](RUNNING.md) and [SETUP.md](SETUP.md) for full deployment guidance.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

MIT — see the LICENSE file for details.

## Authors

- **Vijay Veer Sharma** — Initial development
