import { TraceListResponse, TraceDetailResponse, Span } from './types'
import { getEffectiveApiKey } from './apiKey'

const API_BASE = (() => {
  const configured = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
  if (!configured) {
    return '/api/v1'
  }
  return configured.endsWith('/') ? configured.slice(0, -1) : configured
})()

async function parseJsonOrEmpty<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T
  }
  const text = await response.text()
  if (!text.trim()) {
    return undefined as T
  }
  return JSON.parse(text) as T
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const apiKey = getEffectiveApiKey()
  if (apiKey && !headers.has('X-API-Key')) {
    headers.set('X-API-Key', apiKey)
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return parseJsonOrEmpty<T>(response)
}

async function fetchRootApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const apiKey = getEffectiveApiKey()
  if (apiKey && !headers.has('X-API-Key')) {
    headers.set('X-API-Key', apiKey)
  }

  const response = await fetch(endpoint, {
    ...options,
    headers,
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return parseJsonOrEmpty<T>(response)
}

export async function getTraces(
  limit = 20,
  offset = 0,
  status?: string,
  options?: {
    q?: string
    min_tokens?: number
    min_cost?: number
    has_errors?: boolean
    sort_by?: 'created_at' | 'duration_ms' | 'total_tokens' | 'total_cost' | 'span_count' | 'error_count' | 'name'
    sort_order?: 'asc' | 'desc'
  }
): Promise<TraceListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (status) {
    params.set('status', status)
  }
  if (options?.q) {
    params.set('q', options.q)
  }
  if (options?.min_tokens !== undefined) {
    params.set('min_tokens', String(options.min_tokens))
  }
  if (options?.min_cost !== undefined) {
    params.set('min_cost', String(options.min_cost))
  }
  if (options?.has_errors !== undefined) {
    params.set('has_errors', String(options.has_errors))
  }
  if (options?.sort_by) {
    params.set('sort_by', options.sort_by)
  }
  if (options?.sort_order) {
    params.set('sort_order', options.sort_order)
  }
  return fetchApi(`/traces?${params}`)
}

export async function getTrace(traceId: string): Promise<TraceDetailResponse> {
  return fetchApi(`/traces/${traceId}`)
}

export async function getTraceSpans(traceId: string): Promise<Span[]> {
  return fetchApi(`/traces/${traceId}/spans`)
}

export interface ExperimentSummary {
  experiment_id: string
  trace_count: number
  latest_trace_id: string
  latest_trace_name: string
  latest_created_at: string
  statuses: Record<'running' | 'success' | 'error', number>
  avg_duration_ms: number | null
  total_tokens: number | null
  total_cost: number | null
  error_rate: number
  sample_compare_pair: { trace_a_id: string; trace_b_id: string } | null
}

export interface ExperimentListResponse {
  field: 'run_id' | 'model' | 'prompt_version'
  experiments: ExperimentSummary[]
  total: number
}

export interface TraceSummaryResponse {
  window_days: number
  trace_count: number
  success_rate: number
  running_count: number
  error_count: number
  p50_duration_ms: number | null
  p95_duration_ms: number | null
  avg_tokens: number | null
  avg_cost: number | null
}

export interface ProjectBudgetStatusResponse {
  month_start: string
  month_end: string
  tokens_used: number
  cost_used: number
  monthly_token_limit: number | null
  monthly_cost_limit: number | null
  token_usage_percent: number | null
  cost_usage_percent: number | null
  alert_threshold_percent: number
  token_alert_triggered: boolean
  cost_alert_triggered: boolean
  alert_triggered: boolean
  hard_stop_enabled: boolean
}

export async function getExperiments(options?: {
  field?: 'run_id' | 'model' | 'prompt_version'
  limit?: number
  offset?: number
  include_ungrouped?: boolean
}): Promise<ExperimentListResponse> {
  const params = new URLSearchParams()
  if (options?.field) params.set('field', options.field)
  if (options?.limit !== undefined) params.set('limit', String(options.limit))
  if (options?.offset !== undefined) params.set('offset', String(options.offset))
  if (options?.include_ungrouped !== undefined) {
    params.set('include_ungrouped', String(options.include_ungrouped))
  }
  return fetchApi(`/traces/experiments?${params}`)
}

export async function getTraceSummary(windowDays = 7): Promise<TraceSummaryResponse> {
  return fetchApi(`/traces/summary?window_days=${windowDays}`)
}

export async function getProjectBudgetStatus(): Promise<ProjectBudgetStatusResponse> {
  return fetchApi('/projects/me/budget/status')
}

export type AlertMetric =
  | 'error_rate_percent'
  | 'avg_duration_ms'
  | 'avg_tokens'
  | 'avg_cost'
  | 'trace_count'
  | 'total_tokens'
  | 'total_cost'
export type AlertOperator = 'gt' | 'gte' | 'lt' | 'lte'

export interface AlertRule {
  id: string
  name: string
  metric: AlertMetric
  operator: AlertOperator
  threshold: number
  window_days: number
  is_active: boolean
  notification_cooldown_minutes: number
  last_triggered_at: string | null
  last_notified_at: string | null
  created_at: string
  updated_at: string | null
}

export interface AlertRuleEvaluation extends AlertRule {
  current_value: number
  breached: boolean
  notification_queued: boolean
  notification_sent: boolean
}

export interface AlertWindowMetrics {
  window_days: number
  trace_count: number
  error_rate_percent: number
  avg_duration_ms: number
  avg_tokens: number
  avg_cost: number
  total_tokens: number
  total_cost: number
}

export interface AlertEvaluationResponse {
  generated_at: string
  alert_count: number
  notifications_queued: number
  notifications_sent: number
  notifications_failed: number
  rules: AlertRuleEvaluation[]
  window_metrics: AlertWindowMetrics[]
}

export interface AlertDestination {
  id: string
  name: string
  kind: 'webhook'
  target_url: string
  is_active: boolean
  created_at: string
  updated_at: string | null
}

export type AlertEventType =
  | 'breach'
  | 'notification_queued'
  | 'notification_sent'
  | 'notification_failed'
  | 'notification_replayed'
  | 'notification_replay_failed'

export interface AlertEvent {
  id: string
  event_type: AlertEventType
  rule_id: string | null
  destination_id: string | null
  rule_name: string | null
  metric: AlertMetric | null
  operator: AlertOperator | null
  threshold: number | null
  current_value: number | null
  message: string | null
  created_at: string
}

export interface AlertDeadLetter {
  id: string
  event_type: 'notification_failed' | 'notification_replay_failed'
  rule_id: string | null
  destination_id: string | null
  rule_name: string | null
  destination_name: string | null
  current_value: number | null
  message: string | null
  replayable: boolean
  replay_attempts: number
  replay_attempts_remaining: number
  next_replay_at: string | null
  replay_blocked_reason: string | null
  created_at: string
}

export interface AlertReplayResponse {
  event_id: string
  replayed: boolean
  queued: boolean
  delivered: boolean
  message: string
}

export interface AlertOpsSummary {
  window_days: number
  generated_at: string
  queue_depth: number
  total_delivery_attempts: number
  notifications_sent: number
  notifications_failed: number
  notifications_queued: number
  delivery_success_rate: number
  replay_attempts: number
  replay_successes: number
  replay_failures: number
  replay_success_rate: number
  median_replay_seconds: number | null
}

export interface AlertOpsTrendPoint {
  date: string
  notifications_sent: number
  notifications_failed: number
  notifications_queued: number
  notifications_replayed: number
  delivery_attempts: number
  delivery_success_rate: number
}

export interface AlertOpsTrends {
  window_days: number
  generated_at: string
  series: AlertOpsTrendPoint[]
}

export async function getAlertRules(): Promise<AlertRule[]> {
  return fetchApi('/projects/me/alerts')
}

export async function createAlertRule(payload: {
  name: string
  metric: AlertMetric
  operator: AlertOperator
  threshold: number
  window_days: number
  is_active?: boolean
  notification_cooldown_minutes?: number
}): Promise<AlertRule> {
  return fetchApi('/projects/me/alerts', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateAlertRule(
  ruleId: string,
  payload: {
    name?: string
    metric?: AlertMetric
    operator?: AlertOperator
    threshold?: number
    window_days?: number
    is_active?: boolean
    notification_cooldown_minutes?: number
  }
): Promise<AlertRule> {
  return fetchApi(`/projects/me/alerts/${ruleId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteAlertRule(ruleId: string): Promise<void> {
  await fetchApi(`/projects/me/alerts/${ruleId}`, {
    method: 'DELETE',
  })
}

export async function evaluateAlertRules(options?: {
  persist?: boolean
  notify?: boolean
}): Promise<AlertEvaluationResponse> {
  const params = new URLSearchParams()
  if (options?.persist ?? true) {
    params.set('persist', 'true')
  }
  if (options?.notify) {
    params.set('notify', 'true')
  }
  const query = params.toString()
  return fetchApi(`/projects/me/alerts/evaluate${query ? `?${query}` : ''}`)
}

export async function getAlertDestinations(): Promise<AlertDestination[]> {
  return fetchApi('/projects/me/alerts/destinations')
}

export async function createAlertDestination(payload: {
  name: string
  kind?: 'webhook'
  target_url: string
  secret_token?: string
  is_active?: boolean
}): Promise<AlertDestination> {
  return fetchApi('/projects/me/alerts/destinations', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateAlertDestination(
  destinationId: string,
  payload: {
    name?: string
    kind?: 'webhook'
    target_url?: string
    secret_token?: string | null
    is_active?: boolean
  }
): Promise<AlertDestination> {
  return fetchApi(`/projects/me/alerts/destinations/${destinationId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteAlertDestination(destinationId: string): Promise<void> {
  await fetchApi(`/projects/me/alerts/destinations/${destinationId}`, {
    method: 'DELETE',
  })
}

export async function getAlertEvents(params?: {
  event_type?: AlertEventType
  rule_id?: string
  limit?: number
  offset?: number
}): Promise<AlertEvent[]> {
  const searchParams = new URLSearchParams()
  if (params?.event_type) searchParams.set('event_type', params.event_type)
  if (params?.rule_id) searchParams.set('rule_id', params.rule_id)
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit))
  if (params?.offset !== undefined) searchParams.set('offset', String(params.offset))
  return fetchApi(`/projects/me/alerts/events?${searchParams}`)
}

export async function getAlertDeadLetters(params?: {
  replayable_only?: boolean
  limit?: number
  offset?: number
}): Promise<AlertDeadLetter[]> {
  const searchParams = new URLSearchParams()
  if (params?.replayable_only) searchParams.set('replayable_only', 'true')
  if (params?.limit !== undefined) searchParams.set('limit', String(params.limit))
  if (params?.offset !== undefined) searchParams.set('offset', String(params.offset))
  const query = searchParams.toString()
  return fetchApi(`/projects/me/alerts/dead-letter${query ? `?${query}` : ''}`)
}

export async function replayAlertDeadLetter(eventId: string): Promise<AlertReplayResponse> {
  return fetchApi(`/projects/me/alerts/dead-letter/${eventId}/replay`, {
    method: 'POST',
  })
}

export async function getAlertOpsSummary(windowDays = 7): Promise<AlertOpsSummary> {
  const params = new URLSearchParams({ window_days: String(windowDays) })
  return fetchApi(`/projects/me/alerts/ops-summary?${params}`)
}

export async function getAlertOpsTrends(windowDays = 14): Promise<AlertOpsTrends> {
  const params = new URLSearchParams({ window_days: String(windowDays) })
  return fetchApi(`/projects/me/alerts/ops-trends?${params}`)
}

// Curation API

export interface CurationLabel {
  id: string
  trace_id: string
  label: string | null
  quality_score: number | null
  notes: string | null
  exported: boolean
  created_at: string
  updated_at: string | null
}

export interface CuratedTrace {
  trace_id: string
  trace_name: string
  label: string | null
  quality_score: number | null
  notes: string | null
  exported: boolean
  span_count: number
  total_tokens: number | null
  duration_ms: number | null
}

export interface CurationStats {
  total_labeled: number
  exported_count: number
  labels: Record<string, number>
  average_quality_score: number | null
}

export async function getLabel(traceId: string): Promise<CurationLabel | null> {
  try {
    return await fetchApi(`/curation/labels/${traceId}`)
  } catch {
    // 404 means no label exists yet - that's OK
    return null
  }
}

export async function createOrUpdateLabel(data: {
  trace_id: string
  label?: string
  quality_score?: number
  notes?: string
}): Promise<CurationLabel> {
  return fetchApi('/curation/labels', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteLabel(traceId: string): Promise<void> {
  await fetchApi(`/curation/labels/${traceId}`, { method: 'DELETE' })
}

export async function getCuratedTraces(params?: {
  label?: string
  exported?: boolean
  min_score?: number
  limit?: number
  offset?: number
}): Promise<CuratedTrace[]> {
  const searchParams = new URLSearchParams()
  if (params?.label) searchParams.set('label', params.label)
  if (params?.exported !== undefined) searchParams.set('exported', String(params.exported))
  if (params?.min_score !== undefined) searchParams.set('min_score', String(params.min_score))
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.offset) searchParams.set('offset', String(params.offset))
  return fetchApi(`/curation/traces?${searchParams}`)
}

export async function getCurationStats(): Promise<CurationStats> {
  return fetchApi('/curation/stats')
}

export async function exportCuratedTraces(data: {
  trace_ids: string[]
  format?: string
  include_input_output?: boolean
}): Promise<{ format: string; count: number; traces: unknown[] }> {
  return fetchApi('/curation/export', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

// Intelligence API

export interface TraceAnalysis {
  trace_id: string
  analysis: {
    quality_score: number
    labels: string[]
    suggestions: string[]
    summary: string
  }
  cached: boolean
}

export interface SelfAnalysis {
  trace_id: string
  analysis: {
    effectiveness: number
    reasoning_quality: number
    tool_usage: number
    overall_score: number
    strengths: string[]
    weaknesses: string[]
    improvements: string[]
    summary: string
  }
  cached: boolean
}

export interface SyntheticResult {
  trace_id: string
  mode: 'variations' | 'corrections'
  count: number
  results: Array<{ input: string; output: string; metadata?: Record<string, unknown> }>
}

export interface SuggestedCuration {
  trace_id: string
  label: string
  quality_score: number
  notes: string | null
  source_quality_score: number
}

export interface TraceComparisonMetric {
  name: string
  label: string
  trace_a: number
  trace_b: number
  delta: number
  delta_pct: number
  direction: 'improved' | 'regressed' | 'unchanged'
}

export interface TraceComparisonSignal {
  id: string
  title: string
  severity: 'critical' | 'high' | 'medium' | 'low'
  kind: string
  detail: string
  recommendation: string
}

export interface IntelligenceComparison {
  trace_a_id: string
  trace_b_id: string
  summary: {
    status: 'regressed' | 'mixed' | 'improved' | 'neutral'
    regression_score: number
    signal_count: number
  }
  metrics: TraceComparisonMetric[]
  signals: TraceComparisonSignal[]
  top_actions: string[]
}

export interface FailureModeEvidence {
  label: string
  location: string
  weight: number
}

export interface FailureModeEntry {
  mode: 'infra' | 'llm' | 'tool' | 'policy' | 'data'
  score: number
  severity: 'high' | 'medium' | 'low' | 'none'
  evidence_count: number
  evidence: FailureModeEvidence[]
  recommendations: string[]
}

export interface FailureModesResult {
  trace_id: string
  status: 'issue_detected' | 'no_major_failure_signals'
  primary_mode: 'infra' | 'llm' | 'tool' | 'policy' | 'data' | 'none'
  confidence: number
  summary: string
  modes: FailureModeEntry[]
}

export interface RegressionHypothesis {
  id: string
  title: string
  confidence: number
  severity: 'high' | 'medium' | 'low'
  evidence: string[]
  recommendation: string
}

export interface RegressionExplainResult {
  trace_a_id: string
  trace_b_id: string
  compare_summary: {
    status: 'regressed' | 'mixed' | 'improved' | 'neutral'
    regression_score: number
    signal_count: number
  }
  candidate_failure: {
    status: 'issue_detected' | 'no_major_failure_signals'
    primary_mode: 'infra' | 'llm' | 'tool' | 'policy' | 'data' | 'none'
    confidence: number
  }
  candidate_anomaly: {
    status: 'outlier' | 'degraded' | 'watch' | 'normal' | 'insufficient_history'
    anomaly_score: number
    anomaly_count: number
  }
  candidate_safety: {
    risk_level: 'critical' | 'high' | 'medium' | 'low'
    risk_score: number
  }
  explanation: {
    status: 'regression_explained' | 'changes_explained' | 'no_clear_regression_cause'
    hypothesis_count: number
    top_hypothesis_confidence: number
    summary: string
    hypotheses: RegressionHypothesis[]
  }
}

export interface IntelligenceSummaryResult {
  trace_id: string
  baseline_trace_id: string | null
  triage_score: number
  triage_status: 'high_risk' | 'review' | 'stable'
  candidate_failure: {
    status: 'issue_detected' | 'no_major_failure_signals'
    primary_mode: 'infra' | 'llm' | 'tool' | 'policy' | 'data' | 'none'
    confidence: number
  }
  candidate_anomaly: {
    status: 'outlier' | 'degraded' | 'watch' | 'normal' | 'insufficient_history'
    anomaly_score: number
    anomaly_count: number
  }
  candidate_safety: {
    risk_level: 'critical' | 'high' | 'medium' | 'low'
    risk_score: number
  }
  compare_summary: {
    status: 'regressed' | 'mixed' | 'improved' | 'neutral'
    regression_score: number
    signal_count: number
  } | null
  explanation: {
    status: 'regression_explained' | 'changes_explained' | 'no_clear_regression_cause'
    hypothesis_count: number
    top_hypothesis_confidence: number
    summary: string
    hypotheses: RegressionHypothesis[]
  } | null
  generated_at: string
  cached: boolean
  cache_ttl_seconds: number
}

export interface TraceCopilotRootCause {
  title: string
  detail: string
  source: 'regression_explain' | 'failure_modes' | 'anomaly_detect' | 'safety_scan' | 'summary'
  confidence: number
}

export interface TraceCopilotFix {
  id: string
  title: string
  priority: 'high' | 'medium' | 'low'
  rationale: string
  expected_gain: string
  linked_span_ids: string[]
}

export interface TraceCopilotSpanReference {
  span_id: string
  span_name: string
  span_type: string
  status: string
  duration_ms: number
  tokens: number
  reason: string
}

export interface TraceCopilotResult {
  trace_id: string
  baseline_trace_id: string | null
  triage_score: number
  triage_status: 'high_risk' | 'review' | 'stable'
  confidence: number
  summary: string
  root_cause: TraceCopilotRootCause
  next_fixes: TraceCopilotFix[]
  span_references: TraceCopilotSpanReference[]
  candidate_failure: IntelligenceSummaryResult['candidate_failure']
  candidate_anomaly: IntelligenceSummaryResult['candidate_anomaly']
  candidate_safety: IntelligenceSummaryResult['candidate_safety']
  compare_summary: IntelligenceSummaryResult['compare_summary']
  generated_at: string
  cached: boolean
  cache_ttl_seconds: number
}

export async function analyzeTrace(traceId: string): Promise<TraceAnalysis> {
  return fetchApi('/intelligence/analyze', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId }),
  })
}

export async function compareTraces(
  traceAId: string,
  traceBId: string
): Promise<IntelligenceComparison> {
  return fetchApi('/intelligence/compare', {
    method: 'POST',
    body: JSON.stringify({ trace_a_id: traceAId, trace_b_id: traceBId }),
  })
}

export async function getFailureModes(traceId: string): Promise<FailureModesResult> {
  return fetchApi('/intelligence/failure-modes', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId }),
  })
}

export async function getRegressionExplain(
  traceAId: string,
  traceBId: string,
  historyLimit = 20
): Promise<RegressionExplainResult> {
  return fetchApi('/intelligence/regression-explain', {
    method: 'POST',
    body: JSON.stringify({
      trace_a_id: traceAId,
      trace_b_id: traceBId,
      history_limit: historyLimit,
    }),
  })
}

export async function getIntelligenceSummary(
  traceId: string,
  options?: {
    baselineTraceId?: string
    historyLimit?: number
    refreshCache?: boolean
  }
): Promise<IntelligenceSummaryResult> {
  return fetchApi('/intelligence/summary', {
    method: 'POST',
    body: JSON.stringify({
      trace_id: traceId,
      baseline_trace_id: options?.baselineTraceId,
      history_limit: options?.historyLimit ?? 20,
      refresh_cache: options?.refreshCache ?? false,
    }),
  })
}

export async function getTraceCopilot(
  traceId: string,
  options?: {
    baselineTraceId?: string
    historyLimit?: number
    refreshCache?: boolean
  }
): Promise<TraceCopilotResult> {
  return fetchApi('/intelligence/copilot', {
    method: 'POST',
    body: JSON.stringify({
      trace_id: traceId,
      baseline_trace_id: options?.baselineTraceId,
      history_limit: options?.historyLimit ?? 20,
      refresh_cache: options?.refreshCache ?? false,
    }),
  })
}

export async function selfAnalyzeTrace(traceId: string): Promise<SelfAnalysis> {
  return fetchApi('/intelligence/self-analyze', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId }),
  })
}

export async function suggestCuration(traceId: string): Promise<SuggestedCuration> {
  return fetchApi('/intelligence/suggest-curation', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId }),
  })
}

export async function generateSynthetic(
  traceId: string,
  mode: 'variations' | 'corrections' = 'variations',
  n = 3
): Promise<SyntheticResult> {
  const data = await fetchApi<{
    trace_id?: string
    mode?: 'variations' | 'corrections'
    type?: 'variations' | 'corrections'
    count?: number
    results?: Array<{ input: string; output: string; metadata?: Record<string, unknown> }>
    variations?: Array<{ input: string; output: string; metadata?: Record<string, unknown> }>
  }>('/intelligence/generate-synthetic', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId, mode, n }),
  })

  const normalizedResults = data.results ?? data.variations ?? []

  return {
    trace_id: data.trace_id ?? traceId,
    mode: data.mode ?? data.type ?? mode,
    count: data.count ?? normalizedResults.length,
    results: normalizedResults,
  }
}

// Demo/System Status API

export interface HealthDetailedResponse {
  status: 'healthy' | 'degraded'
  timestamp: string
  version: string
  checks: {
    database?: { status: 'healthy' | 'unhealthy' }
    redis?: { status: 'healthy' | 'unhealthy' }
    intelligence?: { status: 'configured' | 'not_configured' }
  }
}

export interface DemoPreflightResponse {
  ready: boolean
  can_seed: boolean
  checks: Array<{
    component: 'database' | 'redis' | 'intelligence' | string
    status: 'ok' | 'warning' | 'error'
    required: boolean
    message: string
  }>
  blockers: string[]
  recommendations: string[]
  fix_commands: string[]
}

export interface StoryModeLatestResponse {
  found: boolean
  scenario: 'agent_regression' | string | null
  seeded: number
  trace_ids: string[]
  recommended_flow: {
    compare: string
    trace_baseline: string
    trace_candidate: string
    trace_recovery: string
    curation: string
  }
}

export interface IntelligenceStatusResponse {
  nvidia_api_key_configured: boolean
  model: string
  base_url: string
  llm_timeout_seconds?: number
  llm_max_tokens?: number
}

export interface StoryModeSeedResponse {
  scenario: 'agent_regression'
  seeded: number
  trace_ids: string[]
  recommended_flow: {
    compare: string
    trace_baseline: string
    trace_candidate: string
    trace_recovery: string
    curation: string
  }
}

export async function getDetailedHealth(): Promise<HealthDetailedResponse> {
  return fetchRootApi('/health/detailed')
}

export async function getDemoPreflight(): Promise<DemoPreflightResponse> {
  return fetchApi('/demo/preflight')
}

export async function getLatestStoryMode(): Promise<StoryModeLatestResponse> {
  return fetchApi('/demo/story-mode/latest')
}

export async function getIntelligenceStatus(): Promise<IntelligenceStatusResponse> {
  return fetchApi('/intelligence/status')
}

export async function seedStoryMode(
  scenario: 'agent_regression' = 'agent_regression'
): Promise<StoryModeSeedResponse> {
  return fetchApi('/demo/story-mode', {
    method: 'POST',
    body: JSON.stringify({ scenario }),
  })
}
