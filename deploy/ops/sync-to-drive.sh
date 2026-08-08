#!/usr/bin/env bash
# Phase-2 Google Drive sync (placeholder until hbcsanyard Gmail + service account are ready).
#
# Expected env (in data/smtp.env or data/drive.env):
#   DRIVE_ENABLED=1
#   DRIVE_FOLDER_ID=...          # shared "HBC Sanyard Backups" folder
#   GOOGLE_APPLICATION_CREDENTIALS=/var/www/.../data/drive-sa.json
#
# Syncs: latest on-box backup tarball + data/receipts, profile-photos, info-centre, payments.
#
# Usage:
#   WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions ./sync-to-drive.sh
#   # or after backup-site.sh when DRIVE_ENABLED=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-}}"
SITE_ID="${SITE_ID:-}"

if [[ -z "$WEB_ROOT" ]]; then
  echo "error: set WEB_ROOT" >&2
  exit 2
fi

# shellcheck source=load-site-env.sh
source "${SCRIPT_DIR}/load-site-env.sh"
load_site_env "$WEB_ROOT"
# Optional dedicated drive env
if [[ -f "${WEB_ROOT}/data/drive.env" ]]; then
  load_site_env_file() { :; }
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

if [[ "${DRIVE_ENABLED:-0}" != "1" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Drive sync skipped (DRIVE_ENABLED!=1). See deploy/OPS-BACKUP.md § Drive."
  exit 0
fi

if [[ -z "${DRIVE_FOLDER_ID:-}" ]]; then
  echo "error: DRIVE_FOLDER_ID required when DRIVE_ENABLED=1" >&2
  exit 1
fi
if [[ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" || ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
  # Default path preserved on deploy
  if [[ -f "${WEB_ROOT}/data/drive-sa.json" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="${WEB_ROOT}/data/drive-sa.json"
  else
    echo "error: missing service account JSON (data/drive-sa.json)" >&2
    exit 1
  fi
fi

python3 "${SCRIPT_DIR}/sync-to-drive.py" \
  --site-root "$WEB_ROOT" \
  --folder-id "$DRIVE_FOLDER_ID" \
  --site-id "${SITE_ID:-$(basename "$WEB_ROOT" | cut -d. -f1)}"
