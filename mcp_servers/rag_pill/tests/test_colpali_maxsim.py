"""MaxSim — the late-interaction scorer, in isolation.

Pure arithmetic, no model: a query token takes the best-matching page patch
and the maxima are summed. These tests encode the behaviour that makes
late interaction different from a single-vector cosine — a page can win on
one sharply-matching patch even when the rest of the page is irrelevant.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_servers.rag_pill.engines.colpali_backend import maxsim


def test_single_token_takes_the_best_patch() -> None:
    query = np.array([[1.0, 0.0]])
    page = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]])
    assert maxsim(query, page) == pytest.approx(1.0)


def test_scores_sum_over_query_tokens() -> None:
    query = np.array([[1.0, 0.0], [0.0, 1.0]])
    page = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert maxsim(query, page) == pytest.approx(2.0)


def test_one_sharp_patch_beats_a_uniformly_mediocre_page() -> None:
    """The defining property: late interaction rewards a precise local match.

    `sharp` answers the query on exactly one patch and is noise elsewhere;
    `bland` is moderately related everywhere. A mean-pooled single vector
    would favour `bland`; MaxSim must favour `sharp`.
    """
    query = np.array([[1.0, 0.0]])
    sharp = np.array([[1.0, 0.0], [0.0, -1.0], [0.0, -1.0]])
    bland = np.array([[0.6, 0.8], [0.6, 0.8], [0.6, 0.8]])
    assert maxsim(query, sharp) > maxsim(query, bland)


def test_empty_side_scores_zero_rather_than_raising() -> None:
    query = np.array([[1.0, 0.0]])
    assert maxsim(query, np.empty((0, 2))) == 0.0
    assert maxsim(np.empty((0, 2)), query) == 0.0


def test_dimension_mismatch_is_loud() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        maxsim(np.array([[1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]))


def test_rejects_non_2d_input() -> None:
    with pytest.raises(ValueError, match="2-D"):
        maxsim(np.array([1.0, 0.0]), np.array([[1.0, 0.0]]))
