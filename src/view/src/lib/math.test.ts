import { describe, expect, it } from 'vitest'
import { normalizeMath } from './math'

describe('normalizeMath', () => {
  it('converts inline \\(...\\) to $...$', () => {
    expect(normalizeMath('the value \\(x^2\\) here')).toBe('the value $x^2$ here')
  })

  it('converts block \\[...\\] to $$...$$', () => {
    expect(normalizeMath('\\[E = mc^2\\]')).toBe('$$E = mc^2$$')
  })

  it('handles mixed inline and block math in one string', () => {
    expect(normalizeMath('inline \\(a_i\\) and block \\[\\sum x\\]')).toBe(
      'inline $a_i$ and block $$\\sum x$$',
    )
  })

  it('leaves fenced code blocks untouched', () => {
    const input = '```\n\\(x\\)\n```'
    expect(normalizeMath(input)).toBe(input)
  })

  it('leaves inline code untouched', () => {
    const input = 'use `\\(x\\)` literally'
    expect(normalizeMath(input)).toBe(input)
  })

  it('is idempotent on dollar-delimited content', () => {
    const input = 'already $x^2$ and $$y = 1$$'
    expect(normalizeMath(input)).toBe(input)
  })

  it('returns content with no math unchanged', () => {
    const input = 'no math here at all'
    expect(normalizeMath(input)).toBe(input)
  })
})
