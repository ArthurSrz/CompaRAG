/**
 * buildToolArenaRequest — assemble the JSON payload for POST /tool-arena/compare.
 *
 * Sandbox-only for now; benchmark mode (evaluation_query_id) wires later.
 * The `expected_answer` field is purely client-side ground-truth display —
 * the backend ignores it. We send it anyway so future analytics can pick it
 * up server-side without another deploy.
 *
 * shouldShowExpectedAnswerBanner — decides whether to render the
 * "Réponse attendue" banner during the blind comparison step.
 */

export type ArenaPhase = 'input' | 'loading' | 'results' | 'revealed' | 'unavailable'

export type ArenaTaskType = 'summary' | 'qa'

export type BuildRequestInput = {
  task: string
  goal: string
  documentContent: string
  taskType: ArenaTaskType
  expectedAnswer: string
}

export type ToolArenaRequest = {
  task: string
  goal: string
  document_content: string
  task_type: ArenaTaskType
  haystack: 'sandbox'
  expected_answer?: string
}

export function buildToolArenaRequest(input: BuildRequestInput): ToolArenaRequest {
  const base: ToolArenaRequest = {
    task: input.task,
    goal: input.goal,
    document_content: input.documentContent,
    task_type: input.taskType,
    haystack: 'sandbox'
  }
  const trimmed = input.expectedAnswer.trim()
  if (input.taskType === 'qa' && trimmed.length > 0) {
    base.expected_answer = trimmed
  }
  return base
}

export function shouldShowExpectedAnswerBanner(
  phase: ArenaPhase,
  expectedAnswer: string | null
): boolean {
  if (phase !== 'results') return false
  if (!expectedAnswer) return false
  return expectedAnswer.trim().length > 0
}
