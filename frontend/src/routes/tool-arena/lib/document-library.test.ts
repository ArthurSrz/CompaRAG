/**
 * Document library client.
 *
 * Vitest server workspace (no jsdom — see build-request.test.ts).
 *
 * The asymmetry between the two functions is the point and is pinned here:
 * a failing *listing* hides the picker and leaves upload working, while a
 * failing *selection* must surface, because the user asked for it.
 */
import { describe, expect, it, vi } from 'vitest'
import {
  LibraryDocumentError,
  exampleOf,
  fetchLibraryDocument,
  fetchLibraryDocuments
} from './document-library'

const BASE = 'https://api.test'

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body
  } as Response
}

describe('fetchLibraryDocuments', () => {
  it('returns the listing', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([
        { id: 'a', title: 'A', description: 'da' },
        { id: 'b', title: 'B', description: 'db' }
      ])
    )
    const docs = await fetchLibraryDocuments(BASE, fetchImpl as never)
    expect(docs.map((d) => d.id)).toEqual(['a', 'b'])
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/tool-arena/documents`)
  })

  it('returns [] when the backend errors, so the picker just disappears', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(null, false, 500))
    expect(await fetchLibraryDocuments(BASE, fetchImpl as never)).toEqual([])
  })

  it('returns [] when the network throws', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline')
    })
    expect(await fetchLibraryDocuments(BASE, fetchImpl as never)).toEqual([])
  })

  it('drops malformed entries rather than rendering undefined titles', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse([{ id: 'a', title: 'A', description: '' }, { nope: true }, null])
    )
    const docs = await fetchLibraryDocuments(BASE, fetchImpl as never)
    expect(docs).toHaveLength(1)
  })

  it('returns [] when the payload is not a list', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ documents: [] }))
    expect(await fetchLibraryDocuments(BASE, fetchImpl as never)).toEqual([])
  })
})

describe('fetchLibraryDocument', () => {
  it('returns the document text', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ id: 'a', content: 'texte' }))
    const doc = await fetchLibraryDocument(BASE, 'a', fetchImpl as never)
    expect(doc.content).toBe('texte')
  })

  it('returns the example pair shipped with the document', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse({
        id: 'a',
        title: 'A',
        description: 'da',
        content: 'texte',
        suggested_question: 'Quelle pression ?',
        expected_answer: 'Entre 1,0 et 1,5 bar'
      })
    )
    const doc = await fetchLibraryDocument(BASE, 'a', fetchImpl as never)
    expect(exampleOf(doc)).toEqual({
      question: 'Quelle pression ?',
      answer: 'Entre 1,0 et 1,5 bar'
    })
  })

  it('loads a document that ships no example, with nothing to prefill', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ id: 'a', content: 'texte' }))
    const doc = await fetchLibraryDocument(BASE, 'a', fetchImpl as never)
    expect(doc.content).toBe('texte')
    expect(exampleOf(doc)).toBeNull()
  })

  it('url-encodes the id', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ content: 'x' }))
    await fetchLibraryDocument(BASE, 'a b/c', fetchImpl as never)
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/tool-arena/documents/a%20b%2Fc`)
  })

  it('throws with the status when the document is missing', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(null, false, 404))
    await expect(
      fetchLibraryDocument(BASE, 'ghost', fetchImpl as never)
    ).rejects.toThrow(LibraryDocumentError)
  })

  it('throws rather than loading an empty document', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ content: '   ' }))
    await expect(
      fetchLibraryDocument(BASE, 'a', fetchImpl as never)
    ).rejects.toThrow('empty')
  })

  it('throws on a network failure', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline')
    })
    await expect(
      fetchLibraryDocument(BASE, 'a', fetchImpl as never)
    ).rejects.toThrow('network')
  })
})

describe('exampleOf', () => {
  it('rejects a half-pair rather than prefilling a question with no answer', () => {
    expect(exampleOf({ suggested_question: 'Q', expected_answer: null })).toBeNull()
    expect(exampleOf({ suggested_question: '  ', expected_answer: 'A' })).toBeNull()
  })

  it('is null for a document that has neither', () => {
    expect(exampleOf(null)).toBeNull()
    expect(exampleOf({})).toBeNull()
  })
})
