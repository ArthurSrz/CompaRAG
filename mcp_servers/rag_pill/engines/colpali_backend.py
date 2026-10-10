"""
BUT : isoler le modèle ColPali derrière un Protocol, pour que le moteur soit
testable sans télécharger un VLM de plusieurs giga-octets.

ColPali embedding backends + the MaxSim late-interaction scorer.

ColPali's paradigm shift is in two places and this module holds both:

1. **What gets embedded.** Not a text chunk — a page *image*, encoded by a
   vision-language model. Nothing is parsed, chunked or OCR'd first, so
   tables, figures, columns and scanned pages survive indexing intact.

2. **How similarity is computed.** Not one vector per chunk against one
   vector per query. ColPali keeps *every* patch embedding of the page and
   *every* token embedding of the query, then scores by MaxSim: each query
   token picks its single best-matching page patch, and those maxima are
   summed. A page wins because it answers the query term by term, not
   because its average meaning is vaguely close.

NOTE on the import: the pip package is `colpali-engine`, imported as
`colpali_engine`. That is a third-party top-level package and is unrelated
to this file's sibling module `colpali_engine.py` inside this subpackage —
absolute imports resolve to site-packages, never to a sibling.
"""

from __future__ import annotations

import io
from typing import Protocol, Sequence, runtime_checkable

import numpy as np


def maxsim(query_embedding: np.ndarray, page_embedding: np.ndarray) -> float:
    """Late-interaction score between a query and a page.

    `query_embedding` is (n_query_tokens, dim), `page_embedding` is
    (n_page_patches, dim). Every query token is matched against its single
    best page patch; the score is the sum of those maxima.

    Model outputs are L2-normalized, so the dot product is cosine similarity.
    Returns 0.0 for an empty side rather than raising: a blank page is a
    legitimate corpus member and must simply rank last.
    """
    if query_embedding.size == 0 or page_embedding.size == 0:
        return 0.0
    if query_embedding.ndim != 2 or page_embedding.ndim != 2:
        raise ValueError(
            "maxsim expects 2-D (tokens, dim) arrays, got "
            f"{query_embedding.shape} and {page_embedding.shape}"
        )
    if query_embedding.shape[1] != page_embedding.shape[1]:
        raise ValueError(
            "embedding dimension mismatch: "
            f"{query_embedding.shape[1]} vs {page_embedding.shape[1]}"
        )
    similarities = query_embedding @ page_embedding.T
    return float(similarities.max(axis=1).sum())


@runtime_checkable
class ColPaliBackend(Protocol):
    """The visual encoder, behind an interface the tests can fake.

    Both methods return (tokens, dim) float arrays — plural vectors per
    item, which is what makes late interaction possible.
    """

    model_id: str

    def embed_pages(self, images: Sequence[bytes]) -> list[np.ndarray]: ...

    def embed_query(self, query: str) -> np.ndarray: ...


class TransformersColPaliBackend:
    """Production backend — a ColPali-family VLM loaded via `colpali-engine`.

    Default model is `vidore/colSmol-256M`: the 256M-parameter member of the
    family, built for CPU inference. The headline `vidore/colpali-v1.3` is
    ~3B and wants a GPU — switch via COLPALI_MODEL_ID when one is available.

    Loading is lazy and idempotent so that constructing the engine at server
    startup costs nothing until the first visual query arrives.
    """

    # Maps a model id to its (model class, processor class) in colpali_engine.
    # The family shares an API but not a class: the ColSmol models are
    # Idefics3-based, colpali-v1.x is PaliGemma-based.
    _CLASSES: dict[str, tuple[str, str]] = {
        "idefics3": ("ColIdefics3", "ColIdefics3Processor"),
        "paligemma": ("ColPali", "ColPaliProcessor"),
        "qwen2": ("ColQwen2", "ColQwen2Processor"),
    }

    def __init__(
        self,
        model_id: str = "vidore/colSmol-256M",
        architecture: str = "idefics3",
        device: str | None = None,
        batch_size: int = 4,
    ) -> None:
        self.model_id = model_id
        self._architecture = architecture
        self._device = device
        self._batch_size = batch_size
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415
        from colpali_engine import models as colpali_models  # noqa: PLC0415

        try:
            model_cls_name, processor_cls_name = self._CLASSES[self._architecture]
        except KeyError as exc:
            raise ValueError(
                f"unknown ColPali architecture {self._architecture!r}; "
                f"expected one of {sorted(self._CLASSES)}"
            ) from exc

        model_cls = getattr(colpali_models, model_cls_name)
        processor_cls = getattr(colpali_models, processor_cls_name)

        device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        self._model = model_cls.from_pretrained(
            self.model_id, torch_dtype=dtype, device_map=device
        ).eval()
        self._processor = processor_cls.from_pretrained(self.model_id)
        self._torch = torch

    def _to_numpy(self, tensor) -> list[np.ndarray]:
        return [row.to("cpu").float().numpy() for row in tensor]

    def embed_pages(self, images: Sequence[bytes]) -> list[np.ndarray]:
        self._load()
        from PIL import Image  # noqa: PLC0415

        pil_images = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in images]
        out: list[np.ndarray] = []
        for start in range(0, len(pil_images), self._batch_size):
            batch = pil_images[start : start + self._batch_size]
            processed = self._processor.process_images(batch).to(self._model.device)
            with self._torch.no_grad():
                out.extend(self._to_numpy(self._model(**processed)))
        return out

    def embed_query(self, query: str) -> np.ndarray:
        self._load()
        processed = self._processor.process_queries([query]).to(self._model.device)
        with self._torch.no_grad():
            return self._to_numpy(self._model(**processed))[0]


class HTTPColPaliBackend:
    """Calls a hosted ColPali endpoint instead of loading the weights locally.

    Trades a 2.5 GB image and a cold-start model load for a network hop. The
    engine cannot tell the difference: both backends satisfy the same
    Protocol and return the same (tokens, dim) arrays.

    `transport` is the seam for tests — a callable taking the JSON-ready
    request body and returning the decoded JSON response. The default posts
    to `endpoint_url` with a bearer token.

    Default model is `vidore/colpali-v1.3-hf` rather than the local backend's
    colSmol: it is the only ColPali carrying Hugging Face's
    `endpoints_compatible` tag *and* standalone weights. colSmol-256M ships
    as a LoRA adapter (39 MB) that needs its base model loaded alongside,
    which a stock endpoint will not do.

    UNVERIFIED: the exact response shape of a hosted ColPali endpoint has not
    been confirmed against a live service (see COLPALI.md). `_as_multivector`
    therefore accepts the three plausible encodings and fails loudly rather
    than silently mis-parsing — one real call will settle which one applies.
    """

    def __init__(
        self,
        endpoint_url: str,
        token: str,
        model_id: str = "vidore/colpali-v1.3-hf",
        timeout: int = 60,
        batch_size: int = 4,
        transport=None,
    ) -> None:
        if not endpoint_url:
            raise ValueError("endpoint_url is required")
        self.model_id = model_id
        self._endpoint_url = endpoint_url
        self._token = token
        self._timeout = timeout
        self._batch_size = batch_size
        self._transport = transport or self._post

    def _post(self, body: dict) -> object:
        import json  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        request = urllib.request.Request(
            self._endpoint_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _as_multivector(payload: object, *, context: str) -> np.ndarray:
        """Coerce one item's response into a (tokens, dim) array.

        Accepts a bare 2-D list, or a dict keyed `embedding`/`embeddings`.
        Anything else raises: a wrong guess here would silently corrupt every
        ranking, which is far worse than a failed call.
        """
        if isinstance(payload, dict):
            for key in ("embedding", "embeddings"):
                if key in payload:
                    payload = payload[key]
                    break
            else:
                raise ValueError(
                    f"{context}: response dict has no 'embedding'/'embeddings' key "
                    f"(keys: {sorted(payload)})"
                )
        array = np.asarray(payload, dtype=np.float32)
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]  # endpoint kept the batch axis
        if array.ndim != 2:
            raise ValueError(
                f"{context}: expected a 2-D (tokens, dim) embedding, got shape "
                f"{array.shape}. ColPali is multi-vector — a 1-D response means "
                "the endpoint pooled it and the late-interaction signal is gone."
            )
        return array

    def embed_pages(self, images: Sequence[bytes]) -> list[np.ndarray]:
        import base64  # noqa: PLC0415

        out: list[np.ndarray] = []
        for start in range(0, len(images), self._batch_size):
            batch = images[start : start + self._batch_size]
            response = self._transport(
                {
                    "inputs": [
                        base64.b64encode(raw).decode("ascii") for raw in batch
                    ],
                    "parameters": {"task": "image"},
                }
            )
            if not isinstance(response, list) or len(response) != len(batch):
                raise ValueError(
                    f"expected {len(batch)} page embeddings, got "
                    f"{len(response) if isinstance(response, list) else type(response).__name__}"
                )
            out.extend(
                self._as_multivector(item, context=f"page {start + i}")
                for i, item in enumerate(response)
            )
        return out

    def embed_query(self, query: str) -> np.ndarray:
        response = self._transport(
            {"inputs": [query], "parameters": {"task": "query"}}
        )
        if isinstance(response, list) and len(response) == 1:
            response = response[0]
        return self._as_multivector(response, context="query")
