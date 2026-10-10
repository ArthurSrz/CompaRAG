"""Engine metadata — frozen facts about each engine, importable without
the engine's heavy framework deps.

The mcp_servers.json generator (scripts/generate_mcp_registry.py) reads this
module to emit Tool Arena entries; it must not require LangChain, LlamaIndex,
Haystack, etc. to be installed. Runtime engine *instantiation* still happens
in mcp_servers/rag_pill/server.py and does require those deps.

Adding a new engine = appending one EngineMetadata entry below.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineMetadata:
    id: str
    name: str  # short framework name for the registry "name" field, e.g. "LangChain"
    display_label: str  # full label appended to entry description, e.g. "LangChain + FAISS"
    supports: frozenset[str]  # task_types the engine can execute
    sanitize_terms: tuple[str, ...] = ()  # brand strings to scrub before reveal
    # Experimental engines are instantiated by the server but kept OUT of the
    # generated arena registry: they can be exercised directly while their
    # prerequisites are missing, without being matched against the live
    # engines and losing votes for a reason that is not about their quality.
    experimental: bool = False
    # Free-text note on what an experimental engine is still waiting for.
    experimental_reason: str = ""


ENGINES: tuple[EngineMetadata, ...] = (
    EngineMetadata(
        id="langchain",
        name="LangChain",
        display_label="LangChain + FAISS",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("LangChain", "langchain", "FAISS"),
    ),
    EngineMetadata(
        id="llamaindex",
        name="LlamaIndex",
        display_label="LlamaIndex + VectorStoreIndex",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("LlamaIndex", "llama-index", "llama_index"),
    ),
    EngineMetadata(
        id="haystack",
        name="Haystack",
        display_label="Haystack + InMemoryDocumentStore",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("Haystack", "haystack", "deepset"),
    ),
    EngineMetadata(
        id="txtai",
        name="txtai",
        display_label="txtai Embeddings DB",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("txtai", "TXTAI", "NeuML"),
    ),
    EngineMetadata(
        id="bm25",
        name="BM25",
        display_label="BM25 Okapi — recherche lexicale, sans embeddings",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("BM25", "bm25", "Okapi", "okapi"),
    ),
    EngineMetadata(
        id="hybrid",
        name="Hybride",
        display_label="Hybride BM25 + dense, fusion par rang réciproque (RRF)",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("BM25", "bm25", "Okapi", "RRF", "rrf", "hybride", "Hybrid"),
    ),
    EngineMetadata(
        id="colpali",
        name="ColPali",
        display_label="ColPali — late interaction visuelle sur pages PDF (encodeur visuel propre)",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=(
            "ColPali",
            "colpali",
            "ColQwen",
            "colSmol",
            "ColSmol",
            "Vidore",
            "vidore",
            "PaliGemma",
            "Idefics",
        ),
        experimental=True,
        experimental_reason=(
            "needs a PDF corpus in mcp_servers/corpus/ and a validated run "
            "against real ColPali weights; see mcp_servers/rag_pill/COLPALI.md"
        ),
    ),
    EngineMetadata(
        id="chroma_baseline",
        name="Chroma (baseline)",
        display_label="Chroma + naive retriever",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("Chroma", "chroma", "chromadb"),
    ),
)


METADATA_BY_ID: dict[str, EngineMetadata] = {e.id: e for e in ENGINES}
