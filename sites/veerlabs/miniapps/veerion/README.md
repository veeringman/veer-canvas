<img src="assets/veerion_logo.png" alt="Veerion Logo" width="180" style="display:block;margin:0 0 24px 0;padding:0;"/>

Veerion is a new web browser. Built ground-up in Rust. Owing nothing to anyone.

It is not a Chromium fork, a WebKit port, a Gecko skin, a Servo derivative, an Electron wrapper, or a CEF shell. Every layer — networking, TLS, HTTP/3, HTML/CSS parser, DOM, style, layout, paint, compositor, GPU pipeline, text shaping, media decode, JavaScript engine, web platform APIs, UI shell, extension model, and AI agent runtime — is designed and implemented from scratch in safe Rust.

This is the documentation baseline for that build.

## Vision

A browser that changes everything again.

For thirty years the web has run on a small set of aging C++ engines whose architecture was set before mobile, before the cloud, and long before AI. Veerion is a clean-sheet rewrite of what the browser is and what it is for: a memory-safe, multi-process, capability-governed runtime for the AI-native web — designed for a world where the browser hosts not just pages, but agents that act on the user's behalf.

There is no comparable product. There is nothing to match. This is the new baseline.

## Mission

Build the world's first AI-native, memory-safe, capability-secure web browser — a ground-up Rust implementation that treats every page, extension, and agent as an untrusted workload, isolates it by default, and governs it with explicit, revocable, user-granted capabilities.

## Problem

Today's browsers were designed to render documents, not to host autonomous AI agents, tool-using assistants, and untrusted generated code. They are also built on decades-old C++ engines whose attack surface is enormous. Users face:

- Weak isolation between tabs, extensions, and agent actions
- Implicit, coarse-grained permissions (one prompt, forever)
- No standard way to run AI agents securely inside the browser
- Limited auditability of what code did on the user's behalf
- A massive memory-unsafe TCB (trusted computing base) inherited from existing engines

## Solution Summary

Veerion is a full, ground-up browser whose differentiator is a memory-safe engine and a secure runtime core:

- 100% Rust implementation; no third-party browser engine code
- Multi-process architecture: UI process, per-site renderer processes, network process, GPU/compositor process
- Custom Rust HTML/CSS parser, DOM, style/layout, paint, and compositor
- Custom Rust JavaScript engine (ECMAScript subset first, expanding over time)
- Per-tab sandboxed runtime sessions, not just render processes
- WASM-first execution layer for extensions, agents, and untrusted code
- Capability-based, per-site and per-agent permissions
- Optional microVM isolation for high-risk sites and agent workloads
- Built-in AI agent runtime with auditable, revocable tool use
- Ephemeral, disposable browsing sessions as a first-class mode

## Non-Goals

- No reuse of Chromium, Blink, WebKit, Gecko, Servo, V8, SpiderMonkey, JavaScriptCore, Skia, ANGLE, Electron, CEF, or any other existing browser/engine codebase
- No language other than Rust for first-party engine and runtime code (build tooling and platform glue excepted)
- No proprietary or non-standard web platform extensions in MVP; we implement standards, not divergent dialects

## Documentation Index

- [docs/product-requirements.md](docs/product-requirements.md) - product scope, user personas, use cases, and MVP requirements.
- [docs/system-architecture.md](docs/system-architecture.md) - platform architecture, services, execution lifecycle, and interfaces.
- [docs/security-model.md](docs/security-model.md) - threat model, trust boundaries, policy model, and security controls.
- [docs/implementation-roadmap.md](docs/implementation-roadmap.md) - phased delivery plan, milestones, dependencies, and Definition of Done.

## Proposed Repository Layout

```text
/docs
    product-requirements.md
    system-architecture.md
    security-model.md
    implementation-roadmap.md
/crates
    veerion-shell           # UI process: windows, tabs, address bar, settings (Rust + GPU UI toolkit)
    veerion-net             # networking process: DNS, TLS, HTTP/1.1/2/3, QUIC, WebSocket, cache
    veerion-html            # HTML5 tokenizer + tree construction
    veerion-css             # CSS parser, selector matcher, cascade
    veerion-dom             # DOM tree, events, mutation, traversal
    veerion-style           # style resolution, computed values, inheritance
    veerion-layout          # box tree, fragment tree, block/inline/flex/grid
    veerion-paint           # display list, painting primitives
    veerion-gfx             # GPU abstraction (wgpu-backed) and software fallback
    veerion-compositor      # layer tree, rasterization, present
    veerion-text            # font loading, shaping, line breaking, BiDi
    veerion-media           # image/audio/video decoders (Rust-native), MSE/EME later
    veerion-js              # JavaScript engine: parser, bytecode, interpreter, GC, JIT (later)
    veerion-webapi          # web platform APIs (Fetch, Storage, WebSockets, Workers, etc.)
    veerion-runtime         # per-tab runtime session abstraction
    veerion-orchestrator    # process and lifecycle orchestration
    veerion-wasm            # WASM execution for extensions/agents/tools
    veerion-vmm             # microVM backend for high-risk profiles
    veerion-security        # policy engine, capability broker, audit, sandboxing
    veerion-agent           # in-browser AI agent runtime
    veerion-sdk             # extension/agent developer APIs
/examples
/third_party                # platform glue only (OS, GPU drivers, fonts); NO browser engines
```

## Guiding Principles

- The browser is the product; we own the engine end to end
- Pure Rust, memory-safe by default; `unsafe` is rare, isolated, and reviewed
- Multi-process, sandboxed-by-default architecture
- Every tab is a sandboxed runtime session, not just a render surface
- Least-privilege, per-site and per-agent capabilities by default
- Ephemeral-by-default browsing and agent sessions
- WASM-first execution substrate for non-page code
- Standards compliance over invention; we follow the web platform specs
- Transparent, auditable AI agent actions
- User control over data, identity, and trust at all times

## Current Status

Documentation baseline established. Next step is to scaffold the Phase 0 implementation workspace: Cargo workspace, multi-process skeleton, and the first end-to-end "hello page" path through our own HTML/CSS/layout/paint pipeline.
