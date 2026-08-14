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
WEB_ROOT="${WEB_ROOT:-}"
GITHUB_OWNER="${GITHUB_OWNER:-}"
_CFG_ADMIN_PORT=""
_CFG_SERVICE_NAME=""
_CFG_PLATFORM="0"
_CFG_OPS="0"
_CFG_EXTRA_DOMAINS=""
_CFG_CMS_PREFIX=""

if [[ -f "$SITE_CONFIG" ]]; then
  read_site_config() {
    python3 - "$SITE_CONFIG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
admin = cfg.get("admin") or {}
print(cfg.get("name", ""))
print(cfg.get("domain", ""))
print(cfg.get("webRoot", ""))
print(cfg.get("githubOwner", ""))
print(admin.get("port", ""))
print(admin.get("serviceName", ""))
print("1" if cfg.get("platform") else "0")
print("1" if cfg.get("ops") else "0")
primary = (cfg.get("domain") or "").strip()
extras = [str(x).strip() for x in (cfg.get("extraDomains") or []) if str(x).strip()]
for alias in (cfg.get("aliases") or []):
    a = str(alias).strip()
    if not a or a == primary or a == f"www.{primary}":
        continue
    # One nginx example per apex host (www.* is in the same vhost).
    apex = a[4:] if a.startswith("www.") else a
    if apex != primary and apex not in extras:
        extras.append(apex)
print(" ".join(extras))
print(((cfg.get("admin") or {}).get("cmsPrefix") or "/admin").strip() or "/admin")
PY
  }
  _i=0
  while IFS= read -r _line; do
    case "$_i" in
      0) [[ -n "$_line" ]] && SITE_NAME="$_line" ;;
      1) [[ -n "$_line" ]] && SITE_DOMAIN="$_line" ;;
      2) [[ -n "$_line" ]] && _CFG_WEB_ROOT="$_line" ;;
      3) [[ -n "$_line" ]] && GITHUB_OWNER="$_line" ;;
      4) [[ -n "$_line" ]] && _CFG_ADMIN_PORT="$_line" ;;
      5) [[ -n "$_line" ]] && _CFG_SERVICE_NAME="$_line" ;;
      6) _CFG_PLATFORM="$_line" ;;
      7) _CFG_OPS="$_line" ;;
      8) [[ -n "$_line" ]] && _CFG_EXTRA_DOMAINS="$_line" ;;
      9) [[ -n "$_line" ]] && _CFG_CMS_PREFIX="$_line" ;;
    esac
    _i=$((_i + 1))
  done < <(read_site_config)
fi

if [[ -z "$WEB_ROOT" ]]; then
  WEB_ROOT="${_CFG_WEB_ROOT:-/var/www/${SITE_DOMAIN:-$SITE_ID}}"
fi
ADMIN_PORT="${ADMIN_PORT:-${_CFG_ADMIN_PORT:-8080}}"
SERVICE_NAME="${VEERCANVAS_SERVICE_NAME:-${_CFG_SERVICE_NAME:-veercanvas-admin}}"
IS_PLATFORM="${VEERCANVAS_PLATFORM:-$_CFG_PLATFORM}"
IS_OPS="${VEERCANVAS_OPS:-$_CFG_OPS}"
EXTRA_DOMAINS="${EXTRA_DOMAINS:-${_CFG_EXTRA_DOMAINS:-}}"
CMS_PREFIX="${CMS_PREFIX:-${_CFG_CMS_PREFIX:-/admin}}"

IMPORT_SCRIPT="${VEERCANVAS_ROOT}/cli/scripts/import_github_projects_full.py"
ADMIN_DIR="${VEERCANVAS_ROOT}/admin"
DEPLOY_DIR="${VEERCANVAS_ROOT}/deploy"
