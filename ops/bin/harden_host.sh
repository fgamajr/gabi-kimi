#!/usr/bin/env bash

set -euo pipefail

ssh_port="${SSH_PORT:-22}"
frontend_http_port="${FRONTEND_HTTP_PORT:-80}"
frontend_https_port="${FRONTEND_HTTPS_PORT:-443}"

if ! command -v ufw >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ufw
fi

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

if [ -n "${SSH_ALLOWED_CIDR:-}" ]; then
  ufw allow from "${SSH_ALLOWED_CIDR}" to any port "${ssh_port}" proto tcp
else
  ufw allow "${ssh_port}/tcp"
fi

ufw allow "${frontend_http_port}/tcp"
ufw allow "${frontend_https_port}/tcp"

for port in 27017 9200 8001 8902; do
  ufw deny "${port}/tcp"
done

ufw logging on
ufw --force enable
ufw status verbose
