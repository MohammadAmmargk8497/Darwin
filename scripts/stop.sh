#!/usr/bin/env bash
# Stop Streamlit (and any ollama serve this script started).

set -euo pipefail

printf "Stopping Streamlit...\n"
pkill -f "streamlit run ui_app.py" 2>/dev/null || true

# Only kill foreground `ollama serve` processes started by run.sh/install.sh —
# the systemd unit, if any, is left alone.
if pgrep -f "^ollama serve" >/dev/null 2>&1; then
    printf "Stopping foreground ollama serve...\n"
    pkill -f "^ollama serve" 2>/dev/null || true
fi

printf "Stopped.\n"
