# Veer Edge Platform

**Veer Edge** is a Rust-native, modular, and secure Mobile Edge Platform that unifies mobile computing, on-device inference, IoT gateway control, and multi-protocol communication under one powerful architecture. It enables real-time decision-making, offline-first intelligence, and seamless cloud-edge-device orchestration — ideal for modern edge-native apps in logistics, manufacturing, smart cities, and more.

---

## 🧠 Key Capabilities

- 🚀 **Edge-Native Runtime:** Fast, lightweight Spin/WASM runtimes with TVM, ONNX for real-time inference
- 📶 **Protocol-Rich Gateway:** Supports QUIC, WebTransport, MQTT, CoAP, HTTP/2, LwM2M
- 📱 **Offline-First Mobile Apps:** Built using Vero (Rust UI runtime), with local storage & sync
- 📡 **IoT Gateway Control:** Bridging legacy and modern device protocols with pub/sub architecture
- 🔐 **Security Built-In:** TPM-based attestation, secure boot, Vault integration, OPA policy control
- 🔄 **Distributed Edge Coordination:** Runs in Far Edge, Near Edge, and Mobile Environments

---

## 🧱 Architecture Overview

![Veer Edge Architecture](docs/veer_edge_platform.png)

### Layered Components

#### 📲 Mobile App Layer
- `Vero Runtime`, `Edge SDK`, `Local Storage`, `ML Inference`
- **Protocols:** gRPC, QUIC, WebTransport, HTTP/2, LwM2M, WebRTC

#### 🌐 Edge Gateway Node
- `MQTT Broker`, `QUIC/WebTransport Listener`, `Spin Runtime`, `QuasarCache`
- **Bridges:** MQTT, CoAP, QUIC, HTTP, NATS

#### 🔁 Edge Middleware
- `Service Mesh`, `Protocol Abstraction`, `Pub/Sub`, `Sync Engine`
- **Messaging:** Kafka, NATS, ZeroMQ, AMQP

#### ☁️ Cloud / Core
- `Model Training (Kubeflow)`, `Analytics (ClickHouse)`, `Vault`, `Monitoring`
- **Integration:** HTTPS, gRPC, S3 Sync, Webhooks

#### 📦 Device Layer (Field/IoT Devices)
- `Sensors`, `Cameras`, `Mobile Agents`, `Legacy Machines`
- **Protocols:** LoRaWAN, Zigbee, BLE, Modbus, CAN, Serial, LwM2M

---

## 🔧 Technology Stack

| Area              | Technologies |
|-------------------|--------------|
| Runtime           | Rust, Spin, wasmEdge, Actix |
| ML Inference      | TVM, ONNX Runtime, TFLite |
| Protocols         | QUIC, MQTT, WebTransport, CoAP, HTTP/2 |
| Caching & Storage | QuasarCache, RocksDB, RedisEdge |
| Messaging         | NATS, ZeroMQ, Kafka |
| Gateway Layer     | Envoy, Nimbus, Mosquitto |
| Security          | Vault, TPM, OPA, Secure Boot |
| Monitoring        | Grafana, Prometheus, Loki |
| CI/CD & Ops       | GitOps, ArgoCD, OpenTelemetry |

---

## 📦 Use Cases

- 🏭 **Smart Manufacturing:** Predictive maintenance, edge AI control loops
- 🛍️ **Retail & Banking:** Personalized experience at the edge, secure transaction hubs
- 🚛 **Logistics:** Fleet telemetry, route optimization, secure offline sync
- 🏥 **Healthcare:** On-device diagnostics, secure data sync, MDM enforcement
- 🌆 **Smart Cities:** Sensor fusion, real-time surveillance, distributed intelligence

---

## 🚀 Quick Start

```bash
# Clone the repo
git clone https://github.com/veeringman/veer-edge-platform.git
cd veer-edge-platform

# Build the core edge gateway (requires Rust & Cargo)
cargo build --release

# Launch Edge Gateway Node
./target/release/veer_edge
```

---

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## 🤝 Contributing

We welcome community contributions! Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) guide and open a PR or issue.

---

## ✨ Credits

Veer Edge is built as part of a next-gen edge innovation initiative, combining the best of modern networking, security, and AI at the edge.
