#!/usr/bin/env bash
# Finds a working Webshare proxy and updates INLABS_PROXY in .env.
# Proxy list format: ip:port:user:pass (one per line)
# Usage: update_proxy.sh [proxy_list_file] [env_file]

set -euo pipefail

proxy_list="${1:-${HOME}/webshare_proxies.txt}"
env_file="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.env}"
test_url="https://httpbin.org/ip"
timeout_sec=8

if [[ ! -f "${proxy_list}" ]]; then
  echo "[update_proxy] Proxy list not found: ${proxy_list}" >&2
  exit 1
fi

if [[ ! -f "${env_file}" ]]; then
  echo "[update_proxy] .env file not found: ${env_file}" >&2
  exit 1
fi

while IFS=: read -r ip port user pass; do
  [[ -z "${ip}" || "${ip}" == \#* ]] && continue
  proxy_url="http://${user}:${pass}@${ip}:${port}"
  if curl -sf --max-time "${timeout_sec}" --proxy "${proxy_url}" "${test_url}" -o /dev/null 2>/dev/null; then
    echo "[update_proxy] Working proxy found: ${ip}:${port}"
    # Update or insert INLABS_PROXY in .env
    if grep -q '^INLABS_PROXY=' "${env_file}"; then
      sed -i "s|^INLABS_PROXY=.*|INLABS_PROXY=${proxy_url}|" "${env_file}"
    else
      echo "INLABS_PROXY=${proxy_url}" >> "${env_file}"
    fi
    echo "[update_proxy] .env updated"
    exit 0
  fi
done < "${proxy_list}"

echo "[update_proxy] No working proxy found in list. INLABS_PROXY unchanged." >&2
exit 1
