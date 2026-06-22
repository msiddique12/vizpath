import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckSquare, Database, FileJson, Loader2, PlaySquare } from 'lucide-react'
import clsx from 'clsx'
import {
  buildDataset,
  buildEvalSuite,
  createDatasetBuild,
  createEvalRun,
  createSavedEvalSuite,
  downloadDatasetBuild,
  DatasetFormat,
  EvalAssertionProfile,
  getDatasetBuilds,
  getSavedEvalSuites,
  getTraces,
} from '@/lib/api'

const DATASET_FORMATS: Array<{ value: DatasetFormat; label: string }> = [
  { value: 'chat', label: 'Chat' },
  { value: 'tool_calls', label: 'Tool calls' },
  { value: 'preference', label: 'Preference' },
]

const EVAL_PROFILES: Array<{ value: EvalAssertionProfile; label: string }> = [
  { value: 'balanced', label: 'Balanced' },
  { value: 'strict', label: 'Strict' },
  { value: 'latency', label: 'Latency' },
  { value: 'cost', label: 'Cost' },
  { value: 'tooling', label: 'Tooling' },
]

function previewJson(value: unknown): string {
  return JSON.stringify(value, null, 2).slice(0, 2400)
}

export default function DatasetsPage() {
  const [selectedTraceIds, setSelectedTraceIds] = useState<Set<string>>(new Set())
  const [datasetFormat, setDatasetFormat] = useState<DatasetFormat>('chat')
  const [includeFailed, setIncludeFailed] = useState(false)
  const [minQualityScore, setMinQualityScore] = useState('')
  const [evalName, setEvalName] = useState('Trace regression suite')
  const [evalProfile, setEvalProfile] = useState<EvalAssertionProfile>('balanced')
  const [selectedSuiteId, setSelectedSuiteId] = useState('')

  const tracesQuery = useQuery({
    queryKey: ['traces', 'dataset-builder'],
    queryFn: () => getTraces(100, 0, undefined, { sort_by: 'created_at', sort_order: 'desc' }),
  })

  const datasetBuildsQuery = useQuery({
    queryKey: ['dataset-builds'],
    queryFn: () => getDatasetBuilds({ limit: 20, offset: 0 }),
  })

  const savedEvalSuitesQuery = useQuery({
    queryKey: ['saved-eval-suites'],
    queryFn: () => getSavedEvalSuites({ limit: 20, offset: 0 }),
  })

  const traces = useMemo(() => tracesQuery.data?.traces ?? [], [tracesQuery.data?.traces])
  const selectedTraceList = useMemo(
    () => traces.filter((trace) => selectedTraceIds.has(trace.id)),
    [selectedTraceIds, traces]
  )
  const selectedIds = useMemo(() => selectedTraceList.map((trace) => trace.id), [selectedTraceList])

  const datasetMutation = useMutation({
    mutationFn: () =>
      buildDataset({
        trace_ids: selectedIds,
        format: datasetFormat,
        include_failed: includeFailed,
        min_quality_score: minQualityScore.trim() ? Number(minQualityScore) : undefined,
      }),
  })

  const evalMutation = useMutation({
    mutationFn: () =>
      buildEvalSuite({
        trace_ids: selectedIds,
        name: evalName.trim() || 'Trace regression suite',
        assertion_profile: evalProfile,
      }),
  })

  const savedDatasetMutation = useMutation({
    mutationFn: () =>
      createDatasetBuild({
        trace_ids: selectedIds,
        name: `${datasetFormat} dataset ${new Date().toLocaleDateString()}`,
        format: datasetFormat,
        include_failed: includeFailed,
        min_quality_score: minQualityScore.trim() ? Number(minQualityScore) : undefined,
        include_raw: false,
      }),
    onSuccess: () => datasetBuildsQuery.refetch(),
  })

  const savedEvalSuiteMutation = useMutation({
    mutationFn: () =>
      createSavedEvalSuite({
        trace_ids: selectedIds,
        name: evalName.trim() || 'Trace regression suite',
        assertion_profile: evalProfile,
      }),
    onSuccess: (suite) => {
      setSelectedSuiteId(suite.id)
      savedEvalSuitesQuery.refetch()
    },
  })

  const evalRunMutation = useMutation({
    mutationFn: () =>
      createEvalRun(selectedSuiteId, {
        name: `Candidate run ${new Date().toLocaleString()}`,
        candidate_trace_ids: selectedIds,
      }),
    onSuccess: () => savedEvalSuitesQuery.refetch(),
  })

  const downloadDatasetMutation = useMutation({
    mutationFn: ({ buildId, format }: { buildId: string; format: 'json' | 'jsonl' }) =>
      downloadDatasetBuild(buildId, format),
    onSuccess: (content, variables) => {
      const blob = new Blob([content], {
        type: variables.format === 'jsonl' ? 'application/x-ndjson' : 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `dataset-build-${variables.buildId}.${variables.format}`
      anchor.click()
      URL.revokeObjectURL(url)
    },
  })

  const toggleTrace = (traceId: string) => {
    setSelectedTraceIds((current) => {
      const next = new Set(current)
      if (next.has(traceId)) {
        next.delete(traceId)
      } else {
        next.add(traceId)
      }
      return next
    })
  }

  const selectVisible = () => {
    setSelectedTraceIds(new Set(traces.map((trace) => trace.id)))
  }

  const clearSelection = () => {
    setSelectedTraceIds(new Set())
  }

  const canBuild =
    selectedIds.length > 0 &&
    !datasetMutation.isPending &&
    !evalMutation.isPending &&
    !savedDatasetMutation.isPending &&
    !savedEvalSuiteMutation.isPending &&
    !evalRunMutation.isPending

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-muted-100 flex items-center gap-2">
          <Database className="h-6 w-6 text-primary-400" />
          Dataset Builder
        </h1>
        <p className="mt-1 text-sm text-muted-400">
          Convert production traces into training records and regression eval suites.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-4">
        <section className="bg-dark-900 border border-dark-700 rounded-lg">
          <div className="flex items-center justify-between border-b border-dark-700 p-4">
            <div>
              <h2 className="text-sm font-medium text-muted-100">Trace Sources</h2>
              <p className="text-xs text-muted-400 mt-1">{selectedIds.length} selected</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={selectVisible}
                className="px-3 py-1.5 text-xs rounded border border-dark-700 text-muted-200 hover:bg-dark-800"
              >
                Select visible
              </button>
              <button
                type="button"
                onClick={clearSelection}
                className="px-3 py-1.5 text-xs rounded border border-dark-700 text-muted-200 hover:bg-dark-800"
              >
                Clear
              </button>
            </div>
          </div>

          {tracesQuery.isLoading ? (
            <div className="flex items-center justify-center h-48 text-muted-400">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              Loading traces...
            </div>
          ) : traces.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-400">No traces available.</div>
          ) : (
            <div className="divide-y divide-dark-700">
              {traces.map((trace) => {
                const selected = selectedTraceIds.has(trace.id)
                return (
                  <button
                    key={trace.id}
                    type="button"
                    onClick={() => toggleTrace(trace.id)}
                    className={clsx(
                      'w-full px-4 py-3 text-left flex items-center gap-3 hover:bg-dark-800 transition-colors',
                      selected && 'bg-primary-900/20'
                    )}
                  >
                    <CheckSquare className={clsx('h-4 w-4', selected ? 'text-primary-400' : 'text-muted-600')} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-muted-100 truncate">{trace.name}</p>
                      <p className="text-xs text-muted-400 mt-1">
                        {trace.status} · {trace.span_count} spans · {trace.total_tokens ?? 0} tokens
                      </p>
                    </div>
                    <span className="text-xs text-muted-500">{new Date(trace.created_at).toLocaleDateString()}</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <section className="bg-dark-900 border border-dark-700 rounded-lg p-4 space-y-3">
            <h2 className="text-sm font-medium text-muted-100 flex items-center gap-2">
              <FileJson className="h-4 w-4" />
              Build Dataset
            </h2>
            <label className="block text-xs text-muted-400">
              Format
              <select
                value={datasetFormat}
                onChange={(event) => setDatasetFormat(event.target.value as DatasetFormat)}
                className="mt-1 w-full bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
              >
                {DATASET_FORMATS.map((format) => (
                  <option key={format.value} value={format.value}>
                    {format.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-300">
              <input
                type="checkbox"
                checked={includeFailed}
                onChange={(event) => setIncludeFailed(event.target.checked)}
              />
              Include failed traces
            </label>
            <label className="block text-xs text-muted-400">
              Minimum quality score
              <input
                value={minQualityScore}
                onChange={(event) => setMinQualityScore(event.target.value)}
                inputMode="decimal"
                className="mt-1 w-full bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
                placeholder="Optional"
              />
            </label>
            <button
              type="button"
              disabled={!canBuild}
              onClick={() => datasetMutation.mutate()}
              className={clsx(
                'w-full flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium',
                canBuild ? 'bg-primary-600 text-white hover:bg-primary-700' : 'bg-dark-700 text-muted-500'
              )}
            >
              {datasetMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileJson className="h-4 w-4" />}
              Generate records
            </button>
            <button
              type="button"
              disabled={!canBuild}
              onClick={() => savedDatasetMutation.mutate()}
              className={clsx(
                'w-full flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium border',
                canBuild ? 'bg-dark-800 border-dark-700 text-muted-100 hover:bg-dark-700' : 'bg-dark-700 border-dark-700 text-muted-500'
              )}
            >
              {savedDatasetMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
              Save redacted build
            </button>
          </section>

          <section className="bg-dark-900 border border-dark-700 rounded-lg p-4 space-y-3">
            <h2 className="text-sm font-medium text-muted-100 flex items-center gap-2">
              <PlaySquare className="h-4 w-4" />
              Build Eval Suite
            </h2>
            <label className="block text-xs text-muted-400">
              Suite name
              <input
                value={evalName}
                onChange={(event) => setEvalName(event.target.value)}
                className="mt-1 w-full bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-xs text-muted-400">
              Assertion profile
              <select
                value={evalProfile}
                onChange={(event) => setEvalProfile(event.target.value as EvalAssertionProfile)}
                className="mt-1 w-full bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
              >
                {EVAL_PROFILES.map((profile) => (
                  <option key={profile.value} value={profile.value}>
                    {profile.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!canBuild}
              onClick={() => evalMutation.mutate()}
              className={clsx(
                'w-full flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium',
                canBuild ? 'bg-dark-800 border border-dark-700 text-muted-100 hover:bg-dark-700' : 'bg-dark-700 text-muted-500'
              )}
            >
              {evalMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlaySquare className="h-4 w-4" />}
              Generate eval cases
            </button>
            <button
              type="button"
              disabled={!canBuild}
              onClick={() => savedEvalSuiteMutation.mutate()}
              className={clsx(
                'w-full flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium border',
                canBuild ? 'bg-dark-800 border-dark-700 text-muted-100 hover:bg-dark-700' : 'bg-dark-700 border-dark-700 text-muted-500'
              )}
            >
              {savedEvalSuiteMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlaySquare className="h-4 w-4" />}
              Save eval suite
            </button>
            <label className="block text-xs text-muted-400">
              Saved suite for run
              <select
                value={selectedSuiteId}
                onChange={(event) => setSelectedSuiteId(event.target.value)}
                className="mt-1 w-full bg-dark-800 border border-dark-700 text-muted-200 rounded px-3 py-2 text-sm"
              >
                <option value="">Select saved suite...</option>
                {(savedEvalSuitesQuery.data?.suites ?? []).map((suite) => (
                  <option key={suite.id} value={suite.id}>
                    {suite.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!canBuild || !selectedSuiteId}
              onClick={() => evalRunMutation.mutate()}
              className={clsx(
                'w-full flex items-center justify-center gap-2 rounded px-3 py-2 text-sm font-medium',
                canBuild && selectedSuiteId ? 'bg-primary-600 text-white hover:bg-primary-700' : 'bg-dark-700 text-muted-500'
              )}
            >
              {evalRunMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlaySquare className="h-4 w-4" />}
              Record eval run
            </button>
          </section>
        </aside>
      </div>

      <section className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
          <h2 className="text-sm font-medium text-muted-100">Saved Dataset Builds</h2>
          <div className="mt-3 space-y-2">
            {(datasetBuildsQuery.data?.builds ?? []).length === 0 ? (
              <p className="text-xs text-muted-400">No saved builds yet.</p>
            ) : (
              (datasetBuildsQuery.data?.builds ?? []).map((build) => (
                <div key={build.id} className="flex items-center justify-between gap-3 rounded border border-dark-700 bg-dark-800 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-muted-100">{build.name}</p>
                    <p className="text-xs text-muted-400">
                      {build.record_count} records · {build.redaction_mode} · {build.format}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => downloadDatasetMutation.mutate({ buildId: build.id, format: 'jsonl' })}
                    disabled={downloadDatasetMutation.isPending}
                    className="shrink-0 rounded border border-dark-700 px-2 py-1 text-xs text-muted-200 hover:bg-dark-700"
                  >
                    Download JSONL
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
          <h2 className="text-sm font-medium text-muted-100">Saved Eval Suites</h2>
          <div className="mt-3 space-y-2">
            {(savedEvalSuitesQuery.data?.suites ?? []).length === 0 ? (
              <p className="text-xs text-muted-400">No saved eval suites yet.</p>
            ) : (
              (savedEvalSuitesQuery.data?.suites ?? []).map((suite) => (
                <button
                  key={suite.id}
                  type="button"
                  onClick={() => setSelectedSuiteId(suite.id)}
                  className={clsx(
                    'w-full rounded border p-3 text-left',
                    selectedSuiteId === suite.id
                      ? 'border-primary-700 bg-primary-900/20'
                      : 'border-dark-700 bg-dark-800 hover:bg-dark-700'
                  )}
                >
                  <p className="text-sm text-muted-100">{suite.name}</p>
                  <p className="text-xs text-muted-400">
                    {suite.case_count} cases · {suite.run_count} runs · {suite.assertion_profile}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>
      </section>

      {(datasetMutation.data || evalMutation.data || savedDatasetMutation.data || savedEvalSuiteMutation.data || evalRunMutation.data) && (
        <section className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {datasetMutation.data && (
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <h2 className="text-sm font-medium text-muted-100">Dataset Output</h2>
              <p className="mt-1 text-xs text-muted-400">
                {datasetMutation.data.record_count} records · {datasetMutation.data.skipped_count} skipped
              </p>
              <pre className="mt-3 max-h-96 overflow-auto rounded bg-dark-950 p-3 text-xs text-muted-200">
                {previewJson(datasetMutation.data.records)}
              </pre>
            </div>
          )}
          {evalMutation.data && (
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <h2 className="text-sm font-medium text-muted-100">Eval Suite Output</h2>
              <p className="mt-1 text-xs text-muted-400">
                {evalMutation.data.case_count} cases · {evalMutation.data.assertion_profile}
              </p>
              <pre className="mt-3 max-h-96 overflow-auto rounded bg-dark-950 p-3 text-xs text-muted-200">
                {previewJson(evalMutation.data.cases)}
              </pre>
            </div>
          )}
          {savedDatasetMutation.data && (
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <h2 className="text-sm font-medium text-muted-100">Saved Dataset Build</h2>
              <p className="mt-1 text-xs text-muted-400">
                {savedDatasetMutation.data.record_count} records · {savedDatasetMutation.data.redaction_mode}
              </p>
              <pre className="mt-3 max-h-96 overflow-auto rounded bg-dark-950 p-3 text-xs text-muted-200">
                {previewJson(savedDatasetMutation.data.artifact?.records ?? [])}
              </pre>
            </div>
          )}
          {savedEvalSuiteMutation.data && (
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <h2 className="text-sm font-medium text-muted-100">Saved Eval Suite</h2>
              <p className="mt-1 text-xs text-muted-400">
                {savedEvalSuiteMutation.data.case_count} cases · {savedEvalSuiteMutation.data.assertion_profile}
              </p>
              <pre className="mt-3 max-h-96 overflow-auto rounded bg-dark-950 p-3 text-xs text-muted-200">
                {previewJson(savedEvalSuiteMutation.data.cases ?? [])}
              </pre>
            </div>
          )}
          {evalRunMutation.data && (
            <div className="bg-dark-900 border border-dark-700 rounded-lg p-4">
              <h2 className="text-sm font-medium text-muted-100">Eval Run Result</h2>
              <p className="mt-1 text-xs text-muted-400">
                {evalRunMutation.data.pass_count} passed · {evalRunMutation.data.fail_count} failed
              </p>
              <pre className="mt-3 max-h-96 overflow-auto rounded bg-dark-950 p-3 text-xs text-muted-200">
                {previewJson(evalRunMutation.data.results ?? [])}
              </pre>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
