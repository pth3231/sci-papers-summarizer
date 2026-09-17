export type Role = 'user' | 'assistant'

export interface Message {
  id: string
  role: Role
  content: string
}

export type DocStatus = 'uploading' | 'ready' | 'error'

export interface DocMeta {
  id: string
  name: string
  size: number
  status: DocStatus
  /** Number of chunks ingested into the vector store (backend response). */
  chunks?: number
}
