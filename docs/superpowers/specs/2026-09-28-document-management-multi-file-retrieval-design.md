# Document Management & Multi-File Retrieval — Design

Date: 2026-09-28
Status: Approved for planning

## Context

The RAG pipeline (upload → parse → chunk → embed → store → retrieve → generate) works end to end, but document handling is minimal:

- `GET /documents/` is a stub that always returns `{"documents": []}`. The frontend only tracks uploads in local React state, so the list resets on every reload.
- Chat/search retrieval accepts a single optional `document_id` — the UI lets the user "focus" on exactly one paper (or none, meaning search everything). There's no way to scope a question to a custom subset of papers.
- Uploads are saved to `uploads/<filename>`, so two uploads with the same filename overwrite each other on disk while the vector store still holds chunks tied to the old document_id — an orphaned-data bug.
- There's no delete endpoint.
- The chat endpoint retrieves context chunks before generating an answer, but never surfaces which chunks/papers were used — answers are unattributed.

This spec finalizes document management and retrieval: a real, persistent document list; multi-file selection with custom retrieval scope; deletion; and visible sources — built with proper error handling rather than only the happy path.

## Goals

- Document list persists across reloads and is backend-authoritative.
- Users can select any subset of uploaded papers ("custom choice") to scope a chat question to; selecting none searches all papers (unchanged default).
- Users can delete an uploaded paper (chunks + file + registry entry).
- Same-name uploads never collide or orphan data.
- Chat answers show which papers/excerpts they drew from.
- Failure paths (parse errors, delete of missing doc, etc.) are handled explicitly and surfaced to the user instead of failing silently or leaving stuck state.

## Non-goals

- Async/background upload processing — uploads stay synchronous (embedding a single paper is fast; revisit if the future parser spec makes this slow).
- Automated tests — skipped for this round per explicit decision; manual verification only.
- Per-document top-k retrieval balancing — multi-doc retrieval uses global top-k across the selected set, not top-k-per-document.
- Better parsing (diagrams/math) — separate follow-up spec.

## Architecture

### Document registry (new)

A SQLite-backed registry (`src/database/document_store.py`, stdlib `sqlite3`, no new dependency) becomes the source of truth for the document list, replacing the current "derive everything from Chroma or local state" approach. Rationale: it gives real status tracking and cheap listing/deletion instead of scanning every chunk in Chroma to reconstruct document metadata.

Table `documents`:

| column | type | notes |
|---|---|---|
| id | text (PK) | UUID, same as `document_id` used in Chroma metadata |
| filename | text | original filename |
| size_bytes | integer | original upload size |
| status | text | `ready` \| `error` |
| error_message | text, nullable | set when status is `error` |
| chunk_count | integer | 0 when errored |
| created_at | text | ISO timestamp |

### Upload flow changes

- Files save to `uploads/<document_id>/<filename>` instead of `uploads/<filename>`. This is what makes same-name uploads safe — each upload gets its own ID-namespaced folder, so two uploads of `paper.pdf` never collide and each is a fully separate document.
- A registry row is created for every upload attempt, not just successful ones. If parsing/chunking/embedding fails partway through, the row is kept with `status='error'` and the exception message, rather than the document vanishing entirely. The user sees the failed row in their list and can delete it (no stuck, invisible state).
- On success: row updated with `status='ready'`, `chunk_count`, `size_bytes`.

### Delete flow (new)

`DELETE /documents/{id}`, in this order:

1. Delete Chroma chunks: `collection.delete(where={"document_id": id})`.
2. Delete `uploads/<id>/` folder from disk.
3. Delete the registry row.

Deleting the registry row last means that if an earlier step throws, the record persists and the delete is retryable — nothing gets silently lost. Returns 404 if `id` isn't in the registry.

### Retrieval changes

- `ChatRequest.document_id: str | None` → `ChatRequest.document_ids: list[str] | None`. Empty/omitted = search all papers (today's default behavior, unchanged).
- `vector_store.search_chunks` takes `document_ids: list[str] | None` and filters with Chroma's `where={"document_id": {"$in": document_ids}}` when the list is non-empty.
- Multi-document retrieval returns one global top-k across all selected documents combined (not top-k per document) — simplest option, matches the explicit decision to accept that a strongly dominant paper may crowd out others in the returned context.
- `GET /search/` gets the same `document_ids` parameter for consistency with chat.

### Sources

Retrieval already completes before the LLM call starts. The chat endpoint will attach the retrieved sources (filename + excerpt truncated to ~200 chars, for display only — not re-parsed for grounding) as a JSON `X-Sources` response header, set before the `StreamingResponse` begins streaming the answer body. The streamed body format is unchanged (still plain text deltas).

The CORS middleware must add `expose_headers=["X-Sources"]` — without it, browsers hide custom response headers from cross-origin `fetch` calls (relevant in dev, where the Vite server and FastAPI run on different origins).

## Frontend changes

- `UploadPanel` fetches `GET /documents/` on mount so a reload shows previously uploaded papers, instead of starting from an empty list.
- The single-toggle "focus one paper" interaction becomes checkboxes — any subset of papers can be selected independently. `App`'s `activeDocId: string | null` becomes `activeDocIds: string[]` (empty = search all).
- Each document row gets a delete action (×), guarded by `window.confirm(...)` — no custom modal needed for a single-user tool.
- A document with `status: 'error'` displays its `error_message` inline and remains deletable.
- `ChatPanel`'s composer focus label changes from "Asking about: `<name>` / all papers" to listing the selected paper names, or "all papers" when none are selected.
- After an assistant message finishes streaming, a "Sources" block renders underneath it (paper name + excerpt), parsed from the `X-Sources` header. `Message` gains an optional `sources?: { filename: string; excerpt: string }[]`.

## Error handling

- **Upload parse/chunk/embed failure**: registry row kept with `status='error'` + message; HTTP 422 returned to the caller; document still visible in the list (deletable, not stuck).
- **Delete unknown id**: 404.
- **Delete partial failure**: registry row retained (see ordering above) so the operation can be retried instead of leaving orphaned Chroma chunks or files with no record.
- **Chat with stale document_ids** (e.g. a doc was deleted in another tab while still selected client-side): Chroma's `$in` filter simply matches nothing for the missing id — no special backend handling needed. Frontend already reconciles selection against the fetched list on next load.
- **API error surfacing**: consistent `{"detail": "..."}` JSON bodies, which the frontend's existing `errorMessage()` helper already parses.

## Testing

Manual verification only for this round (explicit decision — no test framework introduced yet).

Manual test checklist for the implementation plan to cover:
- Upload two files with the same name → both appear as distinct documents, no data collision.
- Upload a corrupt/unparseable file → appears with `status: 'error'` and a message, is deletable.
- Reload the page after uploading → documents persist.
- Select 0, 1, and multiple documents → chat retrieval scope matches selection.
- Delete a document → its chunks no longer surface in retrieval, file removed from disk.
- Ask a question and confirm the Sources block matches the excerpts actually used.
