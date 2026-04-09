import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Sparkles, Loader2, Star, Tag, Lightbulb, CheckCircle2, Wand2, ShieldAlert, AlertTriangle, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import {
  analyzeTrace,
  getFailureModes,
  getTraceCopilot,
  selfAnalyzeTrace,
  getIntelligenceStatus,
  getRegressionExplain,
  suggestCuration,
  createOrUpdateLabel,
  TraceAnalysis,
  SelfAnalysis,
  FailureModesResult,
  RegressionExplainResult,
} from '@/lib/api'

interface IntelligencePanelProps {
  traceId: string
}

export default function IntelligencePanel({ traceId }: IntelligencePanelProps) {
  const queryClient = useQueryClient()
  const [analysis, setAnalysis] = useState<TraceAnalysis | null>(null)
  const [selfAnalysis, setSelfAnalysis] = useState<SelfAnalysis | null>(null)
  const [failureModes, setFailureModes] = useState<FailureModesResult | null>(null)
  const [regressionExplain, setRegressionExplain] = useState<RegressionExplainResult | null>(null)
  const [baselineTraceId, setBaselineTraceId] = useState<string>('')
  const [actionStatus, setActionStatus] = useState<string | null>(null)

  const copilotQuery = useQuery({
    queryKey: ['trace-copilot', traceId],
    queryFn: () => getTraceCopilot(traceId),
    staleTime: 30000,
  })

  const intelligenceStatus = useQuery({
    queryKey: ['intelligence-status'],
    queryFn: getIntelligenceStatus,
    staleTime: 30000,
  })

  // Reset state when traceId changes to prevent showing stale data
  useEffect(() => {
    setAnalysis(null)
    setSelfAnalysis(null)
    setFailureModes(null)
    setRegressionExplain(null)
    setBaselineTraceId('')
    setActionStatus(null)
  }, [traceId])

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeTrace(traceId),
    onSuccess: (data) => setAnalysis(data),
  })

  const selfAnalyzeMutation = useMutation({
    mutationFn: () => selfAnalyzeTrace(traceId),
    onSuccess: (data) => setSelfAnalysis(data),
  })

  const failureModesMutation = useMutation({
    mutationFn: () => getFailureModes(traceId),
    onSuccess: (data) => setFailureModes(data),
  })

  const regressionExplainMutation = useMutation({
    mutationFn: () => getRegressionExplain(baselineTraceId.trim(), traceId),
    onSuccess: (data) => setRegressionExplain(data),
  })

  const applySuggestionMutation = useMutation({
    mutationFn: async () => {
      const suggestion = await suggestCuration(traceId)
      return createOrUpdateLabel({
        trace_id: traceId,
        label: suggestion.label,
        quality_score: suggestion.quality_score,
        notes: suggestion.notes || undefined,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['curation-label', traceId] })
      queryClient.invalidateQueries({ queryKey: ['curated-traces'] })
      queryClient.invalidateQueries({ queryKey: ['curation-stats'] })
      setActionStatus('Applied AI suggestion to Curation.')
    },
    onError: () => {
      setActionStatus('Failed to apply AI suggestion.')
    },
  })

  const qualityScore = analysis?.analysis.quality_score ?? 0
  const copilotTopFix = copilotQuery.data?.next_fixes[0]
  const primaryAction = copilotTopFix?.title ?? (
    qualityScore >= 80
      ? 'Promote this trace for training export.'
      : qualityScore >= 60
        ? 'Label as good/needs improvement and keep for review.'
        : 'Label as failure and generate corrections.'
  )

  const likelyIssue = copilotQuery.data?.root_cause.detail
    || analysis?.analysis.suggestions[0]
    || selfAnalysis?.analysis.weaknesses[0]
    || 'No major issue detected.'
  const expectedGain = copilotTopFix?.expected_gain ?? (
    qualityScore >= 80
      ? 'Higher quality examples with minimal rework.'
      : qualityScore >= 60
        ? 'Moderate quality lift by applying top suggestions.'
        : 'Significant reliability gain from corrections.'
  )
  const isIntelligenceReady = intelligenceStatus.data?.nvidia_api_key_configured === true
  const isAnalyzeDisabled =
    analyzeMutation.isPending || selfAnalyzeMutation.isPending || !isIntelligenceReady
  const baselineId = baselineTraceId.trim()
  const isSameTraceComparison = baselineId.length > 0 && baselineId === traceId
  const isRegressionDisabled =
    regressionExplainMutation.isPending || baselineId.length === 0 || isSameTraceComparison

  return (
    <div className="bg-dark-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Brain className="h-4 w-4" />
          Intelligence
        </h3>
        <span className="text-xs text-muted-500">Nemotron-powered</span>
      </div>

      {(!isIntelligenceReady || intelligenceStatus.isError || intelligenceStatus.isLoading) && (
        <div className="bg-amber-900/30 border border-amber-800 rounded-lg px-3 py-2 text-xs text-amber-300">
          {intelligenceStatus.isLoading
            ? 'Checking NVIDIA intelligence configuration...'
            : !isIntelligenceReady
              ? 'NVIDIA API key not configured. Set NVIDIA_API_KEY in your server env to enable analysis.'
              : 'Could not verify intelligence readiness.'}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => analyzeMutation.mutate()}
          disabled={isAnalyzeDisabled}
          aria-label="Analyze trace with Nemotron"
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            isAnalyzeDisabled
              ? 'bg-dark-700 text-muted-400 cursor-wait'
              : 'bg-primary-600 text-white hover:bg-primary-700'
          )}
        >
          {analyzeMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          Analyze
        </button>
        <button
          onClick={() => selfAnalyzeMutation.mutate()}
          disabled={isAnalyzeDisabled}
          aria-label="Perform deep self-analysis on trace"
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            isAnalyzeDisabled
              ? 'bg-dark-700 text-muted-400 cursor-wait'
              : 'bg-dark-900 border border-dark-700 text-muted-200 hover:bg-dark-700'
          )}
        >
          {selfAnalyzeMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Brain className="h-4 w-4" />
          )}
          Deep Analysis
        </button>
      </div>

      {(analyzeMutation.isError || selfAnalyzeMutation.isError) && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-2">
          <p className="text-xs text-red-400">
            {analyzeMutation.error?.message || selfAnalyzeMutation.error?.message || 'Analysis failed. Ensure NVIDIA API key is configured.'}
          </p>
        </div>
      )}

      <div className="bg-dark-900 border border-dark-700 rounded-lg p-3 space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-wide text-muted-400">Trace Copilot</p>
          <button
            onClick={() => copilotQuery.refetch()}
            disabled={copilotQuery.isFetching}
            className={clsx(
              'inline-flex items-center gap-1 rounded border px-2 py-1 text-xs transition-colors',
              copilotQuery.isFetching
                ? 'border-dark-600 text-muted-500'
                : 'border-dark-600 text-muted-300 hover:text-muted-100'
            )}
          >
            <RefreshCw className={clsx('h-3 w-3', copilotQuery.isFetching && 'animate-spin')} />
            Refresh
          </button>
        </div>

        {copilotQuery.isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            Building deterministic copilot brief...
          </div>
        )}

        {copilotQuery.isError && (
          <div className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-2">
            <p className="text-xs text-red-400">
              {copilotQuery.error?.message || 'Could not load copilot brief.'}
            </p>
          </div>
        )}

        {copilotQuery.data && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span
                className={clsx(
                  'inline-flex rounded-full border px-2 py-0.5 text-xs',
                  copilotQuery.data.triage_status === 'high_risk'
                    ? 'border-red-700 text-red-300'
                    : copilotQuery.data.triage_status === 'review'
                      ? 'border-amber-700 text-amber-300'
                      : 'border-green-700 text-green-300'
                )}
              >
                {copilotQuery.data.triage_status.replace('_', ' ')}
              </span>
              <span className="text-xs text-muted-400">
                score {copilotQuery.data.triage_score} · confidence {Math.round(copilotQuery.data.confidence * 100)}%
              </span>
            </div>

            <div className="bg-dark-800 rounded-lg p-2">
              <p className="text-xs text-muted-400">Root Cause</p>
              <p className="text-sm text-muted-100">{copilotQuery.data.root_cause.title}</p>
              <p className="text-xs text-muted-300 mt-1">{copilotQuery.data.root_cause.detail}</p>
            </div>

            <div className="space-y-1">
              <p className="text-xs text-muted-400">Top Fixes</p>
              {copilotQuery.data.next_fixes.map((fix) => (
                <div key={fix.id} className="rounded border border-dark-700 bg-dark-800 px-2 py-2">
                  <p className="text-xs text-muted-100">
                    {fix.title} <span className="text-muted-500">({fix.priority})</span>
                  </p>
                  <p className="text-xs text-muted-400 mt-1">{fix.rationale}</p>
                </div>
              ))}
            </div>

            {copilotQuery.data.span_references.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-muted-400">Span References</p>
                <div className="flex flex-wrap gap-1.5">
                  {copilotQuery.data.span_references.map((reference) => (
                    <a
                      key={reference.span_id}
                      href={`?view=timeline&span_name=${encodeURIComponent(reference.span_name)}`}
                      className="inline-flex items-center rounded border border-dark-600 bg-dark-900 px-2 py-1 text-xs text-muted-300 hover:text-muted-100"
                      title={reference.reason}
                    >
                      {reference.span_name}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="bg-dark-900 border border-dark-700 rounded-lg p-3 space-y-3">
        <p className="text-xs uppercase tracking-wide text-muted-400">Deterministic Diagnostics</p>
        <div className="flex gap-2">
          <button
            onClick={() => failureModesMutation.mutate()}
            disabled={failureModesMutation.isPending}
            className={clsx(
              'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
              failureModesMutation.isPending
                ? 'bg-dark-700 text-muted-400 cursor-wait'
                : 'bg-dark-900 border border-dark-700 text-muted-200 hover:bg-dark-700'
            )}
          >
            {failureModesMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ShieldAlert className="h-4 w-4" />
            )}
            Failure Modes
          </button>
          <button
            onClick={() => regressionExplainMutation.mutate()}
            disabled={isRegressionDisabled}
            className={clsx(
              'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
              isRegressionDisabled
                ? 'bg-dark-700 text-muted-400 cursor-not-allowed'
                : 'bg-dark-900 border border-dark-700 text-muted-200 hover:bg-dark-700'
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

        <div>
          <label htmlFor="baseline-trace-id" className="block text-xs text-muted-400 mb-1">
            Baseline Trace ID (for regression explain)
          </label>
          <input
            id="baseline-trace-id"
            type="text"
            value={baselineTraceId}
            onChange={(event) => setBaselineTraceId(event.target.value)}
            placeholder="trace-baseline-123"
            className="w-full rounded-lg border border-dark-700 bg-dark-800 px-3 py-2 text-sm text-muted-100 placeholder:text-muted-500 focus:outline-none focus:ring-1 focus:ring-primary-600"
          />
          {isSameTraceComparison && (
            <p className="mt-1 text-xs text-amber-400">
              Baseline trace must be different from current trace.
            </p>
          )}
        </div>

        {(failureModesMutation.isError || regressionExplainMutation.isError) && (
          <div className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-2">
            <p className="text-xs text-red-400">
              {failureModesMutation.error?.message || regressionExplainMutation.error?.message || 'Diagnostics request failed.'}
            </p>
          </div>
        )}

        {failureModes && (
          <div className="bg-dark-800 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-400 uppercase tracking-wide">Failure Modes</p>
              <span className="text-xs text-muted-300">{failureModes.status}</span>
            </div>
            <p className="text-sm text-muted-200">{failureModes.summary}</p>
            {failureModes.status === 'issue_detected' && (
              <p className="text-xs text-primary-300">
                Primary mode: <span className="font-medium text-primary-200">{failureModes.primary_mode}</span> ({Math.round(failureModes.confidence * 100)}% confidence)
              </p>
            )}
            {failureModes.modes.slice(0, 2).map((mode) => (
              <div key={mode.mode} className="bg-dark-900 rounded px-2 py-2">
                <p className="text-xs text-muted-300">
                  {mode.mode} · {mode.score} · {mode.severity}
                </p>
                {mode.recommendations[0] && (
                  <p className="text-xs text-muted-400 mt-1">{mode.recommendations[0]}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {regressionExplain && (
          <div className="bg-dark-800 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-400 uppercase tracking-wide">Regression Explain</p>
              <span className="text-xs text-muted-300">{regressionExplain.explanation.status}</span>
            </div>
            <p className="text-sm text-muted-200">{regressionExplain.explanation.summary}</p>
            {regressionExplain.explanation.hypotheses.slice(0, 2).map((hypothesis) => (
              <div key={hypothesis.id} className="bg-dark-900 rounded px-2 py-2">
                <p className="text-xs text-muted-200">
                  {hypothesis.title} ({Math.round(hypothesis.confidence * 100)}%)
                </p>
                <p className="text-xs text-muted-400 mt-1">{hypothesis.recommendation}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-dark-900 border border-dark-700 rounded-lg p-3 space-y-2">
        <p className="text-xs uppercase tracking-wide text-muted-400">Action Plan</p>
        <div className="grid grid-cols-1 gap-2">
          <div className="bg-dark-800 rounded-lg p-2">
            <p className="text-xs text-muted-400">Likely Root Cause</p>
            <p className="text-sm text-muted-200">{likelyIssue}</p>
          </div>
          <div className="bg-dark-800 rounded-lg p-2">
            <p className="text-xs text-muted-400">Fix Now</p>
            <p className="text-sm text-muted-200">{primaryAction}</p>
          </div>
          <div className="bg-dark-800 rounded-lg p-2">
            <p className="text-xs text-muted-400">Expected Gain</p>
            <p className="text-sm text-muted-200">{expectedGain}</p>
          </div>
        </div>

        <button
          onClick={() => applySuggestionMutation.mutate()}
          disabled={applySuggestionMutation.isPending || !isIntelligenceReady}
          className={clsx(
            'w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            applySuggestionMutation.isPending || !isIntelligenceReady
              ? 'bg-dark-700 text-muted-400 cursor-wait'
              : 'bg-nvidia-500 text-black hover:bg-nvidia-400'
          )}
        >
          {applySuggestionMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Wand2 className="h-4 w-4" />
          )}
          Apply AI Suggestion to Curation
        </button>

        {actionStatus && (
          <p className="text-xs text-green-400 flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />
            {actionStatus}
          </p>
        )}
      </div>

      {analysis && (
        <div className="space-y-3 pt-2 border-t border-dark-700">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-400">Quality Score</span>
            <div className="flex items-center gap-1">
              <Star className="h-3 w-3 text-amber-500" />
              <span className="text-sm font-medium text-muted-100">
                {analysis.analysis.quality_score}/100
              </span>
            </div>
          </div>

          {analysis.analysis.labels.length > 0 && (
            <div>
              <p className="text-xs text-muted-400 mb-1.5 flex items-center gap-1">
                <Tag className="h-3 w-3" />
                Labels
              </p>
              <div className="flex flex-wrap gap-1.5">
                {analysis.analysis.labels.map((label) => (
                  <span
                    key={label}
                    className="inline-flex px-2 py-0.5 text-xs rounded-full bg-primary-900/30 text-primary-400 border border-primary-800"
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {analysis.analysis.summary && (
            <div>
              <p className="text-xs text-muted-400 mb-1">Summary</p>
              <p className="text-sm text-muted-200">{analysis.analysis.summary}</p>
            </div>
          )}

          {analysis.analysis.suggestions.length > 0 && (
            <div>
              <p className="text-xs text-muted-400 mb-1.5 flex items-center gap-1">
                <Lightbulb className="h-3 w-3" />
                Suggestions
              </p>
              <ul className="space-y-1">
                {analysis.analysis.suggestions.map((suggestion, i) => (
                  <li key={i} className="text-xs text-muted-300 pl-3 relative">
                    <span className="absolute left-0 text-muted-500">&bull;</span>
                    {suggestion}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.cached && (
            <p className="text-xs text-muted-500">Cached result</p>
          )}
        </div>
      )}

      {selfAnalysis && (
        <div className="space-y-3 pt-2 border-t border-dark-700">
          <p className="text-xs font-medium text-muted-300 uppercase tracking-wide">Deep Analysis</p>

          <div className="grid grid-cols-2 gap-2">
            {[
              { label: 'Effectiveness', value: selfAnalysis.analysis.effectiveness },
              { label: 'Reasoning', value: selfAnalysis.analysis.reasoning_quality },
              { label: 'Tool Usage', value: selfAnalysis.analysis.tool_usage },
              { label: 'Overall', value: selfAnalysis.analysis.overall_score },
            ].map(({ label, value }) => (
              <div key={label} className="bg-dark-900 rounded px-2 py-1.5">
                <p className="text-xs text-muted-400">{label}</p>
                <p className="text-sm font-medium text-muted-100">{value}/100</p>
              </div>
            ))}
          </div>

          {selfAnalysis.analysis.summary && (
            <div>
              <p className="text-xs text-muted-400 mb-1">Summary</p>
              <p className="text-sm text-muted-200">{selfAnalysis.analysis.summary}</p>
            </div>
          )}

          {selfAnalysis.analysis.strengths.length > 0 && (
            <div>
              <p className="text-xs text-green-400 mb-1">Strengths</p>
              <ul className="space-y-0.5">
                {selfAnalysis.analysis.strengths.map((s, i) => (
                  <li key={i} className="text-xs text-muted-300 pl-3 relative">
                    <span className="absolute left-0 text-green-500">&bull;</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selfAnalysis.analysis.weaknesses.length > 0 && (
            <div>
              <p className="text-xs text-red-400 mb-1">Weaknesses</p>
              <ul className="space-y-0.5">
                {selfAnalysis.analysis.weaknesses.map((w, i) => (
                  <li key={i} className="text-xs text-muted-300 pl-3 relative">
                    <span className="absolute left-0 text-red-500">&bull;</span>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selfAnalysis.analysis.improvements.length > 0 && (
            <div>
              <p className="text-xs text-amber-400 mb-1">Improvements</p>
              <ul className="space-y-0.5">
                {selfAnalysis.analysis.improvements.map((imp, i) => (
                  <li key={i} className="text-xs text-muted-300 pl-3 relative">
                    <span className="absolute left-0 text-amber-500">&bull;</span>
                    {imp}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selfAnalysis.cached && (
            <p className="text-xs text-muted-500">Cached result</p>
          )}
        </div>
      )}
    </div>
  )
}
