/**
 * buildToolArenaRequest — pure-TS payload builder for the arena duel.
 *
 * Vitest server workspace (no jsdom — see project_vitest4_jsdom_broken memory).
 */
import { describe, expect, it } from 'vitest'
import { BenchmarkRequestError, buildToolArenaRequest } from './build-request'

describe('buildToolArenaRequest', () => {
  it('summary mode omits expected_answer (slice 1.1)', () => {
    expect(
      buildToolArenaRequest({
        task: 't',
        goal: 'g',
        documentContent: 'd',
        taskType: 'summary',
        expectedAnswer: ''
      })
    ).toEqual({
      task: 't',
      goal: 'g',
      document_content: 'd',
      task_type: 'summary',
      haystack: 'sandbox'
    })
  })

  it('qa mode with expected_answer includes it (slice 1.2)', () => {
    const req = buildToolArenaRequest({
      task: 't',
      goal: 'g',
      documentContent: 'd',
      taskType: 'qa',
      expectedAnswer: 'Paris'
    })
    expect(req.expected_answer).toBe('Paris')
    expect(req.task_type).toBe('qa')
  })

  it('qa mode with empty expected_answer omits the field (slice 1.3 — empty)', () => {
    const req = buildToolArenaRequest({
      task: 't',
      goal: 'g',
      documentContent: 'd',
      taskType: 'qa',
      expectedAnswer: ''
    })
    expect('expected_answer' in req).toBe(false)
  })

  it('qa mode with whitespace-only expected_answer omits the field (slice 1.3 — whitespace)', () => {
    const req = buildToolArenaRequest({
      task: 't',
      goal: 'g',
      documentContent: 'd',
      taskType: 'qa',
      expectedAnswer: '   \n\t  '
    })
    expect('expected_answer' in req).toBe(false)
  })
})


describe('buildToolArenaRequest — benchmark mode', () => {
  const input = {
    task: 'ma question',
    goal: 'mon objectif',
    documentContent: 'mon document',
    taskType: 'qa' as const,
    expectedAnswer: 'ma reponse',
    haystack: 'benchmark' as const,
    evaluationQueryId: 'ref_palier_arriere_vaux'
  }

  it('sends only the query id', () => {
    expect(buildToolArenaRequest(input)).toEqual({
      task: '',
      goal: '',
      document_content: '',
      task_type: 'qa',
      haystack: 'benchmark',
      evaluation_query_id: 'ref_palier_arriere_vaux'
    })
  })

  it('drops the user document, question and expected answer', () => {
    const payload = buildToolArenaRequest(input)
    expect(payload.document_content).toBe('')
    expect(payload.task).toBe('')
    // The server already holds the ground truth; the user's guess would only
    // pollute it.
    expect(payload.expected_answer).toBeUndefined()
  })

  it('refuses benchmark mode without a query id', () => {
    expect(() =>
      buildToolArenaRequest({ ...input, evaluationQueryId: undefined })
    ).toThrow(BenchmarkRequestError)
  })

  it('still defaults to sandbox when no mode is given', () => {
    const { haystack, evaluationQueryId, ...sandboxInput } = input
    expect(buildToolArenaRequest(sandboxInput).haystack).toBe('sandbox')
  })
})

describe('debug flag', () => {
  it('asks for it in sandbox mode only when enabled', () => {
    const base = {
      task: 'q',
      goal: 'g',
      documentContent: 'doc',
      taskType: 'qa' as const,
      expectedAnswer: ''
    }
    expect(buildToolArenaRequest(base).debug).toBeUndefined()
    expect(buildToolArenaRequest({ ...base, debug: true }).debug).toBe(true)
  })

  it('carries over to benchmark mode, where tools fail too', () => {
    const req = buildToolArenaRequest({
      task: '',
      goal: '',
      documentContent: '',
      taskType: 'qa',
      expectedAnswer: '',
      haystack: 'benchmark',
      evaluationQueryId: 'q01',
      debug: true
    })
    expect(req.debug).toBe(true)
  })
})
