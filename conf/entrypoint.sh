#!/bin/sh
set -e
mkdir -p /data/logs /run/relay
chown -R www-data:www-data /data /run/relay
chmod 700 /data
if [ -z "$ADMIN_PASSWORD" ]; then
  echo "ERROR: ADMIN_PASSWORD is not set. Put it in the .env file next to docker-compose.yml." >&2
  exit 1
fi
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
