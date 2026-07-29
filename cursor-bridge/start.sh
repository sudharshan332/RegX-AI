#!/usr/bin/env bash
# Start cursor-bridge with macOS system CAs so Node can reach api.cursor.com
# behind corporate SSL inspection (Cisco/Zscaler/etc).
set -euo pipefail
cd "$(dirname "$0")"

CA_BUNDLE="${NODE_EXTRA_CA_CERTS:-$HOME/.regx-system-cas.pem}"
if [[ ! -s "$CA_BUNDLE" ]]; then
  echo "[cursor-bridge] Building CA bundle at $CA_BUNDLE ..."
  security find-certificate -a -p /Library/Keychains/System.keychain > "$CA_BUNDLE"
  if [[ -f "$HOME/Library/Keychains/login.keychain-db" ]]; then
    security find-certificate -a -p "$HOME/Library/Keychains/login.keychain-db" >> "$CA_BUNDLE"
  fi
fi

export NODE_EXTRA_CA_CERTS="$CA_BUNDLE"
export CURSOR_BRIDGE_PORT="${CURSOR_BRIDGE_PORT:-5002}"
echo "[cursor-bridge] NODE_EXTRA_CA_CERTS=$NODE_EXTRA_CA_CERTS"
exec node server.js
