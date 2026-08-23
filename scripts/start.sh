#!/usr/bin/env bash
# ============================================================================
# Code Sonar — one-command startup (Unix / macOS / WSL).
#
# Launches the FastAPI backend and Vite dev server as background
# processes. Outputs go to logs/. PIDs are recorded in logs/*.pid
# so scripts/stop.sh can shut everything down cleanly.
#
# Usage:
#   ./scripts/start.sh
#
# Shutdown:
#   ./scripts/stop.sh
# ============================================================================

set -euo pipefail

# ---- Resolve repo root (this script lives in <repo>/scripts) --------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ---- Config ----------------------------------------------------------------
BACKEND_PORT="${BACKEND_PORT:-8000}"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

echo
echo "=== Code Sonar startup ==============================================="
echo "Repo root:  $REPO_ROOT"
echo "Backend:    http://127.0.0.1:${BACKEND_PORT}"
echo "Frontend:   http://localhost:5173"
echo "======================================================================"
echo

# ---- Pick a free backend port (try 8000, then 8765) -----------------------
pick_free_port() {
    local port="$1"
    if ! (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null; then
        echo "$port"
        return 0
    fi
    return 1
}
if ! pick_free_port "$BACKEND_PORT" >/dev/null; then
    echo "Port ${BACKEND_PORT} in use, falling back to 8765."
    BACKEND_PORT=8765
fi

# ---- Dependency checks ----------------------------------------------------
for cmd in python3 node npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[ERROR] '$cmd' not on PATH. Install $cmd and retry."
        exit 1
    fi
done

# ---- Backend venv setup ---------------------------------------------------
VENV="$REPO_ROOT/backend/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "[INFO] Creating Python venv at $VENV ..."
    (cd "$REPO_ROOT/backend" && python3 -m venv .venv) || {
        echo "[ERROR] venv creation failed"; exit 1; }
fi
if [ ! -x "$VENV/bin/uvicorn" ]; then
    echo "[INFO] Installing backend dependencies ..."
    (cd "$REPO_ROOT/backend" && \
        "$VENV/bin/python" -m pip install -e ".[dev]") || {
        echo "[ERROR] backend install failed"; exit 1; }
fi

# ---- Frontend dependency install -----------------------------------------
if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    echo "[INFO] Installing frontend dependencies ..."
    (cd "$REPO_ROOT/frontend" && npm install) || {
        echo "[ERROR] frontend install failed"; exit 1; }
fi

# ---- Launch backend in background ----------------------------------------
echo "[INFO] Launching backend on port ${BACKEND_PORT} ..."
(
    cd "$REPO_ROOT/backend"
    nohup "$VENV/bin/uvicorn" app.main:app \
        --host 127.0.0.1 --port "${BACKEND_PORT}" --reload \
        > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
)
echo "[INFO] Backend PID: $(cat "$LOG_DIR/backend.pid")"

# ---- Wait for backend health --------------------------------------------
echo -n "[INFO] Waiting for backend"
HEALTH_TRIES=0
until curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; do
    HEALTH_TRIES=$((HEALTH_TRIES + 1))
    if [ "$HEALTH_TRIES" -ge 20 ]; then
        echo " [WARN] Backend did not respond on /health within 20s."
        echo "        Continuing to launch frontend anyway."
        break
    fi
    sleep 1
    echo -n "."
done
echo

# ---- Launch frontend in background --------------------------------------
echo "[INFO] Launching frontend on http://localhost:5173 ..."
(
    cd "$REPO_ROOT/frontend"
    nohup npm run dev \
        > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
)
echo "[INFO] Frontend PID: $(cat "$LOG_DIR/frontend.pid")"

echo
echo "=== Code Sonar is starting ==========================================="
echo
echo "  Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "  Frontend: http://localhost:5173"
echo
echo "Both servers run in background. To stop, run:"
echo "  ./scripts/stop.sh"
echo
echo "To see live logs: tail -f $LOG_DIR/{backend,frontend}.log"
echo
echo "Tip: open the frontend URL in your browser, type a repo path, and"
echo "     click 'Run scan'."
echo "======================================================================"
echo
