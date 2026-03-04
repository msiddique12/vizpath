import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { AlertTriangle, Check, Copy, Loader2, TrendingDown, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import { IntelligenceComparison } from '@/lib/api'
import { Span, Trace } from '@/lib/types'

interface TraceComparisonProps {
  traceA: { trace: Trace; spans: Span[] }
  traceB: { trace: Trace; spans: Span[] }
  intelligenceCompare?: IntelligenceComparison
  intelligenceCompareLoading?: boolean
}

interface ComparisonMetric {
  label: string
  valueA: string | number
  valueB: string | number
  diff: number
  unit: string
}

interface SpanDrillDownStats {
  count: number
  avgDurationMs: number
  p95DurationMs: number
  maxDurationMs: number
  errorCount: number
}

type SeverityLevel = 'critical' | 'high' | 'medium' | 'low'

interface ChangeReasonGroup {
  key: string
  title: string
  severity: SeverityLevel
  signals: NonNullable<IntelligenceComparison['signals']>
  impactedMetrics: string[]
}

interface GuardrailConfig {
  maxLatencyRegressionPct: number
  maxTokenRegressionPct: number
  maxCostRegressionPct: number
  maxErrorIncrease: number
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

function severityRank(severity: SeverityLevel): number {
  const rank: Record<SeverityLevel, number> = {
    critical: 4,
    high: 3,
    medium: 2,
    low: 1,
  }
  return rank[severity]
}

function kindTitle(kind: string): string {
  const map: Record<string, string> = {
    performance: 'Performance Changes',
    reliability: 'Reliability Changes',
    efficiency: 'Efficiency Changes',
    cost: 'Cost Changes',
    complexity: 'Complexity Changes',
  }
  return map[kind] || `${kind.charAt(0).toUpperCase()}${kind.slice(1)} Changes`
}

function getSpanDrillDownStats(spans: Span[], spanName: string): SpanDrillDownStats {
  const matching = spans.filter((span) => span.name === spanName)
  if (matching.length === 0) {
    return { count: 0, avgDurationMs: 0, p95DurationMs: 0, maxDurationMs: 0, errorCount: 0 }
  }

  const durations = matching
    .map((span) => span.duration_ms || 0)
    .filter((duration) => duration >= 0)
    .sort((a, b) => a - b)
  const totalDuration = durations.reduce((sum, duration) => sum + duration, 0)
  const p95Index = Math.min(durations.length - 1, Math.floor(durations.length * 0.95))

  return {
    count: matching.length,
    avgDurationMs: totalDuration / durations.length,
    p95DurationMs: durations[p95Index] || 0,
    maxDurationMs: durations[durations.length - 1] || 0,
    errorCount: matching.filter((span) => span.status === 'error').length,
  }
}

export default function TraceComparison({
  traceA,
  traceB,
  intelligenceCompare,
  intelligenceCompareLoading = false,
}: TraceComparisonProps) {
  const [selectedSpanName, setSelectedSpanName] = useState<string | null>(null)
  const [copiedReport, setCopiedReport] = useState(false)
  const [guardrails, setGuardrails] = useState<GuardrailConfig>({
    maxLatencyRegressionPct: 20,
    maxTokenRegressionPct: 25,
    maxCostRegressionPct: 20,
    maxErrorIncrease: 0,
  })

  useEffect(() => {
    const saved = localStorage.getItem('compare_guardrails_v1')
    if (!saved) return
    try {
      const parsed = JSON.parse(saved)
      setGuardrails((prev) => ({
        maxLatencyRegressionPct: Number(parsed.maxLatencyRegressionPct ?? prev.maxLatencyRegressionPct),
        maxTokenRegressionPct: Number(parsed.maxTokenRegressionPct ?? prev.maxTokenRegressionPct),
        maxCostRegressionPct: Number(parsed.maxCostRegressionPct ?? prev.maxCostRegressionPct),
        maxErrorIncrease: Number(parsed.maxErrorIncrease ?? prev.maxErrorIncrease),
      }))
    } catch {
      // Ignore malformed stored values.
    }
  }, [])

  useEffect(() => {
    localStorage.setItem('compare_guardrails_v1', JSON.stringify(guardrails))
  }, [guardrails])

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

  const selectedSpanStats = useMemo(() => {
    if (!selectedSpanName) return null
    return {
      traceA: getSpanDrillDownStats(traceA.spans, selectedSpanName),
      traceB: getSpanDrillDownStats(traceB.spans, selectedSpanName),
    }
  }, [selectedSpanName, traceA.spans, traceB.spans])

  const reasonGroups = useMemo((): ChangeReasonGroup[] => {
    if (!intelligenceCompare) return []

    const groups = new Map<string, ChangeReasonGroup>()
    const metricByKind: Record<string, string[]> = {
      performance: ['duration_ms'],
      reliability: ['error_count'],
      efficiency: ['total_tokens'],
      cost: ['total_cost'],
      complexity: ['span_count', 'llm_calls', 'tool_calls'],
    }

    intelligenceCompare.signals.forEach((signal) => {
      const current = groups.get(signal.kind)
      if (!current) {
        groups.set(signal.kind, {
          key: signal.kind,
          title: kindTitle(signal.kind),
          severity: signal.severity,
          signals: [signal],
          impactedMetrics: [],
        })
      } else {
        current.signals.push(signal)
        if (severityRank(signal.severity) > severityRank(current.severity)) {
          current.severity = signal.severity
        }
      }
    })

    for (const group of groups.values()) {
      const candidateMetrics = metricByKind[group.key] || []
      group.impactedMetrics = intelligenceCompare.metrics
        .filter(
          (metric) =>
            candidateMetrics.includes(metric.name) &&
            (metric.direction === 'regressed' || metric.direction === 'improved')
        )
        .map((metric) => metric.label)
    }

    return Array.from(groups.values()).sort(
      (a, b) => severityRank(b.severity) - severityRank(a.severity)
    )
  }, [intelligenceCompare])

  const guardrailChecks = useMemo(() => {
    if (!intelligenceCompare) return null

    const findMetric = (name: string) => intelligenceCompare.metrics.find((metric) => metric.name === name)
    const latency = findMetric('duration_ms')
    const tokens = findMetric('total_tokens')
    const cost = findMetric('total_cost')
    const errors = findMetric('error_count')

    const checks = [
      {
        key: 'latency',
        label: `Latency regression <= ${guardrails.maxLatencyRegressionPct}%`,
        actual: latency?.delta_pct ?? 0,
        pass: (latency?.delta_pct ?? 0) <= guardrails.maxLatencyRegressionPct,
        renderValue: `${(latency?.delta_pct ?? 0).toFixed(1)}%`,
      },
      {
        key: 'tokens',
        label: `Token regression <= ${guardrails.maxTokenRegressionPct}%`,
        actual: tokens?.delta_pct ?? 0,
        pass: (tokens?.delta_pct ?? 0) <= guardrails.maxTokenRegressionPct,
        renderValue: `${(tokens?.delta_pct ?? 0).toFixed(1)}%`,
      },
      {
        key: 'cost',
        label: `Cost regression <= ${guardrails.maxCostRegressionPct}%`,
        actual: cost?.delta_pct ?? 0,
        pass: (cost?.delta_pct ?? 0) <= guardrails.maxCostRegressionPct,
        renderValue: `${(cost?.delta_pct ?? 0).toFixed(1)}%`,
      },
      {
        key: 'errors',
        label: `Error increase <= ${guardrails.maxErrorIncrease}`,
        actual: errors?.delta ?? 0,
        pass: (errors?.delta ?? 0) <= guardrails.maxErrorIncrease,
        renderValue: `${(errors?.delta ?? 0).toFixed(0)}`,
      },
    ]

    return {
      checks,
      pass: checks.every((check) => check.pass),
    }
  }, [guardrails, intelligenceCompare])

  const compareReport = useMemo(() => {
    if (!intelligenceCompare || !guardrailChecks) return null
    const lines = [
      `# Vizpath Compare Report`,
      ``,
      `- Trace A: ${traceA.trace.name} (${traceA.trace.id})`,
      `- Trace B: ${traceB.trace.name} (${traceB.trace.id})`,
      `- Status: ${intelligenceCompare.summary.status}`,
      `- Regression score: ${intelligenceCompare.summary.regression_score}`,
      `- Guardrails: ${guardrailChecks.pass ? "PASS" : "FAIL"}`,
      ``,
      `## Top Signals`,
    ]

    const topSignals = intelligenceCompare.signals.slice(0, 5)
    if (topSignals.length === 0) {
      lines.push(`- No major signals detected.`)
    } else {
      for (const signal of topSignals) {
        lines.push(`- [${signal.severity}] ${signal.title}: ${signal.detail}`)
      }
    }

    lines.push(``, `## Top Actions`)
    if (intelligenceCompare.top_actions.length === 0) {
      lines.push(`- None`)
    } else {
      for (const action of intelligenceCompare.top_actions) {
        lines.push(`- ${action}`)
      }
    }

    lines.push(``, `## Guardrail Checks`)
    for (const check of guardrailChecks.checks) {
      lines.push(`- ${check.pass ? "PASS" : "FAIL"} ${check.label} (actual: ${check.renderValue})`)
    }

    return lines.join('\n')
  }, [guardrailChecks, intelligenceCompare, traceA.trace.id, traceA.trace.name, traceB.trace.id, traceB.trace.name])

  return (
    <div className="space-y-6">
      <div className="border border-dark-700 rounded-lg p-4 bg-dark-800/60">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-sm font-medium text-muted-100">Intelligence Delta</h4>
            <p className="text-xs text-muted-400 mt-1">
              Deterministic regression signals and recommended next actions.
            </p>
          </div>
          {intelligenceCompareLoading ? (
            <Loader2 className="h-4 w-4 text-primary-500 animate-spin mt-1" />
          ) : (
            intelligenceCompare && (
              <div className="flex items-center gap-2">
                <span
                  className={clsx(
                    'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
                    intelligenceCompare.summary.status === 'regressed' &&
                      'bg-red-900/50 text-red-400',
                    intelligenceCompare.summary.status === 'mixed' &&
                      'bg-yellow-900/50 text-yellow-300',
                    intelligenceCompare.summary.status === 'improved' &&
                      'bg-green-900/50 text-green-400',
                    intelligenceCompare.summary.status === 'neutral' &&
                      'bg-dark-700 text-muted-300'
                  )}
                >
                  {intelligenceCompare.summary.status.toUpperCase()} · Score{' '}
                  {intelligenceCompare.summary.regression_score}
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    if (!compareReport) return
                    await navigator.clipboard.writeText(compareReport)
                    setCopiedReport(true)
                    setTimeout(() => setCopiedReport(false), 1400)
                  }}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-dark-700 bg-dark-900 text-muted-300 hover:text-muted-100 hover:bg-dark-800"
                >
                  {copiedReport ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
                  {copiedReport ? 'Copied report' : 'Copy report'}
                </button>
              </div>
            )
          )}
        </div>

        {intelligenceCompare && intelligenceCompare.signals.length > 0 ? (
          <div className="mt-4 space-y-2">
            {intelligenceCompare.signals.slice(0, 3).map((signal) => (
              <div key={signal.id} className="rounded border border-dark-700 p-3">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-yellow-400" />
                  <p className="text-sm text-muted-100">{signal.title}</p>
                  <span
                    className={clsx(
                      'ml-auto px-1.5 py-0.5 rounded text-[10px] font-medium uppercase',
                      signal.severity === 'critical' && 'bg-red-900/60 text-red-300',
                      signal.severity === 'high' && 'bg-orange-900/60 text-orange-300',
                      signal.severity === 'medium' && 'bg-yellow-900/60 text-yellow-300',
                      signal.severity === 'low' && 'bg-green-900/50 text-green-400'
                    )}
                  >
                    {signal.severity}
                  </span>
                </div>
                <p className="text-xs text-muted-400 mt-1">{signal.detail}</p>
                <p className="text-xs text-muted-300 mt-2">{signal.recommendation}</p>
              </div>
            ))}
          </div>
        ) : (
          !intelligenceCompareLoading && (
            <p className="mt-4 text-xs text-muted-400">
              No major regression signals detected for this pair.
            </p>
          )
        )}

        {intelligenceCompare && intelligenceCompare.top_actions.length > 0 && (
          <div className="mt-4 grid md:grid-cols-3 gap-2">
            {intelligenceCompare.top_actions.map((action, index) => (
              <div key={`${action}-${index}`} className="rounded bg-dark-900 border border-dark-700 p-2">
                <p className="text-xs text-muted-300">{action}</p>
              </div>
            ))}
          </div>
        )}

        {reasonGroups.length > 0 && (
          <div className="mt-4">
            <h5 className="text-xs font-medium text-muted-200 mb-2 uppercase tracking-wide">
              Change Reasons
            </h5>
            <div className="space-y-2">
              {reasonGroups.map((group) => (
                <details key={group.key} className="rounded border border-dark-700 bg-dark-900/70 p-2">
                  <summary className="flex cursor-pointer list-none items-center gap-2">
                    <span
                      className={clsx(
                        'px-1.5 py-0.5 rounded text-[10px] font-medium uppercase',
                        group.severity === 'critical' && 'bg-red-900/60 text-red-300',
                        group.severity === 'high' && 'bg-orange-900/60 text-orange-300',
                        group.severity === 'medium' && 'bg-yellow-900/60 text-yellow-300',
                        group.severity === 'low' && 'bg-green-900/50 text-green-400'
                      )}
                    >
                      {group.severity}
                    </span>
                    <span className="text-xs text-muted-100">{group.title}</span>
                    <span className="ml-auto text-[11px] text-muted-400">
                      {group.signals.length} signal{group.signals.length === 1 ? '' : 's'}
                    </span>
                  </summary>
                  <div className="pt-2 space-y-2">
                    {group.impactedMetrics.length > 0 && (
                      <p className="text-[11px] text-muted-400">
                        Impacted metrics: {group.impactedMetrics.join(', ')}
                      </p>
                    )}
                    {group.signals.map((signal) => (
                      <div key={signal.id} className="rounded border border-dark-700 p-2">
                        <p className="text-xs text-muted-100">{signal.title}</p>
                        <p className="text-xs text-muted-400 mt-1">{signal.detail}</p>
                        <p className="text-xs text-muted-300 mt-1">{signal.recommendation}</p>
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}

        {guardrailChecks && (
          <div className="mt-4 rounded border border-dark-700 bg-dark-900/70 p-3">
            <div className="flex items-center justify-between gap-2">
              <h5 className="text-xs font-medium text-muted-200 uppercase tracking-wide">
                Regression Guardrails
              </h5>
              <span
                className={clsx(
                  'text-[11px] px-2 py-0.5 rounded font-medium',
                  guardrailChecks.pass
                    ? 'bg-green-900/50 text-green-400'
                    : 'bg-red-900/50 text-red-400'
                )}
              >
                {guardrailChecks.pass ? 'PASS' : 'FAIL'}
              </span>
            </div>

            <div className="mt-3 grid md:grid-cols-4 gap-2">
              <input
                type="number"
                min={0}
                value={guardrails.maxLatencyRegressionPct}
                onChange={(event) =>
                  setGuardrails((prev) => ({
                    ...prev,
                    maxLatencyRegressionPct: Number(event.target.value || 0),
                  }))
                }
                className="bg-dark-800 border border-dark-700 rounded px-2 py-1 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                aria-label="Max latency regression percent"
                placeholder="Max latency %"
              />
              <input
                type="number"
                min={0}
                value={guardrails.maxTokenRegressionPct}
                onChange={(event) =>
                  setGuardrails((prev) => ({
                    ...prev,
                    maxTokenRegressionPct: Number(event.target.value || 0),
                  }))
                }
                className="bg-dark-800 border border-dark-700 rounded px-2 py-1 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                aria-label="Max token regression percent"
                placeholder="Max token %"
              />
              <input
                type="number"
                min={0}
                value={guardrails.maxCostRegressionPct}
                onChange={(event) =>
                  setGuardrails((prev) => ({
                    ...prev,
                    maxCostRegressionPct: Number(event.target.value || 0),
                  }))
                }
                className="bg-dark-800 border border-dark-700 rounded px-2 py-1 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                aria-label="Max cost regression percent"
                placeholder="Max cost %"
              />
              <input
                type="number"
                min={0}
                value={guardrails.maxErrorIncrease}
                onChange={(event) =>
                  setGuardrails((prev) => ({
                    ...prev,
                    maxErrorIncrease: Number(event.target.value || 0),
                  }))
                }
                className="bg-dark-800 border border-dark-700 rounded px-2 py-1 text-xs text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                aria-label="Max error increase"
                placeholder="Max errors"
              />
            </div>

            <div className="mt-3 space-y-1.5">
              {guardrailChecks.checks.map((check) => (
                <div key={check.key} className="flex items-center justify-between text-xs">
                  <span className="text-muted-300">{check.label}</span>
                  <span
                    className={clsx(
                      'px-1.5 py-0.5 rounded font-medium',
                      check.pass ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
                    )}
                  >
                    {check.renderValue}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-1" />
        <div className="text-center">
          <p className="text-sm font-medium text-muted-100 truncate">{traceA.trace.name}</p>
          <p className="text-xs text-muted-400">Trace A</p>
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-muted-100 truncate">{traceB.trace.name}</p>
          <p className="text-xs text-muted-400">Trace B</p>
        </div>
      </div>

      <div className="border border-dark-700 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-dark-800">
            <tr>
              <th className="text-left text-xs font-medium text-muted-400 px-4 py-2">Metric</th>
              <th className="text-center text-xs font-medium text-muted-400 px-4 py-2">Trace A</th>
              <th className="text-center text-xs font-medium text-muted-400 px-4 py-2">Trace B</th>
              <th className="text-center text-xs font-medium text-muted-400 px-4 py-2">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-dark-700">
            {metrics.map((metric) => (
              <tr key={metric.label}>
                <td className="px-4 py-3 text-sm text-muted-200">{metric.label}</td>
                <td className="px-4 py-3 text-sm text-muted-100 text-center">{metric.valueA}</td>
                <td className="px-4 py-3 text-sm text-muted-100 text-center">{metric.valueB}</td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={clsx(
                      'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
                      metric.diff === 0
                        ? 'bg-dark-700 text-muted-300'
                        : metric.diff < 0
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-red-900/50 text-red-400'
                    )}
                  >
                    {metric.diff < 0 ? (
                      <TrendingDown className="h-3 w-3 mr-1" />
                    ) : metric.diff > 0 ? (
                      <TrendingUp className="h-3 w-3 mr-1" />
                    ) : null}
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
        <h4 className="text-sm font-medium text-muted-200 mb-3">Span Type Distribution</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {spanTypeComparison.map(({ type, countA, countB, diff }) => (
            <div key={type} className="bg-dark-800 rounded-lg p-3">
              <p className="text-sm font-medium text-muted-100 capitalize">{type}</p>
              <div className="mt-2 flex items-center justify-between text-xs">
                <span className="text-muted-400">A: {countA}</span>
                <span
                  className={clsx(
                    'px-1.5 py-0.5 rounded',
                    diff === 0
                      ? 'bg-dark-700 text-muted-300'
                      : diff < 0
                        ? 'bg-green-900/50 text-green-400'
                        : 'bg-red-900/50 text-red-400'
                  )}
                >
                  {diff === 0 ? '=' : diff > 0 ? `+${diff.toFixed(0)}%` : `${diff.toFixed(0)}%`}
                </span>
                <span className="text-muted-400">B: {countB}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {timelineComparison.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-medium text-muted-200">Top Performance Differences by Span</h4>
            <p className="text-xs text-muted-500">Click a row to inspect deeper.</p>
          </div>
          <div className="space-y-2">
            {timelineComparison.map(({ name, avgDurationA, avgDurationB, diff }) => (
              <button
                key={name}
                type="button"
                onClick={() => setSelectedSpanName(name)}
                className={clsx(
                  'w-full flex items-center gap-4 py-2 border-b border-dark-700 text-left hover:bg-dark-800 rounded px-1',
                  selectedSpanName === name && 'bg-dark-800'
                )}
              >
                <span className="text-sm text-muted-200 truncate flex-1">{name}</span>
                <span className="text-xs text-muted-400 w-20 text-right">
                  {formatDuration(avgDurationA)}
                </span>
                <div className="w-24 flex justify-center">
                  <span
                    className={clsx(
                      'px-2 py-0.5 rounded text-xs font-medium',
                      diff === 0
                        ? 'bg-dark-700 text-muted-300'
                        : diff < 0
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-red-900/50 text-red-400'
                    )}
                  >
                    {diff === 0 ? '=' : `${diff > 0 ? '+' : ''}${diff.toFixed(0)}%`}
                  </span>
                </div>
                <span className="text-xs text-muted-400 w-20 text-left">
                  {formatDuration(avgDurationB)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {selectedSpanName && selectedSpanStats && (
        <div className="border border-dark-700 rounded-lg p-4 bg-dark-800/40">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 className="text-sm font-medium text-muted-100">Span Deep Dive</h4>
              <p className="text-xs text-muted-400 mt-1">{selectedSpanName}</p>
            </div>
            <button
              type="button"
              onClick={() => setSelectedSpanName(null)}
              className="text-xs text-muted-400 hover:text-muted-200"
            >
              Clear
            </button>
          </div>

          <div className="mt-4 grid md:grid-cols-2 gap-3">
            <div className="rounded border border-dark-700 p-3">
              <p className="text-xs text-muted-400 mb-2">Trace A</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <p className="text-muted-300">Calls: {selectedSpanStats.traceA.count}</p>
                <p className="text-muted-300">Errors: {selectedSpanStats.traceA.errorCount}</p>
                <p className="text-muted-300">
                  Avg: {formatDuration(selectedSpanStats.traceA.avgDurationMs)}
                </p>
                <p className="text-muted-300">
                  P95: {formatDuration(selectedSpanStats.traceA.p95DurationMs)}
                </p>
                <p className="text-muted-300">
                  Max: {formatDuration(selectedSpanStats.traceA.maxDurationMs)}
                </p>
              </div>
              <Link
                to={`/traces/${traceA.trace.id}?view=timeline&span_name=${encodeURIComponent(selectedSpanName)}`}
                className="inline-flex mt-3 text-xs text-primary-500 hover:text-primary-400"
              >
                Open Trace A timeline
              </Link>
            </div>

            <div className="rounded border border-dark-700 p-3">
              <p className="text-xs text-muted-400 mb-2">Trace B</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <p className="text-muted-300">Calls: {selectedSpanStats.traceB.count}</p>
                <p className="text-muted-300">Errors: {selectedSpanStats.traceB.errorCount}</p>
                <p className="text-muted-300">
                  Avg: {formatDuration(selectedSpanStats.traceB.avgDurationMs)}
                </p>
                <p className="text-muted-300">
                  P95: {formatDuration(selectedSpanStats.traceB.p95DurationMs)}
                </p>
                <p className="text-muted-300">
                  Max: {formatDuration(selectedSpanStats.traceB.maxDurationMs)}
                </p>
              </div>
              <Link
                to={`/traces/${traceB.trace.id}?view=timeline&span_name=${encodeURIComponent(selectedSpanName)}`}
                className="inline-flex mt-3 text-xs text-primary-500 hover:text-primary-400"
              >
                Open Trace B timeline
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
