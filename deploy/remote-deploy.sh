#!/bin/bash
# Deploy a VeerCanvas site + admin CMS to a remote host.
#
# Usage:
#   SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh
#   SITE_ID=veerlabs EC2_KEY=./VeerSetuHost.pem ./deploy/remote-deploy.sh --import-repos
#
# Options:
#   --import-repos   Fetch GitHub repos and refresh catalog before deploy (IMPORT_REPOS=1).

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

REPO_ROOT="$(cd "${VEERCANVAS_ROOT}/.." && pwd)"
EC2_HOST="${EC2_HOST:-3.216.30.113}"
EC2_USER="${EC2_USER:-ubuntu}"
EC2_KEY="${EC2_KEY:-$REPO_ROOT/VeerSetuHost.pem}"

if [[ ! -f "$EC2_KEY" ]]; then
  echo "error: SSH key not found at $EC2_KEY" >&2
  exit 1
fi

chmod 600 "$EC2_KEY"
SSH_OPTS=(-i "$EC2_KEY" -o StrictHostKeyChecking=accept-new)
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

echo "VeerCanvas deploy: site=${SITE_ID} domain=${SITE_DOMAIN} web_root=${WEB_ROOT}"
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" 'echo "SSH OK"'

if [[ "$IMPORT_REPOS" == "1" ]]; then
  TOKEN_FILE="$REPO_ROOT/gh_token.txt"
  IMPORT_TOKEN="${GH_TOKEN:-}"
  if [[ -z "$IMPORT_TOKEN" && -f "$TOKEN_FILE" ]]; then
    IMPORT_TOKEN="$(tr -d '\n' < "$TOKEN_FILE")"
  fi
  echo "Refreshing GitHub catalog for ${SITE_ID} ..."
  IMPORT_CMD=(
    python3 "$IMPORT_SCRIPT" "${GITHUB_OWNER:-veeringman}" imported_projects
    --site-root "$SITE_DIR"
    --projects-json "$SITE_DIR/projects.json"
    --replace-existing
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

ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" "sudo mkdir -p '$WEB_ROOT' && sudo chown -R ubuntu:ubuntu '$WEB_ROOT'"

echo "Syncing site ${SITE_ID} to ${EC2_USER}@${EC2_HOST}:${WEB_ROOT} ..."
rsync -az --delete \
  -e "$RSYNC_SSH" \
  --filter 'P veercanvas/' \
  --exclude '.git' \
  --exclude 'prompts/' \
  --exclude 'site.config.json' \
  "$SITE_DIR/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/"

echo "Syncing VeerCanvas platform ..."
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" bash -s -- "$WEB_ROOT" <<'REMOTE_DIRS'
set -euo pipefail
WEB_ROOT="$1"
sudo mkdir -p "$WEB_ROOT/veercanvas/admin" "$WEB_ROOT/veercanvas/deploy"
sudo chown -R ubuntu:ubuntu "$WEB_ROOT/veercanvas"
REMOTE_DIRS

RSYNC_MKPATH=()
if rsync --help 2>&1 | grep -q mkpath; then
  RSYNC_MKPATH=(--mkpath)
fi

rsync -az "${RSYNC_MKPATH[@]}" \
  -e "$RSYNC_SSH" \
  --exclude '__pycache__' \
  --exclude 'admin.db' \
  "$VEERCANVAS_ROOT/admin/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/admin/"

rsync -az "${RSYNC_MKPATH[@]}" \
  -e "$RSYNC_SSH" \
  "$VEERCANVAS_ROOT/deploy/" \
  "${EC2_USER}@${EC2_HOST}:$WEB_ROOT/veercanvas/deploy/"

ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" \
  "sudo VEERCANVAS_SITE_ID=$SITE_ID VEERCANVAS_SITE_ROOT=$WEB_ROOT WEB_ROOT=$WEB_ROOT DOMAIN=$SITE_DOMAIN bash $WEB_ROOT/veercanvas/deploy/site-deploy.sh"

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
fi

echo "Deploy complete."
