export type Role = 'user' | 'assistant'

export interface SourceExcerpt {
  filename: string
  excerpt: string
}

export interface Message {
  id: string
  role: Role
  content: string
  sources?: SourceExcerpt[]
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
