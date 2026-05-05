FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libstdc++6 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY mcp_servers/rag_pill/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/corpus /app/mcp_servers/corpus
COPY mcp_servers/rag_pill /app/mcp_servers/rag_pill
RUN touch /app/mcp_servers/__init__.py

EXPOSE 8012

ENV PYTHONPATH=/app
CMD ["python", "-m", "mcp_servers.rag_pill.server"]
