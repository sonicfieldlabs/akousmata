#!/usr/bin/env bash
# Run the listening navigator locally (store = this folder unless AKOUSMATA_PATH is set).
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m uvicorn akousmata_app.server:app --host "${AKOUSMATA_HOST:-127.0.0.1}" --port "${AKOUSMATA_PORT:-5180}" --reload
