#!/bin/sh
set -eu
umask 077

backup_dir=${BACKUP_DIR:-backups}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_dir"
temporary=$(mktemp "$backup_dir/.arena-$stamp.XXXXXX")
target="$backup_dir/arena-$stamp-$$.dump"
trap 'rm -f "$temporary"' EXIT

docker compose exec -T db sh -ec 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$temporary"
mv "$temporary" "$target"
printf 'Database backup written to %s\n' "$target"
