#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

# Use isolated venv if available
if [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON="$DIR/.venv/bin/python"
else
    PYTHON="python"
fi

echo "Starting LangChain RAG server on port 8010..."
"$PYTHON" "$DIR/langchain_rag/server.py" &
PID1=$!

echo "Starting LlamaIndex RAG server on port 8011..."
"$PYTHON" "$DIR/llamaindex_rag/server.py" &
PID2=$!

trap "echo 'Stopping servers...'; kill $PID1 $PID2 2>/dev/null" EXIT INT TERM
echo "Both servers running. Press Ctrl+C to stop."
wait
