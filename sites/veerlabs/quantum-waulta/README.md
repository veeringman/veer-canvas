# Waulta (Quantum Waulta)

> **Quantum Waulta** — Future-proof your keys with quantum-grade security  
> *(branded “Waulta” throughout docs and tooling)*

---

## 🔎 Detailed Description

**Quantum Waulta** (branded throughout as **Waulta**) is a next-generation, open-source hardware wallet designed to “future-proof your keys with quantum-grade security.” At its core is an ESP32 microcontroller paired with a Microchip ATECC608A secure element, running a Rust-based firmware stack under FreeRTOS (or async Rust). All HD-wallet, PSBT, and crypto-chip logic lives in a single shared crate—`waulta-core`—so every client (CLI, desktop GUI, mobile app, or WebAssembly UI) embeds the exact same battle-tested wallet engine.

### Key Pillars

1. **End-to-End Security**  
   - **Secure Element**: ATECC608A stores private keys, performs BIP32 key-derivation and ECDSA signing inside tamper-resistant hardware.  
   - **ESP32 Protections**: Secure Boot, Flash Encryption, hardware RNG, and optional pin-strap to disable JTAG in production.  

2. **Deterministic Wallet Architecture**  
   - **BIP32 HD Wallets**: One seed phrase → unlimited address tree → single backup for all your coins.  
   - **PSBT (BIP174)**: Standardized, multi-party transaction format—perfect for multisig, coinjoin, and host-wallet workflows.  

3. **Rust-Native Ecosystem**  
   - **`waulta-core`**: Unified Rust library for wallet logic, CP interface, and UI flows—no duplication across platforms.  
   - **Host Clients**:  
     - **CLI**: Scripting, batch PSBT signing, and automation.  
     - **Desktop GUI**: Rich Rust GUI via Tauri, egui or Slint.  
     - **Mobile App**: On-the-go balance & send via Dioxus Mobile or Slint.  
     - **Web (WASM)**: Self-hostable static SPA running `waulta-core` in the browser.

4. **Offline-First, Zero-Backend**  
   - All clients link directly into `waulta-core`—there is no central server.  
   - True offline operation: generate addresses, sign PSBTs, and review transaction history without any network dependency.  

5. **Modular & Extensible**  
   - Firmware layers: HAL → Crypto Interface → Wallet Core → App Logic → Device I/O.  
   - Clean separation enables:  
     - Adding new coins (ed25519, BLS, post-quantum)  
     - Switching display/UI engines  
     - Integrating alternative secure elements  

### Use Cases

- **Personal Security**: Keep your Bitcoin, Ethereum, and ERC-20 tokens safe on a hardware wallet you fully control.  
- **Multisig & CoinJoin**: Collaborate with friends or organizations to build and co-sign transactions via PSBT.  
- **Open-Source Auditing**: Review and contribute to every line of Rust, from the key-derivation core to the mobile UI.  
- **Offline Workflows**: Build transactions on an air-gapped laptop, sign them on Waulta, then broadcast from a separate machine.

---

By combining a hardened secure element, a modern Rust codebase, a truly offline design, and a wide range of client interfaces, **Quantum Waulta** delivers a hardware-wallet experience that’s both cutting-edge and trustworthy—ready for today’s threats and tomorrow’s quantum challenges.  

---

## 🚀 Features

- **Hierarchical Deterministic (BIP32)** key management  
- **PSBT (BIP174)** support for safe, multi-party transaction signing  
- **Secure key storage** in ATECC608A crypto co-processor  
- **ESP32-based firmware** with Secure Boot & Flash Encryption  
- **Rust-native host apps**:  
    - **CLI** for scripting and automation  
    - **Desktop GUI** (Tauri / egui / Slint)  
    - **Mobile App** (Dioxus Mobile / Slint)  
- **USB CDC-ACM** & **BLE GATT** transports  
- Modular, layered code: HAL → Crypto Interface → Wallet Core → App Logic  

---

## 📂 Repository Layout

    waulta/
    ├── .github/
    │   └── workflows/ci.yml
    ├── docs/
    │   ├── architecture.md
    │   ├── getting_started.md
    │   └── CONTRIBUTING.md
    ├── firmware/
    │   ├── .cargo/config.toml
    │   ├── Cargo.toml
    │   └── src/
    │       ├── main.rs
    │       └── atecc.rs
    ├── host/
    │   ├── cli/            # Rust CLI tool
    │   │   ├── Cargo.toml
    │   │   └── src/main.rs
    │   ├── app-desktop/    # Rust desktop GUI (e.g. Tauri or Slint)
    │   │   ├── Cargo.toml
    │   │   └── src/main.rs
    │   └── app-mobile/     # Rust mobile app (e.g. Dioxus Mobile or Slint)
    │       ├── Cargo.toml
    │       └── src/main.rs
    ├── examples/
    │   └── sign_demo/      # CLI example for PSBT signing
    │       └── README.md
    ├── scripts/
    │   └── setup.sh        # scaffolding script
    ├── LICENSE
    └── README.md

---

## 🛠️ Getting Started

### 1. Clone & Scaffold

    git clone https://github.com/your-org/quantum-waulta.git
    cd quantum-waulta
    bash scripts/setup.sh

### 2. Build Firmware

    cd firmware
    cargo build

### 3. Build & Run CLI

    cd ../host/cli
    cargo build && cargo run -- --help

### 4. Build & Run Desktop GUI

    cd ../host/app-desktop
    # if using Tauri:
    cargo tauri dev
    # or, for Slint/egui:
    cargo run

### 5. Build & Run Mobile App

    cd ../host/app-mobile
    # Dioxus Mobile example:
    # iOS
    cargo dioxus run --target x86_64-apple-ios
    # Android
    cargo dioxus run --target aarch64-linux-android

_For full details and troubleshooting see [docs/getting_started.md](docs/getting_started.md)._

---

## 🔍 Architecture

- **Firmware (ESP32):**  
    - HAL → Crypto Interface (ATECC608A) → Wallet Core (BIP32, PSBT) → Application Logic (UI flow)

- **Host (Rust):**  
    - **CLI:** `waulta-cli` – terminal & scripting  
    - **Desktop GUI:** `waulta-desktop` – Rust + Tauri/egui/Slint  
    - **Mobile App:** `waulta-mobile` – Rust + Dioxus Mobile/Slint  

- **Transport:** USB CDC-ACM & BLE GATT carry PSBT payloads

![Software Architecture](docs/architecture.md)

---

## 📖 Examples

### PSBT Signing Demo (CLI)

    cd examples/sign_demo
    cargo run --example sign

---

## 🤝 Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for:

- Issue & PR guidelines  
- Coding standards  
- Testing & CI requirements  

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
