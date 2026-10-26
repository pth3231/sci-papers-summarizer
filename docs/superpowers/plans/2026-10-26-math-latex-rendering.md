# Math LaTeX Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat answers render mathematics reliably by prompting GLM to emit delimited LaTeX and normalizing backslash delimiters on the frontend before KaTeX runs.

**Architecture:** Two coordinated changes. (1) The backend `SYSTEM_PROMPT` gains an explicit math-formatting contract so GLM emits `$...$` / `$$...$$` LaTeX instead of Unicode/ASCII math. (2) A pure frontend helper `normalizeMath()` rewrites any `\(...\)` → `$...$` and `\[...\]` → `$$...$$` (GLM's common fallback delimiters) before `remark-math` sees the content, leaving code spans untouched. KaTeX (already wired) is unchanged.

**Tech Stack:** Python/FastAPI backend (pytest), React 19 + TypeScript frontend (Vite 8), KaTeX via `remark-math` + `rehype-katex`. New: Vitest for frontend unit tests.

## Global Constraints

- Frontend helpers live in `src/view/src/lib/` as small single-responsibility modules (mirror `src/view/src/lib/citations.ts`).
- `normalizeMath` must be a pure `string → string` function with no side effects and no DOM dependency.
- Do not change the KaTeX/remark/rehype plugin configuration or the streaming/error-sentinel path.
- Frontend transforms compose as `normalizeMath(citationize(msg.content))` — `citationize` first, then `normalizeMath`.
- All paths below are relative to the repo root unless shown otherwise.

---

### Task 1: Vitest setup + `normalizeMath` helper

**Files:**
- Modify: `src/view/package.json` (add `vitest` dev dep + `test` script)
- Modify: `src/view/vite.config.ts` (add Vitest `test` config)
- Create: `src/view/src/lib/math.ts`
- Test: `src/view/src/lib/math.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `export function normalizeMath(content: string): string` from `src/view/src/lib/math.ts`.

- [ ] **Step 1: Install Vitest and add the test script**

Run (from repo root):

```bash
cd src/view && npm install -D vitest && cd -
```

Then edit `src/view/package.json` scripts block to add a `test` entry:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "test": "vitest run"
  },
```

- [ ] **Step 2: Add Vitest config to `src/view/vite.config.ts`**

Replace the file contents with (switches `defineConfig` import to `vitest/config`, which types the `test` field; `node` environment is enough for a pure string transform):

```ts
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
  },
})
```

- [ ] **Step 3: Write the failing tests**

Create `src/view/src/lib/math.test.ts`:

```ts
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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run (from repo root):

```bash
cd src/view && npm test && cd -
```

Expected: FAIL — Vitest reports it cannot resolve `./math` (module not created yet).

- [ ] **Step 5: Implement `normalizeMath`**

Create `src/view/src/lib/math.ts`:

```ts
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run (from repo root):

```bash
cd src/view && npm test && cd -
```

Expected: PASS — all 7 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/view/package.json src/view/package-lock.json src/view/vite.config.ts src/view/src/lib/math.ts src/view/src/lib/math.test.ts
git commit -m "feat(view): add normalizeMath helper + Vitest for math delimiter normalization"
```

---

### Task 2: Add math-formatting contract to `SYSTEM_PROMPT`

**Files:**
- Modify: `src/routers/chat.py:23-29` (the `SYSTEM_PROMPT` constant)
- Test: `src/tests/test_chat_prompt.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: an updated `SYSTEM_PROMPT` string (same name, same module `src.routers.chat`); its structure/usage in `stream_answer(SYSTEM_PROMPT, user_prompt)` is unchanged.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_chat_prompt.py`:

```python
from src.routers.chat import SYSTEM_PROMPT


def test_system_prompt_requires_latex_math_contract():
    prompt = SYSTEM_PROMPT.lower()
    # The model must be told to emit LaTeX wrapped in dollar delimiters,
    # not Unicode/ASCII math, so remark-math + KaTeX can render it.
    assert "latex" in prompt
    assert "$...$" in SYSTEM_PROMPT
    assert "$$...$$" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from repo root):

```bash
uv run pytest src/tests/test_chat_prompt.py -q
```

Expected: FAIL — current prompt contains no `latex`/`$...$`/`$$...$$`.

- [ ] **Step 3: Update `SYSTEM_PROMPT`**

In `src/routers/chat.py`, replace the existing constant (lines 23-29):

```python
SYSTEM_PROMPT = (
    "You are a scientific paper summarizer. Answer the question using the "
    "provided context excerpts from the user's papers when they are relevant. "
    "Prefer concise bullet points. End each bullet or claim with its citation "
    "marker(s), like [1] or [2][5]. Cite only the numbered excerpts provided, "
    "and say so explicitly when the context is insufficient."
)
```

with:

```python
SYSTEM_PROMPT = (
    "You are a scientific paper summarizer. Answer the question using the "
    "provided context excerpts from the user's papers when they are relevant. "
    "Prefer concise bullet points. End each bullet or claim with its citation "
    "marker(s), like [1] or [2][5]. Cite only the numbered excerpts provided, "
    "and say so explicitly when the context is insufficient. "
    "Write ALL mathematics as standard LaTeX: wrap inline math in $...$ and "
    "standalone or emphasized equations in $$...$$. Never write math as Unicode "
    "symbols (such as √, Σ, α, ≤, ×) or as bare ASCII (such as x^2 or a_i) "
    "outside these delimiters. Do not use **bold** to emphasize an equation — "
    "put it on its own line as display math with $$...$$."
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from repo root):

```bash
uv run pytest src/tests/test_chat_prompt.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the existing chat tests to confirm no regression**

Run (from repo root):

```bash
uv run pytest src/tests -q -k chat
```

Expected: PASS — citation/top-k/streaming behavior unchanged (the prompt change is additive).

- [ ] **Step 6: Commit**

```bash
git add src/routers/chat.py src/tests/test_chat_prompt.py
git commit -m "feat(chat): instruct model to emit delimited LaTeX for math"
```

---

### Task 3: Wire `normalizeMath` into `ChatPanel`

**Files:**
- Modify: `src/view/src/components/ChatPanel.tsx` (import + render call site)

**Interfaces:**
- Consumes: `normalizeMath` from `../lib/math` (Task 1).
- Produces: assistant messages rendered through `normalizeMath(citationize(msg.content))`.

- [ ] **Step 1: Import `normalizeMath`**

In `src/view/src/components/ChatPanel.tsx`, add the import next to the existing `citations` import (currently near line 9, `import { CITATION_MARKER_RE } from '../lib/citations'`):

```ts
import { normalizeMath } from '../lib/math'
```

- [ ] **Step 2: Compose the transform at the render site**

Find the `<Markdown>` child for assistant content (currently `{citationize(msg.content)}`) and change it to:

```tsx
                {normalizeMath(citationize(msg.content))}
```

Leave `remarkPlugins`, `rehypePlugins`, and the `a` component override exactly as they are.

- [ ] **Step 3: Type-check and build**

Run (from repo root):

```bash
cd src/view && npm run build && cd -
```

Expected: PASS — `tsc -b` reports no type errors and Vite builds successfully.

- [ ] **Step 4: Lint**

Run (from repo root):

```bash
cd src/view && npm run lint && cd -
```

Expected: no new ESLint errors.

- [ ] **Step 5: Verify rendering in the running app**

Start the backend (`uv run fastapi dev`) and frontend (`cd src/view && npm run dev`), ask a question whose answer contains math, and confirm:
- Inline math renders (e.g. `$x^2$` shows as a formula, not literal text).
- Any `\(...\)` / `\[...\]` the model emits also renders (normalization working).
- No markdown mangling of underscores/carets inside formulas.

- [ ] **Step 6: Commit**

```bash
git add src/view/src/components/ChatPanel.tsx
git commit -m "feat(view): render assistant math through normalizeMath before KaTeX"
```

---

## Self-Review

**Spec coverage:**
- SYSTEM_PROMPT math contract → Task 2. ✓
- `normalizeMath` helper in `src/view/src/lib/math.ts` → Task 1. ✓
- Compose `normalizeMath(citationize(...))` at render site → Task 3. ✓
- Vitest setup → Task 1 (folded into the helper's deliverable). ✓
- Frontend unit tests (both delimiters, code-fence exclusion, idempotency, no-math) → Task 1, Step 3. ✓
- Backend existing tests still pass → Task 2, Step 5. ✓
- KaTeX/plugin config unchanged → stated in Global Constraints and Task 3, Step 2. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command shows expected output. ✓

**Type consistency:** `normalizeMath(content: string): string` defined in Task 1, consumed with that exact signature in Task 3. `SYSTEM_PROMPT` name unchanged across Task 2 and its test. ✓
