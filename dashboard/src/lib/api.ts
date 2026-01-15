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
