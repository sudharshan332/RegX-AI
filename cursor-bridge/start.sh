#!/usr/bin/env bash
# Start cursor-bridge. On macOS, export system CAs so Node can reach
# api.cursor.com behind corporate SSL inspection. On Linux, reuse the
# OS CA bundle when present.
set -euo pipefail
cd "$(dirname "$0")"

# Optional local overrides (gitignored). Example: CURSOR_BRIDGE_PORT=5012
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

pick_linux_ca_bundle() {
  local candidate
  for candidate in \
    "${NODE_EXTRA_CA_CERTS:-}" \
    /etc/pki/tls/certs/ca-bundle.crt \
    /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
    /etc/ssl/certs/ca-certificates.crt
  do
    if [[ -n "$candidate" && -s "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [[ -n "${NODE_EXTRA_CA_CERTS:-}" && -s "${NODE_EXTRA_CA_CERTS}" ]]; then
  :
elif command -v security >/dev/null 2>&1; then
  CA_BUNDLE="${HOME}/.regx-system-cas.pem"
  if [[ ! -s "$CA_BUNDLE" ]]; then
    echo "[cursor-bridge] Building CA bundle at $CA_BUNDLE ..."
    security find-certificate -a -p /Library/Keychains/System.keychain > "$CA_BUNDLE"
    if [[ -f "$HOME/Library/Keychains/login.keychain-db" ]]; then
      security find-certificate -a -p "$HOME/Library/Keychains/login.keychain-db" >> "$CA_BUNDLE"
    fi
  fi
  export NODE_EXTRA_CA_CERTS="$CA_BUNDLE"
else
  if LINUX_CA="$(pick_linux_ca_bundle)"; then
    export NODE_EXTRA_CA_CERTS="$LINUX_CA"
  else
    unset NODE_EXTRA_CA_CERTS
    echo "[cursor-bridge] No system CA bundle found; starting without NODE_EXTRA_CA_CERTS"
  fi
fi

export CURSOR_BRIDGE_PORT="${CURSOR_BRIDGE_PORT:-5002}"
if [[ -n "${NODE_EXTRA_CA_CERTS:-}" ]]; then
  echo "[cursor-bridge] NODE_EXTRA_CA_CERTS=$NODE_EXTRA_CA_CERTS"
else
  echo "[cursor-bridge] NODE_EXTRA_CA_CERTS=(unset)"
fi
echo "[cursor-bridge] CURSOR_BRIDGE_PORT=$CURSOR_BRIDGE_PORT"
exec node server.js
