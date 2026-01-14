import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { Span, SpanType } from '@/lib/types'

const SPAN_COLORS: Record<SpanType, string> = {
  llm: 'bg-purple-500',
  tool: 'bg-blue-500',
  agent: 'bg-green-500',
  retrieval: 'bg-yellow-500',
  chain: 'bg-orange-500',
  custom: 'bg-slate-400',
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
}: {
  node: SpanNode
  timeRange: { min: number; max: number }
  expanded: boolean
  onToggle: () => void
}) {
  const { span } = node
  const hasChildren = node.children.length > 0

  const startTime = new Date(span.start_time).getTime()
  const endTime = span.end_time ? new Date(span.end_time).getTime() : Date.now()
  const duration = span.duration_ms ?? endTime - startTime

  const totalDuration = timeRange.max - timeRange.min
  const leftPercent = ((startTime - timeRange.min) / totalDuration) * 100
  const widthPercent = Math.max((duration / totalDuration) * 100, 0.5)

  return (
    <div className="group">
      <div className="flex items-center py-2 hover:bg-slate-50 rounded">
        <div
          className="flex items-center gap-1 min-w-[200px] pr-4"
          style={{ paddingLeft: `${node.depth * 20}px` }}
        >
          {hasChildren ? (
            <button onClick={onToggle} className="p-0.5 hover:bg-slate-200 rounded">
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-slate-500" />
              ) : (
                <ChevronRight className="h-4 w-4 text-slate-500" />
              )}
            </button>
          ) : (
            <span className="w-5" />
          )}
          <span className="text-sm text-slate-700 truncate">{span.name}</span>
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

        <div className="min-w-[80px] text-right text-sm text-slate-500 pl-4">
          {duration < 1000 ? `${duration.toFixed(0)}ms` : `${(duration / 1000).toFixed(2)}s`}
        </div>
      </div>

      {expanded &&
        node.children.map((child) => (
          <SpanRowWrapper key={child.span.id} node={child} timeRange={timeRange} />
        ))}
    </div>
  )
}

function SpanRowWrapper({
  node,
  timeRange,
}: {
  node: SpanNode
  timeRange: { min: number; max: number }
}) {
  const [expanded, setExpanded] = useState(true)
  return (
    <SpanRow
      node={node}
      timeRange={timeRange}
      expanded={expanded}
      onToggle={() => setExpanded(!expanded)}
    />
  )
}

export default function SpanTimeline({ spans }: { spans: Span[] }) {
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
    return <p className="text-slate-500 text-sm">No spans recorded yet.</p>
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center text-xs text-slate-500 pb-2 border-b">
        <div className="min-w-[200px]">Span</div>
        <div className="flex-1">Timeline</div>
        <div className="min-w-[80px] text-right">Duration</div>
      </div>
      {tree.map((node) => (
        <SpanRowWrapper key={node.span.id} node={node} timeRange={timeRange} />
      ))}
      <div className="flex items-center gap-4 pt-4 border-t text-xs">
        {Object.entries(SPAN_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1">
            <div className={clsx('w-3 h-3 rounded', color)} />
            <span className="text-slate-600">{type}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
