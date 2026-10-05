"""Le paramétrage de l'appel Anthropic doit rester compatible avec le SDK
installé. Incident 2026-10-04 : un rebuild non épinglé a tiré anthropic 1.x,
qui a retiré `temperature` de messages.create() → TypeError sur chaque tour,
les deux intervieweurs hors service. Ce test lie les vrais kwargs à la
signature du SDK installé, sans appel réseau."""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-unused")

from mcp_servers.interview_pill import server  # noqa: E402


def test_messages_create_kwargs_bind_to_installed_sdk(monkeypatch):
    real_create = anthropic.Anthropic(api_key="x").messages.create
    captured: dict = {}

    def fake_create(**kwargs):
        inspect.signature(real_create).bind(**kwargs)  # TypeError if unsupported
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"type": "question", "question": "?"}')],
            usage=SimpleNamespace(),
        )

    monkeypatch.setattr(server._client.messages, "create", fake_create)
    skill = server.SKILLS["grill"]
    system = server._build_system(skill, "t", "g", 1, 10, False)
    messages = server._build_messages([], False)

    server._complete_sync(skill, system, messages)

    # The per-strategy temperature still reaches the API, through extra_body.
    assert captured["extra_body"]["temperature"] == skill.temperature
