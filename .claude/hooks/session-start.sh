#!/bin/bash
# SessionStart (cloud sessions only): install the project and, when the container has a
# local PostgreSQL 16, start it with a scratch database so the database tests run too.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

uv sync --quiet

# Local Postgres for the tests that need POARTA_TEST_DSN (skipped without it).
if command -v pg_ctlcluster >/dev/null 2>&1 && pg_lsclusters 2>/dev/null | grep -q '^16 *main'; then
  if ! pg_lsclusters | grep -E '^16 +main' | grep -q online; then
    pg_ctlcluster 16 main start >/dev/null 2>&1 || true
  fi
  if pg_lsclusters | grep -E '^16 +main' | grep -q online; then
    su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='poarta'\"" | grep -q 1 \
      || su postgres -c "psql -q -c \"CREATE ROLE poarta LOGIN PASSWORD 'poarta' SUPERUSER;\""
    su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='poarta_test'\"" | grep -q 1 \
      || su postgres -c "psql -q -c 'CREATE DATABASE poarta_test OWNER poarta;'"
    if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
      echo 'export POARTA_TEST_DSN="postgresql://poarta:poarta@localhost:5432/poarta_test"' \
        >> "$CLAUDE_ENV_FILE"
    fi
  fi
fi
