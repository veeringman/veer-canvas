#!/bin/bash
# Deprecated — use deploy/remote-deploy.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Note: deploy-remote.sh delegates to deploy/remote-deploy.sh" >&2
exec "$ROOT/deploy/remote-deploy.sh" "$@"
