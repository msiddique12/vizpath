import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, Brain, Loader2, ShieldAlert } from 'lucide-react'
import clsx from 'clsx'
import { compareTraces, getFailureModes, getRegressionExplain, getTraces } from '@/lib/api'

export default function IntelligencePage() {
  const [candidateTraceId, setCandidateTraceId] = useState('')
  const [baselineTraceId, setBaselineTraceId] = useState('')

  const { data: tracesData, isLoading: tracesLoading, error: tracesError } = useQuery({
    queryKey: ['traces', 100],
    queryFn: () => getTraces(100),
  })

  const traces = useMemo(() => tracesData?.traces ?? [], [tracesData?.traces])

  const compareQuery = useQuery({
    queryKey: ['triage-compare', baselineTraceId, candidateTraceId],
    queryFn: () => compareTraces(baselineTraceId, candidateTraceId),
    enabled: Boolean(baselineTraceId && candidateTraceId && baselineTraceId !== candidateTraceId),
  })

  const failureModesMutation = useMutation({
    mutationFn: () => getFailureModes(candidateTraceId),
  })

  const regressionExplainMutation = useMutation({
    mutationFn: () => getRegressionExplain(baselineTraceId, candidateTraceId),
  })

  const baselineAndCandidateValid =
    baselineTraceId.length > 0 &&
    candidateTraceId.length > 0 &&
    baselineTraceId !== candidateTraceId

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-muted-100 flex items-center gap-2">
          <Brain className="h-6 w-6 text-primary-400" />
          Intelligence Triage
        </h1>
        <p className="mt-1 text-sm text-muted-400">
          Triage regressions with deterministic compare, failure modes, and ranked explanations.
        </p>
      </div>

      <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-4">
        <p className="text-xs uppercase tracking-wide text-muted-400">Trace Selection</p>
        {tracesLoading ? (
          <div className="flex items-center gap-2 text-muted-300 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading traces...
          </div>
        ) : tracesError ? (
          <p className="text-sm text-red-400">Could not load traces for intelligence triage.</p>
        ) : traces.length === 0 ? (
          <p className="text-sm text-muted-400">No traces available yet.</p>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div>
              <label htmlFor="baseline-trace" className="block text-xs text-muted-400 mb-1">
                Baseline Trace
              </label>
              <select
                id="baseline-trace"
                value={baselineTraceId}
                onChange={(event) => setBaselineTraceId(event.target.value)}
                className="w-full bg-dark-800 border border-dark-700 text-muted-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="">Select baseline trace...</option>
                {traces.map((trace) => (
                  <option key={trace.id} value={trace.id}>
                    {trace.name} ({trace.id})
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="candidate-trace" className="block text-xs text-muted-400 mb-1">
                Candidate Trace
              </label>
              <select
                id="candidate-trace"
                value={candidateTraceId}
                onChange={(event) => setCandidateTraceId(event.target.value)}
                className="w-full bg-dark-800 border border-dark-700 text-muted-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                <option value="">Select candidate trace...</option>
                {traces.map((trace) => (
                  <option key={trace.id} value={trace.id}>
                    {trace.name} ({trace.id})
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {baselineTraceId && candidateTraceId && baselineTraceId === candidateTraceId && (
          <p className="text-xs text-amber-400">Baseline and candidate traces must be different.</p>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => failureModesMutation.mutate()}
            disabled={candidateTraceId.length === 0 || failureModesMutation.isPending}
            className={clsx(
              'flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              candidateTraceId.length > 0 && !failureModesMutation.isPending
                ? 'bg-dark-800 border border-dark-700 text-muted-200 hover:bg-dark-700'
                : 'bg-dark-700 text-muted-500 cursor-not-allowed'
            )}
          >
            {failureModesMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ShieldAlert className="h-4 w-4" />
            )}
            Run Failure Modes
          </button>
          <button
            type="button"
            onClick={() => regressionExplainMutation.mutate()}
            disabled={!baselineAndCandidateValid || regressionExplainMutation.isPending}
            className={clsx(
              'flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
              baselineAndCandidateValid && !regressionExplainMutation.isPending
                ? 'bg-primary-600 text-white hover:bg-primary-700'
                : 'bg-dark-700 text-muted-500 cursor-not-allowed'
            )}
          >
            {regressionExplainMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )}
            Explain Regression
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-400">Compare Context</p>
          {compareQuery.isLoading ? (
            <p className="text-sm text-muted-400">Computing compare metrics...</p>
          ) : compareQuery.error ? (
            <p className="text-sm text-red-400">Compare query failed.</p>
          ) : compareQuery.data ? (
            <>
              <p className="text-sm text-muted-200">
                Status: <span className="text-primary-300">{compareQuery.data.summary.status}</span>
              </p>
              <p className="text-xs text-muted-400">
                Regression score: {compareQuery.data.summary.regression_score} · Signals: {compareQuery.data.summary.signal_count}
              </p>
              {compareQuery.data.signals.slice(0, 2).map((signal) => (
                <div key={signal.id} className="bg-dark-800 rounded p-2">
                  <p className="text-xs text-muted-200">{signal.title}</p>
                  <p className="text-xs text-muted-400 mt-1">{signal.detail}</p>
                </div>
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-500">Select baseline and candidate traces to load compare context.</p>
          )}
        </div>

        <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-400">Failure Modes</p>
          {failureModesMutation.isError ? (
            <p className="text-sm text-red-400">Failure mode diagnostics request failed.</p>
          ) : failureModesMutation.data ? (
            <>
              <p className="text-sm text-muted-200">{failureModesMutation.data.summary}</p>
              <p className="text-xs text-primary-300">
                Primary: {failureModesMutation.data.primary_mode} ({Math.round(failureModesMutation.data.confidence * 100)}%)
              </p>
              {failureModesMutation.data.modes.slice(0, 2).map((mode) => (
                <div key={mode.mode} className="bg-dark-800 rounded p-2">
                  <p className="text-xs text-muted-200">
                    {mode.mode} · {mode.score} · {mode.severity}
                  </p>
                  {mode.recommendations[0] && (
                    <p className="text-xs text-muted-400 mt-1">{mode.recommendations[0]}</p>
                  )}
                </div>
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-500">Run failure mode diagnostics for a candidate trace.</p>
          )}
        </div>

        <div className="bg-dark-900 rounded-lg border border-dark-700 p-4 space-y-2">
          <p className="text-xs uppercase tracking-wide text-muted-400">Regression Explain</p>
          {regressionExplainMutation.isError ? (
            <p className="text-sm text-red-400">Regression explanation request failed.</p>
          ) : regressionExplainMutation.data ? (
            <>
              <p className="text-sm text-muted-200">{regressionExplainMutation.data.explanation.summary}</p>
              <p className="text-xs text-muted-400">
                Top confidence: {Math.round(regressionExplainMutation.data.explanation.top_hypothesis_confidence * 100)}%
              </p>
              {regressionExplainMutation.data.explanation.hypotheses.slice(0, 2).map((hypothesis) => (
                <div key={hypothesis.id} className="bg-dark-800 rounded p-2">
                  <p className="text-xs text-muted-200">{hypothesis.title}</p>
                  <p className="text-xs text-muted-400 mt-1">{hypothesis.recommendation}</p>
                </div>
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-500">
              Select baseline + candidate traces and run regression explanation.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
