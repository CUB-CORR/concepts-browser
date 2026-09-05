#!/usr/bin/env bash
# Consistent SQLite backup (safe while the API is running, thanks to WAL mode).
# Usage: ./scripts/backup.sh [db_path] [out_path]
set -euo pipefail

DB="${1:-./data/concepts.db}"
OUT="${2:-./backups/concepts-$(date +%Y%m%d-%H%M%S).db}"

mkdir -p "$(dirname "$OUT")"
sqlite3 "$DB" ".backup '$OUT'"
echo "Backup written to $OUT"
