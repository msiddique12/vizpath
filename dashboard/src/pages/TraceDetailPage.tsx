import { useEffect, useState } from 'react'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Loader2, GitBranch, List, Grid2x2, X, Link2, Check, ClipboardCopy, FileJson } from 'lucide-react'
import clsx from 'clsx'
import { getTrace } from '@/lib/api'
import { exportTrace, ExportFormat } from '@/lib/export'
import { Span } from '@/lib/types'
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
  const [copiedLink, setCopiedLink] = useState(false)
  const [copiedTraceId, setCopiedTraceId] = useState(false)
  const [copiedTraceJson, setCopiedTraceJson] = useState(false)
  const [copiedSpanId, setCopiedSpanId] = useState<string>('')
  const initialView = (searchParams.get('view') as ViewMode) || 'timeline'
  const [viewMode, setViewMode] = useState<ViewMode>(
    initialView === 'timeline' || initialView === 'dag' || initialView === 'heatmap'
      ? initialView
      : 'timeline'
  )
  const focusSpanName = searchParams.get('span_name')?.trim() || ''

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase() || ''
      const isTypingContext =
        tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable
      if (isTypingContext) return
      if (event.key === '1') setViewMode('timeline')
      if (event.key === '2') setViewMode('dag')
      if (event.key === '3') setViewMode('heatmap')
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    const next = new URLSearchParams(window.location.search)
    if (next.get('view') === viewMode) return
    next.set('view', viewMode)
    setSearchParams(next, { replace: true })
  }, [setSearchParams, viewMode])

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

  const handleCopyTracePayload = async () => {
    try {
      const payload = JSON.stringify({ trace, spans }, null, 2)
      await navigator.clipboard.writeText(payload)
      setCopiedTraceJson(true)
      setTimeout(() => setCopiedTraceJson(false), 1500)
    } catch {
      setCopiedTraceJson(false)
    }
  }

  const handleFocusSpan = (span: Span) => {
    const next = new URLSearchParams(searchParams)
    next.set('span_name', span.name)
    next.set('view', 'timeline')
    setSearchParams(next)
  }

  const handleCopySpanPayload = async (span: Span) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(span, null, 2))
      setCopiedSpanId(span.id)
      setTimeout(() => setCopiedSpanId(''), 1200)
    } catch {
      setCopiedSpanId('')
    }
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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(trace.id)
                setCopiedTraceId(true)
                setTimeout(() => setCopiedTraceId(false), 1200)
              } catch {
                setCopiedTraceId(false)
              }
            }}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-sm text-muted-200 hover:bg-dark-700"
          >
            {copiedTraceId ? <Check className="h-4 w-4 text-green-400" /> : <ClipboardCopy className="h-4 w-4" />}
            {copiedTraceId ? 'Copied ID' : 'Copy trace ID'}
          </button>
          <button
            type="button"
            onClick={async () => {
              await navigator.clipboard.writeText(window.location.href)
                setCopiedLink(true)
                setTimeout(() => setCopiedLink(false), 1200)
              }}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-sm text-muted-200 hover:bg-dark-700"
            >
              {copiedLink ? <Check className="h-4 w-4 text-green-400" /> : <Link2 className="h-4 w-4" />}
              {copiedLink ? 'Copied' : 'Copy link'}
            </button>
            <button
              type="button"
              onClick={handleCopyTracePayload}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-dark-800 border border-dark-700 rounded-lg text-sm text-muted-200 hover:bg-dark-700"
            >
              {copiedTraceJson ? <Check className="h-4 w-4 text-green-400" /> : <FileJson className="h-4 w-4" />}
              {copiedTraceJson ? 'Copied payload' : 'Copy payload'}
            </button>
            <ExportMenu onExport={handleExport} />
          </div>
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
        {copiedSpanId ? (
          <p className="mb-3 text-xs text-green-400">Copied span payload to clipboard.</p>
        ) : null}

        {viewMode === 'timeline' && (
          <SpanTimeline
            spans={spans}
            focusSpanName={focusSpanName}
            onCopySpan={handleCopySpanPayload}
            onFocusSpan={handleFocusSpan}
          />
        )}
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
