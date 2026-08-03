<p align="center">
  <img src="assets/veero.png" alt="Veero Logo" width="220">
</p>

<p align="center">
    <strong>Build Native. Everywhere.</strong>
</p>

<p align="center">

A next-generation Rust-native application framework for building beautiful, secure, AI-native mobile applications across every major platform from a single codebase.

</p>

---

## Vision

Veero is not another cross-platform framework.

It is a **Universal Native Application Platform** built from the ground up in Rust.

Modern mobile development has become fragmented.

- Different languages
- Different UI frameworks
- Different tooling
- Different design systems
- Different networking stacks

Veero unifies the entire application stack into one cohesive developer experience while preserving truly native user experiences.

Our goal is simple:

> **Write once. Feel native everywhere.**

---

# Why Veero?

Existing frameworks usually compromise one of these:

- Performance
- Native look and feel
- Developer productivity
- Safety
- Binary size
- AI integration

Veero is designed to optimize all of them.

---

# Core Principles

- Rust Native
- Native by Design
- GPU Accelerated
- AI First
- Offline First
- Secure by Default
- Zero JavaScript Runtime
- Zero Reflection
- Memory Safe
- High Performance
- Beautiful Developer Experience

---

# Features

## Native Rendering

Modern GPU accelerated rendering engine.

- Metal
- Vulkan
- OpenGL ES
- Future WebGPU support

No HTML.

No WebView.

No JavaScript runtime.

---

## Declarative UI

Modern declarative widgets inspired by the best ideas from SwiftUI, Jetpack Compose and Flutter.

```rust
App::new()
    .window(|| {
        Column::new()
            .child(Text::new("Hello Veero"))
            .child(Button::new("Continue"))
    });
```

---

## Rust Everywhere

Everything is written in Rust.

- UI
- Networking
- Storage
- Async runtime
- Animations
- State management
- Rendering
- Plugins

One language.

One ecosystem.

---

## AI Native

AI is a first-class citizen.

Built-in support for

- Chat interfaces
- Speech recognition
- Speech synthesis
- Streaming LLM responses
- Embeddings
- Tool Calling
- Local AI models
- Cloud AI providers

---

## Modern State Management

Reactive programming without boilerplate.

- Signals
- Observable state
- Async state
- Dependency injection
- Time travel debugging

---

## Navigation

Modern routing system.

- Stack navigation
- Nested navigation
- Deep links
- Universal links
- Route guards
- Type-safe routing

---

## Networking

Production-ready networking.

- HTTP/1
- HTTP/2
- HTTP/3
- GraphQL
- gRPC
- WebSockets
- Server-Sent Events

---

## Storage

Unified APIs.

- SQLite
- Secure Storage
- Preferences
- File APIs
- Encrypted databases

---

## Animation Engine

Rich GPU accelerated animations.

- Springs
- Physics
- Shared transitions
- Blur
- Glass effects
- Particle systems
- Custom shaders

---

## Accessibility

Accessibility by default.

- Screen readers
- Dynamic fonts
- High contrast
- RTL
- Keyboard navigation
- Localization

---

# Supported Platforms

| Platform | Status |
|----------|--------|
| Android | Planned |
| iOS | Planned |
| HarmonyOS NEXT | Planned |
| Wear OS | Planned |
| watchOS | Planned |
| visionOS | Planned |
| Android TV | Planned |
| tvOS | Planned |
| Embedded Linux | Planned |

---

# Architecture

```
Application
      │
      ▼
Reactive Widget Tree
      │
      ▼
Layout Engine
      │
      ▼
Rendering Engine
      │
      ▼
GPU Backend
      │
      ▼
Platform Layer
      │
 ┌────┴─────────────┐
 │                  │
Android          iOS
 │                  │
HarmonyOS     Future Platforms
```

---

# Project Structure

```
veero/

├── crates/
│   ├── veero-ui
│   ├── veero-runtime
│   ├── veero-renderer
│   ├── veero-layout
│   ├── veero-animation
│   ├── veero-navigation
│   ├── veero-storage
│   ├── veero-network
│   ├── veero-ai
│   ├── veero-cli
│   ├── veero-devtools
│   └── veero-testing
│
├── examples/
├── templates/
├── docs/
├── tools/
└── sdk/
```

---

# Developer Experience

A single CLI powers everything.

```bash
veero new hello_app

veero run android

veero run ios

veero test

veero doctor

veero package

veero publish
```

---

# Hot Reload

Designed for rapid iteration.

- Instant reload
- Stateful reload
- Live UI editing
- Performance overlays

---

# Security

Built with security as a foundation.

- Rust memory safety
- Secure storage
- Certificate pinning
- Secure networking
- Sandboxed plugins
- Signed packages

---

# Performance Goals

- Native startup speed
- 120 FPS rendering
- Small binaries
- Minimal memory usage
- Fast incremental builds
- Predictable performance

---

# Long-Term Roadmap

## Phase 1

Core runtime

Rendering engine

Widget system

Android

iOS

CLI

---

## Phase 2

DevTools

Animations

Accessibility

Plugin SDK

Hot Reload

---

## Phase 3

AI Framework

Offline sync

Cloud services

Visual designer

---

## Phase 4

Desktop

Embedded

XR

Automotive

Cloud deployment

---

# Philosophy

Veero is not trying to imitate existing frameworks.

It is designed to rethink how modern native applications should be built in the AI era.

Rather than wrapping native SDKs or embedding a browser engine, Veero provides a unified Rust-native runtime that delivers consistent developer productivity without sacrificing native performance or user experience.

---

# Open Source

Veero is an open-source project developed by **VeerLabs**.

We believe the future of application development should be:

- Open
- Secure
- Fast
- Native
- AI-powered

---

# License

Apache-2.0 OR MIT

---

## Build Native. Everywhere.
