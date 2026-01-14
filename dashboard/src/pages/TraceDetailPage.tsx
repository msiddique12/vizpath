import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Loader2, GitBranch, List } from 'lucide-react'
import clsx from 'clsx'
import { getTrace } from '@/lib/api'
import SpanTimeline from '@/components/SpanTimeline'
import DAGView from '@/components/DAGView'

type ViewMode = 'timeline' | 'dag'

export default function TraceDetailPage() {
  const { traceId } = useParams<{ traceId: string }>()
  const [viewMode, setViewMode] = useState<ViewMode>('timeline')

  const { data, isLoading, error } = useQuery({
    queryKey: ['trace', traceId],
    queryFn: () => getTrace(traceId!),
    enabled: !!traceId,
    refetchInterval: (query) => {
      const trace = query.state.data?.trace
      return trace?.status === 'running' ? 2000 : false
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-700">Failed to load trace details.</p>
      </div>
    )
  }

  const { trace, spans } = data

  return (
    <div>
      <div className="mb-6">
        <Link
          to="/traces"
          className="inline-flex items-center text-sm text-slate-500 hover:text-slate-700 mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to traces
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{trace.name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {spans.length} spans
              {trace.duration_ms && ` · ${(trace.duration_ms / 1000).toFixed(2)}s`}
              {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-slate-900">Execution View</h2>
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
            <button
              onClick={() => setViewMode('timeline')}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                viewMode === 'timeline'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              )}
            >
              <List className="h-4 w-4" />
              Timeline
            </button>
            <button
              onClick={() => setViewMode('dag')}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                viewMode === 'dag'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              )}
            >
              <GitBranch className="h-4 w-4" />
              DAG
            </button>
          </div>
        </div>

        {viewMode === 'timeline' ? (
          <SpanTimeline spans={spans} />
        ) : (
          <DAGView spans={spans} width={800} height={500} />
        )}
      </div>
    </div>
  )
}
