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

from mcp_servers.rag_pill.providers.batched_embed import (
    batched_embed,
    clear_embed_cache,
)


@pytest.fixture(autouse=True)
def _isolate_embed_cache():
    """The module-level memoize cache (added 2026-05-13) persists between
    tests. Without isolation, a cache hit in test N skips a scripted
    response in test N+1 and breaks call-count assertions."""
    clear_embed_cache()
    yield
    clear_embed_cache()


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


# --- per-input memoize cache (2026-05-13) ---------------------------------
#
# Motivation: a 1000-chunk doc with one bad batch sends the outer
# execute_with_embedding_retry into a full rebuild. Without per-input
# memoization, every outer retry re-embeds the 999 chunks we already had
# good vectors for — geometric cost amplification that hit production as
# "Engine X failed: No embedding data received" on a 428KB upload.


def test_second_call_with_same_inputs_skips_upstream_entirely() -> None:
    """Successful vectors persist across batched_embed calls. A second
    call with identical inputs makes zero upstream embeddings.create
    calls — the cache hit path returns directly."""
    inputs = [f"chunk-{i}" for i in range(8)]
    client = _StubClient([
        _EmbedResp(data=[_ok_item() for _ in range(8)]),
        # no second response scripted — second call must not reach upstream
    ])

    out1 = batched_embed(client, model="m", inputs=inputs, batch_size=8)
    assert client.calls == [inputs]
    assert out1.shape == (8, 4)

    out2 = batched_embed(client, model="m", inputs=inputs, batch_size=8)
    assert client.calls == [inputs]  # unchanged — second call hit cache
    assert out2.shape == (8, 4)


def test_partial_cache_only_re_embeds_missing_inputs() -> None:
    """The load-bearing path: outer retry rebuilds after one bad batch.
    First call cached the first batch; second call (with the same first
    batch + a new second batch) re-embeds ONLY the second batch."""
    first = [f"a-{i}" for i in range(4)]
    client1 = _StubClient([_EmbedResp(data=[_ok_item() for _ in range(4)])])
    batched_embed(client1, model="m", inputs=first, batch_size=4)
    assert client1.calls == [first]

    # Second call: first 4 inputs are cached, plus 4 new ones.
    second = first + [f"b-{i}" for i in range(4)]
    client2 = _StubClient([_EmbedResp(data=[_ok_item() for _ in range(4)])])
    out = batched_embed(client2, model="m", inputs=second, batch_size=4)

    # Only the new batch was sent upstream.
    assert client2.calls == [[f"b-{i}" for i in range(4)]]
    assert out.shape == (8, 4)


def test_cache_does_not_cross_models() -> None:
    """Same input text under a different model name is a cache miss —
    embeddings from openai/text-embedding-3-small must not be served for
    openai/text-embedding-3-large queries."""
    inputs = ["chunk"]
    client_small = _StubClient([_EmbedResp(data=[_ok_item()])])
    batched_embed(client_small, model="small", inputs=inputs, batch_size=1)

    client_large = _StubClient([_EmbedResp(data=[_ok_item()])])
    out = batched_embed(client_large, model="large", inputs=inputs, batch_size=1)
    assert client_large.calls == [["chunk"]]
    assert out.shape == (1, 4)


def test_cache_reassembles_partial_batch_in_original_order() -> None:
    """Within a single batch, a mix of cached + uncached inputs must
    reassemble in the original input order — not cached-first then
    fresh-last. Critical for downstream retrieval (chunks index into
    the source doc by position)."""
    # Seed cache with one specific input.
    cached_only = ["seed"]
    client0 = _StubClient([
        _EmbedResp(data=[type("E", (), {"embedding": [9.0, 9.0, 9.0, 9.0]})()])
    ])
    batched_embed(client0, model="m", inputs=cached_only, batch_size=1)

    # Mixed batch: positions 0 and 2 are uncached, position 1 is the cached
    # "seed" entry. The reassembled output must put the seed vector at idx 1.
    mixed = ["new-0", "seed", "new-2"]
    fresh_vecs = [
        type("E", (), {"embedding": [1.0, 1.0, 1.0, 1.0]})(),
        type("E", (), {"embedding": [2.0, 2.0, 2.0, 2.0]})(),
    ]
    client1 = _StubClient([_EmbedResp(data=fresh_vecs)])
    out = batched_embed(client1, model="m", inputs=mixed, batch_size=3)

    # Upstream only saw the two missing inputs.
    assert client1.calls == [["new-0", "new-2"]]
    # And the seed vector landed at index 1, not appended at the end.
    assert out[0].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert out[1].tolist() == [9.0, 9.0, 9.0, 9.0]
    assert out[2].tolist() == [2.0, 2.0, 2.0, 2.0]
