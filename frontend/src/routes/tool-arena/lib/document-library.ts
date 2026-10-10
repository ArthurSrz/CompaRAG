/**
 * Document library client — the arena's pre-loaded corpus.
 *
 * The backend has always served this (GET /tool-arena/documents, DOC-02/DOC-03)
 * but nothing in the UI called it, so the only way to give the arena a
 * document was to upload one. These helpers close that gap.
 *
 * Both return the same `document_content: string` the upload path produces,
 * so everything downstream — the compare request, the ephemeral corpus, the
 * engines — is unchanged.
 *
 * Kept out of the component and pure-TS so it can be tested without a DOM
 * (see build-request.test.ts for the same pattern).
 */

export type LibraryDocument = {
  id: string
  title: string
  description: string
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
 * Fetch one document's text. Throws on failure — unlike the listing, this one
 * is a deliberate user action, so silence would leave them staring at a form
 * that refuses to submit with no reason given.
 */
export async function fetchLibraryDocumentContent(
  base: string,
  id: string,
  fetchImpl: FetchLike = fetch
): Promise<string> {
  let resp: Response
  try {
    resp = await fetchImpl(`${base}/tool-arena/documents/${encodeURIComponent(id)}`)
  } catch {
    throw new LibraryDocumentError('network')
  }
  if (!resp.ok) throw new LibraryDocumentError(String(resp.status))
  const body = (await resp.json()) as { content?: string }
  const content = body?.content ?? ''
  if (!content.trim()) throw new LibraryDocumentError('empty')
  return content
}
