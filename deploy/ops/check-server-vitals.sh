#!/usr/bin/env bash
# Monitor server vitals and email when nearing critical levels.
#
# Usage:
#   SITE_ID=hbcsanyard WEB_ROOT=/var/www/... ./check-server-vitals.sh
#
# Env (defaults):
#   DISK_WARN_PCT=20      alert when free disk % at or below
#   DISK_CRIT_PCT=10      critical when free disk % at or below
#   MEM_WARN_PCT=15       alert when MemAvailable % at or below
#   MEM_CRIT_PCT=8        critical when MemAvailable % at or below
#   LOAD_WARN_RATIO=1.5   load1 / cpu_count
#   LOAD_CRIT_RATIO=2.5
#   BACKUP_MAX_AGE_H=28   critical if latest backup older than this (hours)
#   ALERT_COOLDOWN_WARN=21600   seconds between repeat warn emails (6h)
#   ALERT_COOLDOWN_CRIT=3600    seconds between repeat critical emails (1h)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VEERCANVAS_ROOT="${VEERCANVAS_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

SITE_ID="${SITE_ID:-}"
WEB_ROOT="${WEB_ROOT:-${VEERCANVAS_SITE_ROOT:-}}"
SERVICE_NAME="${VEERCANVAS_SERVICE_NAME:-}"

HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname || echo host)"
STATE_DIR="/var/lib/veercanvas/vitals"
STATE_FILE=""

if [[ -z "$WEB_ROOT" && -n "$SITE_ID" ]]; then
  for cfg in \
    "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" \
    "${WEB_ROOT}/veercanvas/sites/${SITE_ID}/site.config.json"; do
    if [[ -f "$cfg" ]]; then
      WEB_ROOT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("webRoot") or "")' "$cfg")"
      break
    fi
  done
fi
if [[ -z "$WEB_ROOT" ]]; then
  echo "error: set WEB_ROOT or SITE_ID" >&2
  exit 2
fi
SITE_ID="${SITE_ID:-$(basename "$WEB_ROOT" | cut -d. -f1)}"
# shellcheck source=load-site-env.sh
source "${SCRIPT_DIR}/load-site-env.sh"
load_site_env "$WEB_ROOT"
DISK_WARN_PCT="${DISK_WARN_PCT:-20}"
DISK_CRIT_PCT="${DISK_CRIT_PCT:-10}"
MEM_WARN_PCT="${MEM_WARN_PCT:-15}"
MEM_CRIT_PCT="${MEM_CRIT_PCT:-8}"
LOAD_WARN_RATIO="${LOAD_WARN_RATIO:-1.5}"
LOAD_CRIT_RATIO="${LOAD_CRIT_RATIO:-2.5}"
BACKUP_MAX_AGE_H="${BACKUP_MAX_AGE_H:-28}"
ALERT_COOLDOWN_WARN="${ALERT_COOLDOWN_WARN:-21600}"
ALERT_COOLDOWN_CRIT="${ALERT_COOLDOWN_CRIT:-3600}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/veercanvas/${SITE_ID}}"
STATE_FILE="${STATE_DIR}/${SITE_ID}.state"

if [[ "${OPS_VITALS_ENABLED:-1}" == "0" ]] || [[ "$(echo "${OPS_VITALS_ENABLED:-1}" | tr '[:upper:]' '[:lower:]')" == "false" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] vitals disabled (OPS_VITALS_ENABLED)"
  exit 0
fi

if [[ -z "$SERVICE_NAME" ]]; then
  for cfg in \
    "${VEERCANVAS_ROOT}/sites/${SITE_ID}/site.config.json" \
    "${WEB_ROOT}/veercanvas/sites/${SITE_ID}/site.config.json"; do
    if [[ -f "$cfg" ]]; then
      SERVICE_NAME="$(python3 -c 'import json,sys; print(((json.load(open(sys.argv[1])).get("admin") or {}).get("serviceName")) or "")' "$cfg" 2>/dev/null || true)"
      break
    fi
  done
fi

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

alert() {
  python3 "${SCRIPT_DIR}/send-ops-alert.py" \
    --site-root "$WEB_ROOT" \
    --subject "$1" \
    --body "$2" 2>&1 || true
}

# Returns: warn|crit|ok (severity for a metric)
disk_free_pct() {
  local mount="$1"
  df -P "$mount" 2>/dev/null | awk 'NR==2 { gsub(/%/,"",$5); print 100-$5 }'
}

disk_severity() {
  local mount="$1"
  local free
  free="$(disk_free_pct "$mount")"
  [[ -z "$free" ]] && { echo "ok"; return; }
  if (( free <= DISK_CRIT_PCT )); then echo "crit"
  elif (( free <= DISK_WARN_PCT )); then echo "warn"
  else echo "ok"
  fi
}

mem_available_pct() {
  awk '/MemAvailable:/ { avail=$2 } /MemTotal:/ { total=$2 } END {
    if (total+0 > 0) printf "%.0f", (avail/total)*100; else print "100"
  }' /proc/meminfo 2>/dev/null || echo "100"
}

mem_severity() {
  local free
  free="$(mem_available_pct)"
  if (( free <= MEM_CRIT_PCT )); then echo "crit"
  elif (( free <= MEM_WARN_PCT )); then echo "warn"
  else echo "ok"
  fi
}

load_severity() {
  local cpus load1 ratio
  cpus="$(nproc 2>/dev/null || echo 1)"
  load1="$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)"
  ratio="$(python3 -c "print(round(float('$load1') / max(1, int('$cpus')), 2))" 2>/dev/null || echo 0)"
  if awk "BEGIN { exit !($ratio >= $LOAD_CRIT_RATIO) }"; then echo "crit"
  elif awk "BEGIN { exit !($ratio >= $LOAD_WARN_RATIO) }"; then echo "warn"
  else echo "ok"
  fi
}

service_severity() {
  local svc="$1"
  [[ -z "$svc" ]] && { echo "ok"; return; }
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    echo "ok"
  else
    echo "crit"
  fi
}

nginx_severity() {
  if systemctl is-active --quiet nginx 2>/dev/null; then echo "ok"
  else echo "crit"
  fi
}

backup_severity() {
  local latest="${BACKUP_ROOT}/latest/db/rwa.db"
  if [[ ! -f "$latest" ]]; then
    echo "warn"
    return
  fi
  local age_h
  age_h="$(python3 -c "
import os, time
p = '$latest'
age = (time.time() - os.path.getmtime(p)) / 3600
print(int(age))
" 2>/dev/null || echo 999)"
  if (( age_h >= BACKUP_MAX_AGE_H )); then echo "crit"
  elif (( age_h >= BACKUP_MAX_AGE_H - 4 )); then echo "warn"
  else echo "ok"
  fi
}

max_sev() {
  local a="$1" b="$2"
  if [[ "$a" == "crit" || "$b" == "crit" ]]; then echo "crit"
  elif [[ "$a" == "warn" || "$b" == "warn" ]]; then echo "warn"
  else echo "ok"
  fi
}

should_alert() {
  local key="$1" sev="$2"
  [[ "$sev" == "ok" ]] && return 1
  mkdir -p "$STATE_DIR"
  local now last last_sev cooldown
  now="$(date +%s)"
  last=0
  last_sev="ok"
  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE" 2>/dev/null || true
    eval "last=\${last_${key}:-0}"
    eval "last_sev=\${sev_${key}:-ok}"
  fi
  if [[ "$sev" == "crit" ]]; then cooldown="$ALERT_COOLDOWN_CRIT"
  else cooldown="$ALERT_COOLDOWN_WARN"
  fi
  # Always alert on escalation or first time in this severity.
  if [[ "$sev" == "crit" && "$last_sev" != "crit" ]]; then return 0; fi
  if [[ "$last_sev" == "ok" ]]; then return 0; fi
  if (( now - last >= cooldown )); then return 0; fi
  return 1
}

record_alert() {
  local key="$1" sev="$2"
  mkdir -p "$STATE_DIR"
  local now
  now="$(date +%s)"
  touch "$STATE_FILE"
  chmod 600 "$STATE_FILE" 2>/dev/null || true
  # Update state file (simple key=value)
  if grep -q "^last_${key}=" "$STATE_FILE" 2>/dev/null; then
    sed -i "s/^last_${key}=.*/last_${key}=${now}/" "$STATE_FILE"
    sed -i "s/^sev_${key}=.*/sev_${key}=${sev}/" "$STATE_FILE"
  else
    echo "last_${key}=${now}" >> "$STATE_FILE"
    echo "sev_${key}=${sev}" >> "$STATE_FILE"
  fi
}

record_ok() {
  local key="$1"
  if [[ -f "$STATE_FILE" ]] && grep -q "^sev_${key}=" "$STATE_FILE" 2>/dev/null; then
    sed -i "s/^sev_${key}=.*/sev_${key}=ok/" "$STATE_FILE"
  fi
}

build_report() {
  local root_free web_free backup_free mem_pct load1 cpus ratio
  root_free="$(disk_free_pct /)"
  web_free="$(disk_free_pct "$WEB_ROOT" 2>/dev/null || echo "?")"
  backup_free="$(disk_free_pct "$BACKUP_ROOT" 2>/dev/null || echo "?")"
  mem_pct="$(mem_available_pct)"
  cpus="$(nproc 2>/dev/null || echo 1)"
  load1="$(awk '{print $1}' /proc/loadavg)"
  ratio="$(python3 -c "print(round(float('$load1') / max(1, int('$cpus')), 2))" 2>/dev/null || echo "?")"
  cat <<EOF
Site: ${SITE_ID}
Host: ${HOSTNAME_SHORT}
Time (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)

Disk free:
  / (root): ${root_free}% free (warn ≤${DISK_WARN_PCT}%, crit ≤${DISK_CRIT_PCT}%)
  web root: ${web_free}% free
  backups:  ${backup_free}% free

Memory: ${mem_pct}% available (warn ≤${MEM_WARN_PCT}%, crit ≤${MEM_CRIT_PCT}%)
Load: ${load1} on ${cpus} CPU(s) (ratio ${ratio}; warn ≥${LOAD_WARN_RATIO}, crit ≥${LOAD_CRIT_RATIO})

Services:
  ${SERVICE_NAME:-(unset)}: $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || echo inactive)
  nginx: $(systemctl is-active nginx 2>/dev/null || echo inactive)

Backup: ${BACKUP_ROOT}/latest
  $(if [[ -f "${BACKUP_ROOT}/latest/db/rwa.db" ]]; then ls -lh "${BACKUP_ROOT}/latest/db/rwa.db"; else echo "missing"; fi)

Thresholds are in deploy/ops/check-server-vitals.sh and optional smtp.env overrides.
EOF
}

# --- checks ---
OVERALL="ok"
ISSUES=()

check_metric() {
  local key="$1" label="$2" sev="$3" detail="$4"
  OVERALL="$(max_sev "$OVERALL" "$sev")"
  if [[ "$sev" != "ok" ]]; then
    ISSUES+=("${label}: ${detail} [${sev}]")
    if should_alert "$key" "$sev"; then
      NEED_SEND=1
      ALERT_KEYS+=("$key")
      ALERT_SEVS+=("$sev")
    fi
  else
    record_ok "$key"
  fi
}

NEED_SEND=0
ALERT_KEYS=()
ALERT_SEVS=()

# Disk: root, web, backup — use worst of the three
disk_root="$(disk_severity /)"
disk_web="$(disk_severity "$WEB_ROOT")"
disk_backup="$(disk_severity "$BACKUP_ROOT")"
disk_worst="ok"
for d in "$disk_root" "$disk_web" "$disk_backup"; do
  disk_worst="$(max_sev "$disk_worst" "$d")"
done
disk_detail="root $(disk_free_pct /)% free"
check_metric "disk" "Disk" "$disk_worst" "$disk_detail"

mem_s="$(mem_severity)"
check_metric "mem" "Memory" "$mem_s" "$(mem_available_pct)% available"

load_s="$(load_severity)"
load1="$(awk '{print $1}' /proc/loadavg)"
cpus="$(nproc 2>/dev/null || echo 1)"
check_metric "load" "Load" "$load_s" "load ${load1} / ${cpus} CPUs"

svc_s="$(service_severity "${SERVICE_NAME}.service")"
check_metric "service" "Admin service" "$svc_s" "${SERVICE_NAME:-unset}"

ngx_s="$(nginx_severity)"
check_metric "nginx" "Nginx" "$ngx_s" "nginx"

bak_s="$(backup_severity)"
check_metric "backup" "Backup age" "$bak_s" "latest under ${BACKUP_ROOT}"

log "vitals site=${SITE_ID} overall=${OVERALL} issues=${#ISSUES[@]}"

VITALS_JSON="$(python3 - "$OVERALL" "${ISSUES[@]}" <<'PY'
import json, sys
overall = sys.argv[1]
issues = sys.argv[2:]
print(json.dumps({"overall": overall, "issueCount": len(issues), "issues": issues[:12]}))
PY
)"
python3 "${SCRIPT_DIR}/write-ops-status.py" \
  --site-root "$WEB_ROOT" \
  --section lastVitals \
  --json "$VITALS_JSON" 2>/dev/null || true

if [[ "$NEED_SEND" == "1" ]]; then
  level="WARNING"
  [[ "$OVERALL" == "crit" ]] && level="CRITICAL"
  body="Server vitals ${level} on ${HOSTNAME_SHORT}

Issues:
$(printf '  - %s\n' "${ISSUES[@]}")

$(build_report)"
  alert "[VeerCanvas] Server ${level} · ${SITE_ID} · ${HOSTNAME_SHORT}" "$body"
  for i in "${!ALERT_KEYS[@]}"; do
    record_alert "${ALERT_KEYS[$i]}" "${ALERT_SEVS[$i]}"
  done
  log "alert sent (${level})"
fi

if [[ "$OVERALL" == "crit" ]]; then exit 2; fi
if [[ "$OVERALL" == "warn" ]]; then exit 1; fi
exit 0
