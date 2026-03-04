import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FlaskConical, Loader2, GitCompare, ArrowRight } from 'lucide-react'
import clsx from 'clsx'
import { getExperiments } from '@/lib/api'

type ExperimentField = 'run_id' | 'model' | 'prompt_version'

const FIELD_LABELS: Record<ExperimentField, string> = {
  run_id: 'Run ID',
  model: 'Model',
  prompt_version: 'Prompt Version',
}

function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export default function ExperimentsPage() {
  const [field, setField] = useState<ExperimentField>('run_id')
  const [includeUngrouped, setIncludeUngrouped] = useState(false)

  const experimentsQuery = useQuery({
    queryKey: ['experiments', field, includeUngrouped],
    queryFn: () =>
      getExperiments({
        field,
        limit: 100,
        include_ungrouped: includeUngrouped,
      }),
  })

  const experiments = experimentsQuery.data?.experiments ?? []

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-muted-100">Experiments</h1>
          <p className="mt-1 text-sm text-muted-400">
            Group traces by run metadata and jump straight into A/B compare.
          </p>
        </div>
        <FlaskConical className="h-6 w-6 text-muted-400" />
      </div>

      <div className="mb-4 bg-dark-900 rounded-lg border border-dark-700 p-4 flex flex-wrap items-center gap-2">
        {(Object.keys(FIELD_LABELS) as ExperimentField[]).map((key) => (
          <button
            key={key}
            onClick={() => setField(key)}
            className={clsx(
              'px-3 py-1.5 rounded-lg text-xs border',
              field === key
                ? 'bg-primary-900/30 border-primary-800 text-primary-300'
                : 'bg-dark-800 border-dark-700 text-muted-300 hover:bg-dark-700'
            )}
          >
            {FIELD_LABELS[key]}
          </button>
        ))}
        <label className="ml-auto inline-flex items-center gap-2 text-xs text-muted-300">
          <input
            type="checkbox"
            checked={includeUngrouped}
            onChange={(event) => setIncludeUngrouped(event.target.checked)}
            className="rounded border-dark-600 bg-dark-800"
          />
          Include ungrouped
        </label>
      </div>

      {experimentsQuery.isLoading ? (
        <div className="flex items-center justify-center h-40">
          <Loader2 className="h-7 w-7 text-primary-600 animate-spin" />
        </div>
      ) : experimentsQuery.isError ? (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-400 text-sm">
          Failed to load experiments.
        </div>
      ) : experiments.length === 0 ? (
        <div className="bg-dark-900 border border-dark-700 rounded-lg p-8 text-center">
          <p className="text-muted-400 text-sm">
            No experiment groups found for <span className="text-muted-200">{FIELD_LABELS[field]}</span>.
          </p>
          <p className="text-muted-500 text-xs mt-2">
            Add trace metadata like run_id/model/prompt_version during ingestion.
          </p>
        </div>
      ) : (
        <div className="bg-dark-900 border border-dark-700 rounded-lg divide-y divide-dark-700">
          {experiments.map((experiment) => (
            <div key={experiment.experiment_id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm text-muted-100 font-medium">{experiment.experiment_id}</p>
                  <p className="text-xs text-muted-400 mt-1">
                    {experiment.trace_count} traces · Avg duration {formatDuration(experiment.avg_duration_ms)} ·
                    Error rate {(experiment.error_rate * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-muted-500 mt-1">
                    Latest: {experiment.latest_trace_name}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-xs px-2 py-0.5 rounded bg-dark-800 text-muted-300">
                    success {experiment.statuses.success}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-dark-800 text-muted-300">
                    error {experiment.statuses.error}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded bg-dark-800 text-muted-300">
                    running {experiment.statuses.running}
                  </span>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Link
                  to={`/traces/${experiment.latest_trace_id}`}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-dark-800 border border-dark-700 text-muted-200 hover:bg-dark-700"
                >
                  Open latest trace <ArrowRight className="h-3.5 w-3.5" />
                </Link>
                {experiment.sample_compare_pair && (
                  <Link
                    to={`/compare?traceA=${experiment.sample_compare_pair.trace_a_id}&traceB=${experiment.sample_compare_pair.trace_b_id}`}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-dark-800 border border-dark-700 text-muted-200 hover:bg-dark-700"
                  >
                    Compare recent pair <GitCompare className="h-3.5 w-3.5" />
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
