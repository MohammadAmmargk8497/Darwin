#!/usr/bin/env bash
# Bring Darwin up via docker compose. Zero host changes beyond Docker itself.

set -euo pipefail

cd "$(dirname "$0")/.."

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
# `docker pull` fails with:
#     error getting credentials - err: exec: "docker-credential-desktop":
#     executable file not found in $PATH
# Detect that case and offer a surgical fix.
check_docker_credentials() {
    local config="$HOME/.docker/config.json"
    [ -f "$config" ] || return 0

    # Is credsStore set to "desktop"?
    if ! grep -qE '"credsStore"[[:space:]]*:[[:space:]]*"desktop"' "$config"; then
        return 0
    fi

    # If the helper binary actually exists, the config is fine — Docker
    # Desktop is installed here and will be used.
    if command -v docker-credential-desktop >/dev/null 2>&1; then
        return 0
    fi

    cat <<EOF
[warn] ~/.docker/config.json has "credsStore": "desktop" but
       docker-credential-desktop is not installed on this machine.
       Image pulls will fail with a credential-helper error.
EOF

    # Non-interactive (e.g. CI): don't modify config silently, print the
    # manual command and exit.
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
        *)
            printf "[error] Aborted. Fix manually and re-run this script.\n" >&2
            exit 1
            ;;
    esac

    local backup="${config}.bak.$(date +%s)"
    cp "$config" "$backup"
    printf "[info] Backup saved: %s\n" "$backup"

    if command -v jq >/dev/null 2>&1; then
        # Surgical: drop just the credsStore key, preserve everything else.
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
        # No jq — the safest thing is to move the whole file aside. Docker
        # will create a fresh default on next invocation. Credential logins
        # (if any) are preserved in the backup; users can restore manually.
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

    # If port is bound by our own compose stack, there's nothing to do —
    # `compose up -d` will be a no-op for running services.
    if command -v docker >/dev/null 2>&1 && \
       docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'darwin-ollama'; then
        printf "[info] darwin-ollama is already running — compose will reuse it.\n"
        return 0
    fi

    # Is the listener an Ollama server?
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
        *)
            printf "[error] Aborted. Stop Ollama yourself and re-run.\n" >&2
            exit 1
            ;;
    esac

    local stopped=false
    if command -v systemctl >/dev/null 2>&1 && \
       systemctl is-active --quiet ollama 2>/dev/null; then
        printf "[info] Stopping ollama.service via systemctl (sudo prompt may appear)...\n"
        if sudo systemctl stop ollama; then
            stopped=true
        fi
    fi

    # Catch foreground `ollama serve` instances too.
    if pgrep -x ollama >/dev/null 2>&1; then
        printf "[info] Killing foreground ollama processes...\n"
        pkill -x ollama 2>/dev/null || true
        stopped=true
    fi

    if ! $stopped; then
        printf "[error] Couldn't identify how to stop Ollama. Stop it manually and re-run.\n" >&2
        exit 1
    fi

    # Wait up to 10s for the port to actually free up.
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

# Ensure bind-mount targets exist so Docker doesn't create them as root-owned.
mkdir -p "Darwin Research/Research/Incoming" papers logs

# Pass the invoking user's UID/GID so files written to the bind mounts
# stay owned by this user on the host (see docker-compose.yml).
PUID=$(id -u)
PGID=$(id -g)
export PUID PGID

printf "==> Building Darwin image and starting the stack (user %s:%s)...\n" "$PUID" "$PGID"
docker compose up -d --build

cat <<EOF

==> Darwin is starting.

First run downloads the llama3.2:3b model (~2 GB) — watch progress:

    docker compose logs -f darwin

Once you see "You can now view your Streamlit app in your browser", open:

    http://localhost:8501

Other useful commands:

    docker compose ps                  # service status
    docker compose logs -f             # tail all logs
    docker compose down                # stop (data is preserved)
    docker compose down -v             # stop AND drop the model volume

EOF
