import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Brain, Sparkles, Loader2, Star, Tag, Lightbulb } from 'lucide-react'
import clsx from 'clsx'
import { analyzeTrace, selfAnalyzeTrace, TraceAnalysis, SelfAnalysis } from '@/lib/api'

interface IntelligencePanelProps {
  traceId: string
}

export default function IntelligencePanel({ traceId }: IntelligencePanelProps) {
  const [analysis, setAnalysis] = useState<TraceAnalysis | null>(null)
  const [selfAnalysis, setSelfAnalysis] = useState<SelfAnalysis | null>(null)

  // Reset state when traceId changes to prevent showing stale data
  useEffect(() => {
    setAnalysis(null)
    setSelfAnalysis(null)
  }, [traceId])

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeTrace(traceId),
    onSuccess: (data) => setAnalysis(data),
  })

  const selfAnalyzeMutation = useMutation({
    mutationFn: () => selfAnalyzeTrace(traceId),
    onSuccess: (data) => setSelfAnalysis(data),
  })

  return (
    <div className="bg-dark-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Brain className="h-4 w-4" />
          Intelligence
        </h3>
        <span className="text-xs text-muted-500">Nemotron-powered</span>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => analyzeMutation.mutate()}
          disabled={analyzeMutation.isPending}
          aria-label="Analyze trace with Nemotron"
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            analyzeMutation.isPending
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
          disabled={selfAnalyzeMutation.isPending}
          aria-label="Perform deep self-analysis on trace"
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            selfAnalyzeMutation.isPending
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
