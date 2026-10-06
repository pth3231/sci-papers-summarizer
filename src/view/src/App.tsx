import { useEffect, useState } from 'react'
import './App.css'
import { ChatPanel } from './components/ChatPanel'
import { UploadPanel } from './components/UploadPanel'
import {
  deleteDocument,
  isAcceptedFile,
  listDocuments,
  streamChat,
  uploadDocument,
} from './lib/api'
import { CITATION_MARKER_RE } from './lib/citations'
import type { DocMeta, Message } from './types'

function extractCitations(content: string, sourceCount: number) {
  const markers = [...content.matchAll(CITATION_MARKER_RE)].map((m) => Number(m[1]))
  const valid = markers.filter((n) => n >= 1 && n <= sourceCount)
  const invalid = markers.filter((n) => n < 1 || n > sourceCount)
  return { valid, invalid }
}

function App() {
  const [docs, setDocs] = useState<DocMeta[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [activeDocIds, setActiveDocIds] = useState<string[]>([])

  // Backend is the source of truth for the document list, so a reload still
  // shows previously uploaded papers.
  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((err) => setNotice(err instanceof Error ? err.message : String(err)))
  }, [])

  function toggleDoc(id: string) {
    setActiveDocIds((current) =>
      current.includes(id) ? current.filter((docId) => docId !== id) : [...current, id],
    )
  }

  async function handleDelete(id: string) {
    try {
      await deleteDocument(id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
      setActiveDocIds((prev) => prev.filter((docId) => docId !== id))
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleFiles(files: File[]) {
    for (const file of files) {
      if (!isAcceptedFile(file.name)) {
        setNotice(`"${file.name}" skipped — only PDF and text files are supported`)
        continue
      }
      setNotice(null)

      // Optimistic entry; replaced once the upload resolves.
      const tempId = crypto.randomUUID()
      setDocs((prev) => [
        ...prev,
        { id: tempId, name: file.name, size: file.size, status: 'uploading' },
      ])
      try {
        const doc = await uploadDocument(file)
        setDocs((prev) => prev.map((d) => (d.id === tempId ? doc : d)))
        setActiveDocIds((prev) => [...prev, doc.id]) // new paper joins the current scope
      } catch (err) {
        // The backend may still have recorded a failed-upload row (with its
        // own real id) — drop the optimistic placeholder and refetch so it
        // shows up instead of silently vanishing.
        setDocs((prev) => prev.filter((d) => d.id !== tempId))
        setNotice(err instanceof Error ? err.message : String(err))
        try {
          setDocs(await listDocuments())
        } catch {
          // Keep whatever we had — the notice above already surfaced the failure.
        }
      }
    }
  }

  async function handleSend(text: string) {
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    const history = [...messages, userMsg]

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setIsStreaming(true)
    let streamed = ''
    try {
      const sources = await streamChat(
        history,
        (delta) => {
          streamed += delta
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m)),
          )
        },
        activeDocIds,
      )
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, sources, citations: extractCitations(streamed, sources.length) }
            : m,
        ),
      )
    } catch (err) {
      const note = err instanceof Error ? err.message : String(err)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: m.content.trimEnd(), error: note }
            : m,
        ),
      )
    } finally {
      setIsStreaming(false)
    }
  }

  const selectedNames = docs
    .filter((d) => activeDocIds.includes(d.id))
    .map((d) => d.name)

  return (
    <div className="app">
      <UploadPanel
        docs={docs}
        notice={notice}
        activeDocIds={activeDocIds}
        onFiles={handleFiles}
        onToggleDoc={toggleDoc}
        onDelete={handleDelete}
      />
      <ChatPanel
        messages={messages}
        isStreaming={isStreaming}
        focusLabel={selectedNames.length > 0 ? selectedNames.join(', ') : undefined}
        onSend={handleSend}
      />
    </div>
  )
}

export default App
