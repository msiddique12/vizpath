import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, GitCompare, X, ArrowLeftRight, Sparkles } from 'lucide-react'
import clsx from 'clsx'
import { useSearchParams } from 'react-router-dom'
import { compareTraces, getTraces, getTrace } from '@/lib/api'
import { Trace } from '@/lib/types'
import TraceComparison from '@/components/TraceComparison'

export default function ComparisonPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedTraceA, setSelectedTraceA] = useState<string | null>(
    searchParams.get('traceA')
  )
  const [selectedTraceB, setSelectedTraceB] = useState<string | null>(
    searchParams.get('traceB')
  )

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

  useEffect(() => {
    const next = new URLSearchParams(window.location.search)
    if (selectedTraceA) next.set('traceA', selectedTraceA)
    else next.delete('traceA')
    if (selectedTraceB) next.set('traceB', selectedTraceB)
    else next.delete('traceB')
    setSearchParams(next, { replace: true })
  }, [selectedTraceA, selectedTraceB, setSearchParams])

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

  const formatTimestamp = (ts: string) => {
    return new Date(ts).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
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
      <div className="flex-1">
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
