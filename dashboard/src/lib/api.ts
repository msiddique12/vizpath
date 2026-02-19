import { TraceListResponse, TraceDetailResponse, Span } from './types'

const API_BASE = '/api/v1'

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return response.json()
}

async function fetchRootApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(endpoint, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return response.json()
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

export async function analyzeTrace(traceId: string): Promise<TraceAnalysis> {
  return fetchApi('/intelligence/analyze', {
    method: 'POST',
    body: JSON.stringify({ trace_id: traceId }),
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

export interface IntelligenceStatusResponse {
  nvidia_api_key_configured: boolean
  model: string
  base_url: string
}

export async function getDetailedHealth(): Promise<HealthDetailedResponse> {
  return fetchRootApi('/health/detailed')
}

export async function getIntelligenceStatus(): Promise<IntelligenceStatusResponse> {
  return fetchApi('/intelligence/status')
}
