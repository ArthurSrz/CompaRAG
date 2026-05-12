/**
 * sse-client — async iterable wrapping fetch() against /tool-arena/compare's
 * SSE stream (Phase 13 / Wave 6.8). Parses `data: <json>\n\n` framed events
 * and yields parsed objects in arrival order.
 *
 * Buffer handling: a single SSE event can span multiple ReadableStream
 * chunks (slice 7.2), so we accumulate and split on the double-newline
 * frame delimiter rather than assuming one event per read.
 */

export type SSEEvent = {
  type: string
  pos?: 'a' | 'b'
  [key: string]: unknown
}

export type CompareStreamBody = {
  task: string
  goal: string
  document_content: string
  haystack: 'sandbox' | 'benchmark'
  task_type?: string
  evaluation_query_id?: string
}

export type StreamCompareOptions = {
  fetchImpl?: typeof fetch
  url?: string
  signal?: AbortSignal
}

const FRAME_SEP = '\n\n'

export async function* streamCompare(
  body: CompareStreamBody,
  opts: StreamCompareOptions = {}
): AsyncIterable<SSEEvent> {
  const fetchImpl = opts.fetchImpl ?? fetch
  const url = opts.url ?? '/tool-arena/compare'

  const response = await fetchImpl(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify(body),
    signal: opts.signal
  })

  if (!response.ok || !response.body) {
    throw new Error(`compare stream failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sepIdx: number
    while ((sepIdx = buffer.indexOf(FRAME_SEP)) !== -1) {
      const frame = buffer.slice(0, sepIdx)
      buffer = buffer.slice(sepIdx + FRAME_SEP.length)
      const event = parseFrame(frame)
      if (event) yield event
    }
  }

  // Flush any trailing event without a final \n\n (defensive).
  if (buffer.trim().length > 0) {
    const event = parseFrame(buffer)
    if (event) yield event
  }
}

function parseFrame(frame: string): SSEEvent | null {
  // SSE frames can carry multiple field lines; we only care about `data:`.
  // Multi-line `data:` payloads are joined per the spec, though our backend
  // emits single-line JSON. Keep this lenient so server changes don't break us.
  const lines = frame.split('\n')
  const dataLines = lines
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice('data:'.length).trimStart())
  if (dataLines.length === 0) return null
  try {
    return JSON.parse(dataLines.join('\n')) as SSEEvent
  } catch {
    return null
  }
}
