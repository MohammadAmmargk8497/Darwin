#!/usr/bin/env bash
# Darwin — native installer for Ubuntu / Debian.
#
# End-to-end: installs Python + Ollama, pulls the default model, creates a
# virtualenv, installs the Python deps, and seeds the vault. Idempotent —
# safe to re-run.
#
# Usage:
#     ./scripts/install.sh
#
# Environment overrides:
#     DARWIN_MODEL   — Ollama model to pull (default: llama3.2:3b)
#     DARWIN_VENV    — virtualenv directory (default: .venv)

set -euo pipefail

readonly RED=$'\033[0;31m'
readonly GREEN=$'\033[0;32m'
readonly YELLOW=$'\033[1;33m'
readonly NC=$'\033[0m'

info()  { printf "%s[info]%s %s\n"  "$GREEN"  "$NC" "$*"; }
warn()  { printf "%s[warn]%s %s\n"  "$YELLOW" "$NC" "$*"; }
die()   { printf "%s[error]%s %s\n" "$RED"    "$NC" "$*" >&2; exit 1; }
step()  { printf "\n%s==>%s %s\n"   "$GREEN"  "$NC" "$*"; }

# Run from repo root regardless of where the user invoked the script from.
cd "$(dirname "$0")/.."

MODEL="${DARWIN_MODEL:-llama3.2:3b}"
VENV="${DARWIN_VENV:-.venv}"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if ! command -v apt-get >/dev/null 2>&1; then
    die "This installer targets Ubuntu / Debian. For other systems, see README.md."
fi

if [ "$EUID" -eq 0 ]; then
    die "Do not run this script as root. It will use sudo where needed."
fi

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------

step "Installing system packages (python3, venv, curl, build-essential)"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip \
    curl build-essential ca-certificates

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

step "Installing Ollama"
if command -v ollama >/dev/null 2>&1; then
    info "Ollama already installed: $(ollama --version 2>/dev/null | head -1 || echo 'unknown version')"
else
    info "Running the official Ollama installer..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

step "Starting Ollama"
if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
    info "Ollama already running."
else
    # The official installer configures a systemd unit on most distros;
    # enable+start it if present, else fall back to a background process.
    if systemctl list-unit-files 2>/dev/null | grep -q '^ollama\.service'; then
        sudo systemctl enable --now ollama || true
    else
        info "No systemd unit — starting ollama in the background."
        nohup ollama serve >/dev/null 2>&1 &
        disown || true
    fi
    for _ in $(seq 1 20); do
        if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
        warn "Ollama did not come up in 20s — continuing; you can run 'ollama serve' manually later."
    fi
fi

step "Pulling Ollama model ($MODEL)"
if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Fxq "$MODEL"; then
    info "Model '$MODEL' already pulled."
else
    info "Downloading '$MODEL' — first-run download, may take a while."
    ollama pull "$MODEL"
fi

# ---------------------------------------------------------------------------
# Virtualenv + Python deps
# ---------------------------------------------------------------------------

step "Creating virtualenv at $VENV"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi

step "Installing Python dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt
info "Installed into $VENV"

# ---------------------------------------------------------------------------
# Config + data dirs
# ---------------------------------------------------------------------------

step "Seeding configuration and data directories"
if [ ! -f .env ]; then
    cp .env.example .env
    info "Created .env from template."
else
    info ".env already present — leaving as-is."
fi

mkdir -p "Darwin Research/Research/Incoming" papers logs
info "vault, papers, logs directories ready."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

cat <<EOF

${GREEN}==>${NC} Install complete.

Start Darwin:
    ./scripts/run.sh

Then open http://localhost:8501 in your browser.

Useful follow-ups:
    ./scripts/doctor.sh     check everything is wired up
    ./scripts/stop.sh       stop Streamlit (and any ollama this script started)
EOF
