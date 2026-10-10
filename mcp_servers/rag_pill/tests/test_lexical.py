"""BM25 Okapi and reciprocal rank fusion, in isolation.

The formula is implemented rather than imported (see engines/lexical.py), so
it owes the arena an auditable test: not just "it returns something", but
that each of BM25's three moving parts — IDF, term-frequency saturation,
length normalization — actually moves.
"""

from __future__ import annotations

import pytest

from mcp_servers.rag_pill.engines.lexical import (
    BM25Index,
    reciprocal_rank_fusion,
    tokenize,
)


def test_tokenize_folds_case_and_accents() -> None:
    assert tokenize("Référence ÉLECTRIQUE") == ["reference", "electrique"]


def test_identifiers_are_kept_whole_as_well_as_split() -> None:
    """Regression. Splitting alone reduced "E-330" to the ubiquitous letter
    "e" plus a bare number, and the fault code ranked no better than noise —
    measured on a real maintenance manual, where the query "Que signifie le
    code E-330 ?" returned the spare-parts table. The glued form is what
    makes an identifier searchable at all."""
    assert tokenize("E-330") == ["e330", "330"]
    assert tokenize("PAL-3300-B") == ["pal3300b", "pal", "3300"]


def test_identifier_matches_with_or_without_the_hyphen() -> None:
    """Glueing also absorbs the user who types the reference without it."""
    assert "e330" in tokenize("E-330")
    assert "e330" in tokenize("E330")


def test_near_identical_references_stay_distinguishable() -> None:
    """The case dense retrieval cannot handle: two part numbers differing by
    a single trailing letter. BM25 must separate them."""
    index = BM25Index(
        [
            "Palier avant turbine T3 | PAL-3300-A | 2",
            "Palier arriere turbine T3 | PAL-3300-B | 1",
        ]
    )
    ranked = index.rank("PAL-3300-B", top_k=2)
    assert ranked[0][0] == 1, "the wrong reference ranked first"
    assert ranked[0][1] > ranked[1][1], "the two references scored identically"


def test_single_letters_are_dropped_but_lone_digits_kept() -> None:
    """A stray letter carries no signal and dilutes scoring; a lone figure
    can be the answer."""
    assert tokenize("a b 4 mm") == ["4", "mm"]


def test_plain_hyphenated_words_are_only_split() -> None:
    """No digit means it is prose, not a reference."""
    assert tokenize("ci-dessous") == ["ci", "dessous"]


def test_rare_terms_outweigh_common_ones() -> None:
    """IDF: a term in every document barely discriminates; a rare one does.

    Under Lucene's IDF variant a ubiquitous term keeps a small positive
    weight rather than zero — it stops being evidence without becoming a
    penalty. What matters is the ratio, pinned here at an order of
    magnitude. The threshold is 5x: the measured ratio on this three-document
    corpus is ~7.3x, and it widens as the corpus grows.
    """
    index = BM25Index(
        [
            "le rapport mentionne la turbine",
            "le rapport mentionne la pompe",
            "le rapport mentionne le palier",
        ]
    )
    # "turbine" appears once, "rapport" in all three.
    rare = max(index.score("turbine"))
    common = max(index.score("rapport"))
    assert common > 0
    assert rare > 5 * common, (
        f"rare term scored {rare:.3f} vs ubiquitous {common:.3f} — IDF is flat"
    )


def test_term_frequency_saturates() -> None:
    """k1: the tenth occurrence must add far less than the second."""
    index = BM25Index(["turbine " * 2 + "texte", "turbine " * 10 + "texte", "autre"])
    scores = index.score("turbine")
    twice, ten_times = scores[0], scores[1]
    assert ten_times > twice
    assert ten_times < 5 * twice, "score grew linearly — saturation is not applied"


def test_long_chunks_do_not_win_on_length_alone() -> None:
    """b: two chunks mentioning the term once, the longer must not win."""
    index = BM25Index(["turbine", "turbine " + "remplissage " * 40, "autre sujet"])
    scores = index.score("turbine")
    assert scores[0] > scores[1]


def test_rank_drops_non_matching_documents() -> None:
    index = BM25Index(["la turbine vibre", "le ciel est bleu"])
    ranked = index.rank("turbine", top_k=5)
    assert [i for i, _ in ranked] == [0]


def test_rank_is_deterministic_on_ties() -> None:
    index = BM25Index(["turbine", "turbine"])
    assert [i for i, _ in index.rank("turbine", top_k=2)] == [0, 1]


def test_empty_query_and_empty_index_are_safe() -> None:
    assert BM25Index(["texte"]).score("") == [0.0]
    assert BM25Index([]).rank("turbine", top_k=3) == []


def test_rrf_rewards_agreement_over_one_ranker_s_favourite() -> None:
    """Document 1 is second on both lists; document 0 is first on one and
    absent from the other. Consensus wins — that is the point of RRF."""
    fused = reciprocal_rank_fusion([[0, 1], [2, 1]])
    assert fused[0][0] == 1


def test_rrf_never_reads_scores_only_positions() -> None:
    """Fusion must be identical whatever the underlying scores were, which
    is what makes it safe across incomparable scales."""
    assert reciprocal_rank_fusion([[7, 3]]) == reciprocal_rank_fusion([[7, 3]])
    fused = dict(reciprocal_rank_fusion([[7, 3]]))
    assert fused[7] > fused[3]


def test_rrf_surfaces_a_document_only_one_ranker_found() -> None:
    fused = dict(reciprocal_rank_fusion([[0], [99]]))
    assert set(fused) == {0, 99}


@pytest.mark.parametrize("k", [1, 60, 1000])
def test_rrf_damping_keeps_order_within_a_single_list(k) -> None:
    fused = reciprocal_rank_fusion([[5, 6, 7]], k=k)
    assert [i for i, _ in fused] == [5, 6, 7]
