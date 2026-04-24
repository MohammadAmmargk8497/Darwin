#!/usr/bin/env bash
# Bring Darwin up via docker compose. Auto-detects NVIDIA GPU and sizes
# the Ollama model to fit available VRAM. By default runs in the
# foreground and tears the whole stack down cleanly when you Ctrl-C or
# close the terminal. Pass --detach to keep it running after the shell
# returns.

set -euo pipefail

cd "$(dirname "$0")/.."

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

DETACH=0
for arg in "$@"; do
    case "$arg" in
        -d|--detach) DETACH=1 ;;
        -h|--help)
            cat <<EOF
Usage: scripts/docker-run.sh [--detach]

Starts the Darwin stack via Docker Compose. By default, stays in the
foreground streaming logs; Ctrl-C (or closing the terminal) triggers a
clean docker-compose-down of both containers.

  -d, --detach    Start detached and return immediately.
                  Use 'docker compose down' later to stop.
EOF
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Docker preflight
# ---------------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[error] Docker is not installed.

On Ubuntu 24.04:

    sudo apt-get update
    sudo apt-get install -y docker.io docker-compose-v2
    sudo usermod -aG docker $USER
    # log out and back in for group membership to apply

Or follow: https://docs.docker.com/engine/install/ubuntu/
EOF
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    printf "[error] docker compose plugin missing (apt: docker-compose-v2)\n" >&2
    exit 1
fi

# Fresh Linux boxes sometimes inherit a ~/.docker/config.json with
# `"credsStore": "desktop"` left over from a Mac or Windows machine. On
# Linux without Docker Desktop, the helper binary is missing and every
# `docker pull` fails.
check_docker_credentials() {
    local config="$HOME/.docker/config.json"
    [ -f "$config" ] || return 0
    if ! grep -qE '"credsStore"[[:space:]]*:[[:space:]]*"desktop"' "$config"; then
        return 0
    fi
    if command -v docker-credential-desktop >/dev/null 2>&1; then
        return 0
    fi

    cat <<EOF
[warn] ~/.docker/config.json has "credsStore": "desktop" but
       docker-credential-desktop is not installed on this machine.
       Image pulls will fail with a credential-helper error.
EOF

    if [ ! -t 0 ]; then
        cat <<EOF
[error] Stdin is not a terminal — not prompting for permission.
        Run this and retry:
            sed -i '/"credsStore"[[:space:]]*:[[:space:]]*"desktop"/d' $config
EOF
        exit 1
    fi

    printf "Fix it now? A timestamped backup will be saved next to the file. [Y/n] "
    read -r reply
    reply="${reply:-Y}"
    case "$reply" in
        [Yy]*) ;;
        *) printf "[error] Aborted. Fix manually and re-run this script.\n" >&2; exit 1 ;;
    esac

    local backup="${config}.bak.$(date +%s)"
    cp "$config" "$backup"
    printf "[info] Backup saved: %s\n" "$backup"

    if command -v jq >/dev/null 2>&1; then
        local tmp="${config}.tmp.$$"
        if jq 'del(.credsStore)' "$config" > "$tmp"; then
            mv "$tmp" "$config"
            printf "[info] Removed credsStore via jq.\n"
        else
            rm -f "$tmp"
            printf "[warn] jq failed — falling back to file-aside rename.\n"
            mv "$config" "${config}.disabled"
        fi
    else
        printf "[info] jq not available — moving the whole config aside.\n"
        printf "       (Install jq for a surgical fix: sudo apt-get install -y jq)\n"
        mv "$config" "${config}.disabled"
    fi
}

check_docker_credentials

# If the user followed the native-install path first (./scripts/install.sh),
# a systemd Ollama is already on port 11434 and Docker's Ollama container
# can't bind the same port. Detect and offer to stop it.
check_port_conflict() {
    local port=11434
    local in_use=false

    if command -v ss >/dev/null 2>&1; then
        ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port" && in_use=true
    elif command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1 && in_use=true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | grep -qE "[:.]$port[[:space:]]" && in_use=true
    fi

    $in_use || return 0

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'darwin-ollama'; then
        printf "[info] darwin-ollama is already running — compose will reuse it.\n"
        return 0
    fi

    if ! curl -fsS "http://127.0.0.1:$port/api/tags" >/dev/null 2>&1; then
        printf "[error] Port %s is in use by a non-Ollama service.\n" "$port" >&2
        printf "        Stop whatever is using it and re-run this script.\n" >&2
        exit 1
    fi

    cat <<EOF
[warn] Port $port is already bound by a native Ollama running on this
       machine (likely from ./scripts/install.sh). Docker's Ollama
       container can't bind the same port.
EOF

    if [ ! -t 0 ]; then
        cat <<EOF
[error] Stdin is not a terminal — not prompting.
        Stop the native Ollama and retry, e.g.:
            sudo systemctl stop ollama
EOF
        exit 1
    fi

    printf "Stop the native Ollama now and continue with Docker? [Y/n] "
    read -r reply
    reply="${reply:-Y}"
    case "$reply" in
        [Yy]*) ;;
        *) printf "[error] Aborted. Stop Ollama yourself and re-run.\n" >&2; exit 1 ;;
    esac

    local stopped=false
    if command -v systemctl >/dev/null 2>&1 && \
       systemctl is-active --quiet ollama 2>/dev/null; then
        printf "[info] Stopping ollama.service via systemctl (sudo prompt may appear)...\n"
        if sudo systemctl stop ollama; then
            stopped=true
        fi
    fi
    if pgrep -x ollama >/dev/null 2>&1; then
        printf "[info] Killing foreground ollama processes...\n"
        pkill -x ollama 2>/dev/null || true
        stopped=true
    fi
    if ! $stopped; then
        printf "[error] Couldn't identify how to stop Ollama. Stop it manually and re-run.\n" >&2
        exit 1
    fi

    local waited=0
    while [ $waited -lt 10 ]; do
        if ! curl -fsS "http://127.0.0.1:$port/api/tags" >/dev/null 2>&1; then
            printf "[info] Port %s is free.\n" "$port"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done

    printf "[error] Port %s still bound after 10s. Check what's holding it.\n" "$port" >&2
    exit 1
}

check_port_conflict

# ---------------------------------------------------------------------------
# GPU detection + model sizing
# ---------------------------------------------------------------------------
#
# We look for two things on the host:
#   1. An NVIDIA GPU (nvidia-smi reports non-zero total VRAM).
#   2. nvidia-container-toolkit registered with Docker (so `--gpus` works).
# Both must be true to enable GPU passthrough. Otherwise we fall back to
# CPU, which is slow but correct.
#
# Based on total VRAM we pick an Ollama model that comfortably fits in a
# Q4 quantisation, leaving headroom for context. Users can override by
# exporting MODEL_NAME before running the script (or setting it in .env).
# ---------------------------------------------------------------------------

VRAM_MB=0
GPU_AVAILABLE=false
TOOLKIT_AVAILABLE=false

if command -v nvidia-smi >/dev/null 2>&1; then
    # Sum across all GPUs (awk treats empty output as 0).
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
              | awk '{s+=$1} END {print s+0}')
    if [ "${VRAM_MB:-0}" -gt 0 ]; then
        GPU_AVAILABLE=true
        printf "[info] NVIDIA GPU detected: %d MB total VRAM.\n" "$VRAM_MB"
    fi
fi

if $GPU_AVAILABLE; then
    if docker info 2>/dev/null | grep -qE 'Runtimes:[^$]*nvidia'; then
        TOOLKIT_AVAILABLE=true
        printf "[info] nvidia-container-toolkit is set up — enabling GPU passthrough.\n"
    else
        cat <<'EOF'
[warn] GPU detected, but nvidia-container-toolkit isn't wired into
       Docker. Ollama will run on CPU (slow). To enable GPU:

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update
    sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker

Then re-run this script.
EOF
    fi
fi

# Pick the default model tier based on what fits in the detected VRAM.
# Q4_K_M quantisation sizes, rough upper bounds:
#   llama3.2:3b  ~ 2 GB
#   llama3.1:8b  ~ 5 GB
#   qwen2.5:14b  ~ 9 GB
#   qwen2.5:32b  ~ 20 GB
if [ -z "${MODEL_NAME:-}" ]; then
    if $TOOLKIT_AVAILABLE && [ "$VRAM_MB" -ge 22000 ]; then
        MODEL_NAME="qwen2.5:14b"       # 24 GB GPUs: strong reasoning, ~9 GB resident
    elif $TOOLKIT_AVAILABLE && [ "$VRAM_MB" -ge 8000 ]; then
        MODEL_NAME="llama3.1:8b"       # 8-22 GB GPUs: solid function calling
    else
        MODEL_NAME="llama3.2:3b"       # CPU or small GPU: the safe fallback
    fi
    printf "[info] Selected model: %s\n" "$MODEL_NAME"
else
    printf "[info] Using MODEL_NAME from environment: %s\n" "$MODEL_NAME"
fi
export MODEL_NAME

# ---------------------------------------------------------------------------
# Compose file selection
# ---------------------------------------------------------------------------

COMPOSE_FILES=(-f docker-compose.yml)
if $TOOLKIT_AVAILABLE; then
    COMPOSE_FILES+=(-f docker-compose.gpu.yml)
fi

# ---------------------------------------------------------------------------
# User + bind mounts
# ---------------------------------------------------------------------------

mkdir -p "Darwin Research/Research/Incoming" papers logs
PUID=$(id -u)
PGID=$(id -g)
export PUID PGID

# ---------------------------------------------------------------------------
# Start — detached or foreground-with-auto-shutdown
# ---------------------------------------------------------------------------

if [ "$DETACH" = "1" ]; then
    printf "==> Starting detached (model=%s, user=%s:%s)...\n" "$MODEL_NAME" "$PUID" "$PGID"
    docker compose "${COMPOSE_FILES[@]}" up -d --build
    cat <<EOF

Darwin is starting. Open http://localhost:8501 once logs settle.

    docker compose logs -f darwin        # watch startup
    docker compose ps                    # status
    docker compose down                  # stop when done
EOF
    exit 0
fi

# Foreground mode: install cleanup trap BEFORE compose up so Ctrl-C during
# the build also tears things down, then stream logs until interrupted.
_cleanup_ran=0
cleanup() {
    # Guard against double execution (EXIT + INT both fire).
    [ "$_cleanup_ran" = "1" ] && return
    _cleanup_ran=1
    trap - EXIT INT TERM HUP
    printf "\n==> Shutting down the stack (Ctrl-C received)...\n"
    docker compose "${COMPOSE_FILES[@]}" down
    printf "==> Done. Data volumes and bind mounts are preserved.\n"
}
trap cleanup EXIT INT TERM HUP

printf "==> Starting (model=%s, user=%s:%s)...\n" "$MODEL_NAME" "$PUID" "$PGID"
docker compose "${COMPOSE_FILES[@]}" up -d --build

cat <<EOF

==> Darwin is running.

    Open:  http://localhost:8501
    Stop:  Ctrl-C here (or close this terminal) — auto shuts down everything.

==> Streaming darwin logs (Ctrl-C to stop):

EOF

# Block until the user hits Ctrl-C. `logs -f` exits 130 on SIGINT; '|| true'
# so errexit doesn't short-circuit before the trap can run.
docker compose "${COMPOSE_FILES[@]}" logs -f darwin || true
