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
