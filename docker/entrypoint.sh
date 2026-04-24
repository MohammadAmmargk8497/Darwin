#!/bin/sh
# Darwin container entrypoint.
#
# Waits for the Ollama service to be reachable, ensures the requested model
# is pulled, then hands off to whatever CMD was passed (Streamlit by
# default). Non-fatal: if Ollama never comes up, the UI still starts and
# surfaces a visible warning rather than hanging.

set -e

API="${API_BASE:-http://ollama:11434}"
MODEL="${MODEL_NAME:-llama3.2:3b}"

# Ollama check is a no-op when provider is openai/groq/etc.
if [ "${PROVIDER:-ollama}" = "ollama" ]; then
    printf "[entrypoint] Waiting for Ollama at %s...\n" "$API"
    i=0
    until curl -fsS "$API/api/tags" >/dev/null 2>&1; do
        i=$((i + 1))
        if [ "$i" -ge 90 ]; then
            printf "[entrypoint] Ollama not reachable after 90s — UI will start and show a warning.\n"
            break
        fi
        sleep 1
    done

    # Pull the requested model if we can reach Ollama and it isn't already present.
    if curl -fsS "$API/api/tags" >/dev/null 2>&1; then
        if curl -fsS "$API/api/tags" | grep -q "\"name\":\"${MODEL}\""; then
            printf "[entrypoint] Model '%s' already available.\n" "$MODEL"
        else
            printf "[entrypoint] Pulling model '%s' — first run can take several minutes...\n" "$MODEL"
            # Stream the pull so users see progress in `docker compose logs`.
            # If the pull fails, log and continue — the UI will show the error.
            curl -N -X POST "$API/api/pull" \
                -H "Content-Type: application/json" \
                -d "{\"name\":\"$MODEL\"}" \
                || printf "[entrypoint] Model pull returned a non-zero exit; UI will surface the error.\n"
            printf "\n[entrypoint] Model pull finished.\n"
        fi

        # Fire a throwaway generation so Ollama compiles CUDA kernels, warms
        # the KV cache allocator, and loads weights into VRAM before the
        # user's first real query. Without this the first UI turn eats an
        # 8-10s cold-start penalty. We cap num_ctx identically to what the
        # agent uses so the warmup actually warms the right configuration.
        WARMUP_CTX="${OLLAMA_NUM_CTX:-8192}"
        printf "[entrypoint] Warming model (num_ctx=%s)...\n" "$WARMUP_CTX"
        curl -fsS -X POST "$API/api/generate" \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_ctx\":$WARMUP_CTX}}" \
            >/dev/null 2>&1 \
            && printf "[entrypoint] Warmup done — first query will be fast.\n" \
            || printf "[entrypoint] Warmup skipped (non-fatal).\n"
    fi
fi

exec "$@"
