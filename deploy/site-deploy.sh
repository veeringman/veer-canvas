#!/bin/bash
# On-host VeerCanvas setup: nginx, admin systemd, venv.
# Usually invoked by deploy/remote-deploy.sh after rsync.
#
# Usage:
#   sudo VEERCANVAS_SITE_ROOT=/var/www/veerlabs.solutions DOMAIN=veerlabs.solutions \
#     ADMIN_PORT=8080 VEERCANVAS_SERVICE_NAME=veercanvas-admin \
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
ADMIN_PORT="${ADMIN_PORT:-8080}"
IS_PLATFORM="${VEERCANVAS_PLATFORM:-0}"
IS_OPS="${VEERCANVAS_OPS:-0}"
SITE_ID="${VEERCANVAS_SITE_ID:-}"
CMS_PREFIX="${CMS_PREFIX:-${VEERCANVAS_ADMIN_PREFIX:-/admin}}"

if [[ ! -f "$WEB_ROOT/index.html" ]]; then
  echo "error: site index.html not found in WEB_ROOT=$WEB_ROOT" >&2
  exit 1
fi

rewrite_admin_port() {
  local file="$1"
  # Rewrite CMS admin upstreams only. Never touch VeerSetu AuthBuddy bind :18080
  # (or other non-admin ports used by /agent/ and /auth/ proxies).
  sed -i -E "s|127\\.0\\.0\\.1:808[0-9]\\b|127.0.0.1:${ADMIN_PORT}|g" "$file"
}

install_nginx_config() {
  local target="$NGINX_SITES_AVAILABLE/$DOMAIN"
  local example="${SCRIPT_DIR}/nginx/examples/${DOMAIN}.conf"
  local has_cert=0
  if [[ -f "${CERT_DIR}/fullchain.pem" && -f "${CERT_DIR}/privkey.pem" ]]; then
    has_cert=1
  fi

  if [[ -f "$example" && "$has_cert" == "1" ]]; then
    echo "Using nginx example: $example"
    cp "$example" "$target"
    rewrite_admin_port "$target"
    return
  fi

  if [[ -f "${WEB_ROOT}/deploy/nginx_${DOMAIN}.conf" && "$has_cert" == "1" ]]; then
    cp "${WEB_ROOT}/deploy/nginx_${DOMAIN}.conf" "$target"
    rewrite_admin_port "$target"
    return
  fi

  echo "Writing HTTP nginx config for $DOMAIN (port ${ADMIN_PORT}; cert present=${has_cert}; ops=${IS_OPS})"
  if [[ "$IS_OPS" == "1" || "$IS_OPS" == "true" ]]; then
    tee "$target" > /dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    root $WEB_ROOT;
    index index.html;
    client_max_body_size 20m;

    # Ops: observability dashboard at /; pure CMS at /admin/
    location = /admin { return 301 /admin/; }
    location ^~ /admin/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix /admin;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }
    location ^~ /static/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/static/;
        proxy_set_header Host \$host;
    }
    location ^~ /site/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/site/;
        proxy_set_header Host \$host;
    }
    location = /login { return 302 /admin/login?next=/; }
    location = /logout { return 302 /admin/logout; }
    location ^~ /api/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location / { try_files \$uri \$uri/ /index.html; }
    location = /projects.json { return 404; }
}
EOF
    return
  fi

  tee "$target" > /dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
    server_tokens off;
    root $WEB_ROOT;
    index index.html;
    client_max_body_size 20m;

    error_page 403 /errors/403.html;
    error_page 404 /errors/404.html;
    error_page 500 /errors/500.html;
    error_page 502 /errors/502.html;
    error_page 503 /errors/503.html;
    error_page 504 /errors/504.html;

    location = /admin { return 301 /admin/; }
    location ^~ /admin/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix /admin;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        proxy_intercept_errors on;
    }
    location ^~ /static/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/static/;
        proxy_set_header Host \$host;
        proxy_intercept_errors on;
    }
    location ^~ /site/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/site/;
        proxy_set_header Host \$host;
        proxy_intercept_errors on;
    }
    location = /login { return 302 /admin/login; }
    location = /logout { return 302 /admin/logout; }
    location ^~ /api/ {
        proxy_pass http://127.0.0.1:${ADMIN_PORT}/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_intercept_errors on;
    }
    # AuthBuddy via VeerSetu connect on EC2 (127.0.0.1:18080) — not LAN IP.
    location ^~ /agent/ {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_set_header Host authbuddy.veerlabs.solutions;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_intercept_errors on;
    }
    location ^~ /auth/ {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_set_header Host authbuddy.veerlabs.solutions;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_intercept_errors on;
    }
    location / { try_files \$uri \$uri/ =404; }
    location = /projects.json { return 404; }
}
EOF
}

ensure_tls() {
  if [[ -f "${CERT_DIR}/fullchain.pem" && -f "${CERT_DIR}/privkey.pem" ]]; then
    return
  fi
  if ! command -v certbot >/dev/null 2>&1; then
    echo "Warning: certbot not installed; leaving $DOMAIN on HTTP."
    return
  fi
  echo "Requesting Let's Encrypt certificate for $DOMAIN ..."
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email --redirect || \
    certbot certonly --webroot -w "$WEB_ROOT" -d "$DOMAIN" \
      --non-interactive --agree-tos --register-unsafely-without-email || true

  # Optional www alias when DNS exists.
  if getent hosts "www.$DOMAIN" >/dev/null 2>&1; then
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos \
      --register-unsafely-without-email --expand --redirect || true
  fi

  if [[ -f "${CERT_DIR}/fullchain.pem" ]]; then
    local example="${SCRIPT_DIR}/nginx/examples/${DOMAIN}.conf"
    if [[ -f "$example" ]]; then
      cp "$example" "$NGINX_SITES_AVAILABLE/$DOMAIN"
      rewrite_admin_port "$NGINX_SITES_AVAILABLE/$DOMAIN"
    fi
  fi
}

install_extra_domains() {
  local extra example http_example target cert_dir
  for extra in ${EXTRA_DOMAINS:-}; do
    [[ -n "$extra" && "$extra" != "$DOMAIN" ]] || continue
    example="${SCRIPT_DIR}/nginx/examples/${extra}.conf"
    http_example="${SCRIPT_DIR}/nginx/examples/${extra}.http.conf"
    target="$NGINX_SITES_AVAILABLE/$extra"
    cert_dir="/etc/letsencrypt/live/${extra}"
    echo "Installing extra domain vhost: $extra (web root stays $WEB_ROOT)"
    if [[ -f "${cert_dir}/fullchain.pem" && -f "${cert_dir}/privkey.pem" && -f "$example" ]]; then
      cp "$example" "$target"
    elif [[ -f "$http_example" ]]; then
      cp "$http_example" "$target"
    elif [[ -f "$example" ]]; then
      cp "$example" "$target"
    else
      echo "warning: no nginx example for extra domain $extra" >&2
      continue
    fi
    rewrite_admin_port "$target"
    ln -sf "$target" "$NGINX_SITES_ENABLED/$extra"
    nginx -t
    systemctl reload nginx
    if [[ ! -f "${cert_dir}/fullchain.pem" ]]; then
      if command -v certbot >/dev/null 2>&1; then
        echo "Requesting Let's Encrypt certificate for $extra ..."
        certbot certonly --webroot -w "$WEB_ROOT" -d "$extra" -d "www.$extra" \
          --non-interactive --agree-tos --register-unsafely-without-email \
          || echo "warning: TLS for $extra not issued yet (check DNS A records point only at this host)" >&2
      fi
      if [[ -f "${cert_dir}/fullchain.pem" && -f "$example" ]]; then
        cp "$example" "$target"
        rewrite_admin_port "$target"
        nginx -t
        systemctl reload nginx
      fi
    fi
  done
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

  local platform_env="0"
  local ops_env="0"
  if [[ "$IS_PLATFORM" == "1" || "$IS_PLATFORM" == "true" ]]; then
    platform_env="1"
  fi
  if [[ "$IS_OPS" == "1" || "$IS_OPS" == "true" ]]; then
    ops_env="1"
  fi

  echo "Installing systemd service ${SERVICE_NAME} (port ${ADMIN_PORT}, platform=${platform_env}, ops=${ops_env}) ..."
  tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=VeerCanvas Admin (${DOMAIN})
After=network.target

[Service]
User=ubuntu
WorkingDirectory=$WEB_ROOT
Environment=VEERCANVAS_ROOT=${WEB_ROOT}/veercanvas
Environment=VEERCANVAS_SITE_ROOT=$WEB_ROOT
Environment=VEER_SITE_ROOT=$WEB_ROOT
Environment=VEERCANVAS_SITE_ID=${SITE_ID}
Environment=VEERCANVAS_PLATFORM=${platform_env}
Environment=VEERCANVAS_OPS=${ops_env}
Environment=VEERCANVAS_ADMIN_PREFIX=${CMS_PREFIX:-/admin}
Environment=PORT=${ADMIN_PORT}
Environment=VEERCANVAS_ADMIN_PORT=${ADMIN_PORT}
Environment=PATH=$WEB_ROOT/venv/bin:/usr/bin:/bin
EnvironmentFile=-$WEB_ROOT/data/smtp.env
EnvironmentFile=-$WEB_ROOT/data/vapid.env
EnvironmentFile=-$WEB_ROOT/data/ai.env
EnvironmentFile=-/etc/veercanvas/${SITE_ID}.env
ExecStart=$WEB_ROOT/venv/bin/python $ADMIN_APP
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  if [[ "$SERVICE_NAME" != "veerlabs-admin" ]]; then
    systemctl stop veerlabs-admin.service 2>/dev/null || true
    systemctl disable veerlabs-admin.service 2>/dev/null || true
  fi
  systemctl enable "${SERVICE_NAME}.service"
  systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  if ! systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    echo "error: ${SERVICE_NAME} failed to start" >&2
    journalctl -u "${SERVICE_NAME}" -n 40 --no-pager >&2 || true
    exit 1
  fi
  echo "Admin service ${SERVICE_NAME} is active on port ${ADMIN_PORT}"
}

echo "[1/4] Nginx config for $DOMAIN"
install_nginx_config
echo "[2/4] VeerCanvas admin service"
setup_admin_service
echo "[3/4] Enable site + TLS"
ln -sf "$NGINX_SITES_AVAILABLE/$DOMAIN" "$NGINX_SITES_ENABLED/$DOMAIN"
nginx -t
systemctl reload nginx
ensure_tls
echo "[3b/4] Extra domains (${EXTRA_DOMAINS:-none})"
install_extra_domains
echo "[4/4] Reload nginx"
nginx -t
systemctl reload nginx

if [[ -n "${SITE_ID}" ]]; then
  echo "[ops] Installing Phase-1 backup + log retention for ${SITE_ID}"
  SITE_ID="$SITE_ID" WEB_ROOT="$WEB_ROOT" DOMAIN="$DOMAIN" \
    VEERCANVAS_SERVICE_NAME="$SERVICE_NAME" \
    bash "${SCRIPT_DIR}/install-ops.sh" || echo "warning: install-ops failed (non-fatal)" >&2
fi

echo "Site: https://$DOMAIN/ (or http if cert pending)"
echo "CMS: https://$DOMAIN${CMS_PREFIX}/"
if [[ "${CMS_PREFIX}" != "/admin" ]]; then
  echo "Portal desk: https://$DOMAIN/admin/"
fi
