/**
 * Document preview.
 *
 * Vitest server workspace (no jsdom — see build-request.test.ts).
 *
 * The caps are the point: the excerpt must stay small enough to sit above
 * the question box, and the expanded view must stay small enough not to
 * freeze the tab on a 5 MB upload.
 */
import { describe, expect, it } from 'vitest'
import {
  EXCERPT_CHARS,
  FULL_CHARS,
  buildDocumentPreview,
  canExpand
} from './document-preview'

const words = (n: number) => 'mot '.repeat(n)

describe('buildDocumentPreview', () => {
  it('returns a short document whole, untruncated', () => {
    const p = buildDocumentPreview('Trois mots ici')
    expect(p.text).toBe('Trois mots ici')
    expect(p.truncated).toBe(false)
    expect(p.charCount).toBe(14)
  })

  it('caps the excerpt and still reports the full length', () => {
    const content = words(1000)
    const p = buildDocumentPreview(content)
    expect(p.text.length).toBeLessThanOrEqual(EXCERPT_CHARS)
    expect(p.truncated).toBe(true)
    expect(p.charCount).toBe(content.length)
  })

  it('cuts on a word boundary so a part number is never half-shown', () => {
    // The cap lands inside `PAL-3300-B`: a raw slice would preview `PAL-`,
    // which reads as a different part than `PAL-3300-A`.
    // 'mot ' is 4 chars, so this prefix ends on a space just short of the cap.
    const prefix = 'mot '.repeat(Math.floor(EXCERPT_CHARS / 4) - 1)
    const content = `${prefix}PAL-3300-B ${words(50)}`
    const p = buildDocumentPreview(content)
    expect(p.truncated).toBe(true)
    expect(p.text).not.toContain('PAL')
  })

  it('still shows something when the first chars hold no whitespace', () => {
    const p = buildDocumentPreview('x'.repeat(EXCERPT_CHARS * 2))
    expect(p.text.length).toBe(EXCERPT_CHARS)
    expect(p.truncated).toBe(true)
  })

  it('expanded shows far more, but not a 5MB upload', () => {
    const content = words(200_000)
    const p = buildDocumentPreview(content, true)
    expect(p.text.length).toBeGreaterThan(EXCERPT_CHARS)
    expect(p.text.length).toBeLessThanOrEqual(FULL_CHARS)
    expect(p.truncated).toBe(true)
  })

  it('treats an empty document as empty rather than throwing', () => {
    expect(buildDocumentPreview('')).toEqual({ text: '', truncated: false, charCount: 0 })
  })
})

describe('canExpand', () => {
  it('is false for a document the excerpt already shows whole', () => {
    expect(canExpand('court')).toBe(false)
  })

  it('is true as soon as the excerpt leaves something out', () => {
    expect(canExpand('y'.repeat(EXCERPT_CHARS + 1))).toBe(true)
  })
})
