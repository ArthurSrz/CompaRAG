"""LangChain engine adapter — lazy-imports langchain so a missing install
only disables this engine via SUPPORTS = set()."""

import asyncio
import os
from pathlib import Path

from mcp_servers.rag_pill.cache import IndexCache, doc_hash
from mcp_servers.rag_pill.schemas import Pill, QAPill, SummaryPill

CORPUS_DIR = Path(__file__).resolve().parent.parent.parent / "corpus"

try:
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document as LCDocument
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class LangChainEngine:
    id = "langchain"
    SUPPORTS: set[str] = {"summary", "qa"} if _AVAILABLE else set()

    def __init__(self, cache: IndexCache) -> None:
        self._cache = cache
        self._api_key = os.environ["OPENROUTER_API_KEY"]

    def _splitter(self, pill: Pill):
        return RecursiveCharacterTextSplitter(
            chunk_size=pill.chunk_size, chunk_overlap=pill.chunk_overlap
        )

    def _embeddings(self, pill: Pill):
        return OpenAIEmbeddings(
            model=pill.embedder,
            base_url="https://openrouter.ai/api/v1",
            openai_api_key=self._api_key,
        )

    def _llm(self, pill: Pill):
        max_tokens = getattr(pill, "max_output_tokens", 4096)
        return ChatOpenAI(
            model=pill.llm,
            base_url="https://openrouter.ai/api/v1",
            api_key=self._api_key,
            temperature=pill.temperature,
            extra_body={"max_tokens": max_tokens},
        )

    async def _build_index(self, pill: Pill, document_content: str):
        loop = asyncio.get_event_loop()
        splitter = self._splitter(pill)
        embeddings = self._embeddings(pill)

        if document_content.strip():
            doc = LCDocument(page_content=document_content, metadata={"source": "uploaded"})
            chunks = splitter.split_documents([doc])
        else:
            loader = DirectoryLoader(str(CORPUS_DIR), glob="*.md", loader_cls=TextLoader)
            docs = loader.load()
            chunks = splitter.split_documents(docs)

        return await loop.run_in_executor(
            None, lambda: FAISS.from_documents(chunks, embeddings)
        )

    async def execute(
        self, pill: Pill, task: str, goal: str, document_content: str
    ) -> str:
        key = (
            self.id,
            pill.embedder,
            pill.chunk_size,
            pill.chunk_overlap,
            doc_hash(document_content),
        )
        vectorstore = await self._cache.get_or_build(
            key, lambda: self._build_index(pill, document_content)
        )

        top_k = getattr(pill, "top_k", 3)
        retriever = vectorstore.as_retriever(search_kwargs={"k": top_k})
        query = f"{task} {goal}"
        results = retriever.invoke(query)
        context = "\n\n---\n\n".join(d.page_content for d in results)

        if isinstance(pill, SummaryPill):
            instruction = (
                f"Summarize the context as {pill.style}, "
                f"compressing to ~{int(pill.compression_ratio * 100)}% of source length."
            )
        elif isinstance(pill, QAPill):
            cite = " Cite source chunks." if pill.cite_sources else ""
            instruction = f"Answer the question using ONLY the context.{cite}"
        else:
            instruction = "Use the context to satisfy the goal."

        prompt = ChatPromptTemplate.from_template(
            f"{instruction}\n\nContext:\n{{context}}\n\nQuestion: {{query}}\n\nAnswer:"
        )
        msgs = prompt.format_messages(context=context, query=query)
        answer = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._llm(pill).invoke(msgs)
        )
        return answer.content
