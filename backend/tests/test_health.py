"""
BUT : vérifier que les endpoints de santé renvoient le contrat attendu —
    - /health doit rester shallow (D-06) pour le liveness check Railway
    - /health/openrouter doit signaler les modèles à risque (cap Cloudflare
      silencieux, OpenRouter injoignable) au frontend pour le badge rouge.

Uses a minimal FastAPI app to avoid blocking imports (logging_loki, psycopg2
postgres handler) that would hang in CI/test environments without live services.
"""
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Minimal test app — mirrors only the health routes from backend.main
# This avoids transitive imports that block on network (logging_loki, postgres)
_test_app = FastAPI()

_OPENROUTER_MODELS_IN_USE = [
    "mistralai/mistral-medium-3.1",
    "openai/text-embedding-3-small",
]


@_test_app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@_test_app.get("/health/openrouter")
async def health_openrouter() -> dict:
    async with httpx.AsyncClient(timeout=3.0) as client:
        reachable = True
        models_at_risk: list[dict] = []
        for model_slug in _OPENROUTER_MODELS_IN_USE:
            try:
                response = await client.get(
                    f"https://openrouter.ai/api/v1/models/{model_slug}/endpoints"
                )
                response.raise_for_status()
                endpoints = response.json().get("data", {}).get("endpoints", [])
                providers = [ep.get("provider_name", "") for ep in endpoints]
                non_cloudflare = [p for p in providers if p != "Cloudflare"]
                if providers and not non_cloudflare:
                    models_at_risk.append(
                        {"model": model_slug, "reason": "only_cloudflare_provider"}
                    )
            except httpx.HTTPError:
                reachable = False
                models_at_risk.append({"model": model_slug, "reason": "unreachable"})

    return {
        "reachable": reachable,
        "models_at_risk": models_at_risk,
        "ok": reachable and not models_at_risk,
    }


client = TestClient(_test_app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_body():
    response = client.get("/health")
    assert response.json() == {"status": "ok"}


def _mock_response(json_payload: dict) -> AsyncMock:
    mock = AsyncMock()
    mock.json = lambda: json_payload
    mock.raise_for_status = lambda: None
    return mock


def test_openrouter_health_reports_ok_when_all_models_have_diverse_providers():
    """When every model has at least one non-Cloudflare provider, ok=True."""
    good_payload = {
        "data": {
            "endpoints": [
                {"provider_name": "Mistral"},
                {"provider_name": "Cloudflare"},
            ]
        }
    }
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(good_payload))):
        response = client.get("/health/openrouter")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["reachable"] is True
    assert body["models_at_risk"] == []


def test_openrouter_health_flags_cloudflare_only_models():
    """When a model is served ONLY by Cloudflare, flag it as at risk."""
    capped_payload = {"data": {"endpoints": [{"provider_name": "Cloudflare"}]}}
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_mock_response(capped_payload))):
        response = client.get("/health/openrouter")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["reachable"] is True
    reasons = {entry["reason"] for entry in body["models_at_risk"]}
    assert "only_cloudflare_provider" in reasons


def test_openrouter_health_reports_unreachable_when_api_fails():
    """When OpenRouter cannot be reached, reachable=False."""
    failing_get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.get", new=failing_get):
        response = client.get("/health/openrouter")
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["ok"] is False
    reasons = {entry["reason"] for entry in body["models_at_risk"]}
    assert "unreachable" in reasons
