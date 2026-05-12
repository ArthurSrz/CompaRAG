/**
 * sse-client — async iterable over the /tool-arena/compare SSE stream
 * (Phase 13 / Wave 7 slices 7.1+7.2).
 *
 * The backend emits `data: {...}\n\n` per event; this client wraps `fetch`
 * with a ReadableStream reader and yields parsed JSON event objects in order.
 *
 * 7.1 — happy path: multi-event SSE body parses into ordered objects.
 * 7.2 — chunk-split: one SSE event split across two reads still parses.
 */
import { describe, expect, it } from 'vitest'
import { streamCompare } from './sse-client'

function mockFetchResponse(chunks: string[]): typeof fetch {
  return (() => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        for (const c of chunks) {
          controller.enqueue(encoder.encode(c))
        }
        controller.close()
      }
    })
    return Promise.resolve(
      new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' }
      })
    )
  }) as unknown as typeof fetch
}

describe('streamCompare', () => {
  it('parses SSE data lines into event objects in order (slice 7.1)', async () => {
    const body =
      'data: {"type":"ingest_start","pos":"a"}\n\n' +
      'data: {"type":"ingest_done","pos":"b","cache_hit":true}\n\n' +
      'data: {"type":"complete"}\n\n'

    const events: unknown[] = []
    for await (const e of streamCompare(
      { task: 't', goal: 'g', document_content: 'd', haystack: 'sandbox' },
      { fetchImpl: mockFetchResponse([body]) }
    )) {
      events.push(e)
    }

    expect(events).toEqual([
      { type: 'ingest_start', pos: 'a' },
      { type: 'ingest_done', pos: 'b', cache_hit: true },
      { type: 'complete' }
    ])
  })

  it('handles a single event split across two reads (slice 7.2)', async () => {
    const chunks = [
      'data: {"type":"ingest_start"',
      ',"pos":"a"}\n\n' + 'data: {"type":"complete"}\n\n'
    ]
    const events: unknown[] = []
    for await (const e of streamCompare(
      { task: 't', goal: 'g', document_content: 'd', haystack: 'sandbox' },
      { fetchImpl: mockFetchResponse(chunks) }
    )) {
      events.push(e)
    }
    expect(events).toEqual([
      { type: 'ingest_start', pos: 'a' },
      { type: 'complete' }
    ])
  })
})
