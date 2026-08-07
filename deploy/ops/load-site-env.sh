#!/usr/bin/env bash
# Load site ops thresholds from data/smtp.env into the environment.
# Usage: load_site_env /var/www/example.com

load_site_env() {
  local root="${1:?site root required}"
  local envfile="${root}/data/smtp.env"
  [[ -f "$envfile" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ -z "$line" || "$line" != *=* ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    key="$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    val="$(echo "$val" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed "s/^['\"]//;s/['\"]$//")"
    [[ -n "$key" ]] && export "$key=$val"
  done < "$envfile"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  load_site_env "${1:?site root}"
fi
