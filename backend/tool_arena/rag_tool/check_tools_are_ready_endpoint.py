"""
BUT : tester un RAGTool de bout en bout avec un prompt fixe — vérifie sa
connectivité, la forme de son enveloppe de réponse, et que la sanitization
tourne. Utile pour qualifier un nouvel outil avant de l'ajouter à l'arène.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.tool_arena.answer.wrap_answer_in_standard_envelope import normalize_output
from backend.tool_arena.blind_reveal.hide_tool_identity_before_vote import sanitize_envelope
from backend.tool_arena.comparison.contracts import (
    DryRunCheck,
    DryRunRequest,
    DryRunResponse,
)
from backend.tool_arena.rag_tool.ask_one_tool import single_mcp_call
from backend.tool_arena.rag_tool.list_available_tools import registry

logger = logging.getLogger("languia")

dry_run_router = APIRouter()

_DRY_RUN_TASK = "What is this document about?"
_DRY_RUN_GOAL = "Provide a brief summary"
_DRY_RUN_TIMEOUT = 30  # seconds


@dry_run_router.post("/dry-run", response_model=DryRunResponse)
async def dry_run(body: DryRunRequest) -> DryRunResponse:
    """Validate a registered RAG tool end-to-end with a hardcoded test prompt.

    Runs three checks:
      1. connectivity — real MCP call with 30s timeout
      2. envelope_shape — normalize_output produces non-empty answer
      3. sanitization — sanitize_envelope runs without error (best-effort)
    """
    try:
        server = registry.get_server(body.tool_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Tool '{body.tool_id}' not found in registry"
        )

    checks: list[DryRunCheck] = []
    raw_text: str | None = None
    duration_ms: int = 0

    try:
        raw_text, duration_ms = await asyncio.wait_for(
            single_mcp_call(server, _DRY_RUN_TASK, _DRY_RUN_GOAL),
            timeout=_DRY_RUN_TIMEOUT,
        )
        checks.append(
            DryRunCheck(
                name="connectivity",
                passed=True,
                detail=f"MCP call succeeded in {duration_ms}ms",
            )
        )
    except asyncio.TimeoutError:
        checks.append(
            DryRunCheck(
                name="connectivity",
                passed=False,
                detail=f"MCP call timed out after {_DRY_RUN_TIMEOUT}s",
            )
        )
    except Exception as exc:
        checks.append(DryRunCheck(name="connectivity", passed=False, detail=str(exc)))

    if not checks[0].passed:
        checks.append(DryRunCheck(name="envelope_shape", passed=False, detail="Skipped — connectivity failed"))
        checks.append(DryRunCheck(name="sanitization", passed=False, detail="Skipped — connectivity failed"))
        return DryRunResponse(valid=False, tool_id=body.tool_id, checks=checks, raw_sample=None)

    envelope = None
    try:
        envelope = normalize_output(raw_text, duration_ms)
        if not envelope.answer or not envelope.answer.strip():
            checks.append(DryRunCheck(name="envelope_shape", passed=False, detail="Normalized answer is empty"))
            envelope = None
        else:
            checks.append(
                DryRunCheck(
                    name="envelope_shape",
                    passed=True,
                    detail=f"Answer: {len(envelope.answer)} chars, sources: {len(envelope.sources)}",
                )
            )
    except Exception as exc:
        checks.append(DryRunCheck(name="envelope_shape", passed=False, detail=f"normalize_output raised: {exc}"))
        envelope = None

    if envelope is None:
        checks.append(DryRunCheck(name="sanitization", passed=False, detail="Skipped — envelope_shape failed"))
        return DryRunResponse(valid=False, tool_id=body.tool_id, checks=checks, raw_sample=None)

    try:
        sanitized = sanitize_envelope(envelope, [server])
        stripped_urls = sum(1 for s in sanitized.sources if s.url is None)
        checks.append(
            DryRunCheck(
                name="sanitization",
                passed=True,
                detail=f"Sanitized {stripped_urls} source URLs",
            )
        )
        final_envelope = sanitized
    except Exception as exc:
        logger.warning("dry_run sanitization raised (non-fatal): %s", exc)
        checks.append(
            DryRunCheck(
                name="sanitization",
                passed=True,
                detail=f"Sanitization skipped (non-fatal): {exc}",
            )
        )
        final_envelope = envelope

    valid = all(c.passed for c in checks)
    return DryRunResponse(
        valid=valid,
        tool_id=body.tool_id,
        checks=checks,
        raw_sample=final_envelope.model_dump() if valid else None,
    )
