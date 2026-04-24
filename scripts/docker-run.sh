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
