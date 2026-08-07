#!/bin/bash
# Deploy a VeerCanvas site + admin CMS to a remote host.
#
# Usage:
#   SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh
#   SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh --import-repos
#
# Options:
#   --import-repos   Fetch NEW GitHub repos only (skips already imported unless marked reimport).
# Env:
#   OVERRIDE_CATALOG=1   Push local catalog instead of preserving live CMS state.

set -euo pipefail

IMPORT_REPOS="${IMPORT_REPOS:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --import-repos) IMPORT_REPOS=1; shift ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

VEERCANVAS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/site-env.sh
source "${VEERCANVAS_ROOT}/deploy/lib/site-env.sh"

EC2_HOST="${EC2_HOST:-3.216.30.113}"
EC2_USER="${EC2_USER:-ubuntu}"
EC2_KEY="${EC2_KEY:-$VEERCANVAS_ROOT/VeerSetuHost.pem}"

if [[ ! -f "$EC2_KEY" ]]; then
  echo "error: SSH key not found at $EC2_KEY" >&2
  exit 1
fi

chmod 600 "$EC2_KEY"
SSH_OPTS=(-i "$EC2_KEY" -o StrictHostKeyChecking=accept-new)
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

echo "VeerCanvas deploy: site=${SITE_ID} domain=${SITE_DOMAIN} web_root=${WEB_ROOT} service=${SERVICE_NAME} port=${ADMIN_PORT} platform=${IS_PLATFORM} ops=${IS_OPS}"
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" 'echo "SSH OK"'

ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" "sudo mkdir -p '$WEB_ROOT' && sudo chown -R ubuntu:ubuntu '$WEB_ROOT'"

# Live CMS catalog is the source of truth for hide/delete/import state unless overridden.
# This prevents local git from resurrecting deleted/disabled projects on deploy.
if [[ "${OVERRIDE_CATALOG:-0}" != "1" ]]; then
  echo "Pulling live CMS catalog from server (set OVERRIDE_CATALOG=1 to skip)..."
  for catalog_file in projects.json projects-public.json catalog-exclusions.json site-meta.json; do
    rsync -az -e "$RSYNC_SSH" \
      "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/$catalog_file" \
      "$SITE_DIR/$catalog_file" 2>/dev/null \
      || echo "Warning: could not pull $catalog_file (first deploy?)."
  done
  rsync -az -e "$RSYNC_SSH" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/miniapps/" \
    "$SITE_DIR/miniapps/" 2>/dev/null \
    || echo "Warning: could not pull miniapps (first deploy?)."
  mkdir -p "$SITE_DIR/assets/site"
  rsync -az -e "$RSYNC_SSH" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/assets/site/" \
    "$SITE_DIR/assets/site/" 2>/dev/null \
    || echo "Warning: could not pull assets/site (no custom brand uploads yet)."
  # Ensure newer site-meta content keys exist without wiping live CMS values.
  export SITE_DIR
  python3 - <<'PY'
import json
from pathlib import Path
import os
site = Path(os.environ["SITE_DIR"])
path = site / "site-meta.json"
defaults = {
    "siteName": "VeerLabs Solutions",
    "brandName": "VeerLabs",
    "brandTag": "Solutions",
    "eyebrow": "Veeringman studio catalog",
    "title": "VeerLabs Solutions",
    "subtitle": "Explore secure edge fabric, browsers, operating systems, and networking stacks. Each tile opens a documentation-rich project page.",
    "chipPrimary": "Project catalog",
    "chipSecondary": "Powered by VeerCanvas",
    "platform": "VeerCanvas",
    "favicon": "assets/favicon.svg",
    "brandMark": "assets/veer-canvas-icon.svg",
}
data = {}
if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
if not isinstance(data, dict):
    data = {}
merged = dict(defaults)
merged.update({k: v for k, v in data.items() if v not in (None, "")})
# Only fill brand asset paths when missing; never overwrite CMS uploads.
for key, rel in (("favicon", "assets/favicon.svg"), ("brandMark", "assets/veer-canvas-icon.svg")):
    current = merged.get(key) or ""
    current_path = site / str(current).split("?", 1)[0]
    if current and current_path.exists():
        continue
    # Prefer uploaded assets/site files when present.
    stem = "brand-mark" if key == "brandMark" else "favicon"
    site_dir = site / "assets" / "site"
    uploaded = None
    if site_dir.exists():
        matches = sorted(p for p in site_dir.glob(f"{stem}.*") if p.is_file() and p.stat().st_size > 0)
        uploaded = matches[0] if matches else None
    if uploaded:
        merged[key] = f"assets/site/{uploaded.name}"
    elif (site / rel).exists():
        merged[key] = rel
# Ensure AuthBuddy agent auth gate keys survive live CMS pull.
auth_defaults = {
    "agentBaseUrl": "",
    "idpPublicUrl": "https://authbuddy.veerlabs.solutions",
    "clientId": "veerlabs-web",
    "gateAllLearnMore": True,
}
cfg_path = site / "site.config.json"
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg_auth = cfg.get("auth") if isinstance(cfg, dict) else None
        if isinstance(cfg_auth, dict):
            auth_defaults.update({k: v for k, v in cfg_auth.items() if v not in (None, "")})
    except json.JSONDecodeError:
        pass
live_auth = merged.get("auth") if isinstance(merged.get("auth"), dict) else {}
auth = dict(auth_defaults)
auth.update({k: v for k, v in live_auth.items() if v not in (None, "")})
# Prefer local site.config auth for IdP / gate flags when present.
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg_auth = cfg.get("auth") if isinstance(cfg, dict) else None
        if isinstance(cfg_auth, dict):
            for k in ("idpPublicUrl", "clientId", "gateAllLearnMore", "agentBaseUrl"):
                if k in cfg_auth and cfg_auth[k] not in (None, ""):
                    auth[k] = cfg_auth[k]
    except json.JSONDecodeError:
        pass
merged["auth"] = auth
path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
print(f"Merged site-meta keys: {', '.join(sorted(merged.keys()))}")
print(f"brandMark={merged.get('brandMark')} favicon={merged.get('favicon')}")
print(f"auth={merged.get('auth')}")
PY
fi

if [[ "$IMPORT_REPOS" == "1" ]]; then
  TOKEN_FILE=""
  for candidate in "$VEERCANVAS_ROOT/gt_token.txt" "$VEERCANVAS_ROOT/gh_token.txt"; do
    if [[ -f "$candidate" ]]; then
      TOKEN_FILE="$candidate"
      break
    fi
  done
  # Prefer token file over ambient GH_TOKEN/GITHUB_TOKEN (often stale in the shell).
  IMPORT_TOKEN=""
  if [[ -n "$TOKEN_FILE" ]]; then
    IMPORT_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
  fi
  if [[ -z "$IMPORT_TOKEN" ]]; then
    IMPORT_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
  fi
  echo "Importing NEW GitHub repos for ${SITE_ID} (existing projects skipped unless reimport marked)..."
  if [[ -z "$IMPORT_TOKEN" ]]; then
    echo "Warning: no GitHub token found (gt_token.txt / gh_token.txt / GH_TOKEN); private repos will be skipped."
  else
    echo "Using GitHub token from ${TOKEN_FILE:-environment}"
  fi
  IMPORT_CMD=(
    python3 "$IMPORT_SCRIPT" "${GITHUB_OWNER:-veeringman}" imported_projects
    --site-root "$SITE_DIR"
    --projects-json "$SITE_DIR/projects.json"
    --fetch-repos
  )
  if [[ -n "$IMPORT_TOKEN" ]]; then
    IMPORT_CMD+=(--token "$IMPORT_TOKEN")
  fi
  "${IMPORT_CMD[@]}" || echo "Warning: import failed; continuing with existing catalog."
else
  echo "Skipping GitHub import (pass --import-repos or set IMPORT_REPOS=1)."
fi

echo "Building public catalog ..."
python3 "$IMPORT_SCRIPT" "${GITHUB_OWNER:-veeringman}" imported_projects \
  --site-root "$SITE_DIR" \
  --projects-json "$SITE_DIR/projects.json" \
  --write-public-catalog

echo "Syncing site ${SITE_ID} to ${EC2_USER}@${EC2_HOST}:${WEB_ROOT} ..."
# Runtime data/config on the server must survive rebuilds:
# - exclude from upload so local copies never overwrite production
# - protect (P) so --delete cannot remove them either
rsync -az --delete \
  -e "$RSYNC_SSH" \
  --filter 'P veercanvas/' \
  --filter 'P assets/site/' \
  --filter 'P assets/site/***' \
  --filter 'P engagement.json' \
  --filter 'P contact-messages.json' \
  --filter 'P visitor-access.json' \
  --filter 'P data/rwa.db' \
  --filter 'P data/rwa.db-*' \
  --filter 'P data/smtp.env' \
  --filter 'P data/*.env' \
  --filter 'P data/imports/' \
  --filter 'P data/imports/***' \
  --filter 'P data/payments/' \
  --filter 'P data/payments/***' \
  --filter 'P data/profile-photos/' \
  --filter 'P data/profile-photos/***' \
  --filter 'P data/info-centre/' \
  --filter 'P data/info-centre/***' \
  --exclude 'data/rwa.db' \
  --exclude 'data/rwa.db-*' \
  --exclude 'data/smtp.env' \
  --exclude 'data/*.env' \
  --exclude 'data/imports/' \
  --exclude 'data/payments/' \
  --exclude 'data/profile-photos/' \
  --exclude 'data/info-centre/' \
  --exclude '.git' \
  --exclude 'prompts/' \
  --exclude 'site.config.json' \
  "$SITE_DIR/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/"

# First-deploy bootstrap only: seed DB / example env if missing on server (never overwrite).
echo "Bootstrapping missing runtime data (ignore-existing) ..."
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" "mkdir -p '$WEB_ROOT/data/imports' '$WEB_ROOT/data/payments' '$WEB_ROOT/data/profile-photos' '$WEB_ROOT/data/info-centre' && sudo chown -R ubuntu:ubuntu '$WEB_ROOT/data'"
if [[ -f "$SITE_DIR/data/rwa.db" ]]; then
  rsync -az --ignore-existing -e "$RSYNC_SSH" \
    "$SITE_DIR/data/rwa.db" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/data/rwa.db"
fi
if [[ -f "$SITE_DIR/data/smtp.env.example" ]]; then
  rsync -az --ignore-existing -e "$RSYNC_SSH" \
    "$SITE_DIR/data/smtp.env.example" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/data/smtp.env.example"
fi
# Never push a real smtp.env from the laptop; only create from example when absent.
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" bash -s -- "$WEB_ROOT" <<'REMOTE_ENV'
set -euo pipefail
WEB_ROOT="$1"
if [[ ! -f "$WEB_ROOT/data/smtp.env" && -f "$WEB_ROOT/data/smtp.env.example" ]]; then
  cp "$WEB_ROOT/data/smtp.env.example" "$WEB_ROOT/data/smtp.env"
  chmod 600 "$WEB_ROOT/data/smtp.env" || true
  echo "Created data/smtp.env from example (edit via Super admin Settings)."
else
  echo "Preserved existing data/smtp.env (or no example present)."
fi
if [[ -f "$WEB_ROOT/data/rwa.db" ]]; then
  echo "Preserved data/rwa.db on server."
else
  echo "Warning: data/rwa.db still missing — app will seed on first start if scripts available."
fi
REMOTE_ENV

echo "Syncing VeerCanvas platform ..."
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" bash -s -- "$WEB_ROOT" <<'REMOTE_DIRS'
set -euo pipefail
WEB_ROOT="$1"
sudo mkdir -p "$WEB_ROOT/veercanvas/admin" "$WEB_ROOT/veercanvas/deploy" "$WEB_ROOT/veercanvas/cli/scripts" "$WEB_ROOT/veercanvas/sites"
sudo chown -R ubuntu:ubuntu "$WEB_ROOT/veercanvas"
REMOTE_DIRS

rsync -az \
  -e "$RSYNC_SSH" \
  --exclude '__pycache__' \
  --exclude 'admin.db' \
  --exclude 'gh_token.txt' \
  --exclude 'gt_token.txt' \
  "$VEERCANVAS_ROOT/admin/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/admin/"

# Install GitHub token for admin private-repo imports (never commit; chmod 600 remotely).
for candidate in "$VEERCANVAS_ROOT/gt_token.txt" "$VEERCANVAS_ROOT/gh_token.txt"; do
  if [[ -f "$candidate" ]]; then
    echo "Syncing GitHub token for admin imports..."
    rsync -az -e "$RSYNC_SSH" "$candidate" \
      "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/gh_token.txt"
    ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
      "chmod 600 '$WEB_ROOT/veercanvas/gh_token.txt'"
    break
  fi
done

rsync -az \
  -e "$RSYNC_SSH" \
  "$VEERCANVAS_ROOT/deploy/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/deploy/"

rsync -az \
  -e "$RSYNC_SSH" \
  "$VEERCANVAS_ROOT/cli/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/cli/"

# Platform (site create) and Ops (observability) need the sites/ inventory tree.
if [[ "$IS_PLATFORM" == "1" || "$IS_PLATFORM" == "true" || "$IS_OPS" == "1" || "$IS_OPS" == "true" ]]; then
  echo "Syncing sites tree for control-plane inventory ..."
  rsync -az \
    -e "$RSYNC_SSH" \
    --exclude '.git' \
    --exclude 'prompts/' \
    --exclude 'miniapps/*/node_modules' \
    "$VEERCANVAS_ROOT/sites/" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/sites/"
fi

# Also keep this site's config + RWA scripts under veercanvas/sites/<id> for inventory/imports.
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" "mkdir -p '$WEB_ROOT/veercanvas/sites/$SITE_ID/scripts'"
rsync -az -e "$RSYNC_SSH" \
  "$SITE_DIR/site.config.json" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/sites/$SITE_ID/site.config.json" \
  2>/dev/null || true
if [[ -d "$SITE_DIR/scripts" ]]; then
  rsync -az -e "$RSYNC_SSH" \
    --exclude '__pycache__' \
    "$SITE_DIR/scripts/" \
    "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/sites/$SITE_ID/scripts/"
fi

echo "Running remote site-deploy (service=${SERVICE_NAME} port=${ADMIN_PORT} platform=${IS_PLATFORM} ops=${IS_OPS}) ..."
if ! ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
  "sudo VEERCANVAS_SITE_ID=$SITE_ID VEERCANVAS_SITE_ROOT=$WEB_ROOT WEB_ROOT=$WEB_ROOT DOMAIN=$SITE_DOMAIN ADMIN_PORT=$ADMIN_PORT VEERCANVAS_SERVICE_NAME=$SERVICE_NAME VEERCANVAS_PLATFORM=$IS_PLATFORM VEERCANVAS_OPS=$IS_OPS bash $WEB_ROOT/veercanvas/deploy/site-deploy.sh"; then
  echo "error: remote site-deploy failed" >&2
  exit 1
fi

if ! ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
  "systemctl is-active --quiet '$SERVICE_NAME'"; then
  echo "error: admin service $SERVICE_NAME is not running on the server" >&2
  ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
    "sudo journalctl -u '$SERVICE_NAME' -n 40 --no-pager" >&2 || true
  exit 1
fi

echo "Verifying deployment ..."
VERIFY_URL="https://${SITE_DOMAIN}/site-meta.json"
if curl -fsSL "$VERIFY_URL" >/dev/null 2>&1; then
  curl -fsSL "$VERIFY_URL"
  echo
  ADMIN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -L "https://${SITE_DOMAIN}/admin/")
  echo "Admin HTTP status: $ADMIN_CODE"
else
  curl -fsSL "http://${SITE_DOMAIN}/site-meta.json" || true
  echo
  ADMIN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -L "http://${SITE_DOMAIN}/admin/" || true)
  echo "Admin HTTP status (http): $ADMIN_CODE"
fi

echo "Deploy complete."
