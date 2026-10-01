#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-api}"
shift || true

case "$cmd" in
  api)
    exec uvicorn concrisk.api.main:app --host 0.0.0.0 --port 8080
    ;;
  dashboard)
    # Streamlit flags required when behind Container Apps ingress.
    exec streamlit run dashboard/app.py \
      --server.address=0.0.0.0 \
      --server.port=8501 \
      --server.headless=true \
      --server.enableXsrfProtection=false \
      --server.enableCORS=false
    ;;
  etl)
    # Any remaining args are forwarded to the pipeline, e.g. --quarters 8.
    exec python -m concrisk.etl.pipeline "$@"
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    echo "unknown entrypoint: $cmd (expected: api | dashboard | etl | migrate)" >&2
    exit 2
    ;;
esac
