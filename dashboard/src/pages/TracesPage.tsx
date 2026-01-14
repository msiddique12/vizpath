import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { AlertCircle, CheckCircle, Clock, Loader2, Wifi, WifiOff } from 'lucide-react'
import clsx from 'clsx'
import { getTraces } from '@/lib/api'
import { Trace, SpanStatus } from '@/lib/types'
import { useWebSocket } from '@/hooks/useWebSocket'

function StatusBadge({ status }: { status: SpanStatus }) {
  const config = {
    running: { icon: Loader2, color: 'text-blue-600 bg-blue-50', label: 'Running' },
    success: { icon: CheckCircle, color: 'text-green-600 bg-green-50', label: 'Success' },
    error: { icon: AlertCircle, color: 'text-red-600 bg-red-50', label: 'Error' },
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
      className="block hover:bg-slate-50 transition-colors"
    >
      <div className="px-6 py-4 flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <p className="text-sm font-medium text-slate-900 truncate">{trace.name}</p>
            <StatusBadge status={trace.status} />
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {trace.span_count} spans
            {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            {trace.total_cost && ` · $${trace.total_cost.toFixed(4)}`}
          </p>
        </div>
        <div className="ml-6 flex items-center gap-6">
          {trace.duration_ms && (
            <div className="text-right">
              <p className="text-sm font-medium text-slate-900">
                {trace.duration_ms < 1000
                  ? `${trace.duration_ms.toFixed(0)}ms`
                  : `${(trace.duration_ms / 1000).toFixed(2)}s`}
              </p>
              <p className="text-xs text-slate-500">Duration</p>
            </div>
          )}
          <div className="text-right text-sm text-slate-500">
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

  const { connected } = useWebSocket({
    onMessage: (msg) => {
      if (msg.type === 'span_ingested') {
        queryClient.invalidateQueries({ queryKey: ['traces'] })
      }
    },
  })

  const { data, isLoading, error } = useQuery({
    queryKey: ['traces'],
    queryFn: () => getTraces(50),
    refetchInterval: connected ? false : 5000,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-700">Failed to load traces. Make sure the server is running.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Traces</h1>
          <p className="mt-1 text-sm text-slate-500">
            {data?.total ?? 0} traces recorded
          </p>
        </div>
        <div className={clsx(
          'flex items-center gap-1.5 px-2 py-1 rounded-full text-xs',
          connected ? 'bg-green-50 text-green-700' : 'bg-slate-100 text-slate-500'
        )}>
          {connected ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
          {connected ? 'Live' : 'Polling'}
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 divide-y divide-slate-200">
        {data?.traces.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-slate-500">No traces yet. Start tracing your agents to see them here.</p>
          </div>
        ) : (
          data?.traces.map((trace) => <TraceRow key={trace.id} trace={trace} />)
        )}
      </div>
    </div>
  )
}
