<p align="center">
  <img src="assets/logo/veersetu-logo.svg" alt="VeerSetu" width="640"/>
</p>

<h3 align="center">Zero-trust edge fabric for secure remote access, service publishing, and private networking.</h3>

<p align="center">
  <em>Zero-trust connectivity for the agentic era — post-quantum, programmable, self-hosted.</em>
</p>

---

**VeerSetu** is a programmable zero-trust edge fabric written in Rust. It securely connects humans, devices, services, and AI agents across any network — without exposing ports, without trusting the LAN, and without locking you into a SaaS.

It unifies what is today a sprawl of disjoint tools — VPN, reverse tunnel, mesh, ZTNA gateway, identity proxy, service publishing, MCP gateway — into a single identity-aware, post-quantum, programmable fabric.

## What makes it different

| Pillar | What you get |
|---|---|
| **Post-quantum identity** | PQ-hybrid handshake (X25519 + ML-KEM), capability tokens (Biscuit), DIDs / Verifiable Credentials, continuous hardware attestation. |
| **Programmable edge** | Ship signed WASM modules that run *at your own gateway* — custom auth, transforms, edge functions. Cloudflare Workers semantics on your hardware. |
| **AI-native** | `agent:` is a first-class principal. MCP gateway with per-tool capability scoping. Inference router across local → relay GPU → cloud. |
| **Local-first** | CRDT-based control plane. Agents keep working when the cloud doesn't. Federated deployments peer with each other. |
| **Verifiable trust** | Sigstore-style transparency log. SLSA L3+ reproducible builds. Differential-privacy telemetry. |

## Status

Pre-alpha. Vision and architecture are stabilising; engineering scaffolding is underway.

Current infrastructure milestones:

- control-plane overlay lease and route advertisement APIs are live;
- native host route backends are available for Linux (`linux-netlink`), Windows (`windows-route`), and macOS (`macos-route`, elevated mode);
- integration test scaffolds exist for Linux/Windows/macOS route backends (platform and privilege gated);
- cross-platform host bring-up SOPs are documented for Linux, Windows, macOS, and Raspberry Pi.

- 📖 **Vision:** [docs/VISION.md](docs/VISION.md)
- 🗺️ **Roadmap:** [docs/ROADMAP.md](docs/ROADMAP.md)
- 🧭 **Control API:** [docs/CONTROL_API.md](docs/CONTROL_API.md)
- 🛠️ **Host Build Manual (Linux/Windows/macOS/Pi):** [docs/LINUX_WINDOWS_HOST_BUILD_MANUAL.md](docs/LINUX_WINDOWS_HOST_BUILD_MANUAL.md)
- 📓 **Public Host SSH Runbook:** [docs/PUBLIC_HOST_SSH_RUNBOOK.md](docs/PUBLIC_HOST_SSH_RUNBOOK.md)
- ✅ **TODO / Progress:** [TODO.md](TODO.md)
- 🎨 **Brand:** [assets/logo/README.md](assets/logo/README.md)

## Architecture at a glance

```
Control Plane (CRDT, PQ-CA, Policy, Transparency Log, AI Router)
        │
        ├── Edge Gateway Agent  ── WASM runtime · MCP gateway · service discovery
        ├── Smart Relay Network ── eBPF · MP-QUIC + FEC · stream multiplexing
        └── Client Nodes        ── capability wallet · attestation · DID
                                    │
                  PQ-hybrid QUIC over the Veer Fabric Protocol
```

## Crates (planned)

| Crate | Purpose |
|---|---|
| `veersetu-core`    | Shared types, VFP wire format |
| `veersetu-quic`    | PQ-hybrid QUIC transport |
| `veersetu-agent`   | Edge gateway daemon |
| `veersetu-relay`   | Smart relay node |
| `veersetu-control` | Control plane services |
| `veersetu-policy`  | Policy DSL + WASM engine |
| `veersetu-cli`     | Operator CLI |
| `veersetu-sdk`     | Developer SDK |

## CLI sketch

```bash
veersetu login
veersetu expose 8080                # publish a local port
veersetu connect home               # join a mesh
veersetu policy apply policy.yaml
veersetu agent register code-reviewer-v3
```

## Direct-first access (Phase 1)

Agents can now publish a real TCP service through QUIC while advertising
their direct data-plane address to the control plane. Clients discover that
direct address from the logged-in profile and fall back to the relay if the
direct path is unavailable.

```bash
# Agent side: expose localhost:22 as service `ssh` and advertise direct QUIC.
veersetu-agent \
  --control-url http://127.0.0.1:51821 \
  --relay 127.0.0.1:51820 \
  --service ssh \
  --upstream 127.0.0.1:22 \
  --direct-bind 0.0.0.0:61222 \
  --direct-advertise 203.0.113.10:61222 \
  --direct-server-name agent.example.internal

# Client side: forwards local TCP to the discovered direct path first.
veersetu connect ssh --local-bind 127.0.0.1:10022
ssh -p 10022 user@127.0.0.1

# HTTP works the same way; point the agent upstream at your web service.
veersetu connect web --local-bind 127.0.0.1:18080
curl http://127.0.0.1:18080/
```

Manual override is still available with `veersetu connect ssh --direct
203.0.113.10:61222 --direct-server-name agent.example.internal`; relay remains
the fallback route.

For a public-internet SSH test with a Mac behind a home router, use any public
relay/control host. The helper defaults to `tie.veerlabs.solutions` for the
relay/control host and the browser-facing HTTP ingress for the Ubuntu agent's
`:8080` service. The scripted path is:

```bash
deploy/veersetu-setup.sh --role public-host
deploy/veersetu-setup.sh --role agent --control-token CONTROL_TOKEN
deploy/veersetu-setup.sh --role client --control-token CONTROL_TOKEN --ssh-user REMOTE_USER
```

On Windows agents, use the native PowerShell helper instead:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\veersetu-agent-setup.ps1 -ControlToken CONTROL_TOKEN -EnableOpenSSHServer
```

Full manual/reference steps are in [docs/PUBLIC_HOST_SSH_RUNBOOK.md](docs/PUBLIC_HOST_SSH_RUNBOOK.md).

## Policy API (Phase 1)

The control plane currently exposes a practical policy lifecycle contract:

- `POST /v1/policy/apply`
- `POST /v1/policy/validate`
- `GET /v1/policies`
- `GET /v1/policies/{name}`
- `DELETE /v1/policies/{name}`

### Apply with optimistic locking

```bash
curl -sS -X POST http://127.0.0.1:51821/v1/policy/apply \
  -H 'content-type: application/json' \
  -d '{
    "name": "allow-echo",
    "format": "yaml",
    "content": "allow:\n  - service: echo\n    principal: user:alice",
    "if_match_revision": 3
  }'
```

Typical response fields:

- `created`: first write vs existing policy
- `changed`: whether content/format actually changed
- `revision`: monotonic revision (no bump on no-op re-apply)
- `content_sha256`: canonical payload fingerprint
- `previous_revision` / `previous_content_sha256`: set only on real updates

### Validate without persisting

```bash
curl -sS -X POST http://127.0.0.1:51821/v1/policy/validate \
  -H 'content-type: application/json' \
  -d '{
    "name": "precheck",
    "format": "yml",
    "content": "allow:\n  service: echo"
  }'
```

Validation canonicalizes `yml` to `yaml` and returns `content_sha256` for drift checks.

### Status codes and safety guarantees

- `400 Bad Request`: invalid format, malformed payload, or policy rule-shape violations
- `404 Not Found`: `GET`/`DELETE` on missing policy name
- `412 Precondition Failed`: `if_match_sha256` or `if_match_revision` mismatch

Identical re-apply is idempotent: `changed=false`, unchanged revision, and no persisted-state rewrite.

For the binding architecture contract, see `docs/adr/0004-control-policy-api-semantics.md`.

## License

Open core. To be finalised: Apache-2.0 for the OSS crates; BSL-1.1 for managed / AI features. See [TODO.md](TODO.md) for the decision record.

## Contributing

We're not ready for external contributions yet, but star the repo to follow along. Security disclosures will go to `security@veersetu.io` (PGP key to be published).

