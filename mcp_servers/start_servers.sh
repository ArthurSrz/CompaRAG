#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$DIR/.." && pwd)"

if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
else
    PYTHON="python"
fi

echo "Starting RAG Pill dispatcher on port 8012..."
PYTHONPATH="$PROJECT_ROOT" PORT=8012 "$PYTHON" -m mcp_servers.rag_pill.server &
PID_PILL=$!

# Legacy servers — kept running during migration. Remove once mcp_servers.json
# no longer references their endpoints (and Railway services are torn down).
echo "Starting LangChain RAG (legacy) server on port 8010..."
"$PYTHON" "$DIR/langchain_rag/server.py" &
PID1=$!

echo "Starting LlamaIndex RAG (legacy) server on port 8011..."
"$PYTHON" "$DIR/llamaindex_rag/server.py" &
PID2=$!

trap "echo 'Stopping servers...'; kill $PID_PILL $PID1 $PID2 2>/dev/null" EXIT INT TERM
echo "All servers running. Press Ctrl+C to stop."
wait
