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
  fetchLibraryDocumentContent,
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

describe('fetchLibraryDocumentContent', () => {
  it('returns the document text', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ id: 'a', content: 'texte' }))
    expect(await fetchLibraryDocumentContent(BASE, 'a', fetchImpl as never)).toBe('texte')
  })

  it('url-encodes the id', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ content: 'x' }))
    await fetchLibraryDocumentContent(BASE, 'a b/c', fetchImpl as never)
    expect(fetchImpl).toHaveBeenCalledWith(`${BASE}/tool-arena/documents/a%20b%2Fc`)
  })

  it('throws with the status when the document is missing', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(null, false, 404))
    await expect(
      fetchLibraryDocumentContent(BASE, 'ghost', fetchImpl as never)
    ).rejects.toThrow(LibraryDocumentError)
  })

  it('throws rather than loading an empty document', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ content: '   ' }))
    await expect(
      fetchLibraryDocumentContent(BASE, 'a', fetchImpl as never)
    ).rejects.toThrow('empty')
  })

  it('throws on a network failure', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('offline')
    })
    await expect(
      fetchLibraryDocumentContent(BASE, 'a', fetchImpl as never)
    ).rejects.toThrow('network')
  })
})
