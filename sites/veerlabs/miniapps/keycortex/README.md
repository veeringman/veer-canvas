<img src="./keycortex_logo.png" alt="KeyCortex Logo" width="180" />

# KeyCortex
A Secure Rust based digital wallet and cryptographic signing engine that binds enterprise identies to blockchain keys and executes policy-approved transactions.

KeyCortex is designed with an extensible multi-chain architecture, while the initial implementation supports only FlowCortex L1 (`flowcortex-l1`) with PROOF (native coin) and FloweR (native stablecoin).

## API Contract

- Frozen v0.1 wallet/auth contract: `KeyCortex_API_v0.1_Contract.md`
- Engineering learnings log: `KeyCortex_Learnings.md`

## Fast Local Runs (Persistent Build Cache)

To avoid repeated `librocksdb-sys` rebuilds, use a persistent Cargo target directory and run the cached launcher.

One-time shell setup (optional but recommended):

```bash
echo 'export CARGO_TARGET_DIR="$HOME/.cache/keycortex/cargo-target"' >> ~/.bashrc
source ~/.bashrc
```

Run wallet-service using cached artifacts:

```bash
./scripts/run_wallet_service_cached.sh
```

Behavior:

- uses `$CARGO_TARGET_DIR/debug/wallet-service` when present
- if missing, reuses `./target/debug/wallet-service` and seeds the cache
- builds only when no binary is available

Force a rebuild into the persistent cache:

```bash
./scripts/run_wallet_service_cached.sh --rebuild
```

## Service Diagnostics

Related operations docs:

- `KeyCortex_Postgres_Degradation_Playbook.md`
- `KeyCortex_Startupz_Field_Ownership_Matrix.md`

### `GET /startupz`

Returns a consolidated startup/runtime diagnostics payload for operations visibility.

Key fields:

- `storage_mode`: `rocksdb-only` or `postgres+rocksdb`
- `postgres_enabled`: true when Postgres repository is active
- `postgres_startup`: Postgres startup status including migration directory, applied migration file count, and startup error details
- `db_fallback_counters`: fallback counter totals and per-path counts for Postgres failure fallback behavior
- `auth_mode` and JWKS status fields mirroring auth runtime readiness signals

Example:

```bash
curl -s http://127.0.0.1:8080/startupz | jq
```

Sample response excerpt:

```json
{
	"service": "wallet-service",
	"storage_mode": "postgres+rocksdb",
	"postgres_enabled": true,
	"postgres_startup": {
		"configured": true,
		"enabled": true,
		"migrations_dir": "./migrations/postgres",
		"migration_files_applied": 1,
		"last_error": null
	},
	"db_fallback_counters": {
		"postgres_unavailable": 0,
		"challenge_persist_failures": 0,
		"challenge_mark_used_failures": 0,
		"binding_write_failures": 0,
		"binding_read_failures": 0,
		"audit_write_failures": 0,
		"audit_read_failures": 0,
		"total": 0
	}
}
```

## Local Postgres Test Runbook

Use this to run Postgres-backed repository tests and diagnostics smoke checks locally.

1) Start local Postgres (Docker example):

```bash
docker run --rm -d \
	--name keycortex-pg \
	-e POSTGRES_USER=keycortex \
	-e POSTGRES_PASSWORD=keycortex \
	-e POSTGRES_DB=keycortex_test \
	-p 5432:5432 \
	postgres:16
```

2) Run wallet-service Postgres integration tests:

```bash
TEST_DATABASE_URL=postgres://keycortex:keycortex@127.0.0.1:5432/keycortex_test \
TEST_MIGRATIONS_DIR=./migrations/postgres \
cargo test -p wallet-service db::tests -- --nocapture
```

3) Run diagnostics/fallback smoke test against a running service:

```bash
BASE_URL=http://127.0.0.1:8080 ./scripts/smoke_db_fallback.sh
```

4) Stop local Postgres:

```bash
docker stop keycortex-pg
```

## Release Gate Checklist

Use this checklist before promoting wallet-service changes:

- `/health`, `/readyz`, and `/startupz` return 200 in target environment
- `/startupz.postgres_startup.enabled` is `true` for Postgres-backed deployments
- `/startupz.postgres_startup.last_error` is `null`
- `/startupz.db_fallback_counters.total` is stable (no unexplained growth)
- fallback smoke script passes: `BASE_URL=<service_url> ./scripts/smoke_db_fallback.sh`
- Postgres integration tests pass in CI (`wallet-service-ci` workflow)

## Operations Troubleshooting (Fallback Counter Spikes)

If `db_fallback_counters.total` increases rapidly:

1) Check startup diagnostics:

```bash
curl -s http://127.0.0.1:8080/startupz | jq
```

2) Identify dominant counter field:

- `binding_read_failures` / `audit_read_failures` → Postgres read path instability
- `binding_write_failures` / `audit_write_failures` → Postgres write path instability
- `challenge_*_failures` → challenge lifecycle persistence issues
- `postgres_unavailable` → startup connection/init failures

3) Verify Postgres health and connectivity:

- confirm DB reachable from service network
- validate credentials in `DATABASE_URL`
- inspect Postgres logs for timeouts or connection limits

4) Verify migrations:

- confirm `KEYCORTEX_POSTGRES_MIGRATIONS_DIR` points to valid SQL files
- check `/startupz.postgres_startup.migration_files_applied` > 0 for initialized deployments

5) Mitigate while investigating:

- keep service running; RocksDB fallback remains active
- scale/repair Postgres and monitor counters for stabilization

### Alert Threshold Recommendations

Use the 5-minute delta of `db_fallback_counters.total` from `/startupz`:

- `0-2` in 5m: normal noise (no alert)
- `3-10` in 5m: warning (investigate Postgres latency/errors)
- `>10` in 5m: critical (active degradation)

Per-counter critical suggestions (5-minute delta):

- `postgres_unavailable >= 1`
- `binding_write_failures >= 5`
- `audit_write_failures >= 5`
- `binding_read_failures >= 10`
- `audit_read_failures >= 10`
- `challenge_persist_failures >= 3`
- `challenge_mark_used_failures >= 3`

Operational note:

- Trigger a page if critical threshold is crossed in 2 consecutive windows.
