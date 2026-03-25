import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { createOrUpdateLabel, getCuratedTraces, getTraces } from '@/lib/api'
import { Trace } from '@/lib/types'

type InboxLabel = 'failure' | 'needs_improvement'

function inferFailureMode(trace: Trace): string {
  const searchable = `${trace.name} ${JSON.stringify(trace.metadata || {})}`.toLowerCase()

  if (searchable.includes('timeout') || (trace.duration_ms ?? 0) >= 30000) {
    return 'Timeout / slow execution'
  }
  if (
    searchable.includes('tool') ||
    searchable.includes('http') ||
    searchable.includes('api') ||
    searchable.includes('connection')
  ) {
    return 'Tool / integration failure'
  }
  if (
    searchable.includes('token') ||
    searchable.includes('context') ||
    (trace.total_tokens ?? 0) >= 12000
  ) {
    return 'Context / token pressure'
  }
  if (
    searchable.includes('parse') ||
    searchable.includes('schema') ||
    searchable.includes('json')
  ) {
    return 'Output parsing failure'
  }
  return 'General execution failure'
}

function formatDuration(durationMs: number | null): string {
  if (!durationMs) {
    return '-'
  }
  return durationMs < 1000 ? `${durationMs.toFixed(0)}ms` : `${(durationMs / 1000).toFixed(2)}s`
}

export default function FailureInboxPage() {
  const queryClient = useQueryClient()

  const tracesQuery = useQuery({
    queryKey: ['failure-inbox', 'traces'],
    queryFn: () => getTraces(150, 0, 'error', { sort_by: 'created_at', sort_order: 'desc' }),
    refetchInterval: 5000,
  })

  const curatedTracesQuery = useQuery({
    queryKey: ['failure-inbox', 'curation'],
    queryFn: () => getCuratedTraces({ limit: 300, offset: 0 }),
    refetchInterval: 10000,
  })

  const labelsByTraceId = useMemo(() => {
    const map: Record<string, string> = {}
    ;(curatedTracesQuery.data || []).forEach((row) => {
      if (row.label) {
        map[row.trace_id] = row.label
      }
    })
    return map
  }, [curatedTracesQuery.data])

  const labelMutation = useMutation({
    mutationFn: ({ traceId, label }: { traceId: string; label: InboxLabel }) =>
      createOrUpdateLabel({ trace_id: traceId, label }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['failure-inbox', 'curation'] })
      queryClient.invalidateQueries({ queryKey: ['curated-traces'] })
      queryClient.invalidateQueries({ queryKey: ['curation-stats'] })
    },
  })

  const groupedFailures = useMemo(() => {
    const groups = new Map<string, Trace[]>()
    ;(tracesQuery.data?.traces || []).forEach((trace) => {
      const mode = inferFailureMode(trace)
      const existing = groups.get(mode)
      if (existing) {
        existing.push(trace)
      } else {
        groups.set(mode, [trace])
      }
    })

    return Array.from(groups.entries())
      .map(([mode, traces]) => ({ mode, traces }))
      .sort((a, b) => b.traces.length - a.traces.length)
  }, [tracesQuery.data?.traces])

  if (tracesQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (tracesQuery.error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4">
        <p className="text-red-400">Failed to load failure inbox.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-muted-100 flex items-center gap-2">
          <AlertTriangle className="h-6 w-6 text-amber-400" />
          Failure Inbox
        </h1>
        <p className="mt-1 text-sm text-muted-400">
          {tracesQuery.data?.total ?? 0} failed traces grouped by likely failure mode.
        </p>
      </div>

      {groupedFailures.length === 0 ? (
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-8 text-center">
          <p className="text-muted-300">No failed traces in the current window.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groupedFailures.map((group) => (
            <section key={group.mode} className="bg-dark-900 rounded-lg border border-dark-700">
              <div className="px-4 py-3 border-b border-dark-700 flex items-center justify-between">
                <h2 className="text-sm font-medium text-muted-100">{group.mode}</h2>
                <span className="text-xs text-muted-400">{group.traces.length} traces</span>
              </div>
              <div className="divide-y divide-dark-700">
                {group.traces.map((trace) => (
                  <div key={trace.id} className="px-4 py-3 flex flex-wrap items-center gap-3 justify-between">
                    <div className="min-w-0">
                      <Link to={`/traces/${trace.id}`} className="text-sm text-muted-100 hover:text-primary-300">
                        {trace.name}
                      </Link>
                      <p className="text-xs text-muted-400 mt-1">
                        {trace.error_count} errors · {trace.span_count} spans · {formatDuration(trace.duration_ms)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={clsx(
                          'px-2 py-0.5 text-xs rounded-full border',
                          labelsByTraceId[trace.id]
                            ? 'bg-primary-600/10 border-primary-500 text-primary-300'
                            : 'bg-dark-800 border-dark-700 text-muted-400'
                        )}
                      >
                        {labelsByTraceId[trace.id] ? `Label: ${labelsByTraceId[trace.id]}` : 'Unlabeled'}
                      </span>
                      <button
                        type="button"
                        onClick={() => labelMutation.mutate({ traceId: trace.id, label: 'failure' })}
                        disabled={labelMutation.isPending}
                        aria-label={`Label trace ${trace.id} as failure`}
                        className="px-2.5 py-1 text-xs rounded border border-red-700 text-red-300 hover:bg-red-900/20 disabled:opacity-60"
                      >
                        Mark failure
                      </button>
                      <button
                        type="button"
                        onClick={() => labelMutation.mutate({ traceId: trace.id, label: 'needs_improvement' })}
                        disabled={labelMutation.isPending}
                        aria-label={`Label trace ${trace.id} as needs improvement`}
                        className="px-2.5 py-1 text-xs rounded border border-amber-700 text-amber-300 hover:bg-amber-900/20 disabled:opacity-60"
                      >
                        Needs review
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
