#!/usr/bin/env bash
# run.sh — Start the LLM Selfbot
#
# Usage:
#   ./run.sh            → auto-detect mode from config.yaml
#   ./run.sh discord    → Discord only
#   ./run.sh snapchat   → both Python bridge + Node.js runner
#   ./run.sh both       → Discord + Snapchat

set -e

MODE="${1:-auto}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Ensure Python deps ────────────────────────────────────────────────────────
if ! python3 -c "import discord" 2>/dev/null; then
    echo "[run.sh] Installing Python dependencies..."
    pip3 install -r requirements.txt --break-system-packages 2>/dev/null || pip3 install -r requirements.txt
fi

# Telegram controller starts in the same console via main.py (when a token is
# set). Disable with TELEGRAM_AUTOSTART=false in .env.

# ── Ensure Node deps for Snapchat ─────────────────────────────────────────────
install_node_deps() {
    if [ ! -d "platforms/snapchat/node_modules" ]; then
        echo "[run.sh] Installing Node.js dependencies for Snapchat..."
        cd platforms/snapchat
        npm install
        cd "$SCRIPT_DIR"
    fi
}

# ── Launch functions ──────────────────────────────────────────────────────────
run_discord() {
    echo "[run.sh] Starting Discord platform..."
    python3 main.py discord
}

run_snapchat() {
    install_node_deps
    echo "[run.sh] Starting Snapchat (bridge + browser runner in one terminal)..."
    # main.py launches the Node runner itself and ties it to this process.
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
    auto)
        # Ask Python what mode config.yaml says, then dispatch to the right launcher
        DETECTED_MODE=$(python3 -c "from utils.helpers import load_config; c=load_config(); s=c.get('snapchat',{}).get('enabled',False); d=c.get('discord',{}).get('enabled',True); print('both' if s and d else 'snapchat' if s else 'discord')")
        echo "[run.sh] Auto-detected mode: $DETECTED_MODE"
        case "$DETECTED_MODE" in
            discord)  run_discord ;;
            snapchat) run_snapchat ;;
            both)     run_both ;;
            *)        python3 main.py ;;
        esac
        ;;
    *)
        echo "Usage: ./run.sh [discord|snapchat|both]"
        exit 1
        ;;
esac
