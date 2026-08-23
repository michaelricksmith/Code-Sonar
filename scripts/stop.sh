#!/usr/bin/env bash
# ============================================================================
# Code Sonar — stop the running services (Unix / macOS / WSL).
#
# Reads PIDs from logs/backend.pid and logs/frontend.pid (written by
# start.sh) and terminates the processes. Idempotent: missing PID
# files or dead PIDs are no-ops.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"

echo "Stopping Code Sonar..."

stop_pid() {
    local name="$1"
    local pidfile="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid="$(cat "$pidfile" 2>/dev/null || true)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Stopping $name (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            if kill -0 "$pid" 2>/dev/null; then
                echo "  $name still alive, sending SIGKILL."
                kill -9 "$pid" 2>/dev/null || true
            fi
        else
            echo "[skip] $name PID $pid is not running."
        fi
        rm -f "$pidfile"
    else
        echo "[skip] No PID file for $name (was start.sh used?)."
    fi
}

stop_pid "backend" "$LOG_DIR/backend.pid"
stop_pid "frontend" "$LOG_DIR/frontend.pid"

# Belt-and-braces: kill anything still bound to the dev ports.
for port in 8000 8765 5173; do
    pids="$(ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $NF}' | grep -oE 'pid=[0-9]+' | cut -d= -f2 || true)"
    for pid in $pids; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "Killing leftover PID $pid on :$port"
            kill "$pid" 2>/dev/null || true
        fi
    done
done

echo "Code Sonar stopped."
