#!/bin/bash
set -e

# Auto-detect a sibling Ollama container on the compose network. Only kicks
# in when the user hasn't explicitly pointed AI_LLM_BASE_URL elsewhere, so
# existing deployments that talk to a host LLM are unaffected. See
# docs/LLM_SETUP.md and the `with-llm` profile in docker-compose.yml.
DEFAULT_LLM_BASE_URL="http://host.docker.internal:8080/v1"
if [ "${AI_LLM_BASE_URL:-$DEFAULT_LLM_BASE_URL}" = "$DEFAULT_LLM_BASE_URL" ] \
   && getent hosts ollama >/dev/null 2>&1; then
    export AI_LLM_BASE_URL="http://ollama:11434/v1"
    export AI_LLM_MODEL="${AI_LLM_MODEL:-qwen3:4b-instruct-q4_K_M}"
    echo "Detected Ollama sidecar; AI_LLM_BASE_URL=$AI_LLM_BASE_URL AI_LLM_MODEL=$AI_LLM_MODEL"
fi

# Wait for MongoDB to be ready
echo "Waiting for MongoDB..."
for i in $(seq 1 30); do
    if python -c "from pymongo import MongoClient; MongoClient('${MONGODB_URI:-mongodb://localhost:27017/}', serverSelectionTimeoutMS=2000).server_info()" 2>/dev/null; then
        echo "MongoDB is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "Warning: MongoDB not reachable after 30 seconds, starting anyway."
    fi
    sleep 1
done

# Ensure the default Ollama model is available on first boot when we're
# wired to a sibling sidecar. Idempotent: the pull API is a no-op if the
# model is already present.
if [ -n "${AI_LLM_BASE_URL:-}" ] && echo "$AI_LLM_BASE_URL" | grep -q '://ollama:'; then
    echo "Ensuring Ollama model $AI_LLM_MODEL is available (this may download on first boot)..."
    # Wait briefly for Ollama to finish starting before pulling.
    for i in $(seq 1 20); do
        if curl -fsS "http://ollama:11434/api/tags" >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
    curl -fsS -X POST "http://ollama:11434/api/pull" \
         -H 'Content-Type: application/json' \
         -d "{\"name\": \"$AI_LLM_MODEL\"}" >/dev/null \
      && echo "Ollama model $AI_LLM_MODEL ready." \
      || echo "Warning: could not pull $AI_LLM_MODEL. Extraction will error until this succeeds; run 'docker compose exec ollama ollama pull $AI_LLM_MODEL' manually."
fi

# Auto-load example data if database is empty (first boot)
CASE_COUNT=$(python -c "
from pymongo import MongoClient
c = MongoClient('${MONGODB_URI:-mongodb://localhost:27017/}', serverSelectionTimeoutMS=3000)
print(c['cases']['processed_cases'].count_documents({}))
" 2>/dev/null || echo "0")

if [ "$CASE_COUNT" = "0" ]; then
    echo "Empty database detected — loading example cases..."
    python -m vetpathdb load-examples
fi

# Skip the ~3 GB embedding-model download by default unless the LLM
# endpoint is actually reachable AND the caller did not explicitly opt in
# to model loading. Loading the embedding model is only useful when
# semantic-search-with-LLM-rerank is going to be run, which itself needs
# a working LLM endpoint.
if [ -z "${SKIP_MODELS:-}" ] && [ -z "${LOAD_MODELS:-}" ]; then
    if [ -n "${AI_LLM_BASE_URL:-}" ] && \
       curl -fsS --max-time 3 "${AI_LLM_BASE_URL%/}/models" >/dev/null 2>&1; then
        echo "LLM endpoint reachable; loading embedding model on startup."
    else
        echo "LLM endpoint not reachable; defaulting to SKIP_MODELS=true (set LOAD_MODELS=true to override)."
        export SKIP_MODELS=true
    fi
fi

# Start the server
exec python -m vetpathdb serve "$@"
