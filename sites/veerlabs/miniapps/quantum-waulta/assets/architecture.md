# Waulta Product & Project Architecture

> This document describes the end-to-end architecture of **Waulta** (“Quantum Waulta”), covering both software and hardware components for a fully offline-capable, open-source setup.

---

## 📐 Overview

Waulta is a hardware-wallet solution based on an ESP32 microcontroller paired with an ATECC608A crypto co-processor. All core wallet logic (BIP32 key derivation, PSBT parsing/signing, device I/O) lives in a single Rust crate (`waulta-core`). Four “thick” client applications (CLI, Desktop, Mobile, Web WASM) link directly against `waulta-core`, eliminating the need for any backend.

---

## 🖥️ Application Architecture

    +--------------+      +---------------+
    |   CLI App    |      |   Web (WASM)  |
    +--------------+      +---------------+
           \                    /
            →   waulta-core   ←
           /                    \
    +--------------+      +--------------+
    | Desktop App  |      |  Mobile App  |
    +--------------+      +--------------+

- **waulta-core**: shared Rust library providing:
  - BIP32 (HD wallets)  
  - PSBT (Partially Signed Bitcoin Transactions)  
  - Crypto-chip interface (wake, sign, derive)  
- **CLI App**: Terminal tool for scripting, backups, batch signing  
- **Desktop App**: Rust GUI (Tauri / egui / Slint)  
- **Mobile App**: Rust mobile UI (Dioxus Mobile / Slint)  
- **Web (WASM)**: Browser-based SPA loading `waulta-core` via WebAssembly  

---

## 🔧 Hardware Architecture

    +----------------------+     I²C     +---------------------------+
    | ESP32 Microcontroller|<----------->|  ATECC608A Crypto         |
    |  • Secure Boot       |             |    Co-processor           |
    |  • Flash Encryption  |             +---------------------------+
    +----------------------+
            │
            │ SPI / I²C / GPIO
            ▼
    +----------------------+
    |     UI Layer         |
    |  • OLED Display      |
    |  • Buttons / Encoder |
    +----------------------+
            │
            │ USB CDC-ACM / BLE GATT
            ▼
    +----------------------+
    |   Host Devices       |
    |  • PC / Desktop      |
    |  • Mobile Phone      |
    +----------------------+

- **ESP32** runs FreeRTOS (or async Rust) with Secure Boot & Flash Encryption enabled.  
- **ATECC608A** handles all private-key operations: secure storage, ECDSA signing, BIP32 derivation, RNG.  
- **UI Layer** provides address display, transaction review, and user confirmation via buttons.  
- **Host Communication** uses USB CDC-ACM or BLE GATT to transport PSBTs/APDUs to/from clients.

---
