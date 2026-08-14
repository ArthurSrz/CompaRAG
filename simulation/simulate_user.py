"""Simulate one user session through the knowledge-capture arena.

Drives the full loop against any deployment:
    start -> N replies per arm (persona-driven or canned) -> finish -> finalize
    -> vote -> reveal

Expert answers come from either:
  - an LLM persona via OpenRouter (--persona "…", needs OPENROUTER_API_KEY), or
  - canned answers (--answers-file answers.txt, one answer per line, reused
    round-robin), or
  - a built-in default persona (sourdough baker) if neither is given.

Usage:
    python simulation/simulate_user.py                       # prod, default persona
    python simulation/simulate_user.py --base-url http://localhost:8001 \
        --task "V60 coffee at home" --goal "Capture what no recipe says" \
        --turns 3 --vote a
    python simulation/simulate_user.py --persona "Expert plombier chauffagiste, 20 ans de métier" \
        --task "Diagnostic de chaudières" --turns 5 --vote auto

Only stdlib + httpx (already a repo dependency): `uv run python simulation/simulate_user.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import httpx

DEFAULT_BASE = "https://comparag-production.up.railway.app"
DEFAULT_TASK = "Sourdough bread baking at home"
DEFAULT_GOAL = "Capture what I know that no recipe says"
DEFAULT_PERSONA = (
    "You are a home sourdough baker with 8 years of practice. You have strong,"
    " specific opinions learned by doing: you judge starter readiness by float"
    " test and smell (green apple = ready, vinegar = missed window), you never"
    " bake dark roasts of knowledge — wait, you only talk sourdough. Answer"
    " interview questions concretely, in 2-4 sentences, with real heuristics,"
    " numbers, failure stories and exceptions. Correct the interviewer's"
    " hypotheses when they are wrong."
)
PERSONA_MODEL = os.getenv("SIMULATION_LLM_ID", "openrouter/anthropic/claude-haiku-4.5")


class Expert:
    """Produces expert answers — LLM persona, canned lines, or both."""

    def __init__(self, persona: str | None, canned: list[str]):
        self.persona = persona
        self.canned = canned
        self.i = 0
        self.history: list[dict] = []

    def answer(self, question: str) -> str:
        if self.canned:
            ans = self.canned[self.i % len(self.canned)]
            self.i += 1
            return ans
        return self._llm_answer(question)

    def _llm_answer(self, question: str) -> str:
        import litellm  # lazy: only needed in persona mode

        self.history.append({"role": "user", "content": question})
        response = litellm.completion(
            model=PERSONA_MODEL,
            messages=[{"role": "system", "content": self.persona}] + self.history,
            temperature=0.7,
            max_tokens=400,
        )
        text = response.choices[0].message.content or "(no answer)"
        self.history.append({"role": "assistant", "content": text})
        return text


def run_session(base: str, task: str, goal: str, turns: int, vote: str,
                expert_a: Expert, expert_b: Expert) -> dict:
    client = httpx.Client(base_url=base, timeout=120)

    print(f"→ start  task={task!r}")
    r = client.post("/tool-arena/interview/start", json={"task": task, "goal": goal})
    if r.status_code == 503:
        sys.exit(f"tool_unavailable: {r.text}")
    r.raise_for_status()
    d = r.json()
    session = d["session_hash"]
    headers = {"X-Session-Hash": session}
    print(f"  session={session}  max_turns={d['max_turns']}")
    arms = {"a": d["arm_a"], "b": d["arm_b"]}

    experts = {"a": expert_a, "b": expert_b}
    for t in range(turns):
        for arm in ("a", "b"):
            state = arms[arm]
            if state["done"] or state.get("error"):
                continue
            question = state.get("question") or ""
            answer = experts[arm].answer(question)
            print(f"→ reply {arm} turn {t+1}: {answer[:70]}…")
            r = client.post("/tool-arena/interview/reply", headers=headers,
                            json={"arm": arm, "answer": answer})
            r.raise_for_status()
            arms[arm] = r.json()["state"]

    for arm in ("a", "b"):
        if not arms[arm]["done"]:
            print(f"→ finish {arm}")
            r = client.post("/tool-arena/interview/finish", headers=headers,
                            json={"arm": arm})
            r.raise_for_status()
            arms[arm] = r.json()["state"]

    print("→ finalize")
    r = client.post("/tool-arena/interview/finalize", headers=headers)
    r.raise_for_status()
    final = r.json()
    for side in ("a", "b"):
        res, err = final[f"result_{side}"], final[f"error_{side}"]
        print(f"  artifact {side}: {'ERROR ' + err if err else str(len(res)) + ' chars'}")

    chosen = vote if vote in ("a", "b", "tie") else random.choice(["a", "b", "tie"])
    print(f"→ vote {chosen}")
    r = client.post("/tool-arena/vote", headers=headers, json={
        "chosen": chosen,
        "preferences": {"vote_goal_rating_a": None, "vote_goal_rating_b": None},
    })
    r.raise_for_status()
    reveal = r.json()
    for side in ("tool_a", "tool_b"):
        info = reveal[side]
        print(f"  reveal {info['pos']}: {info['name']}  ({info['duration_ms']}ms"
              f"{', ERROR' if info['error'] else ''})")
    return {"session": session, "final": final, "reveal": reveal, "chosen": chosen}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--task", default=DEFAULT_TASK)
    p.add_argument("--goal", default=DEFAULT_GOAL)
    p.add_argument("--turns", type=int, default=3, help="expert answers per arm before finish")
    p.add_argument("--vote", default="auto", help="a | b | tie | auto (random)")
    p.add_argument("--persona", default=None, help="LLM persona (needs OPENROUTER_API_KEY)")
    p.add_argument("--answers-file", default=None, help="canned answers, one per line")
    p.add_argument("--sessions", type=int, default=1, help="number of simulated users")
    p.add_argument("--out", default=None, help="append JSONL results to this file")
    args = p.parse_args()

    canned: list[str] = []
    if args.answers_file:
        canned = [l.strip() for l in open(args.answers_file, encoding="utf-8") if l.strip()]
    persona = args.persona or (None if canned else DEFAULT_PERSONA)

    for n in range(args.sessions):
        print(f"===== simulated user {n+1}/{args.sessions} =====")
        # Fresh experts per session — but the SAME persona answers both arms
        # (Expert invariant); separate histories because interviews are independent.
        result = run_session(
            args.base_url, args.task, args.goal, args.turns, args.vote,
            Expert(persona, canned), Expert(persona, canned),
        )
        if args.out:
            with open(args.out, "a", encoding="utf-8") as f:
                f.write(json.dumps({**result, "ts": time.time()}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
