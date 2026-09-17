import { useState } from 'react'
import './App.css'
import { ChatPanel } from './components/ChatPanel'
import { UploadPanel } from './components/UploadPanel'
import { isAcceptedFile, streamChat, uploadDocument } from './lib/api'
import type { DocMeta, Message } from './types'

function App() {
  const [docs, setDocs] = useState<DocMeta[]>([])
  const [rejection, setRejection] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [activeDocId, setActiveDocId] = useState<string | null>(null)

  function toggleDoc(id: string) {
    setActiveDocId((current) => (current === id ? null : id))
  }

  async function handleFiles(files: File[]) {
    for (const file of files) {
      if (!isAcceptedFile(file.name)) {
        setRejection(`"${file.name}" skipped — only PDF and text files are supported`)
        continue
      }
      setRejection(null)

      // Optimistic entry; patched once the (mock) upload resolves.
      const tempId = crypto.randomUUID()
      setDocs((prev) => [
        ...prev,
        { id: tempId, name: file.name, size: file.size, status: 'uploading' },
      ])
      try {
        const doc = await uploadDocument(file)
        setDocs((prev) => prev.map((d) => (d.id === tempId ? doc : d)))
        setActiveDocId(doc.id) // new paper becomes the focus of the chat
      } catch {
        setDocs((prev) => prev.map((d) => (d.id === tempId ? { ...d, status: 'error' } : d)))
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
    try {
      await streamChat(history, (delta) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m)),
        )
      }, activeDocId ?? undefined)
    } catch (err) {
      const note = err instanceof Error ? err.message : String(err)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: `${m.content}\n\n[error] ${note}` } : m,
        ),
      )
    } finally {
      setIsStreaming(false)
    }
  }

  return (
    <div className="app">
      <UploadPanel
        docs={docs}
        rejection={rejection}
        activeDocId={activeDocId}
        onFiles={handleFiles}
        onToggleDoc={toggleDoc}
      />
      <ChatPanel
        messages={messages}
        isStreaming={isStreaming}
        focusLabel={activeDocId ? docs.find((d) => d.id === activeDocId)?.name : undefined}
        onSend={handleSend}
      />
    </div>
  )
}

export default App
