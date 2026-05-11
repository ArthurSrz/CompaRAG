"""EphemeralCorpus — wraps user-uploaded text as a single-doc haystack."""

from __future__ import annotations

import hashlib
from typing import Iterable

from mcp_servers.rag_pill.corpus.base import CorpusDocument


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

    def list_evaluation_queries(self) -> list:
        return []
