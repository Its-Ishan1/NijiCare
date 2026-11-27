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
if ! [[ "$PORT" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "PORT must be an integer from 1 to 65535." >&2
  exit 1
fi
if "$PYTHON" -c 'import socket,sys; s=socket.socket(); s.settimeout(.25); rc=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); sys.exit(0 if rc == 0 else 1)' "$PORT"; then
  echo "Port $PORT already has a local server; refusing to open a possibly older site." >&2
  echo "Stop that server with Ctrl+C, or start this clone on another port: PORT=8082 ./start-web.sh" >&2
  exit 1
fi

echo "Starting Secret Wards locally at http://127.0.0.1:${PORT}"
echo "Press Ctrl+C to stop the server."
exec "$PYTHON" -B "$ROOT/demo-app/server/server.py"
