#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
destination="${1:-./backups}"
mkdir -p "$destination"
stamp="$(date +%Y%m%d-%H%M%S)"
umask 077
docker compose stop web
trap 'docker compose start web >/dev/null' EXIT HUP INT TERM
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$destination/$stamp.database.dump"
docker compose run --rm --no-deps --entrypoint tar web -czf - -C /app/media . > "$destination/$stamp.media.tar.gz"
printf '%s\n' "Backup saved: $destination/$stamp"
