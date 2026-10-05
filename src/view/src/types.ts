export type Role = 'user' | 'assistant'

export interface SourceExcerpt {
  index: number
  filename: string
  section: string
  kind: 'text' | 'figure'
  figure_url: string | null
  excerpt: string
}

export interface Message {
  id: string
  role: Role
  content: string
  sources?: SourceExcerpt[]
  /** Set when generation failed — rendered as an error banner, not answer text. */
  error?: string
  /** Post-stream citation validation against msg.sources. */
  citations?: { valid: number[]; invalid: number[] }
}

export type DocStatus = 'uploading' | 'ready' | 'error'

export interface DocMeta {
  id: string
  name: string
  size: number
  status: DocStatus
  /** Number of chunks ingested into the vector store (backend response). */
  chunks?: number
  /** Set when status is 'error' — why the upload failed. */
  error?: string
}
