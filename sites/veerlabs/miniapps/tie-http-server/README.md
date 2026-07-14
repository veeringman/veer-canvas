# TIE HTTP Server

**Take It Easy — A High-Performance, Feature-Rich HTTP Server Written in C**

---

## Overview

TIE HTTP Server is a lightweight, production-capable HTTP server built from scratch in C. It supports HTTP/1.1 and HTTP/2 over TLS, with a modular architecture covering reverse proxying, virtual hosting, API gateway functionality, WebSocket connections, Server-Sent Events, CGI execution, and a built-in web-based admin console.

### Key Capabilities

| Category | Features |
|---|---|
| **Protocols** | HTTP/1.1, HTTP/2 (HPACK, multiplexing, server push), HTTP/3 (Alt-Svc advertisement) |
| **Security** | TLS 1.2/1.3, ECDHE ciphers, HSTS, mTLS, post-quantum cryptography (hybrid), security headers, CORS |
| **Serving** | Static files, CGI scripts, chunked transfer, byte-range requests, Server-Sent Events |
| **Routing** | Path-based router, virtual hosts (wildcard), reverse proxy (round-robin), API gateway (rate limiting, API keys) |
| **Performance** | Thread pool, in-memory cache (FIFO eviction), ETag/304 support, gzip/deflate compression |
| **Management** | Web admin console, session-based auth, live config/routes/proxy/vhost/gateway management |
| **Middleware** | CORS, compression, security headers, ETag, request ID, HSTS, redirect, admin auth |
| **WebSocket** | RFC 6455 — text, binary, ping/pong, close frames, per-path handlers |
| **Logging** | 4-level logging (DEBUG/INFO/WARNING/ERROR), file + console, thread-safe |

---

## Quick Start

### Prerequisites

- GCC or Clang (C11)
- OpenSSL development libraries
- zlib
- pthreads

### Build & Run

```bash
# Full build (all features enabled)
make all
./bin/tie_server

# Minimal build (no optional features)
make minimal

# Clean build artifacts
make clean
```

### Build Variants

| Target | Description |
|---|---|
| `make all` | Full build with all features |
| `make full` | Explicit full-feature build |
| `make minimal` | HTTP/1.1 only, no optional modules |
| `make install` | System-wide installation |

### Feature Flags

All features are enabled by default. Disable selectively via `make ENABLE_<FLAG>=0`:

```bash
make ENABLE_WEBSOCKET=0 ENABLE_H3=0
```

| Flag | Default | Description |
|---|---|---|
| `ENABLE_H2` | 1 | HTTP/2 over TLS with HPACK |
| `ENABLE_H3` | 1 | HTTP/3 Alt-Svc advertisement |
| `ENABLE_WEBSOCKET` | 1 | RFC 6455 WebSocket support |
| `ENABLE_REVERSE_PROXY` | 1 | Path-based reverse proxying |
| `ENABLE_VHOST` | 1 | Virtual host support |
| `ENABLE_API_GATEWAY` | 1 | API gateway with rate limiting |
| `ENABLE_STREAMING` | 1 | Chunked transfer, SSE, range requests |

---

## Configuration

Main configuration file: `config/tie_server.conf`

### Core Settings

```ini
SERVER_HOST=0.0.0.0          # Bind address
SERVER_PORT=5050              # HTTP port
ENABLE_SSL=1                 # Enable HTTPS
SECURE_PORT=5353             # HTTPS port
DEFAULT_PAGE=index.html      # Default directory page
CONTENT_ROOT=static          # Document root
NUM_THREADS=8                # Worker threads
```

### SSL/TLS

```ini
SSL_CERT_FILE=config/certs/tie_cert.pem
SSL_KEY_FILE=config/certs/tie_key.pem
TLS_MIN_VERSION=1.2          # 1.2 or 1.3
TLS_ALPN=h2,http/1.1         # ALPN negotiation
TLS_HSTS_ENABLED=1           # Strict Transport Security
TLS_PQC_ENABLED=0            # Post-quantum cryptography
MTLS_ENABLED=0               # Mutual TLS
MTLS_CA_FILE=config/certs/ca_cert.pem
```

### Admin Console

```ini
ADMIN_USER=admin
ADMIN_PASS=takeiteasy        # CHANGE IN PRODUCTION
```

Access the admin UI at `https://localhost:5353/tie/admin/`

### Caching

```ini
ENABLE_CACHE=1
CACHE_SIZE=50                # Max size in MB
CACHE_TTL=600                # TTL in seconds
```

### Virtual Hosts

```ini
VHOST_1_HOSTNAME=example.com
VHOST_1_DOCROOT=/var/www/example
VHOST_1_SSL_CERT=config/certs/cert.pem
VHOST_1_SSL_KEY=config/certs/key.pem
VHOST_1_ALIAS=www.example.com
VHOST_1_PROXY_HOST=127.0.0.1
VHOST_1_PROXY_PORT=3000
VHOST_1_HTTP_REDIRECT=1
```

See `config/samples/` for additional configuration examples.

---

## Directory Structure

```
tie_http_server/
├── src/
│   ├── main.c                 # Entry point, startup sequence
│   ├── core/                  # HTTP server, router, protocols, middleware
│   ├── handlers/              # Static files, CGI, admin, proxy, API gateway
│   ├── middleware/             # Compression, ETag, security headers, request ID
│   ├── config/                # Config parser, security config loader
│   ├── ssl/                   # TLS server, config, utilities
│   ├── shared_memory/         # Shared memory cache
│   └── utils/                 # Thread pool, memory pool, string/file utilities
├── include/                   # All header files
├── config/
│   ├── tie_server.conf        # Main configuration
│   ├── mime.types             # MIME type mappings
│   ├── certs/                 # SSL certificates
│   └── samples/               # Sample configuration files
├── static/                    # Static content document root
├── cgi-bin/                   # CGI scripts
├── logs/                      # Log output
├── tests/                     # Unit and integration tests
├── bin/                       # Compiled binary
└── Makefile                   # Build system
```

---

## Architecture

```
Client Request
     │
     ▼
┌─────────────────┐
│  TCP / TLS      │  Port 5050 (HTTP) or 5353 (HTTPS)
│  Listener       │  ALPN negotiation for HTTP/2
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Thread Pool     │  Pre-allocated worker threads (4–16)
│  Task Queue      │  FIFO dispatch, mutex + condvar
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Protocol Layer  │  HTTP/1.1 parser  ←or→  HTTP/2 (HPACK, streams)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Middleware      │  CORS → Security Headers → Compression → ETag
│  Pipeline        │  → Request ID → HSTS → Admin Auth → Alt-Svc
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Router          │  Path + method matching, vhost resolution
│                  │  Static files, CGI, API, Admin, Proxy, Gateway
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Response        │  Headers, body, compression, chunked encoding
│  Builder         │  Cache integration (ETag, Last-Modified, 304)
└─────────────────┘
```

---

## Documentation

| Document | Description |
|---|---|
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | Complete setup, configuration, and feature guide |
| [docs/ADMIN_MANUAL.md](docs/ADMIN_MANUAL.md) | Admin console usage, API reference, operations guide |
| [TODO.md](TODO.md) | Project roadmap and status |
| [config/samples/](config/samples/) | Sample configuration files |

---

## Testing

```bash
# Run integration tests
bash tests/test_integration.sh

# Individual test files in tests/ directory
```

---

## License

MIT License (c) 2025
