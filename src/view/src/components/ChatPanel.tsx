import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import 'katex/dist/katex.min.css'
import rehypeKatex from 'rehype-katex'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { API_BASE_URL } from '../lib/api'
import { CITATION_MARKER_RE } from '../lib/citations'
import type { Message } from '../types'

// Turn [n] markers into #cite-n links so they survive markdown rendering
// (markdown links can't carry classes — the `a` override below decides
// chip styling from the invalid-citation list).
function citationize(content: string): string {
  return content.replace(CITATION_MARKER_RE, (_m, num: string) => `[${num}](#cite-${num})`)
}

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
        {messages.map((msg) => {
          const invalidCites = msg.citations?.invalid ?? []
          return (
          <div key={msg.id} className={`message ${msg.role}`}>
            {msg.role === 'assistant' ? (
              <Markdown
                remarkPlugins={[remarkMath, remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeKatex]}
                components={{
                  a: ({ href, children }) =>
                    typeof href === 'string' && href.startsWith('#cite-') ? (
                      <a
                        href={href}
                        className={`cite-chip${invalidCites.includes(Number(href.slice(6))) ? ' invalid' : ''}`}
                      >
                        {children}
                      </a>
                    ) : (
                      <a href={href} target="_blank" rel="noreferrer">{children}</a>
                    ),
                }}
              >
                {citationize(msg.content)}
              </Markdown>
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
              <div className="sources-block" id="cite-list">
                <p className="sources-title">Sources</p>
                <ul className="sources-list">
                  {msg.sources.map((source) => {
                    const cited = msg.citations?.valid.includes(source.index) ?? false
                    return (
                      <li key={source.index} className={`source-item${cited ? '' : ' uncited'}`}>
                        <span className="source-filename">
                          [{source.index}] {source.filename}
                          {source.section ? ` — ${source.section}` : ''}
                        </span>
                        {source.kind === 'figure' && source.figure_url && (
                          <img
                            className="source-figure"
                            src={`${API_BASE_URL}${source.figure_url}`}
                            alt={source.excerpt}
                          />
                        )}
                        <span className="source-excerpt">{source.excerpt}</span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </div>
          )
        })}
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
