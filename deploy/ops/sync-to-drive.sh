#!/usr/bin/env bash
# Phase-2 Google Drive sync.
#
# Expected env (in data/smtp.env or data/drive.env):
#   DRIVE_ENABLED=1
#   DRIVE_FOLDER_ID=...          # shared "Housing Colony Sanyard Backups" folder
#   GOOGLE_APPLICATION_CREDENTIALS=/var/www/.../data/drive-sa.json
#   DRIVE_RETAIN_DAYS=14
#
# Syncs: latest on-box backup tarball + selected data/* asset dirs.
#
# Usage:
#   WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions SITE_ID=hbcsanyard ./sync-to-drive.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-}}"
SITE_ID="${SITE_ID:-}"

if [[ -z "$WEB_ROOT" ]]; then
  echo "error: set WEB_ROOT" >&2
  exit 2
fi

# shellcheck source=load-site-env.sh
source "${SCRIPT_DIR}/load-site-env.sh"
load_site_env "$WEB_ROOT"
# Optional dedicated drive env (overrides smtp.env)
if [[ -f "${WEB_ROOT}/data/drive.env" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" || "$line" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    key="$(echo "$key" | sed 's/[[:space:]]*$//')"
    val="$(echo "$val" | sed 's/^[[:space:]]*//;s/^["'\'']//;s/["'\'']$//')"
    export "$key=$val"
  done < "${WEB_ROOT}/data/drive.env"
fi

SITE_ID="${SITE_ID:-$(basename "$WEB_ROOT" | cut -d. -f1)}"

if [[ "${DRIVE_ENABLED:-0}" != "1" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Drive sync skipped (DRIVE_ENABLED!=1). See deploy/OPS-BACKUP.md § Drive."
  python3 "${SCRIPT_DIR}/write-ops-status.py" \
    --site-root "$WEB_ROOT" \
    --section lastDriveSync \
    --json '{"ok":false,"skipped":true,"reason":"DRIVE_ENABLED!=1"}' 2>/dev/null || true
  exit 0
fi

if [[ -z "${DRIVE_FOLDER_ID:-}" ]]; then
  echo "error: DRIVE_FOLDER_ID required when DRIVE_ENABLED=1" >&2
  python3 "${SCRIPT_DIR}/write-ops-status.py" \
    --site-root "$WEB_ROOT" \
    --section lastDriveSync \
    --json '{"ok":false,"error":"DRIVE_FOLDER_ID missing"}' 2>/dev/null || true
  exit 1
fi
if [[ -f "${WEB_ROOT}/data/drive-token.json" ]]; then
  export DRIVE_TOKEN_JSON="${DRIVE_TOKEN_JSON:-${WEB_ROOT}/data/drive-token.json}"
fi
if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" || ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
  if [[ -f "${WEB_ROOT}/data/drive-sa.json" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="${WEB_ROOT}/data/drive-sa.json"
  fi
fi
if [[ ! -f "${DRIVE_TOKEN_JSON:-}" && ! -f "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  echo "error: missing Drive credentials (data/drive-token.json or data/drive-sa.json)" >&2
  python3 "${SCRIPT_DIR}/write-ops-status.py" \
    --site-root "$WEB_ROOT" \
    --section lastDriveSync \
    --json '{"ok":false,"error":"no Drive token or service account"}' 2>/dev/null || true
  exit 1
fi

set +e
PY="${DRIVE_PYTHON:-}"
if [[ -z "$PY" && -x "${WEB_ROOT}/data/drive-venv/bin/python" ]]; then
  PY="${WEB_ROOT}/data/drive-venv/bin/python"
elif [[ -z "$PY" && -x /var/lib/veercanvas/drive-venv/bin/python ]]; then
  PY=/var/lib/veercanvas/drive-venv/bin/python
fi
PY="${PY:-python3}"
OUT="$("$PY" "${SCRIPT_DIR}/sync-to-drive.py" \
  --site-root "$WEB_ROOT" \
  --folder-id "$DRIVE_FOLDER_ID" \
  --site-id "$SITE_ID" \
  --retain-days "${DRIVE_RETAIN_DAYS:-14}" 2>&1)"
RC=$?
set -e
echo "$OUT"
JSON_LINE="$(echo "$OUT" | tail -n 1)"
if [[ "$RC" -eq 0 ]]; then
  python3 "${SCRIPT_DIR}/write-ops-status.py" \
    --site-root "$WEB_ROOT" \
    --section lastDriveSync \
    --json "$JSON_LINE" 2>/dev/null || true
else
  ERR="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1][:400]))' "$OUT")"
  python3 "${SCRIPT_DIR}/write-ops-status.py" \
    --site-root "$WEB_ROOT" \
    --section lastDriveSync \
    --json "{\"ok\":false,\"error\":${ERR}}" 2>/dev/null || true
  exit "$RC"
fi
