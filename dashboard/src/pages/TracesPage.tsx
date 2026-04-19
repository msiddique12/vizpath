import { MouseEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
import {
  createOrUpdateLabel,
  getCuratedTraces,
  getIntelligenceIncidents,
  getLabel,
  getProjectBudgetStatus,
  getTraceSummary,
  getTraces,
} from '@/lib/api'
import { getEffectiveApiKey } from '@/lib/apiKey'
import { Trace, SpanStatus } from '@/lib/types'
import { getTraceRiskFlags } from '@/lib/traceRisk'
import { useWebSocket } from '@/hooks/useWebSocket'
import WebSocketRecoveryPanel from '@/components/WebSocketRecoveryPanel'

const PAGE_SIZE = 50
const FILTER_STORAGE_KEY = 'traces_filters_v1'
const FILTER_PRESETS_STORAGE_KEY = 'traces_filter_presets_v1'
const PINNED_TRACES_STORAGE_KEY = 'traces_pinned_v1'

type SortBy = 'created_at' | 'duration_ms' | 'total_tokens' | 'total_cost' | 'span_count' | 'error_count' | 'name'
type SortOrder = 'asc' | 'desc'
type StatusFilter = '' | 'running' | 'success' | 'error'
type HasErrorsFilter = '' | 'true' | 'false'
type FilterState = {
  search: string
  statusFilter: StatusFilter
  minTokens: string
  minCost: string
  hasErrors: HasErrorsFilter
  pinnedOnly: boolean
  sortBy: SortBy
  sortOrder: SortOrder
}
type SavedFilterPreset = {
  id: string
  name: string
  filters: FilterState
}
type QuickLabelValue = 'good' | 'needs_improvement' | 'failure'

const QUICK_LABEL_OPTIONS: Array<{ value: QuickLabelValue; label: string }> = [
  { value: 'good', label: 'Good' },
  { value: 'needs_improvement', label: 'Needs review' },
  { value: 'failure', label: 'Failure' },
]

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

function parseBooleanFilter(value: unknown): boolean {
  return value === true || value === 'true'
}

function getSavedFilters(): FilterState | null {
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
      pinnedOnly: parseBooleanFilter(parsed.pinnedOnly),
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
    pinnedOnly: parseBooleanFilter(searchParams.get('pinned_only')),
    sortBy: parseSortBy(searchParams.get('sort_by')) ?? undefined,
    sortOrder:
      searchParams.get('sort_order') === 'asc' || searchParams.get('sort_order') === 'desc'
        ? (searchParams.get('sort_order') as SortOrder)
        : undefined,
  }
}

function getSavedFilterPresets(): SavedFilterPreset[] {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return []
  }

  try {
    const savedRaw = window.localStorage.getItem(FILTER_PRESETS_STORAGE_KEY)
    if (!savedRaw) return []
    const parsed = JSON.parse(savedRaw)
    if (!Array.isArray(parsed)) {
      return []
    }

    return parsed
      .map((item) => {
        if (typeof item !== 'object' || item === null) {
          return null
        }
        const candidate = item as Partial<SavedFilterPreset>
        if (typeof candidate.id !== 'string' || typeof candidate.name !== 'string') {
          return null
        }
        const filters = candidate.filters
        if (typeof filters !== 'object' || filters === null) {
          return null
        }

        return {
          id: candidate.id,
          name: candidate.name,
          filters: {
            search: typeof filters.search === 'string' ? filters.search : '',
            statusFilter: parseStatusFilter(filters.statusFilter ?? ''),
            minTokens: parseNumericFilter(filters.minTokens ?? ''),
            minCost: parseNumericFilter(filters.minCost ?? ''),
            hasErrors: parseHasErrorsFilter(filters.hasErrors ?? ''),
            pinnedOnly: parseBooleanFilter(filters.pinnedOnly),
            sortBy: parseSortBy(filters.sortBy ?? '') ?? 'created_at',
            sortOrder: filters.sortOrder === 'asc' || filters.sortOrder === 'desc' ? filters.sortOrder : 'desc',
          },
        } satisfies SavedFilterPreset
      })
      .filter((value): value is SavedFilterPreset => value !== null)
      .slice(0, 8)
  } catch {
    return []
  }
}

function buildSearchParamsFromFilters(filters: FilterState) {
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
  if (filters.pinnedOnly) {
    next.set('pinned_only', 'true')
  }
  if (filters.sortBy !== 'created_at') {
    next.set('sort_by', filters.sortBy)
  }
  if (filters.sortOrder !== 'desc') {
    next.set('sort_order', filters.sortOrder)
  }
  return next
}

function getPinnedTraceIds(): string[] {
  if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
    return []
  }

  try {
    const savedRaw = window.localStorage.getItem(PINNED_TRACES_STORAGE_KEY)
    if (!savedRaw) return []
    const parsed = JSON.parse(savedRaw)
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed.filter((item): item is string => typeof item === 'string').slice(0, 500)
  } catch {
    return []
  }
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

function formatBudgetPercent(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return '-'
  }
  return `${value.toFixed(1)}%`
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

function TraceRow({
  trace,
  onQuickLabel,
  activeQuickLabel,
  quickLabelPending,
  selected,
  onToggleSelect,
  pinned,
  onTogglePin,
  noteSummary,
  noteDraft,
  noteEditorOpen,
  noteLoading,
  noteSaving,
  onOpenNoteEditor,
  onChangeNoteDraft,
  onCloseNoteEditor,
  onSaveNote,
}: {
  trace: Trace
  onQuickLabel: (traceId: string, label: QuickLabelValue) => void
  activeQuickLabel: QuickLabelValue | null
  quickLabelPending: boolean
  selected: boolean
  onToggleSelect: (traceId: string) => void
  pinned: boolean
  onTogglePin: (traceId: string) => void
  noteSummary: string
  noteDraft: string
  noteEditorOpen: boolean
  noteLoading: boolean
  noteSaving: boolean
  onOpenNoteEditor: (traceId: string) => void
  onChangeNoteDraft: (traceId: string, value: string) => void
  onCloseNoteEditor: (traceId: string) => void
  onSaveNote: (traceId: string) => void
}) {
  const [copiedTraceId, setCopiedTraceId] = useState(false)
  const [copiedTraceLink, setCopiedTraceLink] = useState(false)
  const traceUrl = `${window.location.origin}${window.location.pathname}/${trace.id}`
  const riskFlags = getTraceRiskFlags(trace)

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

  const handleQuickLabel = (event: MouseEvent<HTMLButtonElement>, label: QuickLabelValue) => {
    event.preventDefault()
    event.stopPropagation()
    onQuickLabel(trace.id, label)
  }

  const handleToggleSelect = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    onToggleSelect(trace.id)
  }

  const handleTogglePin = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    onTogglePin(trace.id)
  }

  const handleOpenNoteEditor = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    onOpenNoteEditor(trace.id)
  }

  const handleSaveNote = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    onSaveNote(trace.id)
  }

  const handleCloseNoteEditor = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    event.stopPropagation()
    onCloseNoteEditor(trace.id)
  }

  return (
    <Link
      to={`/traces/${trace.id}`}
      className={clsx(
        'block hover:bg-dark-800 transition-colors',
        selected && 'bg-primary-600/5 border-l-2 border-primary-500'
      )}
    >
      <div className="px-6 py-4 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <button
              type="button"
              onClick={handleToggleSelect}
              aria-label={selected ? `Deselect trace ${trace.id}` : `Select trace ${trace.id}`}
              className={clsx(
                'inline-flex items-center rounded-md border px-2 py-0.5 text-xs transition-colors',
                selected
                  ? 'border-primary-500 text-primary-300 bg-primary-600/10'
                  : 'border-dark-700 text-muted-400 hover:text-muted-200'
              )}
            >
              {selected ? 'Selected' : 'Select'}
            </button>
            <button
              type="button"
              onClick={handleTogglePin}
              aria-label={pinned ? `Unpin trace ${trace.id}` : `Pin trace ${trace.id}`}
              className={clsx(
                'inline-flex items-center rounded-md border px-2 py-0.5 text-xs transition-colors',
                pinned
                  ? 'border-amber-500 text-amber-300 bg-amber-500/10'
                  : 'border-dark-700 text-muted-400 hover:text-muted-200'
              )}
            >
              {pinned ? 'Pinned' : 'Pin'}
            </button>
          </div>
          <div className="flex items-center gap-3">
            <p className="text-sm font-medium text-muted-100 truncate">{trace.name}</p>
            <StatusBadge status={trace.status} />
            {riskFlags.map((flag) => (
              <span
                key={flag.key}
                className={clsx(
                  'inline-flex items-center rounded-full px-2 py-0.5 text-xs border',
                  flag.level === 'high'
                    ? 'bg-red-900/30 border-red-700 text-red-300'
                    : 'bg-amber-900/30 border-amber-700 text-amber-300'
                )}
              >
                {flag.label}
              </span>
            ))}
          </div>
          <p className="mt-1 text-sm text-muted-400">
            {trace.span_count} spans
            {trace.total_tokens && ` · ${trace.total_tokens.toLocaleString()} tokens`}
            {trace.total_cost && ` · ${formatCost(trace.total_cost)}`}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-500">Quick label:</span>
            {QUICK_LABEL_OPTIONS.map((labelOption) => {
              const isActive = activeQuickLabel === labelOption.value
              return (
                <button
                  key={labelOption.value}
                  type="button"
                  onClick={(event) => handleQuickLabel(event, labelOption.value)}
                  disabled={quickLabelPending}
                  className={clsx(
                    'px-2 py-0.5 text-xs rounded-full border transition-colors',
                    isActive
                      ? 'bg-primary-600/20 border-primary-500 text-primary-300'
                      : 'bg-dark-900 border-dark-700 text-muted-300 hover:text-muted-100 hover:border-muted-500',
                    quickLabelPending && 'opacity-60 cursor-not-allowed'
                  )}
                >
                  {quickLabelPending && isActive ? 'Saving...' : labelOption.label}
                </button>
              )
            })}
            <button
              type="button"
              onClick={handleOpenNoteEditor}
              className="px-2 py-0.5 text-xs rounded-full border bg-dark-900 border-dark-700 text-muted-300 hover:text-muted-100 hover:border-muted-500"
              aria-label={`Edit note for ${trace.id}`}
            >
              {noteSummary ? 'Edit note' : 'Add note'}
            </button>
          </div>
          {noteSummary && !noteEditorOpen && (
            <p className="mt-2 text-xs text-muted-400 truncate" title={noteSummary}>
              Note: {noteSummary}
            </p>
          )}
          {noteEditorOpen && (
            <div
              className="mt-2 flex items-center gap-2"
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
              }}
            >
              <input
                value={noteDraft}
                onChange={(event) => onChangeNoteDraft(trace.id, event.target.value)}
                placeholder={noteLoading ? 'Loading note...' : 'Add handoff note'}
                disabled={noteLoading || noteSaving}
                className="flex-1 min-w-0 bg-dark-900 border border-dark-700 rounded px-2 py-1 text-xs text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <button
                type="button"
                onClick={handleSaveNote}
                disabled={noteLoading || noteSaving}
                className="px-2 py-1 text-xs rounded border border-primary-500 text-primary-300 bg-primary-600/10 hover:bg-primary-600/20 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {noteSaving ? 'Saving...' : 'Save'}
              </button>
              <button
                type="button"
                onClick={handleCloseNoteEditor}
                disabled={noteSaving}
                className="px-2 py-1 text-xs rounded border border-dark-700 text-muted-300 hover:text-muted-100 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
            </div>
          )}
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
  const filtersInitializedRef = useRef(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [minTokens, setMinTokens] = useState('')
  const [minCost, setMinCost] = useState('')
  const [hasErrors, setHasErrors] = useState<HasErrorsFilter>('')
  const [pinnedOnly, setPinnedOnly] = useState(false)
  const [sortBy, setSortBy] = useState<SortBy>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const [summaryWindowDays, setSummaryWindowDays] = useState<7 | 30>(7)
  const [savedFilterName, setSavedFilterName] = useState('')
  const [savedFilterPresets, setSavedFilterPresets] = useState<SavedFilterPreset[]>(() => getSavedFilterPresets())
  const [quickLabels, setQuickLabels] = useState<Record<string, QuickLabelValue>>({})
  const [pendingQuickLabels, setPendingQuickLabels] = useState<Record<string, boolean>>({})
  const [selectedTraceIds, setSelectedTraceIds] = useState<string[]>([])
  const [pinnedTraceIds, setPinnedTraceIds] = useState<string[]>(() => getPinnedTraceIds())
  const [copiedEmptyStateCommand, setCopiedEmptyStateCommand] = useState<string | null>(null)
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({})
  const [openNoteEditors, setOpenNoteEditors] = useState<Record<string, boolean>>({})
  const [loadingNotes, setLoadingNotes] = useState<Record<string, boolean>>({})
  const [pendingNoteSaves, setPendingNoteSaves] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const parsed = getFiltersFromSearchParams(searchParams)

    if (!filtersInitializedRef.current) {
      const saved = getSavedFilters()
      setSearch(searchParams.has('q') ? parsed.search : saved?.search || '')
      setStatusFilter(searchParams.has('status') ? parsed.statusFilter : saved?.statusFilter || '')
      setMinTokens(searchParams.has('min_tokens') ? parsed.minTokens : saved?.minTokens || '')
      setMinCost(searchParams.has('min_cost') ? parsed.minCost : saved?.minCost || '')
      setHasErrors(searchParams.has('has_errors') ? parsed.hasErrors : saved?.hasErrors || '')
      setPinnedOnly(searchParams.has('pinned_only') ? parsed.pinnedOnly : saved?.pinnedOnly || false)
      setSortBy(parsed.sortBy || saved?.sortBy || 'created_at')
      setSortOrder(parsed.sortOrder || saved?.sortOrder || 'desc')
      filtersInitializedRef.current = true
      return
    }

    setSearch(parsed.search)
    setStatusFilter(parsed.statusFilter)
    setMinTokens(parsed.minTokens)
    setMinCost(parsed.minCost)
    setHasErrors(parsed.hasErrors)
    setPinnedOnly(parsed.pinnedOnly)
    setSortBy(parsed.sortBy || 'created_at')
    setSortOrder(parsed.sortOrder || 'desc')
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
          pinnedOnly,
          sortBy,
          sortOrder,
        })
      )
    } catch {
      // Ignore storage failures (for example in restricted environments).
    }
  }, [hasErrors, minCost, minTokens, pinnedOnly, search, sortBy, sortOrder, statusFilter])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(FILTER_PRESETS_STORAGE_KEY, JSON.stringify(savedFilterPresets))
    } catch {
      // Ignore storage failures (for example in restricted environments).
    }
  }, [savedFilterPresets])

  useEffect(() => {
    const next = buildSearchParamsFromFilters({
      search,
      statusFilter,
      minTokens,
      minCost,
      hasErrors,
      pinnedOnly,
      sortBy,
      sortOrder,
    })

    const current = new URLSearchParams(searchParams)
    if (next.toString() !== current.toString()) {
      setSearchParams(next, { replace: true })
    }
  }, [hasErrors, minCost, minTokens, pinnedOnly, search, searchParams, setSearchParams, sortBy, sortOrder, statusFilter])

  useEffect(() => {
    setPage(1)
  }, [search, statusFilter, minTokens, minCost, hasErrors, pinnedOnly, sortBy, sortOrder])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return
    }

    try {
      window.localStorage.setItem(PINNED_TRACES_STORAGE_KEY, JSON.stringify(pinnedTraceIds))
    } catch {
      // Ignore storage failures.
    }
  }, [pinnedTraceIds])

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
        queryClient.invalidateQueries({ queryKey: ['project-budget-status'] })
      }
    },
  })

  const handleSubmitRuntimeApiKey = (apiKey: string) => {
    setRuntimeWebSocketKey(apiKey)
    queryClient.invalidateQueries()
  }

  const traceQueryLimit = pinnedOnly ? 500 : PAGE_SIZE

  const { data, isLoading, error } = useQuery({
    queryKey: ['traces', page, statusFilter, queryOptions, traceQueryLimit],
    queryFn: () =>
      getTraces(
        traceQueryLimit,
        pinnedOnly ? 0 : (page - 1) * PAGE_SIZE,
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

  const budgetStatusQuery = useQuery({
    queryKey: ['project-budget-status'],
    queryFn: getProjectBudgetStatus,
    refetchInterval: connected ? false : 15000,
    retry: false,
  })
  const budgetStatusData = budgetStatusQuery.data
  const hasBudgetStatusData =
    budgetStatusData &&
    typeof budgetStatusData.tokens_used === 'number' &&
    typeof budgetStatusData.cost_used === 'number' &&
    typeof budgetStatusData.alert_threshold_percent === 'number' &&
    typeof budgetStatusData.hard_stop_enabled === 'boolean'

  const incidentsQuery = useQuery({
    queryKey: ['intelligence-incidents'],
    queryFn: () => getIntelligenceIncidents({ limit: 5, minRisk: 1 }),
    refetchInterval: connected ? false : 10000,
    retry: false,
  })
  const incidentRows = incidentsQuery.data?.incidents ?? []

  const pinnedTraceIdSet = useMemo(() => new Set(pinnedTraceIds), [pinnedTraceIds])
  const visibleTraces = useMemo(() => {
    const traces = data?.traces || []
    return pinnedOnly ? traces.filter((trace) => pinnedTraceIdSet.has(trace.id)) : traces
  }, [data?.traces, pinnedOnly, pinnedTraceIdSet])

  const visibleTotal = pinnedOnly ? visibleTraces.length : (data?.total ?? 0)
  const totalPages = pinnedOnly ? 1 : data?.total ? Math.ceil(data.total / PAGE_SIZE) : 1
  const hasNextPage = page < totalPages
  const hasPrevPage = page > 1
  const hasActiveFilters =
    Boolean(search) ||
    Boolean(statusFilter) ||
    Boolean(hasErrors) ||
    Boolean(minTokens) ||
    Boolean(minCost) ||
    pinnedOnly
  const currentFilters: FilterState = useMemo(
    () => ({
      search,
      statusFilter,
      minTokens,
      minCost,
      hasErrors,
      pinnedOnly,
      sortBy,
      sortOrder,
    }),
    [hasErrors, minCost, minTokens, pinnedOnly, search, sortBy, sortOrder, statusFilter]
  )
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
    pinnedOnly
      ? {
          key: 'pinnedOnly',
          label: 'Pinned only',
          clear: () => setPinnedOnly(false),
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

  const authKeyConfigured = Boolean(getEffectiveApiKey())

  const curatedTracesQuery = useQuery({
    queryKey: ['curated-traces', 'notes-cache'],
    queryFn: () => getCuratedTraces({ limit: 200, offset: 0 }),
    refetchInterval: connected ? false : 10000,
  })

  const curatedNotesByTrace = useMemo(() => {
    const map: Record<string, string> = {}
    const curatedRows = Array.isArray(curatedTracesQuery.data) ? curatedTracesQuery.data : []
    curatedRows.forEach((item) => {
      map[item.trace_id] = item.notes ?? ''
    })
    return map
  }, [curatedTracesQuery.data])

  const quickLabelMutation = useMutation({
    mutationFn: ({ traceId, label }: { traceId: string; label: QuickLabelValue }) =>
      createOrUpdateLabel({ trace_id: traceId, label }),
    onMutate: ({ traceId }) => {
      setPendingQuickLabels((prev) => ({ ...prev, [traceId]: true }))
    },
    onSuccess: (result) => {
      const nextLabel = result.label
      if (nextLabel === 'good' || nextLabel === 'needs_improvement' || nextLabel === 'failure') {
        setQuickLabels((prev) => ({ ...prev, [result.trace_id]: nextLabel }))
      }
      queryClient.invalidateQueries({ queryKey: ['curation-label', result.trace_id] })
      queryClient.invalidateQueries({ queryKey: ['curated-traces'] })
      queryClient.invalidateQueries({ queryKey: ['curation-stats'] })
    },
    onSettled: (_result, _error, variables) => {
      setPendingQuickLabels((prev) => {
        const next = { ...prev }
        delete next[variables.traceId]
        return next
      })
    },
  })

  const bulkQuickLabelMutation = useMutation({
    mutationFn: async ({ traceIds, label }: { traceIds: string[]; label: QuickLabelValue }) =>
      Promise.all(traceIds.map((traceId) => createOrUpdateLabel({ trace_id: traceId, label }))),
    onMutate: ({ traceIds }) => {
      setPendingQuickLabels((prev) => {
        const next = { ...prev }
        traceIds.forEach((traceId) => {
          next[traceId] = true
        })
        return next
      })
    },
    onSuccess: (results) => {
      setQuickLabels((prev) => {
        const next = { ...prev }
        results.forEach((result) => {
          if (result.label === 'good' || result.label === 'needs_improvement' || result.label === 'failure') {
            next[result.trace_id] = result.label
          }
        })
        return next
      })
      queryClient.invalidateQueries({ queryKey: ['curated-traces'] })
      queryClient.invalidateQueries({ queryKey: ['curation-stats'] })
    },
    onSettled: (_result, _error, variables) => {
      setPendingQuickLabels((prev) => {
        const next = { ...prev }
        variables.traceIds.forEach((traceId) => {
          delete next[traceId]
        })
        return next
      })
    },
  })

  const saveNoteMutation = useMutation({
    mutationFn: async ({ traceId, notes }: { traceId: string; notes: string }) =>
      createOrUpdateLabel({ trace_id: traceId, notes }),
    onMutate: ({ traceId }) => {
      setPendingNoteSaves((prev) => ({ ...prev, [traceId]: true }))
    },
    onSuccess: (result) => {
      setNoteDrafts((prev) => ({ ...prev, [result.trace_id]: result.notes || '' }))
      setOpenNoteEditors((prev) => ({ ...prev, [result.trace_id]: false }))
      queryClient.invalidateQueries({ queryKey: ['curation-label', result.trace_id] })
      queryClient.invalidateQueries({ queryKey: ['curated-traces'] })
    },
    onSettled: (_result, _error, variables) => {
      setPendingNoteSaves((prev) => {
        const next = { ...prev }
        delete next[variables.traceId]
        return next
      })
    },
  })

  const applyFilters = (nextFilters: FilterState) => {
    setSearch(nextFilters.search)
    setStatusFilter(nextFilters.statusFilter)
    setMinTokens(nextFilters.minTokens)
    setMinCost(nextFilters.minCost)
    setHasErrors(nextFilters.hasErrors)
    setPinnedOnly(nextFilters.pinnedOnly)
    setSortBy(nextFilters.sortBy)
    setSortOrder(nextFilters.sortOrder)
  }

  const handleSaveFilterPreset = () => {
    const name = savedFilterName.trim()
    if (!name) {
      return
    }

    const normalizedName = name.toLowerCase()
    const existing = savedFilterPresets.find((preset) => preset.name.toLowerCase() === normalizedName)
    if (existing) {
      setSavedFilterPresets((prev) =>
        prev.map((preset) => (preset.id === existing.id ? { ...preset, name, filters: currentFilters } : preset))
      )
    } else {
      const newPreset: SavedFilterPreset = {
        id: `preset-${Date.now().toString(36)}`,
        name,
        filters: currentFilters,
      }
      setSavedFilterPresets((prev) => [newPreset, ...prev].slice(0, 8))
    }

    setSavedFilterName('')
  }

  const handleDeleteFilterPreset = (presetId: string) => {
    setSavedFilterPresets((prev) => prev.filter((preset) => preset.id !== presetId))
  }

  const handleQuickLabel = (traceId: string, label: QuickLabelValue) => {
    if (pendingQuickLabels[traceId]) {
      return
    }
    quickLabelMutation.mutate({ traceId, label })
  }

  const handleToggleTraceSelection = (traceId: string) => {
    setSelectedTraceIds((prev) =>
      prev.includes(traceId) ? prev.filter((id) => id !== traceId) : [...prev, traceId]
    )
  }

  const handleTogglePinned = (traceId: string) => {
    setPinnedTraceIds((prev) =>
      prev.includes(traceId) ? prev.filter((id) => id !== traceId) : [traceId, ...prev].slice(0, 500)
    )
  }

  const handleBulkQuickLabel = (label: QuickLabelValue) => {
    if (selectedTraceIds.length === 0 || bulkQuickLabelMutation.isPending) {
      return
    }
    bulkQuickLabelMutation.mutate({ traceIds: selectedTraceIds, label })
  }

  const handleCopyCommand = async (command: string) => {
    try {
      if (!navigator.clipboard?.writeText) {
        return
      }
      await navigator.clipboard.writeText(command)
      setCopiedEmptyStateCommand(command)
      window.setTimeout(() => setCopiedEmptyStateCommand((current) => (current === command ? null : current)), 1200)
    } catch {
      // Clipboard is convenience-only in this view.
    }
  }

  const handleOpenNoteEditor = async (traceId: string) => {
    setOpenNoteEditors((prev) => ({ ...prev, [traceId]: true }))
    if (noteDrafts[traceId] !== undefined) {
      return
    }
    if (curatedNotesByTrace[traceId] !== undefined) {
      setNoteDrafts((prev) => ({ ...prev, [traceId]: curatedNotesByTrace[traceId] }))
      return
    }

    setLoadingNotes((prev) => ({ ...prev, [traceId]: true }))
    const label = await getLabel(traceId)
    setNoteDrafts((prev) => ({ ...prev, [traceId]: label?.notes || '' }))
    setLoadingNotes((prev) => {
      const next = { ...prev }
      delete next[traceId]
      return next
    })
  }

  const handleCloseNoteEditor = (traceId: string) => {
    setOpenNoteEditors((prev) => ({ ...prev, [traceId]: false }))
  }

  const handleChangeNoteDraft = (traceId: string, value: string) => {
    setNoteDrafts((prev) => ({ ...prev, [traceId]: value }))
  }

  const handleSaveNote = (traceId: string) => {
    if (pendingNoteSaves[traceId]) {
      return
    }
    saveNoteMutation.mutate({ traceId, notes: noteDrafts[traceId] || '' })
  }

  useEffect(() => {
    const visibleTraceIds = new Set(visibleTraces.map((trace) => trace.id))
    setSelectedTraceIds((prev) => prev.filter((traceId) => visibleTraceIds.has(traceId)))
  }, [visibleTraces])

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
            {visibleTotal} traces {pinnedOnly ? 'in pinned view' : 'recorded'}
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

      <WebSocketRecoveryPanel
        isConnected={connected}
        lastDisconnect={lastDisconnect}
        authKeyConfigured={authKeyConfigured}
        onRetry={reconnect}
        onSubmitApiKey={handleSubmitRuntimeApiKey}
        inputId="traces-ws-auth-key-input"
      />

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

      {hasBudgetStatusData && (
        <div
          className={clsx(
            'mb-4 rounded-lg border p-4',
            budgetStatusData.alert_triggered
              ? 'bg-amber-900/20 border-amber-700/60'
              : 'bg-dark-900 border-dark-700'
          )}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-muted-200">Budget Guardrails</h2>
            <span
              className={clsx(
                'text-xs px-2 py-1 rounded-full',
                budgetStatusData.hard_stop_enabled
                  ? 'bg-red-900/40 text-red-300'
                  : 'bg-dark-800 text-muted-300'
              )}
            >
              {budgetStatusData.hard_stop_enabled ? 'Hard stop on' : 'Hard stop off'}
            </span>
          </div>

          {budgetStatusData.monthly_token_limit === null &&
          budgetStatusData.monthly_cost_limit === null ? (
            <p className="text-xs text-muted-400">
              No monthly budget configured. Set token or cost limits via
              <code className="ml-1 text-muted-300">/api/v1/projects/me/budget</code>.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="bg-dark-800 rounded-lg p-3">
                <p className="text-xs text-muted-400">Token budget</p>
                <p className="text-sm text-muted-100 mt-1">
                  {budgetStatusData.tokens_used.toLocaleString()}
                  {budgetStatusData.monthly_token_limit !== null
                    ? ` / ${budgetStatusData.monthly_token_limit.toLocaleString()}`
                    : ''}
                </p>
                <p
                  className={clsx(
                    'text-xs mt-1',
                    budgetStatusData.token_usage_percent !== null &&
                      budgetStatusData.token_usage_percent >= budgetStatusData.alert_threshold_percent
                      ? 'text-amber-300'
                      : 'text-muted-400'
                  )}
                >
                  {formatBudgetPercent(budgetStatusData.token_usage_percent)}
                </p>
              </div>
              <div className="bg-dark-800 rounded-lg p-3">
                <p className="text-xs text-muted-400">Cost budget</p>
                <p className="text-sm text-muted-100 mt-1">
                  ${budgetStatusData.cost_used.toFixed(4)}
                  {budgetStatusData.monthly_cost_limit !== null
                    ? ` / $${budgetStatusData.monthly_cost_limit.toFixed(4)}`
                    : ''}
                </p>
                <p
                  className={clsx(
                    'text-xs mt-1',
                    budgetStatusData.cost_usage_percent !== null &&
                      budgetStatusData.cost_usage_percent >= budgetStatusData.alert_threshold_percent
                      ? 'text-amber-300'
                      : 'text-muted-400'
                  )}
                >
                  {formatBudgetPercent(budgetStatusData.cost_usage_percent)}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mb-4 bg-dark-900 rounded-lg border border-dark-700 p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-muted-200">Incident Feed</h2>
          {incidentsQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-500" />}
        </div>
        {incidentsQuery.isError && (
          <p className="text-xs text-amber-300">
            Could not load incident feed. Trace ingestion and guardrails continue normally.
          </p>
        )}
        {!incidentsQuery.isError && incidentRows.length === 0 && (
          <p className="text-xs text-muted-400">
            No active high-risk regression incidents.
          </p>
        )}
        {incidentRows.length > 0 && (
          <div className="space-y-2">
            {incidentRows.map((incident) => (
                <div
                  key={incident.trace_id}
                  className="rounded-lg border border-dark-700 bg-dark-800 p-3 flex items-start justify-between gap-3"
                >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      to={`/traces/${encodeURIComponent(incident.trace_id)}`}
                      className="text-sm text-primary-300 hover:text-primary-200 truncate"
                    >
                      {incident.trace_name || incident.trace_id}
                    </Link>
                    <span className="text-xs text-muted-500">
                      {incident.created_at
                        ? formatDistanceToNow(new Date(incident.created_at), { addSuffix: true })
                        : ''}
                    </span>
                  </div>
                  {incident.top_signal && (
                    <p className="mt-1 text-xs text-muted-300">{incident.top_signal}</p>
                  )}
                  {incident.top_actions[0] && (
                    <p className="mt-1 text-xs text-muted-400">
                      Next step: {incident.top_actions[0]}
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {incident.baseline_trace_id && (
                      <Link
                        to={`/compare?traceA=${encodeURIComponent(incident.baseline_trace_id)}&traceB=${encodeURIComponent(incident.trace_id)}`}
                        className="inline-flex items-center gap-1 rounded-md border border-dark-600 px-2 py-1 text-xs text-muted-200 hover:text-muted-100"
                      >
                        <Link2 className="h-3 w-3" />
                        Compare
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => handleQuickLabel(incident.trace_id, 'failure')}
                      disabled={Boolean(pendingQuickLabels[incident.trace_id])}
                      className={clsx(
                        'rounded-md border px-2 py-1 text-xs transition-colors',
                        pendingQuickLabels[incident.trace_id]
                          ? 'border-dark-700 text-muted-500 cursor-not-allowed'
                          : 'border-red-800 text-red-300 hover:text-red-200'
                      )}
                    >
                      {pendingQuickLabels[incident.trace_id] ? 'Saving...' : 'Mark failure'}
                    </button>
                  </div>
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  <span
                    className={clsx(
                      'px-2 py-0.5 rounded-full text-xs capitalize',
                      incident.risk_level === 'critical'
                        ? 'bg-red-900/40 text-red-300'
                        : incident.risk_level === 'high'
                          ? 'bg-amber-900/40 text-amber-300'
                          : incident.risk_level === 'medium'
                            ? 'bg-yellow-900/35 text-yellow-300'
                            : 'bg-dark-700 text-muted-300'
                    )}
                  >
                    {incident.risk_level}
                  </span>
                  <span className="text-xs text-muted-400">
                    risk {incident.risk_score}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
              setPinnedOnly(false)
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
              setPinnedOnly(false)
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
              setPinnedOnly(false)
              setSortBy('total_cost')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
          >
            Preset: High cost
          </button>
          <button
            onClick={() => setPinnedOnly((prev) => !prev)}
            className={clsx(
              'px-3 py-2 text-xs border rounded-lg',
              pinnedOnly
                ? 'bg-amber-600/10 border-amber-500 text-amber-300'
                : 'bg-dark-800 border-dark-700 text-muted-200 hover:bg-dark-700'
            )}
          >
            Pinned only
          </button>
          <button
            onClick={() => {
              setStatusFilter('')
              setSearch('')
              setMinTokens('')
              setMinCost('')
              setHasErrors('')
              setPinnedOnly(false)
              setSortBy('created_at')
              setSortOrder('desc')
            }}
            className="px-3 py-2 text-xs bg-dark-900 border border-dark-700 rounded-lg text-muted-300 hover:bg-dark-800"
          >
            Clear
          </button>
        </div>

        <div className="pt-2 border-t border-dark-700/70 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={savedFilterName}
              onChange={(event) => setSavedFilterName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  handleSaveFilterPreset()
                }
              }}
              placeholder="Preset name"
              aria-label="Saved filter name"
              className="min-w-[180px] flex-1 max-w-sm bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
            <button
              onClick={handleSaveFilterPreset}
              disabled={!savedFilterName.trim()}
              className={clsx(
                'px-3 py-2 text-xs rounded-lg border',
                savedFilterName.trim()
                  ? 'bg-primary-600 border-primary-500 text-white hover:bg-primary-700'
                  : 'bg-dark-800 border-dark-700 text-muted-500 cursor-not-allowed'
              )}
            >
              Save current filter
            </button>
          </div>

          {savedFilterPresets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {savedFilterPresets.map((preset) => (
                <div key={preset.id} className="inline-flex items-center rounded-lg border border-dark-700 bg-dark-800">
                  <button
                    onClick={() => applyFilters(preset.filters)}
                    className="px-2.5 py-1.5 text-xs text-muted-200 hover:text-muted-100"
                    title={`Apply saved filter: ${preset.name}`}
                  >
                    {preset.name}
                  </button>
                  <button
                    onClick={() => handleDeleteFilterPreset(preset.id)}
                    className="px-2 py-1.5 text-xs text-muted-500 hover:text-red-400 border-l border-dark-700"
                    aria-label={`Delete saved filter ${preset.name}`}
                    title={`Delete saved filter ${preset.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
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
                setPinnedOnly(false)
              }}
              className="px-3 py-1.5 text-xs bg-dark-800 border border-primary-500 text-primary-300 rounded-lg hover:bg-dark-700"
            >
              Clear all filters
            </button>
          </div>
        )}
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 divide-y divide-dark-700">
        {selectedTraceIds.length > 0 && (
          <div className="px-6 py-3 flex flex-wrap items-center justify-between gap-2 bg-dark-800/80 border-b border-dark-700">
            <div className="flex items-center gap-2 text-xs text-muted-300">
              <span>{selectedTraceIds.length} selected</span>
              <button
                type="button"
                onClick={() => setSelectedTraceIds([])}
                className="text-muted-400 hover:text-muted-200"
              >
                Clear selection
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {QUICK_LABEL_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => handleBulkQuickLabel(option.value)}
                  disabled={bulkQuickLabelMutation.isPending}
                  className="px-2.5 py-1 text-xs rounded-lg border border-dark-600 bg-dark-700 text-muted-200 hover:bg-dark-600 disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  Label selected: {option.label}
                </button>
              ))}
              {selectedTraceIds.length === 2 ? (
                <Link
                  to={`/compare?traceA=${encodeURIComponent(selectedTraceIds[0])}&traceB=${encodeURIComponent(selectedTraceIds[1])}`}
                  className="px-2.5 py-1 text-xs rounded-lg border border-primary-500 bg-primary-600/10 text-primary-200 hover:bg-primary-600/20"
                >
                  Compare selected
                </Link>
              ) : (
                <button
                  type="button"
                  disabled
                  className="px-2.5 py-1 text-xs rounded-lg border border-dark-700 bg-dark-800 text-muted-500 cursor-not-allowed"
                >
                  Compare selected (pick 2)
                </button>
              )}
            </div>
          </div>
        )}
        {visibleTraces.length === 0 ? (
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
                    setPinnedOnly(false)
                  }}
                  className="px-3 py-1.5 text-xs bg-dark-800 border border-dark-700 rounded-lg text-muted-200 hover:bg-dark-700"
                >
                  Clear all filters
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-muted-400">No traces yet. Start your first run:</p>
                <div className="grid gap-2 max-w-2xl mx-auto text-left">
                  {[
                    { title: 'Start local stack', command: './demo.sh' },
                    {
                      title: 'Send a first trace',
                      command: 'python -m examples.code_agent.run "How does the intelligence module work?"',
                    },
                  ].map((item) => (
                    <div key={item.command} className="bg-dark-800 border border-dark-700 rounded-lg px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs text-muted-400">{item.title}</p>
                        <button
                          type="button"
                          onClick={() => handleCopyCommand(item.command)}
                          className="inline-flex items-center gap-1 text-xs text-muted-300 hover:text-muted-100"
                          aria-label={`Copy command: ${item.title}`}
                        >
                          <ClipboardCopy className="h-3.5 w-3.5" />
                          {copiedEmptyStateCommand === item.command ? 'Copied' : 'Copy'}
                        </button>
                      </div>
                      <code className="mt-1 block text-xs text-muted-100 break-all">{item.command}</code>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          visibleTraces.map((trace) => (
            <TraceRow
              key={trace.id}
              trace={trace}
              onQuickLabel={handleQuickLabel}
              activeQuickLabel={quickLabels[trace.id] || null}
              quickLabelPending={Boolean(pendingQuickLabels[trace.id])}
              selected={selectedTraceIds.includes(trace.id)}
              onToggleSelect={handleToggleTraceSelection}
              pinned={pinnedTraceIdSet.has(trace.id)}
              onTogglePin={handleTogglePinned}
              noteSummary={noteDrafts[trace.id] ?? curatedNotesByTrace[trace.id] ?? ''}
              noteDraft={noteDrafts[trace.id] ?? ''}
              noteEditorOpen={Boolean(openNoteEditors[trace.id])}
              noteLoading={Boolean(loadingNotes[trace.id])}
              noteSaving={Boolean(pendingNoteSaves[trace.id])}
              onOpenNoteEditor={handleOpenNoteEditor}
              onChangeNoteDraft={handleChangeNoteDraft}
              onCloseNoteEditor={handleCloseNoteEditor}
              onSaveNote={handleSaveNote}
            />
          ))
        )}
      </div>

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-muted-400">
            Showing {((page - 1) * PAGE_SIZE) + 1} - {Math.min(page * PAGE_SIZE, visibleTotal)} of {visibleTotal}
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
