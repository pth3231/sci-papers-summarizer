import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import type { Message } from '../types'

interface ChatPanelProps {
  messages: Message[]
  isStreaming: boolean
  /** Filename of the paper the chat is scoped to, if any. */
  focusLabel?: string
  onSend: (text: string) => void
}

export function ChatPanel({ messages, isStreaming, focusLabel, onSend }: ChatPanelProps) {
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  // Keep the newest message (and its streaming chunks) in view.
  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [messages])

  function submit() {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    onSend(text)
  }

  const streamingId = isStreaming ? messages.at(-1)?.id : undefined

  return (
    <section className="chat-panel">
      <div className="message-list" ref={listRef}>
        {messages.length === 0 && (
          <p className="empty-hint">
            Upload a paper, then ask a question — answers will stream in here.
          </p>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}`}>
            {msg.role === 'assistant' ? (
              <Markdown remarkPlugins={[remarkGfm, remarkBreaks]}>{msg.content}</Markdown>
            ) : (
              msg.content
            )}
            {msg.id === streamingId && <span className="stream-cursor" />}
            {msg.role === 'assistant' && msg.error && (
              <div className="message-error">
                <span className="message-error-title">Generation failed</span>
                <span className="message-error-detail">{msg.error}</span>
              </div>
            )}
            {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
              <div className="sources-block">
                <p className="sources-title">Sources</p>
                <ul className="sources-list">
                  {msg.sources.map((source, index) => (
                    <li key={index} className="source-item">
                      <span className="source-filename">{source.filename}</span>
                      <span className="source-excerpt">{source.excerpt}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="composer">
        <div className={`focus-label${focusLabel === undefined ? ' muted' : ''}`}>
          {focusLabel === undefined ? 'Asking about: all papers' : `Asking about: ${focusLabel}`}
        </div>
        <div className="composer-row">
          <textarea
            value={input}
            rows={2}
            placeholder="Ask about the uploaded papers…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
          />
          <button type="button" onClick={submit} disabled={isStreaming || !input.trim()}>
            {isStreaming ? 'Streaming…' : 'Send'}
          </button>
        </div>
      </div>
    </section>
  )
}
