import type { DocMeta, Message } from '../types'

// In dev (Vite server on :5173) call the backend origin directly — override
// the port with VITE_API_URL if 8000 is taken; when the built frontend is
// served by FastAPI itself, stay same-origin (relative).
const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_URL ?? 'http://localhost:8000')
  : ''

const ACCEPTED_EXTENSIONS = ['.pdf', '.txt']

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

interface UploadResponse {
  document_id: string
  filename: string
  chunks: number
}

// POST multipart/form-data to the backend; the server parses, chunks, embeds,
// and ingests the document before responding.
export async function uploadDocument(file: File): Promise<DocMeta> {
  const body = new FormData()
  body.append('file', file)

  const res = await fetch(`${API_BASE}/documents/`, { method: 'POST', body })
  if (!res.ok) throw new Error(await errorMessage(res))

  const data: UploadResponse = await res.json()
  return {
    id: data.document_id,
    name: data.filename,
    size: file.size,
    chunks: data.chunks,
    status: 'ready',
  }
}

// POST the latest user message; the backend streams the answer back as a
// chunked text response. Decode and forward each delta as it arrives. When
// documentId is given, retrieval is scoped to that one uploaded paper.
export async function streamChat(
  history: Message[],
  onChunk: (delta: string) => void,
  documentId?: string,
): Promise<void> {
  const message = [...history].reverse().find((m) => m.role === 'user')?.content
  if (!message) return

  const res = await fetch(`${API_BASE}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, document_id: documentId }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  if (!res.body) throw new Error('response has no body to stream')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
  onChunk(decoder.decode()) // flush the decoder's tail
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') return data.detail
  } catch {
    // non-JSON error body — fall through
  }
  return `${res.status} ${res.statusText}`
}
