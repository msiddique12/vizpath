import { useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Loader2, GitBranch, List, Grid2x2, X } from 'lucide-react'
import clsx from 'clsx'
import { getTrace } from '@/lib/api'
import { exportTrace, ExportFormat } from '@/lib/export'
import SpanTimeline from '@/components/SpanTimeline'
import DAGView from '@/components/DAGView'
import HeatmapView from '@/components/HeatmapView'
import ExportMenu from '@/components/ExportMenu'
import CurationPanel from '@/components/CurationPanel'
import IntelligencePanel from '@/components/IntelligencePanel'

type ViewMode = 'timeline' | 'dag' | 'heatmap'

export default function TraceDetailPage() {
  const { traceId } = useParams<{ traceId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const initialView = (searchParams.get('view') as ViewMode) || 'timeline'
  const [viewMode, setViewMode] = useState<ViewMode>(
    initialView === 'timeline' || initialView === 'dag' || initialView === 'heatmap'
      ? initialView
      : 'timeline'
  )
  const focusSpanName = searchParams.get('span_name')?.trim() || ''

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
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4">
        <p className="text-red-400">Failed to load trace details.</p>
      </div>
    )
  }

  const { trace, spans } = data

  const handleExport = (format: ExportFormat) => {
    exportTrace({ trace, spans }, format)
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          to="/traces"
          className="inline-flex items-center text-sm text-muted-400 hover:text-muted-200 mb-4"
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to traces
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-muted-100">{trace.name}</h1>
            <p className="mt-1 text-sm text-muted-400">
              {spans.length} spans
              {trace.duration_ms && ` · ${(trace.duration_ms / 1000).toFixed(2)}s`}
              {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            </p>
          </div>
          <ExportMenu onExport={handleExport} />
        </div>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium text-muted-100">Execution View</h2>
          <div className="flex items-center gap-1 bg-dark-800 p-1 rounded-lg">
            <button
              onClick={() => setViewMode('timeline')}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                viewMode === 'timeline'
                  ? 'bg-dark-700 text-muted-100 shadow-sm'
                  : 'text-muted-400 hover:text-muted-100'
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
                  ? 'bg-dark-700 text-muted-100 shadow-sm'
                  : 'text-muted-400 hover:text-muted-100'
              )}
            >
              <GitBranch className="h-4 w-4" />
              DAG
            </button>
            <button
              onClick={() => setViewMode('heatmap')}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                viewMode === 'heatmap'
                  ? 'bg-dark-700 text-muted-100 shadow-sm'
                  : 'text-muted-400 hover:text-muted-100'
              )}
            >
              <Grid2x2 className="h-4 w-4" />
              Heatmap
            </button>
          </div>
        </div>

        {focusSpanName && viewMode === 'timeline' && (
          <div className="mb-3 flex items-center justify-between rounded border border-primary-800 bg-primary-900/20 px-3 py-2">
            <p className="text-xs text-muted-200">
              Focused span: <span className="text-primary-400">{focusSpanName}</span>
            </p>
            <button
              type="button"
              onClick={() => {
                const next = new URLSearchParams(searchParams)
                next.delete('span_name')
                setSearchParams(next)
              }}
              className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
            >
              <X className="h-3 w-3" />
              Clear focus
            </button>
          </div>
        )}

        {viewMode === 'timeline' && <SpanTimeline spans={spans} focusSpanName={focusSpanName} />}
        {viewMode === 'dag' && <DAGView spans={spans} />}
        {viewMode === 'heatmap' && <HeatmapView spans={spans} />}
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <IntelligencePanel traceId={trace.id} />
        <CurationPanel traceId={trace.id} traceName={trace.name} />
      </div>
    </div>
  )
}
