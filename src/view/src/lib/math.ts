// Matches a fenced code block (```...```) or an inline code span (`...`).
// Used to carve out regions that must NOT have their delimiters rewritten.
const CODE_SPAN_RE = /```[\s\S]*?```|`[^`]*`/g

// GLM often emits LaTeX with \(...\) / \[...\] delimiters, which remark-math
// ignores (it only recognizes $...$ / $$...$$). Rewrite them so KaTeX renders.
function convertDelimiters(text: string): string {
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_m, body: string) => `$$${body}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_m, body: string) => `$${body}$`)
}

// Normalize math delimiters outside of code spans. Pure string transform:
// malformed/unbalanced input passes through unchanged rather than throwing,
// and already-$-delimited content is left as-is (idempotent).
export function normalizeMath(content: string): string {
  let result = ''
  let lastIndex = 0
  for (const match of content.matchAll(CODE_SPAN_RE)) {
    const start = match.index ?? 0
    result += convertDelimiters(content.slice(lastIndex, start))
    result += match[0] // code span: leave untouched
    lastIndex = start + match[0].length
  }
  result += convertDelimiters(content.slice(lastIndex))
  return result
}
