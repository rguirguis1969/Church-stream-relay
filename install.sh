#!/usr/bin/env bash
# One-command installer for the stream relay.
# Run on a fresh Ubuntu/Debian server as root:   bash install.sh
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root (for example: sudo bash install.sh)"; exit 1
fi

# 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker (takes a minute or two)..."
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

# 2. Settings file with a strong password
[ -f .env ] || cp .env.example .env
if grep -qE '^ADMIN_PASSWORD=(change-me)?$' .env; then
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 20 || true)"
  sed -i "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$PW/" .env
  NEW_PASSWORD=1
fi
# shellcheck disable=SC1091
set -a; . ./.env; set +a

# Optional web address for HTTPS, asked once.
if [ -z "${DOMAIN:-}" ] && [ -t 0 ] && [ "${NEW_PASSWORD:-0}" = 1 ]; then
  echo
  echo "Optional: do you have a web address (like relay.yourchurch.org) pointed at this server?"
  read -r -p "Type it here, or just press Enter to skip: " DOMAIN || true
  if [ -n "$DOMAIN" ]; then sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env; fi
fi

PROFILE=()
if [ -n "${DOMAIN:-}" ]; then
  # Settings page only via https://DOMAIN; port 8080 closed to the outside.
  sed -i -e "s/^ADMIN_BIND=.*/ADMIN_BIND=127.0.0.1/" -e "s/^COOKIE_SECURE=.*/COOKIE_SECURE=1/" \
         -e "s/^TRUSTED_PROXY=.*/TRUSTED_PROXY=*/" .env
  grep -q '^PUBLIC_HOST=.\+' .env || sed -i "s/^PUBLIC_HOST=.*/PUBLIC_HOST=$DOMAIN/" .env
  PROFILE=(--profile https)
fi

# 3. Firewall (only if ufw is in use)
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow OpenSSH >/dev/null
  ufw allow "${RTMP_PORT:-1935}/tcp" >/dev/null
  if [ -n "${DOMAIN:-}" ]; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  else ufw allow "${ADMIN_PORT:-8080}/tcp" >/dev/null; fi
fi

# 4. Build and start
say "Building and starting the relay (first time takes a few minutes)..."
docker compose "${PROFILE[@]}" up -d --build

IP="$(curl -fsS4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
set -a; . ./.env; set +a
say "All done! The stream relay is running."
if [ -n "${DOMAIN:-}" ]; then
  echo "  Settings page:  https://$DOMAIN"
else
  echo "  Settings page:  http://$IP:${ADMIN_PORT:-8080}"
fi
echo "  Password:       $ADMIN_PASSWORD"
echo
echo "Write the password down somewhere safe. You can see it again any time with:"
echo "  grep ADMIN_PASSWORD $(pwd)/.env"
