import { useQuery } from '@tanstack/react-query'
import { Loader2, DollarSign } from 'lucide-react'
import clsx from 'clsx'
import { getTraces } from '@/lib/api'
import { Trace } from '@/lib/types'

function formatCost(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(3)}`
  return `$${cost.toFixed(2)}`
}

export default function CostPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['traces', 100],
    queryFn: () => getTraces(100),
  })

  const traces = data?.traces || []

  const totalCost = traces.reduce((sum, trace) => sum + (trace.total_cost || 0), 0)
  const totalTokens = traces.reduce((sum, trace) => sum + (trace.total_tokens || 0), 0)
  const tracesWithCost = traces.filter((t) => t.total_cost && t.total_cost > 0)

  const topCostlyTraces = [...traces]
    .filter((t) => t.total_cost && t.total_cost > 0)
    .sort((a, b) => (b.total_cost || 0) - (a.total_cost || 0))
    .slice(0, 10)

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Cost Analytics</h1>
        <p className="mt-1 text-sm text-slate-500">
          Analyze token usage and cost attribution across traces
        </p>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-6">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
          </div>
        ) : error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700">Failed to load cost data.</p>
          </div>
        ) : traces.length === 0 ? (
          <div className="text-center py-12">
            <DollarSign className="h-12 w-12 text-slate-300 mx-auto mb-3" />
            <p className="text-slate-500">No traces available</p>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-slate-50 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide">Total Cost</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1">
                  {formatCost(totalCost)}
                </p>
              </div>
              <div className="bg-slate-50 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide">Total Tokens</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1">
                  {totalTokens.toLocaleString()}
                </p>
              </div>
              <div className="bg-slate-50 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide">Traces</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1">{traces.length}</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-4">
                <p className="text-xs text-slate-500 uppercase tracking-wide">With Cost Data</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1">
                  {tracesWithCost.length}
                </p>
              </div>
            </div>

            {topCostlyTraces.length > 0 && (
              <div>
                <h4 className="text-sm font-medium text-slate-700 mb-3">Most Expensive Traces</h4>
                <div className="border rounded-lg overflow-hidden">
                  <table className="w-full">
                    <thead className="bg-slate-50">
                      <tr>
                        <th className="text-left text-xs font-medium text-slate-500 px-4 py-2">
                          Trace
                        </th>
                        <th className="text-right text-xs font-medium text-slate-500 px-4 py-2">
                          Spans
                        </th>
                        <th className="text-right text-xs font-medium text-slate-500 px-4 py-2">
                          Tokens
                        </th>
                        <th className="text-right text-xs font-medium text-slate-500 px-4 py-2">
                          Cost
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {topCostlyTraces.map((trace: Trace) => (
                        <tr key={trace.id} className="hover:bg-slate-50">
                          <td className="px-4 py-3">
                            <a
                              href={`/traces/${trace.id}`}
                              className="text-sm text-primary-600 hover:text-primary-700 font-medium"
                            >
                              {trace.name}
                            </a>
                            <p className="text-xs text-slate-500 mt-0.5">
                              {new Date(trace.created_at).toLocaleString()}
                            </p>
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600 text-right">
                            {trace.span_count}
                          </td>
                          <td className="px-4 py-3 text-sm text-slate-600 text-right">
                            {(trace.total_tokens || 0).toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span
                              className={clsx(
                                'inline-flex px-2 py-0.5 rounded text-xs font-medium',
                                (trace.total_cost || 0) > 0.1
                                  ? 'bg-red-100 text-red-700'
                                  : (trace.total_cost || 0) > 0.01
                                    ? 'bg-amber-100 text-amber-700'
                                    : 'bg-green-100 text-green-700'
                              )}
                            >
                              {formatCost(trace.total_cost || 0)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {tracesWithCost.length === 0 && (
              <div className="text-center py-8 border-t">
                <p className="text-slate-500 text-sm">
                  No traces with cost data yet. Cost data is tracked when using LLM spans with
                  token counts.
                </p>
              </div>
            )}

            <div className="text-xs text-slate-400 pt-2 border-t">
              Cost estimates are based on token counts and typical API pricing.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
