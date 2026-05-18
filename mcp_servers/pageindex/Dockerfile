# PageIndex MCP server — Railway service image.
#
# This Dockerfile is the build target for the dedicated Railway service that
# hosts PageIndex (https://github.com/VectifyAI/PageIndex). It's separate
# from the backend image because PageIndex pulls heavy deps (PyMuPDF, litellm)
# that the backend has no business carrying.
#
# Deployed via railway.pageindex.toml — see mcp_servers/pageindex/README.md.

# ── Stage 1 ──────────────────────────────────────────────────────────────────
# Fetch the pinned PageIndex source. Pinning to a SHA (not a tag) makes the
# build reproducible and avoids depending on Railway's submodule-init behavior.
FROM alpine/git AS pageindex-fetch
ARG PAGEINDEX_COMMIT=7592163e2a376b3917181fff9ac1858dc5daa2c6
RUN git clone https://github.com/VectifyAI/PageIndex.git /pageindex \
 && cd /pageindex \
 && git checkout ${PAGEINDEX_COMMIT}

# ── Stage 2 ──────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

RUN apt-get update -y \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first so the layer caches across server.py edits.
COPY mcp_servers/pageindex/requirements.txt /app/mcp_servers/pageindex/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp_servers/pageindex/requirements.txt

# Drop PageIndex sources at the path server.py expects (vendor/PageIndex/).
COPY --from=pageindex-fetch /pageindex /app/mcp_servers/pageindex/vendor/PageIndex

# Our server code.
COPY mcp_servers/pageindex/server.py /app/mcp_servers/pageindex/server.py
COPY mcp_servers/pageindex/tool.manifest.yaml /app/mcp_servers/pageindex/tool.manifest.yaml

# Make mcp_servers/ a package so `python -m mcp_servers.pageindex.server` works.
RUN touch /app/mcp_servers/__init__.py /app/mcp_servers/pageindex/__init__.py

ENV PYTHONPATH=/app
# Default port mirrors the local-dev endpoint in mcp_servers.external.json.
# Railway will set $PORT — server.py reads it (mcp_servers/pageindex/server.py).
EXPOSE 8013

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT:-8013}/health" || exit 1

CMD ["python", "-m", "mcp_servers.pageindex.server"]
