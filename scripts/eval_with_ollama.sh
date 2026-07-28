#!/usr/bin/env bash
# Run the ENVX retrieval evaluation against a local Ollama.
#
#   ./scripts/eval_with_ollama.sh [model]
#
# Defaults to bge-m3. Handles the things that usually go wrong:
#   - Ollama already running as a service, so `ollama serve` exits 1.
#   - Model not pulled yet.
#   - Embedding dimension guessed wrong — it is detected, not assumed.

set -uo pipefail

MODEL="${1:-bge-m3}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

command -v ollama >/dev/null 2>&1 || fail "ollama not found. Install from https://ollama.com"

# --- 1. server ---------------------------------------------------------
# On macOS the desktop app already runs it, in which case `ollama serve`
# exits 1 with "address already in use" — which is success for our purposes.
if ! curl -sf "${HOST}/api/tags" >/dev/null 2>&1; then
    say "starting ollama..."
    ollama serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do
        curl -sf "${HOST}/api/tags" >/dev/null 2>&1 && break
        sleep 1
    done
fi
curl -sf "${HOST}/api/tags" >/dev/null 2>&1 || fail "ollama is not answering at ${HOST}"
say "ollama up at ${HOST}"

# --- 2. model ----------------------------------------------------------
if ! ollama list 2>/dev/null | awk '{print $1}' | grep -q "^${MODEL}\(:latest\)\?$"; then
    say "pulling ${MODEL}..."
    ollama pull "${MODEL}" || fail "could not pull ${MODEL}"
fi

# --- 3. dimension ------------------------------------------------------
# Detect rather than assume. A wrong ENVX_EMBEDDING_DIM is the single most
# common setup failure, and the value differs per model (bge-m3 is 1024,
# nomic-embed-text is 768, mxbai-embed-large is 1024).
DIM=$(curl -sf "${HOST}/v1/embeddings" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${MODEL}\",\"input\":[\"dimension probe\"]}" \
      | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["data"][0]["embedding"]))' 2>/dev/null)

[ -n "${DIM:-}" ] || fail "could not read an embedding from ${MODEL} via ${HOST}/v1/embeddings"
say "${MODEL} embedding dimension: ${DIM}"

# --- 4. run ------------------------------------------------------------
cd "${REPO}"
export ENVX_EMBEDDING_URL="${HOST}"
export ENVX_EMBEDDING_MODEL="${MODEL}"
export ENVX_EMBEDDING_DIM="${DIM}"
export PYTHONPATH=src

echo
python3 -m envx.cli eval --tags "$@"
