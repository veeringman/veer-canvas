#!/usr/bin/env bash
# On-box Phase-1 backup for a VeerCanvas site.
#
# Usage (on EC2, usually via cron):
#   SITE_ID=hbcsanyard /var/www/.../veercanvas/deploy/backup-site.sh
#   WEB_ROOT=/var/www/hbcsanyard.veerlabs.solutions ./backup-site.sh
#
# Env:
#   RETAIN_DAYS=14          keep dated backups this many days
#   DISK_MIN_PCT=15         fail+alert if free space on backup volume below this %
#   ACCESS_EVENTS_DAYS=90   prune access_events older than this
#   BACKUP_ROOT=/var/backups/veercanvas/<site-id>
#   ALERT_ON_SUCCESS=0      set 1 to email on success too

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEERCANVAS_ROOT="${VEERCANVAS_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

SITE_ID="${SITE_ID:-}"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname || echo host)"

resolve_web_root() {
  if [[ -n "$WEB_ROOT" ]]; then
    return
  fi
  if [[ -z "$SITE_ID" ]]; then
    echo "error: set SITE_ID or WEB_ROOT" >&2
    exit 2
  fi
  local cfg="${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json"
  if [[ -f "$cfg" ]]; then
    WEB_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("webRoot") or "")' "$cfg")"
  fi
  if [[ -z "$WEB_ROOT" ]]; then
    echo "error: could not resolve WEB_ROOT for SITE_ID=$SITE_ID" >&2
    exit 2
  fi
}

resolve_web_root
SITE_ID="${SITE_ID:-$(basename "$WEB_ROOT" | cut -d. -f1)}"
# Load thresholds / alert email from super-admin settings (data/smtp.env).
# shellcheck source=ops/load-site-env.sh
source "${SCRIPT_DIR}/ops/load-site-env.sh"
load_site_env "$WEB_ROOT"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-${RETAIN_DAYS:-14}}"
DISK_MIN_PCT="${DISK_MIN_PCT:-15}"
ACCESS_EVENTS_DAYS="${ACCESS_EVENTS_DAYS:-90}"
ALERT_ON_SUCCESS="${ALERT_ON_SUCCESS:-0}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/veercanvas/${SITE_ID}}"
RUN_DIR="${BACKUP_ROOT}/${STAMP}"
LOG_TAG="veercanvas-backup:${SITE_ID}"
FAILED=0
FAIL_MSG=""

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

alert() {
  local subject="$1"
  local body="$2"
  python3 "${SCRIPT_DIR}/ops/send-ops-alert.py" \
    --site-root "$WEB_ROOT" \
    --subject "$subject" \
    --body "$body" 2>&1 || true
}

fail() {
  FAILED=1
  FAIL_MSG="$*"
  log "ERROR: $*"
}

cleanup_on_exit() {
  local rc=$?
  if [[ "$FAILED" == "1" || "$rc" -ne 0 ]]; then
    local detail="${FAIL_MSG:-exit $rc}"
    python3 "${SCRIPT_DIR}/ops/write-ops-status.py" \
      --site-root "$WEB_ROOT" \
      --section lastBackup \
      --json "{\"ok\":false,\"error\":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$detail")}" 2>/dev/null || true
    alert \
      "[VeerCanvas] Backup FAILED · ${SITE_ID} · ${HOSTNAME_SHORT}" \
      "Site: ${SITE_ID}
Host: ${HOSTNAME_SHORT}
Web root: ${WEB_ROOT}
Backup root: ${BACKUP_ROOT}
Stamp: ${STAMP}
Error: ${detail}

Check: journalctl / /var/log/veercanvas/backup-${SITE_ID}.log"
  elif [[ "$ALERT_ON_SUCCESS" == "1" ]]; then
    alert \
      "[VeerCanvas] Backup OK · ${SITE_ID} · ${HOSTNAME_SHORT}" \
      "Site: ${SITE_ID}
Stamp: ${STAMP}
Path: ${RUN_DIR}"
  fi
}
trap cleanup_on_exit EXIT

sqlite_backup() {
  local src="$1"
  local dest="$2"
  if [[ ! -f "$src" ]]; then
    log "skip sqlite: missing $src"
    return 0
  fi
  if ! command -v sqlite3 >/dev/null 2>&1; then
    fail "sqlite3 CLI not installed"
    return 1
  fi
  mkdir -p "$(dirname "$dest")"
  # Consistent hot backup without stopping the app.
  if ! sqlite3 "$src" <<SQL
.backup '${dest}'
SQL
  then
    fail "sqlite backup failed for $src"
    return 1
  fi
  # Verify readable (SQLite returns lowercase "ok").
  local check
  check="$(sqlite3 "$dest" "PRAGMA integrity_check;" 2>/dev/null | head -n1 | tr '[:upper:]' '[:lower:]')"
  if [[ "$check" != "ok" ]]; then
    fail "integrity check failed for $dest (${check:-empty})"
    return 1
  fi
  log "sqlite ok: $(basename "$src") -> $(basename "$dest")"
}

check_disk() {
  local target="$1"
  mkdir -p "$target"
  local avail_pct
  avail_pct="$(df -P "$target" | awk 'NR==2 { gsub(/%/,"",$5); print 100-$5 }')"
  if [[ -z "$avail_pct" ]]; then
    log "warn: could not read free disk %"
    return 0
  fi
  log "disk free on $(df -P "$target" | awk 'NR==2{print $6}'): ${avail_pct}%"
  if (( avail_pct < DISK_MIN_PCT )); then
    fail "disk free ${avail_pct}% below minimum ${DISK_MIN_PCT}%"
    return 1
  fi
}

prune_old_backups() {
  mkdir -p "$BACKUP_ROOT"
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETAIN_DAYS}" -print -exec rm -rf {} + 2>/dev/null || true
  # Also drop orphan incomplete dirs older than retention if any.
  log "retention: kept backups newer than ${RETAIN_DAYS} days under $BACKUP_ROOT"
}

log "=== backup start site=${SITE_ID} web_root=${WEB_ROOT} ==="
if ! check_disk "$BACKUP_ROOT"; then
  exit 1
fi
mkdir -p "$RUN_DIR"/{db,uploads,configs}
chmod 750 "$BACKUP_ROOT" "$RUN_DIR" 2>/dev/null || true

# --- SQLite ---
sqlite_backup "${WEB_ROOT}/data/rwa.db" "${RUN_DIR}/db/rwa.db" || true
sqlite_backup "${WEB_ROOT}/veercanvas/admin/admin.db" "${RUN_DIR}/db/admin.db" || true
# Legacy / alternate admin db locations
sqlite_backup "${WEB_ROOT}/admin/admin.db" "${RUN_DIR}/db/admin-legacy.db" || true

# --- Uploads + secrets (mode 600 for env) ---
UPLOAD_LIST=()
for rel in data/profile-photos data/receipts data/no-dues data/no-objection data/vault data/payments data/info-centre data/attestations data/imports data/messages data/smtp.env data/vapid.env data/ai.env; do
  if [[ -e "${WEB_ROOT}/${rel}" ]]; then
    UPLOAD_LIST+=("$rel")
  fi
done
if ((${#UPLOAD_LIST[@]})); then
  tar -C "$WEB_ROOT" -czf "${RUN_DIR}/uploads/data-bundle.tgz" "${UPLOAD_LIST[@]}"
  chmod 600 "${RUN_DIR}/uploads/data-bundle.tgz" 2>/dev/null || true
  log "uploads archive: ${#UPLOAD_LIST[@]} paths"
else
  log "skip uploads: nothing present"
fi

# --- Configs ---
CFG_TMP="${RUN_DIR}/configs/_staging"
mkdir -p "$CFG_TMP"
SERVICE_NAME="${VEERCANVAS_SERVICE_NAME:-}"
if [[ -z "$SERVICE_NAME" && -f "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" ]]; then
  SERVICE_NAME="$(python3 -c 'import json,sys; print(((json.load(open(sys.argv[1])).get("admin") or {}).get("serviceName")) or "")' "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" 2>/dev/null || true)"
fi
DOMAIN="$(python3 -c 'import json,sys; p=sys.argv[1];
import pathlib
c=pathlib.Path(p)
print(json.load(open(c)).get("domain","") if c.is_file() else "")' "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" 2>/dev/null || true)"
[[ -z "$DOMAIN" ]] && DOMAIN="$(basename "$WEB_ROOT")"

if [[ -n "$SERVICE_NAME" && -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
  cp "/etc/systemd/system/${SERVICE_NAME}.service" "$CFG_TMP/"
fi
if [[ -f "/etc/nginx/sites-available/${DOMAIN}" ]]; then
  cp "/etc/nginx/sites-available/${DOMAIN}" "$CFG_TMP/nginx-${DOMAIN}"
fi
if [[ -f "/etc/veercanvas/${SITE_ID}.env" ]]; then
  cp "/etc/veercanvas/${SITE_ID}.env" "$CFG_TMP/veercanvas-${SITE_ID}.env"
  chmod 600 "$CFG_TMP/veercanvas-${SITE_ID}.env" || true
fi
if [[ -f "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" ]]; then
  cp "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" "$CFG_TMP/"
elif [[ -f "${WEB_ROOT}/veercanvas/sites/${SITE_ID}/site.config.json" ]]; then
  cp "${WEB_ROOT}/veercanvas/sites/${SITE_ID}/site.config.json" "$CFG_TMP/"
fi
if compgen -G "${CFG_TMP}/*" >/dev/null; then
  tar -C "$CFG_TMP" -czf "${RUN_DIR}/configs/configs.tgz" .
  rm -rf "$CFG_TMP"
  log "configs archived"
else
  rm -rf "$CFG_TMP"
  log "skip configs: none found"
fi

# --- Manifest ---
{
  echo "site_id=${SITE_ID}"
  echo "stamp=${STAMP}"
  echo "host=${HOSTNAME_SHORT}"
  echo "web_root=${WEB_ROOT}"
  echo "retain_days=${RETAIN_DAYS}"
  echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "files:"
  find "$RUN_DIR" -type f -printf '  %P %s\n' | sort
} > "${RUN_DIR}/MANIFEST.txt"

# Convenience archive of the whole run (easier to copy off-box later)
tar -C "$BACKUP_ROOT" -czf "${BACKUP_ROOT}/${SITE_ID}-${STAMP}.tgz" "$STAMP"
chmod 600 "${BACKUP_ROOT}/${SITE_ID}-${STAMP}.tgz" 2>/dev/null || true
ln -sfn "$STAMP" "${BACKUP_ROOT}/latest"
ln -sfn "${SITE_ID}-${STAMP}.tgz" "${BACKUP_ROOT}/latest.tgz"

# --- Log / event rollover pieces run with backup ---
RWA_DB="${WEB_ROOT}/data/rwa.db"
if [[ -f "$RWA_DB" ]]; then
  python3 "${SCRIPT_DIR}/ops/prune-access-events.py" "$RWA_DB" --days "$ACCESS_EVENTS_DAYS" || log "warn: access_events prune failed"
fi

prune_old_backups
# Drop matching .tgz older than retention
find "$BACKUP_ROOT" -maxdepth 1 -type f -name "${SITE_ID}-*.tgz" -mtime "+${RETAIN_DAYS}" -delete 2>/dev/null || true

if [[ "$FAILED" == "1" ]]; then
  exit 1
fi
python3 "${SCRIPT_DIR}/ops/write-ops-status.py" \
  --site-root "$WEB_ROOT" \
  --section lastBackup \
  --json "{\"ok\":true,\"path\":\"${RUN_DIR}\",\"stamp\":\"${STAMP}\"}" 2>/dev/null || true

# Optional Phase-2 Drive upload
if [[ "${DRIVE_ENABLED:-0}" == "1" ]]; then
  log "Drive sync starting…"
  SITE_ID="$SITE_ID" WEB_ROOT="$WEB_ROOT" \
    bash "${SCRIPT_DIR}/ops/sync-to-drive.sh" || log "warn: Drive sync failed"
fi

log "=== backup ok -> ${RUN_DIR} ==="
exit 0
