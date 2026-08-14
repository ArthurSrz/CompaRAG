# Interview Pill MCP server — Railway service image.
#
# Hosts the two knowledge-capture InterviewStrategies (grill / gsd_discuss)
# behind a single stateless `interview_move` tool. Separate from the backend
# image for the same reason as pageindex: litellm has no business in the
# backend, and one Railway service per MCP server is the house pattern.
#
# Deployed via railway.interview.toml — see mcp_servers/interview_pill/README.md.

FROM python:3.13-slim AS runtime

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first so the layer caches across server.py edits.
COPY mcp_servers/interview_pill/requirements.txt /app/mcp_servers/interview_pill/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp_servers/interview_pill/requirements.txt

COPY mcp_servers/interview_pill/server.py /app/mcp_servers/interview_pill/server.py
COPY mcp_servers/interview_pill/prompts /app/mcp_servers/interview_pill/prompts
COPY mcp_servers/interview_pill/tool.manifest.yaml /app/mcp_servers/interview_pill/tool.manifest.yaml

# Make mcp_servers/ a package so `python -m mcp_servers.interview_pill.server` works.
RUN touch /app/mcp_servers/__init__.py /app/mcp_servers/interview_pill/__init__.py

ENV PYTHONPATH=/app
# Default port mirrors the local-dev endpoint in mcp_servers.external.json.
# Railway will set $PORT — server.py reads it.
EXPOSE 8014

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8014}/health" || exit 1

CMD ["python", "-m", "mcp_servers.interview_pill.server"]
