#!/usr/bin/env bash
# ICEFLOW: start the whole prototype with one command (macOS / Linux / Git Bash).
#
#   ./start.sh              install if needed, then run backend and bridge console
#   ./start.sh --skip-install
#   ./start.sh --check      run the verification checks instead of serving
#
# Ctrl-C stops both servers.

set -euo pipefail
cd "$(dirname "$0")"

SKIP_INSTALL=0
CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --skip-install) SKIP_INSTALL=1 ;;
        --check) CHECK_ONLY=1 ;;
        *) echo "Unknown option: $arg"; exit 2 ;;
    esac
done

say() { printf '  \033[36m%s\033[0m\n' "$1"; }
warn() { printf '  \033[33m%s\033[0m\n' "$1"; }

echo
printf '  ICEFLOW  |  SIH 2026 PS-26059  |  MoES / NCPOR\n'
printf '  \033[90m---------------------------------------------------\033[0m\n'

for tool in python npm; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf '  \033[31mMissing prerequisite: %s\033[0m\n' "$tool"
        echo "  Install Python 3.11+ and Node 18+, then run this again."
        exit 1
    fi
done

if [ "$SKIP_INSTALL" -eq 0 ]; then
    say "Installing Python dependencies..."
    python -m pip install -q -r requirements.txt
    if [ ! -d frontend/node_modules ]; then
        say "Installing frontend dependencies (first run only, takes a minute)..."
        (cd frontend && npm install --silent)
    fi
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
    say "Running the test suite..."
    python -m pytest tests/ -q
    say "Running the command-line demonstration..."
    python -m src.cli --quick
    echo
    say "Checks complete. See the README section 'How to check the prototype is actually working'."
    exit 0
fi

say "Starting the API on http://127.0.0.1:8000  (docs at /docs)"
say "ICEFLOW_ENV=dev is set for local development so the API exposes a permissive CORS middleware."
ICEFLOW_ENV=dev python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

cleanup() {
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
        say "Stopping the API..."
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

say "Waiting for the API to warm its caches..."
READY=0
for _ in $(seq 1 60); do
    sleep 1
    if curl -sf --max-time 2 http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
        READY=1
        break
    fi
done
if [ "$READY" -eq 1 ]; then say "API is up."; else warn "The API did not become ready in 60 seconds."; fi

say "Starting the bridge console on http://localhost:5173"
echo
printf '  \033[32mOpen  http://localhost:5173  in your browser.\033[0m\n'
printf '  \033[90mPress Ctrl-C here to stop both servers.\033[0m\n'
echo

cd frontend && npm run dev
