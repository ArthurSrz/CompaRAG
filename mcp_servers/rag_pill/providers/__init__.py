"""LLM and embedding provider adapters.

`LLMProvider` is a real Protocol — engines call it for generation, regardless
of which framework they use for indexing/retrieval. This keeps the test
surface clean (stub provider in tests, no live OPENROUTER_API_KEY needed)
and concentrates OpenRouter wiring in one place.

`EmbeddingConfig` is a plain config object — embedders cannot be unified
across frameworks (FAISS wants a LangChain `OpenAIEmbeddings`, LlamaIndex
wants its own `OpenAIEmbedding`, Haystack wants a `OpenAIDocumentEmbedder`),
so engines construct their framework-native embedder from this shared config
instead of re-reading os.environ themselves.
"""

from mcp_servers.rag_pill.providers.embedding import EmbeddingConfig
from mcp_servers.rag_pill.providers.llm import LLMProvider, OpenRouterLLM

__all__ = ["EmbeddingConfig", "LLMProvider", "OpenRouterLLM"]
