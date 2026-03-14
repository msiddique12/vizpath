import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { ChevronRight, ChevronDown, Eye, ClipboardCopy } from 'lucide-react'
import { Span, SpanType } from '@/lib/types'

const SPAN_COLORS: Record<SpanType, string> = {
  llm: 'bg-purple-500',
  tool: 'bg-blue-500',
  agent: 'bg-nvidia-500',
  retrieval: 'bg-yellow-500',
  chain: 'bg-orange-500',
  custom: 'bg-dark-400',
}

interface SpanNode {
  span: Span
  children: SpanNode[]
  depth: number
}

function buildSpanTree(spans: Span[]): SpanNode[] {
  const spanMap = new Map<string, SpanNode>()
  const roots: SpanNode[] = []

  spans.forEach((span) => {
    spanMap.set(span.id, { span, children: [], depth: 0 })
  })

  spans.forEach((span) => {
    const node = spanMap.get(span.id)!
    if (span.parent_id && spanMap.has(span.parent_id)) {
      const parent = spanMap.get(span.parent_id)!
      node.depth = parent.depth + 1
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })

  return roots
}

function SpanRow({
  node,
  timeRange,
  expanded,
  onToggle,
  focusSpanName,
  onCopySpan,
  onFocusSpan,
}: {
  node: SpanNode
  timeRange: { min: number; max: number }
  expanded: boolean
  onToggle: () => void
  focusSpanName?: string
  onCopySpan?: (span: Span) => void
  onFocusSpan?: (span: Span) => void
}) {
  const { span } = node
  const hasChildren = node.children.length > 0
  const hasFocus = Boolean(focusSpanName)
  const isFocused = !hasFocus || span.name === focusSpanName

  const startTime = new Date(span.start_time).getTime()
  const endTime = span.end_time ? new Date(span.end_time).getTime() : Date.now()
  const duration = span.duration_ms ?? endTime - startTime

  const totalDuration = timeRange.max - timeRange.min
  const leftPercent = ((startTime - timeRange.min) / totalDuration) * 100
  const widthPercent = Math.max((duration / totalDuration) * 100, 0.5)

  return (
    <div className={clsx('group', hasFocus && !isFocused && 'opacity-45')}>
      <div
        className={clsx(
          'flex items-center py-2 rounded',
          isFocused ? 'hover:bg-dark-800' : 'hover:bg-dark-900/20',
          hasFocus && isFocused && 'bg-primary-900/10 ring-1 ring-primary-900/60'
        )}
      >
        <div
          className="flex items-center gap-1 min-w-[200px] pr-4"
          style={{ paddingLeft: `${node.depth * 20}px` }}
        >
          {hasChildren ? (
            <button onClick={onToggle} className="p-0.5 hover:bg-dark-700 rounded">
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-300" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-300" />
              )}
            </button>
          ) : (
            <span className="w-5" />
          )}
          <span className="text-sm text-muted-100 truncate">{span.name}</span>
          {onCopySpan && (
            <button
              type="button"
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                onCopySpan(span)
              }}
              className="inline-flex items-center p-0.5 rounded hover:bg-dark-700 text-muted-400 hover:text-muted-100"
              title="Copy span JSON"
              aria-label={`Copy span JSON for ${span.name}`}
            >
              <ClipboardCopy className="h-3.5 w-3.5" />
            </button>
          )}
          {onFocusSpan && (
            <button
              type="button"
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                onFocusSpan(span)
              }}
              className="inline-flex items-center p-0.5 rounded hover:bg-dark-700 text-muted-400 hover:text-muted-100"
              title="Focus span in timeline"
              aria-label={`Focus span ${span.name}`}
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="flex-1 relative h-6">
          <div
            className={clsx(
              'absolute h-full rounded',
              SPAN_COLORS[span.span_type as SpanType] || SPAN_COLORS.custom,
              span.status === 'error' && 'ring-2 ring-red-500'
            )}
            style={{
              left: `${leftPercent}%`,
              width: `${widthPercent}%`,
              minWidth: '4px',
            }}
            title={`${span.name} - ${duration.toFixed(0)}ms`}
          />
        </div>

        <div className="min-w-[80px] text-right text-sm text-muted-300 pl-4">
          {duration < 1000 ? `${duration.toFixed(0)}ms` : `${(duration / 1000).toFixed(2)}s`}
        </div>
      </div>

      {expanded &&
        node.children.map((child) => (
          <SpanRowWrapper
            key={child.span.id}
            node={child}
            timeRange={timeRange}
            focusSpanName={focusSpanName}
          />
        ))}
    </div>
  )
}

function SpanRowWrapper({
  node,
  timeRange,
  focusSpanName,
  onCopySpan,
  onFocusSpan,
}: {
  node: SpanNode
  timeRange: { min: number; max: number }
  focusSpanName?: string
  onCopySpan?: (span: Span) => void
  onFocusSpan?: (span: Span) => void
}) {
  const [expanded, setExpanded] = useState(true)
  return (
    <SpanRow
      node={node}
      timeRange={timeRange}
      expanded={expanded}
      onToggle={() => setExpanded(!expanded)}
      focusSpanName={focusSpanName}
      onCopySpan={onCopySpan}
      onFocusSpan={onFocusSpan}
    />
  )
}

export default function SpanTimeline({
  spans,
  focusSpanName,
  onCopySpan,
  onFocusSpan,
}: {
  spans: Span[]
  focusSpanName?: string
  onCopySpan?: (span: Span) => void
  onFocusSpan?: (span: Span) => void
}) {
  const tree = useMemo(() => buildSpanTree(spans), [spans])

  const timeRange = useMemo(() => {
    if (spans.length === 0) return { min: 0, max: 1000 }

    let min = Infinity
    let max = -Infinity

    spans.forEach((span) => {
      const start = new Date(span.start_time).getTime()
      const end = span.end_time ? new Date(span.end_time).getTime() : Date.now()
      min = Math.min(min, start)
      max = Math.max(max, end)
    })

    return { min, max }
  }, [spans])

  if (spans.length === 0) {
    return <p className="text-muted-300 text-sm">No spans recorded yet.</p>
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center text-xs text-muted-400 pb-2 border-b border-dark-700">
        <div className="min-w-[200px]">Span</div>
        <div className="flex-1">Timeline</div>
        <div className="min-w-[80px] text-right">Duration</div>
      </div>
      {tree.map((node) => (
        <SpanRowWrapper
          key={node.span.id}
          node={node}
          timeRange={timeRange}
          focusSpanName={focusSpanName}
          onCopySpan={onCopySpan}
          onFocusSpan={onFocusSpan}
        />
      ))}
      <div className="flex items-center gap-4 pt-4 border-t border-dark-700 text-xs">
        {Object.entries(SPAN_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1">
            <div className={clsx('w-3 h-3 rounded', color)} />
            <span className="text-muted-300">{type}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
