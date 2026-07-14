#!/usr/bin/env bash
# Resolve VeerCanvas site paths from SITE_ID and optional site.config.json.
# Source this file from deploy scripts: source "$(dirname "$0")/lib/site-env.sh"

set -euo pipefail

VEERCANVAS_ROOT="${VEERCANVAS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SITE_ID="${SITE_ID:-veerlabs}"
SITE_DIR="${VEERCANVAS_ROOT}/sites/${SITE_ID}"
SITE_CONFIG="${SITE_DIR}/site.config.json"

if [[ ! -d "$SITE_DIR" ]]; then
  echo "error: site directory not found: $SITE_DIR" >&2
  exit 1
fi

SITE_NAME="$SITE_ID"
SITE_DOMAIN="localhost"
WEB_ROOT="${WEB_ROOT:-/var/www/${SITE_ID}}"
GITHUB_OWNER="${GITHUB_OWNER:-}"

if [[ -f "$SITE_CONFIG" ]]; then
  read_site_config() {
    python3 - "$SITE_CONFIG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
print(cfg.get("name", ""))
print(cfg.get("domain", ""))
print(cfg.get("webRoot", ""))
print(cfg.get("githubOwner", ""))
PY
  }
  _i=0
  while IFS= read -r _line; do
    case "$_i" in
      0) [[ -n "$_line" ]] && SITE_NAME="$_line" ;;
      1) [[ -n "$_line" ]] && SITE_DOMAIN="$_line" ;;
      2) [[ -n "$_line" && -z "${WEB_ROOT_SET:-}" ]] && WEB_ROOT="$_line" ;;
      3) [[ -n "$_line" ]] && GITHUB_OWNER="$_line" ;;
    esac
    _i=$((_i + 1))
  done < <(read_site_config)
fi

IMPORT_SCRIPT="${VEERCANVAS_ROOT}/cli/scripts/import_github_projects_full.py"
ADMIN_DIR="${VEERCANVAS_ROOT}/admin"
DEPLOY_DIR="${VEERCANVAS_ROOT}/deploy"
