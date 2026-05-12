"""batched_embed — fan a long input list over the OpenAI embeddings API
in small groups, retrying each batch on empty/None responses.

OpenRouter occasionally returns 200 OK with empty ``data`` arrays for big
embedding batches. The legacy retry guard (retry.execute_with_embedding_retry)
restarts the entire ``engine.execute()`` on failure — meaning a single bad
batch wastes the work already done on the good batches and gets the same
"all-at-once" payload on retry, so the same flake re-fires.

batched_embed flips the retry boundary: split inputs into groups of N,
retry *per group* with backoff, and concatenate. A bad group costs one
group's worth of work, not the whole indexing call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from mcp_servers.rag_pill.providers.batched_embed import batched_embed


@dataclass
class _EmbedResp:
    data: list[Any]


def _ok_item(dim: int = 4):
    return type("E", (), {"embedding": [0.1] * dim})()


def _empty_data_resp():
    return _EmbedResp(data=[])


class _StubClient:
    """Records calls; replays a scripted response per call."""

    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = list(scripted)
        self.calls: list[list[str]] = []

    @property
    def embeddings(self):
        return self

    def create(self, *, model: str, input: list[str], **kwargs):
        self.calls.append(list(input))
        nxt = self._scripted.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def test_splits_inputs_into_batches_of_configured_size() -> None:
    """A 50-input call with batch_size=16 fans out into 4 sub-calls
    (16+16+16+2). Default batching is the load-bearing knob — every other
    test inherits from this."""
    inputs = [f"chunk-{i}" for i in range(50)]
    client = _StubClient([_EmbedResp(data=[_ok_item() for _ in range(n)]) for n in (16, 16, 16, 2)])

    out = batched_embed(client, model="m", inputs=inputs, batch_size=16)

    assert isinstance(out, np.ndarray)
    assert out.shape == (50, 4)
    assert [len(c) for c in client.calls] == [16, 16, 16, 2]


def test_recovers_when_a_single_batch_returns_empty_data() -> None:
    """The production failure mode: 200 OK with empty data on one batch.
    batched_embed must retry that batch, NOT the whole input list, and
    succeed without re-embedding the good batches."""
    inputs = [f"chunk-{i}" for i in range(20)]
    client = _StubClient([
        _EmbedResp(data=[_ok_item() for _ in range(16)]),  # first batch OK
        _empty_data_resp(),                                # second batch empty (flake)
        _EmbedResp(data=[_ok_item() for _ in range(4)]),   # retry of second batch OK
    ])

    out = batched_embed(client, model="m", inputs=inputs, batch_size=16, max_retries_per_batch=1)
    assert out.shape == (20, 4)
    # First batch was NOT re-sent.
    assert [len(c) for c in client.calls] == [16, 4, 4]


def test_raises_after_max_retries_per_batch_exhausted() -> None:
    """If a single batch keeps returning empty data past the retry budget,
    surface the canonical retry marker so the outer guard / dispatcher can
    classify the failure consistently with the existing flow."""
    inputs = ["a", "b", "c"]
    client = _StubClient([_empty_data_resp(), _empty_data_resp()])

    with pytest.raises(ValueError, match="No embedding data received"):
        batched_embed(client, model="m", inputs=inputs, batch_size=16, max_retries_per_batch=1)


def test_treats_none_valued_embeddings_as_empty_data() -> None:
    """OpenRouter's other degraded shape: 200 OK with data populated but
    embedding=None inside each item. Same root cause; must retry too."""
    inputs = ["a", "b"]

    class _NoneItem:
        embedding = None

    client = _StubClient([
        _EmbedResp(data=[_NoneItem(), _NoneItem()]),
        _EmbedResp(data=[_ok_item(), _ok_item()]),
    ])

    out = batched_embed(client, model="m", inputs=inputs, batch_size=16, max_retries_per_batch=1)
    assert out.shape == (2, 4)
