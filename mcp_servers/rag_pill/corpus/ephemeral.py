"""EphemeralCorpus — wraps user-uploaded text as a single-doc haystack."""

from __future__ import annotations

import hashlib
from functools import cached_property
from typing import Iterable

from mcp_servers.rag_pill.corpus.base import CorpusDocument, compute_version_hash


class EphemeralCorpus:
    id = "ephemeral"
    has_ground_truth = False

    def __init__(self, document_content: str) -> None:
        if not document_content.strip():
            raise ValueError("EphemeralCorpus requires non-empty document_content")
        upload_id = "upload-" + hashlib.sha256(
            document_content.encode("utf-8")
        ).hexdigest()[:16]
        self._doc = CorpusDocument(id=upload_id, text=document_content)

    def iter_documents(self) -> Iterable[CorpusDocument]:
        return iter([self._doc])

    def get_document(self, doc_id: str) -> CorpusDocument | None:
        return self._doc if doc_id == self._doc.id else None

    def list_evaluation_queries(self) -> list:
        return []

    @cached_property
    def version_hash(self) -> str:
        return compute_version_hash([self._doc])
