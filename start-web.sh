#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.10+ is required. Set PYTHON to its executable or install Python." >&2
  exit 1
fi

if [[ -z "${RAKSHA_SECRET:-}" ]]; then
  export RAKSHA_SECRET="practice-synthetic-demo-only"
  echo "Using the demo-only key. Use synthetic data only, or set RAKSHA_SECRET before launch." >&2
fi

export PORT="${PORT:-8081}"
echo "Starting Secret Wards locally at http://127.0.0.1:${PORT}"
echo "Press Ctrl+C to stop the server."
exec "$PYTHON" -B "$ROOT/demo-app/server/server.py"
