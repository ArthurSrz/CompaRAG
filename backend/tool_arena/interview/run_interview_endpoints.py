"""
BUT : orchestrer la boucle d'entretien knowledge_capture — le pendant
« capture de connaissances » de run_comparison_endpoint.py, où l'expert
humain remplace le document comme source invariante.

Endpoints :
    POST /tool-arena/interview/start    -> apparie deux outils de capture,
                                           ouvre les deux entretiens
    POST /tool-arena/interview/reply    -> relaie la réponse de l'expert à UN
                                           bras, rend la question suivante
    POST /tool-arena/interview/finish   -> l'expert clôt un bras : artefact forcé
    POST /tool-arena/interview/finalize -> normalise + sanitise les deux
                                           artefacts, persiste, rend la
                                           CompareResponse aveugle — /vote et
                                           /reveal existants prennent le relais

Invariants (ontologie goal_directed_action) :
    - Expert / InterviewProtocol / LLM : constants entre les bras. max_turns
      et deadline sont décidés ICI, jamais par les outils.
    - Interview : variant — chaque appel MCP n'embarque QUE le transcript de
      son bras. Les réponses données au bras A n'atteignent jamais le bras B.
    - BlindProtocol : les questions sont sanitisées avant affichage ; les
      artefacts au finalize ; tool_id ne sort jamais avant /vote.

Persistance : contrairement à /compare (persist au compare), les tool_calls
sont persistés au FINALIZE — il n'existe aucun résultat avant l'artefact.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from backend.tool_arena.answer.wrap_answer_in_standard_envelope import normalize_output
from backend.tool_arena.blind_reveal.hide_tool_identity_before_vote import (
    sanitize_envelope,
    sanitize_output,
)
from backend.tool_arena.blind_reveal.identify_user_session import (
    get_tool_session,
    get_tool_session_hash,
)
from backend.tool_arena.blind_reveal.remember_who_was_which import (
    create_tool_session,
    retrieve_tool_session,
    store_tool_session,
)
# Late-bound module access (not from-imports): test_ask_two_tools_concurrently
# reloads this module to re-read env timeouts, which rebinds its classes.
# Attribute access on the module object always resolves the current class, so
# the except clause below keeps matching after a reload.
from backend.tool_arena.comparison import ask_two_tools_concurrently as dispatch_mod
from backend.tool_arena.comparison.contracts import CompareResponse
from backend.tool_arena.config import MCPServerConfig
from backend.tool_arena.interview.contracts import (
    ArmState,
    InterviewFinishRequest,
    InterviewReplyRequest,
    InterviewReplyResponse,
    InterviewStartRequest,
    InterviewStartResponse,
)
from backend.tool_arena.interview.interview_protocol import (
    INTERVIEW_MAX_TURNS,
    compute_deadline_ts,
    should_force_artifact,
    transcript_to_markdown,
)
from backend.tool_arena.models import MCPToolCall, ToolCallRecord, save_tool_call_to_db
from backend.tool_arena.rag_tool.ask_one_interview_move import single_interview_move
from backend.tool_arena.rag_tool.list_available_tools import registry

logger = logging.getLogger("languia")

interview_router = APIRouter()

# Un move = un seul appel LLM (pas d'indexation) — 60 s suffisent largement.
INTERVIEW_MOVE_TIMEOUT = float(os.environ.get("INTERVIEW_MOVE_TIMEOUT", "60"))

GENERIC_ARM_ERROR = "Tool encountered an error"


def _all_servers() -> list[MCPServerConfig]:
    return [registry.get_server(sid) for sid in registry.server_ids]


def _placeholder_tool(server_id: str, llm_id: str) -> dict:
    """Occupe tool_a/tool_b dès le start pour que /vote avant finalize tombe
    proprement sur son garde-fou 422 existant (au lieu d'un KeyError 500)."""
    return {
        "tool_id": server_id,
        "llm_id": llm_id,
        "error": "interview in progress — not finalized",
        "duration_ms": 0,
    }


@asynccontextmanager
async def _session_lock(session_hash: str, timeout_s: float = 8.0):
    """Verrou best-effort sur la mutation de session (SET NX + expiry).

    Les deux bras avancent en parallèle (Terminer A + Terminer B) : chaque
    requête lit la session, passe des secondes dans l'appel LLM, puis réécrit
    la session ENTIÈRE — last-writer-wins écraserait le done/artifact de
    l'autre bras. L'appel LLM reste HORS verrou ; seul le commit (relecture
    fraîche + mutation + store) est sérialisé. Best-effort : si Redis refuse
    le verrou (indispo, tests), on continue sans — comportement d'avant.
    """
    from utils.storage.redis import get_redis_client

    key = f"tool_arena:lock:{session_hash}"
    client = None
    locked = False
    try:
        client = get_redis_client()
        deadline = time.monotonic() + timeout_s
        while not client.set(key, "1", nx=True, ex=10):
            if time.monotonic() > deadline:
                logger.warning("interview session lock timeout hash=%s", session_hash)
                break
            await asyncio.sleep(0.05)
        else:
            locked = True
    except Exception as exc:
        logger.warning("interview session lock unavailable: %s", exc)
    try:
        yield
    finally:
        if locked and client is not None:
            try:
                client.delete(key)
            except Exception:
                pass


def _arm_state(arm: dict, max_turns: int) -> ArmState:
    if arm.get("error"):
        return ArmState(
            type="error",
            turn=arm["turn"],
            max_turns=max_turns,
            done=True,
            error=GENERIC_ARM_ERROR,
        )
    if arm.get("done"):
        return ArmState(type="artifact", turn=arm["turn"], max_turns=max_turns, done=True)
    question = None
    for entry in reversed(arm["transcript"]):
        if entry["role"] == "interviewer":
            question = entry["content"]
            break
    return ArmState(
        type="question",
        question=question,
        turn=arm["turn"],
        max_turns=max_turns,
        done=False,
    )


async def _play_move(
    server: MCPServerConfig,
    session: dict,
    arm: dict,
    force_artifact: bool,
) -> None:
    """Joue un move pour un bras et met à jour son état en place.

    Toute exception devient une erreur de bras (done=True) — le protocole
    d'erreur est le même que le chemin error_a/error_b de /compare.
    """
    interview = session["interview"]
    try:
        move, duration_ms = await asyncio.wait_for(
            single_interview_move(
                server=server,
                task=session["task"],
                goal=session["goal"],
                transcript=arm["transcript"],
                turn=arm["turn"] + 1,
                max_turns=interview["max_turns"],
                force_artifact=force_artifact,
            ),
            timeout=INTERVIEW_MOVE_TIMEOUT,
        )
    except Exception as exc:
        logger.error(
            "interview move failed server=%s: %s: %s",
            server.id, type(exc).__name__, exc,
        )
        arm["error"] = f"{type(exc).__name__}: {exc}"
        arm["done"] = True
        return

    arm["duration_ms_total"] = arm.get("duration_ms_total", 0) + duration_ms
    if move["type"] == "artifact":
        arm["artifact"] = move["artifact_markdown"]
        arm["artifact_subtype"] = move.get("artifact_subtype")
        arm["done"] = True
    else:
        # BlindProtocol : la question est sanitisée AVANT d'entrer au
        # transcript — c'est elle qui part à l'écran.
        question = sanitize_output(move["question"], _all_servers())
        arm["transcript"].append({"role": "interviewer", "content": question})


@interview_router.post("/interview/start", response_model=None)
async def start_interview(body: InterviewStartRequest):
    """Apparie deux outils knowledge_capture et ouvre les deux entretiens."""
    dispatcher = dispatch_mod.MCPDispatcher()
    try:
        server_a, server_b = await dispatcher.pick_pair(task_type="knowledge_capture")
    except dispatch_mod.InsufficientReadyServersError as exc:
        logger.warning(
            "interview/start: 503 tool_unavailable (ready_count=%d)", exc.ready_count
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "tool_unavailable",
                "message": (
                    "Not enough capture tools are currently available to run "
                    "a comparison. Please try again shortly."
                ),
                "ready_count": exc.ready_count,
            },
        )

    session_hash = create_tool_session()
    session = {
        "session_hash": session_hash,
        "task": body.task,
        "goal": body.goal,
        "task_type": "knowledge_capture",
        "voted": False,
        "llm_id_a": server_a.llm_id or "",
        "llm_id_b": server_b.llm_id or "",
        "tool_a": _placeholder_tool(server_a.id, server_a.llm_id or ""),
        "tool_b": _placeholder_tool(server_b.id, server_b.llm_id or ""),
        "interview": {
            "max_turns": INTERVIEW_MAX_TURNS,
            "deadline_ts": compute_deadline_ts(),
            "server_a_id": server_a.id,
            "server_b_id": server_b.id,
            "finalized": False,
            "arms": {
                "a": {"transcript": [], "turn": 0, "done": False, "artifact": None,
                       "artifact_subtype": None, "error": None, "duration_ms_total": 0},
                "b": {"transcript": [], "turn": 0, "done": False, "artifact": None,
                       "artifact_subtype": None, "error": None, "duration_ms_total": 0},
            },
        },
    }

    arms = session["interview"]["arms"]
    await asyncio.gather(
        _play_move(server_a, session, arms["a"], force_artifact=False),
        _play_move(server_b, session, arms["b"], force_artifact=False),
    )

    store_tool_session(session_hash, session)
    return InterviewStartResponse(
        session_hash=session_hash,
        max_turns=INTERVIEW_MAX_TURNS,
        deadline_ts=session["interview"]["deadline_ts"],
        arm_a=_arm_state(arms["a"], INTERVIEW_MAX_TURNS),
        arm_b=_arm_state(arms["b"], INTERVIEW_MAX_TURNS),
    )


def _get_interview(session: dict) -> dict:
    interview = session.get("interview")
    if not interview:
        raise HTTPException(status_code=404, detail="No interview in this session")
    if session.get("voted"):
        raise HTTPException(status_code=403, detail="Already voted")
    return interview


def _server_for_arm(interview: dict, arm_key: str) -> MCPServerConfig:
    server_id = interview[f"server_{arm_key}_id"]
    return registry.get_server(server_id)


async def _advance_arm(
    session_hash: str,
    session: dict,
    arm_key: str,
    answer: str | None,
    force: bool,
) -> InterviewReplyResponse:
    interview = _get_interview(session)
    arm = interview["arms"][arm_key]
    if arm["done"]:
        raise HTTPException(status_code=409, detail="This interview arm is finished")

    # Phase 1 — calcul sur un instantané, AUCUNE mutation de session : l'appel
    # LLM dure des secondes et l'autre bras avance en parallèle.
    transcript = [dict(e) for e in arm["transcript"]]
    turn = arm["turn"]
    if answer is not None:
        transcript.append({"role": "expert", "content": answer})
        turn += 1

    force_artifact = force or should_force_artifact(
        expert_answers=turn,
        max_turns=interview["max_turns"],
        deadline_ts=interview["deadline_ts"],
    )

    server = _server_for_arm(interview, arm_key)
    outcome: dict
    try:
        move, duration_ms = await asyncio.wait_for(
            single_interview_move(
                server=server,
                task=session["task"],
                goal=session["goal"],
                transcript=transcript,
                turn=turn + 1,  # contrat outil : réponses de l'expert + 1
                max_turns=interview["max_turns"],
                force_artifact=force_artifact,
            ),
            timeout=INTERVIEW_MOVE_TIMEOUT,
        )
        outcome = {"move": move, "duration_ms": duration_ms, "error": None}
    except Exception as exc:
        logger.error(
            "interview move failed server=%s: %s: %s",
            server.id, type(exc).__name__, exc,
        )
        outcome = {"move": None, "duration_ms": 0, "error": f"{type(exc).__name__}: {exc}"}

    # Phase 2 — commit sérialisé sur l'état FRAIS : sans cela, deux commits
    # concurrents (un par bras) s'écrasent mutuellement (last-writer-wins) et
    # both_done ne devient jamais vrai.
    async with _session_lock(session_hash):
        try:
            fresh = retrieve_tool_session(session_hash)
        except ValueError:
            fresh = session
        fresh_interview = fresh.get("interview") or interview
        fresh_arm = fresh_interview["arms"][arm_key]

        fresh_arm["transcript"] = transcript
        fresh_arm["turn"] = turn
        fresh_arm["duration_ms_total"] = (
            fresh_arm.get("duration_ms_total", 0) + outcome["duration_ms"]
        )
        if outcome["error"] is not None:
            fresh_arm["error"] = outcome["error"]
            fresh_arm["done"] = True
        elif outcome["move"]["type"] == "artifact":
            fresh_arm["artifact"] = outcome["move"]["artifact_markdown"]
            fresh_arm["artifact_subtype"] = outcome["move"].get("artifact_subtype")
            fresh_arm["done"] = True
        else:
            # BlindProtocol : la question est sanitisée AVANT d'entrer au
            # transcript — c'est elle qui part à l'écran.
            question = sanitize_output(outcome["move"]["question"], _all_servers())
            fresh_arm["transcript"] = transcript + [
                {"role": "interviewer", "content": question}
            ]
        store_tool_session(session_hash, fresh)

    arms = fresh_interview["arms"]
    return InterviewReplyResponse(
        arm=arm_key,
        state=_arm_state(fresh_arm, fresh_interview["max_turns"]),
        both_done=arms["a"]["done"] and arms["b"]["done"],
    )


@interview_router.post("/interview/reply", response_model=InterviewReplyResponse)
async def reply(
    body: InterviewReplyRequest,
    session_hash: str = Depends(get_tool_session_hash),
    session: dict = Depends(get_tool_session),
):
    """Relaie la réponse de l'expert à UN bras et rend le move suivant."""
    return await _advance_arm(
        session_hash, session, body.arm, answer=body.answer, force=False
    )


@interview_router.post("/interview/finish", response_model=InterviewReplyResponse)
async def finish_arm(
    body: InterviewFinishRequest,
    session_hash: str = Depends(get_tool_session_hash),
    session: dict = Depends(get_tool_session),
):
    """L'expert clôt un bras plus tôt : l'artefact est exigé immédiatement."""
    return await _advance_arm(
        session_hash, session, body.arm, answer=None, force=True
    )


@interview_router.post("/interview/finalize", response_model=CompareResponse)
async def finalize(
    session_hash: str = Depends(get_tool_session_hash),
    session: dict = Depends(get_tool_session),
):
    """Transforme les deux artefacts en résultats aveugles vote-compatibles.

    Miroir exact du pipeline de dispatch() : normalize -> sanitize_envelope ->
    sanitize_output, puis MCPToolCall + persistance. Idempotent — refaire
    l'appel rend la même CompareResponse depuis la session.
    """
    # Relire l'état frais : la session injectée par Depends a pu être lue
    # avant le dernier commit d'un bras (les commits sont sérialisés par
    # _session_lock, pas les lectures des dépendances FastAPI).
    try:
        session = retrieve_tool_session(session_hash)
    except ValueError:
        pass
    interview = session.get("interview")
    if not interview:
        raise HTTPException(status_code=404, detail="No interview in this session")

    if not interview.get("finalized"):
        arms = interview["arms"]
        if not (arms["a"]["done"] and arms["b"]["done"]):
            raise HTTPException(
                status_code=409, detail="Both interview arms must be finished"
            )

        all_servers = _all_servers()
        for arm_key in ("a", "b"):
            arm = arms[arm_key]
            server_id = interview[f"server_{arm_key}_id"]
            llm_id = session.get(f"llm_id_{arm_key}") or ""
            if arm.get("error") or not arm.get("artifact"):
                tool_call = MCPToolCall(
                    session_id=session_hash,
                    task=session["task"],
                    goal=session["goal"],
                    tool_id=server_id,
                    llm_id=llm_id,
                    raw_result="",
                    mediated_result="",
                    duration_ms=arm.get("duration_ms_total", 0),
                    error=arm.get("error") or "no artifact produced",
                )
            else:
                envelope = normalize_output(
                    arm["artifact"], arm.get("duration_ms_total", 0)
                )
                envelope = sanitize_envelope(envelope, all_servers)
                sanitized_artifact = sanitize_output(envelope.answer, all_servers)
                transcript_md = sanitize_output(
                    transcript_to_markdown(arm["transcript"]), all_servers
                )
                tool_call = MCPToolCall(
                    session_id=session_hash,
                    task=session["task"],
                    goal=session["goal"],
                    tool_id=server_id,
                    llm_id=llm_id,
                    raw_result=transcript_md,
                    mediated_result=sanitized_artifact,
                    duration_ms=arm.get("duration_ms_total", 0),
                )
            try:
                record = ToolCallRecord(**tool_call.model_dump(mode="json"))
                save_tool_call_to_db(record.model_dump(mode="json"))
            except Exception as exc:
                logger.error(
                    "Failed to persist interview tool_call %s: %s",
                    tool_call.call_id, exc,
                )
            session[f"tool_{arm_key}"] = tool_call.model_dump(mode="json")

        interview["finalized"] = True
        store_tool_session(session_hash, session)

    tool_a, tool_b = session["tool_a"], session["tool_b"]
    return CompareResponse(
        session_hash=session_hash,
        result_a=tool_a["mediated_result"] if tool_a.get("error") is None else None,
        result_b=tool_b["mediated_result"] if tool_b.get("error") is None else None,
        error_a=GENERIC_ARM_ERROR if tool_a.get("error") is not None else None,
        error_b=GENERIC_ARM_ERROR if tool_b.get("error") is not None else None,
    )
