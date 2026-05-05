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
        id="chroma_baseline",
        name="Chroma (baseline)",
        display_label="Chroma + naive retriever",
        supports=frozenset({"summary", "qa"}),
        sanitize_terms=("Chroma", "chroma", "chromadb"),
    ),
)


METADATA_BY_ID: dict[str, EngineMetadata] = {e.id: e for e in ENGINES}
