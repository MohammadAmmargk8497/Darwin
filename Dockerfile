# Darwin research agent — container image.
# Multi-stage so the runtime layer doesn't carry build-essential.

# ---- builder ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Most of our deps ship wheels, but build-essential is there as a safety net
# for architectures without prebuilt pymupdf wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PAPER_STORAGE=/data/papers \
    OBSIDIAN_VAULT_PATH=/data/vault \
    DARWIN_LOG_DIR=/data/logs \
    RESEARCH_LOG_DB=/data/logs/research_log.db \
    API_BASE=http://ollama:11434 \
    PROVIDER=ollama \
    MODEL_NAME=llama3.2:3b

WORKDIR /app

# curl is used by entrypoint.sh to poll Ollama and trigger the model pull.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Copy installed deps from the builder.
COPY --from=builder /install /usr/local

# Application code. Ordering below is deliberate: pyproject/config layers
# change less often than src/, which changes less often than ui_app.py.
COPY pyproject.toml requirements.txt ./
COPY config/ ./config/
COPY src/ ./src/
COPY ui_app.py agent_wrapper.py ./
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    mkdir -p /data/papers /data/vault/Research/Incoming /data/logs

# We intentionally run as root inside the container. This is a single-user
# local dev tool bound to 127.0.0.1, and root-in-container keeps file
# ownership on bind-mounted host directories matching the invoking user
# when combined with the `user:` directive in docker-compose.yml.

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["streamlit", "run", "ui_app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
