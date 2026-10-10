"""
BUT : la recherche lexicale — trouver par mots exacts et non par sens.
C'est la référence historique que l'arène n'avait pas, et le seul moyen
de démontrer que les embeddings servent à quelque chose.

BM25 Okapi + reciprocal rank fusion, implemented directly.

Why not a library: BM25 is a published formula (Robertson & Sparck Jones),
not a library's idiosyncrasy. Fifty lines of it, with the parameters named
and testable against hand-computed values, make a better *interpretable
baseline* — the role this engine plays, alongside chroma_baseline — than a
dependency whose quirks become part of the measurement. It also keeps the
shared image free of another package.

What BM25 does differently from a dense retriever: it scores a chunk on the
query's *exact terms*, weighted so that rare terms count more (IDF), extra
repetitions count less (saturation via k1), and long chunks do not win just
by containing more words (length normalization via b). It cannot match a
synonym — and that is the point. On jargon, proper nouns, part numbers and
error codes, the thing a dense retriever smooths away is exactly the thing
being searched for.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Sequence

# Robertson's defaults, and the values nearly every BM25 deployment uses.
# k1 governs term-frequency saturation, b the strength of length
# normalization. Named here rather than inlined so a pill could expose them.
K1 = 1.5
B = 0.75

# Reciprocal rank fusion's damping constant, from Cormack et al. 2009. It
# decides how fast a list's influence decays with rank: at k=60 the gap
# between rank 1 and rank 2 is small, so fusion rewards documents that
# several rankers like rather than one ranker's favourite.
RRF_K = 60

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase, strip accents, split on word characters.

    Accent folding is a deliberate recall trade for French: a corpus written
    with accents must still answer a query typed without them. It costs the
    rare pair that differs only by an accent.
    """
    folded = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return _TOKEN_RE.findall(stripped)


class BM25Index:
    """Okapi BM25 over a fixed list of documents."""

    def __init__(self, documents: Sequence[str], k1: float = K1, b: float = B) -> None:
        self._k1 = k1
        self._b = b
        self._tokenized = [tokenize(d) for d in documents]
        self._lengths = [len(t) for t in self._tokenized]
        self._avg_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        self._frequencies = [Counter(t) for t in self._tokenized]

        document_frequency: Counter[str] = Counter()
        for tokens in self._tokenized:
            document_frequency.update(set(tokens))

        total = len(self._tokenized)
        # Lucene's IDF variant: the +1 inside the log keeps the result
        # strictly positive. Robertson's original formula goes negative once
        # a term appears in more than half the corpus, so a word like "le"
        # would actively push down every chunk containing it. Here such a
        # term merely contributes almost nothing, which is the intent.
        self._idf = {
            term: math.log((total - count + 0.5) / (count + 0.5) + 1.0)
            for term, count in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self._tokenized)

    def score(self, query: str) -> list[float]:
        """Score every document against the query. Index-aligned."""
        query_terms = tokenize(query)
        scores = [0.0] * len(self._tokenized)
        if not query_terms or not self._avg_length:
            return scores

        for index, frequencies in enumerate(self._frequencies):
            length = self._lengths[index]
            normalization = self._k1 * (
                1 - self._b + self._b * length / self._avg_length
            )
            total = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                total += (
                    self._idf.get(term, 0.0)
                    * frequency
                    * (self._k1 + 1)
                    / (frequency + normalization)
                )
            scores[index] = total
        return scores

    def rank(self, query: str, top_k: int) -> list[tuple[int, float]]:
        """Top-k (document index, score), best first, zero-scores dropped."""
        scored = [(i, s) for i, s in enumerate(self.score(query)) if s > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_k]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], k: int = RRF_K
) -> list[tuple[int, float]]:
    """Fuse several ranked lists of document indices into one.

    Each list contributes 1/(k + rank) per document, ranks being 0-based.
    Scores are never compared across rankers — only positions — which is
    what makes this safe to apply to a BM25 score and a cosine similarity,
    two quantities on incomparable scales. Trying to normalize them into
    each other is the usual way hybrid retrieval goes quietly wrong.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, document_index in enumerate(ranking):
            fused[document_index] = fused.get(document_index, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
