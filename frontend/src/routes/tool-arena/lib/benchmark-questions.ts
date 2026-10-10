/**
 * Benchmark catalogue client — GET /tool-arena/questions.
 *
 * These are the questions whose answers the backend already knows, so it can
 * score both tools automatically (Recall@K, MRR, NDCG) alongside the human
 * vote. The payload deliberately carries no ground truth: a client holding
 * the expected passages could grade, or game, the duel it is voting on.
 *
 * Returns [] on any failure, like the document listing: benchmark mode is an
 * addition. A backend without a mounted corpus should make the option
 * disappear, not break the form — and offering it would only earn a 422.
 */

export type BenchmarkQuestion = {
  id: string
  query_text: string
  goal_text: string
}

type FetchLike = typeof fetch

export async function fetchBenchmarkQuestions(
  base: string,
  fetchImpl: FetchLike = fetch
): Promise<BenchmarkQuestion[]> {
  try {
    const resp = await fetchImpl(`${base}/tool-arena/questions`)
    if (!resp.ok) return []
    const body = await resp.json()
    if (!Array.isArray(body)) return []
    return body.filter(
      (q): q is BenchmarkQuestion =>
        !!q && typeof q.id === 'string' && typeof q.query_text === 'string'
    )
  } catch {
    return []
  }
}
