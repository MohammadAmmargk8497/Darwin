#!/usr/bin/env bash
# Darwin diagnostic — verify every piece of the stack is in place.

set -euo pipefail

cd "$(dirname "$0")/.."

readonly GREEN=$'\033[0;32m'
readonly RED=$'\033[0;31m'
readonly YELLOW=$'\033[1;33m'
readonly NC=$'\033[0m'

pass=0
fail=0

ok()   { printf "  %s✓%s %s\n"  "$GREEN"  "$NC" "$*"; pass=$((pass + 1)); }
bad()  { printf "  %s✗%s %s\n"  "$RED"    "$NC" "$*"; fail=$((fail + 1)); }
info() { printf "  %s·%s %s\n"  "$YELLOW" "$NC" "$*"; }

printf "\n== Darwin environment check ==\n\n"

# --- Python ---------------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
    ok "python3 — $(python3 --version 2>&1)"
else
    bad "python3 not found (install: sudo apt-get install -y python3 python3-venv)"
fi

# --- Virtualenv + deps ----------------------------------------------------
VENV="${DARWIN_VENV:-.venv}"
if [ -x "$VENV/bin/python" ]; then
    ok "virtualenv at $VENV"
    missing=$("$VENV/bin/python" - <<'PY'
import importlib.util
mods = ["mcp", "fastmcp", "arxiv", "pymupdf", "loguru",
        "pydantic", "pydantic_settings", "streamlit", "tenacity", "yaml"]
print(",".join(m for m in mods if importlib.util.find_spec(m) is None))
PY
)
    if [ -z "$missing" ]; then
        ok "Python deps present"
    else
        bad "missing deps: $missing (run ./scripts/install.sh)"
    fi
else
    bad "no virtualenv at $VENV (run ./scripts/install.sh)"
fi

# --- Ollama ---------------------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
    ok "ollama — $(ollama --version 2>&1 | head -1)"
    if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
        ok "ollama API reachable at http://localhost:11434"
        models=$(curl -fsS http://localhost:11434/api/tags \
            | python3 -c "import sys,json;print(' '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null)
        if [ -n "$models" ]; then
            ok "ollama models: $models"
        else
            bad "no models pulled (run 'ollama pull llama3.2:3b')"
        fi
    else
        bad "ollama not running (try 'sudo systemctl start ollama' or 'ollama serve')"
    fi
else
    bad "ollama not installed (run ./scripts/install.sh or curl -fsSL https://ollama.com/install.sh | sh)"
fi

# --- Vault + data dirs ----------------------------------------------------
if [ -d "Darwin Research" ]; then
    count=$(find "Darwin Research/Research/Incoming" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
    ok "vault: Darwin Research/ (${count} notes in Incoming)"
else
    bad "vault directory 'Darwin Research/' missing"
fi

if [ -d papers ]; then
    count=$(find papers -maxdepth 1 -name '*.pdf' 2>/dev/null | wc -l | tr -d ' ')
    ok "papers/ (${count} PDFs)"
else
    bad "papers/ directory missing"
fi

if [ -d logs ]; then
    ok "logs/ directory present"
else
    info "logs/ directory will be created on first run"
fi

# --- Config ---------------------------------------------------------------
if [ -f .env ]; then
    ok ".env present"
else
    info ".env missing — copy from .env.example if you need to set secrets"
fi

if [ -f config/agent_config.json ]; then
    ok "config/agent_config.json present"
else
    bad "config/agent_config.json missing"
fi

# --- Summary --------------------------------------------------------------
printf "\nSummary: %s%d pass%s, %s%d fail%s\n\n" \
    "$GREEN" "$pass" "$NC" \
    "$RED"   "$fail" "$NC"

[ "$fail" -eq 0 ]
