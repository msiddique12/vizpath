import { useMemo } from 'react'
import clsx from 'clsx'
import { Span, Trace } from '@/lib/types'

interface TraceComparisonProps {
  traceA: { trace: Trace; spans: Span[] }
  traceB: { trace: Trace; spans: Span[] }
}

interface ComparisonMetric {
  label: string
  valueA: string | number
  valueB: string | number
  diff: number
  unit: string
}

function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatTokens(tokens: number | null | undefined): string {
  if (!tokens) return '-'
  return tokens.toLocaleString()
}

function calculateDiff(a: number, b: number): number {
  if (a === 0 && b === 0) return 0
  if (a === 0) return 100
  return ((b - a) / a) * 100
}

export default function TraceComparison({ traceA, traceB }: TraceComparisonProps) {
  const metrics = useMemo((): ComparisonMetric[] => {
    const durationA = traceA.trace.duration_ms || 0
    const durationB = traceB.trace.duration_ms || 0
    const tokensA = traceA.trace.total_tokens || 0
    const tokensB = traceB.trace.total_tokens || 0

    return [
      {
        label: 'Duration',
        valueA: formatDuration(durationA),
        valueB: formatDuration(durationB),
        diff: calculateDiff(durationA, durationB),
        unit: 'ms',
      },
      {
        label: 'Span Count',
        valueA: traceA.spans.length,
        valueB: traceB.spans.length,
        diff: calculateDiff(traceA.spans.length, traceB.spans.length),
        unit: '',
      },
      {
        label: 'Total Tokens',
        valueA: formatTokens(tokensA),
        valueB: formatTokens(tokensB),
        diff: calculateDiff(tokensA, tokensB),
        unit: '',
      },
    ]
  }, [traceA, traceB])

  const spanTypeComparison = useMemo(() => {
    const countByType = (spans: Span[]) => {
      const counts: Record<string, number> = {}
      spans.forEach((span) => {
        counts[span.span_type] = (counts[span.span_type] || 0) + 1
      })
      return counts
    }

    const countsA = countByType(traceA.spans)
    const countsB = countByType(traceB.spans)
    const allTypes = new Set([...Object.keys(countsA), ...Object.keys(countsB)])

    return Array.from(allTypes).map((type) => ({
      type,
      countA: countsA[type] || 0,
      countB: countsB[type] || 0,
      diff: calculateDiff(countsA[type] || 0, countsB[type] || 0),
    }))
  }, [traceA, traceB])

  const timelineComparison = useMemo(() => {
    const getSpansByName = (spans: Span[]) => {
      const map: Record<string, Span[]> = {}
      spans.forEach((span) => {
        if (!map[span.name]) map[span.name] = []
        map[span.name].push(span)
      })
      return map
    }

    const spansA = getSpansByName(traceA.spans)
    const spansB = getSpansByName(traceB.spans)
    const allNames = new Set([...Object.keys(spansA), ...Object.keys(spansB)])

    return Array.from(allNames)
      .map((name) => {
        const avgDuration = (spans: Span[]) => {
          if (!spans || spans.length === 0) return 0
          return spans.reduce((sum, s) => sum + (s.duration_ms || 0), 0) / spans.length
        }
        const avgA = avgDuration(spansA[name])
        const avgB = avgDuration(spansB[name])

        return {
          name,
          avgDurationA: avgA,
          avgDurationB: avgB,
          countA: spansA[name]?.length || 0,
          countB: spansB[name]?.length || 0,
          diff: calculateDiff(avgA, avgB),
        }
      })
      .sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff))
      .slice(0, 10)
  }, [traceA, traceB])

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-1" />
        <div className="text-center">
          <p className="text-sm font-medium text-slate-900 truncate">{traceA.trace.name}</p>
          <p className="text-xs text-slate-500">Trace A</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-slate-900 truncate">{traceB.trace.name}</p>
          <p className="text-xs text-slate-500">Trace B</p>
        </div>
      </div>

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-50">
            <tr>
              <th className="text-left text-xs font-medium text-slate-500 px-4 py-2">Metric</th>
              <th className="text-center text-xs font-medium text-slate-500 px-4 py-2">Trace A</th>
              <th className="text-center text-xs font-medium text-slate-500 px-4 py-2">Trace B</th>
              <th className="text-center text-xs font-medium text-slate-500 px-4 py-2">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {metrics.map((metric) => (
              <tr key={metric.label}>
                <td className="px-4 py-3 text-sm text-slate-700">{metric.label}</td>
                <td className="px-4 py-3 text-sm text-slate-900 text-center">{metric.valueA}</td>
                <td className="px-4 py-3 text-sm text-slate-900 text-center">{metric.valueB}</td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={clsx(
                      'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
                      metric.diff === 0
                        ? 'bg-slate-100 text-slate-600'
                        : metric.diff < 0
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                    )}
                  >
                    {metric.diff === 0
                      ? 'No change'
                      : `${metric.diff > 0 ? '+' : ''}${metric.diff.toFixed(1)}%`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-3">Span Type Distribution</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {spanTypeComparison.map(({ type, countA, countB, diff }) => (
            <div key={type} className="bg-slate-50 rounded-lg p-3">
              <p className="text-sm font-medium text-slate-900 capitalize">{type}</p>
              <div className="mt-2 flex items-center justify-between text-xs">
                <span className="text-slate-500">A: {countA}</span>
                <span
                  className={clsx(
                    'px-1.5 py-0.5 rounded',
                    diff === 0
                      ? 'bg-slate-200 text-slate-600'
                      : diff < 0
                        ? 'bg-green-100 text-green-700'
                        : 'bg-red-100 text-red-700'
                  )}
                >
                  {diff === 0 ? '=' : diff > 0 ? `+${diff.toFixed(0)}%` : `${diff.toFixed(0)}%`}
                </span>
                <span className="text-slate-500">B: {countB}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {timelineComparison.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-slate-700 mb-3">
            Top Performance Differences by Span
          </h4>
          <div className="space-y-2">
            {timelineComparison.map(({ name, avgDurationA, avgDurationB, diff }) => (
              <div key={name} className="flex items-center gap-4 py-2 border-b border-slate-100">
                <span className="text-sm text-slate-700 truncate flex-1">{name}</span>
                <span className="text-xs text-slate-500 w-20 text-right">
                  {formatDuration(avgDurationA)}
                </span>
                <div className="w-24 flex justify-center">
                  <span
                    className={clsx(
                      'px-2 py-0.5 rounded text-xs font-medium',
                      diff === 0
                        ? 'bg-slate-100 text-slate-600'
                        : diff < 0
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                    )}
                  >
                    {diff === 0 ? '=' : `${diff > 0 ? '+' : ''}${diff.toFixed(0)}%`}
                  </span>
                </div>
                <span className="text-xs text-slate-500 w-20 text-left">
                  {formatDuration(avgDurationB)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
