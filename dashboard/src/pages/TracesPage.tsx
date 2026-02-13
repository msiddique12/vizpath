import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { AlertCircle, CheckCircle, Clock, Loader2, Wifi, WifiOff, ChevronLeft, ChevronRight } from 'lucide-react'
import clsx from 'clsx'
import { getTraces } from '@/lib/api'
import { Trace, SpanStatus } from '@/lib/types'
import { useWebSocket } from '@/hooks/useWebSocket'

const PAGE_SIZE = 50

function StatusBadge({ status }: { status: SpanStatus }) {
  const config = {
    running: { icon: Loader2, color: 'text-blue-400 bg-blue-900/50', label: 'Running' },
    success: { icon: CheckCircle, color: 'text-green-400 bg-green-900/50', label: 'Success' },
    error: { icon: AlertCircle, color: 'text-red-400 bg-red-900/50', label: 'Error' },
  }
  const { icon: Icon, color, label } = config[status]

  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium', color)}>
      <Icon className={clsx('h-3 w-3', status === 'running' && 'animate-spin')} />
      {label}
    </span>
  )
}

function TraceRow({ trace }: { trace: Trace }) {
  return (
    <Link
      to={`/traces/${trace.id}`}
      className="block hover:bg-dark-800 transition-colors"
    >
      <div className="px-6 py-4 flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <p className="text-sm font-medium text-muted-100 truncate">{trace.name}</p>
            <StatusBadge status={trace.status} />
          </div>
          <p className="mt-1 text-sm text-muted-400">
            {trace.span_count} spans
            {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            {trace.total_cost && ` · $${trace.total_cost.toFixed(4)}`}
          </p>
        </div>
        <div className="ml-6 flex items-center gap-6">
          {trace.duration_ms && (
            <div className="text-right">
              <p className="text-sm font-medium text-muted-100">
                {trace.duration_ms < 1000
                  ? `${trace.duration_ms.toFixed(0)}ms`
                  : `${(trace.duration_ms / 1000).toFixed(2)}s`}
              </p>
              <p className="text-xs text-muted-400">Duration</p>
            </div>
          )}
          <div className="text-right text-sm text-muted-400">
            <Clock className="h-4 w-4 inline mr-1" />
            {formatDistanceToNow(new Date(trace.start_time), { addSuffix: true })}
          </div>
        </div>
      </div>
    </Link>
  )
}

export default function TracesPage() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)

  const { connected } = useWebSocket({
    onMessage: (msg) => {
      if (msg.type === 'span_ingested') {
        queryClient.invalidateQueries({ queryKey: ['traces'] })
      }
    },
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['traces', page],
    queryFn: () => getTraces(PAGE_SIZE, (page - 1) * PAGE_SIZE),
    refetchInterval: connected ? false : 5000,
  })

  const totalPages = data?.total ? Math.ceil(data.total / PAGE_SIZE) : 1
  const hasNextPage = page < totalPages
  const hasPrevPage = page > 1

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg p-4">
        <p className="text-red-400">Failed to load traces. Make sure the server is running.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-muted-100">Traces</h1>
          <p className="mt-1 text-sm text-muted-400">
            {data?.total ?? 0} traces recorded
          </p>
        </div>
        <div className={clsx(
          'flex items-center gap-1.5 px-2 py-1 rounded-full text-xs',
          connected ? 'bg-green-900/30 text-green-400' : 'bg-dark-700 text-muted-400'
        )}>
          {connected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
          {connected ? 'Live' : 'Polling'}
        </div>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 divide-y divide-dark-700">
        {data?.traces.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-muted-400">No traces yet. Start tracing your agents to see them here.</p>
          </div>
        ) : (
          data?.traces.map((trace) => <TraceRow key={trace.id} trace={trace} />)
        )}
      </div>

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-muted-400">
            Showing {((page - 1) * PAGE_SIZE) + 1} - {Math.min(page * PAGE_SIZE, data?.total || 0)} of {data?.total || 0}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={!hasPrevPage}
              aria-label="Previous page"
              className={clsx(
                'flex items-center gap-1 px-3 py-2 text-sm rounded-lg transition-colors',
                hasPrevPage
                  ? 'bg-dark-800 text-muted-200 hover:bg-dark-700'
                  : 'bg-dark-900 text-muted-500 cursor-not-allowed'
              )}
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </button>
            <span className="text-sm text-muted-400 px-2">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={!hasNextPage}
              aria-label="Next page"
              className={clsx(
                'flex items-center gap-1 px-3 py-2 text-sm rounded-lg transition-colors',
                hasNextPage
                  ? 'bg-dark-800 text-muted-200 hover:bg-dark-700'
                  : 'bg-dark-900 text-muted-500 cursor-not-allowed'
              )}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
