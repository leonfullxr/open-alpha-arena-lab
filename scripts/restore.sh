#!/bin/sh
set -eu

if [ "${RESTORE_TARGET:-}" != "local-dev-confirmed" ]; then
  echo "Refusing restore: set RESTORE_TARGET=local-dev-confirmed to target the local Compose database." >&2
  exit 2
fi
if [ -z "${RESTORE_FILE:-}" ] || [ ! -f "$RESTORE_FILE" ]; then
  echo "Set RESTORE_FILE to an existing custom-format pg_dump file." >&2
  exit 2
fi

printf 'Restoring %s into the local Compose database; all current database contents will be replaced.\n' "$RESTORE_FILE" >&2
docker compose exec -T db sh -ec 'pg_restore --exit-on-error --single-transaction --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$RESTORE_FILE"
printf 'Restore completed.\n'
