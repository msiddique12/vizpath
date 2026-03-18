import { FormEvent, MouseEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import {
  AlertCircle,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Clock,
  ClipboardCopy,
  Loader2,
  Search,
  Link2,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { getTraceSummary, getTraces } from '@/lib/api'
import { Trace, SpanStatus } from '@/lib/types'
import { useWebSocket } from '@/hooks/useWebSocket'

const PAGE_SIZE = 50
const FILTER_STORAGE_KEY = 'traces_filters_v1'

type SortBy = 'created_at' | 'duration_ms' | 'total_tokens' | 'total_cost' | 'span_count' | 'error_count' | 'name'
type SortOrder = 'asc' | 'desc'
type StatusFilter = '' | 'running' | 'success' | 'error'
type HasErrorsFilter = '' | 'true' | 'false'

const sortByValues: SortBy[] = ['created_at', 'duration_ms', 'total_tokens', 'total_cost', 'span_count', 'error_count', 'name']
const statusFilterValues: StatusFilter[] = ['', 'running', 'success', 'error']
const hasErrorsFilterValues: HasErrorsFilter[] = ['', 'true', 'false']

function parseSortBy(value: string | null): SortBy | undefined {
  return sortByValues.includes(value as SortBy) ? (value as SortBy) : undefined
}

function parseStatusFilter(value: string | null): StatusFilter {
  return statusFilterValues.includes(value as StatusFilter) ? (value as StatusFilter) : ''
}

function parseHasErrorsFilter(value: string | null): HasErrorsFilter {
  return hasErrorsFilterValues.includes(value as HasErrorsFilter) ? (value as HasErrorsFilter) : ''
}

function parseNumericFilter(value: string | null): string {
  if (!value) {
    return ''
  }

  const parsed = Number(value)
  return Number.isNaN(parsed) || parsed < 0 ? '' : String(parsed)
}

function getSavedFilters() {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return null
  }

  try {
    const savedRaw = window.localStorage.getItem(FILTER_STORAGE_KEY)
    if (!savedRaw) return null
    const parsed = JSON.parse(savedRaw)
    return {
      search: typeof parsed.search === 'string' ? parsed.search : '',
      statusFilter: parseStatusFilter(parsed.statusFilter ?? ''),
      minTokens: parseNumericFilter(parsed.minTokens ?? ''),
      minCost: parseNumericFilter(parsed.minCost ?? ''),
      hasErrors: parseHasErrorsFilter(parsed.hasErrors ?? ''),
      sortBy: parseSortBy(parsed.sortBy ?? '') ?? 'created_at',
      sortOrder: parsed.sortOrder === 'asc' || parsed.sortOrder === 'desc' ? parsed.sortOrder : 'desc',
    }
  } catch {
    return null
  }
}

function getFiltersFromSearchParams(searchParams: URLSearchParams) {
  return {
    search: searchParams.get('q') ?? '',
    statusFilter: parseStatusFilter(searchParams.get('status')),
    minTokens: parseNumericFilter(searchParams.get('min_tokens')),
    minCost: parseNumericFilter(searchParams.get('min_cost')),
    hasErrors: parseHasErrorsFilter(searchParams.get('has_errors')),
    sortBy: parseSortBy(searchParams.get('sort_by')) ?? undefined,
    sortOrder:
      searchParams.get('sort_order') === 'asc' || searchParams.get('sort_order') === 'desc'
        ? (searchParams.get('sort_order') as SortOrder)
        : undefined,
  }
}

function buildSearchParamsFromFilters(filters: {
  search: string
  statusFilter: StatusFilter
  minTokens: string
  minCost: string
  hasErrors: HasErrorsFilter
  sortBy: SortBy
  sortOrder: SortOrder
}) {
  const next = new URLSearchParams()
  if (filters.search.trim()) {
    next.set('q', filters.search.trim())
  }
  if (filters.statusFilter) {
    next.set('status', filters.statusFilter)
  }
  if (filters.minTokens) {
    next.set('min_tokens', String(Number(filters.minTokens)))
  }
  if (filters.minCost) {
    next.set('min_cost', String(Number(filters.minCost)))
  }
  if (filters.hasErrors) {
    next.set('has_errors', filters.hasErrors)
  }
  if (filters.sortBy !== 'created_at') {
    next.set('sort_by', filters.sortBy)
  }
  if (filters.sortOrder !== 'desc') {
    next.set('sort_order', filters.sortOrder)
  }
  return next
}

function formatCost(value: number): string {
  return `$${value.toFixed(4)}`
}

function formatDuration(value: number | null): string {
  if (!value) {
    return '-'
  }

  return value < 1000 ? `${value.toFixed(0)}ms` : `${(value / 1000).toFixed(2)}s`
}

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
  const [copiedTraceId, setCopiedTraceId] = useState(false)
  const [copiedTraceLink, setCopiedTraceLink] = useState(false)
  const traceUrl = `${window.location.origin}${window.location.pathname}/${trace.id}`

  const handleCopy = async (
    event: MouseEvent<HTMLButtonElement>,
    value: string,
    setCopied: (value: boolean) => void
  ) => {
    event.preventDefault()
    event.stopPropagation()
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      // Clipboard failures are non-blocking for the primary navigation action.
    }
  }

  return (
    <Link
      to={`/traces/${trace.id}`}
      className="block hover:bg-dark-800 transition-colors"
    >
      <div className="px-6 py-4 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <p className="text-sm font-medium text-muted-100 truncate">{trace.name}</p>
            <StatusBadge status={trace.status} />
          </div>
          <p className="mt-1 text-sm text-muted-400">
            {trace.span_count} spans
            {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            {trace.total_cost && ` · ${formatCost(trace.total_cost)}`}
          </p>
        </div>
        <div className="ml-6 flex items-start gap-6">
          <div className="text-right text-sm text-muted-400">
            <button
              type="button"
              onClick={(event) => handleCopy(event, trace.id, setCopiedTraceId)}
              className="inline-flex items-center gap-1.5 text-xs text-muted-300 hover:text-muted-100"
              title="Copy trace ID"
              aria-label="Copy trace ID"
            >
              <ClipboardCopy className="h-3.5 w-3.5" />
              {copiedTraceId ? 'Copied' : `ID ${trace.id.slice(0, 8)}`}
            </button>
            <p className="text-xs text-muted-500">Trace ID</p>
          </div>
          {trace.duration_ms && (
            <div className="text-right">
              <p className="text-sm font-medium text-muted-100">
                {formatDuration(trace.duration_ms)}
              </p>
              <p className="text-xs text-muted-400">Duration</p>
            </div>
          )}
          <button
            type="button"
            onClick={(event) => handleCopy(event, traceUrl, setCopiedTraceLink)}
            className="inline-flex items-center gap-1.5 text-xs text-muted-300 hover:text-muted-100"
            title="Copy trace link"
            aria-label="Copy trace link"
          >
            <Link2 className="h-3.5 w-3.5" />
            {copiedTraceLink ? 'Copied' : 'Copy link'}
          </button>
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
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [minTokens, setMinTokens] = useState('')
  const [minCost, setMinCost] = useState('')
  const [hasErrors, setHasErrors] = useState<HasErrorsFilter>('')
  const [sortBy, setSortBy] = useState<SortBy>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const [summaryWindowDays, setSummaryWindowDays] = useState<7 | 30>(7)
  const [manualWsApiKey, setManualWsApiKey] = useState('')

  useEffect(() => {
    const saved = getSavedFilters()
    const parsed = getFiltersFromSearchParams(searchParams)

    setSearch(searchParams.has('q') ? parsed.search : saved?.search || '')
    setStatusFilter(searchParams.has('status') ? parsed.statusFilter : saved?.statusFilter || '')
    setMinTokens(searchParams.has('min_tokens') ? parsed.minTokens : saved?.minTokens || '')
    setMinCost(searchParams.has('min_cost') ? parsed.minCost : saved?.minCost || '')
    setHasErrors(searchParams.has('has_errors') ? parsed.hasErrors : saved?.hasErrors || '')
    setSortBy(parsed.sortBy || saved?.sortBy || 'created_at')
    setSortOrder(parsed.sortOrder || saved?.sortOrder || 'desc')
  }, [searchParams])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(
        FILTER_STORAGE_KEY,
        JSON.stringify({
          search,
          statusFilter,
          minTokens,
          minCost,
          hasErrors,
          sortBy,
          sortOrder,
        })
      )
    } catch {
      // Ignore storage failures (for example in restricted environments).
    }
  }, [hasErrors, minCost, minTokens, search, sortBy, sortOrder, statusFilter])

  useEffect(() => {
    const next = buildSearchParamsFromFilters({
      search,
      statusFilter,
      minTokens,
      minCost,
      hasErrors,
      sortBy,
      sortOrder,
    })

    const current = new URLSearchParams(searchParams)
    if (next.toString() !== current.toString()) {
      setSearchParams(next, { replace: true })
    }
  }, [hasErrors, minCost, minTokens, search, searchParams, setSearchParams, sortBy, sortOrder, statusFilter])

  useEffect(() => {
    setPage(1)
  }, [search, statusFilter, minTokens, minCost, hasErrors, sortBy, sortOrder])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase() || ''
      const isTypingContext =
        tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable

      if (event.key === '/' && !isTypingContext) {
        event.preventDefault()
        searchInputRef.current?.focus()
        searchInputRef.current?.select()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const queryOptions = useMemo(() => {
    return {
      q: search.trim() || undefined,
      min_tokens: minTokens ? Number(minTokens) : undefined,
      min_cost: minCost ? Number(minCost) : undefined,
      has_errors: hasErrors === '' ? undefined : hasErrors === 'true',
      sort_by: sortBy,
      sort_order: sortOrder,
    }
  }, [hasErrors, minCost, minTokens, search, sortBy, sortOrder])

  const { connected, lastDisconnect, reconnect, setApiKey: setRuntimeWebSocketKey } = useWebSocket({
    onMessage: (msg) => {
      if (msg.type === 'span_ingested') {
        queryClient.invalidateQueries({ queryKey: ['traces'] })
      }
    },
  })

  const handleManualApiKeySubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = manualWsApiKey.trim()
    if (!trimmed) {
      return
    }
    setRuntimeWebSocketKey(trimmed)
    setManualWsApiKey('')
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['traces', page, statusFilter, queryOptions],
    queryFn: () =>
      getTraces(
        PAGE_SIZE,
        (page - 1) * PAGE_SIZE,
        statusFilter || undefined,
        queryOptions
      ),
    refetchInterval: connected ? false : 5000,
  })

  const summaryQuery = useQuery({
    queryKey: ['trace-summary', summaryWindowDays],
    queryFn: () => getTraceSummary(summaryWindowDays),
    refetchInterval: connected ? false : 5000,
  })

  const totalPages = data?.total ? Math.ceil(data.total / PAGE_SIZE) : 1
  const hasNextPage = page < totalPages
  const hasPrevPage = page > 1
  const hasActiveFilters =
    Boolean(search) || Boolean(statusFilter) || Boolean(hasErrors) || Boolean(minTokens) || Boolean(minCost)
  const activeFilterChips = [
    search ? { key: 'search', label: `Search: ${search}`, clear: () => setSearch('') } : null,
    statusFilter
      ? {
          key: 'status',
          label: `Status: ${statusFilter}`,
          clear: () => setStatusFilter(''),
        }
      : null,
    hasErrors
      ? {
          key: 'errors',
          label: hasErrors === 'true' ? 'With errors only' : 'Without errors only',
          clear: () => setHasErrors(''),
        }
      : null,
    minTokens
      ? {
          key: 'minTokens',
          label: `Min tokens: ${minTokens}`,
          clear: () => setMinTokens(''),
        }
      : null,
    minCost
      ? {
          key: 'minCost',
          label: `Min cost: ${minCost}`,
          clear: () => setMinCost(''),
        }
      : null,
  ].filter(Boolean) as Array<{ key: string; label: string; clear: () => void }>

  const isAuthFailure = lastDisconnect?.code === 4001
  const connectionStatusText = isAuthFailure
    ? 'Live updates are unavailable: authentication is required for WebSocket streaming.'
    : connected === false
      ? 'Live updates disconnected. Retrying automatically when possible.'
      : null
  const authKeyConfigured = Boolean(import.meta.env.VITE_VIZPATH_API_KEY?.trim())
  const canRetryConnection = !isAuthFailure

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

      {connectionStatusText && (
        <div
          role="status"
          className={clsx(
            'mb-4 rounded-lg border px-4 py-3 text-sm',
            isAuthFailure
              ? 'bg-amber-900/30 border-amber-700/60 text-amber-200'
              : 'bg-blue-900/30 border-blue-700/60 text-blue-200'
          )}
        >
          <p>{connectionStatusText}</p>
          <div className="mt-2 flex items-center gap-2">
            {isAuthFailure && (
              <p className="text-xs text-amber-300/90">
                {authKeyConfigured
                  ? 'Update the dashboard API key and reload to reconnect.'
                  : 'Use a websocket API key to reconnect with live updates.'}
              </p>
            )}
            {canRetryConnection && !isAuthFailure && (
              <button
                type="button"
                onClick={reconnect}
                className="px-3 py-1 text-xs rounded-full bg-dark-800 border border-dark-700 text-muted-100 hover:bg-dark-700"
              >
                Retry connection
              </button>
            )}
            {isAuthFailure && !authKeyConfigured && (
              <form
                onSubmit={handleManualApiKeySubmit}
                className="w-full flex items-center gap-2 flex-wrap"
              >
                <label className="sr-only" htmlFor="ws-auth-key-input">
                  Websocket API key
                </label>
                <input
                  id="ws-auth-key-input"
                  name="wsAuthKey"
                  type="password"
                  value={manualWsApiKey}
                  onChange={(event) => setManualWsApiKey(event.target.value)}
                  placeholder="Enter websocket API key"
                  className="h-8 px-2 bg-dark-900 border border-dark-700 rounded text-xs text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
                />
                <button
                  type="submit"
                  disabled={!manualWsApiKey.trim()}
                  className="px-3 py-1 text-xs rounded-full bg-dark-800 border border-dark-700 text-muted-100 hover:bg-dark-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Connect with API key
                </button>
              </form>
            )}
            {!canRetryConnection && (
              <p className="text-xs text-amber-300/90">
                Streaming views will continue via polling when websocket access is unavailable.
              </p>
            )}
          </div>
        </div>
      )}

      {summaryQuery.data && (
        <div className="mb-4 bg-dark-900 rounded-lg border border-dark-700 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-muted-200">KPI Summary</h2>
            <div className="flex items-center gap-1 bg-dark-800 rounded-lg p-1">
              <button
                onClick={() => setSummaryWindowDays(7)}
                className={clsx(
                  'px-2 py-1 text-xs rounded',
                  summaryWindowDays === 7
                    ? 'bg-dark-700 text-muted-100'
                    : 'text-muted-400 hover:text-muted-200'
                )}
              >
                7d
              </button>
              <button
                onClick={() => setSummaryWindowDays(30)}
                className={clsx(
                  'px-2 py-1 text-xs rounded',
                  summaryWindowDays === 30
                    ? 'bg-dark-700 text-muted-100'
                    : 'text-muted-400 hover:text-muted-200'
                )}
              >
                30d
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-dark-800 rounded-lg p-3">
              <p className="text-xs text-muted-400">Success rate</p>
              <p className="text-sm text-muted-100 mt-1">{summaryQuery.data.success_rate.toFixed(1)}%</p>
            </div>
            <div className="bg-dark-800 rounded-lg p-3">
              <p className="text-xs text-muted-400">p50 latency</p>
              <p className="text-sm text-muted-100 mt-1">
                {summaryQuery.data.p50_duration_ms
                  ? summaryQuery.data.p50_duration_ms < 1000
                    ? `${summaryQuery.data.p50_duration_ms.toFixed(0)}ms`
                    : `${(summaryQuery.data.p50_duration_ms / 1000).toFixed(2)}s`
                  : '-'}
              </p>
            </div>
            <div className="bg-dark-800 rounded-lg p-3">
              <p className="text-xs text-muted-400">p95 latency</p>
              <p className="text-sm text-muted-100 mt-1">
                {summaryQuery.data.p95_duration_ms
                  ? summaryQuery.data.p95_duration_ms < 1000
                    ? `${summaryQuery.data.p95_duration_ms.toFixed(0)}ms`
                    : `${(summaryQuery.data.p95_duration_ms / 1000).toFixed(2)}s`
                  : '-'}
              </p>
            </div>
            <div className="bg-dark-800 rounded-lg p-3">
              <p className="text-xs text-muted-400">Avg tokens</p>
              <p className="text-sm text-muted-100 mt-1">
                {summaryQuery.data.avg_tokens ? summaryQuery.data.avg_tokens.toFixed(0) : '-'}
              </p>
            </div>
            <div className="bg-dark-800 rounded-lg p-3">
              <p className="text-xs text-muted-400">Avg cost</p>
              <p className="text-sm text-muted-100 mt-1">
                {summaryQuery.data.avg_cost ? `$${summaryQuery.data.avg_cost.toFixed(4)}` : '-'}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4 bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <label className="relative">
            <Search className="h-4 w-4 text-muted-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              ref={searchInputRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && search) {
                  setSearch('')
                }
              }}
              placeholder="Search trace name"
              className="w-full bg-dark-800 border border-dark-700 rounded-lg pl-9 pr-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </label>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">All statuses</option>
            <option value="running">Running</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>

          <select
            value={hasErrors}
            onChange={(e) => setHasErrors(e.target.value as '' | 'true' | 'false')}
            className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">Any error count</option>
            <option value="true">Only traces with errors</option>
            <option value="false">Only traces without errors</option>
          </select>

          <div className="grid grid-cols-2 gap-2">
            <input
              value={minTokens}
              onChange={(e) => setMinTokens(e.target.value.replace(/[^\d]/g, ''))}
              placeholder="Min tokens"
              className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <input
              value={minCost}
              onChange={(e) => setMinCost(e.target.value.replace(/[^\d.]/g, ''))}
              placeholder="Min cost"
              className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="created_at">Sort: Newest</option>
            <option value="duration_ms">Sort: Duration</option>
            <option value="total_tokens">Sort: Total tokens</option>
            <option value="total_cost">Sort: Total cost</option>
            <option value="span_count">Sort: Span count</option>
            <option value="error_count">Sort: Error count</option>
            <option value="name">Sort: Name</option>
          </select>
          <select
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as SortOrder)}
            className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="desc">Desc</option>
            <option value="asc">Asc</option>
          </select>

          <button
            onClick={() => {
              setStatusFilter('running')
              setSearch('')
              setMinTokens('')
              setMinCost('')
              setHasErrors('')
              setSortBy('created_at')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
          >
            Preset: Live
          </button>
          <button
            onClick={() => {
              setStatusFilter('')
              setSearch('')
              setMinTokens('')
              setMinCost('')
              setHasErrors('true')
              setSortBy('error_count')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
          >
            Preset: Error traces
          </button>
          <button
            onClick={() => {
              setStatusFilter('')
              setSearch('')
              setMinTokens('')
              setMinCost('')
              setHasErrors('')
              setSortBy('total_cost')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
          >
            Preset: High cost
          </button>
          <button
            onClick={() => {
              setStatusFilter('')
              setSearch('')
              setMinTokens('')
              setMinCost('')
              setHasErrors('')
              setSortBy('created_at')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-900 border border-dark-700 rounded-lg text-muted-300 hover:bg-dark-800"
          >
            Clear
          </button>
        </div>

        {activeFilterChips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {activeFilterChips.map((chip) => (
              <button
                key={chip.key}
                onClick={chip.clear}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-dark-800 border border-dark-700 text-muted-300 hover:text-muted-100 hover:bg-dark-700"
                title={`Clear ${chip.label}`}
              >
                <span>{chip.label}</span>
                <X className="h-3 w-3" />
              </button>
            ))}
          </div>
        )}

        {hasActiveFilters && (
          <div className="flex justify-end">
            <button
              onClick={() => {
                setStatusFilter('')
                setSearch('')
                setMinTokens('')
                setMinCost('')
                setHasErrors('')
              }}
              className="px-3 py-1.5 text-xs bg-dark-800 border border-primary-500 text-primary-300 rounded-lg hover:bg-dark-700"
            >
              Clear all filters
            </button>
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 divide-y divide-dark-700">
        {data?.traces.length === 0 ? (
          <div className="px-6 py-12 text-center">
            {hasActiveFilters ? (
              <div className="space-y-3">
                <p className="text-muted-400">No traces match your filters.</p>
                <button
                  onClick={() => {
                    setStatusFilter('')
                    setSearch('')
                    setMinTokens('')
                    setMinCost('')
                    setHasErrors('')
                  }}
                  className="px-3 py-1.5 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
                >
                  Clear all filters
                </button>
              </div>
            ) : (
              <p className="text-muted-400">No traces yet. Start tracing your agents to see them here.</p>
            )}
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
