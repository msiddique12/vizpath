import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, GitCompare, X, ArrowLeftRight, Sparkles, BookmarkPlus, Trash2, BookOpen } from 'lucide-react'
import clsx from 'clsx'
import { useSearchParams } from 'react-router-dom'
import { compareTraces, getTraces, getTrace } from '@/lib/api'
import { Trace } from '@/lib/types'
import TraceComparison from '@/components/TraceComparison'

interface SavedComparePreset {
  id: string
  name: string
  traceA: string
  traceB: string
  createdAt: string
}

const COMPARE_PRESETS_STORAGE_KEY = 'compare_presets_v1'

export default function ComparisonPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const loadPresetsFromStorage = useCallback(() => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') {
      return []
    }

    try {
      const raw = window.localStorage.getItem(COMPARE_PRESETS_STORAGE_KEY)
      if (!raw) return []
      const parsed = JSON.parse(raw) as SavedComparePreset[]
      if (!Array.isArray(parsed)) return []

      return parsed
        .filter(
          (preset): preset is SavedComparePreset =>
            typeof preset?.id === 'string' &&
            typeof preset?.name === 'string' &&
            typeof preset?.traceA === 'string' &&
            typeof preset?.traceB === 'string'
        )
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    } catch {
      return []
    }
  }, [])

  const getPresetById = useCallback((presetId: string | null): SavedComparePreset | null => {
    if (!presetId) return null
    const saved = loadPresetsFromStorage()
    return saved.find((preset) => preset.id === presetId) || null
  }, [loadPresetsFromStorage])

  const queryTraceA = searchParams.get('traceA')
  const queryTraceB = searchParams.get('traceB')
  const presetFromQuery = searchParams.get('preset')

  const [selectedTraceA, setSelectedTraceA] = useState<string | null>(
    queryTraceA
  )
  const [selectedTraceB, setSelectedTraceB] = useState<string | null>(
    queryTraceB
  )
  const [presetName, setPresetName] = useState('')
  const [savedPresets, setSavedPresets] = useState<SavedComparePreset[]>([])

  const { data: tracesData, isLoading: tracesLoading } = useQuery({
    queryKey: ['traces', 50],
    queryFn: () => getTraces(50),
  })

  const { data: traceAData, isLoading: loadingA } = useQuery({
    queryKey: ['trace', selectedTraceA],
    queryFn: () => getTrace(selectedTraceA!),
    enabled: !!selectedTraceA,
  })

  const { data: traceBData, isLoading: loadingB } = useQuery({
    queryKey: ['trace', selectedTraceB],
    queryFn: () => getTrace(selectedTraceB!),
    enabled: !!selectedTraceB,
  })

  const { data: intelligenceCompare, isLoading: compareLoading } = useQuery({
    queryKey: ['trace-compare', selectedTraceA, selectedTraceB],
    queryFn: () => compareTraces(selectedTraceA!, selectedTraceB!),
    enabled: !!selectedTraceA && !!selectedTraceB,
  })

  const traces = useMemo(() => tracesData?.traces || [], [tracesData?.traces])

  const formatTimestamp = (ts: string) => {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  useEffect(() => {
    const next = new URLSearchParams(window.location.search)
    if (selectedTraceA) next.set('traceA', selectedTraceA)
    else next.delete('traceA')
    if (selectedTraceB) next.set('traceB', selectedTraceB)
    else next.delete('traceB')

    const currentSearch = window.location.search.startsWith('?')
      ? window.location.search.slice(1)
      : window.location.search
    if (next.toString() === currentSearch) return

    setSearchParams(next, { replace: true })
  }, [selectedTraceA, selectedTraceB, setSearchParams])

  useEffect(() => {
    const nextTraceA = searchParams.get('traceA')
    const nextTraceB = searchParams.get('traceB')
    const preset = getPresetById(presetFromQuery)
    const resolvedTraceA = nextTraceA ?? preset?.traceA ?? null
    const resolvedTraceB = nextTraceB ?? preset?.traceB ?? null

    if (resolvedTraceA === selectedTraceA && resolvedTraceB === selectedTraceB) return

    setSelectedTraceA(resolvedTraceA)
    setSelectedTraceB(resolvedTraceB)
  }, [searchParams, selectedTraceA, selectedTraceB, presetFromQuery, getPresetById])

  const traceOptions = useMemo(
    () =>
      traces.map((trace: Trace) => ({
        id: trace.id,
        label: `${trace.name} - ${formatTimestamp(trace.created_at)}`,
      })),
    [traces]
  )

  const handleSelectTrace = (traceId: string, slot: 'A' | 'B') => {
    if (slot === 'A') {
      setSelectedTraceA(traceId)
    } else {
      setSelectedTraceB(traceId)
    }
  }

  useEffect(() => {
    setSavedPresets(loadPresetsFromStorage())
  }, [loadPresetsFromStorage])

  useEffect(() => {
    if (!searchParams.get('preset')) return

    const nextSearchParams = Object.fromEntries(searchParams.entries())
    delete nextSearchParams.preset
    setSearchParams(nextSearchParams, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!selectedTraceA || !selectedTraceB) return

    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return
    try {
      setSavedPresets(loadPresetsFromStorage())
    } catch {
      // ignore storage errors
    }
  }, [loadPresetsFromStorage, selectedTraceA, selectedTraceB])

  const persistPresets = (presets: SavedComparePreset[]) => {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

    window.localStorage.setItem(COMPARE_PRESETS_STORAGE_KEY, JSON.stringify(presets))
    setSavedPresets(presets)
  }

  const handleSavePreset = () => {
    if (!selectedTraceA || !selectedTraceB) return

    const trimmedName = presetName.trim() || `Compare ${selectedTraceA} vs ${selectedTraceB}`
    const id = crypto.randomUUID()
    const nextPreset: SavedComparePreset = {
      id,
      name: trimmedName,
      traceA: selectedTraceA,
      traceB: selectedTraceB,
      createdAt: new Date().toISOString(),
    }

    const nextPresets = [nextPreset, ...savedPresets.filter((preset) => preset.id !== id)]
    persistPresets(nextPresets)
    setPresetName('')
  }

  const handleLoadPreset = (preset: SavedComparePreset) => {
    setSearchParams(
      {
        ...Object.fromEntries(searchParams.entries()),
        traceA: preset.traceA,
        traceB: preset.traceB,
        preset: preset.id,
      },
      { replace: true }
    )
  }

  const handleDeletePreset = (id: string) => {
    persistPresets(savedPresets.filter((preset) => preset.id !== id))
  }

  const applyLatestTwo = () => {
    if (traces.length < 2) return
    setSelectedTraceA(traces[0].id)
    setSelectedTraceB(traces[1].id)
  }

  const swapSelected = () => {
    setSelectedTraceA(selectedTraceB)
    setSelectedTraceB(selectedTraceA)
  }

  const TraceSelector = ({
    slot,
    selected,
    onClear,
  }: {
    slot: 'A' | 'B'
    selected: string | null
    onClear: () => void
  }) => {
    const selectedTrace = traces.find((t: Trace) => t.id === selected)

    return (
      <div className="flex-1" data-testid={`trace-selector-${slot.toLowerCase()}`}>
        <label className="block text-sm font-medium text-muted-200 mb-2">Trace {slot}</label>
            {selected && selectedTrace ? (
              <div className="flex items-center gap-2 bg-primary-900/20 border border-primary-800 rounded-lg px-3 py-2">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-muted-100 truncate">{selectedTrace.name}</p>
              <p className="text-xs text-muted-400">{formatTimestamp(selectedTrace.created_at)}</p>
            </div>
            <button
              onClick={onClear}
              className="p-1 text-muted-400 hover:text-muted-200 rounded"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <select
            className="w-full bg-dark-800 border border-dark-700 text-muted-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            value=""
            onChange={(e) => handleSelectTrace(e.target.value, slot)}
          >
            <option value="">Select a trace...</option>
            {traceOptions
              .filter((t) => t.id !== (slot === 'A' ? selectedTraceB : selectedTraceA))
              .map((trace) => (
                <option key={trace.id} value={trace.id}>
                  {trace.label}
                </option>
              ))}
          </select>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-muted-100">Compare Traces</h1>
        <p className="mt-1 text-sm text-muted-400">
          Select two traces to compare their performance and structure
        </p>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-6">
        {tracesLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 text-primary-600 animate-spin" />
          </div>
        ) : traces.length === 0 ? (
          <div className="text-center py-8">
            <GitCompare className="h-12 w-12 text-muted-500 mx-auto mb-3" />
            <p className="text-muted-400">No traces available for comparison</p>
          </div>
        ) : (
          <>
            <div className="mb-4 space-y-3">
              <div className="text-xs uppercase tracking-wide text-muted-300">Saved Compare Presets</div>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={presetName}
                  onChange={(event) => setPresetName(event.target.value)}
                  placeholder="Preset name (optional)"
                  className="flex-1 min-w-[220px] bg-dark-800 border border-dark-700 rounded-lg px-3 py-2 text-sm text-muted-200 focus:outline-none focus:ring-2 focus:ring-primary-500"
                  aria-label="Compare preset name"
                />
                <button
                  type="button"
                  onClick={handleSavePreset}
                  disabled={!selectedTraceA || !selectedTraceB}
                  className={clsx(
                    'inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs border',
                    selectedTraceA && selectedTraceB
                      ? 'bg-dark-800 border-dark-700 text-muted-200 hover:bg-dark-700'
                      : 'bg-dark-900 border-dark-700 text-muted-500 cursor-not-allowed'
                  )}
                >
                  <BookmarkPlus className="h-3.5 w-3.5" />
                  Save preset
                </button>
              </div>

              {savedPresets.length === 0 ? (
                <p className="text-xs text-muted-400">No saved compare presets yet.</p>
              ) : (
                <div className="space-y-2">
                  {savedPresets.map((preset) => (
                    <div
                      key={preset.id}
                      data-testid={`compare-preset-${preset.id}`}
                      className="rounded-lg border border-dark-700 bg-dark-900 p-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="text-xs">
                        <p className="text-muted-200">{preset.name}</p>
                        <p className="text-muted-400 mt-1">
                          {preset.traceA} ↔ {preset.traceB}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleLoadPreset(preset)}
                          aria-label={`Load preset ${preset.name}`}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border border-dark-700 bg-dark-800 text-muted-200 hover:bg-dark-700"
                        >
                          <BookOpen className="h-3.5 w-3.5" />
                          Load
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeletePreset(preset.id)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border border-red-800 text-red-300 hover:bg-red-950/40"
                          aria-label={`Delete preset ${preset.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="mb-4 flex flex-wrap items-center gap-2">
              <button
                onClick={applyLatestTwo}
                disabled={traces.length < 2}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border',
                  traces.length >= 2
                    ? 'bg-dark-800 border-dark-700 text-muted-200 hover:bg-dark-700'
                    : 'bg-dark-900 border-dark-700 text-muted-500 cursor-not-allowed'
                )}
              >
                <Sparkles className="h-3.5 w-3.5" />
                Use latest two traces
              </button>
              <button
                onClick={swapSelected}
                disabled={!selectedTraceA || !selectedTraceB}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border',
                  selectedTraceA && selectedTraceB
                    ? 'bg-dark-800 border-dark-700 text-muted-200 hover:bg-dark-700'
                    : 'bg-dark-900 border-dark-700 text-muted-500 cursor-not-allowed'
                )}
              >
                <ArrowLeftRight className="h-3.5 w-3.5" />
                Swap A/B
              </button>
            </div>

            <div className="flex items-end gap-4 mb-6">
              <TraceSelector
                slot="A"
                selected={selectedTraceA}
                onClear={() => setSelectedTraceA(null)}
              />
              <div className="pb-2">
                <GitCompare className="h-5 w-5 text-muted-400" />
              </div>
              <TraceSelector
                slot="B"
                selected={selectedTraceB}
                onClear={() => setSelectedTraceB(null)}
              />
            </div>

            {selectedTraceA && selectedTraceB && (
              <div className="border-t border-dark-700 pt-6">
                {loadingA || loadingB ? (
                  <div className="flex items-center justify-center h-32">
                    <Loader2 className="h-6 w-6 text-primary-600 animate-spin" />
                  </div>
                ) : traceAData && traceBData ? (
                  <TraceComparison
                    traceA={traceAData}
                    traceB={traceBData}
                    intelligenceCompare={intelligenceCompare}
                    intelligenceCompareLoading={compareLoading}
                  />
                ) : (
                  <p className="text-muted-400 text-center py-8">
                    Failed to load trace data
                  </p>
                )}
              </div>
            )}

            {(!selectedTraceA || !selectedTraceB) && (
              <div
                className={clsx(
                  'border-2 border-dashed rounded-lg p-8 text-center',
                  'border-dark-600 text-muted-400'
                )}
              >
                <GitCompare className="h-10 w-10 mx-auto mb-3 opacity-50" />
                <p className="text-sm">Select two traces above to compare</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
