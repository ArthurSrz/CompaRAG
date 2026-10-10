/**
 * Benchmark catalogue client.
 *
 * Same failure posture as the document listing, and for the same reason:
 * benchmark mode is an addition, so a backend that cannot answer should make
 * the option disappear rather than offer a mode the server would 422.
 */
import { describe, expect, it, vi } from 'vitest'
import { fetchBenchmarkQuestions } from './benchmark-questions'

const BASE = 'https://api.test'

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, status: ok ? 200 : 500, json: async () => body } as Response
}

describe('fetchBenchmarkQuestions', () => {
  it('returns the catalogue', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([
        { id: 'a', query_text: 'Q1', goal_text: 'G1' },
        { id: 'b', query_text: 'Q2', goal_text: 'G2' }
      ])
    )
    const questions = await fetchBenchmarkQuestions(BASE, fetchImpl as never)
    expect(questions.map((q) => q.id)).toEqual(['a', 'b'])
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/tool-arena/questions`)
  })

  it('returns [] when the catalogue is unavailable', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(null, false))
    expect(await fetchBenchmarkQuestions(BASE, fetchImpl as never)).toEqual([])
  })

  it('returns [] when the network throws', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline')
    })
    expect(await fetchBenchmarkQuestions(BASE, fetchImpl as never)).toEqual([])
  })

  it('drops malformed entries', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([{ id: 'a', query_text: 'Q', goal_text: '' }, { id: 'b' }, null])
    )
    expect(await fetchBenchmarkQuestions(BASE, fetchImpl as never)).toHaveLength(1)
  })
})
