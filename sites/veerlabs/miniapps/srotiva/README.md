<p align="left">
  <img src="brand/png/srotiva-logo-lockup.png#gh-light-mode-only" alt="Srotiva" width="480" />
  <img src="brand/png/srotiva-logo-lockup-on-dark.png#gh-dark-mode-only" alt="Srotiva" width="480" />
</p>

### Intelligent Media Infrastructure by VeerLabs

Srotiva is a high-performance, provider-neutral media infrastructure platform for **ingesting, processing, storing, streaming, and intelligently delivering digital media**.

It is designed to provide a common media layer for applications such as **WiseEars**, **WiseEars Chronicle**, web and mobile chat platforms, social/community applications, and future VeerLabs products.

> **Capture. Process. Stream. Deliver.**

---

## Vision

Modern applications increasingly depend on rich media, but every application should not have to independently solve:

* Large-file uploads
* Resumable and multipart uploads
* Video transcoding
* Adaptive bitrate streaming
* Audio processing
* Image optimization
* Thumbnail generation
* Media metadata
* Object storage
* CDN delivery
* Secure media access
* Edge caching
* Intelligent prefetching
* Media lifecycle management
* Media analytics
* AI-powered media processing

**Srotiva provides this infrastructure as a reusable platform.**

Applications interact with Srotiva through APIs and SDKs while Srotiva handles the underlying media lifecycle.

---

## Why Srotiva?

A conventional application often looks like:

```text
Application
    │
    ├── Upload service
    ├── File storage
    ├── FFmpeg
    ├── Video streaming
    ├── CDN integration
    ├── Thumbnail service
    ├── Access control
    └── Media metadata
```

Srotiva consolidates these capabilities into a dedicated media layer:

```text
                    Application
                         │
                    Srotiva API
                         │
             ┌───────────┼───────────┐
             │           │           │
           Ingest     Process      Deliver
             │           │           │
             ▼           ▼           ▼
          Storage     Workers       CDN
                         │
                   Media Pipeline
```

This allows application developers to focus on their product instead of rebuilding media infrastructure.

---

# Core Capabilities

## Media Ingest

Srotiva will support reliable media ingestion from web, mobile, backend and eventually live sources.

Planned capabilities:

* Direct uploads
* Multipart uploads
* Resumable uploads
* Upload sessions
* Upload progress
* Large media files
* Background uploads
* Signed upload URLs
* Client-side upload SDKs
* Live media ingest

---

## Media Processing

Uploaded media can be processed asynchronously through a scalable worker architecture.

Planned processing capabilities include:

* Video transcoding
* Audio transcoding
* Codec conversion
* Resolution generation
* Bitrate optimization
* Thumbnail generation
* Poster frames
* Waveform generation
* Metadata extraction
* Audio normalization
* Image optimization
* Media validation
* Content inspection

FFmpeg will initially be supported as a primary processing engine, while the architecture will remain extensible for GPU and specialized media processors.

---

## Adaptive Streaming

Srotiva is designed around modern adaptive media delivery.

Initial focus:

* HLS
* MPEG-DASH
* Multiple renditions
* Adaptive bitrate selection
* Segment-based delivery
* Fast startup
* Playback buffering
* CDN caching
* Signed playback URLs

Example:

```text
Original Video
      │
      ▼
   Encoder
      │
 ┌────┼──────────────┐
 ▼    ▼              ▼
360p  720p          1080p
 │     │              │
 └─────┼──────────────┘
       ▼
   HLS / DASH
       │
       ▼
      CDN
       │
       ▼
    Client
```

---

## Intelligent Delivery

Fast playback is not only a CDN problem.

Srotiva will combine:

* CDN delivery
* edge caching
* adaptive bitrate streaming
* playback-aware buffering
* viewport awareness
* intelligent prefetching
* media prioritization
* network-aware delivery

The goal is to make media **feel instantaneous**.

For example, a chat application can identify that a video is approaching the user's viewport and begin retrieving its initial segments before playback begins.

```text
User scrolling
      │
      ▼
Video approaches viewport
      │
      ▼
Prefetch first segments
      │
      ▼
Video enters viewport
      │
      ▼
Immediate playback
```

---

# Media as a First-Class Resource

Srotiva will treat media as a platform resource rather than simply a file.

A media asset may contain:

```text
Media Asset
│
├── Identity
├── Owner
├── Access Policy
├── Original Asset
├── Renditions
├── Metadata
├── Thumbnails
├── Streaming Manifests
├── Processing State
├── Lifecycle Policy
└── Analytics
```

Example conceptual resource:

```json
{
  "id": "med_01J...",
  "type": "video",
  "status": "ready",
  "duration": 42.7,
  "width": 1920,
  "height": 1080,
  "content_type": "video/mp4",
  "streaming": {
    "hls": true,
    "dash": true
  }
}
```

---

# Architecture

Srotiva is a **four-plane media fabric**. CMAF is the canonical atom. HLS, DASH, and MoQ are views. Intelligence is a pipeline node, not a sidecar.

Full design: [`docs/architecture.md`](docs/architecture.md)

```text
┌─────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE                            │
│     API · catalog · policy · jobs · tenants · capabilities      │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────────┐
│        DATA PLANE         │   │        INTELLIGENCE PLANE       │
│ ingest · CAS · encode     │   │ transcribe · embed · scene      │
│ CMAF package · origin     │   │ classify · summarize            │
└─────────────┬─────────────┘   └────────────────┬────────────────┘
              │                                  │
              └──────────────┬───────────────────┘
                             ▼
              ┌──────────────────────────────┐
              │         EDGE PLANE           │
              │ MoQ relay · LL-HLS origin    │
              │ authz · ABR · prefetch       │
              └──────────────────────────────┘
```

### Architectural principles

#### Provider Neutral

Srotiva should not be tightly coupled to a particular cloud provider.

Storage, CDN, compute and processing engines should be abstracted behind provider interfaces.

Potential implementations:

* AWS
* Cloudflare
* S3-compatible storage
* Self-hosted infrastructure
* Kubernetes
* Future VeerLabs infrastructure

#### API First

Every major platform capability should be available through a stable API.

#### Asynchronous by Default

Expensive operations such as transcoding and media analysis should execute through background workers.

#### Edge Friendly

Media delivery should be optimized for geographically distributed edge infrastructure.

#### Secure by Default

Media should never be assumed to be publicly accessible.

Signed URLs, authorization policies and expiration mechanisms should be first-class capabilities.

#### Observable

Every major media operation should produce structured events, metrics and traces.

#### Extensible

Processing engines, storage providers, CDN providers and codecs should be replaceable.

---

# Proposed Repository Structure

```text
srotiva/
│
├── README.md
├── Cargo.toml
├── docs/architecture.md
│
├── crates/
│   ├── srotiva-core/            # IDs, kinds, lifecycle
│   ├── srotiva-media/           # catalog / asset graph
│   ├── srotiva-storage/         # content-addressed blobs
│   ├── srotiva-authz/           # capability tokens
│   ├── srotiva-pipeline/        # processing DAG
│   ├── srotiva-ingest/          # TUS / WHIP / MoQ doors
│   ├── srotiva-transcode/       # ladders + encoder adapters
│   ├── srotiva-stream/          # CMAF, HLS, DASH, MoQ views
│   ├── srotiva-intelligence/    # transcript, embed, scene
│   ├── srotiva-edge/            # prefetch + ABR
│   ├── srotiva-worker/          # job runtime
│   ├── srotiva-observe/         # tracing
│   ├── srotiva-api/             # control plane HTTP
│   ├── srotiva-controld/        # control plane process
│   └── srotiva-workerd/         # worker process
│
├── brand/
└── tests/
```

The exact workspace structure may evolve as the architecture matures.

---

# Technology Direction

Srotiva is intended to be **Rust-first**.

Initial technology direction:

| Layer          | Technology                       |
| -------------- | -------------------------------- |
| Core           | Rust                             |
| Async Runtime  | Tokio                            |
| HTTP/API       | Axum                             |
| Serialization  | Serde                            |
| Identity       | ULID (`med_`, `ten_`, `job_`)    |
| Content store  | BLAKE3 CAS behind object adapters |
| Catalog        | PostgreSQL (memory in Phase 0)   |
| Canonical media| CMAF fragment graph              |
| VOD delivery   | LL-HLS / MPEG-DASH               |
| Live fabric    | WHIP ingest → MoQ + LL-HLS       |
| Processing     | Declarative DAG; FFmpeg / HW     |
| Authz          | Attenuable capability tokens     |
| Queue          | Pluggable (memory → NATS)        |
| Cache          | Redis-compatible abstraction     |
| Edge           | WASM-portable decisioning        |
| Observability  | OpenTelemetry                    |
| SDKs           | Rust / TypeScript / React Native |

These are architectural starting points, not permanent dependencies.

---

# Application Integration

Srotiva is intended to become a shared infrastructure service across VeerLabs products.

### WiseEars

```text
WiseEars
   │
   ├── Meeting recordings
   ├── Audio
   ├── Video
   ├── Generated media
   └── Chronicle recordings
          │
          ▼
       Srotiva
```

### Chat Platforms

Instead of routing large media files through the chat application server:

```text
Client
  │
  ├──────────────► Srotiva
  │                  │
  │                  ├── Storage
  │                  ├── Processing
  │                  └── CDN
  │
  └──────────────► Chat API
                     │
                     └── media_id
```

The chat message can therefore remain lightweight:

```json
{
  "type": "video",
  "media_id": "med_01J...",
  "poster": "...",
  "duration": 37.4
}
```

---

# Security

Security is a foundational requirement.

Srotiva will support:

* Authentication
* Authorization
* Tenant isolation
* Media ownership
* Signed upload URLs
* Signed playback URLs
* URL expiration
* Access policies
* Encryption in transit
* Encryption at rest
* Audit events
* Secure deletion
* Rate limiting
* Abuse protection

Srotiva should never expose storage credentials to client applications.

---

# Multi-Tenancy

Srotiva is intended to support multiple applications and tenants.

Conceptually:

```text
Srotiva
│
├── Tenant A
│   ├── Media
│   ├── Policies
│   └── Storage
│
├── Tenant B
│   ├── Media
│   ├── Policies
│   └── Storage
│
└── Tenant C
    ├── Media
    ├── Policies
    └── Storage
```

Isolation must exist at the API, metadata, authorization and storage layers.

---

# Roadmap

## Phase 0 — Foundation

* [x] Repository initialization
* [x] Rust workspace
* [x] Core domain model
* [x] Media resource model
* [x] API conventions
* [x] Configuration system
* [x] Logging and tracing
* [x] Architecture documentation

## Phase 1 — Media Storage

* [ ] Object storage abstraction
* [ ] Local development storage
* [ ] S3-compatible storage
* [ ] Media upload API
* [ ] Multipart upload
* [ ] Resumable uploads
* [ ] Media metadata
* [ ] Secure media URLs

## Phase 2 — Processing

* [ ] Processing job model
* [ ] Worker framework
* [ ] FFmpeg integration
* [ ] Video transcoding
* [ ] Audio transcoding
* [ ] Thumbnail generation
* [ ] Metadata extraction
* [ ] Rendition management

## Phase 3 — Streaming

* [ ] HLS generation
* [ ] MPEG-DASH generation
* [ ] Adaptive bitrate profiles
* [ ] Segment storage
* [ ] Signed playback
* [ ] CDN integration
* [ ] Playback optimization

## Phase 4 — Intelligent Delivery

* [ ] Client playback telemetry
* [ ] Viewport-aware prefetch
* [ ] Predictive prefetch
* [ ] Network-aware quality selection
* [ ] Edge-aware routing
* [ ] Cache optimization

## Phase 5 — Media Intelligence

* [ ] Speech-to-text integration
* [ ] Media embeddings
* [ ] Semantic media search
* [ ] Scene detection
* [ ] Content classification
* [ ] AI-generated metadata
* [ ] Media summarization

## Phase 6 — Realtime Media

* [ ] Live ingest
* [ ] Live transcoding
* [ ] Low-latency streaming
* [ ] WebRTC integration
* [ ] Realtime media events
* [ ] Live recording

---

# Design Philosophy

Srotiva should make media infrastructure feel boring to application developers.

The developer should be able to say:

```text
Upload media.
```

and not have to think about:

```text
multipart uploads
      ↓
object storage
      ↓
transcoding
      ↓
renditions
      ↓
manifests
      ↓
segments
      ↓
CDN
      ↓
signed URLs
      ↓
adaptive playback
```

Srotiva handles the complexity.

---

# Project Status

**Status:** Phase 0 — fabric foundation

The control plane, catalog, CAS, pipeline DAG, capabilities, and in-memory runtime compile and test locally. Provider adapters, FFmpeg, origin, and MoQ relays are the next phases.

```text
cargo test --workspace
cargo run -p srotiva-controld
# GET  http://127.0.0.1:8080/healthz
# POST http://127.0.0.1:8080/v1/media   {"kind":"video"}
```

APIs, storage models, processing interfaces and implementation details will continue to evolve.

---

# License

License details will be established as part of the project governance and repository initialization.

---

## About VeerLabs

**Srotiva is a VeerLabs project.**

VeerLabs builds software platforms and infrastructure focused on intelligent, secure and scalable digital systems.

---

> **Srotiva**
> *Intelligent Media Infrastructure by VeerLabs*
