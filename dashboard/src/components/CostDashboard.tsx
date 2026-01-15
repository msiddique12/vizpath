import { useMemo } from 'react'
import clsx from 'clsx'
import { Span, SpanType } from '@/lib/types'

interface CostDashboardProps {
  spans: Span[]
  totalCost?: number
}

const COST_PER_1K_TOKENS = {
  'gpt-4': 0.03,
  'gpt-4-turbo': 0.01,
  'gpt-4o': 0.005,
  'gpt-4o-mini': 0.00015,
  'gpt-3.5-turbo': 0.0005,
  'claude-3-opus': 0.015,
  'claude-3-sonnet': 0.003,
  'claude-3-haiku': 0.00025,
  'claude-3.5-sonnet': 0.003,
  default: 0.002,
}

function estimateCost(tokens: number, model?: string): number {
  const rate = model && model in COST_PER_1K_TOKENS
    ? COST_PER_1K_TOKENS[model as keyof typeof COST_PER_1K_TOKENS]
    : COST_PER_1K_TOKENS.default
  return (tokens / 1000) * rate
}

function formatCost(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(3)}`
  return `$${cost.toFixed(2)}`
}

export default function CostDashboard({ spans, totalCost }: CostDashboardProps) {
  const costAnalysis = useMemo(() => {
    const byType: Record<string, { count: number; tokens: number; cost: number; duration: number }> = {}
    const topCostlySpans: Array<{ span: Span; cost: number }> = []

    spans.forEach((span) => {
      const tokens = span.token_count || 0
      const model = span.attributes?.model as string | undefined
      const cost = estimateCost(tokens, model)
      const duration = span.duration_ms || 0

      if (!byType[span.span_type]) {
        byType[span.span_type] = { count: 0, tokens: 0, cost: 0, duration: 0 }
      }
      byType[span.span_type].count++
      byType[span.span_type].tokens += tokens
      byType[span.span_type].cost += cost
      byType[span.span_type].duration += duration

      if (tokens > 0) {
        topCostlySpans.push({ span, cost })
      }
    })

    const totalTokens = Object.values(byType).reduce((sum, t) => sum + t.tokens, 0)
    const estimatedTotal = Object.values(byType).reduce((sum, t) => sum + t.cost, 0)

    const typeStats = Object.entries(byType)
      .map(([type, stats]) => ({
        type: type as SpanType,
        ...stats,
        avgCost: stats.count > 0 ? stats.cost / stats.count : 0,
        costPerMs: stats.duration > 0 ? (stats.cost / stats.duration) * 1000 : 0,
      }))
      .sort((a, b) => b.cost - a.cost)

    topCostlySpans.sort((a, b) => b.cost - a.cost)

    return {
      byType: typeStats,
      totalTokens,
      estimatedTotal: totalCost ?? estimatedTotal,
      topCostlySpans: topCostlySpans.slice(0, 5),
    }
  }, [spans, totalCost])

  const maxCost = Math.max(...costAnalysis.byType.map((t) => t.cost), 0.001)

  if (costAnalysis.totalTokens === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-slate-500 text-sm">No token usage data available for cost analysis.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-50 rounded-lg p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Total Cost</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {formatCost(costAnalysis.estimatedTotal)}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Total Tokens</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {costAnalysis.totalTokens.toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">LLM Calls</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {costAnalysis.byType.find((t) => t.type === 'llm')?.count || 0}
          </p>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-3">Cost by Span Type</h4>
        <div className="space-y-3">
          {costAnalysis.byType.map(({ type, count, tokens, cost, duration }) => (
            <div key={type} className="flex items-center gap-4">
              <span className="w-24 text-sm text-slate-700 capitalize">{type}</span>
              <div className="flex-1">
                <div className="h-6 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className={clsx(
                      'h-full rounded-full',
                      type === 'llm' ? 'bg-primary-500' :
                      type === 'tool' ? 'bg-amber-500' :
                      type === 'agent' ? 'bg-emerald-500' :
                      type === 'retrieval' ? 'bg-cyan-500' :
                      'bg-slate-400'
                    )}
                    style={{ width: `${(cost / maxCost) * 100}%` }}
                  />
                </div>
              </div>
              <div className="w-32 text-right">
                <span className="text-sm font-medium text-slate-900">{formatCost(cost)}</span>
                <span className="text-xs text-slate-500 ml-2">({tokens.toLocaleString()} tok)</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {costAnalysis.topCostlySpans.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-slate-700 mb-3">Most Expensive Spans</h4>
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left text-xs font-medium text-slate-500 px-4 py-2">Name</th>
                  <th className="text-left text-xs font-medium text-slate-500 px-4 py-2">Type</th>
                  <th className="text-right text-xs font-medium text-slate-500 px-4 py-2">Tokens</th>
                  <th className="text-right text-xs font-medium text-slate-500 px-4 py-2">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {costAnalysis.topCostlySpans.map(({ span, cost }) => (
                  <tr key={span.id}>
                    <td className="px-4 py-2 text-sm text-slate-900 truncate max-w-xs">
                      {span.name}
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-flex px-2 py-0.5 text-xs rounded-full bg-slate-100 text-slate-600 capitalize">
                        {span.span_type}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-sm text-slate-600 text-right">
                      {(span.token_count || 0).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-sm font-medium text-slate-900 text-right">
                      {formatCost(cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div>
        <h4 className="text-sm font-medium text-slate-700 mb-3">Cost Efficiency</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {costAnalysis.byType
            .filter((t) => t.duration > 0 && t.cost > 0)
            .map(({ type, cost, duration, avgCost }) => (
              <div key={type} className="bg-slate-50 rounded-lg p-3">
                <p className="text-sm font-medium text-slate-900 capitalize">{type}</p>
                <div className="mt-2 space-y-1 text-xs text-slate-500">
                  <p>Avg: {formatCost(avgCost)}/call</p>
                  <p>
                    Rate: {formatCost((cost / duration) * 1000)}/sec
                  </p>
                </div>
              </div>
            ))}
        </div>
      </div>

      <div className="text-xs text-slate-400 pt-2 border-t">
        Cost estimates are based on typical API pricing and may vary from actual charges.
      </div>
    </div>
  )
}
