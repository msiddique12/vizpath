import { useQuery } from '@tanstack/react-query'
import { Loader2, DollarSign } from 'lucide-react'
import { getTraces } from '@/lib/api'
import CostDashboard from '@/components/CostDashboard'
import { Span } from '@/lib/types'

export default function CostPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['traces', { limit: 100 }],
    queryFn: () => getTraces({ limit: 100 }),
  })

  const allSpans: Span[] = data?.traces?.flatMap((t) => t.spans || []) || []

  const totalCost = data?.traces?.reduce((sum, trace) => {
    return sum + (trace.total_cost || 0)
  }, 0) || undefined

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Cost Analytics</h1>
        <p className="mt-1 text-sm text-slate-500">
          Analyze token usage and cost attribution across traces
        </p>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-6">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 text-primary-600 animate-spin" />
          </div>
        ) : error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700">Failed to load cost data.</p>
          </div>
        ) : allSpans.length === 0 ? (
          <div className="text-center py-12">
            <DollarSign className="h-12 w-12 text-slate-300 mx-auto mb-3" />
            <p className="text-slate-500">No traces with cost data available</p>
            <p className="text-sm text-slate-400 mt-1">
              Traces with token counts will appear here for cost analysis
            </p>
          </div>
        ) : (
          <CostDashboard spans={allSpans} totalCost={totalCost} />
        )}
      </div>
    </div>
  )
}
