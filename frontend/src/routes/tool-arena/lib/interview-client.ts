/**
 * BUT : client HTTP typé de la boucle d'entretien knowledge_capture.
 * Quatre appels — start / reply / finish / finalize — en fetch simple (pas de
 * SSE pour le MVP). Même résolution d'origine que +page.svelte pour que les
 * appels partent vers le même backend que /tool-arena/compare.
 */
import { browser, dev } from '$app/environment'
import { env as publicEnv } from '$env/dynamic/public'

export type ArmState = {
  type: 'question' | 'artifact' | 'error'
  question: string | null
  turn: number
  max_turns: number
  done: boolean
  error: string | null
}

export type InterviewStartResponse = {
  session_hash: string
  max_turns: number
  deadline_ts: number
  arm_a: ArmState
  arm_b: ArmState
}

export type InterviewReplyResponse = {
  arm: 'a' | 'b'
  state: ArmState
  both_done: boolean
}

export type CompareResponse = {
  session_hash: string
  result_a: string | null
  result_b: string | null
  error_a: string | null
  error_b: string | null
}

export class ToolUnavailableError extends Error {
  constructor() {
    super('tool_unavailable')
  }
}

function backendBase(): string {
  if (!browser) return publicEnv.PUBLIC_API_LOCAL_URL || publicEnv.PUBLIC_API_URL || 'http://localhost:8001'
  if (dev || publicEnv.PUBLIC_API_DEV_MODE === 'true') return 'http://localhost:8001'
  return publicEnv.PUBLIC_API_URL || window.location.origin || 'http://localhost:8001'
}

async function post<T>(path: string, body: object, sessionHash?: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (sessionHash) headers['X-Session-Hash'] = sessionHash
  const response = await fetch(`${backendBase()}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body)
  })
  if (response.status === 503) {
    const errBody = await response.json().catch(() => ({}))
    if (errBody?.error === 'tool_unavailable') throw new ToolUnavailableError()
  }
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export function startInterview(task: string, goal: string): Promise<InterviewStartResponse> {
  return post('/tool-arena/interview/start', { task, goal })
}

export function sendReply(
  sessionHash: string,
  arm: 'a' | 'b',
  answer: string
): Promise<InterviewReplyResponse> {
  return post('/tool-arena/interview/reply', { arm, answer }, sessionHash)
}

export function finishArm(sessionHash: string, arm: 'a' | 'b'): Promise<InterviewReplyResponse> {
  return post('/tool-arena/interview/finish', { arm }, sessionHash)
}

export function finalizeInterview(sessionHash: string): Promise<CompareResponse> {
  return post('/tool-arena/interview/finalize', {}, sessionHash)
}
