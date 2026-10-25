/**
 * Document library client — the arena's pre-loaded corpus.
 *
 * The backend has always served this (GET /tool-arena/documents, DOC-02/DOC-03)
 * but nothing in the UI called it, so the only way to give the arena a
 * document was to upload one. These helpers close that gap.
 *
 * Both return the same `content: string` the upload path produces, so
 * everything downstream — the compare request, the ephemeral corpus, the
 * engines — is unchanged.
 *
 * Each library document also ships an example pair (`suggested_question` /
 * `expected_answer`): a question the document really answers, and the answer
 * a reader would give. It is what lets a first-time user run a meaningful
 * duel without having read the document first — the form prefills both
 * fields, and the expected answer is then shown next to the two anonymous
 * results. Unlike the benchmark catalogue, this ground truth is safe to hand
 * to the client: nothing scores against it.
 *
 * Kept out of the component and pure-TS so it can be tested without a DOM
 * (see build-request.test.ts for the same pattern).
 */

export type LibraryDocument = {
  id: string
  title: string
  description: string
  // Absent for a manifest entry that ships no example.
  suggested_question?: string | null
  expected_answer?: string | null
}

export type LibraryDocumentDetail = LibraryDocument & {
  content: string
}

type FetchLike = typeof fetch

/**
 * List the library. Returns [] on any failure rather than throwing: the
 * picker is an addition to the upload field, not a replacement, so a backend
 * that cannot answer should make the picker disappear, not break the form.
 */
export async function fetchLibraryDocuments(
  base: string,
  fetchImpl: FetchLike = fetch
): Promise<LibraryDocument[]> {
  try {
    const resp = await fetchImpl(`${base}/tool-arena/documents`)
    if (!resp.ok) return []
    const body = await resp.json()
    if (!Array.isArray(body)) return []
    return body.filter(
      (d): d is LibraryDocument =>
        !!d && typeof d.id === 'string' && typeof d.title === 'string'
    )
  } catch {
    return []
  }
}

export class LibraryDocumentError extends Error {}

/**
 * Fetch one document: its text, and the example pair that comes with it.
 * Throws on failure — unlike the listing, this one is a deliberate user
 * action, so silence would leave them staring at a form that refuses to
 * submit with no reason given.
 *
 * A missing or malformed example is not a failure: the document still loads,
 * the form just has nothing to prefill.
 */
export async function fetchLibraryDocument(
  base: string,
  id: string,
  fetchImpl: FetchLike = fetch
): Promise<LibraryDocumentDetail> {
  let resp: Response
  try {
    resp = await fetchImpl(`${base}/tool-arena/documents/${encodeURIComponent(id)}`)
  } catch {
    throw new LibraryDocumentError('network')
  }
  if (!resp.ok) throw new LibraryDocumentError(String(resp.status))
  const body = (await resp.json()) as Partial<LibraryDocumentDetail>
  const content = body?.content ?? ''
  if (!content.trim()) throw new LibraryDocumentError('empty')
  return {
    id,
    title: typeof body.title === 'string' ? body.title : id,
    description: typeof body.description === 'string' ? body.description : '',
    content,
    suggested_question:
      typeof body.suggested_question === 'string' ? body.suggested_question : null,
    expected_answer:
      typeof body.expected_answer === 'string' ? body.expected_answer : null
  }
}

/**
 * The example pair, or null when the document ships none (or ships a
 * half-pair: a question with no answer is worse than no example at all —
 * it prefills a field the user then has to judge blind).
 */
export function exampleOf(
  doc: Pick<LibraryDocument, 'suggested_question' | 'expected_answer'> | null | undefined
): { question: string; answer: string } | null {
  const question = (doc?.suggested_question ?? '').trim()
  const answer = (doc?.expected_answer ?? '').trim()
  if (!question || !answer) return null
  return { question, answer }
}
