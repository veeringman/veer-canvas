#!/bin/bash
# Repair VeerCanvas admin on the server (502 Bad Gateway).
# Run on EC2 as root/sudo, or via SSH:
#   ssh -i ./VeerSetuHost.pem ubuntu@3.216.30.113 \
#     'sudo WEB_ROOT=/var/www/veerlabs.solutions DOMAIN=veerlabs.solutions bash /var/www/veerlabs.solutions/veercanvas/deploy/repair-admin.sh'

set -euo pipefail

WEB_ROOT="${WEB_ROOT:-/var/www/veerlabs.solutions}"
DOMAIN="${DOMAIN:-veerlabs.solutions}"
DEPLOY_SCRIPT="${WEB_ROOT}/veercanvas/deploy/site-deploy.sh"

if [[ ! -f "$DEPLOY_SCRIPT" ]]; then
  echo "error: $DEPLOY_SCRIPT not found. Run remote-deploy.sh from your Mac first." >&2
  exit 1
fi

export VEERCANVAS_SITE_ROOT="$WEB_ROOT"
export WEB_ROOT
export DOMAIN
bash "$DEPLOY_SCRIPT"

echo "Checking admin on port 8080 ..."
if curl -fsS "http://127.0.0.1:8080/login" >/dev/null; then
  echo "Admin OK: https://${DOMAIN}/admin/"
else
  echo "error: admin still not responding on localhost:8080" >&2
  systemctl status veercanvas-admin --no-pager || true
  journalctl -u veercanvas-admin -n 50 --no-pager || true
  exit 1
fi
