/**
 * buildToolArenaRequest — assemble the JSON payload for POST /tool-arena/compare.
 *
 * Two haystack modes. Sandbox sends the user's own document and their own
 * question. Benchmark sends only an evaluation_query_id: the backend
 * substitutes the canned task/goal from its catalogue and scores both sides
 * against ground truth it never reveals to the client. Sending task/goal in
 * benchmark mode would be ignored at best and misleading at worst, so the
 * builder omits them — and the backend's validator rejects a payload that
 * mixes the two (document_content with an evaluation_query_id, or benchmark
 * without one).
 * The `expected_answer` field is purely client-side ground-truth display —
 * the backend ignores it. We send it anyway so future analytics can pick it
 * up server-side without another deploy.
 *
 * shouldShowExpectedAnswerBanner — decides whether to render the
 * "Réponse attendue" banner during the blind comparison step.
 */

export type ArenaPhase = 'input' | 'loading' | 'results' | 'revealed' | 'unavailable'

export type ArenaTaskType = 'summary' | 'qa'

export type ArenaHaystack = 'sandbox' | 'benchmark'

export type BuildRequestInput = {
  task: string
  goal: string
  documentContent: string
  taskType: ArenaTaskType
  expectedAnswer: string
  haystack?: ArenaHaystack
  evaluationQueryId?: string
}

export type ToolArenaRequest = {
  task: string
  goal: string
  document_content: string
  task_type: ArenaTaskType
  haystack: ArenaHaystack
  expected_answer?: string
  evaluation_query_id?: string
}

export class BenchmarkRequestError extends Error {}

export function buildToolArenaRequest(input: BuildRequestInput): ToolArenaRequest {
  if ((input.haystack ?? 'sandbox') === 'benchmark') {
    if (!input.evaluationQueryId) {
      throw new BenchmarkRequestError('benchmark mode requires an evaluationQueryId')
    }
    // task, goal and document_content stay empty: the backend fills the first
    // two from its catalogue and reads the corpus from disk. The expected
    // answer is ground truth the server already holds, so sending the user's
    // guess would only pollute it.
    return {
      task: '',
      goal: '',
      document_content: '',
      task_type: input.taskType,
      haystack: 'benchmark',
      evaluation_query_id: input.evaluationQueryId
    }
  }

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
