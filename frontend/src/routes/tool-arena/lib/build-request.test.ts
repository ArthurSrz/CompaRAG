/**
 * buildToolArenaRequest + shouldShowExpectedAnswerBanner —
 * pure-TS helpers for the QA ground-truth field UX (Phase 13 / Wave 7+).
 *
 * Vitest server workspace (no jsdom — see project_vitest4_jsdom_broken memory).
 *
 * Slice 1: payload builder
 * Slice 2: banner visibility state machine
 */
import { describe, expect, it } from 'vitest'
import {
  buildToolArenaRequest,
  shouldShowExpectedAnswerBanner
} from './build-request'

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

describe('shouldShowExpectedAnswerBanner', () => {
  it('false during input phase even if expectedAnswer set (slice 2.1)', () => {
    expect(shouldShowExpectedAnswerBanner('input', 'Paris')).toBe(false)
  })

  it('true during results phase when expectedAnswer non-empty (slice 2.2)', () => {
    expect(shouldShowExpectedAnswerBanner('results', 'Paris')).toBe(true)
  })

  it('false during results phase when expectedAnswer empty/whitespace (slice 2.3)', () => {
    expect(shouldShowExpectedAnswerBanner('results', '')).toBe(false)
    expect(shouldShowExpectedAnswerBanner('results', null)).toBe(false)
    expect(shouldShowExpectedAnswerBanner('results', '   ')).toBe(false)
  })

  it('false during revealed phase (slice 2.4)', () => {
    expect(shouldShowExpectedAnswerBanner('revealed', 'Paris')).toBe(false)
  })
})
