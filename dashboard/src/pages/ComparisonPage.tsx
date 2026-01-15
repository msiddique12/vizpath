import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, GitCompare, X } from 'lucide-react'
import clsx from 'clsx'
import { getTraces, getTrace } from '@/lib/api'
import { Trace } from '@/lib/types'
import TraceComparison from '@/components/TraceComparison'

export default function ComparisonPage() {
  const [selectedTraceA, setSelectedTraceA] = useState<string | null>(null)
  const [selectedTraceB, setSelectedTraceB] = useState<string | null>(null)

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

  const traces = tracesData?.traces || []

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
        <label className="block text-sm font-medium text-slate-700 mb-2">Trace {slot}</label>
        {selected && selectedTrace ? (
          <div className="flex items-center gap-2 bg-primary-50 border border-primary-200 rounded-lg px-3 py-2">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">{selectedTrace.name}</p>
              <p className="text-xs text-slate-500">{formatTimestamp(selectedTrace.created_at)}</p>
            </div>
            <button
              onClick={onClear}
              className="p-1 text-slate-400 hover:text-slate-600 rounded"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <select
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            value=""
            onChange={(e) => handleSelectTrace(e.target.value, slot)}
          >
            <option value="">Select a trace...</option>
            {traces
              .filter((t: Trace) => t.id !== (slot === 'A' ? selectedTraceB : selectedTraceA))
              .map((trace: Trace) => (
                <option key={trace.id} value={trace.id}>
                  {trace.name} - {formatTimestamp(trace.created_at)}
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
        <h1 className="text-2xl font-semibold text-slate-900">Compare Traces</h1>
        <p className="mt-1 text-sm text-slate-500">
          Select two traces to compare their performance and structure
        </p>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-6">
        {tracesLoading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-6 w-6 text-primary-600 animate-spin" />
          </div>
        ) : traces.length === 0 ? (
          <div className="text-center py-8">
            <GitCompare className="h-12 w-12 text-slate-300 mx-auto mb-3" />
            <p className="text-slate-500">No traces available for comparison</p>
          </div>
        ) : (
          <>
            <div className="flex items-end gap-4 mb-6">
              <TraceSelector
                slot="A"
                selected={selectedTraceA}
                onClear={() => setSelectedTraceA(null)}
              />
              <div className="pb-2">
                <GitCompare className="h-5 w-5 text-slate-400" />
              </div>
              <TraceSelector
                slot="B"
                selected={selectedTraceB}
                onClear={() => setSelectedTraceB(null)}
              />
            </div>

            {selectedTraceA && selectedTraceB && (
              <div className="border-t pt-6">
                {loadingA || loadingB ? (
                  <div className="flex items-center justify-center h-32">
                    <Loader2 className="h-6 w-6 text-primary-600 animate-spin" />
                  </div>
                ) : traceAData && traceBData ? (
                  <TraceComparison traceA={traceAData} traceB={traceBData} />
                ) : (
                  <p className="text-slate-500 text-center py-8">
                    Failed to load trace data
                  </p>
                )}
              </div>
            )}

            {(!selectedTraceA || !selectedTraceB) && (
              <div
                className={clsx(
                  'border-2 border-dashed rounded-lg p-8 text-center',
                  'border-slate-200 text-slate-400'
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
