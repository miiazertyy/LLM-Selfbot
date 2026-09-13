#!/usr/bin/env bash
# scripts/run.sh, Start the LLMSelfbot
#
# Usage:
#   scripts/run.sh              → supervisor (web UI + platform workers)
#   scripts/run.sh discord      → Discord only (no web UI)
#   scripts/run.sh snapchat     → Snapchat only (no web UI)
#   scripts/run.sh both         → Discord + Snapchat (no web UI)

set -e

MODE="${1:-supervisor}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# ── Ensure Python deps ────────────────────────────────────────────────────────
if ! python3 -c "import discord" 2>/dev/null; then
    echo "[run.sh] Installing Python dependencies..."
    pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
fi

# ── Ensure Node deps for Snapchat ─────────────────────────────────────────────
install_node_deps() {
    if [ ! -d "app/platforms/snapchat/node_modules" ]; then
        echo "[run.sh] Installing Node.js dependencies for Snapchat..."
        (cd app/platforms/snapchat && npm install)
    fi
}

# ── Launch functions ──────────────────────────────────────────────────────────
run_supervisor() {
    echo "[run.sh] Starting supervisor (web UI + workers)..."
    python3 main.py
}

run_discord() {
    echo "[run.sh] Starting Discord platform..."
    python3 main.py discord
}

run_snapchat() {
    install_node_deps
    echo "[run.sh] Starting Snapchat (bridge + browser runner in one terminal)..."
    python3 main.py snapchat
}

run_both() {
    install_node_deps
    echo "[run.sh] Starting Discord + Snapchat (bridge launches the browser runner)..."
    python3 main.py both
}

# ── Mode dispatch ─────────────────────────────────────────────────────────────
case "$MODE" in
    discord)  run_discord ;;
    snapchat) run_snapchat ;;
    both)     run_both ;;
    supervisor) run_supervisor ;;
    auto)
        DETECTED_MODE=$(python3 -c "from app.utils.helpers import load_config; c=load_config(); s=c.get('snapchat',{}).get('enabled',False); d=c.get('discord',{}).get('enabled',True); print('both' if s and d else 'snapchat' if s else 'discord')")
        echo "[run.sh] Auto-detected mode: $DETECTED_MODE"
        case "$DETECTED_MODE" in
            discord)  run_discord ;;
            snapchat) run_snapchat ;;
            both)     run_both ;;
            *)        run_supervisor ;;
        esac
        ;;
    *)
        echo "Usage: ./scripts/run.sh [supervisor|discord|snapchat|both]"
        exit 1
        ;;
esac
