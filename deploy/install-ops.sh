#!/usr/bin/env bash
# Install Phase-1 on-box ops: daily backup cron, journald retention, logrotate.
# Invoked from site-deploy.sh (root) after a successful site install.
#
# Usage:
#   sudo SITE_ID=hbcsanyard WEB_ROOT=/var/www/... DOMAIN=... \
#     bash /var/www/.../veercanvas/deploy/install-ops.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_ID="${SITE_ID:-${VEERCANVAS_SITE_ID:-}}"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-}}"
DOMAIN="${DOMAIN:-}"
SERVICE_NAME="${VEERCANVAS_SERVICE_NAME:-}"

if [[ -z "$SITE_ID" || -z "$WEB_ROOT" ]]; then
  echo "install-ops: skip (SITE_ID/WEB_ROOT required)" >&2
  exit 0
fi

echo "install-ops: site=${SITE_ID} web_root=${WEB_ROOT}"

chmod +x "${SCRIPT_DIR}/backup-site.sh" \
  "${SCRIPT_DIR}/ops/send-ops-alert.py" \
  "${SCRIPT_DIR}/ops/prune-access-events.py" \
  "${SCRIPT_DIR}/ops/check-server-vitals.sh" \
  "${SCRIPT_DIR}/ops/write-ops-status.py" \
  "${SCRIPT_DIR}/ops/load-site-env.sh" \
  "${SCRIPT_DIR}/ops/sync-to-drive.sh" \
  "${SCRIPT_DIR}/ops/sync-to-drive.py" \
  "${SCRIPT_DIR}/ops/authorize-drive.py"

# Hot SQLite backups need the CLI. Plate OCR uses Tesseract when no native binary is present.
NEED_APT=()
if ! command -v sqlite3 >/dev/null 2>&1; then
  NEED_APT+=(sqlite3)
fi
if ! command -v tesseract >/dev/null 2>&1; then
  NEED_APT+=(tesseract-ocr tesseract-ocr-eng)
fi
if ((${#NEED_APT[@]})); then
  echo "install-ops: installing ${NEED_APT[*]}…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq "${NEED_APT[@]}"
fi

# Drive sync Python deps in a dedicated venv (PEP 668 / Ubuntu 24+)
DRIVE_VENV="${DRIVE_VENV:-${WEB_ROOT}/data/drive-venv}"
echo "install-ops: ensuring Google Drive venv at ${DRIVE_VENV}…"
mkdir -p "$(dirname "$DRIVE_VENV")"
if [[ ! -x "${DRIVE_VENV}/bin/python" ]]; then
  python3 -m venv "$DRIVE_VENV" || echo "install-ops: warning: venv create failed" >&2
fi
if [[ -x "${DRIVE_VENV}/bin/pip" ]]; then
  "${DRIVE_VENV}/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
  "${DRIVE_VENV}/bin/pip" install --quiet 'google-api-python-client>=2.100' 'google-auth>=2.20' 'google-auth-oauthlib>=1.2' \
    || echo "install-ops: warning: could not pip-install Drive deps into venv" >&2
else
  echo "install-ops: warning: Drive venv pip missing" >&2
fi
chown -R ubuntu:ubuntu "$DRIVE_VENV" 2>/dev/null || true

mkdir -p /var/backups/veercanvas /var/log/veercanvas /var/lib/veercanvas/vitals /etc/systemd/journald.conf.d
chmod 750 /var/backups/veercanvas /var/log/veercanvas /var/lib/veercanvas
# Allow ubuntu (deploy user) to inspect backups
chown root:ubuntu /var/backups/veercanvas 2>/dev/null || true
chmod 750 /var/backups/veercanvas 2>/dev/null || true

if [[ -f "${WEB_ROOT}/data/drive.env.example" && ! -f "${WEB_ROOT}/data/drive.env" ]]; then
  cp "${WEB_ROOT}/data/drive.env.example" "${WEB_ROOT}/data/drive.env"
  chmod 600 "${WEB_ROOT}/data/drive.env" || true
  chown ubuntu:ubuntu "${WEB_ROOT}/data/drive.env" 2>/dev/null || true
  echo "install-ops: created data/drive.env from example"
fi

# Journald retention (shared across sites)
cp "${SCRIPT_DIR}/ops/journald-veercanvas.conf" /etc/systemd/journald.conf.d/veercanvas.conf
systemctl restart systemd-journald 2>/dev/null || true

# Logrotate
cp "${SCRIPT_DIR}/ops/logrotate-nginx-veercanvas" /etc/logrotate.d/veercanvas-nginx
cp "${SCRIPT_DIR}/ops/logrotate-backup-logs" /etc/logrotate.d/veercanvas-backup

# Daily backup at 02:30 local server time
CRON_FILE="/etc/cron.d/veercanvas-backup-${SITE_ID}"
cat > "$CRON_FILE" <<EOF
# VeerCanvas Phase-1 on-box backup for ${SITE_ID}
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
30 2 * * * root SITE_ID=${SITE_ID} WEB_ROOT=${WEB_ROOT} VEERCANVAS_SERVICE_NAME=${SERVICE_NAME} ${SCRIPT_DIR}/backup-site.sh >> /var/log/veercanvas/backup-${SITE_ID}.log 2>&1
EOF
chmod 644 "$CRON_FILE"

# Vital metrics every 15 minutes (disk, memory, load, services, backup age)
VITALS_CRON="/etc/cron.d/veercanvas-vitals-${SITE_ID}"
cat > "$VITALS_CRON" <<EOF
# VeerCanvas server vitals for ${SITE_ID}
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""
*/15 * * * * root SITE_ID=${SITE_ID} WEB_ROOT=${WEB_ROOT} VEERCANVAS_SERVICE_NAME=${SERVICE_NAME} ${SCRIPT_DIR}/ops/check-server-vitals.sh >> /var/log/veercanvas/vitals-${SITE_ID}.log 2>&1
EOF
chmod 644 "$VITALS_CRON"

# Optional one-shot dry run when INSTALL_OPS_RUN_NOW=1
if [[ "${INSTALL_OPS_RUN_NOW:-0}" == "1" ]]; then
  echo "install-ops: running backup once now…"
  SITE_ID="$SITE_ID" WEB_ROOT="$WEB_ROOT" VEERCANVAS_SERVICE_NAME="$SERVICE_NAME" \
    "${SCRIPT_DIR}/backup-site.sh" || echo "install-ops: warning: initial backup failed" >&2
fi

echo "install-ops: cron ${CRON_FILE}"
echo "install-ops: vitals cron ${VITALS_CRON} (every 15 min)"
echo "install-ops: backups → /var/backups/veercanvas/${SITE_ID}/"
echo "install-ops: logs → /var/log/veercanvas/backup-${SITE_ID}.log"
echo "install-ops: vitals log → /var/log/veercanvas/vitals-${SITE_ID}.log"
echo "install-ops: done"
