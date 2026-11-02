# Design

<!-- impeccable:design-schema 1 -->

## World

Bright, paper-white Operate surface for a two-person thesis-reading tool — precise and terminal-adjacent (Claude Code lineage) rather than consumer-chat. One warm amber-orange accent carries active state, primary actions, and citation chips; everything else stays near-black ink on a bright warm-white ground with flat 1px hairline panels, no decorative shadows.

## Tokens (`src/view/src/index.css`)

- `--background: #fdfbf8` / `--surface: #ffffff` / `--surface-sunken: #f8f4ee` (rail, code blocks, table heads)
- `--ink: #201b13` (text) / `--muted: #7a7265`
- `--border: #ece4d8` / `--border-strong: #d9cdb8`
- `--accent: #e2590f` / `--accent-hover: #c2480a` / `--accent-soft: #fdead9` / `--accent-text: #b6450b`
- `--danger: #b3261e` / `--danger-soft: #fdecea`
- `--sans`: system font stack (carries all UI and prose) / `--mono`: ui-monospace stack (code blocks and citation markers only)
- `--shadow-sm` / `--shadow-md`: soft offset shadows (popover, mobile drawer) — no zero-offset glow

## Structure

- Top bar (48px): sidebar toggle + wordmark, hairline bottom border.
- `.sidebar-shell`: collapsible Papers rail, animated via `grid-template-columns` (not `width`, to avoid layout-thrash). Push-layout on desktop (≥720px); fixed overlay drawer with backdrop below 720px.
- Chat column: message stream (user bubbles in solid ink, assistant in bordered white cards), composer pinned to the bottom.
- Citation chips (`[n]`, monospace, accent-soft pill) open a `CitationPopover` anchored to the clicked chip via a rect captured synchronously at click time — not a live DOM reference, since react-markdown remounts `<a>` nodes on the re-render the click itself triggers.

## Icons

Hand-drawn inline SVG set (`src/view/src/components/Icons.tsx`), single 1.5px stroke: panel toggle, chevron, close, trash, upload, send. Replaces the previous unicode `×`/`▾` glyphs.

## Provenance

No raster assets shipped; this build is code-led (Operate mode, no comp round — see `.impeccable/surfaces/src-view-src.md`).
