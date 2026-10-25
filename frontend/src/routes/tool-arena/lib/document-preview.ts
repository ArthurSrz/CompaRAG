/**
 * Document preview — what the form shows of a loaded document.
 *
 * A ready-made document used to be a title in a dropdown and nothing else:
 * you picked "Manuel de maintenance", got two anonymous answers, and had no
 * way to tell which one was right because you had never seen the document.
 * The preview closes that gap — and it does the same job for an upload,
 * where it doubles as a check that .pdf/.docx extraction produced real text
 * rather than a page of ligature noise.
 *
 * Two caps, because the two views answer different questions:
 *   - EXCERPT_CHARS — "what is this document about?", always on screen.
 *   - FULL_CHARS    — "does it say X?", on demand. Still capped: the upload
 *                     limit is 5 MB, and pushing that into the DOM freezes
 *                     the tab on the very machines this arena is demoed on.
 *
 * Pure TS, no DOM — same reason as build-request.ts: it can be tested in the
 * server workspace.
 */

export const EXCERPT_CHARS = 700
export const FULL_CHARS = 20_000

export type DocumentPreview = {
  /** Text to render. */
  text: string
  /** True when `text` stops short of the document. */
  truncated: boolean
  /** Length of the whole document, not of `text`. */
  charCount: number
}

/**
 * Cut on the last whitespace before the limit so the preview ends on a word
 * rather than mid-identifier — `PAL-3300-B` cut to `PAL-33` reads as a
 * different part number, which is exactly the confusion this document set
 * exists to expose.
 */
function cut(text: string, limit: number): string {
  const hard = text.slice(0, limit)
  const lastBreak = hard.search(/\s\S*$/)
  // Only honour the word boundary if it keeps most of the budget; a document
  // with no whitespace in its first `limit` chars must not preview as empty.
  if (lastBreak > limit * 0.8) return hard.slice(0, lastBreak)
  return hard
}

export function buildDocumentPreview(content: string, expanded = false): DocumentPreview {
  const text = content ?? ''
  const limit = expanded ? FULL_CHARS : EXCERPT_CHARS
  if (text.length <= limit) {
    return { text, truncated: false, charCount: text.length }
  }
  return { text: cut(text, limit), truncated: true, charCount: text.length }
}

/**
 * Whether the "see the whole document" toggle has anything left to show.
 * A 900-character document is over the excerpt cap but under the full cap,
 * so expanding it is worth offering; a 4-line one is not.
 */
export function canExpand(content: string): boolean {
  return (content ?? '').length > EXCERPT_CHARS
}
