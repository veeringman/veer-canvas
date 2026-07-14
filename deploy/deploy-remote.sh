#!/usr/bin/env bash
# Deprecated — use veercanvas/deploy/remote-deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SITE_ID="${SITE_ID:-veerlabs}"
echo "Note: deploy-remote.sh delegates to veercanvas/deploy/remote-deploy.sh" >&2
exec "$ROOT/veercanvas/deploy/remote-deploy.sh" "$@"
