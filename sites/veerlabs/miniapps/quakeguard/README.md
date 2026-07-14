# 🌍 QuakeGuard – AI-Powered Earthquake Resilience System

**QuakeGuard** is an IoT + Edge-AI based system to assess and monitor the earthquake proofness of buildings in real-time. It combines affordable sensors, edge devices, and a mesh network to enhance building safety and disaster preparedness.

## 📦 Key Components

- 📡 **Firmware**: Sensor fusion + anomaly detection (ESP32)
- 🧠 **Edge Node**: Rust-based node for aggregation + alert
- 🔗 **Mesh**: Decentralized LoRa/NB-IoT network
- 📱 **Mobile UI**: Health index, diagnostics, and alerts
- 🧪 **Simulator**: Hands-on testbed for seismic effects

## 🔧 Architecture Overview

The QuakeGuard system is composed of five major layers:

1. **Sensor Layer**: Includes MPU6050 accelerometers, strain gauges, piezoelectric sensors, and acoustic sensors installed across key structural points of the building.
2. **Firmware Layer**: Runs on ESP32/STM32 microcontrollers. Handles data collection, filtering (FFT/threshold), local anomaly detection, and communication logic.
3. **Edge Node Layer**: A Rust-based processing unit that aggregates data from multiple buildings, manages health scores, and forwards alerts to the cloud or local dashboards.
4. **Mesh Network Layer**: Powered by LoRa/NB-IoT for low-power, peer-to-peer communication and community-level tremor validation.
5. **Application Layer**: Mobile/web UI for viewing real-time data, historical trends, risk assessment scores, and emergency notifications.

![QuakeGuard Architecture](./docs/quakeguard_advanced_architecture.png)

## 🏠 Deployment Diagram

The deployment layout shows placement of sensors (accelerometer, strain gauge, acoustic, vibration) on critical load-bearing parts of a building. Edge nodes handle initial processing and communicate via LoRa mesh to ensure decentralized coverage.

![Deployment Diagram](./docs/quakeguard_deployment.png)

## 🧪 Physical Simulator Setup

We also provide a physical earthquake simulation platform. It includes tectonic plates powered by a stepper motor base, mini-structures mounted on flexible ground material, and sensor nodes embedded to mimic real-world stress scenarios. This setup helps in testing algorithms and education.

![Simulator Diagram](./docs/quakeguard_simulator.png)

## 🚀 Roadmap

- [x] Project Scaffolding
- [ ] Firmware core loop
- [ ] Mesh message protocol
- [ ] Edge-to-cloud sync
- [ ] Mobile app dashboard

## 📄 License

[MIT](./LICENSE)

