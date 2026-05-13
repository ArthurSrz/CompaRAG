"""
Document library sub-router (DOC-02, DOC-03).

Isolated from the main router so tests can import this without
pulling in the psycopg2/Redis dependency chain via dispatcher.py.
"""

from pathlib import PurePosixPath

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from backend.tool_arena.documents import (
    DocumentDetail,
    DocumentSummary,
    document_registry,
)
from backend.tool_arena.extractors import (
    UnsupportedDocumentType,
    extract_text,
)

documents_router = APIRouter()

_DOCUMENTS_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"

# Unified upload cap (bytes). Every format gets the same 5 MB raw-upload
# budget; the prior 500 KB / 5 MB split conflated raw upload size with
# post-extraction text size. A 5 MB PDF typically extracts to <500 KB of
# text, while a 500 KB .txt is all text — so the two limits were
# inconsistent for users who think in "document size".
_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
_SIZE_LIMITS = {
    ".txt": _UPLOAD_MAX_BYTES,
    ".md": _UPLOAD_MAX_BYTES,
    ".pdf": _UPLOAD_MAX_BYTES,
    ".docx": _UPLOAD_MAX_BYTES,
}


@documents_router.get("/documents")
async def list_documents(response: Response):
    """Return catalogue of available documents (id, title, description — no content).

    Per DOC-02: unauthenticated, cacheable.
    """
    response.headers["Cache-Control"] = _DOCUMENTS_CACHE_CONTROL
    return [
        DocumentSummary(id=d.id, title=d.title, description=d.description)
        for d in document_registry.list_all()
    ]


@documents_router.get("/documents/{doc_id}")
async def get_document(doc_id: str, response: Response):
    """Return a single document by id including full content.

    Per DOC-03: unauthenticated, cacheable. HTTP 404 when doc_id is unknown.
    """
    doc = document_registry.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    response.headers["Cache-Control"] = _DOCUMENTS_CACHE_CONTROL
    return DocumentDetail(
        id=doc.id,
        title=doc.title,
        description=doc.description,
        content=doc.content,
    )


@documents_router.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):
    """Extract plain text from an uploaded document.

    Frontend uses this to convert binary uploads (.pdf, .docx) into the
    same `document_content: str` shape the rest of the tool-arena
    pipeline already consumes via POST /tool-arena/compare.
    """
    filename = file.filename or ""
    suffix = PurePosixPath(filename).suffix.lower()
    limit = _SIZE_LIMITS.get(suffix)
    data = await file.read()
    if limit is not None and len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds size limit ({len(data)} > {limit} bytes)",
        )
    try:
        text = extract_text(filename, data)
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return {"document_content": text, "char_count": len(text)}
