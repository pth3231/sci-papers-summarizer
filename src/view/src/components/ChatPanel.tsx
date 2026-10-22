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

function sourceElementId(messageId: string, index: number): string {
  return `source-${messageId}-${index}`
}

export function ChatPanel({ messages, isStreaming, focusLabel, onSend }: ChatPanelProps) {
  const [input, setInput] = useState('')
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set())
  const [highlightedSourceId, setHighlightedSourceId] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const pendingScrollIdRef = useRef<string | null>(null)

  function toggleSources(id: string) {
    setExpandedSources((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Expand that message's sources (if collapsed) and queue a scroll — the
  // target may not exist yet this render if sources were just expanded, so
  // the actual scroll happens in the effect below once the DOM has it.
  function goToSource(messageId: string, index: number) {
    setExpandedSources((current) => {
      if (current.has(messageId)) return current
      const next = new Set(current)
      next.add(messageId)
      return next
    })
    pendingScrollIdRef.current = sourceElementId(messageId, index)
  }

  useEffect(() => {
    const targetId = pendingScrollIdRef.current
    if (!targetId) return
    pendingScrollIdRef.current = null
    const el = document.getElementById(targetId)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedSourceId(targetId)
    const timer = setTimeout(() => setHighlightedSourceId(null), 1500)
    return () => clearTimeout(timer)
  }, [expandedSources])

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
                        onClick={(e) => {
                          e.preventDefault()
                          goToSource(msg.id, Number(href.slice(6)))
                        }}
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
              <div className="sources-block">
                <button
                  type="button"
                  className="sources-toggle"
                  onClick={() => toggleSources(msg.id)}
                >
                  Sources ({msg.sources.length}) {expandedSources.has(msg.id) ? '▾' : '▸'}
                </button>
                {expandedSources.has(msg.id) && (
                  <ul className="sources-list">
                    {msg.sources.map((source) => {
                      const cited = msg.citations?.valid.includes(source.index) ?? false
                      const elementId = sourceElementId(msg.id, source.index)
                      return (
                        <li
                          key={source.index}
                          id={elementId}
                          className={`source-item${cited ? '' : ' uncited'}${highlightedSourceId === elementId ? ' highlighted' : ''}`}
                        >
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
                )}
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
