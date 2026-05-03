"""LlamaIndex RAG MCP Server — FastMCP on port 8011 (or $PORT)."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [llamaindex-rag] %(message)s")
log = logging.getLogger("llamaindex_rag")

from fastmcp import FastMCP
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai_like import OpenAILike
from starlette.requests import Request
from starlette.responses import PlainTextResponse

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

Settings.embed_model = OpenAIEmbedding(
    model="text-embedding-3-small",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
Settings.llm = OpenAILike(
    # mistral-small-3.1-24b-instruct is served ONLY by Cloudflare on
    # OpenRouter, which silently caps output at ~143 tokens regardless
    # of max_tokens. mistral-medium-3.1 is served by Mistral's official
    # endpoint, which honors max_tokens correctly.
    model="mistralai/mistral-medium-3.1",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    is_chat_model=True,
    max_tokens=4096,
    context_window=128000,
)

# Set after lifespan build
query_engine = None


@asynccontextmanager
async def lifespan(app):
    global query_engine
    print("Loading corpus and building VectorStoreIndex...")
    loop = asyncio.get_event_loop()
    documents = SimpleDirectoryReader(str(CORPUS_DIR)).load_data()
    index = await loop.run_in_executor(
        None, lambda: VectorStoreIndex.from_documents(documents)
    )
    query_engine = index.as_query_engine(similarity_top_k=3)
    print(f"Index ready: {len(documents)} documents loaded")
    yield


mcp = FastMCP("LlamaIndex RAG", lifespan=lifespan)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


AGENT_SYSTEM_PROMPT = (
    "Résumez le document ou contenu suivant de manière claire et "
    "concise, en capturant les points clés."
)


async def search_documents(query: str) -> str:
    """Useful for answering natural language questions over the static corpus.

    Tutorial-shape helper: delegates to the LlamaIndex query engine via aquery.
    """
    if query_engine is None:
        log.info("search_documents.skip %s", json.dumps({"reason": "engine_not_ready"}))
        return "Index not ready yet, please retry in a moment."

    log.info(
        "search_documents.request %s",
        json.dumps({
            "engine_method": "aquery",
            "query_chars": len(query),
            "query_preview": query[:200],
        }),
    )
    t0 = time.time()
    response = await query_engine.aquery(query)
    duration_ms = int((time.time() - t0) * 1000)
    text = str(response)
    log.info(
        "search_documents.response %s",
        json.dumps({
            "engine_method": "aquery",
            "answer_chars": len(text),
            "duration_ms": duration_ms,
            "retrieved_chunks": len(getattr(response, "source_nodes", []) or []),
        }),
    )
    return text


def build_agent(llm=None):
    """Build a FunctionAgent exposing only the search_documents tool."""
    from llama_index.core.agent.workflow import FunctionAgent

    log.info(
        "build_agent %s",
        json.dumps({
            "tools": ["search_documents"],
            "system_prompt_chars": len(AGENT_SYSTEM_PROMPT),
            "system_prompt_preview": AGENT_SYSTEM_PROMPT[:120],
            "llm": getattr(llm or Settings.llm, "model", None),
        }),
    )
    return FunctionAgent(
        tools=[search_documents],
        llm=llm if llm is not None else Settings.llm,
        system_prompt=AGENT_SYSTEM_PROMPT,
    )


@mcp.tool()
async def rag_query(task: str, goal: str, document_content: str = "") -> str:
    """Answer a question using RAG over a document or the static corpus, synthesized by Mistral Small.

    If document_content is provided, builds an ephemeral in-memory index from it.
    Otherwise falls back to the pre-built static corpus index.
    """
    from llama_index.core import Document as LIDocument

    query = f"{task} {goal}"
    mode = "uploaded" if document_content.strip() else "corpus"

    llm_metadata = {
        "model": getattr(Settings.llm, "model", None),
        "max_tokens": getattr(Settings.llm, "max_tokens", None),
        "context_window": getattr(Settings.llm, "context_window", None),
        "api_base": getattr(Settings.llm, "api_base", None),
    }

    if document_content.strip():
        # User-uploaded doc: bypass vector retrieval and call the LLM directly
        # with the full document. Chunking a short user doc into k=3 chunks
        # returns sparse context and frequently produces "Empty Response".
        # The full doc fits in Mistral's 128k context window.
        prompt = (
            "You are a thorough technical writer. Provide a detailed, well-structured "
            "answer to the user's question using ONLY the document below. "
            "Use markdown formatting: headings, bullet points, sub-bullets, and code blocks where relevant. "
            "Include direct quotes or specific details from the document. "
            "Aim for a comprehensive answer (multiple paragraphs or bullet sections) when the document supports it.\n\n"
            f"Document:\n{document_content}\n\n"
            f"Question: {query}\n\n"
            "Detailed Answer:"
        )

        log.info(
            "rag_query.request %s",
            json.dumps({
                "mode": mode,
                "task_chars": len(task),
                "goal_chars": len(goal),
                "document_chars": len(document_content),
                "prompt_chars": len(prompt),
                "sources": ["uploaded"],
                "llm": llm_metadata,
            }),
        )

        t0 = time.time()
        completion = Settings.llm.complete(prompt)
        duration_ms = int((time.time() - t0) * 1000)
        text = str(completion)

        log.info(
            "rag_query.response %s",
            json.dumps({
                "mode": mode,
                "answer_chars": len(text),
                "duration_ms": duration_ms,
                "raw_metadata": getattr(completion, "additional_kwargs", None),
            }),
        )

        return text
    else:
        if query_engine is None:
            return "Index not ready yet, please retry in a moment."

        log.info(
            "rag_query.request %s",
            json.dumps({
                "mode": mode,
                "task_chars": len(task),
                "goal_chars": len(goal),
                "document_chars": 0,
                "query": query[:200],
                "llm": llm_metadata,
                "engine_method": "aquery",
                "agent_system_prompt_chars": len(AGENT_SYSTEM_PROMPT),
            }),
        )

        t0 = time.time()
        response = await query_engine.aquery(query)
        duration_ms = int((time.time() - t0) * 1000)

        sources = set(
            Path(n.metadata.get("file_name", "unknown")).stem
            for n in response.source_nodes
            if n.metadata.get("file_name")
        )
        source_str = f"Sources: {', '.join(sources)}\n\n" if sources else ""
        text = str(response) if response.response is None else response.response

        log.info(
            "rag_query.response %s",
            json.dumps({
                "mode": mode,
                "answer_chars": len(text),
                "duration_ms": duration_ms,
                "retrieved_chunks": len(response.source_nodes),
                "sources": sorted(sources),
            }),
        )

        return f"{source_str}{text}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8011)), path="/mcp")
