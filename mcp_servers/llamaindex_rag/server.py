"""LlamaIndex RAG MCP Server — FastMCP on port 8011 (or $PORT)."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

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
    model="mistralai/mistral-small-3.1-24b-instruct",
    api_base="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    is_chat_model=True,
    max_tokens=4096,
    context_window=128000,
    # Mirror the langchain fix: forward max_tokens via the raw API body
    # so OpenRouter receives it. LlamaIndex's OpenAILike sometimes maps
    # max_tokens differently when is_chat_model=True; additional_kwargs
    # is forwarded verbatim into the chat completions request.
    # Cloudflare (OpenRouter's cheapest Mistral provider) silently caps
    # output at ~143 tokens regardless of max_tokens. Route around it.
    additional_kwargs={
        "max_tokens": 4096,
        "provider": {"order": ["mistral", "together", "deepinfra"], "allow_fallbacks": True},
    },
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


@mcp.tool()
def rag_query(task: str, goal: str, document_content: str = "") -> str:
    """Answer a question using RAG over a document or the static corpus, synthesized by Mistral Small.

    If document_content is provided, builds an ephemeral in-memory index from it.
    Otherwise falls back to the pre-built static corpus index.
    """
    from llama_index.core import Document as LIDocument

    query = f"{task} {goal}"

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
        text = str(Settings.llm.complete(prompt))
        return f"Sources: uploaded\n\n{text}"
    else:
        if query_engine is None:
            return "Index not ready yet, please retry in a moment."
        response = query_engine.query(query)
        sources = set(
            Path(n.metadata.get("file_name", "unknown")).stem
            for n in response.source_nodes
            if n.metadata.get("file_name")
        )
        source_str = f"Sources: {', '.join(sources)}\n\n" if sources else ""
        return f"{source_str}{response.response}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8011)), path="/mcp")
