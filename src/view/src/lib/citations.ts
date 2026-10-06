// Matches inline citation markers like "[12]" but not markdown links "[12](...)".
// Shared so citation extraction (App.tsx) and rendering (ChatPanel.tsx) stay in lockstep.
export const CITATION_MARKER_RE = /\[(\d{1,3})\](?!\()/g
