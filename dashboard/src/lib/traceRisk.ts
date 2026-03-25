import { Trace } from './types'

export type TraceRiskLevel = 'high' | 'medium'

export interface TraceRiskFlag {
  key: string
  label: string
  level: TraceRiskLevel
}

export function getTraceRiskFlags(trace: Trace): TraceRiskFlag[] {
  const flags: TraceRiskFlag[] = []
  const durationMs = trace.duration_ms ?? 0
  const tokens = trace.total_tokens ?? 0
  const spanCount = trace.span_count ?? 0
  const errors = trace.error_count ?? 0
  const metadataText = JSON.stringify(trace.metadata || {}).toLowerCase()

  if (
    metadataText.includes('infinite') ||
    metadataText.includes('loop') ||
    metadataText.includes('retrying') ||
    metadataText.includes('retry')
  ) {
    flags.push({ key: 'loop-risk', label: 'Loop risk', level: 'high' })
  }

  if (durationMs >= 45000) {
    flags.push({ key: 'runtime-risk', label: 'Long runtime', level: 'high' })
  }

  if (tokens >= 12000) {
    flags.push({ key: 'token-risk', label: 'Token pressure', level: 'medium' })
  }

  if (spanCount >= 40 || (spanCount >= 20 && errors >= 2)) {
    flags.push({ key: 'tool-churn-risk', label: 'Tool churn', level: 'medium' })
  }

  return flags.slice(0, 3)
}
