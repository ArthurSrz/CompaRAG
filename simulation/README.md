# Simulation kit — automated users for the tool arena

Everything needed to simulate users against the CompaRAG arena, especially
the `knowledge_capture` interview loop.

| File | What it is |
|---|---|
| `api_paths.yaml` | Every API path the frontend uses — request/response shapes, error codes, ordering rules, the blind invariant |
| `strategies/grill_strategy.md` | Interviewer A's brain (frontier-round grilling) — copy of `mcp_servers/interview_pill/prompts/` |
| `strategies/gsd_discuss_strategy.md` | Interviewer B's brain (adaptive gray-area discussion) — same source |
| `simulate_user.py` | Runnable simulator: start → replies → finish → finalize → vote → reveal |

## Quick start

```bash
# One simulated user against production, default sourdough persona,
# 3 answers per arm, random vote (needs OPENROUTER_API_KEY for the persona):
uv run python simulation/simulate_user.py

# Canned answers (no LLM, no key), 5 users, local backend:
uv run python simulation/simulate_user.py \
  --base-url http://localhost:8001 \
  --answers-file my_answers.txt --sessions 5 --out runs.jsonl

# Custom persona:
uv run python simulation/simulate_user.py \
  --persona "Cheffe pâtissière, 15 ans, spécialiste macarons" \
  --task "La réussite des macarons" --goal "Capturer ce que je sais d'implicite" \
  --turns 4 --vote auto
```

## Rules the simulator must respect (equifinality invariants)

- **Same expert both arms**: the same persona answers both interviewers in a
  session (Expert is invariant) — but with **separate conversation histories**,
  because each Interview is independent (nothing from arm a may leak to arm b).
- **Serialize per arm**: never send two `/reply` calls to the *same* arm
  concurrently; different arms may proceed in parallel.
- **The protocol is backend-owned**: at `max_turns` answers or past
  `deadline_ts`, the next reply returns the artifact whether you like it or not.
- Vote reveals in the same call — `GET /reveal` is only a re-read afterwards.

## Strategy prompts

The `strategies/` copies tell your simulator what kind of questions each arm
will ask (grill: several numbered `❓ Qn` + `➡️` hypotheses per turn;
gsd_discuss: one question with lettered options). Source of truth stays
`mcp_servers/interview_pill/prompts/` — re-copy after editing there:

```bash
cp mcp_servers/interview_pill/prompts/*.md simulation/strategies/
```

Note: strategy names never appear in arena responses before the reveal
(BlindProtocol); a simulator must not rely on identifying the arm's strategy
from its text — though the *shape* of the questions is fair game.
