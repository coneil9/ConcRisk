#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-api}"

case "$cmd" in
  api)
    exec uvicorn concrisk.api.main:app --host 0.0.0.0 --port 8080
    ;;
  dashboard)
    echo "dashboard entrypoint not implemented yet (Phase 4)"
    exit 0
    ;;
  etl)
    echo "etl entrypoint not implemented yet (Phase 1)"
    exit 0
    ;;
  *)
    echo "unknown entrypoint: $cmd (expected: api | dashboard | etl)" >&2
    exit 2
    ;;
esac
