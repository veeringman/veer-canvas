#!/bin/bash
# On-host VeerCanvas setup: nginx, admin systemd, venv.
# Usually invoked by deploy/remote-deploy.sh after rsync.
#
# Usage:
#   sudo VEERCANVAS_SITE_ROOT=/var/www/veerlabs.solutions DOMAIN=veerlabs.solutions \
#     bash veercanvas/deploy/site-deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEERCANVAS_ROOT="${VEERCANVAS_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-/var/www/veerlabs.solutions}}"
DOMAIN="${DOMAIN:-veerlabs.solutions}"
NGINX_SITES_AVAILABLE="${NGINX_SITES_AVAILABLE:-/etc/nginx/sites-available}"
NGINX_SITES_ENABLED="${NGINX_SITES_ENABLED:-/etc/nginx/sites-enabled}"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
ADMIN_DIR="${WEB_ROOT}/veercanvas/admin"
ADMIN_APP="${ADMIN_DIR}/admin_app.py"
SERVICE_NAME="${VEERCANVAS_SERVICE_NAME:-veercanvas-admin}"

if [[ ! -f "$WEB_ROOT/index.html" ]]; then
  echo "error: site index.html not found in WEB_ROOT=$WEB_ROOT" >&2
  exit 1
fi

install_nginx_config() {
  local target="$NGINX_SITES_AVAILABLE/$DOMAIN"
  local example="${SCRIPT_DIR}/nginx/examples/${DOMAIN}.conf"
  if [[ -f "$example" ]]; then
    echo "Using nginx example: $example"
    cp "$example" "$target"
    return
  fi
  if [[ -f "${WEB_ROOT}/deploy/nginx_${DOMAIN}.conf" ]]; then
    cp "${WEB_ROOT}/deploy/nginx_${DOMAIN}.conf" "$target"
    return
  fi
  echo "Writing fallback nginx config for $DOMAIN"
  tee "$target" > /dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    root $WEB_ROOT;
    index index.html;
    location = /admin { return 301 /admin/; }
    location ^~ /admin/ { proxy_pass http://127.0.0.1:8080/; proxy_set_header Host \$host; }
    location ^~ /static/ { proxy_pass http://127.0.0.1:8080/static/; }
    location ^~ /site/ { proxy_pass http://127.0.0.1:8080/site/; }
    location ^~ /api/ { proxy_pass http://127.0.0.1:8080/api/; }
    location / { try_files \$uri \$uri/ =404; }
}
EOF
}

setup_admin_service() {
  if [[ ! -f "$ADMIN_APP" ]]; then
    if [[ -f "${WEB_ROOT}/deploy/admin_app.py" ]]; then
      echo "Using legacy admin at ${WEB_ROOT}/deploy/admin_app.py"
      ADMIN_DIR="${WEB_ROOT}/deploy"
      ADMIN_APP="${ADMIN_DIR}/admin_app.py"
    else
      echo "Admin app not found — skipping service setup."
      return
    fi
  fi

  echo "Preparing VeerCanvas admin virtualenv ..."
  if [[ ! -d "$WEB_ROOT/venv" ]]; then
    python3 -m venv "$WEB_ROOT/venv"
  fi
  chown -R ubuntu:ubuntu "$WEB_ROOT/venv" 2>/dev/null || true
  sudo -u ubuntu "$WEB_ROOT/venv/bin/pip" install --upgrade pip >/dev/null
  sudo -u ubuntu "$WEB_ROOT/venv/bin/pip" install -r "${ADMIN_DIR}/requirements.txt"

  echo "Installing systemd service ${SERVICE_NAME} ..."
  tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=VeerCanvas Admin
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$WEB_ROOT
Environment=VEERCANVAS_ROOT=${WEB_ROOT}/veercanvas
Environment=VEERCANVAS_SITE_ROOT=$WEB_ROOT
Environment=VEER_SITE_ROOT=$WEB_ROOT
Environment=PATH=$WEB_ROOT/venv/bin:/usr/bin:/bin
ExecStart=$WEB_ROOT/venv/bin/python $ADMIN_APP
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl stop veerlabs-admin.service 2>/dev/null || true
  systemctl disable veerlabs-admin.service 2>/dev/null || true
  systemctl enable "${SERVICE_NAME}.service"
  systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  if ! systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    echo "error: ${SERVICE_NAME} failed to start" >&2
    journalctl -u "${SERVICE_NAME}" -n 40 --no-pager >&2 || true
    exit 1
  fi
  echo "Admin service ${SERVICE_NAME} is active on port 8080"
}

echo "[1/3] Nginx config for $DOMAIN"
install_nginx_config
echo "[2/3] VeerCanvas admin service"
setup_admin_service
echo "[3/3] Reload nginx"
ln -sf "$NGINX_SITES_AVAILABLE/$DOMAIN" "$NGINX_SITES_ENABLED/$DOMAIN"
nginx -t
systemctl reload nginx
echo "Site: https://$DOMAIN/"
echo "Admin: https://$DOMAIN/admin/"
