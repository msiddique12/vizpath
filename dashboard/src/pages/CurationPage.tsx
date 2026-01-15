import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Loader2, Tag, Download, Star, CheckCircle } from 'lucide-react'
import clsx from 'clsx'
import { getCuratedTraces, getCurationStats, exportCuratedTraces, CuratedTrace } from '@/lib/api'
import { exportToJSONL } from '@/lib/export'

const LABEL_COLORS: Record<string, string> = {
  excellent: 'bg-green-100 text-green-700',
  good: 'bg-blue-100 text-blue-700',
  needs_improvement: 'bg-amber-100 text-amber-700',
  failure: 'bg-red-100 text-red-700',
  interesting: 'bg-purple-100 text-purple-700',
}

export default function CurationPage() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [labelFilter, setLabelFilter] = useState<string>('')

  const { data: traces, isLoading: tracesLoading } = useQuery({
    queryKey: ['curated-traces', labelFilter],
    queryFn: () => getCuratedTraces({ label: labelFilter || undefined, limit: 100 }),
  })

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['curation-stats'],
    queryFn: getCurationStats,
  })

  const exportMutation = useMutation({
    mutationFn: async () => {
      const result = await exportCuratedTraces({
        trace_ids: Array.from(selectedIds),
        format: 'jsonl',
        include_input_output: true,
      })
      return result
    },
    onSuccess: (data) => {
      const exportData = data.traces.map((t: unknown) => t)
      exportToJSONL(exportData as never[], `curated-traces-${data.count}.jsonl`)
      setSelectedIds(new Set())
    },
  })

  const toggleSelect = (id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  const toggleSelectAll = () => {
    if (!traces) return
    if (selectedIds.size === traces.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(traces.map((t) => t.trace_id)))
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Curation</h1>
        <p className="mt-1 text-sm text-slate-500">
          Manage labeled traces and export for training
        </p>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Total Labeled</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {statsLoading ? '-' : stats?.total_labeled || 0}
          </p>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Exported</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {statsLoading ? '-' : stats?.exported_count || 0}
          </p>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Avg Score</p>
          <p className="text-2xl font-semibold text-slate-900 mt-1">
            {statsLoading ? '-' : stats?.average_quality_score || '-'}
          </p>
        </div>
        <div className="bg-white rounded-lg border border-slate-200 p-4">
          <p className="text-xs text-slate-500 uppercase tracking-wide">Selected</p>
          <p className="text-2xl font-semibold text-primary-600 mt-1">{selectedIds.size}</p>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200">
        <div className="flex items-center justify-between p-4 border-b border-slate-200">
          <div className="flex items-center gap-3">
            <select
              value={labelFilter}
              onChange={(e) => setLabelFilter(e.target.value)}
              className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
            >
              <option value="">All labels</option>
              <option value="excellent">Excellent</option>
              <option value="good">Good</option>
              <option value="needs_improvement">Needs improvement</option>
              <option value="failure">Failure</option>
              <option value="interesting">Interesting</option>
            </select>
          </div>
          <button
            onClick={() => exportMutation.mutate()}
            disabled={selectedIds.size === 0 || exportMutation.isPending}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors',
              selectedIds.size > 0
                ? 'bg-primary-600 text-white hover:bg-primary-700'
                : 'bg-slate-100 text-slate-400 cursor-not-allowed'
            )}
          >
            {exportMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Export Selected ({selectedIds.size})
          </button>
        </div>

        {tracesLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
          </div>
        ) : !traces || traces.length === 0 ? (
          <div className="text-center py-12">
            <Tag className="h-12 w-12 text-slate-300 mx-auto mb-3" />
            <p className="text-slate-500">No curated traces yet</p>
            <p className="text-sm text-slate-400 mt-1">
              Label traces from the trace detail view to add them here
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={traces.length > 0 && selectedIds.size === traces.length}
                      onChange={toggleSelectAll}
                      className="rounded border-slate-300"
                    />
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 px-4 py-3">
                    Trace
                  </th>
                  <th className="text-left text-xs font-medium text-slate-500 px-4 py-3">
                    Label
                  </th>
                  <th className="text-center text-xs font-medium text-slate-500 px-4 py-3">
                    Score
                  </th>
                  <th className="text-right text-xs font-medium text-slate-500 px-4 py-3">
                    Spans
                  </th>
                  <th className="text-right text-xs font-medium text-slate-500 px-4 py-3">
                    Tokens
                  </th>
                  <th className="text-center text-xs font-medium text-slate-500 px-4 py-3">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {traces.map((trace: CuratedTrace) => (
                  <tr key={trace.trace_id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(trace.trace_id)}
                        onChange={() => toggleSelect(trace.trace_id)}
                        className="rounded border-slate-300"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/traces/${trace.trace_id}`}
                        className="text-sm text-primary-600 hover:text-primary-700 font-medium"
                      >
                        {trace.trace_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      {trace.label && (
                        <span
                          className={clsx(
                            'inline-flex px-2 py-0.5 text-xs font-medium rounded-full',
                            LABEL_COLORS[trace.label] || 'bg-slate-100 text-slate-600'
                          )}
                        >
                          {trace.label.replace('_', ' ')}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {trace.quality_score && (
                        <span className="inline-flex items-center gap-1 text-sm text-slate-600">
                          <Star className="h-3 w-3 text-amber-500" />
                          {trace.quality_score}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600 text-right">
                      {trace.span_count}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600 text-right">
                      {trace.total_tokens?.toLocaleString() || '-'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {trace.exported && (
                        <CheckCircle className="h-4 w-4 text-green-500 mx-auto" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
