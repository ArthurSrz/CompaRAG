"""
BUT : un RAGTool basé sur LangChain — répond à une Question sur un Document
uploadé OU sur le Corpus statique, et renvoie sa réponse texte via le
protocole MCP. C'est l'un des outils que l'arène met en compétition.

Sera déplacé en Phase F sous mcp_servers/_legacy_standalone_servers/ une fois
que rag_pill (qui wrappe déjà LangChain comme moteur) aura prouvé sa stabilité.

LangChain RAG MCP Server — FastMCP on port 8010 (or $PORT).
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [langchain-rag] %(message)s")
log = logging.getLogger("langchain_rag")

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
    # mistral-small-3.1-24b-instruct is served ONLY by Cloudflare on
    # OpenRouter, which silently caps output at ~113 tokens regardless of
    # max_tokens. mistral-medium-3.1 is served by Mistral's official
    # endpoint, which honors max_tokens correctly.
    model="mistralai/mistral-medium-3.1",
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    extra_body={"max_tokens": 4096},
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
    mode = "uploaded" if document_content.strip() else "corpus"

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
    prompt_text = "\n".join(m.content for m in messages)

    log.info(
        "rag_query.request %s",
        json.dumps({
            "mode": mode,
            "task_chars": len(task),
            "goal_chars": len(goal),
            "document_chars": len(document_content),
            "context_chars": len(context),
            "prompt_chars": len(prompt_text),
            "sources": sorted(sources),
            "llm": {
                "model": llm.model_name,
                "base_url": str(llm.openai_api_base),
                "extra_body": getattr(llm, "extra_body", None),
            },
        }),
    )

    t0 = time.time()
    answer = llm.invoke(messages)
    duration_ms = int((time.time() - t0) * 1000)

    finish = None
    response_meta = getattr(answer, "response_metadata", {}) or {}
    finish = response_meta.get("finish_reason")
    usage = response_meta.get("token_usage") or response_meta.get("usage") or {}

    log.info(
        "rag_query.response %s",
        json.dumps({
            "mode": mode,
            "answer_chars": len(answer.content or ""),
            "duration_ms": duration_ms,
            "finish_reason": finish,
            "usage": usage,
        }),
    )

    if sources == {"uploaded"}:
        return answer.content
    return f"Sources: {', '.join(sources)}\n\n{answer.content}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", 8010)), path="/mcp")
