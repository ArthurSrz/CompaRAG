"""LangChain RAG MCP Server — FastMCP on port 8010 (or $PORT)."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

llm = ChatOpenAI(
    model="mistralai/mistral-small-3.1-24b-instruct",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    # Forward max_tokens via the raw API request body (extra_body) so it
    # bypasses LangChain's parameter translation. Newer langchain-openai
    # versions translate `max_tokens` → `max_completion_tokens`, which
    # OpenRouter does NOT recognize for Mistral Small, and the request
    # falls back to the provider default (~100 tokens). Sending the raw
    # `max_tokens` field via extra_body forces it through.
    # Cloudflare (OpenRouter's cheapest Mistral provider) silently caps
    # output at ~113 tokens regardless of max_tokens. Force OpenRouter to
    # route to providers with proper max_tokens honoring.
    extra_body={
        "max_tokens": 4096,
        "provider": {"order": ["mistral", "together", "deepinfra"], "allow_fallbacks": True},
    },
)

embeddings = OpenAIEmbeddings(
    model="openai/text-embedding-3-small",
    base_url="https://openrouter.ai/api/v1",
    openai_api_key=OPENROUTER_API_KEY,
)

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

_PROMPT = ChatPromptTemplate.from_template(
    "You are a thorough technical writer. Provide a detailed, well-structured answer "
    "to the user's question using ONLY the context below. "
    "Use markdown formatting: headings, bullet points, sub-bullets, and code blocks where relevant. "
    "Include direct quotes or specific details from the context. "
    "Aim for a comprehensive answer (multiple paragraphs or bullet sections) when the context supports it. "
    "If the context truly does not contain enough information, say so explicitly.\n\n"
    "Context:\n{context}\n\n"
    "Question: {query}\n\n"
    "Detailed Answer:"
)

# Set after lifespan build
retriever = None


@asynccontextmanager
async def lifespan(app):
    global retriever
    print("Loading corpus and building FAISS index...")
    loop = asyncio.get_event_loop()
    loader = DirectoryLoader(str(CORPUS_DIR), glob="*.md", loader_cls=TextLoader)
    docs = loader.load()
    chunks = splitter.split_documents(docs)
    vectorstore = await loop.run_in_executor(
        None, lambda: FAISS.from_documents(chunks, embeddings)
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    print(f"Index ready: {len(chunks)} chunks from {len(docs)} documents")
    yield


mcp = FastMCP("LangChain RAG", lifespan=lifespan)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.tool()
def rag_query(task: str, goal: str, document_content: str = "") -> str:
    """Answer a question using RAG over a document or the static corpus, synthesized by Mistral Small.

    If document_content is provided, builds an ephemeral in-memory index from it.
    Otherwise falls back to the pre-built static corpus index.
    """
    from langchain_core.documents import Document as LCDocument

    query = f"{task} {goal}"

    if document_content.strip():
        # User-uploaded doc: bypass FAISS retrieval and pass the FULL doc to
        # the LLM. Chunking + k=3 retrieval over a short user doc returns
        # sparse context and triggers "context not enough" refusals. The
        # whole doc fits comfortably in Mistral's 128k context window.
        context = document_content
        sources = {"uploaded"}
    else:
        if retriever is None:
            return "Index not ready yet, please retry in a moment."
        results = retriever.invoke(query)
        if not results:
            return "No relevant documents found for this query."
        context = "\n\n---\n\n".join(doc.page_content for doc in results)
        sources = set(Path(doc.metadata.get("source", "unknown")).stem for doc in results)

    messages = _PROMPT.format_messages(context=context, query=query)
    answer = llm.invoke(messages)

    return f"Sources: {', '.join(sources)}\n\n{answer.content}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8010)), path="/mcp")
