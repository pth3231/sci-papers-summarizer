import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { API_BASE_URL } from '../lib/api'
import type { SourceExcerpt } from '../types'
import { CloseIcon } from './Icons'

export interface AnchorRect {
  top: number
  bottom: number
  left: number
  right: number
}

interface CitationPopoverProps {
  source: SourceExcerpt
  anchorRect: AnchorRect
  onClose: () => void
  /** The chat message list — the one scrollable area expected to move
   * under the popover on its own (e.g. auto-scrolling while a later
   * message streams in). Its scroll re-anchors the popover instead of
   * dismissing it; scroll anywhere else still closes it as before. Taken
   * as a ref (read inside effects, not during render) since refs aren't
   * meant to be dereferenced at render time. */
  scrollContainerRef?: RefObject<HTMLDivElement | null>
}

const MARGIN = 12
const WIDTH = 320

export function CitationPopover({ source, anchorRect, onClose, scrollContainerRef }: CitationPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null)
  // anchorRect is a plain snapshot taken at click time — the chip's own DOM
  // node can be remounted by react-markdown as soon as this popover's state
  // update re-renders the tree, so re-reading its live rect here would race
  // that remount and land on a detached (0,0) node.
  const [style, setStyle] = useState<{ top: number; left: number; flipped: boolean; maxHeight: number }>({
    top: anchorRect.bottom + 8,
    left: Math.max(anchorRect.left, MARGIN),
    flipped: false,
    maxHeight: window.innerHeight - anchorRect.bottom - 8 - MARGIN,
  })
  // How far scrollContainer has scrolled since this popover opened, so its
  // position can track the anchor instead of going stale or disappearing.
  const [scrollDelta, setScrollDelta] = useState(0)

  // Flip above the chip once the popover's real height is known, if there
  // isn't room below.
  useEffect(() => {
    const popoverHeight = popoverRef.current?.offsetHeight ?? 160
    const spaceBelow = window.innerHeight - anchorRect.bottom
    const spaceAbove = anchorRect.top
    const flipped = spaceBelow < popoverHeight + MARGIN && spaceAbove > popoverHeight + MARGIN
    const left = Math.min(
      Math.max(anchorRect.left, MARGIN),
      window.innerWidth - WIDTH - MARGIN,
    )
    setStyle({
      top: flipped ? anchorRect.top - popoverHeight - 8 : anchorRect.bottom + 8,
      left,
      flipped,
      maxHeight: (flipped ? spaceAbove : spaceBelow) - 8 - MARGIN,
    })
    setScrollDelta(0)
  }, [anchorRect])

  // Re-anchor as the message list scrolls on its own (new deltas arriving
  // while streaming auto-scroll it) rather than treating that as the user
  // scrolling the page away from the popover.
  useEffect(() => {
    const container = scrollContainerRef?.current
    if (!container) return
    const initialScrollTop = container.scrollTop
    function onContainerScroll() {
      setScrollDelta(container!.scrollTop - initialScrollTop)
    }
    container.addEventListener('scroll', onContainerScroll)
    return () => container.removeEventListener('scroll', onContainerScroll)
  }, [scrollContainerRef])

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (popoverRef.current?.contains(e.target as Node)) return
      onClose()
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    function onWindowScroll(e: Event) {
      // The message list's own scroll is handled by the effect above
      // instead of dismissing the popover.
      if (e.target === scrollContainerRef?.current) return
      onClose()
    }
    function onResize() {
      onClose()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onWindowScroll, true)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onWindowScroll, true)
      window.removeEventListener('resize', onResize)
    }
  }, [onClose, scrollContainerRef])

  return (
    <div
      ref={popoverRef}
      className={`citation-popover${style.flipped ? ' flipped' : ''}`}
      style={{ top: style.top - scrollDelta, left: style.left, width: WIDTH, maxHeight: Math.max(style.maxHeight, 120) }}
      role="dialog"
      aria-label={`Source ${source.index}`}
    >
      <div className="citation-popover-head">
        <span className="citation-popover-source">
          [{source.index}] {source.filename}
          {source.section ? ` — ${source.section}` : ''}
        </span>
        <button type="button" className="citation-popover-close" onClick={onClose} aria-label="Close">
          <CloseIcon />
        </button>
      </div>
      <div className="citation-popover-body">
        {source.kind === 'figure' && source.figure_url && (
          <img
            className="citation-popover-figure"
            src={`${API_BASE_URL}${source.figure_url}`}
            alt={source.excerpt}
          />
        )}
        <p className="citation-popover-excerpt">{source.excerpt}</p>
      </div>
    </div>
  )
}
