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

export async function getTraces(
  limit = 20,
  offset = 0,
  status?: string
): Promise<TraceListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (status) {
    params.set('status', status)
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
  return fetchApi(`/curation/labels/${traceId}`)
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
