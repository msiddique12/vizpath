import { useMemo } from 'react'
import clsx from 'clsx'
import { Span, SpanType } from '@/lib/types'

interface HeatmapViewProps {
  spans: Span[]
}

const SPAN_TYPES: SpanType[] = ['llm', 'tool', 'agent', 'retrieval', 'chain', 'custom']
const DURATION_BUCKETS = [
  { label: '<10ms', max: 10 },
  { label: '10-50ms', max: 50 },
  { label: '50-100ms', max: 100 },
  { label: '100-500ms', max: 500 },
  { label: '500ms-1s', max: 1000 },
  { label: '1-5s', max: 5000 },
  { label: '>5s', max: Infinity },
]

function getIntensityClass(count: number, maxCount: number): string {
  if (count === 0) return 'bg-slate-50'
  const ratio = count / maxCount
  if (ratio < 0.2) return 'bg-primary-100'
  if (ratio < 0.4) return 'bg-primary-200'
  if (ratio < 0.6) return 'bg-primary-300'
  if (ratio < 0.8) return 'bg-primary-400'
  return 'bg-primary-500'
}

export default function HeatmapView({ spans }: HeatmapViewProps) {
  const { heatmapData, maxCount, stats } = useMemo(() => {
    const data: Record<string, Record<string, number>> = {}
    let max = 0

    SPAN_TYPES.forEach((type) => {
      data[type] = {}
      DURATION_BUCKETS.forEach((bucket) => {
        data[type][bucket.label] = 0
      })
    })

    spans.forEach((span) => {
      const type = SPAN_TYPES.includes(span.span_type as SpanType)
        ? span.span_type
        : 'custom'
      const duration = span.duration_ms || 0

      for (const bucket of DURATION_BUCKETS) {
        if (duration < bucket.max) {
          data[type][bucket.label]++
          max = Math.max(max, data[type][bucket.label])
          break
        }
      }
    })

    const typeStats = SPAN_TYPES.map((type) => {
      const typeSpans = spans.filter((s) =>
        (SPAN_TYPES.includes(s.span_type as SpanType) ? s.span_type : 'custom') === type
      )
      const durations = typeSpans.map((s) => s.duration_ms || 0)
      const total = durations.reduce((a, b) => a + b, 0)
      const avg = typeSpans.length > 0 ? total / typeSpans.length : 0
      const maxDuration = Math.max(...durations, 0)
      return { type, count: typeSpans.length, avg, max: maxDuration }
    }).filter((s) => s.count > 0)

    return { heatmapData: data, maxCount: max, stats: typeStats }
  }, [spans])

  if (spans.length === 0) {
    return <p className="text-slate-500 text-sm">No spans to analyze.</p>
  }

  return (
    <div className="space-y-6">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="text-left text-xs font-medium text-slate-500 pb-2 pr-4">
                Type
              </th>
              {DURATION_BUCKETS.map((bucket) => (
                <th
                  key={bucket.label}
                  className="text-center text-xs font-medium text-slate-500 pb-2 px-1"
                >
                  {bucket.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SPAN_TYPES.map((type) => {
              const hasData = Object.values(heatmapData[type]).some((v) => v > 0)
              if (!hasData) return null

              return (
                <tr key={type}>
                  <td className="text-sm text-slate-700 py-1 pr-4 capitalize">
                    {type}
                  </td>
                  {DURATION_BUCKETS.map((bucket) => {
                    const count = heatmapData[type][bucket.label]
                    return (
                      <td key={bucket.label} className="px-1 py-1">
                        <div
                          className={clsx(
                            'w-full h-8 rounded flex items-center justify-center text-xs transition-colors',
                            getIntensityClass(count, maxCount),
                            count > 0 && maxCount > 0 && count / maxCount > 0.4
                              ? 'text-white'
                              : 'text-slate-600'
                          )}
                          title={`${type}: ${count} spans in ${bucket.label}`}
                        >
                          {count > 0 ? count : ''}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t pt-4">
        <h4 className="text-sm font-medium text-slate-700 mb-3">Statistics by Type</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {stats.map(({ type, count, avg, max }) => (
            <div key={type} className="bg-slate-50 rounded-lg p-3">
              <p className="text-sm font-medium text-slate-900 capitalize">{type}</p>
              <div className="mt-1 space-y-1 text-xs text-slate-500">
                <p>{count} spans</p>
                <p>Avg: {avg < 1000 ? `${avg.toFixed(0)}ms` : `${(avg / 1000).toFixed(2)}s`}</p>
                <p>Max: {max < 1000 ? `${max.toFixed(0)}ms` : `${(max / 1000).toFixed(2)}s`}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span>Intensity:</span>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 rounded bg-slate-50 border" />
          <span>0</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-4 h-4 rounded bg-primary-100" />
          <div className="w-4 h-4 rounded bg-primary-200" />
          <div className="w-4 h-4 rounded bg-primary-300" />
          <div className="w-4 h-4 rounded bg-primary-400" />
          <div className="w-4 h-4 rounded bg-primary-500" />
          <span>High</span>
        </div>
      </div>
    </div>
  )
}
