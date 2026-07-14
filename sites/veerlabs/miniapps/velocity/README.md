# ⚡ VELOCITY

<p align="center">
    <img src="logo/velocity-logo.png" alt="VELOCITY logo" width="920"/>
</p>

> **AI-native, modular, event-driven quantitative trading infrastructure** — focused initially on Indian Equity & Derivatives and Cryptocurrency markets, architected to scale into a universal trading operating system.

---

## Vision

Velocity is **not** a trading bot. It is a **scalable AI-powered quant trading infrastructure platform** built around:

- **Adaptability** — broker/exchange/strategy agnostic from day one
- **Reliability** — institutional-grade risk controls and resilience
- **Extensibility** — every component is an interchangeable plugin
- **Intelligent Execution** — AI augments, never blindly replaces, the quant engine
- **Production-grade Engineering** — observable, testable, cloud-native

---

## Architecture Overview

```
┌────────────────────┐
│ Market Data Layer  │  ← real-time feeds, order book, historical replay
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Feature Pipeline   │  ← momentum, volatility, VWAP, sentiment, regime
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Signal Engine      │  ← plug-and-play strategies (Indian + Crypto)
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Risk Engine        │  ← drawdown, sizing, leverage, circuit breakers
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Execution Engine   │  ← broker-agnostic, async, retry-safe
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ Monitoring & AI    │  ← Grafana, Prometheus, LLM insights
└────────────────────┘
```

---

## Primary Markets

| Market | Instruments | Brokers / Exchanges |
|---|---|---|
| Indian Equities & Derivatives | NSE equities, options, futures, indices | Zerodha Kite, Upstox, Angel One, Fyers |
| Cryptocurrency | Spot, perpetual futures, arbitrage | Binance, Bybit, Coinbase, OKX |

---

## Documentation

| Document | Purpose |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component deep-dive, interfaces, data contracts |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Technology choices and rationale |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phased delivery plan |
| [docs/TODO.md](docs/TODO.md) | Granular per-component task tracker |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Engineering principles and dev guidelines |
| [docs/ORDER_LIFECYCLE_SEQUENCE.md](docs/ORDER_LIFECYCLE_SEQUENCE.md) | End-to-end order lifecycle sequence diagram |

---

## Local Setup and App Management (macOS + Linux/Ubuntu)

Velocity includes script-based lifecycle management under `scripts/`.

1. Initial setup.

On macOS, the existing path is unchanged:

```bash
./scripts/setup.sh
```

On Ubuntu/Debian, install the required system packages once, then bootstrap the project:

```bash
make system-deps
./scripts/setup.sh
```

If `make system-deps` fails due a broken apt source/PPA, you can still continue without apt:

```bash
./scripts/setup.sh
```

The setup script will auto-bootstrap Python 3.12 in user space via `uv` when the system Python is older.

2. Start API in background:

```bash
./scripts/velocityctl.sh start
```

For explicit LAN access (binds to `0.0.0.0` and prints network URLs):

```bash
./scripts/velocityctl.sh start --network
make start-network
```

3. Manage process:

```bash
./scripts/velocityctl.sh status
./scripts/velocityctl.sh logs 200
./scripts/velocityctl.sh restart
./scripts/velocityctl.sh stop
```

Optional setup flags:

```bash
./scripts/setup.sh --python python3.12
./scripts/setup.sh --skip-dev
./scripts/setup.sh --install-system-deps
./scripts/setup.sh --no-python-bootstrap
./scripts/setup.sh --migrate
```

Build distribution artifacts:

```bash
./scripts/build.sh
make build
```

Optional runtime flags/env:

```bash
VELOCITY_HOST=127.0.0.1 VELOCITY_PORT=9000 ./scripts/velocityctl.sh start
./scripts/velocityctl.sh run --host 0.0.0.0 --port 8000
./scripts/velocityctl.sh status --network
```

---

## Free Indian Market Data (NSE/BSE)

Velocity now includes a free India historical data path using Yahoo Finance (`yfinance`).

1. Fetch candles directly (NSE/BSE):

```bash
curl "http://127.0.0.1:8000/data/india/candles?symbol=RELIANCE&exchange=NSE&interval=1d&lookback_days=10&limit=5"
```

2. Run backtest on India free source:

```bash
curl -X POST "http://127.0.0.1:8000/backtesting/run" \
    -H "Content-Type: application/json" \
    -d '{
        "symbol": "RELIANCE",
        "strategy_id": "momentum_breakout",
        "interval": "1d",
        "start_time": "2026-03-01T00:00:00Z",
        "end_time": "2026-05-08T00:00:00Z",
        "source": "india_free",
        "india_exchange": "NSE"
    }'
```

Notes:
- Symbol aliases supported: `RELIANCE`, `NSE:INFY`, `SBIN.BO`, `TCS.NS`.
- This source is best-effort and typically delayed; use broker/exchange licensed feeds for strict real-time trading.

---

## CLI Backtest and Benchmark

Run file-based backtests directly from the CLI:

```bash
/Users/vijay/rnd/projects/velocity/.venv/bin/python -m core.cli backtest \
    --input ./data/candles.csv \
    --strategy momentum_breakout \
    --exchange BINANCE \
    --symbol BTCUSDT \
    --interval 1m \
    --initial-capital 100000 \
    --trade-qty 1 \
    --output ./out/backtest.json \
    --html-report ./out/backtest.html
```

Run the baseline-vs-AI benchmark harness from the same candle file:

```bash
/Users/vijay/rnd/projects/velocity/.venv/bin/python -m core.cli benchmark \
    --input ./data/candles.csv \
    --exchange BINANCE \
    --symbol BTCUSDT \
    --interval 1h \
    --lookback 72 \
    --forecast-horizon 8 \
    --step 6 \
    --output ./out/benchmark.json \
    --html-report ./out/benchmark.html
```

CLI benchmark output includes sample count, baseline/AI accuracy, and edge lift so you can quickly compare deterministic baseline signals against AI-enhanced scoring.

---

## Development Phases

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Data ingestion, paper trading, backtesting, broker integration | ✅ Done |
| **Phase 2** | Quant strategies, risk engine, portfolio layer | ✅ Done |
| **Phase 3** | ML models, regime detection, adaptive optimization | 🔄 In progress (Adaptive Scalper + execution guardrails landed) |
| **Phase 4** | Distributed infrastructure, multi-asset expansion | 🔲 Not started |

### Phase 3 highlights (live)

- **Adaptive Intelligence Scalper** with regime-aware specialists and triple-barrier exits.
- **Walk-forward parameter sweep** at `POST /backtesting/sweep` with a collapsible UI form under the Backtesting Lab.
- **Vol-targeted sizing** via `risk_per_trade_pct` on the backtest form (signal carries a `stop_distance_pct` hint).
- **Pre-trade execution guardrails** (spread / depth / latency + maker-first conversion) configurable live at `GET|PUT /execution/guardrails` and through the **Execution Guardrails** dashboard card.

---

## Core Engineering Principle

Every module must be:
- **independently replaceable** — swap broker, strategy, or AI model without touching others
- **loosely coupled** — communicate via events and well-defined APIs
- **event-aware** — react to market ticks, order updates, risk alerts
- **testable** — unit + integration testable in isolation
- **scalable** — horizontal scaling from single VPS to Kubernetes cluster

---

## Branding

Logo assets live in [`logo/`](logo/). Open [`logo/index.html`](logo/index.html) for the full brand showcase.
