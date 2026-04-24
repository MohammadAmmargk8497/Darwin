#!/usr/bin/env bash
# Start Darwin locally (Streamlit UI + ensure Ollama is up).

set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${DARWIN_VENV:-.venv}"

if [ ! -x "$VENV/bin/streamlit" ]; then
    printf "[error] Darwin is not installed. Run ./scripts/install.sh first.\n" >&2
    exit 1
fi

# Make sure Ollama is reachable; nudge it if not.
if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
    if command -v systemctl >/dev/null 2>&1 && \
       systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
        sudo systemctl start ollama || true
    elif command -v ollama >/dev/null 2>&1; then
        printf "[info] Starting Ollama in the background...\n"
        nohup ollama serve >/dev/null 2>&1 &
        disown || true
    fi
    for _ in $(seq 1 15); do
        if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then break; fi
        sleep 1
    done
fi

printf "[info] Darwin UI → http://localhost:8501\n"
exec "$VENV/bin/streamlit" run ui_app.py
