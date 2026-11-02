# Math LaTeX Rendering — Design

**Date:** 2026-10-26
**Status:** Approved (design)

## Problem

Chat answers that contain mathematics render poorly. The frontend already
wires up KaTeX (`remark-math` + `rehype-katex` in `ChatPanel.tsx`), but the
LLM (GLM) is not emitting math in a form the pipeline can render:

- **Plain text / Unicode math** — expressions arrive as ASCII or Unicode
  (`x^2`, `a_i`, `√`, `Σ`, `α`, `≤`) with no LaTeX delimiters, so
  `remark-math` never recognizes them as math and KaTeX is never invoked.
- **Markdown mangling** — bare `_` and `^` in prose trigger markdown
  emphasis, partially italicizing or corrupting formulas.
- **Lost emphasis** — standalone equations that should be visually prominent
  are not; the model sometimes wraps them in `**bold**` instead of display
  math, which looks wrong.

Root cause: the system prompt gives the model no math-formatting contract, and
even when a model does emit LaTeX, GLM commonly uses `\(...\)` / `\[...\]`
delimiters, which `remark-math` ignores by default (it only recognizes
`$...$` / `$$...$$`).

The renderer (KaTeX) is not the problem — it is being starved of valid input.

## Approach

Approach **B**: fix the source (prompt) *and* make rendering resilient to the
model's delimiter choice.

1. **Backend prompt contract** — instruct the model to always emit standard
   LaTeX wrapped in `$...$` (inline) / `$$...$$` (block).
2. **Frontend delimiter normalization** — a small, pure, well-tested function
   that converts `\(...\)` → `$...$` and `\[...\]` → `$$...$$` before
   `remark-math` runs, so answers render even when the model falls back to
   backslash delimiters.

Rejected alternatives:
- **Prompt-only** — depends entirely on model compliance; raw `\(...\)`
  output would still render as literal text.
- **Swap renderer (MathJax, etc.)** — the renderer is not the problem; adds
  dependencies for no gain. YAGNI.

## Components

### 1. `SYSTEM_PROMPT` — `src/routers/chat.py`

Extend the existing prompt with an explicit math-formatting contract:

- Write **all** mathematical expressions, variables, and symbols as LaTeX.
- Wrap inline math in `$...$`; wrap standalone or emphasized equations in
  `$$...$$`.
- Never use Unicode math symbols (`√`, `Σ`, `α`, `≤`, …) or bare ASCII math
  (`x^2`, `a_i`) outside delimiters.
- Do not use `**bold**` to emphasize an equation — use display math
  (`$$...$$`) instead.

No change to streaming, citation markers, or the context/user-prompt build.

### 2. `normalizeMath()` — frontend helper

A pure `string → string` function in a new module
`src/view/src/lib/math.ts`, mirroring the existing `src/view/src/lib/citations.ts`
helper module. Exported and imported into `ChatPanel.tsx`.

Behavior:
- Convert `\[ ... \]` → `$$ ... $$` (block/display math).
- Convert `\( ... \)` → `$ ... $` (inline math).
- Leave content inside fenced code blocks (```` ``` ````) and inline code
  (`` ` ``) untouched, so code samples containing those sequences are not
  rewritten.
- Idempotent: running it on already-`$`-delimited content is a no-op.

### Data flow

In `ChatPanel.tsx`, assistant content is currently rendered as
`<Markdown>{citationize(msg.content)}</Markdown>`. This becomes:

```
<Markdown>{normalizeMath(citationize(msg.content))}</Markdown>
```

`citationize` runs first (it inserts citation link markup), then
`normalizeMath` fixes math delimiters. The two transforms are independent:
`citationize` touches `[n]` citation tokens, `normalizeMath` touches math
delimiters.

`remarkPlugins`, `rehypePlugins`, and KaTeX CSS stay exactly as they are.

## Error handling

- `normalizeMath` is a pure transform over a string; malformed or unbalanced
  delimiters are passed through unchanged rather than throwing, so a weird
  model output degrades to "renders as-is" rather than crashing the message.
- The streaming/error-sentinel path in `chat.py` is unchanged.

## Testing

- **Vitest setup** (frontend has no test runner today):
  - Add `vitest` as a dev dependency.
  - Add a `"test": "vitest run"` script (and optionally `"test:watch"`) to
    `src/view/package.json`.
  - Add minimal Vitest config (environment `node` is sufficient —
    `normalizeMath` is a pure string transform, no DOM needed). Reuse the
    existing Vite config where practical.
  - Test file: `src/view/src/lib/math.test.ts`.
- **Frontend unit tests** for `normalizeMath`:
  - `\( ... \)` → `$ ... $`
  - `\[ ... \]` → `$$ ... $$`
  - mixed inline + block in one string
  - sequences inside fenced code blocks and inline code are left untouched
  - idempotency (already-`$` content unchanged)
  - content with no math is returned unchanged
- **Backend**: existing chat tests (citations, top-k, streaming) must still
  pass; the prompt change is additive and does not alter response structure.

## Out of scope

- Changing the math renderer (KaTeX stays).
- Parser/ingest-side math handling (already captures equations as LaTeX).
- Styling/theming of rendered equations beyond what display math provides.
