"""
InterviewSkill — first-class representation of a knowledge-capture strategy.

Replaces the bare ``STRATEGIES: dict[str, str]`` dict that previously held
raw markdown strings. A skill now owns its display name, prompt, and LLM
parameters so the server never needs to hard-code per-strategy constants.

Usage::

    from mcp_servers.interview_pill.skills import SKILLS

    skill = SKILLS["grill"]   # InterviewSkill(key='grill', ...)
    print(skill.display_name) # "Grill-me Interviewer"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger("interview_pill.skills")

_SKILLS_YAML = Path(__file__).resolve().parent / "skills.yaml"


@dataclass(frozen=True)
class InterviewSkill:
    """One knowledge-capture interview strategy (the variant in the arena).

    Attributes:
        key:          Registry key — matches ``strategy`` in tool_args.
        display_name: Human-readable label shown in the UI.
        instructions: Full text of the strategy prompt file.
        temperature:  LLM sampling temperature.
        max_tokens:   Maximum tokens for a single interview move.
    """

    key: str
    display_name: str
    instructions: str
    temperature: float
    max_tokens: int


def load_skills(
    yaml_path: Path = _SKILLS_YAML,
) -> dict[str, InterviewSkill]:
    """Parse ``skills.yaml`` and load each strategy's prompt file.

    Prompt files are resolved relative to *yaml_path*'s directory so the
    module works both locally and inside the Docker image (WORKDIR /app).

    Raises:
        FileNotFoundError: if the yaml or any prompt_file is missing.
        ValueError: if a required field is absent in the yaml.
    """
    base = yaml_path.parent
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"skills.yaml must be a mapping, got {type(raw)}")

    skills: dict[str, InterviewSkill] = {}
    for key, cfg in raw.items():
        prompt_path = base / cfg["prompt_file"]
        instructions = prompt_path.read_text(encoding="utf-8")
        skills[key] = InterviewSkill(
            key=key,
            display_name=cfg["display_name"],
            instructions=instructions,
            temperature=float(cfg.get("temperature", 0.3)),
            max_tokens=int(cfg.get("max_tokens", 4096)),
        )
        log.info("skill.loaded key=%s display_name=%r", key, cfg["display_name"])

    return skills


# Loaded once at import time — same lifecycle as the server process.
SKILLS: dict[str, InterviewSkill] = load_skills()
