"""Tests for OAuth state sharing via MCPServerConfig.auth_key.

Two registry entries that point at the same upstream OAuth client (e.g. one
Clarifeye registration exposed as both a summary and a qa contestant) must
share token storage, the OAuth provider cache, and the refresh lock — otherwise
each entry refreshes independently and the upstream's refresh_token rotation
invalidates the other entry's stored copy.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import backend.tool_arena.auth as auth_module
from backend.tool_arena.auth import (
    FileTokenStorage,
    _get_storage,
    build_oauth_provider,
    get_oauth_provider,
    seed_tokens,
)
from backend.tool_arena.config import MCPServerConfig, OAuth2Auth


pytestmark = pytest.mark.anyio


def _make_server(server_id: str, auth_key: str | None = None) -> MCPServerConfig:
    return MCPServerConfig(
        id=server_id,
        name=server_id,
        description="t",
        endpoint="https://upstream.example.com/mcp",
        transport="streamablehttp",
        auth_key=auth_key,
        auth=OAuth2Auth(
            type="oauth2",
            client_id="cid",
            client_secret_env="TEST_AUTH_KEY_SECRET",
            token_url="https://upstream.example.com/o/token/",
        ),
    )


@pytest.fixture(autouse=True)
def _isolate_token_dir(monkeypatch, tmp_path):
    """Point file token storage at tmp_path so the test does not touch the
    real .oauth_tokens directory."""
    monkeypatch.setattr(auth_module, "TOKENS_DIR", tmp_path)
    auth_module._clear_token_cache()
    yield
    auth_module._clear_token_cache()


def test_auth_id_defaults_to_server_id():
    s = _make_server("solo_srv")
    assert s.auth_id == "solo_srv"


def test_auth_id_uses_auth_key_when_set():
    s = _make_server("summary_xyz", auth_key="xyz")
    assert s.auth_id == "xyz"


def test_storage_dirs_are_shared_across_co_tenants(tmp_path, monkeypatch):
    """summary_xyz and qa_xyz, both with auth_key='xyz', must use the same
    on-disk storage directory."""
    monkeypatch.setattr(auth_module, "TOKENS_DIR", tmp_path)

    s_sum = _make_server("summary_xyz", auth_key="xyz")
    s_qa = _make_server("qa_xyz", auth_key="xyz")

    storage_sum = _get_storage(s_sum.auth_id)
    storage_qa = _get_storage(s_qa.auth_id)

    # FileTokenStorage in this dev path; both must point at TOKENS_DIR/xyz.
    assert isinstance(storage_sum, FileTokenStorage)
    assert isinstance(storage_qa, FileTokenStorage)
    assert storage_sum._dir == tmp_path / "xyz"
    assert storage_qa._dir == tmp_path / "xyz"
    # And NOT at TOKENS_DIR/summary_xyz or TOKENS_DIR/qa_xyz.
    assert not (tmp_path / "summary_xyz").exists() or not list((tmp_path / "summary_xyz").iterdir())


def test_provider_cache_is_shared_across_co_tenants(monkeypatch):
    """get_oauth_provider must return the same provider instance for two
    server entries that share an auth_key."""
    monkeypatch.setenv("TEST_AUTH_KEY_SECRET", "secret-value")

    s_sum = _make_server("summary_xyz", auth_key="xyz")
    s_qa = _make_server("qa_xyz", auth_key="xyz")

    p_sum = get_oauth_provider(s_sum)
    p_qa = get_oauth_provider(s_qa)

    assert p_sum is p_qa, "co-tenant entries must share one OAuthProvider"


def test_provider_cache_is_separate_when_auth_keys_differ(monkeypatch):
    """Two entries without a shared auth_key get two distinct providers
    (regression guard against keying the cache too coarsely)."""
    monkeypatch.setenv("TEST_AUTH_KEY_SECRET", "secret-value")

    s_a = _make_server("alpha")  # auth_id == "alpha"
    s_b = _make_server("beta")  # auth_id == "beta"

    p_a = get_oauth_provider(s_a)
    p_b = get_oauth_provider(s_b)

    assert p_a is not p_b


async def test_seed_tokens_writes_to_auth_id_storage(tmp_path, monkeypatch):
    """Seeding via one server-id makes tokens visible to its co-tenant."""
    monkeypatch.setattr(auth_module, "TOKENS_DIR", tmp_path)

    s_sum = _make_server("summary_xyz", auth_key="xyz")
    s_qa = _make_server("qa_xyz", auth_key="xyz")

    await seed_tokens(s_sum, refresh_token="rt-shared")

    qa_storage = _get_storage(s_qa.auth_id)
    tokens = await qa_storage.get_tokens()
    assert tokens is not None
    assert tokens.refresh_token == "rt-shared"


def test_build_oauth_provider_writes_client_info_under_auth_id(
    tmp_path, monkeypatch
):
    """The on-disk client_info.json is written under the auth_id directory,
    not the per-server-id directory, so co-tenant entries see it."""
    monkeypatch.setattr(auth_module, "TOKENS_DIR", tmp_path)
    monkeypatch.setenv("TEST_AUTH_KEY_SECRET", "secret-value")

    s_sum = _make_server("summary_xyz", auth_key="xyz")
    build_oauth_provider(s_sum)

    assert (tmp_path / "xyz" / "client_info.json").exists()
    assert not (tmp_path / "summary_xyz" / "client_info.json").exists()
