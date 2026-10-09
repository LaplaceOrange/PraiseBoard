#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
database="${1:?Usage: restore.sh DATABASE_DUMP MEDIA_ARCHIVE}"
media="${2:?Usage: restore.sh DATABASE_DUMP MEDIA_ARCHIVE}"
test -f "$database"
test -f "$media"
printf '%s' "Restore will replace the database. Type RESTORE: "
read -r answer
test "$answer" = RESTORE
docker compose stop web
trap 'docker compose start web >/dev/null' EXIT HUP INT TERM
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' < "$database"
docker compose run --rm -T --no-deps --entrypoint tar web -xzf - -C /app/media < "$media"
printf '%s\n' "Database and images restored."
