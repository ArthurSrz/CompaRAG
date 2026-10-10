"""HTTPColPaliBackend — hosted inference instead of local weights.

A stubbed transport stands in for the endpoint, so everything the adapter
owns is covered: batching, auth-free request shape, response coercion, and
the failure modes. What is NOT covered is the endpoint's actual response
encoding — that needs one real call, and `_as_multivector` is written to
fail loudly rather than guess.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_servers.rag_pill.engines.colpali_backend import HTTPColPaliBackend

VECTOR = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]  # (2 tokens, 3 dims)


def _backend(responder, **kwargs) -> HTTPColPaliBackend:
    return HTTPColPaliBackend(
        endpoint_url="https://example.invalid/colpali",
        token="t",
        transport=responder,
        **kwargs,
    )


def test_pages_are_sent_in_batches_and_come_back_in_order() -> None:
    calls: list[dict] = []

    def responder(body):
        calls.append(body)
        return [VECTOR] * len(body["inputs"])

    backend = _backend(responder, batch_size=2)
    out = backend.embed_pages([b"a", b"b", b"c"])

    assert len(out) == 3
    assert [len(c["inputs"]) for c in calls] == [2, 1], "batch_size not honoured"
    assert all(v.shape == (2, 3) for v in out)


def test_images_are_base64_encoded() -> None:
    import base64

    captured = {}

    def responder(body):
        captured.update(body)
        return [VECTOR]

    _backend(responder).embed_pages([b"\x89PNG-raw-bytes"])
    assert captured["inputs"] == [base64.b64encode(b"\x89PNG-raw-bytes").decode()]


def test_query_and_pages_are_tagged_as_different_tasks() -> None:
    """ColPali encodes a query and a page differently; the endpoint has to be
    told which one it is receiving."""
    seen: list[str] = []

    def responder(body):
        seen.append(body["parameters"]["task"])
        return [VECTOR]

    backend = _backend(responder)
    backend.embed_pages([b"a"])
    backend.embed_query("marmottes")
    assert seen == ["image", "query"]


@pytest.mark.parametrize(
    "payload",
    [
        VECTOR,                      # bare 2-D list
        {"embedding": VECTOR},       # wrapped, singular
        {"embeddings": VECTOR},      # wrapped, plural
        [VECTOR],                    # batch axis kept
    ],
)
def test_accepts_the_plausible_response_encodings(payload) -> None:
    out = _backend(lambda body: payload).embed_query("q")
    np.testing.assert_allclose(out, np.array(VECTOR, dtype=np.float32))


def test_a_pooled_single_vector_is_rejected_loudly() -> None:
    """The dangerous failure: an endpoint that mean-pools returns one vector
    per page. It would rank *something*, just not by late interaction. Refuse
    it rather than quietly degrade the paradigm under test."""
    with pytest.raises(ValueError, match="late-interaction signal is gone"):
        _backend(lambda body: [0.1, 0.2, 0.3]).embed_query("q")


def test_unexpected_dict_shape_names_its_keys() -> None:
    with pytest.raises(ValueError, match="no 'embedding'/'embeddings' key"):
        _backend(lambda body: {"data": VECTOR}).embed_query("q")


def test_page_count_mismatch_is_caught() -> None:
    with pytest.raises(ValueError, match="expected 2 page embeddings"):
        _backend(lambda body: [VECTOR]).embed_pages([b"a", b"b"])


def test_endpoint_url_is_required() -> None:
    with pytest.raises(ValueError, match="endpoint_url is required"):
        HTTPColPaliBackend(endpoint_url="", token="t")
