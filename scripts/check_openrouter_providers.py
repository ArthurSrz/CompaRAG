#!/usr/bin/env python3
"""
BUT : détecter les modèles OpenRouter servis exclusivement par Cloudflare.

OpenRouter route chaque modèle vers un ou plusieurs fournisseurs. Quand le seul
fournisseur disponible est Cloudflare Workers AI, la sortie est silencieusement
coupée à ~113-143 tokens — peu importe la valeur de `max_tokens` envoyée. Ce
bug a déjà coûté un postmortem complet (cf. knowledge-graph/2026-05-02-...yaml,
cause_mediation_oversummarizes).

Ce script appelle l'endpoint public d'OpenRouter pour chaque modèle utilisé
par CompaRAG et échoue (exit code != 0) si l'un d'eux n'a que Cloudflare
comme fournisseur. À lancer :

  - au boot du backend (warning log non bloquant)
  - dans le cron Railway nocturne pour détecter les dégradations
  - manuellement avant de promouvoir un nouveau modèle

Usage :
    python scripts/check_openrouter_providers.py
    python scripts/check_openrouter_providers.py --verbose
    python scripts/check_openrouter_providers.py --models mistralai/mistral-medium-3.1
"""
from __future__ import annotations

import argparse
import sys

import httpx

# Modèles utilisés par CompaRAG (cf. knowledge-graph/code-ontology.yaml).
# Mettre à jour cette liste quand on ajoute un nouveau RAGTool.
DEFAULT_MODELS_TO_CHECK = [
    "mistralai/mistral-medium-3.1",
    "openai/text-embedding-3-small",
]

CLOUDFLARE_PROVIDER_NAME = "Cloudflare"


class ModelNotEnumerable(Exception):
    """OpenRouter does not expose an /endpoints listing for this model.

    Embedding models (openai/text-embedding-3-small) are passed through
    rather than load-balanced across providers, so the endpoint returns 404.
    Treated as "out of scope for the Cloudflare check" rather than a failure.
    """


def fetch_providers(model_slug: str, timeout: float = 10.0) -> list[str]:
    """Return the list of provider names serving `model_slug` on OpenRouter.

    Raises ModelNotEnumerable when OpenRouter returns 404 — this happens for
    embedding / passthrough models that aren't multi-provider.
    """
    url = f"https://openrouter.ai/api/v1/models/{model_slug}/endpoints"
    response = httpx.get(url, timeout=timeout)
    if response.status_code == 404:
        raise ModelNotEnumerable(model_slug)
    response.raise_for_status()
    data = response.json()
    endpoints = data.get("data", {}).get("endpoints", [])
    return [endpoint.get("provider_name", "") for endpoint in endpoints]


def check_model(model_slug: str, verbose: bool) -> bool:
    """
    Return True if the model has at least one non-Cloudflare provider.
    Print a diagnostic line.
    """
    try:
        providers = fetch_providers(model_slug)
    except ModelNotEnumerable:
        print(
            f"[SKIP]  {model_slug}: OpenRouter does not enumerate providers for "
            f"this model (embedding / passthrough — out of scope for the "
            f"Cloudflare check)"
        )
        return True
    except httpx.HTTPError as exc:
        print(f"[ERROR] {model_slug}: could not reach OpenRouter ({exc})")
        return False

    if not providers:
        print(f"[FAIL]  {model_slug}: no providers listed at all")
        return False

    non_cloudflare = [p for p in providers if p != CLOUDFLARE_PROVIDER_NAME]
    only_cloudflare = providers and not non_cloudflare

    if only_cloudflare:
        print(
            f"[FAIL]  {model_slug}: only Cloudflare serves this model — "
            f"output will be silently capped at ~128 tokens. "
            f"Pick another model or wait for OpenRouter to add providers."
        )
        return False

    if verbose:
        print(f"[OK]    {model_slug}: served by {', '.join(providers)}")
    else:
        print(f"[OK]    {model_slug}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect OpenRouter models served exclusively by Cloudflare.",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=DEFAULT_MODELS_TO_CHECK,
        help="Model slugs to check. Defaults to the CompaRAG-in-use list.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the full provider list for each model.",
    )
    args = parser.parse_args()

    all_ok = True
    for model in args.models:
        all_ok &= check_model(model, args.verbose)

    if not all_ok:
        print(
            "\nAt least one model is at risk of silent truncation. "
            "See knowledge-graph/code-ontology.yaml#openrouter_provider for context."
        )
        return 1

    print("\nAll models have at least one non-Cloudflare provider.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
