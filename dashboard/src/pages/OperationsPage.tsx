import { FormEvent, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Gauge, Loader2, Search, ShieldCheck, Wrench } from 'lucide-react'
import clsx from 'clsx'
import {
  evaluateGuardrails,
  getAgentScorecard,
  getDefaultGuardrails,
  getToolAnalytics,
  getTraces,
  searchTraces,
} from '@/lib/api'

function formatDuration(value: number | null): string {
  if (value === null) return '-'
  return value < 1000 ? `${value.toFixed(0)}ms` : `${(value / 1000).toFixed(2)}s`
}

function formatCost(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`
  return `$${value.toFixed(2)}`
}

export default function OperationsPage() {
  const [windowDays, setWindowDays] = useState(7)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedTraceId, setSelectedTraceId] = useState('')

  const scorecardQuery = useQuery({
    queryKey: ['agent-scorecard', windowDays],
    queryFn: () => getAgentScorecard(windowDays),
  })
  const toolsQuery = useQuery({
    queryKey: ['tool-analytics', windowDays],
    queryFn: () => getToolAnalytics(windowDays),
  })
  const tracesQuery = useQuery({
    queryKey: ['traces', 'operations'],
    queryFn: () => getTraces(100, 0, undefined, { sort_by: 'created_at', sort_order: 'desc' }),
  })
  const defaultsQuery = useQuery({
    queryKey: ['guardrail-defaults'],
    queryFn: getDefaultGuardrails,
  })

  const searchMutation = useMutation({
    mutationFn: () => searchTraces({ query: searchQuery.trim(), limit: 10, include_spans: true }),
  })
  const guardrailMutation = useMutation({
    mutationFn: () =>
      evaluateGuardrails({
        trace_id: selectedTraceId || undefined,
        policies: defaultsQuery.data?.policies,
        window_days: windowDays,
        limit: 50,
      }),
  })

  const traces = tracesQuery.data?.traces ?? []
  const topTools = useMemo(() => toolsQuery.data?.tools.slice(0, 8) ?? [], [toolsQuery.data?.tools])

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (searchQuery.trim()) {
      searchMutation.mutate()
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-muted-100 flex items-center gap-2">
            <Gauge className="h-6 w-6 text-primary-400" />
            Agent Operations
          </h1>
          <p className="mt-1 text-sm text-muted-400">
            Scorecards, tool reliability, semantic trace search, and deterministic guardrail checks.
          </p>
        </div>
        <select
          value={windowDays}
          onChange={(event) => setWindowDays(Number(event.target.value))}
          className="bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {scorecardQuery.isLoading ? (
          <div className="bg-dark-900 border border-dark-700 rounded-lg p-4 text-muted-400">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <>
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <p className="text-xs text-muted-400 uppercase tracking-wide">Reliability</p>
              <p className="mt-1 text-2xl font-semibold text-muted-100">
                {scorecardQuery.data?.reliability_score.toFixed(1) ?? '0.0'}%
              </p>
              <p className="mt-1 text-xs text-muted-500">{scorecardQuery.data?.trace_count ?? 0} traces</p>
            </div>
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <p className="text-xs text-muted-400 uppercase tracking-wide">P95 Latency</p>
              <p className="mt-1 text-2xl font-semibold text-muted-100">
                {formatDuration(scorecardQuery.data?.p95_duration_ms ?? null)}
              </p>
              <p className="mt-1 text-xs text-muted-500">P50 {formatDuration(scorecardQuery.data?.p50_duration_ms ?? null)}</p>
            </div>
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <p className="text-xs text-muted-400 uppercase tracking-wide">Total Cost</p>
              <p className="mt-1 text-2xl font-semibold text-muted-100">
                {formatCost(scorecardQuery.data?.total_cost ?? 0)}
              </p>
              <p className="mt-1 text-xs text-muted-500">{scorecardQuery.data?.total_tokens ?? 0} tokens</p>
            </div>
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <p className="text-xs text-muted-400 uppercase tracking-wide">Tool Success</p>
              <p className="mt-1 text-2xl font-semibold text-muted-100">
                {scorecardQuery.data?.tool_success_rate?.toFixed(1) ?? '-'}%
              </p>
              <p className="mt-1 text-xs text-muted-500">{scorecardQuery.data?.tool_call_count ?? 0} tool calls</p>
            </div>
          </>
        )}
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-dark-900 border border-dark-700 rounded-lg">
          <div className="border-b border-dark-700 p-4">
            <h2 className="text-sm font-medium text-muted-100 flex items-center gap-2">
              <Wrench className="h-4 w-4" />
              Tool Reliability
            </h2>
          </div>
          <div className="divide-y divide-dark-700">
            {topTools.length === 0 ? (
              <p className="p-4 text-sm text-muted-400">No tool spans in this window.</p>
            ) : (
              topTools.map((tool) => (
                <div key={tool.name} className="p-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm text-muted-100">{tool.name}</p>
                    <p className="text-xs text-muted-400 mt-1">
                      {tool.call_count} calls · {tool.error_count} errors · avg {formatDuration(tool.avg_duration_ms)}
                    </p>
                  </div>
                  <span
                    className={clsx(
                      'text-xs rounded px-2 py-1',
                      tool.success_rate >= 95
                        ? 'bg-green-900/30 text-green-300'
                        : tool.success_rate >= 75
                          ? 'bg-amber-900/30 text-amber-300'
                          : 'bg-red-900/30 text-red-300'
                    )}
                  >
                    {tool.success_rate.toFixed(1)}%
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-dark-900 border border-dark-700 rounded-lg p-4 space-y-4">
          <h2 className="text-sm font-medium text-muted-100 flex items-center gap-2">
            <Search className="h-4 w-4" />
            Semantic Trace Search
          </h2>
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="flex-1 bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
              placeholder="tool timeout pricing"
            />
            <button
              type="submit"
              disabled={!searchQuery.trim() || searchMutation.isPending}
              className="px-3 py-2 rounded bg-primary-600 text-white text-sm disabled:bg-dark-700 disabled:text-muted-500"
            >
              {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Search'}
            </button>
          </form>
          <div className="space-y-2">
            {searchMutation.data?.results.map((result) => (
              <div key={result.trace.id} className="rounded border border-dark-700 p-3">
                <p className="text-sm text-muted-100">{result.trace.name}</p>
                <p className="text-xs text-muted-400 mt-1">
                  score {result.score} · terms {result.matched_terms.join(', ')}
                </p>
                {result.matched_spans.length > 0 && (
                  <p className="text-xs text-muted-500 mt-1">
                    spans {result.matched_spans.map((span) => span.name).join(', ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-dark-900 border border-dark-700 rounded-lg p-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium text-muted-100 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Guardrail Evaluation
            </h2>
            <p className="text-xs text-muted-400 mt-1">
              Evaluate built-in cost, latency, error, and LLM-call policies.
            </p>
          </div>
          <div className="flex gap-2">
            <select
              value={selectedTraceId}
              onChange={(event) => setSelectedTraceId(event.target.value)}
              className="bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
            >
              <option value="">Recent traces</option>
              {traces.map((trace) => (
                <option key={trace.id} value={trace.id}>
                  {trace.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => guardrailMutation.mutate()}
              disabled={guardrailMutation.isPending}
              className="px-3 py-2 rounded bg-dark-800 border border-dark-700 text-muted-100 text-sm hover:bg-dark-700"
            >
              {guardrailMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Evaluate'}
            </button>
          </div>
        </div>

        {guardrailMutation.data && (
          <div>
            <p className="text-sm text-muted-200">
              {guardrailMutation.data.breach_count} breaches across {guardrailMutation.data.trace_count} traces.
            </p>
            <div className="mt-3 divide-y divide-dark-700 border border-dark-700 rounded">
              {guardrailMutation.data.results.slice(0, 8).map((result) => (
                <div key={result.trace_id} className="p-3 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm text-muted-100">{result.trace_name}</p>
                    <p className="text-xs text-muted-400 mt-1">
                      {result.policies.filter((policy) => !policy.passed).map((policy) => policy.name).join(', ') || 'All policies passed'}
                    </p>
                  </div>
                  <span
                    className={clsx(
                      'text-xs rounded px-2 py-1',
                      result.passed ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
                    )}
                  >
                    {result.passed ? 'pass' : 'breach'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
