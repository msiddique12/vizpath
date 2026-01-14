export type SpanType = 'llm' | 'tool' | 'agent' | 'retrieval' | 'chain' | 'custom'
export type SpanStatus = 'running' | 'success' | 'error'

export interface Trace {
  id: string
  name: string
  status: SpanStatus
  start_time: string
  end_time: string | null
  duration_ms: number | null
  metadata: Record<string, unknown>
  total_tokens: number | null
  total_cost: number | null
  span_count: number
  error_count: number
}

export interface Span {
  id: string
  trace_id: string
  parent_id: string | null
  name: string
  span_type: SpanType
  status: SpanStatus
  start_time: string
  end_time: string | null
  duration_ms: number | null
  attributes: Record<string, unknown>
  input: unknown
  output: unknown
  error: string | null
  tokens: number | null
  cost: number | null
}

export interface TraceListResponse {
  traces: Trace[]
  total: number
  limit: number
  offset: number
}

export interface TraceDetailResponse {
  trace: Trace
  spans: Span[]
}
