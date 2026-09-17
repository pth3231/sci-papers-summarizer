import { useRef, useState } from 'react'
import type { DocMeta } from '../types'

interface UploadPanelProps {
  docs: DocMeta[]
  rejection: string | null
  onFiles: (files: File[]) => void
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const STATUS_LABEL: Record<DocMeta['status'], string> = {
  uploading: 'processing…',
  ready: 'ready',
  error: 'error',
}

export function UploadPanel({ docs, rejection, onFiles }: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  return (
    <aside className="upload-panel">
      <h2 className="panel-title">Papers</h2>

      <div
        className={`dropzone${dragOver ? ' drag-over' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          onFiles(Array.from(e.dataTransfer.files))
        }}
      >
        <p>Drop PDF / text files here</p>
        <p className="dropzone-hint">or click to browse</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files))
          e.target.value = '' // allow re-selecting the same file
        }}
      />

      {rejection && <p className="rejection">{rejection}</p>}

      <ul className="doc-list">
        {docs.map((doc) => (
          <li key={doc.id} className="doc-item">
            <span className="doc-name" title={doc.name}>
              {doc.name}
            </span>
            <span className="doc-meta">
              {formatSize(doc.size)}
              {doc.chunks !== undefined && ` · ${doc.chunks} chunks`}
              <span className={`status-chip ${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
            </span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
