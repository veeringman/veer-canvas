#!/usr/bin/env bash
# Obtain/repair the Let's Encrypt cert for syntheon.veerlabs.solutions on the
# AI EC2 (Caddy at 100.52.147.238). Same PEM as the VeerSetu portal host.
#
# Run from a machine that can SSH to that box (Mac + Tailscale):
#   EC2_KEY=~/rnd/projects/VeerSetuHost.pem ./deploy/fix-syntheon-tls.sh

set -euo pipefail

EC2_HOST="${EC2_HOST:-100.52.147.238}"
EC2_USER="${EC2_USER:-ubuntu}"
EC2_KEY="${EC2_KEY:-$HOME/rnd/projects/VeerSetuHost.pem}"
SITE="${SYNTHEON_SITE:-syntheon.veerlabs.solutions}"

if [[ ! -f "$EC2_KEY" ]]; then
  echo "error: SSH key not found at $EC2_KEY" >&2
  exit 1
fi
chmod 600 "$EC2_KEY"
SSH_OPTS=(-i "$EC2_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

echo "SSH ${EC2_USER}@${EC2_HOST} (site ${SITE})"
ssh "${SSH_OPTS[@]}" "${EC2_USER}@${EC2_HOST}" "SITE='$SITE' bash -s" <<'REMOTE'
set -euo pipefail
SITE="${SITE:-syntheon.veerlabs.solutions}"

echo "=== listeners ==="
sudo ss -lntp 2>/dev/null | sed -n '1,80p' || sudo netstat -lntp | sed -n '1,80p'

echo "=== units ==="
systemctl list-units --type=service --state=running --no-pager 2>/dev/null | grep -iE 'caddy|egenie|syntheon|wish|ollama' || true

echo "=== docker ==="
if command -v docker >/dev/null 2>&1; then
  sudo docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Image}}' 2>/dev/null || true
fi

CADDYFILE=""
for cand in /etc/caddy/Caddyfile /etc/caddy/Caddyfile.caddy /home/ubuntu/Caddyfile /opt/caddy/Caddyfile; do
  if sudo test -f "$cand"; then
    CADDYFILE="$cand"
    break
  fi
done
if [[ -z "$CADDYFILE" ]]; then
  CADDYFILE="$(sudo find /etc /opt /home /var -name Caddyfile -type f 2>/dev/null | head -1 || true)"
fi
echo "Caddyfile=${CADDYFILE:-none}"
if [[ -n "$CADDYFILE" ]]; then
  echo "=== Caddyfile ==="
  sudo sed -n '1,200p' "$CADDYFILE"
fi

UPSTREAM="127.0.0.1:8120"
if sudo ss -lntp 2>/dev/null | grep -q ':8120 '; then
  UPSTREAM="127.0.0.1:8120"
elif sudo ss -lntp 2>/dev/null | grep -qi syntheon; then
  UPSTREAM="$(sudo ss -lntp 2>/dev/null | awk '/syntheon/{print $4}' | tail -1)"
else
  # Prefer an existing local API that already answers /health.
  for port in 8120 8110 8080 8090 3000 4000 5000; do
    if curl -fsS --max-time 1 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      UPSTREAM="127.0.0.1:${port}"
      break
    fi
  done
fi
echo "upstream=${UPSTREAM}"

if [[ -z "$CADDYFILE" ]]; then
  echo "error: no Caddyfile found" >&2
  exit 1
fi

CONF_DIR="$(dirname "$CADDYFILE")"
SNIPPET="${CONF_DIR}/syntheon.veerlabs.solutions.caddy"
sudo tee "$SNIPPET" >/dev/null <<EOF
${SITE} {
	encode gzip
	reverse_proxy ${UPSTREAM}
}
EOF

if grep -q "syntheon.veerlabs.solutions" "$CADDYFILE" 2>/dev/null; then
  echo "Caddyfile already mentions syntheon — snippet at $SNIPPET (review by hand if TLS still fails)"
else
  if grep -qE 'import |\*.caddy' "$CADDYFILE"; then
    echo "Caddyfile already has imports; snippet written to $SNIPPET"
    if ! sudo grep -q 'syntheon.veerlabs.solutions.caddy' "$CADDYFILE"; then
      echo "import syntheon.veerlabs.solutions.caddy" | sudo tee -a "$CADDYFILE" >/dev/null
    fi
  else
    echo "" | sudo tee -a "$CADDYFILE" >/dev/null
    sudo cat "$SNIPPET" | sudo tee -a "$CADDYFILE" >/dev/null
    echo "appended site block to $CADDYFILE"
  fi
fi

if systemctl is-active --quiet caddy 2>/dev/null; then
  sudo caddy validate --config "$CADDYFILE" || sudo caddy fmt --overwrite "$CADDYFILE" || true
  sudo systemctl reload caddy || sudo systemctl restart caddy
elif command -v docker >/dev/null 2>&1 && sudo docker ps --format '{{.Names}}' | grep -qi caddy; then
  NAME="$(sudo docker ps --format '{{.Names}}' | grep -i caddy | head -1)"
  sudo docker exec "$NAME" caddy reload --config /etc/caddy/Caddyfile || sudo docker restart "$NAME"
else
  echo "warning: could not reload caddy automatically" >&2
fi

sleep 3
echo "=== local curl ==="
curl -sSI --max-time 8 "http://127.0.0.1/" -H "Host: ${SITE}" | head -15 || true
REMOTE
echo "=== public TLS ==="
sleep 5
echo | openssl s_client -connect "${SITE}:443" -servername "$SITE" 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null || echo "cert not public yet"
curl -sS -o /tmp/syn-health -w 'https_health:%{http_code}\n' --max-time 15 "https://${SITE}/health" || true
head -c 200 /tmp/syn-health 2>/dev/null; echo
